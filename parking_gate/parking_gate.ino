
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ====== CẤU HÌNH ======
const char* WIFI_SSID = "Phuong Uyen";
const char* WIFI_PASS = "19022007";

const char* SERVER_BASE = "http://192.168.88.233:8000";

#define SERVO_SELFTEST 1

const int TRIG_IN = 32, ECHO_IN = 14;
const int TRIG_OUT = 33, ECHO_OUT = 27;
const int SERVO_PIN = 13;

const int LCD_SDA = 25;
const int LCD_SCL = 26;
const int LCD_ADDR = 0x27;

const int ANGLE_CLOSED = 180;
const int ANGLE_OPEN = 90;

const float DETECT_CM = 5;
const int DETECT_COUNT = 5;
const unsigned long CLEAR_MS = 3000;
const unsigned long OPEN_MAX_MS = 60000;
const unsigned long COOLDOWN_MS = 5000;
const unsigned long HTTP_TIMEOUT_MS = 12000;

// ========================================================

LiquidCrystal_I2C lcd(LCD_ADDR, 16, 2);
Servo barrier;

enum State { IDLE, OPENED };
State state = IDLE;

int inCount = 0, outCount = 0;
unsigned long clearSince = 0, openedAt = 0, lastReject = 0;

float readCm(int trig, int echo) {
  digitalWrite(trig, LOW);
  delayMicroseconds(2);
  digitalWrite(trig, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig, LOW);

  long us = pulseIn(echo, HIGH, 30000);

  if (us == 0) return 999;
  return us * 0.0343 / 2;
}

void show(const String& l1, const String& l2 = "") {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(l1.substring(0, 16));
  lcd.setCursor(0, 1);
  lcd.print(l2.substring(0, 16));
}

void showReady() {
  show("San sang", "Moi xe vao/ra");
}

void connectWifi() {
  show("Ket noi WiFi...");
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
  }

  Serial.print("[WIFI] ESP32 IP = ");
  Serial.println(WiFi.localIP());

  show("WiFi OK", WiFi.localIP().toString());
  delay(1500);
}

void checkServer() {
  show("Thu ket noi", "server...");

  HTTPClient http;
  http.begin(String(SERVER_BASE) + "/api/status");
  http.setTimeout(5000);

  int code = http.GET();

  Serial.printf("[HTTP] kiem tra server -> code=%d %s\n",
                code, http.errorToString(code).c_str());

  http.end();

  if (code == 200) {
    show("Server OK", "San sang");
  } else {
    show("Khong toi server", "code " + String(code));
  }

  delay(2500);
}

void handleVehicle(const char* sensor) {
  Serial.printf("[SENSOR] Cam bien %s bao co xe -> goi server\n", sensor);

  show("Dang nhan dien", "bien so...");

  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
  }

  HTTPClient http;
  http.begin(String(SERVER_BASE) + "/api/gate-event");
  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");

  int code = http.POST(
    String("{\"gate\":\"auto\",\"sensor\":\"") + sensor + "\"}"
  );

  if (code != 200) {
    Serial.printf("[HTTP] LOI code=%d %s\n",
                  code, http.errorToString(code).c_str());

    if (code > 0) {
      Serial.println(http.getString());
    }

    show("Loi server", String(code));
    http.end();
    lastReject = millis();
    return;
  }

  String body = http.getString();
  http.end();

  Serial.println("[HTTP] Server tra ve: " + body);

  StaticJsonDocument<384> doc;
  DeserializationError err = deserializeJson(doc, body);

  if (err) {
    show("Loi du lieu");
    lastReject = millis();
    return;
  }

  show(doc["line1"] | "", doc["line2"] | "");

  if (doc["open"] | false) {
    Serial.println("[SERVO] Mo thanh chan -> 90 do");

    barrier.write(ANGLE_OPEN);
    state = OPENED;
    openedAt = millis();
    clearSince = 0;
  } else {
    lastReject = millis();
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(TRIG_IN, OUTPUT);
  pinMode(ECHO_IN, INPUT);
  pinMode(TRIG_OUT, OUTPUT);
  pinMode(ECHO_OUT, INPUT);

  barrier.setPeriodHertz(50);
  barrier.write(ANGLE_CLOSED);
  barrier.attach(SERVO_PIN, 500, 2500);

  Wire.begin(LCD_SDA, LCD_SCL);
  lcd.init();
  lcd.backlight();

  connectWifi();

  #if SERVO_SELFTEST
    Serial.println("[SERVO] Tu thu: mo 90 do roi dong 180 do");

    barrier.write(ANGLE_OPEN);
    delay(900);

    barrier.write(ANGLE_CLOSED);
    delay(600);
  #endif

  checkServer();
  showReady();

  Serial.println("\n========== SMART PARKING ==========");
  Serial.println("Cam bien IN  : TRIG 32 | ECHO 14");
  Serial.println("Cam bien OUT : TRIG 33 | ECHO 27");
  Serial.println("Nguong phat hien xe: 5 cm");
  Serial.println("===================================\n");
}

void loop() {
  float dIn = readCm(TRIG_IN, ECHO_IN);

  delay(30);

  float dOut = readCm(TRIG_OUT, ECHO_OUT);

  bool carIn = dIn < DETECT_CM;
  bool carOut = dOut < DETECT_CM;

  // ===== HIỂN THỊ KHOẢNG CÁCH 2 CẢM BIẾN =====
  Serial.printf(
    "[DISTANCE] IN: %6.2f cm | OUT: %6.2f cm | IN: %s | OUT: %s\n",
    dIn,
    dOut,
    carIn ? "CO XE" : "TRONG",
    carOut ? "CO XE" : "TRONG"
  );

  if (state == IDLE) {

    if (millis() - lastReject < COOLDOWN_MS) {
      delay(60);
      return;
    }

    if (lastReject != 0 &&
        millis() - lastReject >= COOLDOWN_MS) {
      showReady();
      lastReject = 0;
    }

    inCount = carIn ? inCount + 1 : 0;
    outCount = carOut ? outCount + 1 : 0;

    if (inCount >= DETECT_COUNT) {
      inCount = outCount = 0;
      handleVehicle("in");
    }
    else if (outCount >= DETECT_COUNT) {
      inCount = outCount = 0;
      handleVehicle("out");
    }

  } else {

    // Chờ xe đi qua hoàn toàn rồi đóng thanh chắn
    if (!carIn && !carOut) {
      if (clearSince == 0) {
        clearSince = millis();
      }
    } else {
      clearSince = 0;
    }

    bool passed =
      clearSince != 0 &&
      millis() - clearSince >= CLEAR_MS;

    bool timeout =
      millis() - openedAt >= OPEN_MAX_MS;

    if (passed || timeout) {
      Serial.println("[SERVO] Xe da qua -> dong thanh chan 180 do");

      barrier.write(ANGLE_CLOSED);
      state = IDLE;
      showReady();
    }
  }

  delay(60);
}
