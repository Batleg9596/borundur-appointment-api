# -*- coding: utf-8 -*-
import os
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, request, jsonify, render_template_string, redirect, session
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

APP=Flask(__name__)
APP.secret_key=os.environ.get('SECRET_KEY','change-me')
url=os.environ.get('DATABASE_URL','sqlite:///appointments_local.db')
if url.startswith('postgres://'): url=url.replace('postgres://','postgresql+psycopg://',1)
elif url.startswith('postgresql://') and '+psycopg' not in url: url=url.replace('postgresql://','postgresql+psycopg://',1)
DB=create_engine(url,pool_pre_ping=True,future=True)
API_KEY=os.environ.get('APPOINTMENT_API_KEY','CHANGE_THIS_SECRET_KEY')
ADMIN_USER=os.environ.get('ADMIN_USERNAME','admin')
ADMIN_PASS=os.environ.get('ADMIN_PASSWORD','borundur_admin_2026')

def allq(sql,p=None):
    with DB.begin() as c:return [dict(r._mapping) for r in c.execute(text(sql),p or {}).fetchall()]
def run(sql,p=None):
    with DB.begin() as c:return c.execute(text(sql),p or {})

def init():
    with DB.begin() as c:
        c.execute(text('''CREATE TABLE IF NOT EXISTS appointments(
        id BIGSERIAL PRIMARY KEY,full_name TEXT NOT NULL,phone TEXT NOT NULL,register_no TEXT NOT NULL,
        service TEXT,appointment_date DATE NOT NULL,appointment_time VARCHAR(5) NOT NULL,doctor TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Шинэ',source TEXT NOT NULL DEFAULT 'Web',synced BOOLEAN NOT NULL DEFAULT FALSE,
        note TEXT,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(appointment_date,appointment_time,doctor))'''))
        c.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT FALSE"))
        c.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS delete_synced BOOLEAN NOT NULL DEFAULT FALSE"))
        c.execute(text('CREATE TABLE IF NOT EXISTS doctors(id BIGSERIAL PRIMARY KEY,name TEXT UNIQUE NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE)'))
        c.execute(text('CREATE TABLE IF NOT EXISTS services(id BIGSERIAL PRIMARY KEY,name TEXT UNIQUE NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE)'))
        c.execute(text('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)'))
        c.execute(text("INSERT INTO doctors(name,active) VALUES('Т.Дармагад',TRUE) ON CONFLICT(name) DO NOTHING"))
        for s in ['Эмчийн үзлэг','Зүү төөнүүр','Бариа засал','Бумба','Хануур','Бусад']:
            c.execute(text('INSERT INTO services(name,active) VALUES(:n,TRUE) ON CONFLICT(name) DO NOTHING'),{'n':s})
        for k,v in {'work_days':'0,1,2,3,4,5','work_start':'10:00','work_end':'16:00','slot_minutes':'60'}.items():
            c.execute(text('INSERT INTO settings(key,value) VALUES(:k,:v) ON CONFLICT(key) DO NOTHING'),{'k':k,'v':v})

def settings():return {x['key']:x['value'] for x in allq('SELECT key,value FROM settings')}
def slots():
    s=settings(); a=datetime.strptime(s['work_start'],'%H:%M'); b=datetime.strptime(s['work_end'],'%H:%M'); step=max(15,int(s['slot_minutes'])); out=[]
    while a<b: out.append(a.strftime('%H:%M')); a+=timedelta(minutes=step)
    return out
def valid(d):
    try:x=datetime.strptime(d,'%Y-%m-%d').date()
    except:return False,'Огнооны формат буруу.'
    if x<date.today():return False,'Өнгөрсөн өдөр сонгох боломжгүй.'
    if x.weekday() not in {int(i) for i in settings()['work_days'].split(',') if i}:return False,'Сонгосон өдөр амарна.'
    return True,''
def available(d,doctor):
    if not valid(d)[0]:return []
    taken={x['appointment_time'] for x in allq("SELECT appointment_time FROM appointments WHERE appointment_date=:d AND doctor=:doc AND status!='Цуцлагдсан' AND deleted=FALSE",{'d':d,'doc':doctor})}
    return [x for x in slots() if x not in taken]
def create(data):
    for k in ['full_name','phone','register_no','doctor','appointment_date','appointment_time']:
        if not str(data.get(k,'')).strip():return False,'Мэдээллээ бүрэн бөглөнө үү.'
    ok,msg=valid(data['appointment_date'])
    if not ok:return False,msg
    if data['appointment_time'] not in available(data['appointment_date'],data['doctor']):return False,'Сонгосон цаг захиалгатай байна.'
    phone=''.join(c for c in str(data['phone']) if c.isdigit())
    if len(phone)<8:return False,'Утасны дугаар буруу.'
    try:
        with DB.begin() as c:
            r=c.execute(text('''INSERT INTO appointments(full_name,phone,register_no,service,appointment_date,appointment_time,doctor,status,source,synced,note)
            VALUES(:n,:p,:r,:s,:d,:t,:doc,'Шинэ',:src,FALSE,:note) RETURNING id'''),
            {'n':data['full_name'].strip(),'p':phone,'r':data['register_no'].strip().upper(),'s':data.get('service',''),'d':data['appointment_date'],'t':data['appointment_time'],'doc':data['doctor'],'src':data.get('source','Web'),'note':data.get('note','')}).fetchone()
            return True,r[0]
    except IntegrityError:return False,'Энэ цагийг өөр хүн түрүүлж захиалсан байна.'

def guard(f):
    @wraps(f)
    def w(*a,**k):return f(*a,**k) if session.get('admin') else redirect('/admin/login')
    return w

STYLE='''<style>*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Arial;background:#eef5f2;color:#18372d}.w{max-width:1180px;margin:auto;padding:18px}.h{background:linear-gradient(135deg,#0d503d,#176f55);color:#fff;border-radius:18px;padding:22px}.c{background:#fff;border-radius:16px;padding:18px;margin-top:16px;box-shadow:0 10px 28px #204c3a14}.g{display:grid;grid-template-columns:1fr 1fr;gap:14px}.f{grid-column:1/-1}label{display:block;font-weight:700;margin-bottom:6px}input,select,textarea{width:100%;padding:11px;border:1px solid #d9e5df;border-radius:10px;font-size:15px}button,a.b{display:inline-block;padding:10px 14px;border:0;border-radius:10px;background:#176f55;color:#fff;font-weight:700;text-decoration:none}nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}nav a{background:#ffffff22;padding:9px 12px;border-radius:9px}table{width:100%;border-collapse:collapse}th,td{padding:9px;border-bottom:1px solid #e7eee9;text-align:left;white-space:nowrap}.scroll{overflow:auto}.red{background:#b63d3d!important}.inline{display:inline}@media(max-width:700px){.g{grid-template-columns:1fr}.f{grid-column:auto}}</style>'''
BOOK='''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'''+STYLE+'''<div class=w><div class=h><h1>Цахим цаг захиалга</h1><p>“Бор-Өндөр” УБҮ-ийн ҮЭ-ийн дэргэдэх уламжлалт эмнэлэг</p></div><div class=c>{% if e %}<p style="color:#b00">{{e}}</p>{% endif %}<form class=g method=post action=/book><div><label>Овог нэр</label><input name=full_name required></div><div><label>Утас</label><input name=phone required></div><div><label>Регистр</label><input name=register_no required></div><div><label>Эмч</label><select name=doctor id=doctor>{% for x in doctors %}<option>{{x.name}}</option>{% endfor %}</select></div><div><label>Үйлчилгээ</label><select name=service>{% for x in services %}<option>{{x.name}}</option>{% endfor %}</select></div><div><label>Огноо</label><input type=date name=appointment_date id=date min={{today}} required></div><div class=f><label>Сул цаг</label><select name=appointment_time id=time required><option value="">Огноо сонгоно уу</option></select></div><div class=f><label>Тайлбар</label><textarea name=note></textarea></div><div class=f><button>Цаг захиалах</button></div></form></div></div><script>async function L(){if(!date.value)return;let r=await fetch('/api/web/available-times?date='+date.value+'&doctor='+encodeURIComponent(doctor.value));let j=await r.json();time.innerHTML=j.ok&&j.times.length?'<option value="">Сул цагаа сонгоно уу</option>'+j.times.map(x=>'<option>'+x+'</option>').join(''):'<option value="">Сул цаг байхгүй</option>'}date.onchange=L;doctor.onchange=L</script>'''
TOP='''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">'''+STYLE+'''<div class=w><div class=h><h2>Цаг захиалгын админ</h2><nav><a href=/admin>Захиалга</a><a href=/admin/doctors>Эмч нар</a><a href=/admin/services>Үйлчилгээ</a><a href=/admin/settings>Ажлын хуваарь</a><a href=/admin/logout>Гарах</a></nav></div>'''

@APP.get('/')
def root():return redirect('/booking')
@APP.get('/booking')
def booking():return render_template_string(BOOK,doctors=allq('SELECT * FROM doctors WHERE active=TRUE ORDER BY name'),services=allq('SELECT * FROM services WHERE active=TRUE ORDER BY name'),today=date.today().isoformat(),e='')
@APP.post('/book')
def book():
    d=request.form.to_dict();d['source']='Web';ok,r=create(d)
    if not ok:return render_template_string(BOOK,doctors=allq('SELECT * FROM doctors WHERE active=TRUE ORDER BY name'),services=allq('SELECT * FROM services WHERE active=TRUE ORDER BY name'),today=date.today().isoformat(),e=r),400
    return '<meta charset=utf-8><h1>✅ Амжилттай захиалагдлаа</h1><p>Захиалгын дугаар: %s</p><a href=/booking>Буцах</a>'%r
@APP.get('/api/web/available-times')
def wt():
    d=request.args.get('date','');doc=request.args.get('doctor','');ok,msg=valid(d)
    return (jsonify({'ok':ok,'message':msg,'times':available(d,doc)}),200 if ok else 400)
@APP.route('/admin/login',methods=['GET','POST'])
def login():
    if request.method=='POST' and request.form.get('username')==ADMIN_USER and request.form.get('password')==ADMIN_PASS:session['admin']=1;return redirect('/admin')
    return '<meta charset=utf-8>'+STYLE+'<div class=w style="max-width:430px"><div class=c><h2>Админ нэвтрэх</h2><form method=post><input name=username placeholder="Нэвтрэх нэр"><br><br><input type=password name=password placeholder="Нууц үг"><br><br><button>Нэвтрэх</button></form></div></div>'
@APP.get('/admin/logout')
def logout():session.clear();return redirect('/admin/login')
@APP.get('/admin')
@guard
def admin():
    d=request.args.get('date',date.today().isoformat());rows=allq('SELECT * FROM appointments WHERE appointment_date=:d AND deleted=FALSE ORDER BY appointment_time',{'d':d})
    body=TOP+'<div class=c><form><input type=date name=date value="%s"><button>Харах</button></form></div><div class="c scroll"><table><tr><th>ID</th><th>Цаг</th><th>Эмч</th><th>Нэр</th><th>Утас</th><th>Регистр</th><th>Үйлчилгээ</th><th>Төлөв</th><th>Үйлдэл</th></tr>'%d
    for x in rows:body+=f'''<tr><td>{x['id']}</td><td>{x['appointment_time']}</td><td>{x['doctor']}</td><td>{x['full_name']}</td><td>{x['phone']}</td><td>{x['register_no']}</td><td>{x['service'] or ''}</td><td>{x['status']}</td><td><form class=inline method=post action=/admin/status/{x['id']}><input type=hidden name=date value={d}><select name=status><option>Шинэ</option><option>Баталгаажсан</option><option>Ирсэн</option><option>Дууссан</option><option>Цуцлагдсан</option></select><button>Солих</button></form> <form class=inline method=post action=/admin/delete/{x['id']} onsubmit="return confirm('MIS дээр мөн устгах уу?')"><input type=hidden name=date value={d}><button class=red>Устгах</button></form></td></tr>'''
    return body+'</table></div></div>'
@APP.post('/admin/status/<int:i>')
@guard
def ast(i):run('UPDATE appointments SET status=:s WHERE id=:i',{'s':request.form['status'],'i':i});return redirect('/admin?date='+request.form['date'])
@APP.post('/admin/delete/<int:i>')
@guard
def admin_delete(i):
    run('UPDATE appointments SET deleted=TRUE, delete_synced=FALSE WHERE id=:i',{'i':i})
    return redirect('/admin?date='+request.form.get('date',date.today().isoformat()))
@APP.route('/admin/doctors',methods=['GET','POST'])
@guard
def doctors():
    if request.method=='POST':run('INSERT INTO doctors(name,active) VALUES(:n,TRUE) ON CONFLICT(name) DO NOTHING',{'n':request.form['name']})
    b=TOP+'<div class=c><form method=post><input name=name placeholder="Эмчийн нэр"><button>Нэмэх</button></form></div><div class=c><table><tr><th>Нэр</th><th>Төлөв</th><th>Үйлдэл</th></tr>'
    for x in allq('SELECT * FROM doctors ORDER BY name'):b+=f"<tr><td>{x['name']}</td><td>{'Идэвхтэй' if x['active'] else 'Идэвхгүй'}</td><td><form method=post action=/admin/doctors/{x['id']}/toggle><button>Солих</button></form></td></tr>"
    return b+'</table></div></div>'
@APP.post('/admin/doctors/<int:i>/toggle')
@guard
def dt(i):run('UPDATE doctors SET active=NOT active WHERE id=:i',{'i':i});return redirect('/admin/doctors')
@APP.route('/admin/services',methods=['GET','POST'])
@guard
def services():
    if request.method=='POST':run('INSERT INTO services(name,active) VALUES(:n,TRUE) ON CONFLICT(name) DO NOTHING',{'n':request.form['name']})
    b=TOP+'<div class=c><form method=post><input name=name placeholder="Үйлчилгээ"><button>Нэмэх</button></form></div><div class=c><table><tr><th>Нэр</th><th>Төлөв</th><th>Үйлдэл</th></tr>'
    for x in allq('SELECT * FROM services ORDER BY name'):b+=f"<tr><td>{x['name']}</td><td>{'Идэвхтэй' if x['active'] else 'Идэвхгүй'}</td><td><form method=post action=/admin/services/{x['id']}/toggle><button>Солих</button></form></td></tr>"
    return b+'</table></div></div>'
@APP.post('/admin/services/<int:i>/toggle')
@guard
def st(i):run('UPDATE services SET active=NOT active WHERE id=:i',{'i':i});return redirect('/admin/services')
@APP.route('/admin/settings',methods=['GET','POST'])
@guard
def aset():
    if request.method=='POST':
        vals={'work_start':request.form['work_start'],'work_end':request.form['work_end'],'slot_minutes':request.form['slot_minutes'],'work_days':','.join(request.form.getlist('work_days'))}
        for k,v in vals.items():run('INSERT INTO settings(key,value) VALUES(:k,:v) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value',{'k':k,'v':v})
    s=settings();sel={int(x) for x in s['work_days'].split(',') if x};days=['Даваа','Мягмар','Лхагва','Пүрэв','Баасан','Бямба','Ням']
    checks=''.join(f'<label style="display:inline"><input style="width:auto" type=checkbox name=work_days value={i} {"checked" if i in sel else ""}> {n}</label> ' for i,n in enumerate(days))
    return TOP+f'''<div class=c><form method=post><label>Эхлэх</label><input type=time name=work_start value={s['work_start']}><label>Дуусах</label><input type=time name=work_end value={s['work_end']}><label>Үзлэгийн минут</label><input type=number name=slot_minutes value={s['slot_minutes']}><p>{checks}</p><button>Хадгалах</button></form></div></div>'''
@APP.get('/health')
def health():return jsonify({'ok':True,'database':'postgresql' if url.startswith('postgresql') else 'sqlite-local','time':datetime.now().isoformat(timespec='seconds')})
@APP.get('/api/appointments/pending')
def pending():
    if request.headers.get('X-API-Key')!=API_KEY:return jsonify({'ok':False,'error':'unauthorized'}),401
    return jsonify({'ok':True,'appointments':allq("SELECT id,full_name,phone,register_no,service,CAST(appointment_date AS TEXT) appointment_date,appointment_time,doctor,status,source,note FROM appointments WHERE synced=FALSE AND deleted=FALSE ORDER BY id")})
@APP.post('/api/appointments/mark-synced')
def synced():
    if request.headers.get('X-API-Key')!=API_KEY:return jsonify({'ok':False,'error':'unauthorized'}),401
    ids=[int(x) for x in (request.get_json(silent=True) or {}).get('ids',[]) if str(x).isdigit()]
    n=0
    for i in ids:n+=run('UPDATE appointments SET synced=TRUE WHERE id=:i',{'i':i}).rowcount
    return jsonify({'ok':True,'updated':n})

@APP.get('/api/appointments/deletions')
def deletions():
    if request.headers.get('X-API-Key')!=API_KEY:return jsonify({'ok':False,'error':'unauthorized'}),401
    ids=[x['id'] for x in allq('SELECT id FROM appointments WHERE deleted=TRUE AND delete_synced=FALSE ORDER BY id')]
    return jsonify({'ok':True,'ids':ids})

@APP.post('/api/appointments/mark-deletions-synced')
def mark_deletions_synced():
    if request.headers.get('X-API-Key')!=API_KEY:return jsonify({'ok':False,'error':'unauthorized'}),401
    ids=[int(x) for x in (request.get_json(silent=True) or {}).get('ids',[]) if str(x).isdigit()]
    n=0
    for i in ids:n+=run('UPDATE appointments SET delete_synced=TRUE WHERE id=:i AND deleted=TRUE',{'i':i}).rowcount
    return jsonify({'ok':True,'updated':n})

@APP.post('/api/appointments/<int:i>/delete')
def api_delete(i):
    if request.headers.get('X-API-Key')!=API_KEY:return jsonify({'ok':False,'error':'unauthorized'}),401
    n=run('UPDATE appointments SET deleted=TRUE, delete_synced=FALSE WHERE id=:i',{'i':i}).rowcount
    return jsonify({'ok':bool(n),'updated':n})

init()
if __name__=='__main__':APP.run(host='0.0.0.0',port=int(os.environ.get('PORT','8000')))
