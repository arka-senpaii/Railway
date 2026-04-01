"""
Smart Railway Automation System — Main Controller
====================================================
Orchestrates sensors, actuators, Firebase sync, RFID announcements,
and manual-override mode using a state-machine approach.

Usage (on Raspberry Pi):
    python main.py

Usage (simulation on desktop):
    python main.py --simulate
"""

import sys
import time
import signal
import logging
import threading
from datetime import datetime, timezone

from config import (
    TrainState, GateState, LightState,
    TRAIN_CLEAR_TIMEOUT, YELLOW_WARNING_DURATION,
    FIREBASE_SYNC_INTERVAL,
)
from sensors import IRSensor, RFIDReader
from actuators import ServoGate, TrafficLight, Buzzer
from firebase_client import FirebaseClient
from announcement import AnnouncementEngine, TrainScheduleDB
from manual_mode import ManualModeController

# ─── Logging setup ───────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("RailwaySystem")

# ═══════════════════════════════════════════════════════════════════════════════
#  Railway Automation Controller
# ═══════════════════════════════════════════════════════════════════════════════

class RailwayController:
    """
    Main state-machine controller.

    States
    ------
    IDLE        → green light, gate open, waiting for train
    APPROACHING → yellow→red light, gate closing, train detected by IR
    PASSING     → red light, gate closed, train is on the track
    DEPARTED    → transition back to IDLE after train clears
    """

    def __init__(self):
        logger.info("=" * 60)
        logger.info("  Smart Railway Automation System")
        logger.info("=" * 60)

        # ── Components ──
        self.ir_sensor = IRSensor()
        self.rfid_reader = RFIDReader()
        self.gate = ServoGate()
        self.light = TrafficLight()
        self.buzzer = Buzzer()
        self.firebase = FirebaseClient()
        self.schedule_db = TrainScheduleDB()
        self.announcer = AnnouncementEngine(self.firebase, self.schedule_db)
        self.manual_ctrl = ManualModeController(
            self.firebase, self.gate, self.light, self.buzzer, self.announcer
        )

        # ── State ──
        self.state = TrainState.IDLE
        self.current_train_id = None
        self._last_detection_time = 0.0
        self._running = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self):
        """Initialise everything and enter the main loop."""
        self._running = True
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

        # Set initial state
        self._set_idle_state()
        self.manual_ctrl.start()

        # Push today's timetable to Firebase so the dashboard can show it
        today_trains = self.schedule_db.get_todays_trains()
        if today_trains:
            self.firebase.push_timetable(today_trains)
            logger.info(f"Pushed {len(today_trains)} trains to Firebase timetable.")
        self.firebase.update_current_train(None)

        logger.info("System online. Entering main loop ...")

        try:
            self._main_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        """Clean up all hardware resources."""
        self._running = False
        logger.info("Shutting down ...")
        self.manual_ctrl.stop()
        self.gate.open_gate()          # safety: leave gate open
        self.light.all_off()
        self.buzzer.off()
        self.ir_sensor.cleanup()
        self.rfid_reader.cleanup()
        self.gate.cleanup()
        self.light.cleanup()
        self.buzzer.cleanup()
        self.firebase.update_current_gate_status("OPEN")
        logger.info("Shutdown complete.")

    def _shutdown_handler(self, signum, frame):
        logger.info(f"Signal {signum} received — shutting down.")
        self._running = False

    # ── Main Loop ────────────────────────────────────────────────────────────

    def _main_loop(self):
        while self._running:
            # If manual override is active, skip automatic logic
            if self.manual_ctrl.is_enabled:
                time.sleep(0.5)
                continue

            # Flush any queued Firebase writes
            self.firebase.flush_offline_queue()

            # State machine transitions
            if self.state == TrainState.IDLE:
                self._handle_idle()

            elif self.state == TrainState.APPROACHING:
                self._handle_approaching()

            elif self.state == TrainState.PASSING:
                self._handle_passing()

            elif self.state == TrainState.DEPARTED:
                self._handle_departed()

            time.sleep(0.1)  # small loop delay

    # ── State Handlers ───────────────────────────────────────────────────────

    def _handle_idle(self):
        """IDLE: Wait for the IR sensor to detect a train."""
        if self.ir_sensor.is_obstacle_detected():
            logger.info("🚆 Train detected by IR sensor!")
            self._last_detection_time = time.time()
            self._transition_to_approaching()

    def _handle_approaching(self):
        """APPROACHING: Warning phase — yellow light, then red + gate close."""
        # If IR still detects, train is moving to PASSING
        if self.ir_sensor.is_obstacle_detected():
            self._last_detection_time = time.time()

        # Try to read RFID for identification
        uid, train_id = self.rfid_reader.read_card()
        if train_id and self.current_train_id is None:
            self.current_train_id = train_id
            self.firebase.update_current_train(train_id)
            result = self.announcer.generate_and_play(train_id)
            logger.info(f"Announcement: {result['message']}")
            if result.get('delay_minutes', 0) > 0:
                self.announcer.generate_late_announcement(
                    result['train_data'], result['delay_minutes']
                )

        # After yellow warning, switch to red and close gate
        elapsed = time.time() - self._last_detection_time
        if elapsed < YELLOW_WARNING_DURATION:
            return  # still in yellow phase

        # Move to PASSING state
        self.state = TrainState.PASSING
        self.light.set_state(LightState.RED)
        self.gate.close_gate()
        self.buzzer.beep(times=3)

        self.firebase.update_current_gate_status("CLOSED")
        self.firebase.update_gate_status("CLOSED")
        logger.info("State → PASSING (red light, gate closed)")

    def _handle_passing(self):
        """PASSING: Train is on the track; wait for it to clear."""
        if self.ir_sensor.is_obstacle_detected():
            self._last_detection_time = time.time()
            return  # still passing

        # No detection — check if clear timeout elapsed
        if time.time() - self._last_detection_time >= TRAIN_CLEAR_TIMEOUT:
            logger.info("✓ Track clear — train has departed.")
            self.state = TrainState.DEPARTED

    def _handle_departed(self):
        """DEPARTED: Open gate, return to IDLE."""
        self.gate.open_gate()
        self.buzzer.off()
        self.current_train_id = None
        self.firebase.update_current_train(None)
        self._set_idle_state()
        logger.info("State → IDLE (green light, gate open)")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _transition_to_approaching(self):
        """IDLE → APPROACHING: yellow light, buzzer warning."""
        self.state = TrainState.APPROACHING
        self.light.set_state(LightState.YELLOW)
        self.buzzer.on()

        self.firebase.update_gate_status("CLOSED")
        logger.info("State → APPROACHING (yellow light)")

    def _set_idle_state(self):
        """Set all actuators and Firebase to IDLE defaults."""
        self.state = TrainState.IDLE
        self.light.set_state(LightState.GREEN)
        self.gate.open_gate()
        self.buzzer.off()

        self.firebase.push_all("OPEN", "OPEN", 0)


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    controller = RailwayController()
    controller.start()
