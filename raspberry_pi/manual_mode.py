"""
Smart Railway Automation System — Manual Override Mode
=======================================================
Listens to /manual_mode and /gate_status in Firebase
and applies gate commands from the dashboard.
"""

import time
import logging
import threading

from config import MANUAL_POLL_INTERVAL, GateState, LightState

logger = logging.getLogger(__name__)


class ManualModeController:
    """
    Event-driven manual override controller.
    Listens to real-time events from Firebase (manual_mode, gate_status,
    announcements) and applies them instantly without polling.
    """

    def __init__(self, firebase_client, servo_gate, traffic_light, buzzer, announcer=None,
                 on_gate_close_callback=None, on_gate_open_callback=None):
        self.fb = firebase_client
        self.gate = servo_gate
        self.light = traffic_light
        self.buzzer = buzzer
        self.announcer = announcer
        self.on_gate_close_callback = on_gate_close_callback
        self.on_gate_open_callback = on_gate_open_callback

        self.enabled = False
        self._listener_registration = None

    # ── Public API ───────────────────────────────────────────────────────────

    def start(self):
        """Begin listening to Firebase for manual-mode commands."""
        if self._listener_registration:
            return
        
        self._listener_registration = self.fb.listen_to_root(self._on_firebase_event)
        logger.info("Manual-mode push listener started.")

    def stop(self):
        """Stop listening."""
        if self._listener_registration:
            try:
                self._listener_registration.close()
            except Exception:
                pass
            self._listener_registration = None
        self.enabled = False
        logger.info("Manual-mode listener stopped.")

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    # ── Internal Event Handlers ──────────────────────────────────────────────

    def _on_firebase_event(self, event):
        if not event or event.data is None:
            return

        try:
            # If the entire root was updated (e.g. init or push_all)
            if event.path == "/":
                data = event.data
                if not isinstance(data, dict):
                    return
                # Trigger Announcement
                trigger = data.get("trigger_announcement")
                if trigger:
                    self._handle_trigger(trigger)
                # Manual Mode flag
                man = data.get("manual_mode")
                if man is not None:
                    self._handle_manual_mode(man == 1)
                # Gate Command
                cmd = data.get("gate_status")
                if cmd and self.enabled:
                    self._handle_gate_cmd(cmd)
                # Custom Announcement
                custom_txt = data.get("custom_announcement")
                if custom_txt:
                    self._handle_custom_announcement(custom_txt)

            # Or if specific keys were updated
            else:
                path = event.path.strip("/")
                val = event.data
                
                if path == "trigger_announcement" and val:
                    self._handle_trigger(val)
                elif path == "manual_mode":
                    self._handle_manual_mode(val == 1)
                elif path == "gate_status" and self.enabled:
                    self._handle_gate_cmd(val)
                elif path == "custom_announcement" and val:
                    self._handle_custom_announcement(val)

        except Exception as exc:
            logger.error(f"Event handler error: {exc}")

    def _handle_trigger(self, trigger_id):
        trigger_id = str(trigger_id).strip()
        if not trigger_id:
            return
        logger.info(f"🔊 Remote announcement triggered from dashboard: Train {trigger_id}")
        self.fb.clear_trigger_announcement()
        self.fb.update_current_train(trigger_id)
        
        if self.announcer:
            threading.Thread(
                target=self.announcer.generate_and_play,
                args=(trigger_id,),
                daemon=True
            ).start()

    def _handle_custom_announcement(self, text: str):
        text = str(text).strip()
        if not text:
            return
        logger.info(f"🔊 Remote Custom Announcement triggered: {text}")
        self.fb.clear_custom_announcement()
        
        if self.announcer:
            threading.Thread(
                target=self.announcer.announce_custom_text,
                args=(text,),
                daemon=True
            ).start()

    def _handle_manual_mode(self, enabled: bool):
        was_enabled = self.enabled
        self.enabled = enabled

        if enabled and not was_enabled:
            logger.info("⚠ Manual override ENABLED from dashboard.")
            # When turned on, apply the current remote gate command immediately
            gate_cmd = self.fb.get_gate_status()
            if gate_cmd:
                self._handle_gate_cmd(gate_cmd)
        elif not enabled and was_enabled:
            logger.info("✓ Manual override DISABLED — returning to auto.")

    def _handle_gate_cmd(self, cmd):
        gate_cmd = str(cmd).upper()
        
        if gate_cmd == "OPEN":
            if self.gate.state != GateState.OPEN or self.light.state != LightState.GREEN:
                self.light.set_state(LightState.GREEN)
                self.gate.open_gate()
                self.fb.update_current_gate_status("OPEN")
                if self.on_gate_open_callback:
                    self.on_gate_open_callback()

        elif gate_cmd == "CLOSED":
            if self.gate.state != GateState.CLOSED or self.light.state != LightState.RED:
                self.light.set_state(LightState.RED)
                self.gate.close_gate()
                self.buzzer.beep(times=2)
                self.fb.update_current_gate_status("CLOSED")
                if self.on_gate_close_callback:
                    self.on_gate_close_callback()
