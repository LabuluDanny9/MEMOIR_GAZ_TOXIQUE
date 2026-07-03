"""
Service meteo temps reel — Open-Meteo API (gratuit, sans cle).
Fournit temperature et humidite pour KCC Kamoto Mine, Kolwezi, Lualaba, RDC.
Cache les donnees 10 minutes pour limiter les appels reseau.
"""

import requests
import threading
import time
from datetime import datetime

# KCC - Kamoto Copper Company, Kolwezi, Lualaba, RDC
LAT = -10.7181
LNG = 25.4728
SITE_NAME = "KCC Kamoto Mine, Kolwezi"

_OPEN_METEO_URL = (
    f"https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LNG}"
    "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature"
    "&timezone=Africa%2FLubumbashi"
    "&forecast_days=1"
)

_WMO_DESCRIPTIONS = {
    0: "Ciel dégagé", 1: "Principalement dégagé", 2: "Partiellement nuageux",
    3: "Couvert", 45: "Brouillard", 48: "Brouillard givrant",
    51: "Bruine légère", 53: "Bruine modérée", 55: "Bruine dense",
    61: "Pluie légère", 63: "Pluie modérée", 65: "Pluie forte",
    80: "Averses légères", 81: "Averses modérées", 82: "Averses violentes",
    95: "Orage", 96: "Orage avec grêle", 99: "Orage violent",
}

_cache = {
    "temperature":         None,
    "humidity":            None,
    "apparent_temperature": None,
    "weather_code":        None,
    "weather_description": None,
    "wind_speed":          None,
    "fetched_at":          None,
    "error":               None,
}
_lock     = threading.Lock()
CACHE_TTL = 600  # 10 minutes


def fetch_weather() -> bool:
    global _cache
    try:
        r = requests.get(_OPEN_METEO_URL, timeout=6)
        r.raise_for_status()
        current = r.json().get("current", {})
        code    = current.get("weather_code")
        with _lock:
            _cache = {
                "temperature":          current.get("temperature_2m"),
                "humidity":             current.get("relative_humidity_2m"),
                "apparent_temperature": current.get("apparent_temperature"),
                "weather_code":         code,
                "weather_description":  _WMO_DESCRIPTIONS.get(code, "Inconnu"),
                "wind_speed":           current.get("wind_speed_10m"),
                "fetched_at":           datetime.utcnow().isoformat(),
                "error":                None,
            }
        print(f"[METEO] {_cache['temperature']}°C  HR={_cache['humidity']}%  "
              f"vent={_cache['wind_speed']}km/h  {_cache['weather_description']}")
        return True
    except Exception as e:
        with _lock:
            _cache["error"] = str(e)
        print(f"[METEO] Erreur : {e}")
        return False


def get_weather() -> dict:
    with _lock:
        fetched = _cache["fetched_at"]

    if fetched is None:
        fetch_weather()
    else:
        age = (datetime.utcnow() - datetime.fromisoformat(fetched)).total_seconds()
        if age > CACHE_TTL:
            fetch_weather()

    with _lock:
        return dict(_cache)


def get_temperature() -> float | None:
    return get_weather().get("temperature")


def get_humidity() -> float | None:
    return get_weather().get("humidity")


def start_background_refresh(interval: int = 600):
    """Lance un thread daemon qui rafraîchit la météo toutes les `interval` secondes."""
    def _loop():
        fetch_weather()          # premier appel immédiat
        while True:
            time.sleep(interval)
            fetch_weather()
    threading.Thread(target=_loop, daemon=True, name="weather-refresh").start()
