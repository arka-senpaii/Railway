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
import argparse
import threading
from datetime import datetime, timezone

from config import (
    TrainState, GateState, LightState,
    MAX_PASSING_TIMEOUT, YELLOW_WARNING_DURATION,
    FIREBASE_SYNC_INTERVAL, IR_SENSOR_IN_PIN, IR_SENSOR_OUT_PIN,
    LOG_LEVEL, MAIN_LOOP_SLEEP,
)
from sensors import IRSensor, RFIDReader
from actuators import ServoGate, TrafficLight, Buzzer
from firebase_client import FirebaseClient
from announcement import AnnouncementEngine, TrainScheduleDB
from manual_mode import ManualModeController

# ─── Logging setup ───────────────────────────────────────────────────────────

# Parse CLI args early so we can set log level
_parser = argparse.ArgumentParser(description="Smart Railway Controller")
_parser.add_argument("--debug", action="store_true", help="Enable verbose INFO/DEBUG logging")
_parser.add_argument("--simulate", action="store_true", help="Run in desktop simulation mode")
_args = _parser.parse_args()

logging.basicConfig(
    level=logging.DEBUG if _args.debug else getattr(logging, LOG_LEVEL, logging.WARNING),
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
        self.ir_sensor_in = IRSensor(pin=IR_SENSOR_IN_PIN)
        self.ir_sensor_out = IRSensor(pin=IR_SENSOR_OUT_PIN)
        self.rfid_reader = RFIDReader()
        self.gate = ServoGate()
        self.light = TrafficLight()
        self.buzzer = Buzzer()
        self.firebase = FirebaseClient()
        self.schedule_db = TrainScheduleDB()
        self.announcer = AnnouncementEngine(self.firebase, self.schedule_db)
        self.manual_ctrl = ManualModeController(
            self.firebase, self.gate, self.light, self.buzzer, self.announcer,
            on_gate_close_callback=self._on_manual_gate_closed,
            on_gate_open_callback=self._on_manual_gate_opened
        )

        # ── State ──
        self.state = TrainState.IDLE
        self.current_train_id = None
        self._last_detection_time = 0.0
        self._passing_start_time = 0.0
        self._out_sensor_triggered = False
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

        # Push the full timetable to Firebase so the dashboard can handle multi-day display natively
        all_trains = self.schedule_db.get_all_trains()
        if all_trains:
            self.firebase.push_timetable(all_trains)
            logger.info(f"Pushed {len(all_trains)} total master schedule trains to Firebase timetable.")
        self.firebase.update_current_train(None)

        # Pre-generate all announcements in background so they're instant
        self.announcer.pregenerate_todays_announcements()

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
        self.ir_sensor_in.cleanup()
        self.ir_sensor_out.cleanup()
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

            time.sleep(MAIN_LOOP_SLEEP)

    def _on_manual_gate_closed(self):
        """Callback from ManualModeController when the gate is manually closed."""
        def _task():
            if self.current_train_id is None:
                train_id = self._predict_current_train()
                if train_id:
                    self.current_train_id = train_id
                    self.firebase.update_current_train(train_id)
                    result = self.announcer.generate_and_play(train_id)
                    logger.info(f"Manual Override Prediction Identified Train: {train_id} — Announcement: {result['message']}")
                    if result.get('delay_minutes', 0) > 0:
                        self.announcer.generate_late_announcement(
                            result['train_data'], result['delay_minutes']
                        )
                        
        threading.Thread(target=_task, daemon=True).start()

    def _on_manual_gate_opened(self):
        """Callback from ManualModeController when the gate is manually opened."""
        self.current_train_id = None
        self.firebase.update_current_train(None)

    # ── State Handlers ───────────────────────────────────────────────────────

    def _handle_idle(self):
        """IDLE: Wait for the IN IR sensor to detect a train."""
        if self.ir_sensor_in.is_obstacle_detected():
            logger.info("🚆 Train detected by IN IR sensor!")
            self._last_detection_time = time.time()
            self._transition_to_approaching()

    def _predict_current_train(self) -> str | None:
        """Find the train in today's schedule whose scheduled arrival time is closest to now."""
        today_trains = self.schedule_db.get_todays_trains()
        if not today_trains:
            return None

        now = datetime.now()
        now_minutes = now.hour * 60 + now.minute
        
        best_train_id = None
        min_diff = 999999

        for train in today_trains:
            arrival_str = train.get("Arrival_Time", "")
            if not arrival_str or arrival_str in ("--", "N/A"):
                continue

            # Parse HH:MM from arrival_str
            try:
                parts = arrival_str.split(":")
                hh = int(parts[0])
                mm = int(parts[1])
                arr_minutes = hh * 60 + mm
                diff = abs(arr_minutes - now_minutes)
                
                # Account for midnight wrap-around seamlessly
                if diff > 12 * 60:
                    diff = 24 * 60 - diff
                    
                if diff < min_diff:
                    min_diff = diff
                    best_train_id = train["Train_No"]
            except Exception:
                pass

        return best_train_id

    def _handle_approaching(self):
        """APPROACHING: Warning phase — yellow light, then red + gate close."""
        # If IN IR still detects, train is moving to PASSING
        if self.ir_sensor_in.is_obstacle_detected():
            self._last_detection_time = time.time()

        # Software Time-Based Prediction (Replaces RFID hardware)
        if self.current_train_id is None:
            train_id = self._predict_current_train()
            if train_id:
                self.current_train_id = train_id
                self.firebase.update_current_train(train_id)
                result = self.announcer.generate_and_play(train_id)
                logger.info(f"Automated Prediction Identified Train: {train_id} — Announcement: {result['message']}")
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
        self._passing_start_time = time.time()
        self._out_sensor_triggered = False
        self.light.set_state(LightState.RED)
        self.gate.close_gate()
        self.buzzer.beep(times=3)

        self.firebase.update_current_gate_status("CLOSED")
        self.firebase.update_gate_status("CLOSED")
        logger.info("State → PASSING (red light, gate closed)")

    def _handle_passing(self):
        """PASSING: Train is on the track; wait for it to clear OUT sensor."""
        # Fallback timeout
        if time.time() - self._passing_start_time >= MAX_PASSING_TIMEOUT:
            logger.warning("TIMEOUT: Train did not reach OUT sensor. Resetting to IDLE.")
            self.state = TrainState.DEPARTED
            return
            
        is_detecting = self.ir_sensor_out.is_obstacle_detected()
        if is_detecting:
            if not self._out_sensor_triggered:
                logger.info("Train has reached the OUT sensor...")
                self._out_sensor_triggered = True
        else:
            if self._out_sensor_triggered:
                logger.info("✓ Track clear — train has passed OUT sensor.")
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
