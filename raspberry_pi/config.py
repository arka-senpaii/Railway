"""
Smart Railway Automation System — Configuration
=================================================
Central configuration for GPIO pins, servo angles, timing,
and Firebase credentials path.
"""

# ─── GPIO Pin Assignments (BCM numbering) ───────────────────────────────────

# KY-032 IR Obstacle Avoidance Sensors
IR_SENSOR_IN_PIN = 17       # GPIO17 — digital OUT from IN KY-032
IR_SENSOR_OUT_PIN = 16      # GPIO16 — digital OUT from OUT KY-032

# RFID MFRC522 (SPI interface — fixed pins on RPi)
# SDA  → GPIO8  (CE0)
# SCK  → GPIO11
# MOSI → GPIO10
# MISO → GPIO9
# RST  → GPIO25
RFID_RST_PIN = 25

# Servo Motor (gate control)
SERVO_PIN = 18               # GPIO18 — PWM-capable pin

# LED Traffic Lights
LED_RED_PIN = 27              # GPIO27
LED_YELLOW_PIN = 22           # GPIO22
LED_GREEN_PIN = 23            # GPIO23

# Buzzer (optional)
BUZZER_PIN = 24               # GPIO24

# ─── Servo Angles ────────────────────────────────────────────────────────────

GATE_OPEN_ANGLE = 0           # degrees — gate fully raised
GATE_CLOSE_ANGLE = 90         # degrees — gate fully lowered

# ─── Timing Thresholds (seconds) ─────────────────────────────────────────────

IR_DEBOUNCE_TIME = 0.3        # debounce for IR sensor reads
MAX_PASSING_TIMEOUT = 120.0   # fallback seconds clear if OUT sensor fails
YELLOW_WARNING_DURATION = 0.05 # yellow light before switching to red
FIREBASE_SYNC_INTERVAL = 1.0  # how often to push status updates
MANUAL_POLL_INTERVAL = 0.5    # how often to check manual override flag

# ─── RPi 3B+ Optimisation (1 GB RAM / 32 GB SD) ─────────────────────────────

MAX_TTS_CACHE_FILES = 50      # LRU eviction after this many cached TTS mp3s
PRE_GEN_LOOKAHEAD = 3         # only pre-generate the next N upcoming trains
TTS_MAX_WORKERS = 2           # parallel gTTS threads (keep low for 1 GB RAM)
LOG_LEVEL = "WARNING"         # production log level (use INFO / DEBUG on desktop)
MAIN_LOOP_SLEEP = 0.15        # main loop delay (seconds) — saves CPU cycles
OFFLINE_QUEUE_MAX = 100       # max queued Firebase writes when offline

# ─── Firebase ────────────────────────────────────────────────────────────────

FIREBASE_CREDENTIALS_PATH = "railway-c8909-firebase-adminsdk-fbsvc-37c2f1e82f.json"   # path to service-account key
FIREBASE_DATABASE_URL = "https://railway-c8909-default-rtdb.firebaseio.com"  # Firebase RTDB URL

# ─── RFID → Train ID Map ─────────────────────────────────────────────────────
# Map RFID card UIDs (as hex strings) to logical train IDs.
# Add your own card UIDs here after scanning them.

RFID_TRAIN_MAP = {
    "A3B2C1D0": "22812",   # Rajdhani Express (via Adra)
    "1A2B3C4D": "12282",   # Duronto Express
    "FF00FF00": "12883",   # Rupasi Bangla Express
    "B4C3D2E1": "12828",   # Purulia - Howrah SF Exp
    "D5E4F3A2": "18011",   # Howrah - Chakradharpur Exp
    "C6D5E4F3": "12816",   # Nandan Kanan Express
    "E7F6A5B4": "12885",   # Aranyak Express
    "F8A7B6C5": "13301",   # Subarnarekha Express
}

# ─── State Constants ─────────────────────────────────────────────────────────

class TrainState:
    IDLE = "idle"
    APPROACHING = "approaching"
    PASSING = "passing"
    DEPARTED = "departed"

class GateState:
    OPEN = "open"
    CLOSED = "closed"

class LightState:
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
