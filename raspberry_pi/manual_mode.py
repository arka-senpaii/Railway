"""
Smart Railway Automation System — Manual Override Mode
=======================================================
Listens to /manual_mode and /gate_status in Firebase
and applies gate commands from the dashboard.
"""

import time
import logging
import threading

from config import MANUAL_POLL_INTERVAL, GateState

logger = logging.getLogger(__name__)


class ManualModeController:
    """
    Polls Firebase for manual_mode and gate_status,
    then applies gate commands to the actuators when manual mode is on.
    """

    def __init__(self, firebase_client, servo_gate, traffic_light, buzzer, announcer=None):
        self.fb = firebase_client
        self.gate = servo_gate
        self.light = traffic_light
        self.buzzer = buzzer
        self.announcer = announcer

        self.enabled = False
        self._running = False
        self._thread = None

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self):
        """Begin polling Firebase for manual-mode commands."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Manual-mode controller started.")

    def stop(self):
        """Stop the polling thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("Manual-mode controller stopped.")

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    # ── Internal ─────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                # 1. Check for Station Master remote announcement trigger
                if self.announcer:
                    trigger_id = self.fb.get_trigger_announcement()
                    if trigger_id:
                        logger.info(f"🔊 Remote announcement triggered from dashboard: Train {trigger_id}")
                        self.fb.clear_trigger_announcement()
                        self.fb.update_current_train(trigger_id)
                        threading.Thread(
                            target=self.announcer.generate_and_play,
                            args=(trigger_id,),
                            daemon=True
                        ).start()

                # 2. Check and handle Manual Mode
                manual_mode = self.fb.get_manual_mode()
                if manual_mode is None:
                    self.enabled = False
                    time.sleep(MANUAL_POLL_INTERVAL)
                    continue

                was_enabled = self.enabled
                self.enabled = (manual_mode == 1)

                if self.enabled and not was_enabled:
                    logger.info("⚠ Manual override ENABLED from dashboard.")
                elif not self.enabled and was_enabled:
                    logger.info("✓ Manual override DISABLED — returning to auto.")

                if self.enabled:
                    self._apply_commands()

            except Exception as exc:
                logger.error(f"Manual-mode poll error: {exc}")

            time.sleep(MANUAL_POLL_INTERVAL)

    def _apply_commands(self):
        """Read gate_status from Firebase and apply to physical gate."""
        gate_cmd = self.fb.get_gate_status()
        if gate_cmd is None:
            return

        gate_cmd = gate_cmd.upper()

        if gate_cmd == "OPEN" and self.gate.state != GateState.OPEN:
            self.gate.open_gate()
            self.fb.update_current_gate_status("OPEN")

        elif gate_cmd == "CLOSED" and self.gate.state != GateState.CLOSED:
            self.gate.close_gate()
            self.buzzer.beep(times=2)
            self.fb.update_current_gate_status("CLOSED")
