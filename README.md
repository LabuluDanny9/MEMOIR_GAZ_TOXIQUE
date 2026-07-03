# Système Intelligent de Surveillance Industrielle des Gaz Toxiques
### IoT + ESP32 + GPS + Random Forest + LSTM

---

## Démarrage rapide (Windows)

```
Étape 1 — Double-cliquez sur :  install.bat
Étape 2 — Double-cliquez sur :  start.bat          (serveur seul)
           OU                   start_demo.bat      (avec simulateur ESP32)
```

Le navigateur s'ouvre automatiquement sur `http://localhost:5000`

---

## Architecture

```
ESP32 + Capteurs (H₂S / CO / T° / Humidité) + GPS NEO-6M
       │
       │  HTTP POST  (JSON, toutes les 5s, WiFi)
       ▼
Serveur Flask  (Python)
       │
       ├── Base de données SQLite
       ├── Calculs physiques  (Dose, dC/dt, k, Indice HI)
       ├── Random Forest      → Classification danger (Normal/Moyen/Dangereux/Critique)
       ├── LSTM Bidirectionnel→ Prédiction 50 secondes à l'avance
       └── WebSocket          → Dashboard temps réel
```

---

## Capteurs ESP32

| Capteur | Paramètre mesuré | Pin ESP32 |
|---------|-----------------|-----------|
| MQ-136  | H₂S (ppm)       | GPIO 34   |
| MQ-7    | CO (ppm)        | GPIO 35   |
| DHT22   | Température (°C) / Humidité (%) | GPIO 4 |
| NEO-6M  | GPS (lat, lng, alt, vitesse) | UART2 (RX=16, TX=17) |
| LED verte| Statut OK       | GPIO 2    |
| LED rouge| Alerte          | GPIO 15   |

### Librairies Arduino (Library Manager) :
- `DHT sensor library` (Adafruit)
- `ArduinoJson` (Benoit Blanchon)
- `TinyGPS++` (Mikal Hart)

### Configuration firmware (`esp32/esp32_sensors_gps.ino`) :
```cpp
const char* WIFI_SSID     = "VOTRE_SSID";
const char* WIFI_PASSWORD = "VOTRE_MOT_DE_PASSE";
const char* SERVER_IP     = "192.168.X.X";   // IP de votre PC
```

---

## Seuils toxicologiques (NIOSH/ACGIH)

| Gaz | TWA (8h) | STEL (15min) | IDLH |
|-----|----------|-------------|------|
| H₂S | 1 ppm   | 5 ppm       | 50 ppm  |
| CO  | 25 ppm  | 100 ppm     | 1200 ppm |

### Niveaux de danger :
- **Normal**    : H₂S < 1 ppm   ET CO < 25 ppm
- **Moyen**     : H₂S < 10 ppm  ET CO < 50 ppm
- **Dangereux** : H₂S < 50 ppm  ET CO < 200 ppm
- **Critique**  : H₂S ≥ 50 ppm  OU CO ≥ 200 ppm

---

## Structure du projet

```
gas_monitoring_system/
├── esp32/
│   └── esp32_sensors_gps.ino    ← Firmware ESP32 (C++)
├── server/
│   ├── app.py                   ← Serveur Flask + WebSocket
│   ├── database.py              ← SQLite
│   ├── physical_calculations.py ← D=∫Cdt, k, dC/dt, HI
│   ├── ml_models.py             ← Random Forest + LSTM
│   ├── real_time_analyzer.py    ← Orchestrateur pipeline
│   └── alert_system.py          ← Alertes intelligentes
├── data/
│   └── generate_dataset.py      ← Générateur 3000 enregistrements
├── notebooks/
│   └── gas_monitoring_complete.ipynb  ← Notebook Jupyter complet
├── static/
│   └── index.html               ← Dashboard web (Leaflet + Chart.js)
├── models/                      ← Modèles ML sauvegardés
├── logs/                        ← Logs du système
├── config.py                    ← Configuration centrale
├── run_server.py                ← Point d'entrée Python
├── install.bat                  ← Installation Windows (1 clic)
├── start.bat                    ← Démarrage normal
├── start_demo.bat               ← Démarrage + simulateur ESP32
└── start_train.bat              ← Réentraîner les modèles ML
```

---

## API REST

| Méthode | Endpoint            | Description                          |
|---------|---------------------|--------------------------------------|
| POST    | `/api/sensor_data`  | Réception données ESP32              |
| GET     | `/api/latest`       | Dernière mesure analysée             |
| GET     | `/api/history`      | Historique (param: `limit`, `device_id`) |
| GET     | `/api/stats`        | Statistiques + état modèles ML       |
| GET     | `/api/devices`      | Liste des casques connectés          |
| GET     | `/api/alerts`       | Dernières alertes                    |
| POST    | `/api/simulate`     | Simuler une mesure ESP32             |
| POST    | `/api/train`        | Réentraîner les modèles ML           |

### Exemple payload ESP32 → Serveur :
```json
{
  "device_id":      "CASQUE_001",
  "worker_name":    "Ahmed Technicien",
  "zone":           "Zone B3 Raffinerie",
  "h2s_ppm":        2.34,
  "co_ppm":         45.6,
  "temperature":    28.5,
  "humidity":       62.0,
  "exposure_time_s": 300,
  "wifi_rssi":      -65,
  "gps_valid":      true,
  "latitude":       36.753800,
  "longitude":       3.058800,
  "altitude":       205.0,
  "speed_kmh":      1.2,
  "satellites":     9,
  "hdop":           1.1
}
```

---

## Lancement sans l'ESP32 (mode démo)

```bash
python run_server.py --demo
```
Ou double-cliquez sur `start_demo.bat`

Le simulateur envoie automatiquement des données toutes les 5 secondes avec des scénarios variés (normal, montée progressive, pic critique, oscillations).

---

## Dépannage

**Le serveur ne démarre pas :**
- Vérifiez que Python 3.10+ est installé
- Exécutez `install.bat` en premier

**Les modèles ML ne chargent pas :**
- Exécutez `start_train.bat` pour les entraîner
- Ou cliquez sur "(Ré)entraîner les modèles ML" dans le dashboard

**L'ESP32 ne se connecte pas au serveur :**
- Vérifiez que le PC et l'ESP32 sont sur le même réseau WiFi
- Trouvez l'IP de votre PC : `ipconfig` dans cmd
- Modifiez `SERVER_IP` dans le firmware

**Le GPS ne fixe pas :**
- Placez le module GPS en extérieur ou près d'une fenêtre
- Le fix initial peut prendre 1-3 minutes (cold start)
- Vérifiez les connexions UART (RX↔TX croisés)
