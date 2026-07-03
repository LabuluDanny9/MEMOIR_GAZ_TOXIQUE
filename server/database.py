"""
Base de donnees SQLite - GazMonitor Pro H2S.
Stocke mesures H2S, predictions, alertes, travailleurs/casques et administrateurs.
"""

import sqlite3
import pandas as pd
from datetime import datetime
from contextlib import contextmanager
import os, sys, json
from werkzeug.security import generate_password_hash, check_password_hash

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id        TEXT    NOT NULL DEFAULT 'CASQUE_001',
    worker_name      TEXT    DEFAULT 'Operateur',
    zone             TEXT    DEFAULT 'Zone A',
    timestamp        REAL    NOT NULL,
    datetime_utc     TEXT    NOT NULL,
    h2s_ppm          REAL    NOT NULL DEFAULT 0,
    temperature      REAL    DEFAULT 25,
    humidity         REAL    DEFAULT 50,
    exposure_time_s  REAL    DEFAULT 0,
    danger_level     INTEGER DEFAULT 0,
    danger_label     TEXT    DEFAULT 'Normal',
    risk_probability REAL    DEFAULT 0,
    h2s_dose         REAL    DEFAULT 0,
    h2s_derivative   REAL    DEFAULT 0,
    h2s_growth_rate  REAL    DEFAULT 0,
    hazard_index     REAL    DEFAULT 0,
    latitude         REAL    DEFAULT 0,
    longitude        REAL    DEFAULT 0,
    altitude         REAL    DEFAULT 0,
    speed_kmh        REAL    DEFAULT 0,
    satellites       INTEGER DEFAULT 0,
    hdop             REAL    DEFAULT 99,
    gps_valid        INTEGER DEFAULT 0,
    wifi_rssi        INTEGER DEFAULT -100,
    created_at       TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement_id  INTEGER REFERENCES measurements(id),
    alert_type      TEXT,
    danger_level    INTEGER,
    message         TEXT,
    h2s_ppm         REAL,
    latitude        REAL DEFAULT 0,
    longitude       REAL DEFAULT 0,
    resolved        INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS predictions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    measurement_id    INTEGER REFERENCES measurements(id),
    horizon_step      INTEGER,
    pred_h2s          REAL,
    pred_danger       INTEGER,
    pred_label        TEXT DEFAULT '',
    risk_probability  REAL DEFAULT 0,
    all_probabilities TEXT DEFAULT '{}',
    created_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id      TEXT NOT NULL UNIQUE,
    worker_name    TEXT NOT NULL DEFAULT 'Operateur',
    zone           TEXT DEFAULT 'Zone A',
    status         TEXT DEFAULT 'active',
    last_seen      REAL,
    last_ip        TEXT DEFAULT '',
    created_at     TEXT DEFAULT (datetime('now')),
    updated_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admins (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    full_name      TEXT DEFAULT 'Administrateur',
    role           TEXT DEFAULT 'admin',
    active         INTEGER DEFAULT 1,
    last_login     TEXT,
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ts  ON measurements(timestamp);
CREATE INDEX IF NOT EXISTS idx_dev ON measurements(device_id);
CREATE INDEX IF NOT EXISTS idx_dlv ON measurements(danger_level);
CREATE INDEX IF NOT EXISTS idx_workers_device ON workers(device_id);
"""

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_default_admin(conn):
    if conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0] == 0:
        conn.execute("""
            INSERT INTO admins (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
        """, ("admin", generate_password_hash("admin123"), "Administrateur KCC", "admin"))
        print("[DB] Admin par defaut cree : admin / admin123")


def init_database():
    with get_conn() as c:
        c.executescript(SCHEMA)
        _ensure_default_admin(c)
    print(f"[DB] Initialisee : {DB_PATH}")


def authenticate_admin(username: str, password: str) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT * FROM admins WHERE username=? AND active=1", (username,)).fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            return None
        c.execute("UPDATE admins SET last_login=? WHERE id=?", (datetime.utcnow().isoformat(), row["id"]))
        admin = dict(row)
        admin.pop("password_hash", None)
        return admin


def upsert_worker(device_id: str, worker_name: str, zone: str, last_ip: str = "", last_seen: float | None = None):
    if not device_id:
        return
    ts = last_seen or datetime.utcnow().timestamp()
    with get_conn() as c:
        c.execute("""
            INSERT INTO workers (device_id, worker_name, zone, last_seen, last_ip)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                worker_name=excluded.worker_name,
                zone=excluded.zone,
                last_seen=excluded.last_seen,
                last_ip=excluded.last_ip,
                updated_at=datetime('now')
        """, (device_id, worker_name or "Operateur", zone or "Zone A", ts, last_ip))


def insert_measurement(d: dict) -> int:
    q = """
    INSERT INTO measurements
    (device_id, worker_name, zone, timestamp, datetime_utc,
     h2s_ppm, temperature, humidity, exposure_time_s,
     danger_level, danger_label, risk_probability,
     h2s_dose, h2s_derivative, h2s_growth_rate, hazard_index,
     latitude, longitude, altitude, speed_kmh,
     satellites, hdop, gps_valid, wifi_rssi)
    VALUES
    (:device_id, :worker_name, :zone, :timestamp, :datetime_utc,
     :h2s_ppm, :temperature, :humidity, :exposure_time_s,
     :danger_level, :danger_label, :risk_probability,
     :h2s_dose, :h2s_derivative, :h2s_growth_rate, :hazard_index,
     :latitude, :longitude, :altitude, :speed_kmh,
     :satellites, :hdop, :gps_valid, :wifi_rssi)
    """
    row = {
        "device_id": d.get("device_id", "CASQUE_001"),
        "worker_name": d.get("worker_name", "Operateur"),
        "zone": d.get("zone", "Zone A"),
        "timestamp": d.get("timestamp", datetime.utcnow().timestamp()),
        "datetime_utc": d.get("datetime_utc", datetime.utcnow().isoformat()),
        "h2s_ppm": d.get("h2s_ppm", 0.0),
        "temperature": d.get("temperature", 25.0),
        "humidity": d.get("humidity", 50.0),
        "exposure_time_s": d.get("exposure_time_s", 0.0),
        "danger_level": d.get("danger_level", 0),
        "danger_label": d.get("danger_label", "Normal"),
        "risk_probability": d.get("risk_probability", 0.0),
        "h2s_dose": d.get("h2s_dose", 0.0),
        "h2s_derivative": d.get("h2s_derivative", 0.0),
        "h2s_growth_rate": d.get("h2s_growth_rate", 0.0),
        "hazard_index": d.get("hazard_index", 0.0),
        "latitude": d.get("latitude", 0.0),
        "longitude": d.get("longitude", 0.0),
        "altitude": d.get("altitude", 0.0),
        "speed_kmh": d.get("speed_kmh", 0.0),
        "satellites": d.get("satellites", 0),
        "hdop": d.get("hdop", 99.9),
        "gps_valid": int(d.get("gps_valid", False)),
        "wifi_rssi": d.get("wifi_rssi", -100),
    }
    with get_conn() as c:
        cur = c.execute(q, row)
        return cur.lastrowid


def insert_alert(mid, atype, lvl, msg, h2s, lat=0, lng=0):
    with get_conn() as c:
        c.execute("""
            INSERT INTO alerts (measurement_id,alert_type,danger_level,message,h2s_ppm,latitude,longitude)
            VALUES (?,?,?,?,?,?,?)
        """, (mid, atype, lvl, msg, h2s, lat, lng))


def insert_prediction(mid, step, ph2s, pdanger, pred_label="", risk_probability=0.0, all_probabilities=None):
    with get_conn() as c:
        c.execute("""
            INSERT INTO predictions
            (measurement_id,horizon_step,pred_h2s,pred_danger,pred_label,risk_probability,all_probabilities)
            VALUES (?,?,?,?,?,?,?)
        """, (mid, step, ph2s, pdanger, pred_label, risk_probability,
              json.dumps(all_probabilities or {}, ensure_ascii=False)))


def get_recent(limit=200, device_id=None) -> pd.DataFrame:
    q = "SELECT * FROM measurements"
    p = []
    if device_id:
        q += " WHERE device_id=?"; p.append(device_id)
    q += " ORDER BY timestamp DESC LIMIT ?"; p.append(limit)
    with get_conn() as c:
        df = pd.read_sql_query(q, c, params=p)
    return df.sort_values("timestamp").reset_index(drop=True)


def get_devices() -> list:
    with get_conn() as c:
        rows = c.execute("""
            SELECT m.device_id,
                   COALESCE(w.worker_name, m.worker_name) AS worker_name,
                   COALESCE(w.zone, m.zone) AS zone,
                   MAX(m.timestamp) as last_seen,
                   AVG(m.h2s_ppm) as avg_h2s,
                   MAX(m.danger_level) as max_danger,
                   COUNT(*) as n_measures,
                   MAX(m.latitude) as lat, MAX(m.longitude) as lng
            FROM measurements m
            LEFT JOIN workers w ON w.device_id = m.device_id
            GROUP BY m.device_id
        """).fetchall()
    return [dict(r) for r in rows]


def get_workers() -> list:
    with get_conn() as c:
        rows = c.execute("""
            SELECT * FROM workers
            ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END,
                     COALESCE(last_seen, 0) DESC, worker_name ASC
        """).fetchall()
    return [dict(r) for r in rows]


def get_worker(device_id: str) -> dict | None:
    with get_conn() as c:
        row = c.execute("SELECT * FROM workers WHERE device_id=?", (device_id,)).fetchone()
    return dict(row) if row else None


def save_worker(device_id: str, worker_name: str, zone: str, status: str = "active") -> dict:
    device_id = (device_id or "").strip()
    if not device_id:
        raise ValueError("device_id requis")
    status = status if status in {"active", "inactive"} else "active"
    with get_conn() as c:
        c.execute("""
            INSERT INTO workers (device_id, worker_name, zone, status, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(device_id) DO UPDATE SET
                worker_name=excluded.worker_name,
                zone=excluded.zone,
                status=excluded.status,
                updated_at=datetime('now')
        """, (device_id, worker_name or "Operateur", zone or "Zone A", status))
        row = c.execute("SELECT * FROM workers WHERE device_id=?", (device_id,)).fetchone()
    return dict(row)


def set_worker_status(device_id: str, status: str) -> dict | None:
    status = status if status in {"active", "inactive"} else "inactive"
    with get_conn() as c:
        c.execute("UPDATE workers SET status=?, updated_at=datetime('now') WHERE device_id=?", (status, device_id))
        row = c.execute("SELECT * FROM workers WHERE device_id=?", (device_id,)).fetchone()
    return dict(row) if row else None


def delete_worker(device_id: str) -> bool:
    with get_conn() as c:
        cur = c.execute("DELETE FROM workers WHERE device_id=?", (device_id,))
    return cur.rowcount > 0


def get_stats() -> dict:
    with get_conn() as c:
        total = c.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
        if total == 0:
            return {"total": 0}
        r = c.execute("""
            SELECT AVG(h2s_ppm) ah, MAX(h2s_ppm) mh,
                   COUNT(CASE WHEN danger_level=2 THEN 1 END) nd,
                   COUNT(CASE WHEN danger_level=1 THEN 1 END) nm,
                   COUNT(CASE WHEN danger_level=0 THEN 1 END) nn
            FROM measurements
        """).fetchone()
        alerts = c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    return {
        "total": total, "alerts": alerts,
        "avg_h2s": round(r["ah"] or 0, 3), "max_h2s": round(r["mh"] or 0, 3),
        "n_dangerous": r["nd"], "n_medium": r["nm"], "n_normal": r["nn"],
    }


def get_alerts_recent(limit=50) -> list:
    with get_conn() as c:
        rows = c.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
