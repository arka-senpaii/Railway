"""
Smart Railway Automation System — Sensors
==========================================
IR obstacle-avoidance sensor (KY-032) and RFID reader (MFRC522).
Includes desktop-safe stubs so the code can be imported without hardware.
"""

import time
import logging

from config import IR_DEBOUNCE_TIME, RFID_RST_PIN, RFID_TRAIN_MAP

logger = logging.getLogger(__name__)

# ─── Hardware abstraction ────────────────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    ON_PI = True
except (ImportError, RuntimeError):
    ON_PI = False
    logger.warning("RPi.GPIO not available — running in SIMULATION mode.")

try:
    from mfrc522 import SimpleMFRC522
    RFID_AVAILABLE = True
except ImportError:
    RFID_AVAILABLE = False
    logger.warning("MFRC522 library not available — RFID disabled.")


# ═══════════════════════════════════════════════════════════════════════════════
#  IR Sensor (KY-032)
# ═══════════════════════════════════════════════════════════════════════════════

class IRSensor:
    """Wrapper for the KY-032 infrared obstacle-avoidance sensor."""

    def __init__(self, pin: int):
        self.pin = pin
        self._last_read_time = 0.0
        self._last_value = False

        if ON_PI:
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            logger.info(f"IR sensor initialised on GPIO{self.pin}")
        else:
            logger.info("IR sensor running in simulation mode.")

    def is_obstacle_detected(self) -> bool:
        """
        Return True when an obstacle (train) is detected.
        KY-032 outputs LOW when an obstacle is present.
        Includes software debounce.
        """
        now = time.time()
        if now - self._last_read_time < IR_DEBOUNCE_TIME:
            return self._last_value

        if ON_PI:
            raw = GPIO.input(self.pin)
            detected = raw == GPIO.LOW  # KY-032 active-low
        else:
            detected = False  # simulation: no obstacle

        self._last_value = detected
        self._last_read_time = now
        return detected

    def cleanup(self):
        if ON_PI:
            GPIO.cleanup(self.pin)


# ═══════════════════════════════════════════════════════════════════════════════
#  RFID Reader (MFRC522)
# ═══════════════════════════════════════════════════════════════════════════════

class RFIDReader:
    """Wrapper for the MFRC522 RFID module."""

    def __init__(self):
        if RFID_AVAILABLE:
            self.reader = SimpleMFRC522()
            logger.info("RFID reader initialised.")
        else:
            self.reader = None
            logger.info("RFID reader running in simulation mode.")

    def read_card(self):
        """
        Attempt to read an RFID card.

        Returns
        -------
        tuple (uid_hex: str | None, train_id: str | None)
            uid_hex  — raw UID as uppercase hex string, or None
            train_id — mapped train ID from config, or None
        """
        if not RFID_AVAILABLE or self.reader is None:
            return None, None

        try:
            uid, _ = self.reader.read_no_block()
            if uid is None:
                return None, None

            uid_hex = format(uid, "08X")
            train_id = RFID_TRAIN_MAP.get(uid_hex)

            if train_id:
                logger.info(f"RFID card scanned → UID: {uid_hex}, Train: {train_id}")
            else:
                logger.warning(f"Unknown RFID card UID: {uid_hex}")

            return uid_hex, train_id

        except Exception as exc:
            logger.error(f"RFID read error: {exc}")
            return None, None

    def cleanup(self):
        """Release SPI resources."""
        if RFID_AVAILABLE:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup()
            except Exception:
                pass
