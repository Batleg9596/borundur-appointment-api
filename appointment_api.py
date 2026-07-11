# -*- coding: utf-8 -*-
import os
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, request

APP = Flask(__name__)
DB_FILE = os.environ.get("APPOINTMENT_DB", "appointments_server.db")
API_KEY = os.environ.get("APPOINTMENT_API_KEY", "CHANGE_THIS_SECRET_KEY")


def db():
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db(); cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS appointments(
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
    )""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pending ON appointments(synced,status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_slot ON appointments(appointment_date,appointment_time,doctor)")
    con.commit(); con.close()


def authorized():
    return request.headers.get("X-API-Key", "") == API_KEY


@APP.before_request
def check_auth():
    if request.path == "/health":
        return None
    if not authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401


@APP.get("/health")
def health():
    return jsonify({"ok": True, "time": datetime.now().isoformat(timespec="seconds")})


@APP.post("/api/appointments")
def create_appointment():
    data = request.get_json(silent=True) or {}
    required = ["full_name", "appointment_date", "appointment_time"]
    missing = [x for x in required if not str(data.get(x, "")).strip()]
    if missing:
        return jsonify({"ok": False, "error": "missing_fields", "fields": missing}), 400

    date = str(data["appointment_date"]).strip()
    time = str(data["appointment_time"]).strip()
    doctor = str(data.get("doctor", "")).strip()
    con = db(); cur = con.cursor()
    cur.execute("""SELECT id FROM appointments
                   WHERE appointment_date=? AND appointment_time=?
                   AND COALESCE(doctor,'')=? AND status NOT IN ('Цуцлагдсан')""", (date, time, doctor))
    if cur.fetchone():
        con.close()
        return jsonify({"ok": False, "error": "slot_taken", "message": "Сонгосон цаг захиалгатай байна."}), 409

    cur.execute("""INSERT INTO appointments(full_name,phone,service,appointment_date,appointment_time,doctor,status,source,facebook_user_id,patient_id,note)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
        str(data.get("full_name", "")).strip(), str(data.get("phone", "")).strip(),
        str(data.get("service", "")).strip(), date, time, doctor,
        str(data.get("status", "Шинэ")).strip() or "Шинэ",
        str(data.get("source", "Facebook")).strip() or "Facebook",
        str(data.get("facebook_user_id", "")).strip(), str(data.get("patient_id", "")).strip(),
        str(data.get("note", "")).strip()
    ))
    appointment_id = cur.lastrowid
    con.commit(); con.close()
    return jsonify({"ok": True, "id": appointment_id, "status": "Шинэ"}), 201


@APP.get("/api/appointments/pending")
def pending():
    con = db(); cur = con.cursor()
    cur.execute("SELECT * FROM appointments WHERE synced=0 ORDER BY id")
    rows = [dict(x) for x in cur.fetchall()]
    con.close()
    return jsonify({"ok": True, "appointments": rows})


@APP.post("/api/appointments/mark-synced")
def mark_synced():
    data = request.get_json(silent=True) or {}
    ids = [str(x) for x in data.get("ids", []) if str(x).isdigit()]
    if not ids:
        return jsonify({"ok": True, "updated": 0})
    marks = ",".join("?" for _ in ids)
    con = db(); cur = con.cursor()
    cur.execute(f"UPDATE appointments SET synced=1 WHERE id IN ({marks})", ids)
    count = cur.rowcount
    con.commit(); con.close()
    return jsonify({"ok": True, "updated": count})


@APP.post("/api/appointments/<int:appointment_id>/status")
def update_status(appointment_id):
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip()
    allowed = {"Шинэ", "Баталгаажсан", "Ирсэн", "Дууссан", "Цуцлагдсан"}
    if status not in allowed:
        return jsonify({"ok": False, "error": "invalid_status"}), 400
    con = db(); cur = con.cursor()
    cur.execute("UPDATE appointments SET status=? WHERE id=?", (status, appointment_id))
    count = cur.rowcount
    con.commit(); con.close()
    return jsonify({"ok": bool(count), "updated": count})


@APP.get("/api/available-times")
def available_times():
    date = request.args.get("date", "").strip()
    doctor = request.args.get("doctor", "").strip()
    if not date:
        return jsonify({"ok": False, "error": "date_required"}), 400
    default_slots = ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30"]
    con = db(); cur = con.cursor()
    cur.execute("""SELECT appointment_time FROM appointments
                   WHERE appointment_date=? AND COALESCE(doctor,'')=? AND status NOT IN ('Цуцлагдсан')""", (date, doctor))
    taken = {x["appointment_time"] for x in cur.fetchall()}
    con.close()
    return jsonify({"ok": True, "date": date, "doctor": doctor, "times": [x for x in default_slots if x not in taken]})


init_db()

if __name__ == "__main__":
    APP.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
