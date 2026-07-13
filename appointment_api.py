# -*- coding: utf-8 -*-
import os, sqlite3
from datetime import datetime, date
from flask import Flask, jsonify, request, render_template_string, redirect

APP = Flask(__name__)
DB_FILE = os.environ.get('APPOINTMENT_DB', 'appointments_server.db')
API_KEY = os.environ.get('APPOINTMENT_API_KEY', 'CHANGE_THIS_SECRET_KEY')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'borundur_admin_2026')
META_VERIFY_TOKEN = os.environ.get('META_VERIFY_TOKEN', 'borundur_verify_2026')
META_PAGE_ACCESS_TOKEN = os.environ.get('META_PAGE_ACCESS_TOKEN', '')
SLOTS = ['10:00','11:00','12:00','13:00','14:00','15:00']
WORK_DAYS = {0,1,2,3,4,5}

def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con=db(); cur=con.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS appointments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        phone TEXT,
        register_no TEXT,
        service TEXT,
        appointment_date TEXT NOT NULL,
        appointment_time TEXT NOT NULL,
        doctor TEXT,
        status TEXT DEFAULT 'Шинэ',
        source TEXT DEFAULT 'Web',
        synced INTEGER DEFAULT 0,
        note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    cols={x['name'] for x in cur.execute('PRAGMA table_info(appointments)').fetchall()}
    if 'register_no' not in cols:
        cur.execute('ALTER TABLE appointments ADD COLUMN register_no TEXT')
    cur.execute('''CREATE TABLE IF NOT EXISTS doctors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        active INTEGER DEFAULT 1
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS services(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        active INTEGER DEFAULT 1
    )''')
    cur.execute("INSERT OR IGNORE INTO doctors(name,active) VALUES('Т.Дармагад',1)")
    for s in ['Эмчийн үзлэг','Зүү төөнүүр','Бариа засал','Бумба','Хануур','Бусад']:
        cur.execute('INSERT OR IGNORE INTO services(name,active) VALUES(?,1)',(s,))
    con.commit(); con.close()

def authorized():
    return request.headers.get('X-API-Key','') == API_KEY

@APP.before_request
def auth():
    public={'/','/booking','/book','/health','/privacy','/delete-data','/webhook','/api/web/available-times'}
    if request.path in public or request.path.startswith('/admin'):
        return None
    if not authorized():
        return jsonify({'ok':False,'error':'unauthorized'}),401

def valid_date(v):
    try:
        d=datetime.strptime(v,'%Y-%m-%d').date()
    except ValueError:
        return False,'Огноо буруу байна.'
    if d < date.today():
        return False,'Өнгөрсөн өдөр сонгох боломжгүй.'
    if d.weekday() not in WORK_DAYS:
        return False,'Ням гарагт амарна.'
    return True,''

def available_times(d,doctor):
    ok,_=valid_date(d)
    if not ok:
        return []
    con=db()
    taken={x['appointment_time'] for x in con.execute(
        """SELECT appointment_time FROM appointments
           WHERE appointment_date=? AND COALESCE(doctor,'')=?
           AND status!='Цуцлагдсан'""",(d,doctor)).fetchall()}
    con.close()
    return [x for x in SLOTS if x not in taken]

def create_appt(data):
    for k in ['full_name','phone','register_no','doctor','appointment_date','appointment_time']:
        if not str(data.get(k,'')).strip():
            return False,'Мэдээллээ бүрэн бөглөнө үү.'
    ok,msg=valid_date(data['appointment_date'])
    if not ok:
        return False,msg
    if data['appointment_time'] not in available_times(data['appointment_date'],data['doctor']):
        return False,'Сонгосон цаг захиалгатай байна.'
    phone=''.join(c for c in data['phone'] if c.isdigit())
    if len(phone)<8:
        return False,'Утасны дугаар буруу байна.'
    con=db(); cur=con.cursor()
    cur.execute('''INSERT INTO appointments(
        full_name,phone,register_no,service,appointment_date,appointment_time,doctor,status,source,note
    ) VALUES(?,?,?,?,?,?,?,?,?,?)''',(
        data['full_name'].strip(),phone,data['register_no'].strip().upper(),
        data.get('service','').strip(),data['appointment_date'],data['appointment_time'],
        data['doctor'].strip(),'Шинэ',data.get('source','Web'),data.get('note','').strip()
    ))
    aid=cur.lastrowid; con.commit(); con.close()
    return True,aid

PAGE = '''<!doctype html><html lang="mn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Бор-Өндөр эмнэлэг - Цаг захиалга</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Arial;background:#eef6f2;color:#17372d}
.wrap{max-width:900px;margin:auto;padding:16px}.hero{padding:26px;border-radius:22px;background:linear-gradient(135deg,#0e5f47,#17805e);color:#fff}
.card{background:#fff;margin-top:18px;padding:22px;border-radius:20px;box-shadow:0 12px 32px #153b2c18}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.full{grid-column:1/-1}
label{display:block;font-weight:700;margin-bottom:6px}input,select,textarea{width:100%;padding:13px;border:1px solid #d3e0da;border-radius:11px;font-size:16px}
button{width:100%;padding:14px;border:0;border-radius:12px;background:#167a5b;color:#fff;font-size:17px;font-weight:800}.err{background:#fff0f0;color:#9d2828;padding:12px;border-radius:10px;margin-bottom:14px}
.note{font-size:13px;color:#667b73;margin-top:7px}@media(max-width:650px){.grid{grid-template-columns:1fr}.full{grid-column:auto}}
</style></head><body><div class="wrap">
<div class="hero"><h1>Цахим цаг захиалга</h1><p>“Бор-Өндөр” УБҮ-ийн ҮЭ-ийн дэргэдэх уламжлалт эмнэлэг</p></div>
<div class="card">{% if error %}<div class="err">{{error}}</div>{% endif %}
<form class="grid" method="post" action="/book">
<div><label>Овог нэр *</label><input name="full_name" required></div>
<div><label>Утас *</label><input name="phone" required inputmode="numeric"></div>
<div><label>Регистр *</label><input name="register_no" required></div>
<div><label>Эмч *</label><select name="doctor" id="doctor">{% for d in doctors %}<option>{{d}}</option>{% endfor %}</select></div>
<div><label>Үйлчилгээ</label><select name="service">{% for s in services %}<option>{{s}}</option>{% endfor %}</select></div>
<div><label>Огноо *</label><input type="date" name="appointment_date" id="date" min="{{today}}" required></div>
<div class="full"><label>Сул цаг *</label><select name="appointment_time" id="time" required><option value="">Огноо сонгоно уу</option></select>
<div class="note">Даваа-Бямба, 10:00-16:00. Нэг үзлэг 60 минут.</div></div>
<div class="full"><label>Нэмэлт тайлбар</label><textarea name="note" rows="3"></textarea></div>
<div class="full"><button>Цаг захиалах</button></div></form></div></div>
<script>
async function loadTimes(){let d=date.value,doc=doctor.value;if(!d)return;
time.innerHTML='<option>Уншиж байна...</option>';let r=await fetch('/api/web/available-times?date='+encodeURIComponent(d)+'&doctor='+encodeURIComponent(doc));
let j=await r.json();time.innerHTML=j.ok&&j.times.length?'<option value="">Сул цагаа сонгоно уу</option>'+j.times.map(x=>'<option>'+x+'</option>').join(''):'<option value="">Сул цаг байхгүй</option>'}
date.onchange=loadTimes;doctor.onchange=loadTimes;
</script></body></html>'''

SUCCESS = '''<!doctype html><html lang="mn"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<body style="font-family:Segoe UI,Arial;background:#eef6f2"><div style="max-width:600px;margin:8vh auto;background:white;padding:28px;border-radius:20px">
<h1>✅ Амжилттай захиалагдлаа</h1><p><b>Захиалгын дугаар:</b> {{id}}</p><p><b>Эмч:</b> {{doctor}}</p>
<p><b>Огноо:</b> {{d}}</p><p><b>Цаг:</b> {{t}}</p><p>Эмнэлгийн ажилтан баталгаажуулж холбогдоно.</p>
<a href="/booking">Өөр цаг захиалах</a></div></body></html>'''

@APP.get('/')
def root():
    return redirect('/booking')

@APP.get('/booking')
def booking():
    con=db()
    doctors=[x['name'] for x in con.execute('SELECT name FROM doctors WHERE active=1 ORDER BY name')]
    services=[x['name'] for x in con.execute('SELECT name FROM services WHERE active=1 ORDER BY name')]
    con.close()
    return render_template_string(PAGE,doctors=doctors,services=services,today=date.today().isoformat(),error='')

@APP.post('/book')
def book():
    data=request.form.to_dict(); data['source']='Web'
    ok,res=create_appt(data)
    if not ok:
        con=db()
        doctors=[x['name'] for x in con.execute('SELECT name FROM doctors WHERE active=1 ORDER BY name')]
        services=[x['name'] for x in con.execute('SELECT name FROM services WHERE active=1 ORDER BY name')]
        con.close()
        return render_template_string(PAGE,doctors=doctors,services=services,today=date.today().isoformat(),error=res),400
    return render_template_string(SUCCESS,id=res,doctor=data['doctor'],d=data['appointment_date'],t=data['appointment_time'])

@APP.get('/api/web/available-times')
def web_times():
    d=request.args.get('date',''); doctor=request.args.get('doctor','')
    ok,msg=valid_date(d)
    if not ok:
        return jsonify({'ok':False,'message':msg,'times':[]}),400
    return jsonify({'ok':True,'times':available_times(d,doctor)})

@APP.get('/admin')
def admin():
    pwd=request.args.get('password',''); selected=request.args.get('date',date.today().isoformat())
    if not pwd:
        return '<form><input type="password" name="password" placeholder="Админ нууц үг"><button>Нэвтрэх</button></form>'
    if pwd!=ADMIN_PASSWORD:
        return 'Нууц үг буруу',403
    con=db(); rows=[dict(x) for x in con.execute('SELECT * FROM appointments WHERE appointment_date=? ORDER BY appointment_time',(selected,))]
    con.close()
    body='<h2>Цаг захиалга</h2><form><input type=password name=password value="%s"><input type=date name=date value="%s"><button>Харах</button></form><table border=1 cellpadding=7><tr><th>ID</th><th>Цаг</th><th>Эмч</th><th>Нэр</th><th>Утас</th><th>Регистр</th><th>Үйлчилгээ</th><th>Төлөв</th></tr>'%(pwd,selected)
    for x in rows:
        body+='<tr><td>{id}</td><td>{appointment_time}</td><td>{doctor}</td><td>{full_name}</td><td>{phone}</td><td>{register_no}</td><td>{service}</td><td>{status}</td></tr>'.format(**x)
    return body+'</table>'

@APP.get('/health')
def health():
    return jsonify({'ok':True,'web_booking':True,'messenger_configured':bool(META_PAGE_ACCESS_TOKEN),'time':datetime.now().isoformat(timespec='seconds')})

@APP.get('/privacy')
def privacy():
    return '<h1>Нууцлалын бодлого</h1><p>Цаг захиалгын мэдээллийг зөвхөн эмнэлгийн үйлчилгээний зорилгоор ашиглана.</p>'

@APP.get('/delete-data')
def delete_data():
    return '<h1>Мэдээлэл устгуулах</h1><p>Эмнэлэгтэй холбогдож нэр, утсаа мэдэгдэн мэдээллээ устгуулна уу.</p>'

@APP.get('/webhook')
def verify_webhook():
    if request.args.get('hub.mode')=='subscribe' and request.args.get('hub.verify_token')==META_VERIFY_TOKEN:
        return request.args.get('hub.challenge',''),200
    return 'Forbidden',403

@APP.post('/webhook')
def webhook():
    return 'EVENT_RECEIVED',200

@APP.post('/api/appointments')
def api_create():
    ok,res=create_appt(request.get_json(silent=True) or {})
    if not ok:
        return jsonify({'ok':False,'error':res}),400
    return jsonify({'ok':True,'id':res}),201

@APP.get('/api/appointments/pending')
def pending():
    con=db(); rows=[dict(x) for x in con.execute('SELECT * FROM appointments WHERE synced=0 ORDER BY id')]; con.close()
    return jsonify({'ok':True,'appointments':rows})

@APP.post('/api/appointments/mark-synced')
def synced():
    ids=[str(x) for x in (request.get_json(silent=True) or {}).get('ids',[]) if str(x).isdigit()]
    if not ids:
        return jsonify({'ok':True,'updated':0})
    marks=','.join('?' for _ in ids)
    con=db(); cur=con.cursor(); cur.execute(f'UPDATE appointments SET synced=1 WHERE id IN ({marks})',ids)
    n=cur.rowcount; con.commit(); con.close(); return jsonify({'ok':True,'updated':n})

@APP.post('/api/appointments/<int:aid>/status')
def status(aid):
    s=(request.get_json(silent=True) or {}).get('status','')
    con=db(); cur=con.cursor(); cur.execute('UPDATE appointments SET status=? WHERE id=?',(s,aid)); n=cur.rowcount; con.commit(); con.close()
    return jsonify({'ok':bool(n),'updated':n})

@APP.get('/api/available-times')
def api_times():
    d=request.args.get('date',''); doctor=request.args.get('doctor','')
    return jsonify({'ok':True,'date':d,'doctor':doctor,'times':available_times(d,doctor)})

init_db()
if __name__=='__main__':
    APP.run(host='0.0.0.0',port=int(os.environ.get('PORT','8000')))
