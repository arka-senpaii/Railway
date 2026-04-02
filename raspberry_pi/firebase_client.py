"""
Smart Railway Automation System — Firebase Client
====================================================
Wrapper around firebase-admin SDK for Realtime Database.
Only pushes three root-level fields:
  - current_gate_status: "OPEN" / "CLOSED"
  - gate_status:         "OPEN" / "CLOSED"
  - manual_mode:         1 / 0
"""

import time
import json
import logging
import threading
from datetime import datetime, timezone
from collections import deque

from config import FIREBASE_CREDENTIALS_PATH, FIREBASE_DATABASE_URL, OFFLINE_QUEUE_MAX

logger = logging.getLogger(__name__)

# ─── Firebase SDK ─────────────────────────────────────────────────────────────
try:
    import firebase_admin
    from firebase_admin import credentials, db
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("firebase-admin not installed — Firebase disabled.")


class FirebaseClient:
    """Thin wrapper for interacting with the Firebase Realtime Database."""

    def __init__(self):
        self.connected = False
        self._offline_queue: deque = deque(maxlen=OFFLINE_QUEUE_MAX)
        self._lock = threading.Lock()

        if not FIREBASE_AVAILABLE:
            logger.info("Firebase client in OFFLINE / SIMULATION mode.")
            return

        try:
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred, {
                "databaseURL": FIREBASE_DATABASE_URL,
            })
            self.connected = True
            logger.info("Firebase initialised successfully.")
        except Exception as exc:
            logger.error(f"Firebase init failed: {exc}")
            logger.info("Falling back to offline mode — will queue updates.")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _write(self, path: str, data):
        """Write data to Firebase; queue on failure."""
        if not FIREBASE_AVAILABLE:
            logger.info(f"[SIM] Firebase SET {path} → {json.dumps(data)}")
            return

        try:
            ref = db.reference(path)
            ref.set(data)
            self.connected = True
        except Exception as exc:
            logger.error(f"Firebase write failed ({path}): {exc}")
            self.connected = False
            with self._lock:
                self._offline_queue.append((path, data))

    def _read(self, path: str):
        """Read data from Firebase; return None on failure."""
        if not FIREBASE_AVAILABLE:
            logger.info(f"[SIM] Firebase GET {path}")
            return None

        try:
            ref = db.reference(path)
            val = ref.get()
            self.connected = True
            return val
        except Exception as exc:
            logger.error(f"Firebase read failed ({path}): {exc}")
            self.connected = False
            return None

    # ── Public API ───────────────────────────────────────────────────────────

    def update_current_gate_status(self, status: str):
        """Update /current_gate_status (the actual physical gate state)."""
        self._write("/current_gate_status", status.upper())
        logger.info(f"current_gate_status → {status.upper()}")

    def update_gate_status(self, status: str):
        """Update /gate_status (the commanded / desired gate state)."""
        self._write("/gate_status", status.upper())
        logger.info(f"gate_status → {status.upper()}")

    def update_manual_mode(self, enabled: bool):
        """Update /manual_mode (1 = manual, 0 = auto)."""
        val = 1 if enabled else 0
        self._write("/manual_mode", val)
        logger.info(f"manual_mode → {val}")

    def get_gate_status(self) -> str | None:
        """Read the commanded gate_status from Firebase."""
        return self._read("/gate_status")

    def get_manual_mode(self) -> int | None:
        """Read manual_mode flag (1 or 0)."""
        return self._read("/manual_mode")

    def push_all(self, current_gate: str, gate: str, manual: int):
        """Push all three fields at once via update (no other data touched)."""
        data = {
            "current_gate_status": current_gate.upper(),
            "gate_status": gate.upper(),
            "manual_mode": manual,
        }
        if not FIREBASE_AVAILABLE:
            logger.info(f"[SIM] Firebase UPDATE / → {json.dumps(data)}")
            return

        try:
            ref = db.reference("/")
            ref.update(data)
            self.connected = True
            logger.info(f"Firebase updated: {data}")
        except Exception as exc:
            logger.error(f"Firebase update failed: {exc}")
            self.connected = False

    # ── Offline queue flush ──────────────────────────────────────────────────

    def flush_offline_queue(self):
        """Try to push queued items; call periodically."""
        if not self._offline_queue:
            return

        logger.info(f"Flushing {len(self._offline_queue)} queued Firebase writes ...")
        retries = []
        with self._lock:
            while self._offline_queue:
                path, data = self._offline_queue.popleft()
                try:
                    ref = db.reference(path)
                    ref.set(data)
                except Exception:
                    retries.append((path, data))

            for item in retries:
                self._offline_queue.append(item)

        if retries:
            logger.warning(f"{len(retries)} items still queued (no connectivity).")
        else:
            logger.info("Offline queue flushed successfully.")

    def push_timetable(self, timetable_data: list[dict]):
        """Upload today's train schedule to Firebase."""
        if not FIREBASE_AVAILABLE:
            return
        try:
            db.reference("timetable").set(timetable_data)
            logger.info(f"Pushed {len(timetable_data)} trains to timetable.")
        except Exception as e:
            logger.error(f"Failed to push timetable: {e}")

    def update_current_train(self, train_id: str | None):
        """Update the ID of the train currently at the station."""
        if not FIREBASE_AVAILABLE:
            return
        try:
            db.reference("/").update({"current_train": train_id})
        except Exception as e:
            logger.error(f"Failed to update current train: {e}")

    # ─── Remote Audio Announcer Add-on ────────────────────────

    def get_trigger_announcement(self) -> str | None:
        """Read a pending train ID for manual announcement."""
        if not FIREBASE_AVAILABLE:
            return None
        try:
            val = db.reference("trigger_announcement").get()
            return str(val).strip() if val else None
        except Exception:
            return None

    def clear_trigger_announcement(self):
        """Reset the trigger after playing it."""
        if not FIREBASE_AVAILABLE:
            return
        try:
            db.reference("/").update({"trigger_announcement": ""})
        except Exception:
            pass

    def clear_custom_announcement(self):
        """Reset the custom announcement node after it's been handled."""
        if not FIREBASE_AVAILABLE:
            return
        try:
            db.reference("/").update({"custom_announcement": ""})
        except Exception:
            pass

    # ─── Realtime Event Listener (Event-Driven Architecture) ─────────────

    def listen_to_root(self, callback):
        """
        Listen to real-time changes at the root of the database.
        This provides instant, push-based updates instead of polling.
        Callback receives `event` with `event.path` and `event.data`.
        Returns the listener registration object.
        """
        if not FIREBASE_AVAILABLE:
            return None
        try:
            return db.reference("/").listen(callback)
        except Exception as exc:
            logger.error(f"Failed to start Firebase listener: {exc}")
            return None
