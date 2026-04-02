"""
Smart Railway Automation System — Main Controller
====================================================
Orchestrates sensors, actuators, Firebase sync, and announcements
using a state-machine approach.

HARDWARE-FIRST RULE:
  Every state transition issues hardware commands (light / gate / buzzer)
  *synchronously* on the main thread.  All Firebase writes and TTS
  generation run in daemon background threads so they never delay the
  physical hardware response.

States
------
IDLE        → green light, gate open, waiting for train
APPROACHING → yellow light + buzzer warn; transitions quickly to PASSING
PASSING     → red light, gate closed, train on track
DEPARTED    → gate opens, returns to IDLE

Usage
-----
    python main.py            # on Raspberry Pi
    python main.py --simulate # desktop simulation (no GPIO)
    python main.py --debug    # verbose logging
"""

import sys
import time
import signal
import logging
import argparse
import threading
from datetime import datetime

from config import (
    TrainState, GateState, LightState,
    MAX_PASSING_TIMEOUT, YELLOW_WARNING_DURATION,
    FIREBASE_SYNC_INTERVAL, IR_SENSOR_IN_PIN, IR_SENSOR_OUT_PIN,
    LOG_LEVEL, MAIN_LOOP_SLEEP,
)
from sensors       import IRSensor, RFIDReader
from actuators     import ServoGate, TrafficLight, Buzzer
from firebase_client import FirebaseClient
from announcement  import AnnouncementEngine, TrainScheduleDB
from manual_mode   import ManualModeController

# ─── CLI args & logging ───────────────────────────────────────────────────────

_parser = argparse.ArgumentParser(description="Smart Railway Controller")
_parser.add_argument("--debug",    action="store_true", help="Verbose logging")
_parser.add_argument("--simulate", action="store_true", help="Desktop simulation (no GPIO)")
_args = _parser.parse_args()

logging.basicConfig(
    level=logging.DEBUG if _args.debug else getattr(logging, LOG_LEVEL, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("RailwaySystem")


# ═════════════════════════════════════════════════════════════════════════════
#  Railway Automation Controller
# ═════════════════════════════════════════════════════════════════════════════

class RailwayController:

    def __init__(self):
        logger.info("=" * 60)
        logger.info("  Smart Railway Automation System")
        logger.info("=" * 60)

        # ── Hardware components ──
        self.ir_in    = IRSensor(pin=IR_SENSOR_IN_PIN)
        self.ir_out   = IRSensor(pin=IR_SENSOR_OUT_PIN)
        self.rfid     = RFIDReader()
        self.gate     = ServoGate()
        self.light    = TrafficLight()
        self.buzzer   = Buzzer()

        # ── Software components ──
        self.firebase     = FirebaseClient()
        self.schedule_db  = TrainScheduleDB()
        self.announcer    = AnnouncementEngine(self.firebase, self.schedule_db)
        self.manual_ctrl  = ManualModeController(
            self.firebase, self.gate, self.light, self.buzzer, self.announcer,
            on_gate_close_callback=self._on_manual_gate_closed,
            on_gate_open_callback=self._on_manual_gate_opened,
        )

        # ── State ──
        self.state                  = TrainState.IDLE
        self.current_train_id       = None
        self._last_detection_time   = 0.0
        self._passing_start_time    = 0.0
        self._out_sensor_triggered  = False
        self._running               = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        signal.signal(signal.SIGINT,  self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

        # Hardware-first: set IDLE state before any network calls
        self._set_idle_state_hardware()
        self.manual_ctrl.start()

        # Push timetable + reset current_train in background
        threading.Thread(target=self._startup_firebase, daemon=True).start()

        # Pre-generate upcoming announcements in background
        self.announcer.pregenerate_todays_announcements()

        logger.info("System online — entering main loop.")
        try:
            self._main_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def _startup_firebase(self):
        """Push initial data to Firebase in a background thread."""
        all_trains = self.schedule_db.get_all_trains()
        if all_trains:
            self.firebase.push_timetable(all_trains)
            logger.info(f"Pushed {len(all_trains)} trains to Firebase timetable.")
        self.firebase.update_current_train(None)
        self.firebase.push_all("OPEN", "OPEN", 0)

    def shutdown(self):
        self._running = False
        logger.info("Shutting down …")
        self.manual_ctrl.stop()
        # Safety: always leave gate open on shutdown
        self.gate.open_gate()
        self.light.all_off()
        self.buzzer.off()
        self.ir_in.cleanup()
        self.ir_out.cleanup()
        self.rfid.cleanup()
        self.gate.cleanup()
        self.light.cleanup()
        self.buzzer.cleanup()
        # Final Firebase update (best-effort)
        try:
            self.firebase.update_current_gate_status("OPEN")
        except Exception:
            pass
        logger.info("Shutdown complete.")

    def _shutdown_handler(self, signum, frame):
        logger.info(f"Signal {signum} received — shutting down.")
        self._running = False

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def _main_loop(self):
        while self._running:
            if self.manual_ctrl.is_enabled:
                time.sleep(0.5)
                continue

            # Flush any queued offline Firebase writes (non-blocking attempt)
            threading.Thread(
                target=self.firebase.flush_offline_queue, daemon=True
            ).start()

            if   self.state == TrainState.IDLE:        self._handle_idle()
            elif self.state == TrainState.APPROACHING:  self._handle_approaching()
            elif self.state == TrainState.PASSING:      self._handle_passing()
            elif self.state == TrainState.DEPARTED:     self._handle_departed()

            time.sleep(MAIN_LOOP_SLEEP)

    # ── Manual-mode callbacks ─────────────────────────────────────────────────

    def _on_manual_gate_closed(self):
        """Called by ManualModeController when the gate is manually closed."""
        def _task():
            if self.current_train_id is None:
                train_id = self._predict_current_train()
                if train_id:
                    self.current_train_id = train_id
                    self.firebase.update_current_train(train_id)
                    result = self.announcer.generate_and_play(train_id)
                    logger.info(f"Manual prediction → Train {train_id}: {result['message']}")
                    if result.get("delay_minutes", 0) > 0:
                        self.announcer.generate_late_announcement(
                            result["train_data"], result["delay_minutes"]
                        )
        threading.Thread(target=_task, daemon=True).start()

    def _on_manual_gate_opened(self):
        self.current_train_id = None
        threading.Thread(
            target=lambda: self.firebase.update_current_train(None), daemon=True
        ).start()

    # ── State Handlers ────────────────────────────────────────────────────────

    def _handle_idle(self):
        """IDLE — wait for IR IN sensor to fire."""
        if self.ir_in.is_obstacle_detected():
            logger.info("🚆 Train detected by IN sensor!")
            self._last_detection_time = time.time()
            self._transition_to_approaching()

    def _handle_approaching(self):
        """
        APPROACHING — yellow warning phase.

        Hardware timeout is YELLOW_WARNING_DURATION (1 s).
        As soon as the timer expires we immediately:
          1. Set RED light        ← HARDWARE (synchronous, main thread)
          2. Close gate           ← HARDWARE (synchronous, main thread)
          3. Sound buzzer x 3     ← HARDWARE (synchronous, main thread)
          4. Update Firebase      ← NETWORK  (background thread)
          5. Predict + announce   ← TTS/NET  (background thread)

        This ordering guarantees the physical gate closes in ~1 s after
        detection regardless of network latency or TTS generation time.
        """
        # Refresh detection timestamp while sensor still sees the train
        if self.ir_in.is_obstacle_detected():
            self._last_detection_time = time.time()

        elapsed = time.time() - self._last_detection_time
        if elapsed < YELLOW_WARNING_DURATION:
            return  # still in yellow warning window

        # ── 1-3: HARDWARE FIRST (runs synchronously on main thread) ──────────
        self.state = TrainState.PASSING
        self._passing_start_time   = time.time()
        self._out_sensor_triggered = False

        self.light.set_state(LightState.RED)   # physical LED change
        self.gate.close_gate()                  # servo motor
        self.buzzer.beep(times=3)               # beep beep beep
        logger.info("State → PASSING (red light, gate closed)")

        # ── 4-5: NETWORK + TTS in background (never blocks hardware) ─────────
        def _bg():
            # Firebase gate status
            self.firebase.update_current_gate_status("CLOSED")
            self.firebase.update_gate_status("CLOSED")

            # Train prediction & announcement
            if self.current_train_id is None:
                train_id = self._predict_current_train()
                if train_id:
                    self.current_train_id = train_id
                    self.firebase.update_current_train(train_id)
                    result = self.announcer.generate_and_play(train_id)
                    logger.info(
                        f"Prediction → Train {train_id}: {result['message']}"
                    )
                    if result.get("delay_minutes", 0) > 0:
                        self.announcer.generate_late_announcement(
                            result["train_data"], result["delay_minutes"]
                        )

        threading.Thread(target=_bg, daemon=True).start()

    def _handle_passing(self):
        """PASSING — wait for train to clear the OUT sensor."""
        # Safety timeout: reset if train never reaches OUT sensor
        if time.time() - self._passing_start_time >= MAX_PASSING_TIMEOUT:
            logger.warning("TIMEOUT: OUT sensor never triggered — resetting.")
            self.state = TrainState.DEPARTED
            return

        detecting = self.ir_out.is_obstacle_detected()
        if detecting and not self._out_sensor_triggered:
            logger.info("Train at OUT sensor …")
            self._out_sensor_triggered = True
        elif not detecting and self._out_sensor_triggered:
            logger.info("✓ Track clear — train passed OUT sensor.")
            self.state = TrainState.DEPARTED

    def _handle_departed(self):
        """
        DEPARTED — revert to safe IDLE state.

        Hardware first, Firebase in background.
        """
        # ── HARDWARE (synchronous) ────────────────────────────────────────────
        self.gate.open_gate()
        self.buzzer.off()
        self.current_train_id = None
        self._set_idle_state_hardware()
        logger.info("State → IDLE (green light, gate open)")

        # ── FIREBASE (background) ─────────────────────────────────────────────
        threading.Thread(
            target=lambda: (
                self.firebase.update_current_train(None),
                self.firebase.push_all("OPEN", "OPEN", 0),
            ),
            daemon=True,
        ).start()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _transition_to_approaching(self):
        """IDLE → APPROACHING: yellow light + buzzer immediately."""
        self.state = TrainState.APPROACHING

        # HARDWARE FIRST
        self.light.set_state(LightState.YELLOW)
        self.buzzer.on()

        # Firebase update in background
        threading.Thread(
            target=lambda: self.firebase.update_gate_status("CLOSED"),
            daemon=True,
        ).start()
        logger.info("State → APPROACHING (yellow light)")

    def _set_idle_state_hardware(self):
        """Apply IDLE hardware outputs (green light, gate open, buzzer off)."""
        self.state = TrainState.IDLE
        self.light.set_state(LightState.GREEN)
        self.gate.open_gate()
        self.buzzer.off()

    def _predict_current_train(self) -> str | None:
        """Find the closest scheduled train to the current time."""
        today_trains = self.schedule_db.get_todays_trains()
        if not today_trains:
            return None

        now = datetime.now()
        now_mins = now.hour * 60 + now.minute
        best, min_diff = None, 999999

        for train in today_trains:
            arr = train.get("Arrival_Time", "")
            if not arr or arr in ("--", "N/A"):
                continue
            try:
                h, m = map(int, arr.split(":"))
                diff = abs(h * 60 + m - now_mins)
                if diff > 12 * 60:
                    diff = 24 * 60 - diff   # midnight wrap-around
                if diff < min_diff:
                    min_diff = diff
                    best = train["Train_No"]
            except Exception:
                pass

        return best


# ═════════════════════════════════════════════════════════════════════════════
#  Entry Point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    controller = RailwayController()
    controller.start()
