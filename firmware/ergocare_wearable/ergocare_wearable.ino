/*
 * ErgoCare Wearable — ESP32 firmware
 * ==================================
 * Sensors
 *   - HW-058 (MAX30102)  pulse / heart rate      I2C (SDA 21, SCL 22), addr 0x57
 *   - MPU6050            posture tilt + movement I2C (SDA 21, SCL 22), addr 0x68
 *   - GSR module         skin conductance        analog GPIO34 (ADC1 — works with Wi-Fi on)
 *
 * Output (once per second)
 *   - One JSON line on USB serial (115200 baud). Status lines start with '#'.
 *   - The same JSON is POSTed to BACKEND_URL/api/devices/<DEVICE_ID>/readings
 *     when Wi-Fi credentials are set in secrets.h (copy secrets.example.h).
 *
 * Design
 *   - Core 1 (loop): samples every sensor at 100 Hz so no heartbeat is missed.
 *   - Core 0 (netTask): sends the latest reading over Wi-Fi. A slow network
 *     never blocks sampling; if it falls behind, only the newest reading is sent.
 *
 * Serial commands (type in Serial Monitor, newline-terminated)
 *   CAL   — set the current posture as "upright" (tilt = 0)
 */

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "MAX30105.h"   // SparkFun MAX3010x library (works with MAX30102)

#if __has_include("secrets.h")
#include "secrets.h"
#endif

// ── Configuration ─────────────────────────────────────────────────────────────
#ifndef WIFI_SSID
#define WIFI_SSID ""            // empty = USB-only mode
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif
#ifndef BACKEND_URL
#define BACKEND_URL ""          // e.g. "http://192.168.1.20:8000"
#endif
#ifndef DEVICE_ID
#define DEVICE_ID "ERGO-01"
#endif

const int      PIN_SDA        = 21;
const int      PIN_SCL        = 22;
const int      PIN_GSR        = 34;
const uint8_t  MPU_ADDR       = 0x68;

const uint32_t SAMPLE_MS      = 10;      // 100 Hz sensor sampling
const uint32_t REPORT_MS      = 1000;    // one reading per second
const uint32_t FINGER_IR_MIN  = 50000;   // IR below this = no finger on sensor
const uint32_t BEAT_TIMEOUT_MS = 4000;   // no beat for 4 s -> bpm unknown
const uint32_t MIN_IBI_MS     = 333;     // 180 BPM max
const uint32_t MAX_IBI_MS     = 1500;    // 40 BPM min
const float    GSR_CONTACT_MIN = 50;     // raw below this = electrodes not touched
const float    MOVING_GYRO_DPS = 8.0;    // mean rotation above this = moving
const float    MOVING_ACC_STD  = 0.35;   // accel std-dev (m/s^2) above this = moving

// ── Sensor state ──────────────────────────────────────────────────────────────
MAX30105 pulse;
bool pulseOk = false;
bool mpuOk   = false;

// Heart rate (timing is counted in FIFO samples -> immune to loop delays)
const uint32_t PULSE_SAMPLE_MS = 10;     // 400 Hz / 4 averaged = 100 samples/s
uint32_t pulseSampleCount = 0;
uint32_t lastBeatSample   = 0;
uint32_t lastIR           = 0;
uint32_t lastPulseDataMs  = 0;           // watchdog: when the sensor last gave samples
uint32_t lastPulseRetryMs = 0;
bool     fingerOn         = false;
float    bpmNow           = 0;           // from the last beat-to-beat interval
float    bpmMedian        = 0;           // median of recent intervals (robust)

// Beat detector: smooth -> slope of IR -> adaptive threshold with hysteresis
const float BEAT_SMOOTH   = 0.20f;       // IR low-pass factor
const float SLOPE_SMOOTH  = 0.35f;       // slope low-pass factor
const float BEAT_HI       = 0.60f;       // beat fires above 60% of typical upstroke
const float BEAT_LO       = 0.20f;       // must drop below 20% before the next beat
const float ARTIFACT_X    = 3.0f;        // slope > 3x typical = motion/pressure spike
float lpIR = 0, prevIR = 0, slopeIR = 0, peakIR = 0, curMaxIR = 0;
bool  armed = false, inBeat = false;
uint32_t learnSamples = 0;
const uint8_t IBI_N = 5;                 // beat-to-beat intervals kept for the median
uint32_t ibis[IBI_N];
uint8_t  ibiCount = 0, ibiIdx = 0;

// Per-report accumulators
uint32_t winSamples = 0;
double   gsrRawSum = 0, gsrMvSum = 0;
double   axSum = 0, aySum = 0, azSum = 0;
double   accMagSum = 0, accMagSqSum = 0;
double   gyroMagSum = 0;
uint32_t mpuSamples = 0;

// Posture reference ("upright") gravity vector
float refX = 0, refY = 0, refZ = 0;
bool  refSet = false;
volatile bool calibrateRequested = false;

uint32_t seq = 0;
uint32_t lastSampleMs = 0, lastReportMs = 0;

// ── Reading passed from sensor core to network core ───────────────────────────
struct Reading {
  uint32_t seq, uptimeMs, ir;
  float bpm, bpmAvg, gsrRaw, gsrMv, tilt, ax, ay, az, gyro, accStd;
  bool finger, gsrContact, moving;
};
QueueHandle_t netQueue;
volatile bool wifiUp = false;

// ── MPU6050 (raw registers — also works with clones that fail WHO_AM_I checks) ─
bool mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

int mpuWhoAmI() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x75);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom(MPU_ADDR, (uint8_t)1) != 1) return -1;
  return Wire.read();
}

bool mpuInit() {
  if (!mpuWrite(0x6B, 0x00)) return false;   // wake up, internal clock
  mpuWrite(0x1C, 0x00);                        // accel ±2 g  -> 16384 LSB/g
  mpuWrite(0x1B, 0x00);                        // gyro ±250°/s -> 131 LSB/(°/s)
  mpuWrite(0x1A, 0x03);                        // low-pass filter ~44 Hz
  return true;
}

bool mpuRead(float &ax, float &ay, float &az, float &gx, float &gy, float &gz) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(MPU_ADDR, (uint8_t)14) != 14) return false;
  int16_t v[7];
  for (int i = 0; i < 7; i++) v[i] = (int16_t)((Wire.read() << 8) | Wire.read());
  const float G = 9.80665f;
  ax = v[0] / 16384.0f * G;
  ay = v[1] / 16384.0f * G;
  az = v[2] / 16384.0f * G;
  gx = v[4] / 131.0f;          // v[3] is temperature — unused
  gy = v[5] / 131.0f;
  gz = v[6] / 131.0f;
  return true;
}

// Angle in degrees between the current gravity vector and the "upright" one.
// Works however the sensor is clipped on, because it is relative to calibration.
float tiltFromRef(float x, float y, float z) {
  float n1 = sqrtf(x * x + y * y + z * z);
  float n2 = sqrtf(refX * refX + refY * refY + refZ * refZ);
  if (n1 < 1e-3f || n2 < 1e-3f) return 0;
  float c = (x * refX + y * refY + z * refZ) / (n1 * n2);
  c = constrain(c, -1.0f, 1.0f);
  return acosf(c) * 180.0f / PI;
}

// ── I2C scan (printed at boot to help with wiring problems) ──────────────────
void i2cScan() {
  Serial.print("# I2C devices:");
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf(" 0x%02X", a);
      found++;
    }
  }
  Serial.println(found ? "" : " none - check SDA/SCL/VCC/GND");
}

// ── Heart-beat detection ──────────────────────────────────────────────────────
// SparkFun's checkForBeat() rejects pulses with an AC swing above 1000, which
// strong finger contact easily exceeds. This detector instead looks for the
// sharp IR drop at each heartbeat (the slope), which ignores slow drift and
// finger-pressure changes, and adapts its threshold to the signal strength.
// Tuned in simulation: median error < 2 BPM from 58-110 BPM, weak to strong signals.
void resetBeatDetector(uint32_t ir) {
  lpIR = prevIR = ir;
  slopeIR = peakIR = curMaxIR = 0;
  armed = inBeat = false;
  learnSamples = 0;
  ibiCount = ibiIdx = 0;
  bpmNow = bpmMedian = 0;
  lastBeatSample = pulseSampleCount;
}

float medianIbi() {
  uint32_t s[IBI_N];
  for (uint8_t i = 0; i < ibiCount; i++) s[i] = ibis[i];
  for (uint8_t i = 1; i < ibiCount; i++) {            // insertion sort (n <= 5)
    uint32_t v = s[i]; int j = i - 1;
    while (j >= 0 && s[j] > v) { s[j + 1] = s[j]; j--; }
    s[j + 1] = v;
  }
  return ibiCount ? (float)s[ibiCount / 2] : 0;
}

bool detectBeat(uint32_t ir) {
  lpIR += BEAT_SMOOTH * ((float)ir - lpIR);
  float slope = prevIR - lpIR;               // IR falling = blood arriving -> positive
  prevIR = lpIR;
  slopeIR += SLOPE_SMOOTH * (slope - slopeIR);
  uint32_t sinceMs = (pulseSampleCount - lastBeatSample) * PULSE_SAMPLE_MS;

  if (peakIR == 0) {                         // first 1.5 s: learn typical upstroke size
    if (slopeIR > curMaxIR) curMaxIR = slopeIR;
    if (++learnSamples >= 150) { peakIR = max(curMaxIR, 3.0f); curMaxIR = 0; }
    return false;
  }
  if (sinceMs > 2500) peakIR *= 0.995f;      // no beats lately: let the threshold sink

  if (slopeIR > ARTIFACT_X * peakIR) {       // movement spike: ignore, re-arm later
    armed = false;
    return false;
  }
  if (inBeat) {                              // inside an upstroke: measure its height
    if (slopeIR > curMaxIR) curMaxIR = slopeIR;
    if (slopeIR < BEAT_LO * peakIR) {
      inBeat = false;
      peakIR += 0.25f * (curMaxIR - peakIR); // adapt to this beat's strength
    }
    return false;
  }
  if (slopeIR < BEAT_LO * peakIR) {
    armed = true;
    return false;
  }
  if (armed && slopeIR > BEAT_HI * peakIR && sinceMs >= MIN_IBI_MS) {
    inBeat = true;
    armed = false;
    curMaxIR = slopeIR;
    return true;
  }
  return false;
}

// ── Pulse sensor start-up and watchdog ───────────────────────────────────────
bool initPulse() {
  if (!pulse.begin(Wire, I2C_SPEED_FAST)) return false;
  // brightness, avg 4, red+IR, 400 Hz, 411 us pulse, 4096 range -> 100 samples/s
  pulse.setup(0x1F, 4, 2, 400, 411, 4096);
  pulse.setPulseAmplitudeRed(0x0A);
  pulse.setPulseAmplitudeGreen(0);
  return true;
}

// A bumped wire can power-cycle the MAX30102, after which it silently stops
// producing samples. If no sample arrives for 1 s, report it and restart it.
void checkPulseHealth() {
  uint32_t now = millis();
  if (pulseOk && now - lastPulseDataMs > 1000) {
    pulseOk = false;
    fingerOn = false;
    bpmNow = bpmMedian = 0;
    Serial.println("# pulse sensor stopped responding - restarting it");
  }
  if (!pulseOk && now - lastPulseRetryMs > 2000) {
    lastPulseRetryMs = now;
    if (initPulse()) {
      pulseOk = true;
      lastPulseDataMs = now;
      Serial.println("# pulse sensor OK again");
    }
  }
}

// ── Sampling (core 1) ─────────────────────────────────────────────────────────
void samplePulse() {
  if (!pulseOk) return;
  pulse.check();
  while (pulse.available()) {
    uint32_t ir = pulse.getFIFOIR();
    pulse.nextSample();
    pulseSampleCount++;
    lastIR = ir;
    lastPulseDataMs = millis();

    bool nowOn = ir >= FINGER_IR_MIN;
    if (nowOn != fingerOn) {             // finger placed / removed -> start fresh
      fingerOn = nowOn;
      resetBeatDetector(ir);
    }
    if (!fingerOn) continue;

    if (detectBeat(ir)) {
      uint32_t ibi = (pulseSampleCount - lastBeatSample) * PULSE_SAMPLE_MS;
      lastBeatSample = pulseSampleCount;
      if (ibi >= MIN_IBI_MS && ibi <= MAX_IBI_MS) {
        ibis[ibiIdx] = ibi;
        ibiIdx = (ibiIdx + 1) % IBI_N;
        if (ibiCount < IBI_N) ibiCount++;
        bpmNow = 60000.0f / ibi;
        if (ibiCount >= 2) bpmMedian = 60000.0f / medianIbi();
      }
    }
  }
  // No beat for a while -> heart rate unknown (detector keeps running)
  if (fingerOn && (pulseSampleCount - lastBeatSample) * PULSE_SAMPLE_MS > BEAT_TIMEOUT_MS) {
    ibiCount = ibiIdx = 0;
    bpmNow = bpmMedian = 0;
  }
}

void sampleOthers() {
  gsrRawSum += analogRead(PIN_GSR);
  gsrMvSum  += analogReadMilliVolts(PIN_GSR);
  winSamples++;

  float ax, ay, az, gx, gy, gz;
  if (mpuOk && mpuRead(ax, ay, az, gx, gy, gz)) {
    axSum += ax; aySum += ay; azSum += az;
    float mag = sqrtf(ax * ax + ay * ay + az * az);
    accMagSum += mag;
    accMagSqSum += mag * mag;
    gyroMagSum += sqrtf(gx * gx + gy * gy + gz * gz);
    mpuSamples++;
  }
}

void resetWindow() {
  winSamples = mpuSamples = 0;
  gsrRawSum = gsrMvSum = 0;
  axSum = aySum = azSum = 0;
  accMagSum = accMagSqSum = gyroMagSum = 0;
}

// ── JSON (shared by USB and Wi-Fi) ────────────────────────────────────────────
int toJson(const Reading &r, char *buf, size_t len) {
  return snprintf(buf, len,
    "{\"device_id\":\"%s\",\"seq\":%lu,\"uptime_ms\":%lu,"
    "\"bpm\":%.1f,\"bpm_avg\":%.1f,\"finger\":%s,\"ir\":%lu,"
    "\"gsr_raw\":%.0f,\"gsr_mv\":%.0f,\"gsr_contact\":%s,"
    "\"tilt\":%.1f,\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,"
    "\"gyro\":%.1f,\"acc_std\":%.2f,\"moving\":%s,"
    "\"pulse_ok\":%s,\"mpu_ok\":%s,\"wifi\":%s}",
    DEVICE_ID, (unsigned long)r.seq, (unsigned long)r.uptimeMs,
    r.bpm, r.bpmAvg, r.finger ? "true" : "false", (unsigned long)r.ir,
    r.gsrRaw, r.gsrMv, r.gsrContact ? "true" : "false",
    r.tilt, r.ax, r.ay, r.az,
    r.gyro, r.accStd, r.moving ? "true" : "false",
    pulseOk ? "true" : "false", mpuOk ? "true" : "false", wifiUp ? "true" : "false");
}

void report() {
  if (winSamples == 0) return;
  Reading r = {};
  r.seq = ++seq;
  r.uptimeMs = millis();
  r.ir = lastIR;
  r.finger = fingerOn;
  r.bpm = bpmNow;
  r.bpmAvg = bpmMedian;
  r.gsrRaw = gsrRawSum / winSamples;
  r.gsrMv  = gsrMvSum / winSamples;
  r.gsrContact = r.gsrRaw >= GSR_CONTACT_MIN;

  if (mpuSamples > 0) {
    r.ax = axSum / mpuSamples;
    r.ay = aySum / mpuSamples;
    r.az = azSum / mpuSamples;
    float meanMag = accMagSum / mpuSamples;
    float var = accMagSqSum / mpuSamples - meanMag * meanMag;
    r.accStd = var > 0 ? sqrtf(var) : 0;
    r.gyro = gyroMagSum / mpuSamples;
    r.moving = r.gyro > MOVING_GYRO_DPS || r.accStd > MOVING_ACC_STD;

    if (!refSet || calibrateRequested) {   // first reading, or CAL requested
      refX = r.ax; refY = r.ay; refZ = r.az;
      refSet = true;
      calibrateRequested = false;
      Serial.println("# posture calibrated: current position = upright (tilt 0)");
    }
    r.tilt = tiltFromRef(r.ax, r.ay, r.az);
  }

  char json[400];
  toJson(r, json, sizeof(json));
  Serial.println(json);
  if (netQueue) xQueueOverwrite(netQueue, &r);   // network core sends the newest
  resetWindow();
}

// ── Network (core 0) ──────────────────────────────────────────────────────────
void netTask(void *) {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t lastTry = millis();
  String url = String(BACKEND_URL) + "/api/devices/" + DEVICE_ID + "/readings";
  char json[400];
  bool announcedFail = false;

  for (;;) {
    bool up = WiFi.status() == WL_CONNECTED;
    if (up != wifiUp) {
      wifiUp = up;
      if (up) Serial.printf("# wifi connected, ip=%s, sending to %s\n",
                            WiFi.localIP().toString().c_str(), url.c_str());
      else    Serial.println("# wifi disconnected - retrying");
    }
    if (!up && millis() - lastTry > 10000) {
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastTry = millis();
    }

    Reading r;
    if (xQueueReceive(netQueue, &r, pdMS_TO_TICKS(500)) != pdTRUE || !up) continue;

    toJson(r, json, sizeof(json));
    HTTPClient http;
    http.setConnectTimeout(800);
    http.setTimeout(800);
    if (!http.begin(url)) continue;
    http.addHeader("Content-Type", "application/json");
    int code = http.POST((uint8_t *)json, strlen(json));
    if (code >= 200 && code < 300) {
      announcedFail = false;
      String body = http.getString();
      if (body.indexOf("\"calibrate\":true") >= 0) calibrateRequested = true;  // app baseline step
    } else if (!announcedFail) {
      Serial.printf("# backend POST failed (%d) - is the server running at %s ?\n", code, BACKEND_URL);
      announcedFail = true;   // print once, not every second
    }
    http.end();
  }
}

// ── Serial commands ───────────────────────────────────────────────────────────
void handleSerial() {
  static String line;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      line.trim();
      if (line.equalsIgnoreCase("CAL")) calibrateRequested = true;
      line = "";
    } else if (line.length() < 32) {
      line += c;
    }
  }
}

// ── Setup / loop ──────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("# ErgoCare wearable starting, device " DEVICE_ID);

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);
  i2cScan();

  pulseOk = initPulse();
  lastPulseDataMs = lastPulseRetryMs = millis();
  Serial.println(pulseOk ? "# pulse sensor (MAX30102) OK"
                         : "# pulse sensor (MAX30102) NOT FOUND - check wiring");

  int who = mpuWhoAmI();
  mpuOk = who >= 0 && mpuInit();
  if (mpuOk) Serial.printf("# motion sensor OK (WHO_AM_I=0x%02X)\n", who);
  else       Serial.println("# motion sensor (MPU6050) NOT FOUND - check wiring");

  analogReadResolution(12);
  Serial.printf("# GSR on GPIO%d\n", PIN_GSR);

  if (strlen(WIFI_SSID) > 0 && strlen(BACKEND_URL) > 0) {
    netQueue = xQueueCreate(1, sizeof(Reading));
    xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 1, nullptr, 0);
    Serial.printf("# wifi: connecting to \"%s\"\n", WIFI_SSID);
  } else {
    Serial.println("# wifi: not configured - USB-only mode (see secrets.example.h)");
  }
  Serial.println("# ready - one JSON reading per second. Type CAL to set upright posture.");
}

void loop() {
  uint32_t now = millis();
  samplePulse();                       // drains the pulse FIFO (never misses a sample)
  checkPulseHealth();
  if (now - lastSampleMs >= SAMPLE_MS) {
    lastSampleMs = now;
    sampleOthers();
  }
  if (now - lastReportMs >= REPORT_MS) {
    lastReportMs = now;
    report();
  }
  handleSerial();
  delay(1);
}
