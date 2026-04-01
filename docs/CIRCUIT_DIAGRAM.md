# Circuit Diagram — Smart Railway Automation System

## Components Required

| # | Component | Qty | Purpose |
|---|-----------|-----|---------|
| 1 | Raspberry Pi 3B+ | 1 | Main controller |
| 2 | KY-032 IR Sensors | 2 | Train detection (In & Out) |
| 3 | MFRC522 RFID Module | 1 | Train identification |
| 4 | SG90 Servo Motor | 1 | Railway gate control |
| 5 | Red LED (5mm) | 1 | Traffic light — stop |
| 6 | Yellow LED (5mm) | 1 | Traffic light — warning |
| 7 | Green LED (5mm) | 1 | Traffic light — go |
| 8 | Active Buzzer | 1 | Audio alert |
| 9 | 220Ω Resistors | 3 | LED current limiting |
| 10 | Breadboard + Jumper Wires | — | Connections |
| 11 | 5V 2.5A Power Supply | 1 | Raspberry Pi power |
| 12 | RFID Cards/Tags | 2-3 | Train identification tags |

---

## GPIO Pin Mapping (BCM Numbering)

```
┌─────────────────────────────────────────────────────────┐
│                   RASPBERRY PI 3B+                      │
│                    (GPIO Header)                        │
├─────────────────┬───────────────────────────────────────┤
│  Pin (BCM)      │  Connected To                        │
├─────────────────┼───────────────────────────────────────┤
│  GPIO 17        │  KY-032 IR Sensor (IN) — OUT pin      │
│  GPIO 16        │  KY-032 IR Sensor (OUT) — OUT pin     │
│  GPIO 18 (PWM)  │  Servo Motor — Signal (orange wire)   │
│  GPIO 22        │  Yellow LED (via 220Ω resistor)       │
│  GPIO 23        │  Green LED (via 220Ω resistor)        │
│  GPIO 24        │  Buzzer — Signal (+) pin              │
│  GPIO 25        │  MFRC522 RFID — RST                   │
│  GPIO 27        │  Red LED (via 220Ω resistor)          │
│                 │                                       │
│  ── SPI Pins (fixed) ──                                │
│  GPIO 8  (CE0)  │  MFRC522 RFID — SDA                   │
│  GPIO 9  (MISO) │  MFRC522 RFID — MISO                  │
│  GPIO 10 (MOSI) │  MFRC522 RFID — MOSI                  │
│  GPIO 11 (SCLK) │  MFRC522 RFID — SCK                   │
│                 │                                       │
│  3.3V           │  MFRC522 VCC, 2x KY-032 VCC            │
│  5V             │  Servo VCC (red wire)                  │
│  GND            │  Common ground for all components      │
└─────────────────┴───────────────────────────────────────┘
```

---

## Wiring Details

### 1. KY-032 IR Obstacle Sensors (x2)

```
KY-032 (In & Out)   Raspberry Pi
─────────────────   ────────────
VCC (Both)  ─────── 3.3V
GND (Both)  ─────── GND
OUT (Sensor IN) ─── GPIO 17
OUT (Sensor OUT)─── GPIO 16
```

> **Note**: The KY-032 has a potentiometer to adjust detection distance (3–40 cm). Adjust it for your track width.

### 2. MFRC522 RFID Module

```
MFRC522         Raspberry Pi
───────         ────────────
SDA    ──────── GPIO 8  (CE0)
SCK    ──────── GPIO 11 (SCLK)
MOSI   ──────── GPIO 10 (MOSI)
MISO   ──────── GPIO 9  (MISO)
RST    ──────── GPIO 25
GND    ──────── GND
3.3V   ──────── 3.3V
```

> **⚠ Important**: The MFRC522 runs on **3.3V only**. Do NOT connect to 5V or it will be damaged.

### 3. Servo Motor (SG90)

```
Servo           Raspberry Pi
─────           ────────────
Signal (Orange) ── GPIO 18 (PWM)
VCC    (Red)    ── 5V
GND    (Brown)  ── GND
```

> **Tip**: For heavy-load servos, use an external 5V supply and share GND with the Pi.

### 4. LED Traffic Lights

```
LED             Raspberry Pi
───             ────────────
Red    Anode   ── 220Ω ── GPIO 27
Red    Cathode ── GND

Yellow Anode   ── 220Ω ── GPIO 22
Yellow Cathode ── GND

Green  Anode   ── 220Ω ── GPIO 23
Green  Cathode ── GND
```

### 5. Active Buzzer

```
Buzzer          Raspberry Pi
──────          ────────────
(+) Signal ──── GPIO 24
(-) GND    ──── GND
```

---

## Physical Layout Suggestion

```
                         ┌───────────┐
      RFID Tag on Train  │  🚆 TRAIN │ ← Direction of travel
                         └───────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────┐
  │                    TRACK                          │
  │  ┌─────────┐                    ┌──────────┐     │
  │  │2x KY-032│  ←── IR Sensors    │ MFRC522  │     │
  │  │(In/Out) │   mounted on       │ (RFID)   │     │
  │  └─────────┘   track side       └──────────┘     │
  └──────────────────────────────────────────────────┘
                              │
                     ┌────────┴────────┐
                     │   SERVO GATE    │  ← Barrier arm
                     └─────────────────┘
                              │
                     ┌────────┴────────┐
                     │  TRAFFIC LIGHT  │  🔴 🟡 🟢
                     └─────────────────┘
```

Place the IN IR sensor 30-50cm before the gate so the system has time to react. Place the OUT sensor after the gate.
Place the RFID reader at track level where the tag on the train will pass close to it.
