# -*- coding: utf-8 -*-
import os
import sqlite3
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (
    Flask, jsonify, request, render_template_string,
    redirect, url_for, session, flash
)

APP = Flask(__name__)
APP.secret_key = os.environ.get("SECRET_KEY", "borundur-secret-key-change-me")

DB_FILE = os.environ.get("APPOINTMENT_DB", "appointments_server.db")
API_KEY = os.environ.get("APPOINTMENT_API_KEY", "CHANGE_THIS_SECRET_KEY")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "borundur_admin_2026")


def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS appointments(
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
        )
    """)

    cols = {x["name"] for x in cur.execute("PRAGMA table_info(appointments)").fetchall()}
    if "register_no" not in cols:
        cur.execute("ALTER TABLE appointments ADD COLUMN register_no TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS doctors(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS services(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    defaults = {
        "work_days": "0,1,2,3,4,5",
        "work_start": "10:00",
        "work_end": "16:00",
        "slot_minutes": "60"
    }
    for k, v in defaults.items():
        cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))

    cur.execute("INSERT OR IGNORE INTO doctors(name,active) VALUES('Т.Дармагад',1)")
    for s in ["Эмчийн үзлэг", "Зүү төөнүүр", "Бариа засал", "Бумба", "Хануур", "Бусад"]:
        cur.execute("INSERT OR IGNORE INTO services(name,active) VALUES(?,1)", (s,))

    cur.execute("CREATE INDEX IF NOT EXISTS idx_appt_slot ON appointments(appointment_date,appointment_time,doctor)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_appt_pending ON appointments(synced,status)")
    con.commit()
    con.close()


def get_settings():
    con = db()
    rows = con.execute("SELECT key,value FROM settings").fetchall()
    con.close()
    return {x["key"]: x["value"] for x in rows}


def generate_slots():
    s = get_settings()
    start = datetime.strptime(s["work_start"], "%H:%M")
    end = datetime.strptime(s["work_end"], "%H:%M")
    minutes = max(15, int(s["slot_minutes"]))
    slots = []
    current = start
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=minutes)
    return slots


def valid_work_date(value):
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return False, "Огнооны формат буруу байна."
    if d < date.today():
        return False, "Өнгөрсөн өдөр сонгох боломжгүй."
    work_days = {int(x) for x in get_settings()["work_days"].split(",") if x.strip()}
    if d.weekday() not in work_days:
        return False, "Сонгосон өдөр эмнэлэг амарна."
    return True, ""


def available_times(date_text, doctor):
    ok, _ = valid_work_date(date_text)
    if not ok:
        return []
    con = db()
    taken = {
        x["appointment_time"]
        for x in con.execute("""
            SELECT appointment_time FROM appointments
            WHERE appointment_date=? AND doctor=?
              AND status NOT IN ('Цуцлагдсан')
        """, (date_text, doctor)).fetchall()
    }
    con.close()
    return [x for x in generate_slots() if x not in taken]


def create_appointment(data):
    required = ["full_name", "phone", "register_no", "doctor", "appointment_date", "appointment_time"]
    if any(not str(data.get(k, "")).strip() for k in required):
        return False, "Мэдээллээ бүрэн бөглөнө үү."

    ok, msg = valid_work_date(data["appointment_date"])
    if not ok:
        return False, msg

    if data["appointment_time"] not in available_times(data["appointment_date"], data["doctor"]):
        return False, "Сонгосон цаг боломжгүй эсвэл аль хэдийн захиалгатай байна."

    phone = "".join(c for c in str(data["phone"]) if c.isdigit())
    if len(phone) < 8:
        return False, "Утасны дугаар буруу байна."

    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO appointments(
            full_name,phone,register_no,service,
            appointment_date,appointment_time,doctor,
            status,source,synced,note
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data["full_name"].strip(),
        phone,
        data["register_no"].strip().upper(),
        data.get("service", "").strip(),
        data["appointment_date"],
        data["appointment_time"],
        data["doctor"],
        data.get("status", "Шинэ"),
        data.get("source", "Web"),
        0,
        data.get("note", "").strip()
    ))
    aid = cur.lastrowid
    con.commit()
    con.close()
    return True, aid


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper


BASE_STYLE = """
<style>
:root{--g:#176f55;--g2:#0d503d;--bg:#eef5f2;--line:#d9e5df}
*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:var(--bg);color:#18372d}
a{text-decoration:none;color:inherit}
.wrap{max-width:1180px;margin:auto;padding:18px}
.hero,.topbar{background:linear-gradient(135deg,var(--g2),var(--g));color:#fff;border-radius:18px;padding:22px}
.card{background:#fff;border-radius:16px;padding:18px;margin-top:16px;box-shadow:0 10px 28px #204c3a14}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.full{grid-column:1/-1}
label{display:block;font-weight:700;margin-bottom:6px}
input,select,textarea{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:10px;font-size:15px}
button,.btn{display:inline-block;padding:10px 14px;border:0;border-radius:10px;background:var(--g);color:#fff;font-weight:700;cursor:pointer}
.btn.red,button.red{background:#b63d3d}.btn.gray{background:#61756d}.btn.orange{background:#b86b20}
nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}nav a{padding:9px 12px;background:#ffffff22;border-radius:9px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:9px;border-bottom:1px solid #e8efeb;text-align:left;white-space:nowrap}
.scroll{overflow:auto}.alert{padding:12px;border-radius:10px;background:#fff0f0;color:#9a2f2f;margin-top:14px}
.ok{background:#e8f7ef;color:#116245}.muted{color:#6f817a;font-size:13px}
.actions{display:flex;gap:6px;align-items:center}.inline{display:inline}
@media(max-width:720px){.grid{grid-template-columns:1fr}.full{grid-column:auto}.wrap{padding:10px}}
</style>
"""

BOOKING_HTML = """<!doctype html><html lang="mn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Цаг захиалга</title>""" + BASE_STYLE + """</head><body><div class="wrap">
<div class="hero"><h1>Цахим цаг захиалга</h1><p>“Бор-Өндөр” УБҮ-ийн ҮЭ-ийн дэргэдэх уламжлалт эмнэлэг</p></div>
<div class="card">
{% if error %}<div class="alert">{{error}}</div>{% endif %}
<form method="post" action="/book" class="grid">
<div><label>Овог нэр *</label><input name="full_name" required></div>
<div><label>Утас *</label><input name="phone" required inputmode="numeric"></div>
<div><label>Регистр *</label><input name="register_no" required></div>
<div><label>Эмч *</label><select name="doctor" id="doctor">{% for d in doctors %}<option>{{d.name}}</option>{% endfor %}</select></div>
<div><label>Үйлчилгээ</label><select name="service">{% for s in services %}<option>{{s.name}}</option>{% endfor %}</select></div>
<div><label>Огноо *</label><input type="date" id="date" name="appointment_date" min="{{today}}" required></div>
<div class="full"><label>Сул цаг *</label><select name="appointment_time" id="time" required><option value="">Огноо сонгоно уу</option></select>
<div class="muted">Ажлын хуваарь админ тохиргооноос автоматаар уншигдана.</div></div>
<div class="full"><label>Нэмэлт тайлбар</label><textarea name="note" rows="3"></textarea></div>
<div class="full"><button>Цаг захиалах</button></div>
</form></div></div>
<script>
async function loadTimes(){
 const d=document.getElementById('date').value, doc=document.getElementById('doctor').value, t=document.getElementById('time');
 if(!d){return}
 t.innerHTML='<option>Уншиж байна...</option>';
 const r=await fetch('/api/web/available-times?date='+encodeURIComponent(d)+'&doctor='+encodeURIComponent(doc));
 const j=await r.json();
 if(!j.ok){t.innerHTML='<option value="">'+(j.message||'Боломжгүй өдөр')+'</option>';return}
 t.innerHTML=j.times.length?'<option value="">Сул цагаа сонгоно уу</option>'+j.times.map(x=>'<option>'+x+'</option>').join(''):'<option value="">Сул цаг байхгүй</option>';
}
date.onchange=loadTimes;doctor.onchange=loadTimes;
</script></body></html>"""

SUCCESS_HTML = """<!doctype html><html lang="mn"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + BASE_STYLE + """
<body><div class="wrap"><div class="card"><h1>✅ Амжилттай захиалагдлаа</h1>
<p><b>Захиалгын дугаар:</b> {{id}}</p><p><b>Эмч:</b> {{doctor}}</p><p><b>Огноо:</b> {{d}}</p><p><b>Цаг:</b> {{t}}</p>
<a class="btn" href="/booking">Өөр цаг захиалах</a></div></div></body></html>"""

LOGIN_HTML = """<!doctype html><html lang="mn"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">""" + BASE_STYLE + """
<body><div class="wrap" style="max-width:430px"><div class="card"><h2>Админ нэвтрэх</h2>
{% if error %}<div class="alert">{{error}}</div>{% endif %}
<form method="post"><label>Хэрэглэгчийн нэр</label><input name="username" required>
<label style="margin-top:12px">Нууц үг</label><input type="password" name="password" required>
<button style="width:100%;margin-top:16px">Нэвтрэх</button></form></div></div></body></html>"""

ADMIN_LAYOUT_TOP = """<!doctype html><html lang="mn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Админ</title>""" + BASE_STYLE + """</head><body><div class="wrap">
<div class="topbar"><h2>Цаг захиалгын админ</h2><nav>
<a href="/admin">Захиалга</a><a href="/admin/doctors">Эмч нар</a><a href="/admin/services">Үйлчилгээ</a><a href="/admin/settings">Ажлын хуваарь</a><a href="/admin/logout">Гарах</a>
</nav></div>"""

ADMIN_APPOINTMENTS = ADMIN_LAYOUT_TOP + """
<div class="card">
<form method="get" class="actions"><input type="date" name="date" value="{{selected}}"><button>Харах</button></form>
</div>
<div class="card scroll"><table><thead><tr><th>ID</th><th>Цаг</th><th>Эмч</th><th>Овог нэр</th><th>Утас</th><th>Регистр</th><th>Үйлчилгээ</th><th>Төлөв</th><th>Үйлдэл</th></tr></thead>
<tbody>{% for x in rows %}<tr>
<td>{{x.id}}</td><td>{{x.appointment_time}}</td><td>{{x.doctor}}</td><td>{{x.full_name}}</td><td>{{x.phone}}</td><td>{{x.register_no or ''}}</td><td>{{x.service}}</td><td>{{x.status}}</td>
<td><form class="inline" method="post" action="/admin/appointments/{{x.id}}/status"><input type="hidden" name="date" value="{{selected}}">
<select name="status"><option>Шинэ</option><option>Баталгаажсан</option><option>Ирсэн</option><option>Дууссан</option><option>Ирээгүй</option><option>Цуцлагдсан</option></select><button>Солих</button></form>
<form class="inline" method="post" action="/admin/appointments/{{x.id}}/delete" onsubmit="return confirm('Устгах уу?')"><input type="hidden" name="date" value="{{selected}}"><button class="red">Устгах</button></form></td>
</tr>{% else %}<tr><td colspan="9">Захиалга алга.</td></tr>{% endfor %}</tbody></table></div></div></body></html>"""

DOCTORS_HTML = ADMIN_LAYOUT_TOP + """
<div class="card"><h3>Эмч нэмэх</h3><form method="post" class="actions"><input name="name" placeholder="Эмчийн нэр" required><button>Нэмэх</button></form></div>
<div class="card"><table><tr><th>Нэр</th><th>Төлөв</th><th>Үйлдэл</th></tr>
{% for x in rows %}<tr><td>{{x.name}}</td><td>{{'Идэвхтэй' if x.active else 'Идэвхгүй'}}</td><td>
<form class="inline" method="post" action="/admin/doctors/{{x.id}}/toggle"><button class="gray">{{'Идэвхгүй болгох' if x.active else 'Идэвхжүүлэх'}}</button></form>
<form class="inline" method="post" action="/admin/doctors/{{x.id}}/delete" onsubmit="return confirm('Устгах уу?')"><button class="red">Устгах</button></form>
</td></tr>{% endfor %}</table></div></div></body></html>"""

SERVICES_HTML = ADMIN_LAYOUT_TOP + """
<div class="card"><h3>Үйлчилгээ нэмэх</h3><form method="post" class="actions"><input name="name" placeholder="Үйлчилгээний нэр" required><button>Нэмэх</button></form></div>
<div class="card"><table><tr><th>Нэр</th><th>Төлөв</th><th>Үйлдэл</th></tr>
{% for x in rows %}<tr><td>{{x.name}}</td><td>{{'Идэвхтэй' if x.active else 'Идэвхгүй'}}</td><td>
<form class="inline" method="post" action="/admin/services/{{x.id}}/toggle"><button class="gray">{{'Идэвхгүй болгох' if x.active else 'Идэвхжүүлэх'}}</button></form>
<form class="inline" method="post" action="/admin/services/{{x.id}}/delete" onsubmit="return confirm('Устгах уу?')"><button class="red">Устгах</button></form>
</td></tr>{% endfor %}</table></div></div></body></html>"""

SETTINGS_HTML = ADMIN_LAYOUT_TOP + """
<div class="card"><h3>Ажлын хуваарь</h3><form method="post" class="grid">
<div><label>Эхлэх цаг</label><input type="time" name="work_start" value="{{s.work_start}}" required></div>
<div><label>Дуусах цаг</label><input type="time" name="work_end" value="{{s.work_end}}" required></div>
<div><label>Нэг үзлэгийн минут</label><input type="number" min="15" step="15" name="slot_minutes" value="{{s.slot_minutes}}" required></div>
<div class="full"><label>Ажиллах өдрүүд</label>
{% for i,n in days %}<label style="display:inline-block;margin-right:12px;font-weight:400"><input style="width:auto" type="checkbox" name="work_days" value="{{i}}" {% if i in selected_days %}checked{% endif %}> {{n}}</label>{% endfor %}
</div><div class="full"><button>Хадгалах</button></div></form></div></div></body></html>"""


@APP.get("/")
def root():
    return redirect("/booking")


@APP.get("/booking")
def booking():
    con = db()
    doctors = con.execute("SELECT * FROM doctors WHERE active=1 ORDER BY name").fetchall()
    services = con.execute("SELECT * FROM services WHERE active=1 ORDER BY name").fetchall()
    con.close()
    return render_template_string(BOOKING_HTML, doctors=doctors, services=services, today=date.today().isoformat(), error="")


@APP.post("/book")
def book():
    data = request.form.to_dict()
    data["source"] = "Web"
    ok, result = create_appointment(data)
    if not ok:
        con = db()
        doctors = con.execute("SELECT * FROM doctors WHERE active=1 ORDER BY name").fetchall()
        services = con.execute("SELECT * FROM services WHERE active=1 ORDER BY name").fetchall()
        con.close()
        return render_template_string(BOOKING_HTML, doctors=doctors, services=services, today=date.today().isoformat(), error=result), 400
    return render_template_string(SUCCESS_HTML, id=result, doctor=data["doctor"], d=data["appointment_date"], t=data["appointment_time"])


@APP.get("/api/web/available-times")
def web_available_times():
    d = request.args.get("date", "")
    doctor = request.args.get("doctor", "")
    ok, msg = valid_work_date(d)
    if not ok:
        return jsonify({"ok": False, "message": msg, "times": []}), 400
    return jsonify({"ok": True, "times": available_times(d, doctor)})


@APP.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USERNAME and request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin")
        error = "Нэвтрэх нэр эсвэл нууц үг буруу."
    return render_template_string(LOGIN_HTML, error=error)


@APP.get("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")


@APP.get("/admin")
@admin_required
def admin_home():
    selected = request.args.get("date", date.today().isoformat())
    con = db()
    rows = con.execute("SELECT * FROM appointments WHERE appointment_date=? ORDER BY appointment_time,doctor", (selected,)).fetchall()
    con.close()
    return render_template_string(ADMIN_APPOINTMENTS, rows=rows, selected=selected)


@APP.post("/admin/appointments/<int:aid>/status")
@admin_required
def admin_status(aid):
    status = request.form.get("status", "Шинэ")
    selected = request.form.get("date", date.today().isoformat())
    con = db()
    con.execute("UPDATE appointments SET status=? WHERE id=?", (status, aid))
    con.commit()
    con.close()
    return redirect(url_for("admin_home", date=selected))


@APP.post("/admin/appointments/<int:aid>/delete")
@admin_required
def admin_delete(aid):
    selected = request.form.get("date", date.today().isoformat())
    con = db()
    con.execute("DELETE FROM appointments WHERE id=?", (aid,))
    con.commit()
    con.close()
    return redirect(url_for("admin_home", date=selected))


@APP.route("/admin/doctors", methods=["GET", "POST"])
@admin_required
def admin_doctors():
    con = db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            con.execute("INSERT OR IGNORE INTO doctors(name,active) VALUES(?,1)", (name,))
            con.commit()
    rows = con.execute("SELECT * FROM doctors ORDER BY name").fetchall()
    con.close()
    return render_template_string(DOCTORS_HTML, rows=rows)


@APP.post("/admin/doctors/<int:did>/toggle")
@admin_required
def doctor_toggle(did):
    con = db()
    con.execute("UPDATE doctors SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (did,))
    con.commit()
    con.close()
    return redirect("/admin/doctors")


@APP.post("/admin/doctors/<int:did>/delete")
@admin_required
def doctor_delete(did):
    con = db()
    con.execute("DELETE FROM doctors WHERE id=?", (did,))
    con.commit()
    con.close()
    return redirect("/admin/doctors")


@APP.route("/admin/services", methods=["GET", "POST"])
@admin_required
def admin_services():
    con = db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            con.execute("INSERT OR IGNORE INTO services(name,active) VALUES(?,1)", (name,))
            con.commit()
    rows = con.execute("SELECT * FROM services ORDER BY name").fetchall()
    con.close()
    return render_template_string(SERVICES_HTML, rows=rows)


@APP.post("/admin/services/<int:sid>/toggle")
@admin_required
def service_toggle(sid):
    con = db()
    con.execute("UPDATE services SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (sid,))
    con.commit()
    con.close()
    return redirect("/admin/services")


@APP.post("/admin/services/<int:sid>/delete")
@admin_required
def service_delete(sid):
    con = db()
    con.execute("DELETE FROM services WHERE id=?", (sid,))
    con.commit()
    con.close()
    return redirect("/admin/services")


@APP.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    con = db()
    if request.method == "POST":
        values = {
            "work_start": request.form.get("work_start", "10:00"),
            "work_end": request.form.get("work_end", "16:00"),
            "slot_minutes": request.form.get("slot_minutes", "60"),
            "work_days": ",".join(request.form.getlist("work_days"))
        }
        for k, v in values.items():
            con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        con.commit()
    con.close()
    s = get_settings()
    selected_days = {int(x) for x in s["work_days"].split(",") if x.strip()}
    days = list(enumerate(["Даваа","Мягмар","Лхагва","Пүрэв","Баасан","Бямба","Ням"]))
    return render_template_string(SETTINGS_HTML, s=s, selected_days=selected_days, days=days)


@APP.get("/health")
def health():
    return jsonify({"ok": True, "web_booking": True, "time": datetime.now().isoformat(timespec="seconds")})


@APP.get("/privacy")
def privacy():
    return "<h1>Нууцлалын бодлого</h1><p>Цаг захиалгын мэдээллийг зөвхөн эмнэлгийн үйлчилгээний зорилгоор ашиглана.</p>"


@APP.get("/delete-data")
def delete_data():
    return "<h1>Мэдээлэл устгуулах</h1><p>Эмнэлэгтэй холбогдож мэдээллээ устгуулна уу.</p>"


def api_authorized():
    return request.headers.get("X-API-Key", "") == API_KEY


@APP.post("/api/appointments")
def api_create():
    if not api_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    ok, result = create_appointment(request.get_json(silent=True) or {})
    if not ok:
        return jsonify({"ok": False, "error": result}), 400
    return jsonify({"ok": True, "id": result}), 201


@APP.get("/api/appointments/pending")
def pending():
    if not api_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    con = db()
    rows = [dict(x) for x in con.execute("SELECT * FROM appointments WHERE synced=0 ORDER BY id").fetchall()]
    con.close()
    return jsonify({"ok": True, "appointments": rows})


@APP.post("/api/appointments/mark-synced")
def mark_synced():
    if not api_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    ids = [str(x) for x in data.get("ids", []) if str(x).isdigit()]
    if not ids:
        return jsonify({"ok": True, "updated": 0})
    marks = ",".join("?" for _ in ids)
    con = db()
    cur = con.cursor()
    cur.execute(f"UPDATE appointments SET synced=1 WHERE id IN ({marks})", ids)
    n = cur.rowcount
    con.commit()
    con.close()
    return jsonify({"ok": True, "updated": n})


init_db()

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
