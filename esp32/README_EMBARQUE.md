# Partie embarquee ESP32 - Liaison stable H2S

Firmware principal: `esp32_h2s_monitor/esp32_h2s_monitor.ino`

Configuration actuelle:

```cpp
const char* WIFI_SSID = "DIL";
const char* SERVER_IP = "10.67.107.74";
const int SERVER_PORT = 8080;
const char* SENSOR_PATH = "/api/sensor_data";
const char* COMMAND_PATH = "/api/esp32/command";
const char* HEARTBEAT_PATH = "/api/esp32/heartbeat";
```

Le projet utilise un seul capteur gaz: MQ-136 pour H2S. Aucun champ CO n'est envoye.

## Fonctionnement reseau

L'ESP32 garde le Wi-Fi actif et desactive le mode sommeil Wi-Fi avec `WiFi.setSleep(false)`. Elle envoie:

- une mesure H2S vers `/api/sensor_data` toutes les 5 secondes quand le dashboard autorise la transmission;
- un heartbeat vers `/api/esp32/heartbeat` toutes les 2 secondes pour maintenir le voyant de connectivite;
- une requete de commande vers `/api/esp32/command` toutes les 2 secondes pour appliquer les boutons Connecter/Deconnecter du dashboard.

Le bouton `Deconnecter ESP32` du dashboard suspend la transmission des mesures, mais l'ESP32 reste connectee au Wi-Fi et continue le heartbeat. Cela permet de la reconnecter ensuite directement depuis le dashboard sans devoir reprogrammer ou redemarrer la carte.

Payload mesure envoye par l'ESP32:

```json
{
  "device_id": "CASQUE_001",
  "worker_name": "DANNY LABULU",
  "zone": "Zone H2S",
  "h2s_ppm": 2.45,
  "temperature": 27.4,
  "humidity": 61.0,
  "wifi_rssi": -58,
  "ip_address": "10.67.107.115",
  "send_count": 0
}
```

## Test attendu dans le moniteur serie

```text
[WiFi] Connecte
[HB] Code: 200 | enabled=true
[CMD] enabled=true
[HTTP] POST http://10.67.107.74:8080/api/sensor_data
[HTTP] Code: 201
```

Si le dashboard clique sur `Deconnecter ESP32`, le moniteur doit afficher `enabled=false` et l'envoi des mesures est suspendu. En cliquant sur `Connecter ESP32`, `enabled=true` revient et les mesures reprennent.
## Diagnostic si la carte ne rejoint pas le serveur

Apres televersement du sketch, ouvrir le moniteur serie a 115200 bauds. Les lignes attendues sont:

```text
[WiFi] Connecte
[WiFi] IP ESP32: 10.67.107.xxx
[SERVER] GET http://10.67.107.74:8080/api/health -> 200
[HTTP] POST http://10.67.107.74:8080/api/sensor_data
[HTTP] Code: 201
```

Si la ligne `[SERVER] ... -> -1` apparait, l'ESP32 est connectee au Wi-Fi mais ne parvient pas a joindre Flask. Dans ce cas, ouvrir PowerShell en administrateur et lancer:

```powershell
New-NetFirewallRule -DisplayName "GazMonitor Port 8080" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8080 -Profile Any
```

Ensuite, redemarrer le serveur Flask et reinitialiser l'ESP32.