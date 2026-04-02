"""
Smart Railway Automation System — Actuators
=============================================
Servo gate, LED traffic lights, and buzzer control.
Desktop-safe: prints actions to console when hardware is absent.
"""

import time
import logging

from config import (
    SERVO_PIN, GATE_OPEN_ANGLE, GATE_CLOSE_ANGLE,
    LED_RED_PIN, LED_YELLOW_PIN, LED_GREEN_PIN,
    BUZZER_PIN, LightState, GateState,
)

logger = logging.getLogger(__name__)

# ─── Hardware abstraction ────────────────────────────────────────────────────
try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    ON_PI = True
except (ImportError, RuntimeError):
    ON_PI = False
    logger.warning("RPi.GPIO not available — actuators in SIMULATION mode.")


def _angle_to_duty(angle: float) -> float:
    """Convert 0-180° angle to servo duty-cycle (2-12 %)."""
    return 2.0 + (angle / 180.0) * 10.0


# ═══════════════════════════════════════════════════════════════════════════════
#  Servo Gate
# ═══════════════════════════════════════════════════════════════════════════════

class ServoGate:
    """Controls the railway crossing gate via a standard servo motor."""

    def __init__(self, pin: int = SERVO_PIN):
        self.pin = pin
        self.state = GateState.OPEN
        self._pwm = None

        if ON_PI:
            GPIO.setup(self.pin, GPIO.OUT)
            self._pwm = GPIO.PWM(self.pin, 50)  # 50 Hz
            self._pwm.start(0)
            logger.info(f"Servo gate initialised on GPIO{self.pin}")
        else:
            logger.info("Servo gate in simulation mode.")

    def _set_angle(self, angle: float):
        if ON_PI and self._pwm:
            duty = _angle_to_duty(angle)
            self._pwm.ChangeDutyCycle(duty)
            time.sleep(0.15)                # wait for servo to reach position
            self._pwm.ChangeDutyCycle(0)    # stop jitter
        else:
            logger.info(f"[SIM] Servo → {angle}°")

    def open_gate(self):
        """Raise the gate (train departed)."""
        logger.info("Opening railway gate ...")
        self._set_angle(GATE_OPEN_ANGLE)
        self.state = GateState.OPEN

    def close_gate(self):
        """Lower the gate (train approaching)."""
        logger.info("Closing railway gate ...")
        self._set_angle(GATE_CLOSE_ANGLE)
        self.state = GateState.CLOSED

    def cleanup(self):
        if ON_PI and self._pwm:
            self._pwm.stop()
            GPIO.cleanup(self.pin)


# ═══════════════════════════════════════════════════════════════════════════════
#  Traffic Light (Red / Yellow / Green LEDs)
# ═══════════════════════════════════════════════════════════════════════════════

class TrafficLight:
    """Manages a 3-LED traffic signal."""

    _PIN_MAP = {
        LightState.RED:    LED_RED_PIN,
        LightState.YELLOW: LED_YELLOW_PIN,
        LightState.GREEN:  LED_GREEN_PIN,
    }

    def __init__(self):
        self.state = LightState.GREEN
        if ON_PI:
            for pin in self._PIN_MAP.values():
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)
            logger.info("Traffic light initialised.")
        else:
            logger.info("Traffic light in simulation mode.")

    def set_state(self, state: str):
        """
        Set the traffic light to the given state.

        Parameters
        ----------
        state : str
            One of LightState.RED, LightState.YELLOW, LightState.GREEN
        """
        if state not in self._PIN_MAP:
            logger.error(f"Invalid light state: {state}")
            return

        self.state = state

        if ON_PI:
            # Turn all off, then light the correct one
            for colour, pin in self._PIN_MAP.items():
                GPIO.output(pin, GPIO.HIGH if colour == state else GPIO.LOW)
        else:
            logger.info(f"[SIM] Traffic light → {state.upper()}")

    def all_off(self):
        """Turn off all LEDs."""
        if ON_PI:
            for pin in self._PIN_MAP.values():
                GPIO.output(pin, GPIO.LOW)
        self.state = None

    def cleanup(self):
        if ON_PI:
            for pin in self._PIN_MAP.values():
                GPIO.cleanup(pin)


# ═══════════════════════════════════════════════════════════════════════════════
#  Buzzer
# ═══════════════════════════════════════════════════════════════════════════════

class Buzzer:
    """Simple on/off buzzer for audible alerts."""

    def __init__(self, pin: int = BUZZER_PIN):
        self.pin = pin
        self.active = False

        if ON_PI:
            GPIO.setup(self.pin, GPIO.OUT)
            GPIO.output(self.pin, GPIO.LOW)
            logger.info(f"Buzzer initialised on GPIO{self.pin}")
        else:
            logger.info("Buzzer in simulation mode.")

    def on(self):
        self.active = True
        if ON_PI:
            GPIO.output(self.pin, GPIO.HIGH)
        else:
            logger.info("[SIM] Buzzer ON 🔔")

    def off(self):
        self.active = False
        if ON_PI:
            GPIO.output(self.pin, GPIO.LOW)
        else:
            logger.info("[SIM] Buzzer OFF")

    def beep(self, duration: float = 0.3, times: int = 3, gap: float = 0.2):
        """Short beep pattern."""
        for _ in range(times):
            self.on()
            time.sleep(duration)
            self.off()
            time.sleep(gap)

    def cleanup(self):
        self.off()
        if ON_PI:
            GPIO.cleanup(self.pin)
