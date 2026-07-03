"""
GazMonitor Pro — Serveur Flask
Surveillance H2S : classification Random Forest + prediction LSTM + dose accumulee.
Recoit les donnees du casque (1 capteur H2S + T/HR + GPS), applique les modeles
pre-entraines et diffuse les resultats au dashboard via WebSocket.
"""

from flask import Flask, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO
from flask_cors import CORS
from datetime import datetime
import threading, os, sys

ROOT_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
sys.path.insert(0, ROOT_DIR)

from config import FLASK_HOST, FLASK_PORT, SECRET_KEY, DANGER_CLASSES, DANGER_COLORS
from server.h2s_engine import DECISION_RULE, RISK_LABELS, classify_c_fusion, engine
from server.database import (init_database, insert_measurement, insert_prediction,
                             upsert_worker, get_workers, get_worker, save_worker,
                             set_worker_status, delete_worker, authenticate_admin, get_conn)

# Meteo (optionnelle)
try:
    from server.weather_service import get_weather, start_background_refresh
    _HAS_WEATHER = True
except Exception:
    _HAS_WEATHER = False
    def get_weather(): return {"temperature": None, "humidity": None, "weather_description": None}
    def start_background_refresh(interval=600): pass

# ─── APP ──────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["SECRET_KEY"] = SECRET_KEY
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading",
                    logger=False, engineio_logger=False)

last_result = {}
devices     = {}   # device_id -> dernier bcast (multi-casques)
_lock       = threading.Lock()
_stats      = {"total": 0, "alerts": 0}
DEVICE_TIMEOUT = 30   # secondes sans donnees => casque hors ligne
ESP32_TIMEOUT = 12    # secondes sans heartbeat => ESP32 hors ligne
esp32_state = {
    "device_id": "CASQUE_001",
    "desired_enabled": True,
    "last_seen": 0.0,
    "last_heartbeat": 0.0,
    "last_sensor_data": 0.0,
    "last_ip": "",
    "wifi_rssi": -100,
    "ip_address": "",
    "source": "startup",
    "message": "En attente du premier heartbeat ESP32",
}

PUBLIC_ENDPOINTS = {
    "login_page", "api_login", "api_logout", "api_health",
    "receive_sensor_data", "api_connectivity", "api_esp32_command", "api_esp32_heartbeat", "static",
}


@app.before_request
def require_admin_auth():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if request.path.startswith("/socket.io/"):
        return None
    if session.get("admin_id"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error": "Authentification administrateur requise"}), 401
    return redirect(url_for("login_page"))


# Seuil de detection incendie (temperature)
FIRE_TEMP_C = 50.0   # >= 50 C => suspicion d'incendie

# Historique journalier (CSV) — dossier logs/
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# Banque d'echantillons reels (par classe) pour simulateur + presets
import json, random, csv
_SAMPLE_BANK = {0: [], 1: [], 2: []}
def _load_bank():
    global _SAMPLE_BANK
    p = os.path.join(ROOT_DIR, "models", "sample_bank.json")
    if os.path.exists(p):
        raw = json.load(open(p))
        _SAMPLE_BANK = {int(k): v for k, v in raw.items()}


def _detect_server_ip():
    import socket as _s, re, subprocess
    try:
        out = subprocess.run(["ipconfig"], capture_output=True, text=True,
                             encoding="latin-1").stdout
        m = re.search(r"(sans fil Wi-Fi.*?)(?=\nCarte |\Z)", out, re.S)
        if m:
            ip = re.search(r"IPv4.*?:\s*([\d.]+)", m.group(1))
            if ip:
                return ip.group(1)
        for ip in re.findall(r"IPv4.*?:\s*([\d.]+)", out):
            if not (ip.startswith("127.") or ip.startswith("169.254.")
                    or ip.startswith("10.2.0.") or ip.startswith("192.168.56.")):
                return ip
    except Exception:
        pass
    try:
        k = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        k.connect(("8.8.8.8", 80))
        ip = k.getsockname()[0]
        k.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _esp32_status_payload_unlocked():
    now = datetime.utcnow().timestamp()
    last_seen = float(esp32_state.get("last_seen") or 0.0)
    online = bool(last_seen and (now - last_seen) < ESP32_TIMEOUT)
    desired = bool(esp32_state.get("desired_enabled", True))
    if online and desired:
        label = "Connecte"
    elif online and not desired:
        label = "Connecte - transmission suspendue"
    elif desired:
        label = "En attente de l'ESP32"
    else:
        label = "Deconnecte par le dashboard"
    return {
        "online": online,
        "desired_enabled": desired,
        "label": label,
        "device_id": esp32_state.get("device_id", "CASQUE_001"),
        "last_seen": last_seen,
        "age_s": round(now - last_seen, 1) if last_seen else None,
        "last_heartbeat": esp32_state.get("last_heartbeat", 0.0),
        "last_sensor_data": esp32_state.get("last_sensor_data", 0.0),
        "last_ip": esp32_state.get("last_ip", ""),
        "wifi_rssi": esp32_state.get("wifi_rssi", -100),
        "ip_address": esp32_state.get("ip_address", ""),
        "source": esp32_state.get("source", "unknown"),
        "message": esp32_state.get("message", ""),
        "timeout_s": ESP32_TIMEOUT,
    }


def _esp32_status_payload():
    with _lock:
        return _esp32_status_payload_unlocked()


def _update_esp32_presence(data, source="heartbeat"):
    now = datetime.utcnow().timestamp()
    device_id = str(data.get("device_id") or esp32_state.get("device_id") or "CASQUE_001")
    try:
        wifi_rssi = int(float(data.get("wifi_rssi", esp32_state.get("wifi_rssi", -100))))
    except (TypeError, ValueError):
        wifi_rssi = int(esp32_state.get("wifi_rssi", -100))
    ip_address = str(data.get("ip_address") or data.get("esp_ip") or esp32_state.get("ip_address", ""))
    with _lock:
        esp32_state.update({
            "device_id": device_id,
            "last_seen": now,
            "last_ip": request.remote_addr or esp32_state.get("last_ip", ""),
            "wifi_rssi": wifi_rssi,
            "ip_address": ip_address,
            "source": source,
            "message": "ESP32 actif" if esp32_state.get("desired_enabled", True) else "Transmission suspendue par le dashboard",
        })
        if source in {"heartbeat", "command", "connectivity"}:
            esp32_state["last_heartbeat"] = now
        if source == "sensor_data":
            esp32_state["last_sensor_data"] = now
        status = _esp32_status_payload_unlocked()
    socketio.emit("esp32_status", status)
    return status

def _history_path(date_str=None):
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOGS_DIR, f"historique_{date_str}.csv")


HIST_HEADER = ["horodatage", "casque", "operateur", "zone",
               "h2s_ppm", "h2s_predit", "dose_cumulee",
               "temperature", "humidite",
               "prob_normal", "prob_modere", "prob_dangereux",
               "niveau", "label", "temp_elevee",
               "vitesse_kmh", "satellites", "altitude", "hdop", "rssi_wifi",
               "exposition", "latitude", "longitude"]


def _log_history(b):
    """Ajoute une ligne H2S-only dans le CSV journalier local."""
    path = _history_path()
    new = not os.path.exists(path)
    if not new:
        try:
            with open(path, encoding="utf-8") as f:
                first_line = f.readline().strip()
            if first_line and first_line != ",".join(HIST_HEADER):
                path = path.replace(".csv", "_h2s.csv")
                new = not os.path.exists(path)
        except Exception:
            pass
    pr = b.get("probabilities", {}) or {}
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(HIST_HEADER)
            w.writerow([
                b.get("timestamp", ""), b.get("device_id", ""), b.get("worker_name", ""), b.get("zone", ""),
                b.get("h2s_ppm", b.get("h2s_mesure", 0)), b.get("prediction_h2s", 0), b.get("dose_accumulee", 0),
                b.get("temperature", 0), b.get("humidity", 0),
                round(pr.get(0, 0), 4), round(pr.get(1, 0), 4), round(pr.get(2, 0), 4),
                b.get("risk_class", 0), b.get("risk_label", ""),
                int(b.get("fire_alert", False)),
                b.get("speed_kmh", 0), b.get("satellites", 0), b.get("altitude", 0),
                b.get("hdop", 0), b.get("wifi_rssi", 0), b.get("exposure_level", ""),
                b.get("latitude", 0), b.get("longitude", 0),
            ])
    except Exception as e:
        print(f"[HIST] Erreur ecriture : {e}")

# ===============================================================
def startup():
    init_database()
    engine.load()
    _load_bank()
    if _HAS_WEATHER:
        try: start_background_refresh(interval=600)
        except Exception: pass
    with _lock:
        global last_result
        last_result = _build_idle_state()
    print(f"[SERVER] Dashboard : http://localhost:{FLASK_PORT}/")
    print(f"[SERVER] Test ESP32: POST http://0.0.0.0:{FLASK_PORT}/api/connectivity")
    print(f"[SERVER] API casque: POST http://0.0.0.0:{FLASK_PORT}/api/sensor_data")




@app.route("/login")
def login_page():
    if session.get("admin_id"):
        return redirect(url_for("dashboard"))
    return LOGIN_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or request.form
    admin = authenticate_admin(str(data.get("username", "")).strip(), str(data.get("password", "")))
    if not admin:
        return jsonify({"error": "Identifiants administrateur invalides"}), 401
    session.clear()
    session["admin_id"] = admin["id"]
    session["admin_username"] = admin["username"]
    return jsonify({"status": "ok", "admin": admin}), 200


@app.route("/api/auth/logout", methods=["POST", "GET"])
def api_logout():
    session.clear()
    if request.method == "GET":
        return redirect(url_for("login_page"))
    return jsonify({"status": "logged_out"}), 200


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "service": "GazMonitor Pro",
        "esp32_endpoint": "/api/sensor_data",
        "connectivity_endpoint": "/api/connectivity",
        "esp32_status_endpoint": "/api/esp32/status",
        "esp32_control_endpoint": "/api/esp32/control",
        "esp32_command_endpoint": "/api/esp32/command",
        "esp32_heartbeat_endpoint": "/api/esp32/heartbeat",
        "port": FLASK_PORT,
        "c_fusion_definition": "C_fusion = concentration H2S fusionnee en ppm",
        "decision_rule": DECISION_RULE,
    }), 200

@app.route("/api/esp32/status")
def api_esp32_status():
    status = _esp32_status_payload()
    ip = _detect_server_ip()
    status.update({
        "server_ip": ip,
        "port": FLASK_PORT,
        "api_url": f"http://{ip}:{FLASK_PORT}/api/sensor_data",
        "command_url": f"http://{ip}:{FLASK_PORT}/api/esp32/command",
        "heartbeat_url": f"http://{ip}:{FLASK_PORT}/api/esp32/heartbeat",
    })
    return jsonify(status), 200


@app.route("/api/esp32/control", methods=["POST"])
def api_esp32_control():
    global last_result
    d = request.get_json(silent=True) or {}
    enabled = bool(d.get("enabled", True))
    with _lock:
        esp32_state["desired_enabled"] = enabled
        esp32_state["message"] = "Connexion demandee depuis le dashboard" if enabled else "Deconnexion demandee depuis le dashboard"
        device_id = esp32_state.get("device_id", "CASQUE_001")
        if not enabled and device_id in devices:
            devices[device_id]["esp32_enabled"] = False
            devices[device_id]["connectivity_only"] = True
            devices[device_id]["system_state"] = "disabled"
            devices[device_id]["risk_label"] = "DESACTIVE"
            last_result = devices[device_id]
        status = _esp32_status_payload_unlocked()
    socketio.emit("esp32_status", status)
    return jsonify({"status": "ok", "esp32": status}), 200


@app.route("/api/esp32/command")
def api_esp32_command():
    data = {
        "device_id": request.args.get("device_id", "CASQUE_001"),
        "wifi_rssi": request.args.get("wifi_rssi", -100),
        "ip_address": request.args.get("ip_address", ""),
    }
    status = _update_esp32_presence(data, "command")
    return jsonify({
        "status": "ok",
        "enabled": status["desired_enabled"],
        "device_id": status["device_id"],
        "send_interval_ms": 5000,
        "heartbeat_interval_ms": 2000,
        "sensor_endpoint": "/api/sensor_data",
    }), 200


@app.route("/api/esp32/heartbeat", methods=["POST"])
def api_esp32_heartbeat():
    if not request.is_json:
        return jsonify({"status": "error", "error": "JSON requis"}), 400
    data = request.get_json(silent=True) or {}
    status = _update_esp32_presence(data, "heartbeat")
    return jsonify({
        "status": "ok",
        "enabled": status["desired_enabled"],
        "online": status["online"],
        "label": status["label"],
    }), 200


@app.route("/api/connectivity", methods=["POST"])
def api_connectivity():
    """Diagnostic reseau ESP32 qui met aussi le dashboard en etat connecte."""
    global last_result
    if not request.is_json:
        return jsonify({"status": "error", "error": "JSON requis"}), 400
    data = request.get_json(silent=True) or {}
    if not any(k in data for k in ("h2s_ppm", "h2s_fusion_ppm", "c_fusion_ppm")):
        return jsonify({"status": "error", "error": "h2s_ppm ou c_fusion_ppm requis"}), 400

    status = _update_esp32_presence(data, "connectivity")
    try:
        raw_h2s = data.get("c_fusion_ppm", data.get("h2s_fusion_ppm", data.get("h2s_ppm", 0.0)))
        h2s = max(0.0, float(raw_h2s or 0.0))
    except (TypeError, ValueError):
        h2s = 0.0
    try:
        temperature = float(data.get("temperature", 25.0) or 25.0)
    except (TypeError, ValueError):
        temperature = 25.0
    try:
        humidity = float(data.get("humidity", 50.0) or 50.0)
    except (TypeError, ValueError):
        humidity = 50.0

    risk_class = classify_c_fusion(h2s)
    risk_label = RISK_LABELS.get(risk_class, "NORMAL") if status["desired_enabled"] else "DESACTIVE"
    probabilities = {0: 0.0, 1: 0.0, 2: 0.0}
    probabilities[risk_class] = 1.0

    res = {
        "risk_class": risk_class,
        "risk_label": risk_label,
        "probabilities": probabilities,
        "h2s_mesure": h2s,
        "h2s_fusion_ppm": h2s,
        "c_fusion_ppm": h2s,
        "decision_rule": DECISION_RULE,
        "prediction_h2s": 0.0,
        "prediction_ready": False,
        "pred_risk_class": 0,
        "pred_risk_label": "NORMAL",
        "pred_probabilities": {0: 1.0, 1: 0.0, 2: 0.0},
        "pred_risk_probability": 0.0,
        "prediction_risk_model": "connectivity",
        "prediction_horizon_s": getattr(engine, "horizon_s", 50),
        "buffer_fill": 0,
        "buffer_size": getattr(engine, "window", 60),
        "dose_accumulee": 0.0,
        "exposure_level": "Faible",
    }
    bcast = _build_broadcast(data, res, h2s, h2s, h2s, h2s, temperature, humidity)
    bcast["system_state"] = "connectivity" if status["desired_enabled"] else "disabled"
    bcast["connectivity_only"] = True
    bcast["esp32_enabled"] = status["desired_enabled"]

    with _lock:
        last_result = bcast
        devices[bcast["device_id"]] = bcast
    socketio.emit("new_data", bcast)

    return jsonify({
        "status": "ok",
        "message": "ESP32 connecte au serveur Flask et visible sur le dashboard",
        "device_id": bcast["device_id"],
        "client_ip": request.remote_addr,
        "server_ip": request.host.split(":")[0],
        "dashboard_online": True,
        "enabled": status["desired_enabled"],
        "h2s_ppm": h2s,
        "c_fusion_ppm": h2s,
        "risk_class": risk_class,
        "risk_label": risk_label,
        "decision_rule": DECISION_RULE,
        "timestamp": bcast["timestamp"],
    }), 200
# ===============================================================
#  Extraction H2S depuis le JSON recu
#  Le prototype utilise un seul capteur gaz: MQ-136.
# ===============================================================
def _extract_sensors(d):
    try:
        raw_h2s = d.get("c_fusion_ppm", d.get("h2s_fusion_ppm", d.get("h2s_ppm", 0.0)))
        h2s = max(0.0, float(raw_h2s or 0.0))
    except (TypeError, ValueError):
        h2s = 0.0
    return h2s, h2s, h2s, h2s


# ===============================================================
#  RECEPTION DES DONNEES DU CASQUE
# ===============================================================
@app.route("/api/sensor_data", methods=["POST"])
def receive_sensor_data():
    if not request.is_json:
        return jsonify({"error": "JSON requis"}), 400
    d = request.get_json(silent=True) or {}

    try:
        s1, s2, s3, s4 = _extract_sensors(d)
        temperature = float(d.get("temperature", 25.0))
        humidity    = float(d.get("humidity", 50.0))
        device_id   = d.get("device_id", "CASQUE_001")
        esp_status = _update_esp32_presence(d, "sensor_data")
        if not esp_status["desired_enabled"]:
            return jsonify({"status": "paused", "enabled": False, "message": "ESP32 suspendu depuis le dashboard"}), 202
        worker_cfg = get_worker(device_id)
        if worker_cfg and worker_cfg.get("status") != "active":
            return jsonify({"error": "Casque desactive", "device_id": device_id}), 403

        # --- Moteur IA : RF + LSTM + dose ---
        res = engine.process(device_id, s1, s2, s3, s4, humidity, temperature)

        # --- Construction du payload dashboard ---
        bcast = _build_broadcast(d, res, s1, s2, s3, s4, temperature, humidity)
        with _lock:
            global last_result
            last_result = bcast
            devices[device_id] = bcast
            _stats["total"] += 1
            if res["risk_class"] >= 2 or bcast["fire_alert"]:
                _stats["alerts"] += 1
        _persist_measurement(d, res, bcast)
        _log_history(bcast)
        socketio.emit("new_data", bcast)

        return jsonify({
            "risk_class":     res["risk_class"],
            "risk_label":     res["risk_label"],
            "prediction_h2s": res["prediction_h2s"],
            "dose_accumulee": res["dose_accumulee"],
            "fire_alert":     bcast["fire_alert"],
            "pred_risk_class": res.get("pred_risk_class", 0),
            "pred_risk_label": res.get("pred_risk_label", "NORMAL"),
            "latitude":       d.get("latitude", 0.0),
            "longitude":      d.get("longitude", 0.0),
        }), 201

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ===============================================================
#  Reinitialiser la dose / buffer d'un casque
# ===============================================================
@app.route("/api/reset", methods=["POST"])
def api_reset():
    d = request.get_json(silent=True) or {}
    engine.reset_device(d.get("device_id", "CASQUE_001"))
    return jsonify({"status": "reset_ok"}), 200


# ===============================================================
#  Lecture etat courant + stats + meteo
# ===============================================================
@app.route("/api/latest")
def api_latest():
    with _lock:
        return jsonify(last_result), 200


# Liste de TOUS les casques actifs (multi-utilisateurs)
@app.route("/api/devices")
def api_devices():
    now = datetime.utcnow().timestamp()
    out = []
    with _lock:
        for did, b in devices.items():
            online = (now - b.get("timestamp_unix", 0)) < DEVICE_TIMEOUT
            out.append({**b, "online": online})
    out.sort(key=lambda x: (-x.get("risk_class", 0), x.get("device_id", "")))
    return jsonify({"count": len(out),
                    "online": sum(1 for d in out if d["online"]),
                    "devices": out}), 200


@app.route("/api/sim_clear", methods=["POST"])
def api_sim_clear():
    """Supprime tous les casques SIM de la flotte et remet leurs buffers a zero."""
    with _lock:
        sim_ids = [k for k in devices if k.startswith("SIM")]
        for sid in sim_ids:
            devices.pop(sid, None)
            engine.reset_device(sid)
    if sim_ids:
        socketio.emit("sim_cleared", {"removed": sim_ids})
    return jsonify({"status": "cleared", "removed": sim_ids}), 200


@app.route("/api/stats")
def api_stats():
    with _lock:
        return jsonify({
            "total_received": _stats["total"],
            "total_alerts":   _stats["alerts"],
            "models_ready":   engine.ready,
            "models":         engine.metrics,
        }), 200


@app.route("/api/workers", methods=["GET", "POST"])
def api_workers():
    if request.method == "GET":
        return jsonify(get_workers()), 200
    d = request.get_json(silent=True) or {}
    try:
        worker = save_worker(
            str(d.get("device_id", "")).strip(),
            str(d.get("worker_name", "Operateur")).strip(),
            str(d.get("zone", "Zone A")).strip(),
            str(d.get("status", "active")).strip(),
        )
        socketio.emit("worker_changed", {"action": "saved", "worker": worker})
        return jsonify(worker), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/workers/<device_id>", methods=["PATCH", "DELETE"])
def api_worker_detail(device_id):
    if request.method == "DELETE":
        existed = delete_worker(device_id)
        with _lock:
            devices.pop(device_id, None)
        engine.reset_device(device_id)
        socketio.emit("worker_changed", {"action": "deleted", "device_id": device_id})
        return jsonify({"status": "deleted" if existed else "not_found", "device_id": device_id}), 200
    d = request.get_json(silent=True) or {}
    if "status" in d and len(d.keys()) == 1:
        worker = set_worker_status(device_id, str(d.get("status", "inactive")))
    else:
        current = get_worker(device_id) or {}
        worker = save_worker(
            device_id,
            str(d.get("worker_name", current.get("worker_name", "Operateur"))).strip(),
            str(d.get("zone", current.get("zone", "Zone A"))).strip(),
            str(d.get("status", current.get("status", "active"))).strip(),
        )
    if not worker:
        return jsonify({"error": "Travailleur introuvable"}), 404
    if worker.get("status") != "active":
        with _lock:
            devices.pop(device_id, None)
        engine.reset_device(device_id)
    socketio.emit("worker_changed", {"action": "updated", "worker": worker})
    return jsonify(worker), 200


@app.route("/api/weather")
def api_weather():
    return jsonify(get_weather()), 200


# Infos serveur pour la connexion facile de l'ESP32 (affichees sur le dashboard)
@app.route("/api/server_info")
def api_server_info():
    ip = _detect_server_ip()
    esp_status = _esp32_status_payload()
    now = datetime.utcnow().timestamp()
    return jsonify({
        "ip":        ip,
        "port":      FLASK_PORT,
        "mdns":      "gazmonitor.local",
        "api_url":   f"http://{ip}:{FLASK_PORT}/api/sensor_data",
        "esp_online": esp_status["online"],
        "esp32_enabled": esp_status["desired_enabled"],
        "esp32_label": esp_status["label"],
        "esp32": esp_status,
        "c_fusion_definition": "C_fusion = concentration H2S fusionnee en ppm",
        "decision_rule": DECISION_RULE,
        "devices_online": sum(1 for b in devices.values()
                              if (now - b.get("timestamp_unix", 0)) < DEVICE_TIMEOUT),
    }), 200

# Renvoie une vraie mesure du dataset pour un niveau (presets saisie manuelle)
@app.route("/api/preset")
def api_preset():
    cls  = int(request.args.get("class", 0))
    fixed = {
        0: [2.0, 2.0, 2.0, 2.0, 62.0, 26.0],
        1: [12.0, 12.0, 12.0, 12.0, 68.0, 29.0],
        2: [25.0, 25.0, 25.0, 25.0, 74.0, 32.0],
    }
    row  = fixed.get(cls, fixed[0])
    return jsonify({
        "h2s_ppm": row[0],
        "sensor1": row[0], "sensor2": row[1], "sensor3": row[2], "sensor4": row[3],
        "sensor1_ppm": row[0], "sensor2_ppm": row[1], "sensor3_ppm": row[2], "sensor4_ppm": row[3],
        "humidity": row[4], "temperature": row[5],
    }), 200


# ===============================================================
#  SIMULATEUR (sans materiel) — genere 1 capteur selon un scenario
# ===============================================================
SIM_CLASSES = ["normal", "modere", "dangereux"]


def _scenario_for_worker(mode, worker_index, phase=0):
    """Attribue un scenario par travailleur selon le mode global."""
    if mode == "tous":
        # Chaque travailleur = un niveau different simultanement
        return ["normal", "modere", "dangereux", "montee"][worker_index % 4]
    if mode == "cycle":
        return SIM_CLASSES[(phase + worker_index) % 3]
    return mode


def _scenario_sample(cls: int):
    """Retourne des valeurs H2S qui correspondent clairement au niveau demande."""
    fixed = {
        0: [2.0, 2.0, 2.0, 2.0, 62.0, 26.0],
        1: [12.0, 12.0, 12.0, 12.0, 68.0, 29.0],
        2: [25.0, 25.0, 25.0, 25.0, 74.0, 32.0],
    }
    bank = list(_SAMPLE_BANK.get(cls) or [])
    random.shuffle(bank)
    return bank[:12] + [fixed[cls]]


def _simulate_one_worker(device_id, worker_name, zone, scenario):
    """Simule une mesure pour un casque et retourne le broadcast complet."""
    seed = sum(ord(c) for c in device_id)
    base_lat = -10.7181 + ((seed % 7) - 3) * 0.0006
    base_lng = 25.4728 + ((seed // 7 % 7) - 3) * 0.0006

    target_cls = {"normal": 0, "modere": 1, "dangereux": 2}.get(scenario, 0)
    if scenario == "montee":
        target_cls = random.choices([0, 1, 2], weights=[0.3, 0.4, 0.3])[0]

    chosen = None
    chosen_res = None
    for row in _scenario_sample(target_cls):
        h2s = float(row[0])
        sensors = [h2s, h2s, h2s, h2s]
        res = engine.process(device_id, h2s, h2s, h2s, h2s, float(row[4]), float(row[5]))
        if int(res.get("risk_class", 0)) == target_cls:
            chosen = row
            chosen_res = res
            break
        chosen = row
        chosen_res = res

    h2s = float(chosen[0])
    sensors = [h2s, h2s, h2s, h2s]
    humidity = float(chosen[4])
    temperature = float(chosen[5])
    payload = {
        "device_id": device_id,
        "worker_name": worker_name,
        "zone": zone,
        "h2s_ppm": sensors[0],
        "sensor1": sensors[0], "sensor2": sensors[1],
        "sensor3": sensors[2], "sensor4": sensors[3],
        "sensor1_ppm": sensors[0], "sensor2_ppm": sensors[1],
        "sensor3_ppm": sensors[2], "sensor4_ppm": sensors[3],
        "temperature": temperature,
        "humidity": humidity,
        "gps_valid": True,
        "latitude": base_lat + random.uniform(-0.0003, 0.0003),
        "longitude": base_lng + random.uniform(-0.0003, 0.0003),
        "altitude": 1440.0,
        "speed_kmh": round(random.uniform(0, 3), 1),
        "satellites": random.randint(6, 12),
        "hdop": round(random.uniform(0.8, 2.0), 1),
        "wifi_rssi": random.randint(-72, -55),
    }
    bcast = _build_broadcast(payload, chosen_res, sensors[0], sensors[1], sensors[2], sensors[3], temperature, humidity)
    bcast["sim_scenario"] = scenario
    bcast["sim_target_class"] = target_cls
    return bcast


@app.route("/api/simulate", methods=["POST"])
def api_simulate():
    body = request.get_json(silent=True) or {}
    bcast = _simulate_one_worker(
        body.get("device_id", "SIM_001"),
        body.get("worker_name", "Simulateur"),
        body.get("zone", "Zone Test"),
        body.get("scenario", "normal"),
    )
    with _lock:
        global last_result
        last_result = bcast
        devices[bcast["device_id"]] = bcast
        _stats["total"] += 1
    _persist_measurement(bcast, _res_from_bcast(bcast), bcast)
    _log_history(bcast)
    socketio.emit("new_data", bcast)
    return jsonify({"status": "ok", "risk_label": bcast["risk_label"], "device": bcast}), 200


@app.route("/api/simulate_fleet", methods=["POST"])
def api_simulate_fleet():
    """
    Simule TOUS les travailleurs en une seule requete atomique.
    Emet fleet_snapshot pour mise a jour simultanee du dashboard.
    """
    body = request.get_json(silent=True) or {}
    mode = body.get("scenario", "tous")
    phase = int(body.get("phase", 0))
    roster = body.get("roster") or [
        {"device_id": "SIM_001", "worker_name": "Technicien DANNY",  "zone": "Galerie Nord — niveau -120 m"},
        {"device_id": "SIM_002", "worker_name": "Foreur MUKENDI",    "zone": "Galerie Est — niveau -90 m"},
        {"device_id": "SIM_003", "worker_name": "Boutefeu KALALA",   "zone": "Puits principal — niveau -150 m"},
        {"device_id": "SIM_004", "worker_name": "Géomètre TSHALA",   "zone": "Galerie Sud — niveau -60 m"},
    ]

    results = []
    try:
        for idx, w in enumerate(roster):
            sc = _scenario_for_worker(mode, idx, phase)
            bcast = _simulate_one_worker(
                w.get("device_id", f"SIM_{idx+1:03d}"),
                w.get("worker_name", f"Operateur {idx+1}"),
                w.get("zone", "Zone Test"),
                sc,
            )
            results.append(bcast)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e), "devices": results}), 500

    if not results:
        return jsonify({"status": "error", "message": "Aucun travailleur simule"}), 500

    with _lock:
        global last_result
        for b in results:
            devices[b["device_id"]] = b
            if b["risk_class"] >= 2 or b.get("fire_alert"):
                _stats["alerts"] += 1
        _stats["total"] += len(results)
        if results:
            last_result = results[-1]

    for b in results:
        _persist_measurement(b, _res_from_bcast(b), b)
        _log_history(b)

    socketio.emit("fleet_snapshot", {
        "scenario": mode,
        "phase": phase,
        "devices": results,
        "timestamp_unix": datetime.utcnow().timestamp(),
    })
    return jsonify({
        "status": "ok",
        "scenario": mode,
        "phase": phase,
        "count": len(results),
        "devices": results,
    }), 200


# ===============================================================
#  Declenchement manuel d'une alerte INCENDIE (test / bouton panique)
# ===============================================================
@app.route("/api/fire_alert", methods=["POST"])
def api_fire_alert():
    global last_result
    with _lock:
        base = dict(last_result) if last_result else {}
    base.update({
        "timestamp":      datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_unix": datetime.utcnow().timestamp(),
        "fire_alert":     True,
        "fire_manual":    True,
    })
    base.setdefault("device_id", "CASQUE_001")
    base.setdefault("worker_name", "Operateur")
    base.setdefault("zone", "Zone A")
    base.setdefault("risk_class", 0)
    base.setdefault("temperature", 55)
    with _lock:
        last_result = base
    socketio.emit("new_data", base)
    return jsonify({"status": "fire_alert_sent"}), 200


# ===============================================================
#  EXPORT de l'historique journalier (CSV telechargeable)
# ===============================================================
#  EXPORT de l'historique des mesures H2S (CSV telechargeable)
# ===============================================================
MEASUREMENT_EXPORT_HEADER = [
    "id_mesure", "capteur_gaz", "datetime_utc", "timestamp_unix",
    "device_id", "worker_name", "zone",
    "h2s_ppm", "temperature_c", "humidity_pct", "exposure_time_s",
    "danger_level", "danger_label", "risk_probability",
    "h2s_dose", "h2s_derivative", "h2s_growth_rate", "hazard_index",
    "latitude", "longitude", "altitude_m", "speed_kmh", "satellites", "hdop", "gps_valid",
    "wifi_rssi", "created_at",
    "prediction_horizon_step", "pred_h2s", "pred_danger", "pred_label",
    "pred_risk_probability", "pred_all_probabilities",
    "alert_type", "alert_message", "alert_resolved", "alert_created_at",
]


def _measurement_export_rows(date_filter=None):
    where = ""
    params = []
    if date_filter:
        where = "WHERE substr(COALESCE(m.datetime_utc, m.created_at), 1, 10) = ?"
        params.append(date_filter)
    sql = f"""
        SELECT
            m.id AS id_mesure,
            'MQ-136' AS capteur_gaz,
            m.datetime_utc,
            m.timestamp AS timestamp_unix,
            m.device_id,
            m.worker_name,
            m.zone,
            m.h2s_ppm,
            m.temperature AS temperature_c,
            m.humidity AS humidity_pct,
            m.exposure_time_s,
            m.danger_level,
            m.danger_label,
            m.risk_probability,
            m.h2s_dose,
            m.h2s_derivative,
            m.h2s_growth_rate,
            m.hazard_index,
            m.latitude,
            m.longitude,
            m.altitude AS altitude_m,
            m.speed_kmh,
            m.satellites,
            m.hdop,
            m.gps_valid,
            m.wifi_rssi,
            m.created_at,
            p.horizon_step AS prediction_horizon_step,
            p.pred_h2s,
            p.pred_danger,
            p.pred_label,
            p.risk_probability AS pred_risk_probability,
            p.all_probabilities AS pred_all_probabilities,
            a.alert_type,
            a.message AS alert_message,
            a.resolved AS alert_resolved,
            a.created_at AS alert_created_at
        FROM measurements m
        LEFT JOIN predictions p ON p.id = (
            SELECT p2.id FROM predictions p2
            WHERE p2.measurement_id = m.id
            ORDER BY p2.id DESC LIMIT 1
        )
        LEFT JOIN alerts a ON a.id = (
            SELECT a2.id FROM alerts a2
            WHERE a2.measurement_id = m.id
            ORDER BY a2.id DESC LIMIT 1
        )
        {where}
        ORDER BY m.timestamp ASC, m.id ASC
    """
    with get_conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def _measurements_csv_response(rows, filename):
    from flask import Response
    import io
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=MEASUREMENT_EXPORT_HEADER, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    data = "\ufeff" + buf.getvalue()
    return Response(data, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename={filename}"
    })


@app.route("/api/history/dates")
def api_history_dates():
    with get_conn() as c:
        rows = c.execute("""
            SELECT DISTINCT substr(COALESCE(datetime_utc, created_at), 1, 10) AS d
            FROM measurements
            WHERE COALESCE(datetime_utc, created_at) IS NOT NULL
            ORDER BY d DESC
        """).fetchall()
    return jsonify([r["d"] for r in rows if r["d"]]), 200


@app.route("/api/history/export")
def api_history_export():
    date = request.args.get("date") or datetime.utcnow().strftime("%Y-%m-%d")
    rows = _measurement_export_rows(date)
    if not rows:
        return jsonify({"error": "Aucune mesure H2S pour cette date", "date": date}), 404
    return _measurements_csv_response(rows, f"GazMonitor_H2S_mesures_{date}.csv")


@app.route("/api/history/export_all")
def api_history_export_all():
    rows = _measurement_export_rows()
    if not rows:
        return jsonify({"error": "Aucune mesure H2S enregistree"}), 404
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    print(f"[EXPORT] Historique H2S complet : {len(rows)} mesures")
    return _measurements_csv_response(rows, f"GazMonitor_H2S_historique_complet_{stamp}.csv")


@app.route("/api/history/export_schema")
def api_history_export_schema():
    return jsonify({
        "capteur_gaz_unique": "MQ-136",
        "gaz_mesure": "H2S",
        "tables": {
            "measurements": ["h2s_ppm", "temperature", "humidity", "dose", "danger", "gps", "wifi"],
            "predictions": ["pred_h2s", "pred_danger", "pred_label", "risk_probability"],
            "alerts": ["alert_type", "danger_level", "message", "h2s_ppm"],
        },
        "c_fusion_stockage": "La colonne h2s_ppm correspond a C_fusion_ppm pour le capteur MQ-136 unique.",
        "decision_rule": DECISION_RULE,
        "colonnes_export": MEASUREMENT_EXPORT_HEADER,
        "colonnes_absentes": ["co_ppm", "sensor1", "sensor2", "sensor3", "sensor4"],
    }), 200

# ===============================================================
@app.route("/")
def dashboard():
    path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    return "<h1>GazMonitor Pro</h1><p>index.html introuvable</p>", 200


# ─── WebSocket ────────────────────────────────────────────────
# NB : on n'envoie PAS la derniere mesure a la connexion.
# Le dashboard reste en VEILLE tant qu'aucune source reelle (casque
# ESP32, simulation ou saisie manuelle) n'envoie de donnees.
@socketio.on("connect")
def on_connect():
    pass


# ===============================================================
#  Construction du payload diffuse au dashboard
# ===============================================================
def _build_broadcast(d, res, s1, s2, s3, s4, temperature, humidity):
    now = datetime.utcnow()
    return {
        "timestamp":       now.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_unix":  now.timestamp(),
        # Identite
        "device_id":   d.get("device_id",   "CASQUE_001"),
        "worker_name": d.get("worker_name", "Operateur"),
        "zone":        d.get("zone",        "Zone A"),
        # Capteurs H2S fusionnes en une seule concentration systeme
        "h2s_ppm": res["h2s_mesure"],
        "h2s_fusion_ppm": res.get("h2s_fusion_ppm", res["h2s_mesure"]),
        "c_fusion_ppm": res.get("c_fusion_ppm", res.get("h2s_fusion_ppm", res["h2s_mesure"])),
        "decision_rule": res.get("decision_rule", DECISION_RULE),
        "sensor1": s1, "sensor2": s2, "sensor3": s3, "sensor4": s4,
        "h2s_mesure":  res["h2s_mesure"],
        "temperature": temperature,
        "humidity":    humidity,
        "wifi_rssi":   d.get("wifi_rssi", -100),
        # Classification RF
        "risk_class":      res["risk_class"],
        "risk_label":      res["risk_label"],
        "risk_color":      DANGER_COLORS.get(res["risk_class"], "#22c55e"),
        "probabilities":   res["probabilities"],     # {0:..,1:..,2:..}
        # Prediction LSTM
        "prediction_h2s":   res["prediction_h2s"],
        "prediction_ready": res["prediction_ready"],
        "pred_risk_class": res.get("pred_risk_class", 0),
        "pred_risk_label": res.get("pred_risk_label", "NORMAL"),
        "pred_probabilities": res.get("pred_probabilities", {0: 1.0, 1: 0.0, 2: 0.0}),
        "pred_risk_probability": res.get("pred_risk_probability", 0.0),
        "prediction_risk_model": res.get("prediction_risk_model", ""),
        "prediction_horizon_s": res.get("prediction_horizon_s", 50),
        "buffer_fill":      res["buffer_fill"],
        "buffer_size":      res["buffer_size"],
        # Dose
        "dose_accumulee":  res["dose_accumulee"],
        "exposure_level":  res["exposure_level"],
        # Incendie : detecte si temperature >= seuil
        "fire_alert":  bool(temperature >= FIRE_TEMP_C),
        # GPS
        "gps_valid":  bool(d.get("gps_valid", False)),
        "latitude":   d.get("latitude",  0.0),
        "longitude":  d.get("longitude", 0.0),
        "altitude":   d.get("altitude",  0.0),
        "speed_kmh":  d.get("speed_kmh", 0.0),
        "satellites": d.get("satellites", 0),
        "hdop":       d.get("hdop", 99.9),
    }




def _res_from_bcast(bcast):
    return {
        "risk_class": bcast.get("risk_class", 0),
        "risk_label": bcast.get("risk_label", "NORMAL"),
        "probabilities": bcast.get("probabilities", {}),
        "h2s_mesure": bcast.get("h2s_mesure", 0.0),
        "h2s_fusion_ppm": bcast.get("h2s_fusion_ppm", bcast.get("h2s_mesure", 0.0)),
        "c_fusion_ppm": bcast.get("c_fusion_ppm", bcast.get("h2s_fusion_ppm", bcast.get("h2s_mesure", 0.0))),
        "prediction_h2s": bcast.get("prediction_h2s", 0.0),
        "pred_risk_class": bcast.get("pred_risk_class", 0),
        "pred_risk_label": bcast.get("pred_risk_label", "NORMAL"),
        "pred_risk_probability": bcast.get("pred_risk_probability", 0.0),
        "pred_probabilities": bcast.get("pred_probabilities", {}),
    }


def _persist_measurement(raw, res, bcast):
    ts = bcast.get("timestamp_unix", datetime.utcnow().timestamp())
    device_id = bcast.get("device_id", "CASQUE_001")
    worker_name = bcast.get("worker_name", "Operateur")
    zone = bcast.get("zone", "Zone A")
    probs = res.get("probabilities", {}) or {}
    level = int(res.get("risk_class", 0))
    mid = insert_measurement({
        "device_id": device_id,
        "worker_name": worker_name,
        "zone": zone,
        "timestamp": ts,
        "datetime_utc": datetime.utcnow().isoformat(),
        "h2s_ppm": float(res.get("c_fusion_ppm", res.get("h2s_mesure", bcast.get("c_fusion_ppm", bcast.get("h2s_mesure", 0.0))))),
        "temperature": bcast.get("temperature", 25.0),
        "humidity": bcast.get("humidity", 50.0),
        "exposure_time_s": raw.get("exposure_time_s", 0.0) if isinstance(raw, dict) else 0.0,
        "danger_level": level,
        "danger_label": res.get("risk_label", "NORMAL"),
        "risk_probability": float(probs.get(level, 0.0)),
        "h2s_dose": bcast.get("dose_accumulee", 0.0),
        "latitude": bcast.get("latitude", 0.0),
        "longitude": bcast.get("longitude", 0.0),
        "altitude": bcast.get("altitude", 0.0),
        "speed_kmh": bcast.get("speed_kmh", 0.0),
        "satellites": bcast.get("satellites", 0),
        "hdop": bcast.get("hdop", 99.9),
        "gps_valid": bcast.get("gps_valid", False),
        "wifi_rssi": bcast.get("wifi_rssi", -100),
    })
    upsert_worker(device_id, worker_name, zone, request.remote_addr or "", ts)
    if bcast.get("prediction_ready"):
        insert_prediction(
            mid, 1, bcast.get("prediction_h2s", 0.0),
            int(bcast.get("pred_risk_class", 0)),
            bcast.get("pred_risk_label", "NORMAL"),
            float(bcast.get("pred_risk_probability", 0.0)),
            bcast.get("pred_probabilities", {}),
        )
    return mid


def _build_idle_state():
    now = datetime.utcnow()
    return {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_unix": now.timestamp(),
        "system_state": "idle",
        "device_id": "AUCUN_CASQUE",
        "worker_name": "Veille",
        "zone": "Systeme en attente",
        "sensor1": 0.0, "sensor2": 0.0, "sensor3": 0.0, "sensor4": 0.0,
        "h2s_mesure": 0.0,
        "h2s_fusion_ppm": 0.0,
        "c_fusion_ppm": 0.0,
        "decision_rule": DECISION_RULE,
        "temperature": 0.0,
        "humidity": 0.0,
        "wifi_rssi": 0,
        "risk_class": 0,
        "risk_label": "NORMAL",
        "risk_color": DANGER_COLORS.get(0, "#22c55e"),
        "probabilities": {0: 1.0, 1: 0.0, 2: 0.0},
        "prediction_h2s": 0.0,
        "prediction_ready": False,
        "prediction_horizon_s": getattr(engine, "horizon_s", 50),
        "pred_risk_class": 0,
        "pred_risk_label": "NORMAL",
        "pred_probabilities": {0: 1.0, 1: 0.0, 2: 0.0},
        "pred_risk_probability": 1.0,
        "prediction_risk_model": "idle",
        "buffer_fill": 0,
        "buffer_size": getattr(engine, "window", 60),
        "dose_accumulee": 0.0,
        "exposure_level": "Faible",
        "fire_alert": False,
        "gps_valid": False,
        "latitude": 0.0,
        "longitude": 0.0,
        "altitude": 0.0,
        "speed_kmh": 0.0,
        "satellites": 0,
        "hdop": 99.9,
    }


LOGIN_HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connexion administrateur - GazMonitor Pro</title>
<link rel="icon" type="image/png" href="/static/casque_iot.png">
<style>
:root{
  --bg:#07111f;--panel:#101827;--panel2:#151f31;--line:#2a374d;
  --tx:#eef5ff;--muted:#9aa8be;--accent:#2f6df0;--h2s:#0ea5c7;
  --ok:#16a34a;--danger:#dc2626;--warn:#d09200;
}
*{box-sizing:border-box}html,body{height:100%}
body{
  margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;
  color:var(--tx);font-family:Segoe UI,Inter,system-ui,-apple-system,sans-serif;
  background:
    radial-gradient(circle at 16% 18%,rgba(47,109,240,.22),transparent 30%),
    radial-gradient(circle at 84% 20%,rgba(14,165,199,.18),transparent 28%),
    linear-gradient(135deg,#060b14 0%,#0a1424 54%,#080d16 100%);
  overflow-x:hidden;
}
body:before{
  content:"";position:fixed;inset:0;pointer-events:none;opacity:.18;
  background-image:linear-gradient(rgba(255,255,255,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.055) 1px,transparent 1px);
  background-size:42px 42px;
}
.shell{width:min(980px,100%);display:grid;grid-template-columns:1.08fr .92fr;gap:0;
  border:1px solid rgba(148,163,184,.24);border-radius:24px;overflow:hidden;
  background:linear-gradient(180deg,rgba(16,24,39,.92),rgba(8,13,22,.94));
  box-shadow:0 30px 80px rgba(0,0,0,.45),inset 0 1px 0 rgba(255,255,255,.06);
  position:relative;
}
.visual{position:relative;min-height:560px;padding:34px;display:flex;flex-direction:column;justify-content:space-between;
  background:linear-gradient(145deg,rgba(47,109,240,.16),rgba(14,165,199,.06));
}
.brand{display:flex;align-items:center;gap:12px}.logo{width:46px;height:46px;border-radius:14px;object-fit:cover;background:#fff;border:1px solid rgba(255,255,255,.25);box-shadow:0 10px 28px rgba(0,0,0,.34)}
.brand h1{font-size:1.15rem;margin:0;letter-spacing:.01em}.brand p{margin:2px 0 0;color:var(--muted);font-size:.78rem}
.hero{display:grid;place-items:center;min-height:300px}.hero img{width:min(430px,95%);filter:drop-shadow(0 28px 36px rgba(0,0,0,.55));transform:translateY(8px)}
.visual h2{font-size:1.55rem;line-height:1.15;margin:0 0 10px}.visual .copy{max-width:470px;color:#c8d4e6;font-size:.9rem;line-height:1.55;margin:0}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}.chip{border:1px solid rgba(148,163,184,.25);background:rgba(8,13,22,.48);border-radius:999px;padding:7px 11px;font-size:.72rem;color:#dbe8f8;font-weight:700}.chip.ok{color:#bbf7d0;border-color:rgba(22,163,74,.35)}
.formside{padding:42px 42px 36px;background:rgba(8,13,22,.68);display:flex;align-items:center}.login{width:100%}
.kicker{display:inline-flex;align-items:center;gap:8px;color:#b7cdfb;border:1px solid rgba(47,109,240,.35);background:rgba(47,109,240,.10);padding:7px 11px;border-radius:999px;font-size:.72rem;font-weight:800;margin-bottom:22px}
.kicker:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 5px rgba(22,163,74,.14)}
h3{font-size:1.72rem;margin:0 0 8px}.sub{margin:0 0 28px;color:var(--muted);font-size:.88rem;line-height:1.45}
.field{margin:15px 0}.field label{display:block;font-size:.72rem;color:#b6c3d6;margin:0 0 7px;font-weight:800;letter-spacing:.02em;text-transform:uppercase}
.control{position:relative}.control input{width:100%;height:48px;border:1px solid var(--line);background:#0b1220;color:#f8fafc;border-radius:12px;padding:0 14px 0 42px;font-size:.95rem;outline:none;transition:.16s}.control input:focus{border-color:var(--accent);box-shadow:0 0 0 4px rgba(47,109,240,.15)}
.ico{position:absolute;left:14px;top:50%;transform:translateY(-50%);color:#7f8da3;font-size:1rem}.meta{display:flex;justify-content:space-between;align-items:center;margin-top:14px;color:var(--muted);font-size:.75rem}.meta b{color:#dbeafe}
button{width:100%;height:48px;margin-top:22px;border:0;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--h2s));color:#fff;font-size:.92rem;font-weight:900;letter-spacing:.01em;cursor:pointer;box-shadow:0 16px 34px rgba(47,109,240,.26);transition:.15s}button:hover{transform:translateY(-1px);filter:brightness(1.06)}button:disabled{opacity:.68;cursor:wait;transform:none}
.err{min-height:22px;margin-top:14px;color:#fecaca;background:rgba(220,38,38,.10);border:1px solid rgba(220,38,38,.28);border-radius:10px;padding:9px 11px;font-size:.78rem;display:none}.err.show{display:block}
.foot{margin-top:24px;padding-top:18px;border-top:1px solid rgba(148,163,184,.16);display:grid;gap:7px;color:#74849a;font-size:.72rem}.foot span{display:flex;justify-content:space-between;gap:14px}.foot b{color:#aebbd0}
@media(max-width:820px){body{padding:14px}.shell{grid-template-columns:1fr}.visual{min-height:auto;padding:24px}.hero img{width:min(320px,90%)}.formside{padding:28px 22px}.visual h2{font-size:1.28rem}}
</style>
</head>
<body>
<main class="shell">
  <section class="visual">
    <div class="brand"><img class="logo" src="/static/casque_iot.png" alt="Casque IoT GazMonitor"><div><h1>GazMonitor Pro</h1><p>Surveillance intelligente H2S</p></div></div>
    <div class="hero"><img src="/static/casque_iot.png" alt="Prototype casque IoT avec ESP32 et capteur MQ-136"></div>
    <div>
      <h2>Acces administrateur securise</h2>
      <p class="copy">Supervision du casque IoT, suivi des mesures H2S, connectivite ESP32 et alertes temps reel pour la mine KCC Kamoto.</p>
      <div class="chips"><span class="chip ok">MQ-136 H2S</span><span class="chip">ESP32 Wi-Fi</span><span class="chip">Dashboard Flask</span><span class="chip">IA RF + LSTM</span></div>
    </div>
  </section>
  <section class="formside">
    <form class="login" id="login-form">
      <div class="kicker">Session administrateur</div>
      <h3>Connexion</h3>
      <p class="sub">Entrez vos identifiants pour acceder au tableau de bord de surveillance.</p>
      <div class="field"><label>Nom utilisateur</label><div class="control"><span class="ico">@</span><input name="username" autocomplete="username" value="admin" required></div></div>
      <div class="field"><label>Mot de passe</label><div class="control"><span class="ico">*</span><input name="password" type="password" autocomplete="current-password" autofocus required></div></div>
      <div class="meta"><span>Serveur local</span><b>Port 8080</b></div>
      <button id="submit-btn" type="submit">Se connecter</button>
      <div class="err" id="err"></div>
      <div class="foot"><span><b>Gaz mesure</b>H2S uniquement</span><span><b>Equipement</b>Casque IoT ESP32</span><span><b>Acces</b>Administrateur</span></div>
    </form>
  </section>
</main>
<script>
const form=document.getElementById('login-form');
const btn=document.getElementById('submit-btn');
const errBox=document.getElementById('err');
form.addEventListener('submit',async e=>{
  e.preventDefault();
  errBox.classList.remove('show');
  errBox.textContent='';
  btn.disabled=true;
  btn.textContent='Verification...';
  const fd=new FormData(form);
  try{
    const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:fd.get('username'),password:fd.get('password')})});
    if(r.ok){location.href='/';return;}
    const d=await r.json().catch(()=>({}));
    errBox.textContent=d.error||'Connexion refusee';
    errBox.classList.add('show');
  }catch(ex){
    errBox.textContent='Serveur momentanement inaccessible';
    errBox.classList.add('show');
  }finally{
    btn.disabled=false;
    btn.textContent='Se connecter';
  }
});
</script>
</body>
</html>"""

if __name__ == "__main__":
    startup()
    socketio.run(app, host=FLASK_HOST, port=FLASK_PORT,
                 debug=False, use_reloader=False, allow_unsafe_werkzeug=True)


