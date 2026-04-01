# Algorithm — Smart Railway Automation System

## State Machine

The system operates as a 4-state machine:

```
  ┌──────────┐   IN IR detects   ┌──────────────┐
  │          │───────────────────▶│              │
  │   IDLE   │                   │  APPROACHING │
  │  (green) │                   │   (yellow)   │
  │          │◀──────────────────│              │
  └──────────┘  gate opened      └──────┬───────┘
       ▲                                │
       │                        after YELLOW_DURATION
       │                                │
  ┌────┴──────┐                  ┌──────▼───────┐
  │           │   clear timeout  │              │
  │  DEPARTED │◀─────────────────│   PASSING    │
  │           │                  │    (red)     │
  └───────────┘                  └──────────────┘
```

---

## Step-by-Step Algorithm

### 1. System Initialization
```
START
├── Initialize GPIO pins (BCM mode)
├── Set up IR sensors (GPIO17=IN, GPIO16=OUT, pull-up, active-low)
├── Set up RFID reader (SPI interface, GPIO25 RST)
├── Set up Servo (GPIO18, PWM 50Hz)
├── Set up LEDs (GPIO27=Red, GPIO22=Yellow, GPIO23=Green)
├── Set up Buzzer (GPIO24)
├── Connect to Firebase (load serviceAccountKey.json)
├── Load train timetable from adrajndet.csv
├── Set initial state → IDLE (green light, gate open)
├── Start manual-override polling thread
└── Enter main loop
```

### 2. Main Loop (runs continuously)
```
LOOP:
├── If manual_override enabled → skip auto logic, sleep 0.5s
├── Flush any queued offline Firebase writes
├── Execute state handler based on current state
└── Sleep 0.1s, repeat
```

### 3. IDLE State
```
IDLE:
├── Traffic light = GREEN
├── Gate = OPEN
├── Buzzer = OFF
├── POLL IN IR sensor
│   ├── If obstacle detected by IN sensor:
│   │   ├── Record detection timestamp
│   │   ├── Transition → APPROACHING
│   │   ├── Set traffic light → YELLOW
│   │   ├── Turn buzzer ON
│   │   └── Push status to Firebase
│   └── If no obstacle: stay in IDLE
```

### 4. APPROACHING State
```
APPROACHING:
├── If IN IR still detects → update last_detection_time
├── Attempt RFID read:
│   ├── If card read → lookup train in adrajndet.csv
│   ├── Get Train_No, Train_Name, Platform_No
│   ├── Compute delay (scheduled vs actual arrival)
│   ├── Generate 13-part audio announcement (EN + BN + HI)
│   ├── Play announcement
│   └── If delayed → also generate late announcement
├── Check if YELLOW_WARNING_DURATION has elapsed:
│   ├── If NO → stay in APPROACHING (yellow phase)
│   └── If YES:
│       ├── Set traffic light → RED
│       ├── Close gate (servo → 90°)
│       ├── Beep buzzer (3 times)
│       ├── Push gate=closed, light=red to Firebase
│       └── Transition → PASSING
```

### 5. PASSING State
```
PASSING:
├── Check if MAX_PASSING_TIMEOUT elapsed (failsafe):
│   ├── If YES → Reset to IDLE (DEPARTED)
├── POLL OUT IR sensor:
│   ├── If OUT sensor detects → Mark train as reached OUT
│   └── If OUT sensor NOT detecting:
│       ├── Check if train had previously reached OUT
│       └── If YES → Transition → DEPARTED
```

### 6. DEPARTED State
```
DEPARTED:
├── Open gate (servo → 0°)
├── Turn buzzer OFF
├── Clear current_train_id
├── Push train status = "departed" to Firebase
├── Transition → IDLE (green light, gate open)
```

---

## Announcement Generation Algorithm

```
ANNOUNCEMENT(train_id):
├── Lookup train_id in adrajndet.csv
│   └── Get: Train_No, Train_Name, Platform_No, Arrival_Time
├── Extract skeleton parts from project.mp3 (7 fixed segments)
├── Generate TTS parts:
│   ├── Part-2:  gTTS(EN) → "Train_No  Train_Name"
│   ├── Part-4:  gTTS(EN) → Platform_No
│   ├── Part-6:  gTTS(BN) → "Train_No  Train_Name"
│   ├── Part-7:  gTTS(BN) → Platform_No
│   ├── Part-10: gTTS(HI) → "Train_No  Train_Name"
│   └── Part-12: gTTS(HI) → Platform_No
├── Merge Parts 1-13 in sequence
└── Export as Announcement_{Train_No}.mp3
```

---

## Manual Override Algorithm

```
MANUAL_OVERRIDE:
├── Poll Firebase /manual_override every 1 second
├── If enabled=true:
│   ├── Skip automatic state machine
│   ├── Read gate command → open/close servo
│   ├── Read traffic_light command → set LED
│   └── Push status updates to Firebase
└── If enabled=false → resume automatic mode
```

---

## Error Handling

| Error | Detection | Recovery |
|-------|-----------|----------|
| IR sensor failure | No reads for extended period from IN/OUT sensors | Log warning, continue with RFID only |
| RFID read error | Exception in read_card() | Log error, continue without train ID |
| Internet loss | Firebase write exception | Queue writes locally, retry on reconnection |
| Servo stall | Timeout on angle set | Reset PWM, retry once |
| Power loss | N/A | System restarts in IDLE state (safe default) |
| gTTS failure | Network error | Log warning, skip audio announcement |
| CSV file missing | FileNotFoundError on load | Use Firebase schedule as fallback |
