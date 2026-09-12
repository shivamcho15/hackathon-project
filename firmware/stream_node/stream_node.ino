// stream_node.ino — the measurement firmware
//
// Streams accelerometer samples to the backend in the SCHEMA.md §1 wire format,
// batched ~20 per message per PIPELINE.md §1. Also mirrors to USB serial, which is
// the PLAN.md item 9 fallback path.
//
// Board: ESP32-WROOM-32   FQBN esp32:esp32:esp32
//
// ⚠ SAFETY ORDER OF OPERATIONS: WiFi and OTA come up FIRST, before the sensor or
// anything else that could hang or crash. If a later stage fails, the node is
// still reachable for a firmware fix. Bricking OTA means someone has to hold the
// IO0 button again, which is exactly what we built OTA to avoid.
//
// Runtime commands over USB or the serial monitor:
//   wifi <ssid>|<password>    save credentials and connect
//   node top | node ground    set this node's identity (persists)
//   server <host>:<port>      backend WebSocket endpoint (persists)
//   calibrate                 re-measure tilt; hold the sensor still
//   stream on | stream off    start/stop sending samples
//   status | scan | help

#include <Wire.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <WebSocketsClient.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

#include "secrets.h"
#include "ui.h"

Ui ui;
// A button-started session records for a fixed window and stops on its own, so a
// judge can press once and get a result without anyone touching a laptop. Separate
// from the `stream on` command, which streams until told otherwise.
uint32_t sessionEndsAt = 0;
// True when the button press is what started streaming, so the window end knows
// whether stopping the stream is correct or whether it would silence an
// autostreaming node that was already running. See the loop() comment.
bool     sessionOwnsStream = false;

// ---- config (PIPELINE.md §1) ----------------------------------------------
static const uint32_t TARGET_HZ  = 200;
static const uint32_t SAMPLE_US  = 1000000UL / TARGET_HZ;
static const uint32_t I2C_HZ     = 400000;
static const int      BATCH_N    = 20;      // 20 samples = 100 ms per message
static const float    CLIP_MS2   = 19.0;    // ±2 g rail is 19.62

Preferences prefs;
WebSocketsClient ws;

// Up to TWO sensors on the one I2C bus, told apart by their AD0 pin: 0x68 and
// 0x69 (PROD_DOC §12.4). That configuration is the bench/tower rig - both sensors
// read by the same microcontroller loop within ~200 us of each other, so they are
// perfectly synchronised with no wireless sync at all. It is strictly better than
// two nodes for the tower demo, and it is what makes a top/ground ratio from the
// model towers trustworthy.
//
// With two sensors present the board emits BOTH channels: 0x68 -> "ground",
// 0x69 -> "top". With one, it emits whatever this node is labelled.
static const int MAX_SENS = 2;
Adafruit_MPU6050 mpu[MAX_SENS];
uint8_t  addrs[MAX_SENS] = {0, 0};
String   labels[MAX_SENS];
int      sensorCount = 0;

String   cfgSsid, cfgPass, cfgNode = "unset", cfgHost = "";
uint16_t cfgPort = 8000;

// Start streaming automatically at boot, persisted in NVS.
//
// Not a convenience - a requirement for the untethered demo. Running from a USB
// power bank there is no laptop attached and therefore nobody to type "stream on".
// It also matters on the bench: closing the serial port resets the board (RTS
// drives EN), so a node only streams for as long as something holds the port open,
// which silently defeats any long-running test.
bool     cfgAutostream = false;
bool     wifiUp = false, wsUp = false, streaming = false, sensorOk = false;

// Mirroring every batch to USB is the PLAN.md item 9 fallback, but it is NOT free
// and must stay off by default. A 20-sample batch is ~1.9 kB of JSON; at 115200
// baud that takes ~165 ms to push out, which is longer than the 100 ms of data it
// represents. The loop then falls permanently behind and the resync logic drops
// ~23 samples every batch - a 10 % hole in the data, repeating, forever.
// Measured live before this was fixed: "[RESYNC] 119636 us behind" every batch.
// Hence: 921600 baud (~21 ms per batch), and off unless explicitly asked for.
bool     serialData = false;

// Set when streaming starts so the paced schedule restarts from "now". Without it
// the first batch reports a large spurious drop, because `next` still holds a
// deadline from whenever streaming was last active.
bool     resetSchedule = false;

// When the socket went down mid-measurement, so a drop can never become permanent.
uint32_t wsDownSince = 0;
// Bounded window during which we pump ws.loop() hard to complete a reconnect.
uint32_t reconnectUntil = 0;

// NTP anchor: epoch ms captured once, then advanced by millis(). Sampling at
// 200 Hz needs sub-second resolution that time(nullptr) alone cannot give.
uint64_t epochAtSync = 0;
uint32_t millisAtSync = 0;

// Tilt rotation, from the measured gravity vector. NOT applied to streamed
// samples - see "wire format" note below.
float rot[MAX_SENS][3][3];
bool  rotValid[MAX_SENS] = {false, false};
float tiltDeg[MAX_SENS] = {0, 0}, gravMag[MAX_SENS] = {0, 0};

// Batch buffer
struct Sample { uint64_t t; float ax, ay, az; };
Sample batch[MAX_SENS][BATCH_N];
int    batchLen = 0;
uint32_t sentBatches = 0, clips = 0, droppedTotal = 0;

uint64_t nowMs() {
  if (epochAtSync == 0) return millis();          // pre-NTP: relative is better than fake
  return epochAtSync + (uint64_t)(millis() - millisAtSync);
}

// ---- WiFi + OTA, brought up first ----------------------------------------
bool connectWifi() {
  if (cfgSsid.length() == 0) { Serial.println("[WIFI] no credentials; set with: wifi <ssid>|<pass>"); return false; }
  Serial.printf("[WIFI] joining \"%s\"\n", cfgSsid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);          // sleep adds latency jitter to the stream
  WiFi.setAutoReconnect(true);   // first line of defence; loop() is the backstop
  WiFi.begin(cfgSsid.c_str(), cfgPass.c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) delay(250);
  if (WiFi.status() != WL_CONNECTED) { Serial.println("[WIFI] FAILED"); return false; }
  wifiUp = true;
  Serial.printf("[WIFI] ip=%s rssi=%d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  return true;
}

void startOta() {
  String host = "quake-" + cfgNode;
  ArduinoOTA.setHostname(host.c_str());
  ArduinoOTA.onStart([]() { streaming = false; Serial.println("[OTA] update starting"); });
  ArduinoOTA.onEnd([]()   { Serial.println("[OTA] done"); });
  ArduinoOTA.begin();
  Serial.printf("[OTA] ready as \"%s\" at %s\n", host.c_str(), WiFi.localIP().toString().c_str());
}

void syncTime() {
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  Serial.print("[NTP] syncing");
  uint32_t t0 = millis();
  time_t now = 0;
  while (millis() - t0 < 10000) {
    now = time(nullptr);
    if (now > 1700000000) break;     // sane epoch => sync landed
    Serial.print(".");
    delay(300);
  }
  Serial.println();
  if (now > 1700000000) {
    epochAtSync  = (uint64_t)now * 1000ULL;
    millisAtSync = millis();
    Serial.printf("[NTP] epoch_ms=%llu\n", (unsigned long long)epochAtSync);
  } else {
    // Deliberately do NOT fake a timestamp. Relative millis is honest and the
    // backend derives fs from deltas anyway; a wrong absolute epoch would
    // silently misalign two nodes, which is worse than an obviously relative one.
    Serial.println("[NTP] FAILED - timestamps will be relative (millis), not epoch");
  }
}

// ---- sensor ---------------------------------------------------------------
bool initSensor() {
  Wire.begin();
  Wire.setClock(I2C_HZ);
  sensorCount = 0;
  for (uint8_t a : {0x68, 0x69}) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() != 0) continue;
    if (!mpu[sensorCount].begin(a, &Wire)) {
      Serial.printf("[SENSOR] 0x%02X answered the bus but begin() failed\n", a);
      continue;
    }
    mpu[sensorCount].setAccelerometerRange(MPU6050_RANGE_2_G);
    mpu[sensorCount].setFilterBandwidth(MPU6050_BAND_44_HZ);
    mpu[sensorCount].setSampleRateDivisor(4);
    addrs[sensorCount] = a;
    sensorCount++;
  }
  if (!sensorCount) { Serial.println("[SENSOR] none found on the bus"); return false; }

  // Channel labels. Two sensors on one board IS the top/ground pair, so the
  // per-board identity doesn't apply - AD0 decides. That also removes the
  // "carried the wrong node upstairs" risk PROTOCOL.md flags, because in this
  // configuration neither sensor goes anywhere.
  if (sensorCount == 2) {
    labels[0] = "ground";   // 0x68, AD0 low
    labels[1] = "top";      // 0x69, AD0 high
    Serial.println("[SENSOR] TWO sensors -> emitting both channels, hardware-synchronised");
  } else {
    labels[0] = cfgNode;
    Serial.printf("[SENSOR] one sensor -> emitting as \"%s\"\n", cfgNode.c_str());
  }
  for (int i = 0; i < sensorCount; i++)
    Serial.printf("[SENSOR] 0x%02X = \"%s\", +/-2g, DLPF 44 Hz, 200 Hz\n",
                  addrs[i], labels[i].c_str());
  return true;
}

// Measure gravity and build a rotation into a level frame. Also reports whether
// the sensor was actually still while measuring - a calibration taken while the
// board is being handled is worse than none, because it looks valid.
void calibrateOne(int s) {
  const int N = 400;
  double sx = 0, sy = 0, sz = 0, s2 = 0;
  sensors_event_t a, g, t;
  for (int i = 0; i < N; i++) {
    mpu[s].getEvent(&a, &g, &t);
    float m = sqrt(a.acceleration.x*a.acceleration.x + a.acceleration.y*a.acceleration.y
                 + a.acceleration.z*a.acceleration.z);
    sx += a.acceleration.x; sy += a.acceleration.y; sz += a.acceleration.z;
    s2 += (double)m * m;
    delay(5);
  }
  float mx = sx/N, my = sy/N, mz = sz/N;
  float gm = sqrt(mx*mx + my*my + mz*mz);
  gravMag[s] = gm;
  float wobble = fabs(sqrt(s2/N) - gm);

  Serial.printf("[CAL] %s: gravity=%.3f m/s^2  ax=%.3f ay=%.3f az=%.3f\n",
                labels[s].c_str(), gm, mx, my, mz);
  if (wobble > 0.15) {
    Serial.printf("[CAL] %s: REJECTED - sensor was moving (wobble %.3f). Hold still and retry.\n",
                  labels[s].c_str(), wobble);
    return;
  }
  // Sanity bound, NOT a calibration standard. Node B measures 10.63 repeatably
  // (three runs within 0.01, wobble check passed - so this is the sensor's scale,
  // not movement), and the old 10.6 ceiling rejected it by 0.03 m/s^2. That cost
  // the tilt rotation entirely for a 0.3 % margin, which is the wrong trade: a
  // scale error 8 % high is a mediocre MPU-6050, not a broken one, and it does not
  // move a spectral peak - frequency comes from timing, not amplitude. What the
  // bound is really for is catching a miswired or dead sensor, which reads near 0
  // or pegged at full scale, nowhere near here.
  //
  // So: still reject the genuinely absurd, but WARN and carry on in between rather
  // than silently discarding the rotation. Note the streamed ax/ay/az are raw
  // either way and the backend computes its own per-session gravity vector
  // (SCHEMA.md 1a), so a warn here costs nothing downstream.
  if (gm < 7.0 || gm > 12.0) {
    Serial.printf("[CAL] %s: gravity %.2f implausible - check wiring/sensor\n",
                  labels[s].c_str(), gm);
    return;
  }
  if (gm < 9.51 || gm > 10.11) {   // 9.81 +- 3 %, the MPU-6050's own spec
    Serial.printf("[CAL] %s: WARN gravity %.3f is %.1f%% off 9.81 - outside the "
                  "sensor's +-3%% spec. Proceeding; frequency is unaffected, but "
                  "any amplitude ratio involving this node inherits the error.\n",
                  labels[s].c_str(), gm, (gm - 9.81) / 9.81 * 100.0);
  }

  float uz[3] = { mx/gm, my/gm, mz/gm };
  float seed[3] = {1, 0, 0};
  if (fabs(uz[0]) > 0.9f) { seed[0] = 0; seed[1] = 1; }
  float d = seed[0]*uz[0] + seed[1]*uz[1] + seed[2]*uz[2];
  float ux[3] = { seed[0]-d*uz[0], seed[1]-d*uz[1], seed[2]-d*uz[2] };
  float nx = sqrt(ux[0]*ux[0]+ux[1]*ux[1]+ux[2]*ux[2]);
  if (nx < 1e-6) { Serial.println("[CAL] degenerate geometry"); return; }
  for (int i = 0; i < 3; i++) ux[i] /= nx;
  float uy[3] = { uz[1]*ux[2]-uz[2]*ux[1], uz[2]*ux[0]-uz[0]*ux[2], uz[0]*ux[1]-uz[1]*ux[0] };
  for (int i = 0; i < 3; i++) { rot[s][0][i]=ux[i]; rot[s][1][i]=uy[i]; rot[s][2][i]=uz[i]; }
  rotValid[s] = true;
  tiltDeg[s] = acos(constrain(uz[2], -1.0f, 1.0f)) * 180.0f / PI;
  Serial.printf("[CAL] %s: OK - tilt %.1f deg, rotation stored\n", labels[s].c_str(), tiltDeg[s]);
}

void calibrate() {
  if (!sensorOk) { Serial.println("[CAL] no sensor"); return; }
  Serial.println("[CAL] CALIBRATING - hold still (2 s per sensor)");
  // Each sensor gets its own rotation: on the tower rig they are taped to
  // different floors at different angles, so one shared correction would be wrong
  // for at least one of them.
  for (int s = 0; s < sensorCount; s++) calibrateOne(s);
}

// ---- transport ------------------------------------------------------------
// Wire format is SCHEMA.md §1 verbatim, batched into a JSON array per
// PIPELINE.md §1. Built by hand rather than with ArduinoJson: the shape is fixed
// and trivial, and this avoids allocating a document 200 times a second.
//
// ⚠ ax/ay/az are RAW SENSOR AXES, deliberately NOT tilt-corrected. CLAUDE.md §6
// says neither side changes the wire format alone, and silently changing what
// ax/ay/az mean is exactly that. The rotation is reported separately in the hello
// message so Shivam can opt into using it. See firmware/README.md.
// One message per sensor. Each message stays a flat array of samples from a single
// node, exactly as SCHEMA.md §1 describes - two sensors produce two messages, not
// one interleaved message, so nothing about the format changes.
void emitBatch() {
  static char buf[2048];
  for (int s = 0; s < sensorCount; s++) {
    int n = snprintf(buf, sizeof(buf), "[");
    for (int i = 0; i < batchLen; i++) {
      n += snprintf(buf + n, sizeof(buf) - n,
                    "%s{\"t\":%llu,\"node\":\"%s\",\"ax\":%.4f,\"ay\":%.4f,\"az\":%.4f}",
                    i ? "," : "", (unsigned long long)batch[s][i].t, labels[s].c_str(),
                    batch[s][i].ax, batch[s][i].ay, batch[s][i].az);
    }
    snprintf(buf + n, sizeof(buf) - n, "]");

    if (wsUp) ws.sendTXT(buf);
    if (serialData) Serial.printf("[DATA] %s\n", buf);   // fallback only - see note above
    sentBatches++;
  }
}

// Additive handshake so the pre-flight screen can catch a swapped top/ground node
// (PROTOCOL.md logistics risk). Not yet in SCHEMA.md - proposed, not imposed.
// One hello per CHANNEL, not per board. With two sensors the backend needs to know
// both exist and how each is oriented; a board-level hello would hide the second
// channel entirely.
void sendHello() {
  char buf[512];
  for (int s = 0; s < sensorCount; s++) {
    snprintf(buf, sizeof(buf),
      "{\"type\":\"hello\",\"node\":\"%s\",\"fs_hz\":%u,\"mac\":\"%s\",\"rssi\":%d,"
      "\"i2c_addr\":\"0x%02X\",\"sensors_on_board\":%d,"
      "\"tilt_deg\":%.1f,\"gravity_ms2\":%.3f,\"calibrated\":%s,\"firmware\":\"stream_node\"}",
      labels[s].c_str(), TARGET_HZ, WiFi.macAddress().c_str(), WiFi.RSSI(),
      addrs[s], sensorCount,
      tiltDeg[s], gravMag[s], rotValid[s] ? "true" : "false");
    if (wsUp) ws.sendTXT(buf);
    Serial.printf("[HELLO] %s\n", buf);
  }
}

// Announce a physical button press so the backend opens a session for it.
//
// ⚠ Without this the button is cosmetic. The node would run its own countdown and
// 12 s window locally, the backend would see samples with no session open, no
// analysis would run, and no "result" would ever come back to display - so the LCD
// would sit on ANALYSING forever. SCHEMA.md §4b (the result push) only fires when a
// session exists, and every path that opens one ran through the frontend.
//
// Sent at PRESS time, not when recording starts, for two reasons: the backend owns
// the clock (SCHEMA.md §3 - it replies with armed_at/stomp_cue_at/window_ends_at),
// and the countdown itself is the guaranteed-quiet baseline (PIPELINE.md §5).
//
// One message per BOARD, not per channel - a press is one physical event. `mac`
// identifies the board unambiguously even when it carries two labelled sensors.
//
// ⚠ ADDITIVE node -> backend message, NOT YET AGREED (CLAUDE.md §6). Nothing in
// SCHEMA.md §1 changes. Harmless if the backend ignores unknown `type` values, which
// is the direction to fail in - the button then does nothing new rather than
// breaking the streaming path. Needs Shivam's yes before SCHEMA.md records it.
void sendButtonPress() {
  char buf[320];
  snprintf(buf, sizeof(buf),
    "{\"type\":\"button\",\"node\":\"%s\",\"mac\":\"%s\",\"sensors_on_board\":%d,"
    "\"countdown_s\":%u,\"duration_s\":%u,\"firmware\":\"stream_node\"}",
    labels[0].c_str(), WiFi.macAddress().c_str(), sensorCount,
    Ui::COUNTDOWN_MS / 1000, Ui::RECORD_MS / 1000);
  if (wsUp) ws.sendTXT(buf);
  Serial.printf("[BUTTON] %s\n", buf);
}

void onWsEvent(WStype_t type, uint8_t *payload, size_t len) {
  switch (type) {
    case WStype_CONNECTED:
      wsUp = true;
      Serial.println("[WS] connected");
      sendHello();
      break;
    case WStype_DISCONNECTED:
      wsUp = false;
      Serial.println("[WS] disconnected");
      break;
    case WStype_TEXT: {
      Serial.printf("[WS] rx: %.*s\n", (int)len, (char*)payload);
      // Backend result pushed back for the on-device display. Parsed by hand to
      // avoid pulling a JSON parser into a 90%-full flash for two fields.
      // Proposed shape: {"type":"result","frequency_hz":3.24,"confidence":"good"}
      String s((char*)payload, len);
      if (s.indexOf("\"result\"") >= 0) {
        int fi = s.indexOf("\"frequency_hz\"");
        if (fi >= 0) {
          float hz = s.substring(s.indexOf(':', fi) + 1).toFloat();
          int ci = s.indexOf("\"confidence\"");
          String conf = "";
          if (ci >= 0) {
            int q1 = s.indexOf('"', s.indexOf(':', ci));
            int q2 = s.indexOf('"', q1 + 1);
            if (q1 > 0 && q2 > q1) conf = s.substring(q1 + 1, q2);
          }
          ui.result(hz, conf.c_str());
        }
      }
      break;
    }
    default: break;
  }
}

void startWs() {
  if (cfgHost.length() == 0) { Serial.println("[WS] no server set; use: server <host>:<port>"); return; }
  Serial.printf("[WS] connecting to ws://%s:%u/ws\n", cfgHost.c_str(), cfgPort);
  ws.begin(cfgHost.c_str(), cfgPort, "/ws");
  ws.onEvent(onWsEvent);
  ws.setReconnectInterval(3000);   // non-blocking retry; never stalls sampling
}

// ---- commands -------------------------------------------------------------
void handleCommand(String line) {
  line.trim();
  if (!line.length()) return;

  if (line.startsWith("wifi ")) {
    String rest = line.substring(5);
    int bar = rest.indexOf('|');
    if (bar < 0) { Serial.println("[CMD] usage: wifi <ssid>|<password>"); return; }
    String s = rest.substring(0, bar); s.trim();
    String p = rest.substring(bar + 1); p.trim();
    prefs.begin("quake", false); prefs.putString("ssid", s); prefs.putString("pass", p); prefs.end();
    cfgSsid = s; cfgPass = p;
    Serial.printf("[CMD] saved \"%s\"\n", s.c_str());
    connectWifi();

  } else if (line.startsWith("node ")) {
    String id = line.substring(5); id.trim();
    if (id != "top" && id != "ground") { Serial.println("[CMD] usage: node top | node ground"); return; }
    prefs.begin("quake", false); prefs.putString("node", id); prefs.end();
    cfgNode = id;
    Serial.printf("[CMD] node = \"%s\" (reboot for OTA hostname)\n", id.c_str());

  } else if (line.startsWith("server ")) {
    String rest = line.substring(7); rest.trim();
    int c = rest.lastIndexOf(':');
    if (c < 0) { Serial.println("[CMD] usage: server <host>:<port>"); return; }
    cfgHost = rest.substring(0, c);
    cfgPort = rest.substring(c + 1).toInt();
    prefs.begin("quake", false); prefs.putString("host", cfgHost); prefs.putUShort("port", cfgPort); prefs.end();
    Serial.printf("[CMD] server = %s:%u\n", cfgHost.c_str(), cfgPort);
    startWs();

  } else if (line == "calibrate") {
    calibrate();

  } else if (line == "stream on") {
    if (!sensorOk) { Serial.println("[CMD] no sensor - cannot stream"); return; }
    streaming = true;  batchLen = 0;  resetSchedule = true;
    Serial.println("[CMD] streaming ON");

  // Persisted in NVS exactly like autostream, and for the same reason: opening the
  // serial port resets the board (RTS drives EN), so a setting that lived only in
  // RAM was erased by the very act of starting a capture. capture_serial.py
  // produced a log with zero [DATA] lines and no error - the node looked healthy
  // and the file was simply empty.
  //
  // This is load-bearing for the multi-floor building measurement, where USB serial
  // is the transport (WiFi will not span five floors of concrete) and each node is
  // plugged into a different laptop.
  } else if (line == "serial on" || line == "serial off") {
    serialData = line.endsWith("on");
    prefs.begin("quake", false); prefs.putBool("serialdata", serialData); prefs.end();
    Serial.printf("[CMD] serial data mirroring %s (persists across reboot and reflash)\n",
                  serialData ? "ON" : "OFF");

  } else if (line == "stream off") {
    streaming = false;
    Serial.println("[CMD] streaming OFF");

  } else if (line == "autostream on" || line == "autostream off") {
    cfgAutostream = line.endsWith("on");
    prefs.begin("quake", false); prefs.putBool("autostream", cfgAutostream); prefs.end();
    Serial.printf("[CMD] autostream %s (persists across reboot and reflash)\n",
                  cfgAutostream ? "ON" : "OFF");

  } else if (line == "status") {
    Serial.printf("[STATUS] node=%s wifi=%s ip=%s ws=%s server=%s:%u sensors=%d\n",
      cfgNode.c_str(), wifiUp ? "up" : "down",
      wifiUp ? WiFi.localIP().toString().c_str() : "-",
      wsUp ? "up" : "down", cfgHost.c_str(), cfgPort, sensorCount);
    for (int s = 0; s < sensorCount; s++)
      Serial.printf("[STATUS]   0x%02X \"%s\" tilt=%.1f grav=%.3f cal=%s\n",
        addrs[s], labels[s].c_str(), tiltDeg[s], gravMag[s], rotValid[s] ? "yes" : "no");
    Serial.printf("[STATUS] streaming=%s batches=%lu clips=%lu dropped=%lu epoch=%s\n",
      streaming ? "on" : "off", (unsigned long)sentBatches, (unsigned long)clips,
      (unsigned long)droppedTotal, epochAtSync ? "ntp" : "relative");

  } else if (line == "help") {
    Serial.println("[CMD] wifi <ssid>|<pass> / node top|ground / server <host>:<port>");
    Serial.println("[CMD] calibrate / stream on|off / serial on|off / autostream on|off");
    Serial.println("[CMD] status / help");

  } else {
    Serial.printf("[CMD] unknown: \"%s\"\n", line.c_str());
  }
}

// ---- setup / loop ---------------------------------------------------------
void setup() {
  // 921600, not 115200: the serial fallback has to carry ~19 kB/s of
  // batched JSON, which does not fit in a 115200 pipe. See serialData note.
  Serial.begin(921600);
  delay(600);
  Serial.println("\n[BOOT] earthquake-assess stream_node");
  // Build stamp. "Did that OTA actually land?" has wasted three separate rounds of
  // debugging tonight - espota can print a full progress bar and still not deploy
  // (wrong host port, wedged node). Compare this against the compile time and the
  // question is answered in one line instead of by inference.
  Serial.printf("[BOOT] build=%s %s\n", __DATE__, __TIME__);

  prefs.begin("quake", false);
  cfgSsid = prefs.getString("ssid", WIFI_SSID);
  cfgPass = prefs.getString("pass", WIFI_PASSWORD);
  cfgNode = prefs.getString("node", "unset");
  cfgHost = prefs.getString("host", "");
  cfgPort = prefs.getUShort("port", 8000);
  cfgAutostream = prefs.getBool("autostream", false);
  serialData = prefs.getBool("serialdata", false);
  prefs.end();
  Serial.printf("[BOOT] node=\"%s\" server=%s:%u serial_data=%s\n",
                cfgNode.c_str(), cfgHost.c_str(), cfgPort, serialData ? "on" : "off");

  // ⚠ network first - see the safety note at the top of this file
  if (connectWifi()) { startOta(); syncTime(); }

  sensorOk = initSensor();
  ui.begin();                       // after Wire.begin(), needs the bus to probe
  if (sensorOk) { ui.show("CALIBRATING...", "hold still"); calibrate(); }
  if (wifiUp && cfgHost.length()) startWs();

  if (!sensorOk)      ui.error("no sensor");
  else if (!wifiUp)   ui.show("READY", "no wifi");
  else                ui.idle(false);

  if (cfgAutostream && sensorOk) {
    // ⚠ Wait for the socket BEFORE streaming. Starting first deadlocks: the
    // no-reconnect-while-streaming guard in loop() would then never let the
    // pending connection complete, and the node would stream into the void
    // forever while looking perfectly healthy. Observed exactly that.
    // Blocking here is fine - nothing is being measured yet.
    if (wifiUp && cfgHost.length()) {
      Serial.print("[BOOT] waiting for backend before autostreaming");
      uint32_t t0 = millis();
      while (!wsUp && millis() - t0 < 12000) { ws.loop(); delay(50); Serial.print("."); }
      Serial.println();
      if (!wsUp) Serial.println("[BOOT] backend not reachable - streaming anyway, will retry when idle");
    }
    streaming = true; batchLen = 0; resetSchedule = true;
    Serial.println("[BOOT] autostream ON - streaming immediately");
    ui.show("STREAMING", cfgNode.c_str());
  }

  Serial.println("[BOOT] ready - 'stream on' to start, 'help' for commands");
}

void loop() {
  static uint32_t next = micros();
  static String cmdBuf;

  // ⚠ WiFi can drop, and nothing above notices. `wifiUp` used to be set once at
  // boot and never revisited, so a dropped link left the node trying to use a dead
  // connection forever - unrecoverable without a power cycle. Observed as ~8
  // minutes of total silence during a soak while the node still answered pings.
  // On a phone hotspot at a venue this is close to certain to happen.
  {
    static uint32_t lastWifiCheck = 0;
    if (millis() - lastWifiCheck > 5000) {
      lastWifiCheck = millis();
      bool up = (WiFi.status() == WL_CONNECTED);
      if (!up && wifiUp) {
        wifiUp = false; wsUp = false;
        Serial.println("[WIFI] connection LOST - reconnecting");
        ui.show("WIFI LOST", "retrying");
        WiFi.reconnect();
      } else if (up && !wifiUp) {
        wifiUp = true;
        Serial.printf("[WIFI] reconnected ip=%s rssi=%d\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
        ArduinoOTA.begin();                              // re-arm after the drop
        if (cfgHost.length()) startWs();
        ui.show("WIFI OK", cfgNode.c_str());
      }
    }
  }

  if (wifiUp) {
    ArduinoOTA.handle();

    // ⚠ ws.loop() BLOCKS for ~5 s per attempt when the server is unreachable -
    // that is WiFiClient's TCP connect timeout, and WebSocketsClient calls it
    // synchronously. Measured: "[RESYNC] 4998547 us behind; 999 samples dropped",
    // repeating, the moment the backend went away.
    //
    // So while a measurement is running, only service an ALREADY-OPEN socket;
    // never let it attempt a reconnect. If the socket is down mid-measurement the
    // samples have nowhere to go regardless, and stalling the 200 Hz loop for five
    // seconds turns "we lost the connection" into "we silently lost the data too".
    // Reconnection resumes the moment streaming stops.
    // Reconnect freely. The earlier versions of this were both wrong, and the
    // reasoning behind them was wrong too:
    //
    //   v1: never reconnect while streaming, to "protect sampling" from the ~5 s
    //       blocking TCP connect. But if the socket is down the samples are being
    //       discarded anyway - the stall costs nothing that was not already lost.
    //       A drop became permanent.
    //   v2: one ws.loop() every 30 s. Worse: a single call opens the TCP connection
    //       but never pumps the handshake to completion, so the server saw a
    //       connection appear, got nothing, timed it out, every ~65 s, forever,
    //       while the node reported healthy. Found by a soak test where the received
    //       batch count froze while connect/disconnect events kept accumulating.
    //
    // The one case where deferring IS justified is serial-fallback mode, because
    // then the samples genuinely do have somewhere to go and a stall loses them.
    if (wsUp || !streaming || !serialData) {
      ws.loop();
      wsDownSince = 0;
    } else {
      if (!wsDownSince) wsDownSince = millis();
      static uint32_t warnedAt = 0;
      if (millis() - warnedAt > 10000) {
        warnedAt = millis();
        Serial.println("[WS] down; deferring reconnect while serial fallback carries the data");
      }
      // Never permanent: after 30 s the serial path is worth less than a working
      // socket, so take the stall.
      if (millis() - wsDownSince > 30000) { wsDownSince = 0; ws.loop(); }
    }
  }

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') { if (cmdBuf.length()) { handleCommand(cmdBuf); cmdBuf = ""; } }
    else if (cmdBuf.length() < 160) cmdBuf += c;
  }

  // UI is ticked every pass, including while streaming, because it must stay
  // responsive to the button and it never blocks.
  // Tell the backend the instant the button goes down, so it can open a session
  // and buffer the countdown as the quiet baseline. See sendButtonPress().
  if (ui.takePress()) sendButtonPress();

  bool wasStreaming = streaming;
  if (ui.tick(streaming)) {
    streaming = true; batchLen = 0; resetSchedule = true;
    sessionEndsAt = millis() + Ui::RECORD_MS;   // PROTOCOL.md §4 fixed 12 s window
    // ⚠ Only take the stream DOWN at the end of the window if the press is what
    // brought it up. On an untethered autostreaming node the stream was already
    // running, and stopping it here left the node permanently silent: watchdog B
    // only fires while `streaming` is true, so nothing restarted it and only a
    // reboot or a typed `stream on` recovered it - with no laptop attached.
    // A judge pressing the button would have killed the node it was demonstrating.
    sessionOwnsStream = !wasStreaming;
  }
  if (sessionEndsAt && millis() > sessionEndsAt) {
    sessionEndsAt = 0;
    if (sessionOwnsStream) {
      streaming = false;
      Serial.println("[SESSION] 12 s window complete; stream off");
    } else {
      Serial.println("[SESSION] 12 s window complete; continuing to stream (autostream)");
    }
    sessionOwnsStream = false;
  }

  // ---- health telemetry + watchdog ---------------------------------------
  // Two soaks died the same way: clean for 12-25 minutes, then a burst of gaps,
  // then total silence while WiFi stayed up. Cause not yet identified - heap
  // exhaustion or a wedged WebSocket client are the leading candidates - so log
  // the heap to find out, AND guarantee recovery regardless of cause.
  //
  // A demo that self-heals in 25 s beats a correct diagnosis we do not have yet.
  // Expo runs 75 minutes; a node that silently dies at minute 12 loses the round.
  {
    static uint32_t lastHealth = 0;
    if (streaming && millis() - lastHealth > 30000) {
      lastHealth = millis();
      Serial.printf("[HEALTH] heap=%lu min_heap=%lu batches=%lu ws=%s rssi=%d up=%lus\n",
                    (unsigned long)ESP.getFreeHeap(),
                    (unsigned long)ESP.getMinFreeHeap(),
                    (unsigned long)sentBatches,
                    wsUp ? "up" : "DOWN", WiFi.RSSI(),
                    (unsigned long)(millis() / 1000));
    }

    // Watchdog A: streaming but no socket for 2 minutes.
    static uint32_t wedgedSince = 0;
    if (streaming && cfgAutostream && !wsUp && cfgHost.length()) {
      if (!wedgedSince) wedgedSince = millis();
      if (millis() - wedgedSince > 120000) {
        Serial.println("[WATCHDOG] no socket for 120 s while streaming - restarting");
        ui.show("RECOVERING", "restarting");
        Serial.flush(); delay(100); ESP.restart();
      }
    } else {
      wedgedSince = 0;
    }

    // Watchdog B: THROUGHPUT. This is the one that matters, and watchdog A would
    // never have fired for it.
    //
    // Traced failure: the socket stayed UP the whole time while the batch counter
    // collapsed from 10/s to 0.05/s. The [HEALTH] line itself, scheduled every
    // 30 s, started arriving every 161 s - the whole loop had slowed ~5x. Heap was
    // flat (~195 kB), so not a leak.
    //
    // ROOT CAUSE NOT ESTABLISHED. The obvious explanation - ws.sendTXT() blocking
    // on a full send buffer behind a slow reader - does NOT fit: the receiving
    // process had used only ~3 s of CPU across the whole run, so it was not slow.
    // A half-open socket (peer gone, TCP not yet timed out) would produce the same
    // symptoms and is the better remaining candidate, but that is a hypothesis.
    //
    // Hence a detector keyed on the SYMPTOM rather than the cause. In this state
    // the node looks perfectly healthy - wifi up, socket up, streaming on - which
    // is exactly why throughput has to be checked directly.
    static uint32_t rateWindow = 0, batchesAtWindow = 0;
    if (streaming && wsUp) {
      if (!rateWindow) { rateWindow = millis(); batchesAtWindow = sentBatches; }
      if (millis() - rateWindow > 60000) {
        uint32_t made = sentBatches - batchesAtWindow;
        // Healthy is ~600 batches/minute per channel. Under 60 means the loop is
        // starved, not merely slow.
        if (made < 60) {
          Serial.printf("[WATCHDOG] throughput collapsed: %lu batches in 60 s "
                        "(expect ~600) while socket reports up - restarting\n",
                        (unsigned long)made);
          ui.show("RECOVERING", "stalled");
          Serial.flush(); delay(100); ESP.restart();
        }
        rateWindow = millis(); batchesAtWindow = sentBatches;
      }
    } else {
      rateWindow = 0;
    }
  }

  if (!streaming || !sensorOk) { delay(2); return; }

  if (resetSchedule) { next = micros(); resetSchedule = false; }

  next += SAMPLE_US;

  // Deadline resync. After anything blocking (reconnect, OTA), the loop would
  // otherwise sprint at ~1000 Hz to catch up, emitting samples spaced 1 ms apart
  // whose timestamps claim 5 ms. The backend assumes uniform spacing and would
  // analyse that as real signal. A visible gap beats fabricated density.
  int32_t behind = (int32_t)(micros() - next);
  if (behind > (int32_t)(4 * SAMPLE_US)) {
    next = micros() + SAMPLE_US;
    droppedTotal += behind / SAMPLE_US;
    // Rate-limited: printing on every resync is self-defeating, since the print
    // itself costs time and causes the next one.
    static uint32_t lastReport = 0;
    if (millis() - lastReport > 2000) {
      lastReport = millis();
      Serial.printf("[RESYNC] %ld us behind; %lu samples dropped total\n",
                    (long)behind, (unsigned long)droppedTotal);
    }
  }
  while ((int32_t)(micros() - next) < 0) { /* spin */ }

  // Both sensors are read back to back inside one tick and share a single
  // timestamp. They are physically ~200 us apart, which is negligible at 0.5-15 Hz
  // and is exactly why PROD_DOC §12.4 calls this configuration perfectly matched:
  // no NTP, no clock drift, no resampling needed.
  sensors_event_t a, g, t;
  uint64_t ts = nowMs();
  for (int s = 0; s < sensorCount; s++) {
    mpu[s].getEvent(&a, &g, &t);
    if (fabs(a.acceleration.x) > CLIP_MS2 || fabs(a.acceleration.y) > CLIP_MS2
        || fabs(a.acceleration.z) > CLIP_MS2) clips++;
    batch[s][batchLen] = { ts, a.acceleration.x, a.acceleration.y, a.acceleration.z };
  }
  batchLen++;
  if (batchLen >= BATCH_N) { emitBatch(); batchLen = 0; }
}
