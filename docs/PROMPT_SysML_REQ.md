# Prompt — Génération Diagramme SysML REQ Casque H₂S

## Prompt complet (ChatGPT / Claude / Gemini)

```
Tu es un ingénieur systèmes spécialisé SysML.
Génère le diagramme des exigences SysML (REQ) complet en syntaxe
PlantUML pour un casque de sécurité industriel connecté, basé sur
les spécifications suivantes :

CONTEXTE :
- Casque intelligent pour mines de cuivre (Gécamines, Lubumbashi,
  Haut-Katanga, RDC)
- MCU : ESP32-WROOM-32 (240 MHz dual-core, WiFi 802.11 b/g/n)
- Serveur central : Flask + SocketIO, Python 3.10

STRUCTURE DES EXIGENCES (9 groupes) :

REQ-000 — Exigence racine
  Surveillance continue H₂S + CO, GPS, transmission 5s, milieu minier

REQ-100 — Détection des gaz
  REQ-101 H₂S : MQ-136, 0-100 ppm, IDLH=50 ppm, ADC GPIO34
  REQ-102 CO  : MQ-7, 0-1000 ppm, IDLH=1200 ppm, ADC GPIO35
  REQ-103 Précision ≤ ±5%

REQ-200 — Conditions ambiantes
  REQ-201 Température : DHT22, -40°C à +80°C, ±0.5°C, GPIO4
  REQ-202 Humidité : DHT22, 0-100%, ±2%
  REQ-203 Météo API : Open-Meteo, fallback, cache 10 min

REQ-300 — Localisation GPS
  REQ-301 Position : NEO-6M, UART2, latitude/longitude/altitude/vitesse
  REQ-302 Qualité : HDOP ≤ 2.0, ≥ 6 satellites
  REQ-303 Carte Leaflet OpenStreetMap, centré Lubumbashi

REQ-400 — Intelligence artificielle
  REQ-401 Random Forest : 4 niveaux (Normal/Moyen/Dangereux/Critique),
          200 arbres, depth=15, 20 features
  REQ-402 LSTM Bidirectionnel : prédiction 50s (10 pas × 5s),
          lookback=20 mesures, architecture 128→64→Dense
  REQ-403 Calculs physiques : dose ∫C(t)dt, dérivée dC/dt, k croissance,
          indice de danger normalisé

REQ-500 — Communication
  REQ-501 WiFi, JSON POST /api/sensor_data, timeout 4s
  REQ-502 Fréquence acquisition : 5 secondes
  REQ-503 Résilience : stockage SPIFFS si perte WiFi, watchdog 8s

REQ-600 — Alertes
  REQ-601 Seuils NIOSH/ACGIH : TWA, STEL, IDLH
  REQ-602 Alertes prédictives LSTM : dépassement à 50s
  REQ-603 Sonore : buzzer 85 dB + MAX98357A I2S
  REQ-604 Visuelle : WS2812B × 6 LEDs RGB, brim casque, GPIO26

REQ-700 — Alimentation
  REQ-701 LiPo 3.7V 5000 mAh, TP4056 + DW01A, boost MT3608 5V
  REQ-702 Autonomie ≥ 8h en continu
  REQ-703 Recharge USB-C 5V/2A

REQ-800 — Interface
  REQ-801 OLED SSD1306 0.96", I2C, SDA:GPIO21 SCL:GPIO22
  REQ-802 Dashboard Flask, Chart.js, Leaflet, http://localhost:5000
  REQ-803 WebSocket temps réel < 100ms par mesure

REQ-900 — Conformité
  REQ-901 Coque EN 397 classe E, HDPE orange RAL 2009
  REQ-902 IP54 électronique embarquée
  REQ-903 Seuils NIOSH/ACGIH intégrés dans la logique d'alerte

RELATIONS À MODÉLISER :
- <<containment>>  : REQ-000 contient REQ-100 à REQ-900, chaque groupe
                     contient ses sous-exigences
- <<deriveReqt>>   : REQ-101/102 → REQ-401/402 (gaz → ML)
                     REQ-401/402 → REQ-601/602 (ML → alertes)
                     REQ-201/202 → REQ-403 (T°/HR → physique)
                     REQ-203 → REQ-201/202 (fallback météo)
- <<refine>>       : REQ-403 → REQ-401 (features → RF)
                     REQ-302 → REQ-301 (qualité → position)
                     REQ-502 → REQ-501 (fréquence → protocole)

FORMAT DE SORTIE :
- Syntaxe PlantUML @startuml ... @enduml
- Chaque rectangle doit afficher : stéréotype «requirement», ID, nom,
  attributs id/text/capteur/priorité selon disponibilité
- Thème sombre (bgcolor #0d1b2e)
- Notes contextuelles sur REQ-000, REQ-402 et REQ-601
- Légende des seuils toxicologiques en bas
```

---

## Outils pour visualiser le .puml

| Outil | Accès |
|-------|-------|
| **PlantUML en ligne** | https://www.plantuml.com/plantuml/uml/ |
| **VS Code** | Extension « PlantUML » (jebbs) + Ctrl+Shift+P → Preview |
| **IntelliJ IDEA** | Plugin PlantUML Integration |
| **draw.io** | Import → « From PlantUML » |
| **Enterprise Architect** | Import SysML directement |
| **Structurizr** | Compatible avec adaptateur PlantUML |

## Fichier source

Le diagramme complet est disponible dans :
`docs/REQ_casque_H2S.puml`

Copier le contenu sur https://www.plantuml.com/plantuml/uml/
pour obtenir le PNG/SVG immédiatement.
