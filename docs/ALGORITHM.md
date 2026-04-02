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

### 1. Scheduled Train Announcements
```
ANNOUNCEMENT(train_id):
├── Lookup train_id natively without fetching via API (using adrajndet.csv)
│   └── Get: Train_No, Train_Name, Platform_No, Arrival_Time
├── Extract skeleton parts from project.mp3 directly in memory (to save SD I/O)
├── Generate TTS parts in parallel using ThreadPool (capped at 2 workers for RPi specs):
│   ├── Part-2:  gTTS(EN) → "Train_No  Train_Name"
│   ├── Part-4:  gTTS(EN) → Platform_No
│   ├── Part-6:  gTTS(BN) → "Train_No  Train_Name"
│   ├── Part-7:  gTTS(BN) → Platform_No
│   ├── Part-10: gTTS(HI) → "Train_No  Train_Name"
│   └── Part-12: gTTS(HI) → Platform_No
├── Merge Parts 1-13 in sequence instantly
├── Export as Announcement_{Train_No}.wav
└── Stream natively using hardware `ffplay` to aux output
```

### 2. Custom Station Master Announcements
```
CUSTOM_TEXT_ANNOUNCEMENT(text):
├── Intercept `/custom_announcement` node change from Firebase (sent by Station Master UI)
├── Read raw text string
├── Generate gTTS audio in Hindi and English in parallel
├── Append Warning chime (`late.mp3`)
├── Export as Custom_Announcement.wav and stream securely to aux
└── Delete locally generated .wav immediately to preserve storage
```

---

## Manual Override & Station Master Algorithm

```
MANUAL_OVERRIDE_AND_STATION_UI:
├── Event-Driven: Set up real-time listener on Firebase database
├── If /manual_mode enabled=true:
│   ├── Suspend automatic sensor triggers and gate loop logic
│   ├── Listen for commands on /gate_status
│   └── Translate UI button clicks ("Open", "Close", "Red", "Green") into SERVO & LED pins
├── If /timetable changes:
│   └── Station Master UI inherently sorts all trains by Day, highlights "NEXT" approaching train natively.
├── If /trigger_announcement triggers:
│   └── Immediately invoke ANNOUNCEMENT(train_id) across internal threading
└── If /custom_announcement triggers:
    └── Play bespoke typed message natively over `ffplay`
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
