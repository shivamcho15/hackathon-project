// smoke_test.ino — hardware verification for the earthquake-assess sensor node
//
// This is NOT the measurement firmware. It answers one question: is this hardware
// capable of delivering what PIPELINE.md assumes? It runs staged checks, prints a
// PASS/FAIL summary, then streams live so you can tilt and stomp.
//
// It also brings up ArduinoOTA. Once this sketch is on the board, every later
// firmware push happens over WiFi - no BOOT jumper, no USB cable. This board has
// no DTR->GPIO0 auto-download circuit (verified by sweeping every reset sequence
// esptool supports), so the first flash must be manual. Only the first.
//
// Board: ESP32-WROOM-32   FQBN esp32:esp32:esp32
// Wiring (PROD_DOC §12.4): VCC->3V3  GND->GND  SDA->GPIO21  SCL->GPIO22
//
// Every line is prefixed with a [TAG] so the capture script can parse it.

#include <Wire.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

#include "secrets.h"

// Credentials are stored in NVS (survives reboots and reflashes) and can be set
// at runtime over USB with:  wifi <ssid>|<password>
// That matters because the network changes tomorrow - the venue runs on Shivam's
// hotspot, not home WiFi - and recompiling for a new SSID would mean refitting
// the GPIO0 jumper. This way a network change is one serial command.
Preferences prefs;
String cfgSsid, cfgPass;

// Node identity ("top" or "ground") is a firmware/NVS constant, NOT an AD0
// address - AD0 only distinguishes two sensors sharing one bus. Stored in NVS so
// a node can be relabelled with a serial command instead of a reflash, and so it
// survives being carried to a different floor. Also drives the OTA hostname, so
// the two boards are separately addressable over WiFi.
String cfgNode = "unset";

// Rotation from sensor axes into a gravity-aligned frame, built from the measured
// baseline. Row 2 is "up"; rows 0 and 1 span the true horizontal plane.
float rot[3][3];
bool  rotValid = false;

// ---- config from PIPELINE.md §1 -------------------------------------------
static const uint32_t TARGET_HZ   = 200;          // fs the whole pipeline assumes
static const uint32_t SAMPLE_US   = 1000000UL / TARGET_HZ;  // 5000 us
static const uint32_t I2C_HZ      = 400000;       // 400 kHz; GY-521 handles it
static const float    CLIP_MS2    = 19.0;         // +/-2g rail is 19.62 m/s^2

// MPU-6050 registers we read back to prove the config actually took
static const uint8_t REG_SMPLRT_DIV   = 0x19;
static const uint8_t REG_CONFIG       = 0x1A;
static const uint8_t REG_ACCEL_CONFIG = 0x1C;
static const uint8_t REG_WHO_AM_I     = 0x75;

Adafruit_MPU6050 mpu;
uint8_t sensorAddr   = 0;
bool    stagesPassed = true;
bool    wifiUp       = false;
float   rateNoWifi   = 0;
float   rateWithWifi = 0;

// ---- small I2C helpers ----------------------------------------------------
bool readReg(uint8_t addr, uint8_t reg, uint8_t &out) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)addr, 1) != 1) return false;
  out = Wire.read();
  return true;
}

void fail(const char *stage, const char *msg) {
  Serial.printf("[FAIL] %s: %s\n", stage, msg);
  stagesPassed = false;
}

// ---- stage 1: who is on the bus ------------------------------------------
void stageScan() {
  Serial.println("[STAGE] 1 I2C bus scan");
  Serial.printf("[SCAN] using SDA=%d SCL=%d clock=%lu Hz\n", SDA, SCL, (unsigned long)I2C_HZ);
  int found = 0;
  for (uint8_t a = 0x08; a < 0x78; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf("[SCAN] device at 0x%02X\n", a);
      found++;
      if ((a == 0x68 || a == 0x69) && sensorAddr == 0) sensorAddr = a;
    }
  }
  Serial.printf("[SCAN] %d device(s) found\n", found);
  if (sensorAddr == 0) {
    fail("scan", "nothing at 0x68 or 0x69 - check 3V3, GND, SDA/SCL, and AD0");
  } else {
    Serial.printf("[SCAN] using MPU at 0x%02X (AD0 %s)\n",
                  sensorAddr, sensorAddr == 0x68 ? "low/floating" : "high");
  }
}

// ---- stage 2: is it really an MPU-6050 -----------------------------------
// GY-521 boards are sometimes shipped with MPU-6500/9250 dies, which report a
// different WHO_AM_I and have different DLPF register semantics. If this is a
// clone, PIPELINE.md's 44 Hz DLPF setting does not mean what the doc says.
void stageIdentity() {
  Serial.println("[STAGE] 2 chip identity");
  uint8_t who = 0;
  if (!readReg(sensorAddr, REG_WHO_AM_I, who)) { fail("identity", "WHO_AM_I read failed"); return; }
  Serial.printf("[WHOAMI] 0x%02X\n", who);
  if (who == 0x68)      Serial.println("[WHOAMI] genuine MPU-6050");
  else if (who == 0x70) fail("identity", "0x70 = MPU-6500 clone, not MPU-6050");
  else if (who == 0x71) fail("identity", "0x71 = MPU-9250 clone, not MPU-6050");
  else                  fail("identity", "unrecognised WHO_AM_I");
}

// ---- stage 3: apply and VERIFY the PIPELINE.md config --------------------
void stageConfig() {
  Serial.println("[STAGE] 3 sensor config");
  if (!mpu.begin(sensorAddr, &Wire)) { fail("config", "mpu.begin() failed"); return; }

  mpu.setAccelerometerRange(MPU6050_RANGE_2_G);      // best resolution for small sway
  mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);        // PIPELINE.md §1 anti-alias
  mpu.setSampleRateDivisor(4);                       // 1000/(1+4) = 200 Hz

  // Read the registers back. A library call that silently no-ops is exactly the
  // kind of thing that produces a plausible-looking wrong answer downstream.
  uint8_t div = 0, cfg = 0, acfg = 0;
  readReg(sensorAddr, REG_SMPLRT_DIV, div);
  readReg(sensorAddr, REG_CONFIG, cfg);
  readReg(sensorAddr, REG_ACCEL_CONFIG, acfg);
  uint8_t dlpf = cfg & 0x07;
  uint8_t afs  = (acfg >> 3) & 0x03;
  Serial.printf("[REG] SMPLRT_DIV=%u (expect 4)\n", div);
  Serial.printf("[REG] DLPF_CFG=%u (expect 3 = 44 Hz accel bandwidth)\n", dlpf);
  Serial.printf("[REG] AFS_SEL=%u (expect 0 = +/-2g)\n", afs);
  if (div != 4)  fail("config", "sample rate divisor did not take");
  if (dlpf != 3) fail("config", "DLPF did not take - aliasing risk");
  if (afs != 0)  fail("config", "accel range did not take");
}

// ---- stage 4: gravity, orientation, and the vertical-axis rule -----------
// Exercises PIPELINE.md §2 step 2 on real hardware: the vertical axis is the one
// whose baseline mean is ~9.81, identified from data, not from the tape job.
void stageGravity() {
  Serial.println("[STAGE] 4 gravity / orientation baseline (hold still, 2 s)");
  const int N = 400;
  double sx = 0, sy = 0, sz = 0;
  sensors_event_t a, g, t;
  for (int i = 0; i < N; i++) {
    mpu.getEvent(&a, &g, &t);
    sx += a.acceleration.x; sy += a.acceleration.y; sz += a.acceleration.z;
    delay(5);
  }
  float mx = sx / N, my = sy / N, mz = sz / N;
  float mag = sqrt(mx*mx + my*my + mz*mz);
  Serial.printf("[BASELINE] mean ax=%.3f ay=%.3f az=%.3f m/s^2\n", mx, my, mz);
  Serial.printf("[BASELINE] |a|=%.3f m/s^2 (expect 9.6-10.0)\n", mag);

  float amx = fabs(mx), amy = fabs(my), amz = fabs(mz);
  const char *vert = (amz >= amx && amz >= amy) ? "Z" : (amy >= amx ? "Y" : "X");
  Serial.printf("[BASELINE] vertical axis = %s -> horizontals are the other two\n", vert);
  Serial.printf("[BASELINE] temp=%.1f C\n", t.temperature);

  buildRotation(mx, my, mz, mag);

  if (mag < 9.3 || mag > 10.3) fail("gravity", "gravity magnitude off - sensor may be faulty or mis-scaled");
}

// ---- tilt correction ------------------------------------------------------
// The modules were hand-soldered, so they sit at an angle: solder blobs on the
// underside and headers that aren't quite perpendicular. Picking the axis with the
// largest gravity component (above) identifies "up" correctly, but the other two
// axes still carry a share of gravity, which means they are not horizontal. The
// PCA sway projection in PIPELINE.md §2 would then be finding the dominant motion
// direction inside a tilted plane, not the real horizontal one.
//
// Fix it in software rather than with tape: gravity always points down, so one
// baseline measurement fully determines the board's orientation. Build an
// orthonormal basis whose third row is the measured up-vector and rotate every
// sample into it. Tilt then stops mattering up to ~45 degrees, and it also handles
// a sensor that ends up on an uneven floor or shifts mid-session.
void buildRotation(float gx, float gy, float gz, float mag) {
  if (mag < 1e-3) { rotValid = false; return; }

  // Row 2 = unit vector pointing along measured gravity ("up" in sensor axes).
  float uz[3] = { gx / mag, gy / mag, gz / mag };

  // Pick any axis not nearly parallel to up, to seed the horizontal plane.
  float seed[3] = {1, 0, 0};
  if (fabs(uz[0]) > 0.9f) { seed[0] = 0; seed[1] = 1; }

  // Row 0 = seed with its vertical component removed, normalised.
  float d = seed[0]*uz[0] + seed[1]*uz[1] + seed[2]*uz[2];
  float ux[3] = { seed[0] - d*uz[0], seed[1] - d*uz[1], seed[2] - d*uz[2] };
  float nx = sqrt(ux[0]*ux[0] + ux[1]*ux[1] + ux[2]*ux[2]);
  if (nx < 1e-6) { rotValid = false; return; }
  for (int i = 0; i < 3; i++) ux[i] /= nx;

  // Row 1 = up x row0, completing a right-handed orthonormal basis.
  float uy[3] = { uz[1]*ux[2] - uz[2]*ux[1],
                  uz[2]*ux[0] - uz[0]*ux[2],
                  uz[0]*ux[1] - uz[1]*ux[0] };

  for (int i = 0; i < 3; i++) { rot[0][i] = ux[i]; rot[1][i] = uy[i]; rot[2][i] = uz[i]; }
  rotValid = true;

  float tiltDeg = acos(constrain(uz[2], -1.0f, 1.0f)) * 180.0f / PI;
  Serial.printf("[TILT] board is %.1f deg off level; rotation built\n", tiltDeg);
  Serial.println("[TILT] h1/h2 below are TRUE horizontal axes, v is true vertical");
}

// Rotate a raw sample into the level frame. h1,h2 = horizontal (what the sway
// analysis uses), v = vertical (discarded by PIPELINE.md §2 step 5).
void applyRotation(float ax, float ay, float az, float &h1, float &h2, float &v) {
  if (!rotValid) { h1 = ax; h2 = ay; v = az; return; }
  h1 = rot[0][0]*ax + rot[0][1]*ay + rot[0][2]*az;
  h2 = rot[1][0]*ax + rot[1][1]*ay + rot[1][2]*az;
  v  = rot[2][0]*ax + rot[2][1]*ay + rot[2][2]*az;
}

// ---- the number that actually matters ------------------------------------
// Run twice: once with the radio off, once with WiFi associated. The production
// firmware samples *while* transmitting, and the WiFi stack shares the CPU and
// adds interrupt latency - so the quiet-room number alone would be misleading.
float stageRate(const char *label) {
  Serial.printf("[STAGE] 5 sample rate (%s)\n", label);
  sensors_event_t a, g, t;

  // unpaced ceiling - how fast CAN we read
  uint32_t t0 = micros();
  uint32_t n = 0;
  while (micros() - t0 < 2000000UL) { mpu.getEvent(&a, &g, &t); n++; }
  float ceilingHz = n / ((micros() - t0) / 1e6f);
  Serial.printf("[RATE:%s] unpaced ceiling = %.1f Hz (need >= %lu)\n",
                label, ceilingHz, (unsigned long)TARGET_HZ);
  if (ceilingHz < TARGET_HZ * 1.2f)
    fail("rate", "not enough headroom above 200 Hz - raise I2C clock or burst-read registers");

  // paced loop on a fixed deadline accumulator, so error cannot accumulate
  const uint32_t WANT = TARGET_HZ * 5;   // 5 seconds
  uint32_t next = micros();
  uint32_t prev = 0, minDt = 0xFFFFFFFF, maxDt = 0;
  double sumDt = 0, sumDt2 = 0;
  uint32_t late = 0;
  uint32_t start = micros();
  for (uint32_t i = 0; i < WANT; i++) {
    next += SAMPLE_US;
    if ((int32_t)(micros() - next) > 0) late++;       // missed the deadline
    while ((int32_t)(micros() - next) < 0) { /* spin */ }
    uint32_t now = micros();
    mpu.getEvent(&a, &g, &t);
    if (i > 0) {
      uint32_t dt = now - prev;
      if (dt < minDt) minDt = dt;
      if (dt > maxDt) maxDt = dt;
      sumDt += dt; sumDt2 += (double)dt * dt;
    }
    prev = now;
  }
  float elapsed = (micros() - start) / 1e6f;
  float actualHz = WANT / elapsed;
  double meanDt = sumDt / (WANT - 1);
  double sd = sqrt(sumDt2 / (WANT - 1) - meanDt * meanDt);
  Serial.printf("[RATE:%s] paced actual = %.3f Hz over %.3f s\n", label, actualHz, elapsed);
  Serial.printf("[RATE:%s] interval mean=%.1f us sd=%.1f us min=%lu max=%lu\n",
                label, meanDt, sd, (unsigned long)minDt, (unsigned long)maxDt);
  Serial.printf("[RATE:%s] missed deadlines = %lu / %lu\n",
                label, (unsigned long)late, (unsigned long)WANT);
  float errPct = 100.0f * fabs(actualHz - (float)TARGET_HZ) / TARGET_HZ;
  Serial.printf("[RATE:%s] fs error = %.3f %% (every reported frequency scales by this)\n",
                label, errPct);
  if (errPct > 1.0f) fail("rate", "fs off by >1% - backend must derive fs from timestamps");
  return actualHz;
}

// ---- WiFi + OTA ----------------------------------------------------------
// Deliberately non-fatal: a hardware smoke test must still report sensor results
// when the network is unavailable. WiFi failing is information, not a dead end.
bool connectWifi(const String &ssid, const String &pass) {
  if (ssid.length() == 0) {
    Serial.println("[WIFI] no network configured - set one with:  wifi <ssid>|<password>");
    return false;
  }

  Serial.printf("[WIFI] joining \"%s\" (2.4 GHz only)\n", ssid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid.c_str(), pass.c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) delay(250);

  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("[WIFI] FAILED to join after %lus (status=%d)\n",
                  (millis() - t0) / 1000, WiFi.status());
    Serial.println("[WIFI] check: 2.4 GHz enabled? password right? hotspot actually on?");
    wifiUp = false;
    return false;
  }

  wifiUp = true;
  Serial.printf("[WIFI] connected ip=%s rssi=%d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  // Hostname carries the node identity so the two boards are separately
  // addressable over WiFi - otherwise both answer to the same name and OTA can
  // only be done by IP, which changes on every DHCP lease.
  String host = "quake-" + cfgNode;
  ArduinoOTA.setHostname(host.c_str());
  ArduinoOTA.onStart([]() { Serial.println("[OTA] update starting"); });
  ArduinoOTA.onEnd([]()   { Serial.println("[OTA] done, rebooting"); });
  ArduinoOTA.onError([](ota_error_t e) { Serial.printf("[OTA] error %u\n", e); });
  ArduinoOTA.begin();
  Serial.printf("[OTA] ready as \"%s\" at %s\n", host.c_str(), WiFi.localIP().toString().c_str());
  Serial.println("[OTA] future firmware pushes need no cable and no BOOT jumper");
  return true;
}

void stageWifi() {
  Serial.println("[STAGE] 6 WiFi + OTA");

  // NVS first, compiled-in secrets.h only as a fallback. Saved credentials
  // survive both reboots and reflashes, so this is set once and forgotten.
  prefs.begin("quake", false);
  cfgSsid = prefs.getString("ssid", WIFI_SSID);
  cfgPass = prefs.getString("pass", WIFI_PASSWORD);
  cfgNode = prefs.getString("node", "unset");
  prefs.end();

  Serial.printf("[NODE] identity = \"%s\"\n", cfgNode.c_str());
  if (cfgNode == "unset")
    Serial.println("[NODE] ⚠ unlabelled - set with:  node top   or   node ground");

  if (cfgSsid.length() == 0) {
    Serial.println("[WIFI] no credentials stored yet");
    Serial.println("[WIFI] send over USB:  wifi <ssid>|<password>");
    Serial.println("[WIFI] hardware checks above are unaffected");
    return;
  }
  connectWifi(cfgSsid, cfgPass);
}

// Runtime commands over USB. Keeps network changes from requiring a reflash.
void handleSerialCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.startsWith("wifi ")) {
    // "wifi <ssid>|<password>" - split on '|' so an SSID containing spaces works.
    String rest = line.substring(5);
    int bar = rest.indexOf('|');
    if (bar < 0) { Serial.println("[CMD] usage: wifi <ssid>|<password>"); return; }
    String ssid = rest.substring(0, bar);      ssid.trim();
    String pass = rest.substring(bar + 1);     pass.trim();

    prefs.begin("quake", false);
    prefs.putString("ssid", ssid);
    prefs.putString("pass", pass);
    prefs.end();
    Serial.printf("[CMD] saved credentials for \"%s\"\n", ssid.c_str());

    cfgSsid = ssid; cfgPass = pass;
    connectWifi(cfgSsid, cfgPass);

  } else if (line.startsWith("node ")) {
    String id = line.substring(5); id.trim();
    if (id != "top" && id != "ground") {
      Serial.println("[CMD] usage: node top   |   node ground");
      return;
    }
    prefs.begin("quake", false);
    prefs.putString("node", id);
    prefs.end();
    cfgNode = id;
    Serial.printf("[CMD] node identity set to \"%s\" (persists across reflash)\n", id.c_str());
    Serial.println("[CMD] reboot for the OTA hostname to follow");

  } else if (line == "status") {
    Serial.printf("[CMD] wifi=%s ssid=\"%s\" ip=%s ota=%s sensor=0x%02X\n",
                  wifiUp ? "up" : "down", cfgSsid.c_str(),
                  wifiUp ? WiFi.localIP().toString().c_str() : "-",
                  wifiUp ? "ready" : "unavailable", sensorAddr);

  } else if (line == "scan") {
    Serial.println("[CMD] scanning for 2.4 GHz networks ...");
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++)
      Serial.printf("[CMD]   \"%s\"  %d dBm\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i));
    Serial.printf("[CMD] %d network(s)\n", n);

  } else if (line == "help") {
    Serial.println("[CMD] wifi <ssid>|<password>   save credentials and connect");
    Serial.println("[CMD] scan                     list visible 2.4 GHz networks");
    Serial.println("[CMD] status                   current state");

  } else {
    Serial.printf("[CMD] unknown: \"%s\" (try: help)\n", line.c_str());
  }
}

void stageSummary() {
  Serial.println("[STAGE] 7 summary");
  if (rateNoWifi > 0 && rateWithWifi > 0) {
    Serial.printf("[SUMMARY] rate no-wifi=%.2f Hz  with-wifi=%.2f Hz  delta=%.2f Hz\n",
                  rateNoWifi, rateWithWifi, rateWithWifi - rateNoWifi);
  }
  Serial.printf("[SUMMARY] wifi=%s ota=%s\n", wifiUp ? "up" : "down", wifiUp ? "ready" : "unavailable");
  Serial.printf("[SUMMARY] %s\n", stagesPassed ? "ALL CHECKS PASSED" : "ONE OR MORE CHECKS FAILED");
  Serial.println("[SUMMARY] entering live mode - tilt the sensor, then stomp near it");
  Serial.println("[SUMMARY] watch clip= : if it ever goes nonzero, +/-2g is too sensitive");
}

void setup() {
  Serial.begin(115200);
  delay(600);
  Serial.println();
  Serial.println("[BOOT] earthquake-assess smoke test");
  Serial.printf("[BOOT] chip=%s rev=%d cores=%d flash=%luMB\n",
                ESP.getChipModel(), ESP.getChipRevision(), ESP.getChipCores(),
                ESP.getFlashChipSize() / (1024UL * 1024UL));

  Wire.begin();
  Wire.setClock(I2C_HZ);

  stageScan();
  if (sensorAddr) {
    stageIdentity();
    stageConfig();
    stageGravity();
    rateNoWifi = stageRate("no-wifi");
  } else {
    Serial.println("[FAIL] skipping sensor stages, nothing on the bus");
  }

  stageWifi();

  // Re-measure with the radio associated. This is the number that predicts
  // production behaviour, and the one to quote to Shivam.
  if (sensorAddr && wifiUp) rateWithWifi = stageRate("with-wifi");

  stageSummary();
}

// Live mode: paced at 200 Hz, reporting peak-hold every 500 ms. Peak-hold is what
// catches a stomp - a 2 Hz print of instantaneous values would miss the transient.
void loop() {
  static uint32_t next = micros();
  static uint32_t windowStart = millis();
  static uint32_t n = 0;
  static float pk[3] = {0, 0, 0};
  static uint32_t clips = 0;
  sensors_event_t a, g, t;

  if (wifiUp) ArduinoOTA.handle();

  // Non-blocking line reader for the runtime commands above.
  static String cmdBuf;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdBuf.length()) { handleSerialCommand(cmdBuf); cmdBuf = ""; }
    } else if (cmdBuf.length() < 160) {
      cmdBuf += c;
    }
  }

  if (!sensorAddr) { delay(1000); return; }

  next += SAMPLE_US;

  // ⚠ Deadline resync. Anything that blocks - a WiFi reconnect, an OTA transfer -
  // leaves `next` far in the past, and the spin below then exits instantly for
  // hundreds of iterations while the loop sprints at ~1000 Hz to "catch up".
  // Observed live: a WiFi connect produced a burst at 968 Hz.
  //
  // Harmless here, but NOT harmless in the streaming firmware: it would emit a
  // burst of samples whose real spacing is 1 ms while their timestamps claim 5 ms.
  // The backend assumes uniform spacing, so it would analyse that as genuine
  // signal and report a wrong frequency with no flag raised. Dropping the missed
  // samples outright is correct - a gap the backend can see beats fabricated
  // density it cannot.
  int32_t behind = (int32_t)(micros() - next);
  if (behind > (int32_t)(4 * SAMPLE_US)) {
    next = micros() + SAMPLE_US;
    Serial.printf("[RESYNC] loop was %ld us behind; schedule reset, %ld samples dropped\n",
                  (long)behind, (long)(behind / SAMPLE_US));
  }

  while ((int32_t)(micros() - next) < 0) { /* spin */ }
  mpu.getEvent(&a, &g, &t);
  n++;

  float h1, h2, vv;
  applyRotation(a.acceleration.x, a.acceleration.y, a.acceleration.z, h1, h2, vv);
  float v[3] = {h1, h2, vv};

  // Clip detection stays on the RAW axes - saturation happens in the sensor,
  // before any rotation, so checking rotated values could hide a railed axis.
  float raw[3] = {a.acceleration.x, a.acceleration.y, a.acceleration.z};
  for (int i = 0; i < 3; i++) {
    if (fabs(v[i]) > pk[i]) pk[i] = fabs(v[i]);
    if (fabs(raw[i]) > CLIP_MS2) clips++;
  }

  if (millis() - windowStart >= 500) {
    float hz = n * 1000.0f / (millis() - windowStart);
    Serial.printf("[LIVE] hz=%.1f h1=%+.2f h2=%+.2f v=%+.2f peak=%.2f/%.2f/%.2f clip=%lu\n",
                  hz, v[0], v[1], v[2], pk[0], pk[1], pk[2], (unsigned long)clips);
    windowStart = millis();
    n = 0;
    pk[0] = pk[1] = pk[2] = 0;
  }
}
