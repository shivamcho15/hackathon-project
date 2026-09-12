// ui.h — display, button, status LED and buzzer for the sensor node.
//
// Wiring is specified in firmware/WIRING.md. Pin map repeated at the bottom.
//
// ⚠ EVERYTHING HERE IS OPTIONAL AND SELF-DETECTING. This was written before any of
// it was wired, against firmware that already works, so the rule is: if a part is
// missing, miswired, or dead, the node still streams exactly as before. No UI
// failure may ever take down the measurement. Status falls back to Serial.
//
// ⚠ NOTHING HERE BLOCKS. The measurement loop is paced at 200 Hz with a ~5 ms
// budget per sample; a delay(1000) for a countdown beat would stall sampling and
// starve OTA. The countdown is therefore a state machine ticked from loop().

#pragma once

#include <Wire.h>
#include <LiquidCrystal.h>
#include <LiquidCrystal_I2C.h>

// ---- pins (WIRING.md) -----------------------------------------------------
#define PIN_BTN     32
#define PIN_BUZZ    33
#define PIN_LED_R   25
#define PIN_LED_G   26
#define PIN_LED_B   27
// Parallel LCD: RS, E, D4, D5, D6, D7
#define LCD_RS 13
#define LCD_EN 14
#define LCD_D4 16
#define LCD_D5 17
#define LCD_D6 18
#define LCD_D7 19

// The ELEGOO kit ships either variant depending on the box, and Saahil could not
// tell which without opening it. Rather than guess, probe the two addresses every
// I2C backpack uses; if neither answers, assume the parallel version.
static const uint8_t LCD_I2C_ADDRS[] = {0x27, 0x3F};

enum UiState { UI_IDLE, UI_COUNT, UI_STOMP, UI_RECORDING, UI_RESULT };

struct Ui {
  bool lcdI2c = false, lcdParallel = false;
  LiquidCrystal_I2C *lcdI = nullptr;
  LiquidCrystal     *lcdP = nullptr;

  UiState  state = UI_IDLE;
  uint32_t stateAt = 0;
  int      countdown = 0;
  bool     lastBtn = true;      // pull-up: released reads HIGH
  uint32_t lastBtnChange = 0;
  bool     present = false;     // any UI hardware at all

  // Set on the tick the button goes down, cleared by takePress(). This is a
  // SEPARATE signal from tick()'s return value, which fires 3 s later when the
  // countdown ends. The backend has to be told at PRESS time, because the
  // countdown window is itself the guaranteed-quiet baseline the pipeline needs
  // (PROTOCOL.md step 6, PIPELINE.md §5) - announcing it at the end of the
  // countdown would throw that baseline away.
  bool     pressed = false;
  bool takePress() { bool p = pressed; pressed = false; return p; }

  // Countdown and recording lengths, exported so the node can tell the backend
  // the same numbers it is about to act on rather than both sides hardcoding
  // them independently.
  static const uint16_t COUNTDOWN_MS = 3000;
  static const uint16_t RECORD_MS    = 12000;

  // ---- detection ----------------------------------------------------------
  // Call AFTER Wire.begin(). Safe to call with nothing connected.
  void begin() {
    pinMode(PIN_BTN, INPUT_PULLUP);
    pinMode(PIN_BUZZ, OUTPUT);   digitalWrite(PIN_BUZZ, LOW);
    pinMode(PIN_LED_R, OUTPUT);  pinMode(PIN_LED_G, OUTPUT);  pinMode(PIN_LED_B, OUTPUT);
    led(0, 0, 0);

    for (uint8_t addr : LCD_I2C_ADDRS) {
      Wire.beginTransmission(addr);
      if (Wire.endTransmission() == 0) {
        lcdI = new LiquidCrystal_I2C(addr, 16, 2);
        lcdI->init();
        lcdI->backlight();
        lcdI2c = present = true;
        Serial.printf("[UI] I2C LCD found at 0x%02X\n", addr);
        break;
      }
    }

    if (!lcdI2c) {
      // A parallel LCD cannot be probed - it has no way to answer. So this is an
      // assumption, not a detection, and it is harmless: driving those six pins
      // with nothing attached does nothing. If the display stays blank, suspect
      // the contrast pot first (WIRING.md §6).
      lcdP = new LiquidCrystal(LCD_RS, LCD_EN, LCD_D4, LCD_D5, LCD_D6, LCD_D7);
      lcdP->begin(16, 2);
      lcdParallel = true;
      Serial.println("[UI] no I2C LCD; driving parallel pins (blank screen => check contrast pot)");
    }

    show("earthquake", "assess  ready");
    Serial.println("[UI] button on GPIO32, LED 25/26/27, buzzer 33");
  }

  // ---- primitives ---------------------------------------------------------
  void show(const char *l1, const char *l2 = "") {
    if (lcdI2c && lcdI) {
      lcdI->clear(); lcdI->setCursor(0, 0); lcdI->print(l1);
      lcdI->setCursor(0, 1); lcdI->print(l2);
    } else if (lcdParallel && lcdP) {
      lcdP->clear(); lcdP->setCursor(0, 0); lcdP->print(l1);
      lcdP->setCursor(0, 1); lcdP->print(l2);
    }
    Serial.printf("[UI] %s | %s\n", l1, l2);   // always, so it works with no LCD
  }

  void led(bool r, bool g, bool b) {
    digitalWrite(PIN_LED_R, r); digitalWrite(PIN_LED_G, g); digitalWrite(PIN_LED_B, b);
  }

  // Non-blocking: latch the buzzer on and let tick() turn it off.
  uint32_t buzzUntil = 0;
  void beep(uint16_t ms) { digitalWrite(PIN_BUZZ, HIGH); buzzUntil = millis() + ms; }

  // ---- state machine ------------------------------------------------------
  void startSession() {
    state = UI_COUNT; countdown = 3; stateAt = millis();
    pressed = true;
    show("CALIBRATING...", "hold still");
    led(0, 0, 1);
    beep(80);
  }

  // Returns true on the tick where recording should begin.
  bool tick(bool streamingNow) {
    if (buzzUntil && millis() > buzzUntil) { digitalWrite(PIN_BUZZ, LOW); buzzUntil = 0; }

    // Debounced falling edge on the button. 40 ms is comfortably past contact
    // bounce without eating a deliberate press.
    bool b = digitalRead(PIN_BTN);
    if (b != lastBtn && millis() - lastBtnChange > 40) {
      lastBtnChange = millis();
      if (b == LOW && state == UI_IDLE) { lastBtn = b; startSession(); return false; }
      lastBtn = b;
    }

    uint32_t dt = millis() - stateAt;
    switch (state) {
      case UI_COUNT: {
        // PROTOCOL.md §4: a 3-2-1 countdown, which is both a mechanical settle
        // window and a demo beat.
        int remaining = 3 - (int)(dt / 1000);
        if (remaining != countdown && remaining > 0) {
          countdown = remaining;
          char l2[17]; snprintf(l2, sizeof(l2), "     %d", remaining);
          show("GET READY", l2);
          beep(80);
        }
        if (dt >= 3000) {
          state = UI_STOMP; stateAt = millis();
          show("STOMP NOW!", "");
          led(1, 0, 0);
          beep(400);
          return true;              // caller starts recording
        }
        break;
      }
      case UI_STOMP:
        if (dt >= 1200) { state = UI_RECORDING; stateAt = millis(); show("RECORDING", "hold still"); led(0, 0, 1); }
        break;
      case UI_RECORDING:
        if (dt >= 11000) { state = UI_RESULT; stateAt = millis(); show("ANALYSING", "..."); led(0, 1, 1); }
        break;
      case UI_RESULT:
        if (dt >= 20000) { state = UI_IDLE; idle(streamingNow); }
        break;
      case UI_IDLE:
      default: break;
    }
    return false;
  }

  void idle(bool streamingNow) {
    show("READY", streamingNow ? "streaming" : "press to measure");
    led(0, 1, 0);
  }

  // Called when the backend pushes a result back over the WebSocket. Display is
  // the whole point of the second sensor node being legible at the table - the
  // judge reads the number off the device, not off a laptop across the room.
  void result(float hz, const char *confidence) {
    char l1[17], l2[17];
    snprintf(l1, sizeof(l1), "%.2f Hz", hz);
    snprintf(l2, sizeof(l2), "T=%.2fs %s", hz > 0 ? 1.0f / hz : 0.0f, confidence);
    show(l1, l2);
    state = UI_RESULT; stateAt = millis();
    led(0, 1, 0);
    beep(120);
  }

  void error(const char *msg) { show("PROBLEM", msg); led(1, 0, 0); }
};
