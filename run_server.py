"""
KCC GazMonitor — Serveur de production
Surveillance des gaz toxiques | Mine Kamoto, Kolwezi, Lualaba, RDC

Usage :
    python run_server.py          # Production (Waitress)
    python run_server.py --demo   # Avec simulateur ESP32
    python run_server.py --train  # Force re-entrainement ML
"""

import sys, os, threading, time, socket
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Certificat TLS auto-signe (genere une seule fois, valable 10 ans)
_BASE = os.path.dirname(os.path.abspath(__file__))
SSL_DIR  = os.path.join(_BASE, "ssl")
SSL_CERT = os.path.join(SSL_DIR, "cert.pem")
SSL_KEY  = os.path.join(SSL_DIR, "key.pem")


_SSL_FLAG = os.path.join(SSL_DIR, "cert_installed.flag")


def _install_cert_windows(cert_file):
    """Installe le cert dans le magasin de confiance Windows (Chrome/Edge).
    Utilise le magasin utilisateur => pas besoin de droits admin."""
    import subprocess
    try:
        r = subprocess.run(
            ["certutil", "-addstore", "-user", "-f", "Root", cert_file],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            # Marque l'installation pour ne pas repeter a chaque demarrage
            open(_SSL_FLAG, "w").write("ok")
            print("[TLS] Certificat installe dans Windows (Chrome/Edge) => cadenas vert")
            return True
        print(f"[TLS] certutil : {(r.stdout + r.stderr).strip()[:120]}")
        return False
    except FileNotFoundError:
        print("[TLS] certutil introuvable")
        return False
    except Exception as e:
        print(f"[TLS] Erreur installation cert : {e}")
        return False


def gen_ssl_cert():
    """Genere le certificat TLS auto-signe et l'installe dans Windows. Retourne True si OK."""
    os.makedirs(SSL_DIR, exist_ok=True)
    newly_generated = False

    if not (os.path.exists(SSL_CERT) and os.path.exists(SSL_KEY)):
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            import datetime, ipaddress

            key  = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            lip  = get_local_ip()
            subj = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME,       "GazMonitor Pro"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "KCC Kamoto"),
                x509.NameAttribute(NameOID.COUNTRY_NAME,      "CD"),
            ])
            san_ips = [x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
            try: san_ips.append(x509.IPAddress(ipaddress.IPv4Address(lip)))
            except Exception: pass

            cert = (x509.CertificateBuilder()
                .subject_name(subj).issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName([
                    x509.DNSName("gazmonitor.local"),
                    x509.DNSName("localhost"),
                    *san_ips,
                ]), critical=False)
                .sign(key, hashes.SHA256()))

            with open(SSL_KEY, "wb") as f:
                f.write(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.TraditionalOpenSSL,
                                          serialization.NoEncryption()))
            with open(SSL_CERT, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            print(f"[TLS] Certificat genere : {SSL_CERT}")
            newly_generated = True
        except Exception as e:
            print(f"[TLS] Generation impossible ({e}) — mode HTTP")
            return False

    # Installation dans le magasin Windows si pas encore fait
    if newly_generated or not os.path.exists(_SSL_FLAG):
        _install_cert_windows(SSL_CERT)

    return True


def get_local_ip():
    """
    Retourne la vraie IP du PC sur le reseau WiFi local (joignable par l'ESP32).
    Ignore les adaptateurs VPN (ProtonVPN 10.2.x) et virtuels (VirtualBox 192.168.56.x)
    qui ne sont PAS accessibles depuis l'ESP32.
    """
    import re, subprocess

    def is_bad(ip):
        return (ip.startswith("127.") or ip.startswith("169.254.") or
                ip.startswith("10.2.0.") or          # ProtonVPN
                ip.startswith("192.168.56.") or       # VirtualBox
                ip.startswith("172.")                  # Docker/Hyper-V
                )

    # 1) Lire ipconfig et prioriser l'adaptateur Wi-Fi
    try:
        out = subprocess.run(["ipconfig"], capture_output=True,
                             text=True, encoding="latin-1").stdout
        # Section Wi-Fi en priorite
        m = re.search(r"(sans fil Wi-Fi.*?)(?=\nCarte |\Z)", out, re.S)
        if m:
            ip = re.search(r"IPv4.*?:\s*([\d.]+)", m.group(1))
            if ip and not is_bad(ip.group(1)):
                return ip.group(1)
        # Sinon n'importe quelle IPv4 LAN valide
        for ip in re.findall(r"IPv4.*?:\s*([\d.]+)", out):
            if not is_bad(ip):
                return ip
    except Exception:
        pass

    # 2) Fallback : socket UDP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if not is_bad(ip):
            return ip
    except Exception:
        pass
    return "127.0.0.1"


def start_mdns(host, port, name="gazmonitor"):
    """
    Enregistre le serveur sur le reseau via mDNS (Bonjour).
    Permet l'acces via http://gazmonitor.local sans connaitre l'IP.
    L'ESP32 peut aussi trouver le serveur via MDNS.queryHost("gazmonitor").
    """
    try:
        from zeroconf import Zeroconf, ServiceInfo
        import socket as s
        zc   = Zeroconf()
        ip_b = s.inet_aton(host if host != "0.0.0.0" else get_local_ip())
        info = ServiceInfo(
            "_http._tcp.local.",
            f"{name}._http._tcp.local.",
            addresses=[ip_b],
            port=port,
            properties={"path": "/", "version": "2.0"},
        )
        zc.register_service(info)
        print(f"[mDNS] Service enregistre : http://{name}.local:{port}")
        return zc
    except Exception as e:
        print(f"[mDNS] Non disponible ({e}) — acces par IP uniquement")
        return None


def run_demo(server_url, n=500):
    """Simule un casque en utilisant le simulateur integre (vraies donnees)."""
    import requests, random
    print(f"\n[DEMO] Simulateur casque : {server_url}")
    scenarios = ["normal", "normal", "modere", "montee", "dangereux"]
    for i in range(n):
        sc = random.choice(scenarios)
        try:
            r = requests.post(f"{server_url}/api/simulate", json={"scenario": sc}, timeout=4)
            d = r.json()
            print(f"[SIM #{i+1:3d}] scenario={sc:10s} -> {d.get('risk_label','?')}")
        except Exception as e:
            print(f"[SIM] Erreur : {e}")
        time.sleep(5)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GazMonitor Pro Server")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()

    from config import FLASK_HOST, FLASK_PORT
    from server.app import app, socketio, startup
    # Mode production : aucun debug, aucun rechargement
    app.debug = False
    app.config["ENV"] = "production"
    app.config["PROPAGATE_EXCEPTIONS"] = True

    # Initialisation
    startup()

    local_ip = get_local_ip()

    # Certificat TLS genere en reserve (pour futur reverse-proxy nginx/caddy)
    gen_ssl_cert()

    # mDNS — acces par nom http://gazmonitor.local
    _zc = start_mdns(local_ip, FLASK_PORT)

    # Simulateur demo si demande
    if args.demo:
        def _demo():
            time.sleep(5)
            run_demo(f"http://127.0.0.1:{FLASK_PORT}")
        threading.Thread(target=_demo, daemon=True, name="demo").start()

    # Banniere
    print()
    print("=" * 60)
    print("  GazMonitor Pro — Surveillance H2S  (production)")
    print("  Mine souterraine KCC Kamoto, Kolwezi, Lualaba, RDC")
    print("=" * 60)
    print(f"  Dashboard reseau : http://{local_ip}:{FLASK_PORT}")
    print(f"  Dashboard local  : http://localhost:{FLASK_PORT}")
    print(f"  Nom reseau       : http://gazmonitor.local")
    print(f"  API casque       : POST http://{local_ip}:{FLASK_PORT}/api/sensor_data")
    print("=" * 60)
    print("  Ctrl+C pour arreter")
    print()

    # --- Mode PRODUCTION : pas de debug, pas de reloader, logs silencieux ---
    import logging, warnings
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore")
    try:
        import flask.cli
        flask.cli.show_server_banner = lambda *a, **k: None
    except Exception:
        pass

    print("[SERVER] Serveur temps reel actif (WebSocket · HTTP)")
    socketio.run(app, host=FLASK_HOST, port=FLASK_PORT,
                 debug=False, use_reloader=False,
                 log_output=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
