"""
Open-Meteo service for GazMonitor Pro.
Provides temperature and relative humidity for the mine environment without an API key.
Values are cached to avoid a network request for every ESP32 packet.
"""

from datetime import datetime
import threading
import time
from urllib.parse import urlencode

import requests

# KCC - Kamoto Copper Company, Kolwezi, Lualaba, RDC
DEFAULT_LAT = -10.7181
DEFAULT_LNG = 25.4728
SITE_NAME = "KCC Kamoto Mine, Kolwezi"
CACHE_TTL = 600  # 10 minutes

_WMO_DESCRIPTIONS = {
    0: "Ciel degage", 1: "Principalement degage", 2: "Partiellement nuageux",
    3: "Couvert", 45: "Brouillard", 48: "Brouillard givrant",
    51: "Bruine legere", 53: "Bruine moderee", 55: "Bruine dense",
    61: "Pluie legere", 63: "Pluie moderee", 65: "Pluie forte",
    80: "Averses legeres", 81: "Averses moderees", 82: "Averses violentes",
    95: "Orage", 96: "Orage avec grele", 99: "Orage violent",
}

_cache = {}
_lock = threading.Lock()


def _safe_coord(value, default):
    try:
        value = float(value)
        if value != value:
            return default
        return value
    except (TypeError, ValueError):
        return default


def _cache_key(latitude=None, longitude=None):
    lat = round(_safe_coord(latitude, DEFAULT_LAT), 4)
    lng = round(_safe_coord(longitude, DEFAULT_LNG), 4)
    return lat, lng


def _empty_payload(latitude=None, longitude=None, error=None):
    lat, lng = _cache_key(latitude, longitude)
    return {
        "temperature": None,
        "humidity": None,
        "apparent_temperature": None,
        "weather_code": None,
        "weather_description": None,
        "wind_speed": None,
        "fetched_at": None,
        "error": error,
        "latitude": lat,
        "longitude": lng,
        "site": SITE_NAME,
        "provider": "Open-Meteo",
    }


def _build_url(latitude, longitude):
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,apparent_temperature",
        "timezone": "Africa/Lubumbashi",
        "forecast_days": 1,
    }
    return "https://api.open-meteo.com/v1/forecast?" + urlencode(params)


def fetch_weather(latitude=None, longitude=None):
    lat, lng = _cache_key(latitude, longitude)
    try:
        response = requests.get(_build_url(lat, lng), timeout=6)
        response.raise_for_status()
        current = response.json().get("current", {})
        code = current.get("weather_code")
        payload = {
            "temperature": current.get("temperature_2m"),
            "humidity": current.get("relative_humidity_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "weather_code": code,
            "weather_description": _WMO_DESCRIPTIONS.get(code, "Inconnu"),
            "wind_speed": current.get("wind_speed_10m"),
            "fetched_at": datetime.utcnow().isoformat(),
            "error": None,
            "latitude": lat,
            "longitude": lng,
            "site": SITE_NAME,
            "provider": "Open-Meteo",
        }
        with _lock:
            _cache[(lat, lng)] = payload
        print(f"[METEO] {lat},{lng} -> {payload['temperature']} C | HR={payload['humidity']}% | {payload['weather_description']}")
        return dict(payload)
    except Exception as exc:
        with _lock:
            previous = dict(_cache.get((lat, lng), _empty_payload(lat, lng)))
            previous["error"] = str(exc)
            _cache[(lat, lng)] = previous
        print(f"[METEO] Erreur Open-Meteo : {exc}")
        return previous


def get_weather(latitude=None, longitude=None, force=False):
    lat, lng = _cache_key(latitude, longitude)
    with _lock:
        cached = dict(_cache.get((lat, lng), {}))
    if force or not cached.get("fetched_at"):
        return fetch_weather(lat, lng)
    try:
        age = (datetime.utcnow() - datetime.fromisoformat(cached["fetched_at"])).total_seconds()
    except Exception:
        age = CACHE_TTL + 1
    if age > CACHE_TTL:
        return fetch_weather(lat, lng)
    return cached


def get_temperature():
    return get_weather().get("temperature")


def get_humidity():
    return get_weather().get("humidity")


def start_background_refresh(interval=600):
    def _loop():
        fetch_weather(DEFAULT_LAT, DEFAULT_LNG)
        while True:
            time.sleep(interval)
            fetch_weather(DEFAULT_LAT, DEFAULT_LNG)
    threading.Thread(target=_loop, daemon=True, name="weather-refresh").start()
