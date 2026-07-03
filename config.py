"""
Configuration centrale — Systeme de surveillance des gaz toxiques.
Seuils toxicologiques bases sur NIOSH/OSHA/ACGIH.
Cas d'usage : Mine souterraine KCC (Kamoto Copper Company), Kolwezi, Lualaba, RDC.

References officielles :
  [1] NIOSH Pocket Guide to Chemical Hazards - H2S
      REL : 10 ppm (plafond, ne jamais depasser sur la periode de travail)
      IDLH: 100 ppm (danger immediat pour la vie ou la sante)
  [2] OSHA - Hydrogen Sulfide Fact Sheet
      PEL : 20 ppm (plafond general), pic acceptable 50 ppm / 10 min
  [3] ACGIH - Threshold Limit Values
      TLV-TWA : 1 ppm | TLV-STEL : 5 ppm
  [4] NIOSH - Carbon Monoxide
      REL : 35 ppm (TWA 10h) | IDLH : 1200 ppm
  [5] OSHA - Carbon Monoxide
      PEL : 50 ppm (TWA 8h)
  [6] ACGIH - TLV-TWA CO : 25 ppm
"""

import os

# --- CHEMINS ---------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
MODELS_DIR  = os.path.join(BASE_DIR, "models")
LOGS_DIR    = os.path.join(BASE_DIR, "logs")
STATIC_DIR  = os.path.join(BASE_DIR, "static")
DB_PATH     = os.path.join(BASE_DIR, "gas_monitoring.db")

# --- SERVEUR FLASK ---------------------------------------------
FLASK_HOST  = "0.0.0.0"
FLASK_PORT  = 8080        # Port interne Flask (5000 occupe par un autre serveur)
HTTP_PORT   = 80          # Port public (portproxy 80->8080)
FLASK_DEBUG = False
SECRET_KEY  = "kcc_gazmonitor_2026"
MDNS_NAME   = "gazmonitor"  # Accessible via http://gazmonitor.local

# ===============================================================
#  CLASSIFICATION DU RISQUE H2S — 3 niveaux (modeles pre-entraines)
#  Sortie du Random Forest : Risk_Class
#  Surveillance H2S uniquement (le CO n'est plus surveille)
# ===============================================================
DANGER_CLASSES = {
    0: "NORMAL",      # Vert  — environnement sain
    1: "MODERE",      # Jaune — surveillance accrue
    2: "DANGEREUX",   # Rouge — alerte, port des EPI / evacuation
}

DANGER_COLORS = {
    0: "#22c55e",  # Vert
    1: "#eab308",  # Jaune
    2: "#ef4444",  # Rouge
}

# Features attendues par les modeles (ordre EXACT)
H2S_FEATURES = ["Sensor1[ppm]", "Sensor2[ppm]", "Sensor3[ppm]",
                "Sensor4[ppm]", "Humidity[%]", "Temperature[C]"]

# LSTM : fenetre temporelle (modele pre-entraine)
LSTM_WINDOW = 20
# Plage d'entrainement du LSTM (H2S en ppm)
H2S_TRAIN_MIN = 2.0
H2S_TRAIN_MAX = 25.0

# --- ACQUISITION ESP32 -----------------------------------------
ACQUISITION_PERIOD_S = 5
BUFFER_SIZE          = 1000
