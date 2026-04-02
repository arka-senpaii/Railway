"""
Smart Railway Automation System — Announcement Engine (Optimised for RPi 3B+)
===============================================================================
Generates Indian-Railways-style announcements in 3 languages using:
  - 13-part audio skeleton from project.mp3
  - TTS via gTTS (cached on disk with LRU eviction)
  - ffplay for zero-overhead playback on Raspberry Pi

RPi 3B+ optimisations:
  • ThreadPoolExecutor capped at TTS_MAX_WORKERS (2)
  • TTS disk cache limited to MAX_TTS_CACHE_FILES (LRU eviction)
  • Pre-generation limited to next PRE_GEN_LOOKAHEAD trains
  • gc.collect() after heavy audio operations
  • Auto-cleanup of late-announcement WAV files after playback
"""

import os
import gc
import logging
import threading
import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv

from config import (
    MAX_TTS_CACHE_FILES, PRE_GEN_LOOKAHEAD, TTS_MAX_WORKERS,
)

logger = logging.getLogger(__name__)

# ─── Optional audio dependencies (graceful fallback) ─────────────────────────
try:
    from gtts import gTTS
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    logger.warning("gTTS not installed — text-to-speech disabled.")

try:
    import audioop
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
    try:
        import imageio_ffmpeg
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("pydub not installed — audio processing disabled.")

import platform
import subprocess

# ─── Playback (optimised for RPi) ────────────────────────────────────────────
PLAY_FUNCTION = None

if platform.system() == "Linux":
    def _play_linux(filepath):
        """Play audio via ffplay — lightest method for RPi 3B+ audio output."""
        try:
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath],
                check=True,
            )
        except FileNotFoundError:
            logger.error("ffplay not found — install ffmpeg: sudo apt install ffmpeg")
        except Exception as e:
            logger.warning(f"Audio playback failed: {e}")
    PLAY_FUNCTION = _play_linux
else:
    def _play_other(filepath):
        try:
            if hasattr(os, 'startfile'):
                os.startfile(filepath)
            else:
                subprocess.run(['open', filepath])
        except Exception as e:
            logger.warning(f"Audio playback failed: {e}")
    PLAY_FUNCTION = _play_other


# ─── Audio skeleton timestamps from project.mp3 ─────────────────────────────
SKELETON_PARTS = [
    (0,     5221,  1),   # English intro chime
    (11213, 13438, 3),   # "is arriving on"
    (14437, 17342, 5),   # Bengali intro
    (23925, 25559, 8),   # "platform e asche"
    (25889, 28247, 9),   # Hindi intro
    (34584, 36206, 11),  # "platform kramank"
    (36885, 38440, 13),  # "par aa rahi hai" + closing
]

# ─── Data paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TIMETABLE_CSV = os.path.join(SCRIPT_DIR, "adrajndet.csv")
SCHEDULE_CSV = os.path.join(SCRIPT_DIR, "adrajn.csv")
ANNOUNCEMENT_MP3 = os.path.join(SCRIPT_DIR, "project.mp3")
LATE_MP3 = os.path.join(SCRIPT_DIR, "late.mp3")
TTS_CACHE_DIR = os.path.join(SCRIPT_DIR, ".tts_cache")


# ─── LRU-evicting TTS cache ─────────────────────────────────────────────────

def _enforce_cache_limit():
    """Delete oldest cached TTS files when cache exceeds MAX_TTS_CACHE_FILES."""
    if not os.path.isdir(TTS_CACHE_DIR):
        return
    files = []
    for f in os.listdir(TTS_CACHE_DIR):
        fp = os.path.join(TTS_CACHE_DIR, f)
        if os.path.isfile(fp) and f.endswith(".mp3"):
            files.append((os.path.getmtime(fp), fp))
    if len(files) <= MAX_TTS_CACHE_FILES:
        return
    files.sort()  # oldest first
    for _, fp in files[: len(files) - MAX_TTS_CACHE_FILES]:
        try:
            os.remove(fp)
        except OSError:
            pass


def _cached_tts(text: str, lang: str, tld: str = 'co.in') -> str:
    """Generate TTS audio via gTTS, caching on disk by content hash."""
    os.makedirs(TTS_CACHE_DIR, exist_ok=True)
    cache_key = hashlib.md5(f"{text}|{lang}|{tld}".encode()).hexdigest()
    cache_path = os.path.join(TTS_CACHE_DIR, f"{cache_key}.mp3")
    if os.path.exists(cache_path):
        # Touch the file so LRU eviction treats it as recently used
        os.utime(cache_path)
        return cache_path
    gTTS(text=text, lang=lang, tld=tld, slow=False).save(cache_path)
    _enforce_cache_limit()
    return cache_path


# ═════════════════════════════════════════════════════════════════════════════
#  Train Schedule DB
# ═════════════════════════════════════════════════════════════════════════════

class TrainScheduleDB:
    """Loads Adra Junction timetable CSVs and provides lookup by train number."""

    def __init__(self):
        self.detailed_df = None
        self.schedule_df = None
        self._load()

    def _load(self):
        try:
            if os.path.exists(TIMETABLE_CSV):
                with open(TIMETABLE_CSV, mode="r", encoding="utf-8") as f:
                    self.detailed_df = list(csv.DictReader(f))
                logger.info(f"Loaded {len(self.detailed_df)} rows from adrajndet.csv")

            if os.path.exists(SCHEDULE_CSV):
                with open(SCHEDULE_CSV, mode="r", encoding="utf-8") as f:
                    self.schedule_df = list(csv.DictReader(f))
                logger.info(f"Loaded {len(self.schedule_df)} rows from adrajn.csv")
        except Exception as exc:
            logger.error(f"Failed to load train data: {exc}")

    def lookup(self, train_no: str) -> dict | None:
        """Look up a train by number (handles spaced format like '2 2 8 1 2')."""
        train_no = str(train_no).replace(" ", "").strip()

        if self.detailed_df is not None:
            for row in self.detailed_df:
                raw = str(row.get("Train No", "")).replace(" ", "").strip()
                if raw == train_no:
                    return {
                        "Train_No": raw,
                        "Train_Name": str(row.get("Train Name", "Unknown")),
                        "From": str(row.get("From", "N/A")),
                        "To": str(row.get("To", "N/A")),
                        "Arrival_Time": str(row.get("Arrival Time", "--")),
                        "Departure_Time": str(row.get("Departure Time", "--")),
                        "Platform_No": str(row.get("Platform", "1")),
                        "Line_Type": str(row.get("Line Type", "Main Line")),
                        "Days": str(row.get("Days of Operation", "Daily")),
                    }

        if self.schedule_df is not None:
            for row in self.schedule_df:
                raw = str(row.get("Train No", "")).replace(" ", "").strip()
                if raw == train_no:
                    return {
                        "Train_No": raw,
                        "Train_Name": str(row.get("Train Name", "Unknown")),
                        "From": str(row.get("From", "N/A")),
                        "To": str(row.get("To", "N/A")),
                        "Arrival_Time": str(row.get("Arrival Time", "--")),
                        "Departure_Time": "--",
                        "Platform_No": "1",
                        "Line_Type": "Main Line",
                        "Days": str(row.get("Days of Operation", "Daily")),
                    }
        return None

    def runs_today(self, days_str: str) -> bool:
        if not isinstance(days_str, str):
            return False
        if "Daily" in days_str:
            return True
        today_short = datetime.now().strftime("%a")
        return today_short in days_str

    def get_all_trains(self) -> list[dict]:
        """Return ALL trains from the master database with explicit Days of Operation mapped."""
        results = []
        df_list = self.detailed_df if self.detailed_df is not None else self.schedule_df
        if df_list is None:
            return results

        for row in df_list:
            results.append({
                "Train_No": str(row.get("Train No", "")).replace(" ", "").strip(),
                "Train_Name": str(row.get("Train Name", "")),
                "From": str(row.get("From", "N/A")),
                "To": str(row.get("To", "N/A")),
                "Arrival_Time": str(row.get("Arrival Time", "--")),
                "Platform_No": str(row.get("Platform", row.get("Platform_No", "1"))),
                "Days": str(row.get("Days of Operation", "Daily")),
            })
        return results

    def get_todays_trains(self) -> list[dict]:
        """Return all trains that run today, sorted by arrival time."""
        results = []
        all_trains = self.get_all_trains()
        for t in all_trains:
            if self.runs_today(t["Days"]):
                results.append(t)
        return results

    def get_upcoming_trains(self, limit: int = PRE_GEN_LOOKAHEAD) -> list[dict]:
        """Return the next `limit` trains arriving after now (for smart pre-gen)."""
        all_today = self.get_todays_trains()
        now = datetime.now()
        now_minutes = now.hour * 60 + now.minute

        upcoming = []
        for t in all_today:
            arr = t.get("Arrival_Time", "--")
            if arr in ("--", "N/A", ""):
                continue
            try:
                parts = arr.split(":")
                arr_minutes = int(parts[0]) * 60 + int(parts[1])
                if arr_minutes >= now_minutes - 10:  # include trains arriving ±10 min
                    upcoming.append((arr_minutes, t))
            except (ValueError, IndexError):
                pass

        upcoming.sort(key=lambda x: x[0])
        return [t for _, t in upcoming[:limit]]


# ═════════════════════════════════════════════════════════════════════════════
#  Announcement Engine (Optimised for RPi 3B+)
# ═════════════════════════════════════════════════════════════════════════════

class AnnouncementEngine:
    """
    Generates Indian-Railways-style announcements in 3 languages.

    RPi 3B+ optimisations:
      • Skeleton kept in memory (loaded once)
      • TTS cached on disk with LRU eviction
      • ThreadPoolExecutor limited to TTS_MAX_WORKERS (2)
      • Pre-generation limited to upcoming trains only
      • gc.collect() after heavy audio operations
      • Late-announcement WAV auto-deleted after playback
    """

    def __init__(self, firebase_client=None, schedule_db: TrainScheduleDB = None):
        self.fb = firebase_client
        self.schedule_db = schedule_db or TrainScheduleDB()
        self._skeleton_segments = {}
        self._skeleton_ready = False
        self._lock = threading.Lock()
        self._pregenerated = {}

    # ── Public API ───────────────────────────────────────────────────────────

    def generate_and_play(self, train_id: str) -> dict:
        """Full pipeline: look up → delay → generate audio → play on Pi."""
        train_data = self.schedule_db.lookup(train_id)

        if train_data is None:
            msg = f"Train {train_id} not found in timetable."
            logger.warning(msg)
            return {"train_data": None, "delay_minutes": 0,
                    "status": "unknown", "message": msg, "audio_file": None}

        delay_info = self._compute_delay(train_data)

        train_no = str(train_id).replace(" ", "").strip()
        audio_file = self._pregenerated.get(train_no)
        if audio_file and os.path.exists(audio_file):
            logger.info(f"Using pre-generated announcement for train {train_no}")
        else:
            audio_file = self._generate_audio(train_data)

        if not audio_file or not os.path.exists(audio_file):
            logger.warning("Audio generation failed. Falling back to project.mp3.")
            if os.path.exists(ANNOUNCEMENT_MP3):
                audio_file = ANNOUNCEMENT_MP3

        # Play on Pi (via ffplay in background thread)
        if audio_file and PLAY_FUNCTION:
            threading.Thread(
                target=PLAY_FUNCTION, args=(audio_file,), daemon=True
            ).start()

        if self.fb:
            self.fb.update_gate_status("CLOSED")

        return {
            "train_data": train_data,
            **delay_info,
            "audio_file": audio_file,
        }

    def pregenerate_todays_announcements(self):
        """
        Pre-generate announcements for the NEXT few upcoming trains only
        (not all) to save RAM and startup time on RPi 3B+.
        """
        def _worker():
            upcoming = self.schedule_db.get_upcoming_trains(PRE_GEN_LOOKAHEAD)
            if not upcoming:
                logger.info("No upcoming trains — skipping pre-generation.")
                return
            logger.info(f"Pre-generating {len(upcoming)} upcoming announcements ...")
            for i, train in enumerate(upcoming, 1):
                train_no = train["Train_No"]
                if train_no in self._pregenerated:
                    continue
                full_data = self.schedule_db.lookup(train_no)
                if full_data:
                    path = self._generate_audio(full_data)
                    if path:
                        self._pregenerated[train_no] = path
                        logger.info(f"  [{i}/{len(upcoming)}] Pre-generated: {train_no}")
            gc.collect()
            logger.info(f"Pre-generation complete — {len(self._pregenerated)} ready.")

        threading.Thread(target=_worker, daemon=True).start()

    def generate_late_announcement(self, train_data: dict, delay_minutes: int) -> str | None:
        """
        Generate delay announcement. Auto-plays and auto-deletes the WAV
        after playback to save disk space on 32 GB SD card.
        """
        if not TTS_AVAILABLE or not PYDUB_AVAILABLE:
            return None
        if delay_minutes <= 0:
            return None

        try:
            if os.path.exists(LATE_MP3):
                audio = AudioSegment.from_mp3(LATE_MP3)
                chime = audio[:1000]
                del audio  # free immediately
            else:
                chime = AudioSegment.silent(duration=1000)

            train_no = train_data["Train_No"]
            train_no_spoken = " ".join(list(str(train_no)))
            train_name = train_data["Train_Name"]
            arrival = train_data.get("Arrival_Time", "N/A")

            text_hi = (
                f"Yatri kripya dhyan de. Gadi sankhya {train_no_spoken}, {train_name}, "
                f"apne nirdharit samay {arrival} se {delay_minutes} minute "
                f"deri se chal rahi hai. Asuvidha ke liye hume khed hai."
            )
            text_en = (
                f"May I have your attention please. Train number {train_no_spoken}, "
                f"{train_name}, scheduled to arrive at {arrival}, is running "
                f"late by {delay_minutes} minutes. We regret the inconvenience."
            )
            text_bn = (
                f"Jatrira onugroho kore shunben. Gari sankhya {train_no_spoken}, "
                f"{train_name}, nirdharito somoy {arrival} er {delay_minutes} "
                f"minute deri te cholche. Apnader oshubidhar jonno amra "
                f"antorik bhabe dukkhito."
            )

            # Generate TTS clips in parallel (capped at TTS_MAX_WORKERS)
            tts_jobs = [("hi", text_hi), ("en", text_en), ("bn", text_bn)]
            tts_paths = {}
            with ThreadPoolExecutor(max_workers=min(TTS_MAX_WORKERS, 3)) as pool:
                futures = {pool.submit(_cached_tts, txt, lang): lang
                           for lang, txt in tts_jobs}
                for fut in as_completed(futures):
                    tts_paths[futures[fut]] = fut.result()

            audio_hi = AudioSegment.from_mp3(tts_paths["hi"])
            audio_en = AudioSegment.from_mp3(tts_paths["en"])
            audio_bn = AudioSegment.from_mp3(tts_paths["bn"])

            final = chime + audio_hi + chime + audio_en + chime + audio_bn

            output_path = os.path.join(SCRIPT_DIR, f"Late_Announcement_{train_no}.wav")
            final.export(output_path, format="wav")

            # Free heavy objects and collect garbage
            del final, audio_hi, audio_en, audio_bn, chime
            gc.collect()

            logger.info(f"Late announcement generated: {output_path}")

            # Play and then auto-delete to save disk space
            if PLAY_FUNCTION:
                def _play_and_cleanup(path):
                    PLAY_FUNCTION(path)
                    try:
                        os.remove(path)
                        logger.debug(f"Cleaned up late announcement: {path}")
                    except OSError:
                        pass
                threading.Thread(
                    target=_play_and_cleanup, args=(output_path,), daemon=True
                ).start()

            return output_path

        except Exception as exc:
            logger.error(f"Late announcement generation failed: {exc}")
            return None

    def announce_custom_text(self, text: str) -> str | None:
        """
        Generate and play a custom text string dynamically using Hindi/English TTS.
        """
        if not text or not TTS_AVAILABLE or not PYDUB_AVAILABLE:
            return None
        
        try:
            # We'll generate English and Hindi in parallel
            tts_jobs = [("hi", text), ("en", text)]
            tts_paths = {}
            with ThreadPoolExecutor(max_workers=TTS_MAX_WORKERS) as pool:
                futures = {pool.submit(_cached_tts, txt, lang): lang for lang, txt in tts_jobs}
                for fut in as_completed(futures):
                    tts_paths[futures[fut]] = fut.result()
            
            # Load chime if available
            if os.path.exists(LATE_MP3):
                audio = AudioSegment.from_mp3(LATE_MP3)
                chime = audio[:1000]
                del audio
            else:
                chime = AudioSegment.silent(duration=1000)
            
            audio_hi = AudioSegment.from_mp3(tts_paths["hi"])
            audio_en = AudioSegment.from_mp3(tts_paths["en"])
            
            final = chime + audio_hi + chime + audio_en
            output_path = os.path.join(SCRIPT_DIR, "Custom_Announcement.wav")
            final.export(output_path, format="wav")
            
            del final, audio_hi, audio_en, chime
            gc.collect()
            logger.info("Custom announcement generated successfully.")
            
            if PLAY_FUNCTION:
                def _play_and_cleanup(path):
                    PLAY_FUNCTION(path)
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                threading.Thread(target=_play_and_cleanup, args=(output_path,), daemon=True).start()
                
            return output_path
            
        except Exception as exc:
            logger.error(f"Custom announcement generation failed: {exc}")
            return None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _compute_delay(self, train_data: dict) -> dict:
        arrival_str = train_data.get("Arrival_Time", "--")
        now = datetime.now()
        actual_str = now.strftime("%H:%M")

        if arrival_str in ("--", "N/A", ""):
            return {
                "delay_minutes": 0,
                "status": "originating",
                "message": (
                    f"🚆 Train {train_data['Train_Name']} ({train_data['Train_No']}) "
                    f"originating from this station. Platform {train_data['Platform_No']}."
                ),
            }

        try:
            scheduled = datetime.strptime(arrival_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
        except ValueError:
            try:
                scheduled = datetime.strptime(arrival_str, "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day
                )
            except ValueError:
                return {
                    "delay_minutes": 0,
                    "status": "unknown",
                    "message": f"Train {train_data['Train_No']} detected. Schedule parse error.",
                }

        diff_minutes = (now - scheduled).total_seconds() / 60.0
        delay = int(max(0, diff_minutes))

        if diff_minutes > 2:
            status = "delayed"
            msg = (
                f"🚆 Train {train_data['Train_Name']} ({train_data['Train_No']}) "
                f"is running late by {delay} minutes. "
                f"Scheduled: {arrival_str}, Actual: {actual_str}. "
                f"Platform {train_data['Platform_No']}."
            )
        elif diff_minutes < -2:
            early_by = abs(int(diff_minutes))
            status = "early"
            msg = (
                f"🚆 Train {train_data['Train_Name']} ({train_data['Train_No']}) "
                f"arriving {early_by} minutes early! "
                f"Scheduled: {arrival_str}. Platform {train_data['Platform_No']}."
            )
        else:
            status = "on_time"
            msg = (
                f"🚆 Train {train_data['Train_Name']} ({train_data['Train_No']}) "
                f"arriving on time at {actual_str}. "
                f"Platform {train_data['Platform_No']}."
            )

        return {"delay_minutes": delay, "status": status, "message": msg}

    def _ensure_skeleton(self):
        """Load skeleton audio parts into memory once."""
        if self._skeleton_ready:
            return True

        if not PYDUB_AVAILABLE or not os.path.exists(ANNOUNCEMENT_MP3):
            logger.warning("Cannot generate skeleton — pydub or project.mp3 missing.")
            return False

        with self._lock:
            if self._skeleton_ready:
                return True
            try:
                audio = AudioSegment.from_mp3(ANNOUNCEMENT_MP3)
                for start, end, part_num in SKELETON_PARTS:
                    self._skeleton_segments[part_num] = audio[start:end]
                del audio  # free the full file — keep only slices
                gc.collect()
                self._skeleton_ready = True
                logger.info("Audio skeleton loaded into memory from project.mp3")
                return True
            except Exception as exc:
                logger.error(f"Skeleton generation failed: {exc}")
                return False

    def _generate_audio(self, train_data: dict) -> str | None:
        """
        Generate the full 13-part announcement audio.

        Optimised for RPi 3B+:
          - TTS_MAX_WORKERS threads (2) instead of 6
          - Cached TTS results (no redundant gTTS calls)
          - Exported as WAV (no MP3 re-encode overhead)
          - gc.collect() after export
        """
        if not TTS_AVAILABLE or not PYDUB_AVAILABLE:
            logger.info(f"[SIM] Would generate audio for: "
                        f"{train_data['Train_No']} {train_data['Train_Name']}")
            return None

        if not self._ensure_skeleton():
            return None

        train_no = train_data["Train_No"]
        train_no_spoken = " ".join(list(str(train_no)))
        train_name = train_data["Train_Name"]
        platform = train_data.get("Platform_No", "1")

        output = os.path.join(SCRIPT_DIR, f"Announcement_{train_no}.wav")
        if os.path.exists(output):
            logger.info(f"Announcement already exists on disk: {output}")
            return output

        try:
            # Generate TTS clips in parallel (capped workers for RPi)
            tts_jobs = {
                2:  (f"{train_no_spoken}  {train_name}", 'en'),
                4:  (str(platform), 'en'),
                6:  (f"{train_no_spoken}  {train_name}", 'bn'),
                7:  (str(platform), 'bn'),
                10: (f"{train_no_spoken}  {train_name}", 'hi'),
                12: (str(platform), 'hi'),
            }

            tts_segments = {}
            with ThreadPoolExecutor(max_workers=TTS_MAX_WORKERS) as pool:
                futures = {
                    pool.submit(_cached_tts, text, lang): part_num
                    for part_num, (text, lang) in tts_jobs.items()
                }
                for fut in as_completed(futures):
                    part_num = futures[fut]
                    tts_segments[part_num] = AudioSegment.from_mp3(fut.result())

            # Merge all 13 parts in order from memory
            combined = AudioSegment.empty()
            for i in range(1, 14):
                if i in self._skeleton_segments:
                    combined += self._skeleton_segments[i]
                elif i in tts_segments:
                    combined += tts_segments[i]

            combined.export(output, format="wav")

            # Free heavy objects
            del combined, tts_segments
            gc.collect()

            logger.info(f"Announcement audio generated: {output}")
            return output

        except Exception as exc:
            logger.error(f"Audio generation failed: {exc}")
            return None
