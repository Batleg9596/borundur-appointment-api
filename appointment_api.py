# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime

from flask import Flask, jsonify, request

APP = Flask(__name__)

DB_FILE = os.environ.get("APPOINTMENT_DB", "appointments_server.db")
API_KEY = os.environ.get("APPOINTMENT_API_KEY", "CHANGE_THIS_SECRET_KEY")

META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "borundur_verify_2026")
META_PAGE_ACCESS_TOKEN = os.environ.get("META_PAGE_ACCESS_TOKEN", "")
META_GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v23.0")


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
            service TEXT,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            doctor TEXT,
            status TEXT DEFAULT 'Шинэ',
            source TEXT DEFAULT 'Facebook',
            facebook_user_id TEXT,
            patient_id TEXT,
            note TEXT,
            synced INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messenger_sessions(
            sender_id TEXT PRIMARY KEY,
            step TEXT NOT NULL DEFAULT 'name',
            full_name TEXT,
            phone TEXT,
            service TEXT,
            appointment_date TEXT,
            appointment_time TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_pending ON appointments(synced,status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_slot ON appointments(appointment_date,appointment_time,doctor)")
    con.commit()
    con.close()


def authorized():
    return request.headers.get("X-API-Key", "") == API_KEY


@APP.before_request
def check_auth():
    if request.path in {"/health", "/webhook", "/privacy", "/delete-data"}:
        return None
    if not authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return None


@APP.get("/health")
def health():
    return jsonify({
        "ok": True,
        "time": datetime.now().isoformat(timespec="seconds"),
        "messenger_configured": bool(META_PAGE_ACCESS_TOKEN),
    })


def send_messenger_text(recipient_id: str, text: str) -> bool:
    if not META_PAGE_ACCESS_TOKEN:
        print("META_PAGE_ACCESS_TOKEN missing")
        return False

    url = (
        f"https://graph.facebook.com/{META_GRAPH_VERSION}/me/messages"
        f"?access_token={META_PAGE_ACCESS_TOKEN}"
    )
    payload = {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {"text": text},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as exc:
        print(f"Messenger HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
    except Exception as exc:
        print(f"Messenger send error: {exc}")
    return False


def reset_session(sender_id: str):
    con = db()
    con.execute("DELETE FROM messenger_sessions WHERE sender_id=?", (sender_id,))
    con.commit()
    con.close()


def get_or_create_session(sender_id: str):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT * FROM messenger_sessions WHERE sender_id=?", (sender_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO messenger_sessions(sender_id,step) VALUES(?,?)",
            (sender_id, "name"),
        )
        con.commit()
        cur.execute("SELECT * FROM messenger_sessions WHERE sender_id=?", (sender_id,))
        row = cur.fetchone()
    result = dict(row)
    con.close()
    return result


def update_session(sender_id: str, **fields):
    allowed = {
        "step", "full_name", "phone", "service",
        "appointment_date", "appointment_time"
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return

    assignments = ", ".join(f"{k}=?" for k in clean)
    values = list(clean.values()) + [sender_id]

    con = db()
    con.execute(
        f"UPDATE messenger_sessions SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE sender_id=?",
        values,
    )
    con.commit()
    con.close()


def create_appointment_record(data):
    required = ["full_name", "appointment_date", "appointment_time"]
    missing = [x for x in required if not str(data.get(x, "")).strip()]
    if missing:
        return False, {"error": "missing_fields", "fields": missing}

    date = str(data["appointment_date"]).strip()
    time = str(data["appointment_time"]).strip()
    doctor = str(data.get("doctor", "")).strip()

    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT id FROM appointments
        WHERE appointment_date=? AND appointment_time=?
          AND COALESCE(doctor,'')=?
          AND status NOT IN ('Цуцлагдсан')
    """, (date, time, doctor))

    if cur.fetchone():
        con.close()
        return False, {"error": "slot_taken"}

    cur.execute("""
        INSERT INTO appointments(
            full_name,phone,service,appointment_date,appointment_time,
            doctor,status,source,facebook_user_id,patient_id,note
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
    """, (
        str(data.get("full_name", "")).strip(),
        str(data.get("phone", "")).strip(),
        str(data.get("service", "")).strip(),
        date,
        time,
        doctor,
        str(data.get("status", "Шинэ")).strip() or "Шинэ",
        str(data.get("source", "Facebook")).strip() or "Facebook",
        str(data.get("facebook_user_id", "")).strip(),
        str(data.get("patient_id", "")).strip(),
        str(data.get("note", "")).strip(),
    ))

    appointment_id = cur.lastrowid
    con.commit()
    con.close()
    return True, {"id": appointment_id, "status": "Шинэ"}


@APP.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode", "")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


@APP.post("/webhook")
def receive_webhook():
    payload = request.get_json(silent=True) or {}

    if payload.get("object") != "page":
        return "EVENT_RECEIVED", 200

    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = str((event.get("sender") or {}).get("id", "")).strip()
            message = event.get("message") or {}
            text = str(message.get("text", "")).strip()

            if not sender_id or not text or message.get("is_echo"):
                continue

            handle_messenger_text(sender_id, text)

    return "EVENT_RECEIVED", 200


def handle_messenger_text(sender_id: str, text: str):
    normalized = text.lower().strip()

    if normalized in {"эхлэх", "start", "цаг", "цаг захиалах", "захиалга", "дахин"}:
        reset_session(sender_id)
        get_or_create_session(sender_id)
        send_messenger_text(sender_id, "Сайн байна уу 👋\nОвог нэрээ бүтнээр нь бичнэ үү.")
        return

    session = get_or_create_session(sender_id)
    step = session["step"]

    if step == "name":
        update_session(sender_id, full_name=text, step="phone")
        send_messenger_text(sender_id, "Утасны дугаараа бичнэ үү. Жишээ: 99112233")
        return

    if step == "phone":
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) < 8:
            send_messenger_text(sender_id, "8 оронтой утасны дугаараа дахин бичнэ үү.")
            return
        update_session(sender_id, phone=digits, step="service")
        send_messenger_text(sender_id, "Ямар үйлчилгээ авах вэ?")
        return

    if step == "service":
        update_session(sender_id, service=text, step="date")
        send_messenger_text(sender_id, "Үзүүлэх өдрөө YYYY-MM-DD хэлбэрээр бичнэ үү.")
        return

    if step == "date":
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            send_messenger_text(sender_id, "Огноог YYYY-MM-DD хэлбэрээр бичнэ үү.")
            return
        update_session(sender_id, appointment_date=text, step="time")
        send_messenger_text(sender_id, "Цагаа HH:MM хэлбэрээр бичнэ үү.")
        return

    if step == "time":
        try:
            canonical_time = datetime.strptime(text, "%H:%M").strftime("%H:%M")
        except ValueError:
            send_messenger_text(sender_id, "Цагийг HH:MM хэлбэрээр бичнэ үү.")
            return

        ok, result = create_appointment_record({
            "full_name": session.get("full_name", ""),
            "phone": session.get("phone", ""),
            "service": session.get("service", ""),
            "appointment_date": session.get("appointment_date", ""),
            "appointment_time": canonical_time,
            "facebook_user_id": sender_id,
            "source": "Facebook",
            "status": "Шинэ",
        })

        if not ok and result.get("error") == "slot_taken":
            send_messenger_text(sender_id, "Сонгосон цаг захиалгатай байна. Өөр цаг бичнэ үү.")
            return

        if not ok:
            reset_session(sender_id)
            send_messenger_text(sender_id, "Алдаа гарлаа. Дахин эхлэхийн тулд «цаг» гэж бичнэ үү.")
            return

        send_messenger_text(
            sender_id,
            "✅ Таны цаг захиалгын хүсэлтийг хүлээн авлаа.\n"
            f"Нэр: {session.get('full_name', '')}\n"
            f"Утас: {session.get('phone', '')}\n"
            f"Үйлчилгээ: {session.get('service', '')}\n"
            f"Огноо: {session.get('appointment_date', '')}\n"
            f"Цаг: {canonical_time}"
        )
        reset_session(sender_id)
        return

    reset_session(sender_id)
    send_messenger_text(sender_id, "Цаг захиалах бол «цаг» гэж бичнэ үү.")


@APP.post("/api/appointments")
def create_appointment():
    data = request.get_json(silent=True) or {}
    ok, result = create_appointment_record(data)
    if not ok:
        status = 409 if result.get("error") == "slot_taken" else 400
        return jsonify({"ok": False, **result}), status
    return jsonify({"ok": True, **result}), 201


@APP.get("/api/appointments/pending")
def pending():
    con = db()
    rows = [dict(x) for x in con.execute(
        "SELECT * FROM appointments WHERE synced=0 ORDER BY id"
    ).fetchall()]
    con.close()
    return jsonify({"ok": True, "appointments": rows})


@APP.post("/api/appointments/mark-synced")
def mark_synced():
    data = request.get_json(silent=True) or {}
    ids = [str(x) for x in data.get("ids", []) if str(x).isdigit()]
    if not ids:
        return jsonify({"ok": True, "updated": 0})

    marks = ",".join("?" for _ in ids)
    con = db()
    cur = con.cursor()
    cur.execute(f"UPDATE appointments SET synced=1 WHERE id IN ({marks})", ids)
    count = cur.rowcount
    con.commit()
    con.close()
    return jsonify({"ok": True, "updated": count})


@APP.post("/api/appointments/<int:appointment_id>/status")
def update_status(appointment_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip()
    allowed = {"Шинэ", "Баталгаажсан", "Ирсэн", "Дууссан", "Цуцлагдсан"}

    if status not in allowed:
        return jsonify({"ok": False, "error": "invalid_status"}), 400

    con = db()
    cur = con.cursor()
    cur.execute("UPDATE appointments SET status=? WHERE id=?", (status, appointment_id))
    count = cur.rowcount
    con.commit()
    con.close()
    return jsonify({"ok": bool(count), "updated": count})


@APP.get("/api/available-times")
def available_times():
    date = request.args.get("date", "").strip()
    doctor = request.args.get("doctor", "").strip()

    if not date:
        return jsonify({"ok": False, "error": "date_required"}), 400

    default_slots = [
        "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
        "13:00", "13:30", "14:00", "14:30", "15:00", "15:30",
        "16:00", "16:30"
    ]

    con = db()
    taken = {
        x["appointment_time"]
        for x in con.execute("""
            SELECT appointment_time FROM appointments
            WHERE appointment_date=?
              AND COALESCE(doctor,'')=?
              AND status NOT IN ('Цуцлагдсан')
        """, (date, doctor)).fetchall()
    }
    con.close()

    return jsonify({
        "ok": True,
        "date": date,
        "doctor": doctor,
        "times": [x for x in default_slots if x not in taken],
    })
@APP.get("/privacy")
def privacy_policy():
    return """
    <!DOCTYPE html>
    <html lang="mn">
    <head>
        <meta charset="UTF-8">
        <title>Нууцлалын бодлого</title>
    </head>
    <body style="font-family:Arial; max-width:800px; margin:40px auto; line-height:1.6;">
        <h1>Нууцлалын бодлого</h1>
        <p>Бор-Өндөр уламжлалт эмнэлгийн цахим цаг захиалгын систем нь
        хэрэглэгчийн нэр, утасны дугаар, сонгосон үйлчилгээ, огноо болон цагийн
        мэдээллийг зөвхөн эмнэлгийн цаг захиалгыг зохион байгуулах зорилгоор ашиглана.</p>

        <p>Хэрэглэгчийн мэдээллийг зөвшөөрөлгүйгээр гуравдагч этгээдэд худалдах,
        сурталчилгаанд ашиглахгүй.</p>

        <p>Мэдээллийг зөвхөн эрх бүхий эмнэлгийн ажилтан үзэх боломжтой.</p>

        <p>Мэдээллээ устгуулах хүсэлтийг эмнэлгийн Facebook Page-ийн Messenger-ээр
        илгээж болно.</p>

        <p>Сүүлд шинэчилсэн: 2026-07-11</p>
    </body>
    </html>
    """, 200, {"Content-Type": "text/html; charset=utf-8"}


@APP.get("/delete-data")
def delete_data_instructions():
    return """
    <!DOCTYPE html>
    <html lang="mn">
    <head>
        <meta charset="UTF-8">
        <title>Хэрэглэгчийн мэдээлэл устгах</title>
    </head>
    <body style="font-family:Arial; max-width:800px; margin:40px auto; line-height:1.6;">
        <h1>Хэрэглэгчийн мэдээлэл устгуулах заавар</h1>
        <p>Цахим цаг захиалгын системд хадгалагдсан мэдээллээ устгуулахын тулд
        Бор-Өндөр уламжлалт эмнэлгийн Facebook Page-ийн Messenger рүү
        “Мэдээллээ устгуулна” гэж бичнэ үү.</p>

        <p>Хүсэлтдээ цаг захиалгад ашигласан нэр, утасны дугаараа оруулна.</p>

        <p>Эмнэлгийн ажилтан хүсэлтийг шалгаж, холбогдох мэдээллийг системээс устгана.</p>
    </body>
    </html>
    """, 200, {"Content-Type": "text/html; charset=utf-8"}

init_db()

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
