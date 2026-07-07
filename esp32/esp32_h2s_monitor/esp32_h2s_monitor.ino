#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <math.h>

const char* WIFI_SSID = "DIL";
const char* WIFI_PASSWORD = "je suis un elite001";
const char* SERVER_IP = "172.21.69.74";
const int SERVER_PORT = 8080;
const char* SENSOR_PATH = "/api/sensor_data";
const char* COMMAND_PATH = "/api/esp32/command";
const char* HEARTBEAT_PATH = "/api/esp32/heartbeat";
const char* HEALTH_PATH = "/api/health";

const char* DEVICE_ID = "CASQUE_001";
const char* WORKER_NAME = "DANNY LABULU";
const char* ZONE_NAME = "Zone H2S";

const int PIN_MQ136 = 34;
const int PIN_DHT = 4;
const int PIN_LED_GREEN = 25;
const int PIN_LED_RED = 26;
const int PIN_LED_ORANGE = 27;
const int PIN_BUZZER = 32;

#define DHTTYPE DHT22
DHT dht(PIN_DHT, DHTTYPE);

const unsigned long SEND_INTERVAL_MS = 5000;
const unsigned long HEARTBEAT_INTERVAL_MS = 3000;
const unsigned long COMMAND_INTERVAL_MS = 500;
const unsigned long WIFI_RETRY_INTERVAL_MS = 5000;
const unsigned long HTTP_TIMEOUT_MS = 4000;
const unsigned long REMOTE_SIM_OVERRIDE_HOLD_MS = 30000;
const float MQ136_R0 = 10.0f;
const float MQ136_RL = 10.0f;
const float MQ136_A = 36.737f;
const float MQ136_B = -3.536f;
const float ADC_VREF = 3.3f;

String sensorUrl;
String commandUrl;
String heartbeatUrl;
String healthUrl;
unsigned long lastSendAt = 0;
unsigned long lastHeartbeatAt = 0;
unsigned long lastCommandAt = 0;
unsigned long lastWiFiAttemptAt = 0;
unsigned long startedAt = 0;
unsigned long sendCount = 0;
int consecutiveSendFailures = 0;
bool esp32Enabled = true;
bool serverReachable = false;
int currentRiskClass = 0;
int lastRiskClass = -1;
bool simulationOverrideActive = false;
unsigned long simulationOverrideUntil = 0;
float h2sPpm = 0.0f;
float temperatureC = 25.0f;
float humidityPct = 50.0f;

void setRgb(bool red, bool green, bool orange) {
  digitalWrite(PIN_LED_RED, red ? HIGH : LOW);
  digitalWrite(PIN_LED_GREEN, green ? HIGH : LOW);
  digitalWrite(PIN_LED_ORANGE, orange ? HIGH : LOW);
}

void setBuzzer(bool on) {
  if (on) {
    tone(PIN_BUZZER, 2200); // Compatible buzzer passif; sonne aussi sur la plupart des buzzers actifs.
  } else {
    noTone(PIN_BUZZER);
    digitalWrite(PIN_BUZZER, LOW);
  }
}

void beep(int times, int onMs, int offMs) {
  for (int i = 0; i < times; i++) {
    setBuzzer(true);
    delay(onMs);
    setBuzzer(false);
    if (offMs > 0) delay(offMs);
  }
}

int classifyLocalRisk(float ppm) {
  if (ppm >= 20.0f) return 2;
  if (ppm >= 10.0f) return 1;
  return 0;
}

bool isSimulationOverrideActive() {
  if (simulationOverrideActive && millis() > simulationOverrideUntil) {
    simulationOverrideActive = false;
  }
  return simulationOverrideActive;
}

void applyRiskLed(int riskClass) {
  if (WiFi.status() != WL_CONNECTED || !esp32Enabled || (!serverReachable && riskClass < 2)) {
    setRgb(false, true, false); // Vert : casque non connecte / serveur indisponible.
    setBuzzer(false);
    return;
  }
  if (riskClass >= 2) {
    setRgb(true, false, false); // Rouge : danger.
    setBuzzer(true);            // Simulation/risque dangereux : alarme maintenue.
  } else if (riskClass == 1) {
    setRgb(false, false, true); // Orange : risque modere.
    setBuzzer(false);
  } else {
    setRgb(false, true, false); // Vert : normal.
    setBuzzer(false);
  }
}

void updateRiskClass(int riskClass, bool allowAlarm) {
  currentRiskClass = constrain(riskClass, 0, 2);
  if (allowAlarm && currentRiskClass >= 2 && lastRiskClass < 2) {
    beep(2, 90, 90);
  }
  applyRiskLed(currentRiskClass);
  lastRiskClass = currentRiskClass;
}

void markServerResult(bool ok) {
  serverReachable = ok;
  applyRiskLed(currentRiskClass);
}

String makeUrl(const char* path) {
  return "http://" + String(SERVER_IP) + ":" + String(SERVER_PORT) + String(path);
}

void configureWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
}

bool connectWiFi(unsigned long timeoutMs = 8000) {
  if (WiFi.status() == WL_CONNECTED) return true;
  configureWiFi();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[WiFi] Connexion a ");
  Serial.print(WIFI_SSID);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
    Serial.print(".");
    delay(300);
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[WiFi] Connecte");
    Serial.println("[WiFi] IP ESP32: " + WiFi.localIP().toString());
    Serial.println("[WiFi] RSSI: " + String(WiFi.RSSI()) + " dBm");
    setRgb(false, true, false);
    return true;
  }

  Serial.println("[WiFi] Echec connexion");
  setRgb(false, true, false);
  return false;
}

bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  unsigned long now = millis();
  if (now - lastWiFiAttemptAt < WIFI_RETRY_INTERVAL_MS) return false;
  lastWiFiAttemptAt = now;
  Serial.println("[WiFi] Perte de liaison, reconnexion...");
  WiFi.reconnect();
  return connectWiFi(7000);
}

float adcToPpm(int rawAdc) {
  if (rawAdc <= 0) return 0.0f;
  float vout = (float(rawAdc) / 4095.0f) * ADC_VREF;
  if (vout < 0.01f || vout >= ADC_VREF) return 0.0f;
  float rs = MQ136_RL * (ADC_VREF - vout) / vout;
  float ratio = rs / MQ136_R0;
  if (ratio <= 0.0f) return 0.0f;
  return max(MQ136_A * powf(ratio, MQ136_B), 0.0f);
}

float readMq136Ppm() {
  long sum = 0;
  for (int i = 0; i < 20; i++) {
    sum += analogRead(PIN_MQ136);
    delay(3);
  }
  float ppm = adcToPpm(sum / 20);
  float correction = 1.0f + 0.005f * (temperatureC - 20.0f) - 0.002f * (humidityPct - 50.0f);
  return max(ppm / max(correction, 0.1f), 0.0f);
}

void readSensors() {
  temperatureC = dht.readTemperature();
  humidityPct = dht.readHumidity();
  if (isnan(temperatureC)) temperatureC = 25.0f;
  if (isnan(humidityPct)) humidityPct = 50.0f;
  h2sPpm = readMq136Ppm();
  if (!isSimulationOverrideActive()) {
    updateRiskClass(classifyLocalRisk(h2sPpm), false);
  } else {
    applyRiskLed(currentRiskClass);
  }
}

void parseEnabledFromResponse(const String& response) {
  if (response.length() == 0) return;
  StaticJsonDocument<1024> res;
  DeserializationError err = deserializeJson(res, response);
  if (err) return;
  if (res.containsKey("enabled")) esp32Enabled = res["enabled"].as<bool>();
  if (res.containsKey("simulation_override")) {
    if (res["simulation_override"].as<bool>()) {
      simulationOverrideActive = true;
      simulationOverrideUntil = millis() + REMOTE_SIM_OVERRIDE_HOLD_MS;
    } else {
      simulationOverrideActive = false;
    }
  }
  if (res.containsKey("risk_class")) {
    updateRiskClass(res["risk_class"].as<int>(), true);
  } else {
    JsonVariant ledState = res["led_state"];
    if (!ledState.isNull() && ledState["risk_class"].is<int>()) {
      updateRiskClass(ledState["risk_class"].as<int>(), true);
    } else {
      applyRiskLed(currentRiskClass);
    }
  }
}

bool getRequest(const String& url, int& code, String& response) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.setReuse(false);
  http.begin(url);
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  code = http.GET();
  response = http.getString();
  http.end();
  return code == 200;
}

bool postJson(const String& url, const String& body, int& code, String& response) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HTTPClient http;
  http.setReuse(false);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  code = http.POST(body);
  response = http.getString();
  http.end();
  return code == 200 || code == 201 || code == 202;
}

bool testServer() {
  int code = -1;
  String response;
  bool ok = getRequest(healthUrl, code, response);
  Serial.println("[SERVER] GET " + healthUrl + " -> " + String(code));
  if (!ok) Serial.println("[SERVER] Injoignable: verifier IP, port 8080 et pare-feu Windows");
  markServerResult(ok);
  return ok;
}

bool sendHeartbeat() {
  StaticJsonDocument<384> doc;
  doc["device_id"] = DEVICE_ID;
  doc["worker_name"] = WORKER_NAME;
  doc["zone"] = ZONE_NAME;
  doc["uptime_s"] = millis() / 1000;
  doc["wifi_rssi"] = WiFi.RSSI();
  doc["ip_address"] = WiFi.localIP().toString();
  doc["enabled"] = esp32Enabled;
  doc["send_count"] = sendCount;

  String body;
  serializeJson(doc, body);
  int code = -1;
  String response;
  bool ok = postJson(heartbeatUrl, body, code, response);
  parseEnabledFromResponse(response);
  Serial.println("[HB] Code: " + String(code) + " | enabled=" + String(esp32Enabled ? "true" : "false"));
  markServerResult(ok);
  return ok;
}

bool pollCommand() {
  String url = commandUrl + "?device_id=" + String(DEVICE_ID) +
               "&wifi_rssi=" + String(WiFi.RSSI()) +
               "&ip_address=" + WiFi.localIP().toString();

  int code = -1;
  String response;
  bool ok = getRequest(url, code, response);
  if (ok) {
    parseEnabledFromResponse(response);
    Serial.println("[CMD] enabled=" + String(esp32Enabled ? "true" : "false"));
    markServerResult(true);
    return true;
  }
  Serial.println("[CMD] Echec code=" + String(code));
  markServerResult(false);
  return false;
}

bool sendMeasurement() {
  if (!esp32Enabled) return false;

  StaticJsonDocument<640> doc;
  doc["device_id"] = DEVICE_ID;
  doc["worker_name"] = WORKER_NAME;
  doc["zone"] = ZONE_NAME;
  doc["timestamp"] = millis() / 1000.0;
  doc["h2s_ppm"] = roundf(h2sPpm * 100.0f) / 100.0f;
  doc["temperature"] = roundf(temperatureC * 10.0f) / 10.0f;
  doc["humidity"] = roundf(humidityPct * 10.0f) / 10.0f;
  doc["exposure_time_s"] = (millis() - startedAt) / 1000;
  doc["wifi_rssi"] = WiFi.RSSI();
  doc["ip_address"] = WiFi.localIP().toString();
  doc["send_count"] = sendCount;

  String body;
  serializeJson(doc, body);

  int code = -1;
  String response;
  Serial.println("[HTTP] POST " + sensorUrl);
  Serial.println("[HTTP] Payload: " + body);
  bool ok = postJson(sensorUrl, body, code, response);
  parseEnabledFromResponse(response);
  Serial.println("[HTTP] Code: " + String(code));
  Serial.println("[HTTP] Reponse: " + response);
  markServerResult(ok);
  return ok;
}

void setup() {
  Serial.begin(115200);
  delay(800);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_LED_ORANGE, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  setBuzzer(false);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_MQ136, ADC_11db);
  dht.begin();

  sensorUrl = makeUrl(SENSOR_PATH);
  commandUrl = makeUrl(COMMAND_PATH);
  heartbeatUrl = makeUrl(HEARTBEAT_PATH);
  healthUrl = makeUrl(HEALTH_PATH);

  Serial.println("=== ESP32 H2S GazMonitor ===");
  Serial.println("Mesures: " + sensorUrl);
  Serial.println("Commande: " + commandUrl);
  Serial.println("Heartbeat: " + heartbeatUrl);
  Serial.println("Health: " + healthUrl);

  configureWiFi();
  connectWiFi(10000);
  if (WiFi.status() == WL_CONNECTED) testServer();
  startedAt = millis();
  beep(2, 80, 80);
}

void loop() {
  unsigned long now = millis();

  if (!ensureWiFi()) {
    setRgb(false, true, false);
    setBuzzer(false);
    return;
  }

  if (esp32Enabled && now - lastSendAt >= SEND_INTERVAL_MS) {
    lastSendAt = now;
    readSensors();
    Serial.printf("H2S=%.2f ppm | T=%.1f C | H=%.1f %% | RSSI=%d dBm\n", h2sPpm, temperatureC, humidityPct, WiFi.RSSI());

    if (sendMeasurement()) {
      sendCount++;
      consecutiveSendFailures = 0;
      applyRiskLed(currentRiskClass);
    } else {
      consecutiveSendFailures++;
      applyRiskLed(currentRiskClass);
      if (consecutiveSendFailures >= 6) {
        Serial.println("[HTTP] Plusieurs echecs, test serveur sans couper le Wi-Fi");
        testServer();
        if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();
        consecutiveSendFailures = 0;
      }
    }
  }

  if (now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatAt = now;
    sendHeartbeat();
  }

  if (now - lastCommandAt >= COMMAND_INTERVAL_MS) {
    lastCommandAt = now;
    pollCommand();
  }

  applyRiskLed(currentRiskClass);
}


