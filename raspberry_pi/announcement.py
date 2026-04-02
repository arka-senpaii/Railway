"""
Smart Railway Automation System — Announcement Engine (RPi 3B+ Optimised)
==========================================================================
Reference: ark.py (original desktop Station Master GUI)

Audio pipeline mirrors ark.py exactly:
  • 13-part skeleton sliced once from project.mp3 (kept in memory)
  • Parts 2,4,6,7,10,12 → gTTS (en / bn / hi) — disk-cached by content hash
  • All 13 parts merged in order → WAV output played via ffplay

RPi 3B+ (1 GB RAM) hard limits applied:
  • TTS runs on a shared ThreadPoolExecutor capped at 2 workers
  • Disk cache limited to MAX_TTS_CACHE_FILES (LRU eviction)
  • Pre-generation limited to next PRE_GEN_LOOKAHEAD upcoming trains
  • gc.collect() called after every heavy audio operation
  • Late-announcement and custom-announcement WAVs self-delete after play
  • Skeleton slices are reused across announcements — loaded exactly once
"""

import os
import gc
import csv
import time
import logging
import hashlib
import threading
import subprocess
import platform
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import MAX_TTS_CACHE_FILES, PRE_GEN_LOOKAHEAD, TTS_MAX_WORKERS

logger = logging.getLogger(__name__)

# ─── Optional audio deps (graceful degradation) ──────────────────────────────
try:
    from gtts import gTTS
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    logger.warning("gTTS not installed — TTS disabled. Run: pip install gtts")

try:
    import audioop          # noqa: F401  (needed by pydub on Python < 3.13)
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
    # Point pydub at imageio-ffmpeg's bundled binary if available (avoids
    # having to install system ffmpeg on development machines)
    try:
        import imageio_ffmpeg
        AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("pydub not installed — audio merging disabled. Run: pip install pydub")

# ─── Audio playback ───────────────────────────────────────────────────────────
# On the Pi we always use ffplay (ships with ffmpeg package) because it handles
# WAV/MP3 without any Python audio driver.  On dev machines fall back to the OS
# default handler.

def _play(filepath: str) -> None:
    """Play an audio file.  Pi: ffplay (zero overhead).  Other: OS default."""
    if platform.system() == "Linux":
        try:
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath],
                check=True,
            )
        except FileNotFoundError:
            logger.error("ffplay not found – install ffmpeg:  sudo apt install ffmpeg")
        except subprocess.CalledProcessError as exc:
            logger.warning(f"ffplay returned non-zero exit: {exc}")
    else:
        # Windows / macOS development
        try:
            if hasattr(os, "startfile"):
                os.startfile(filepath)          # Windows
            else:
                subprocess.run(["open", filepath])  # macOS
        except Exception as exc:
            logger.warning(f"Audio playback failed: {exc}")

# ─── Skeleton timestamps (ms) — identical to ark.py ──────────────────────────
#
# Part layout (1-indexed, matching ark.py Part-N.mp3):
#   1  → intro chime (en)
#   2  → [TTS] train number + name in English
#   3  → "is arriving on"
#   4  → [TTS] platform number in English
#   5  → Bengali intro phrase
#   6  → [TTS] train number + name in Bengali
#   7  → [TTS] platform number in Bengali
#   8  → "platform e asche" (bn)
#   9  → Hindi intro phrase
#  10  → [TTS] train number + name in Hindi
#  11  → "platform kramank" (hi)
#  12  → [TTS] platform number in Hindi
#  13  → "par aa rahi hai" + closing sting

SKELETON_PARTS = [
    (0,     5221,  1),
    (11213, 13438, 3),
    (14437, 17342, 5),
    (23925, 25559, 8),
    (25889, 28247, 9),
    (34584, 36206, 11),
    (36885, 38440, 13),
]

# ─── Paths ────────────────────────────────────────────────────────────────────
_DIR          = os.path.dirname(os.path.abspath(__file__))
TIMETABLE_CSV = os.path.join(_DIR, "adrajndet.csv")
SCHEDULE_CSV  = os.path.join(_DIR, "adrajn.csv")
PROJECT_MP3   = os.path.join(_DIR, "project.mp3")
LATE_MP3      = os.path.join(_DIR, "late.mp3")
TTS_CACHE_DIR = os.path.join(_DIR, ".tts_cache")


# ─── TTS disk cache (LRU eviction) ───────────────────────────────────────────

def _evict_cache() -> None:
    """Delete oldest TTS cache files when count exceeds MAX_TTS_CACHE_FILES."""
    if not os.path.isdir(TTS_CACHE_DIR):
        return
    files = [
        (os.path.getmtime(fp), fp)
        for f in os.listdir(TTS_CACHE_DIR)
        if f.endswith(".mp3")
        for fp in (os.path.join(TTS_CACHE_DIR, f),)
        if os.path.isfile(fp)
    ]
    if len(files) <= MAX_TTS_CACHE_FILES:
        return
    files.sort()
    for _, fp in files[: len(files) - MAX_TTS_CACHE_FILES]:
        try:
            os.remove(fp)
        except OSError:
            pass


def _cached_tts(text: str, lang: str, tld: str = "co.in") -> str:
    """Generate TTS via gTTS and cache it on disk keyed by content hash.

    The `tld='co.in'` parameter gives the Indian-accented English voice,
    matching the ark.py reference behaviour.
    """
    os.makedirs(TTS_CACHE_DIR, exist_ok=True)
    key  = hashlib.md5(f"{text}|{lang}|{tld}".encode()).hexdigest()
    path = os.path.join(TTS_CACHE_DIR, f"{key}.mp3")
    if os.path.exists(path):
        os.utime(path)   # bump mtime so LRU eviction keeps it
        return path
    gTTS(text=text, lang=lang, tld=tld, slow=False).save(path)
    _evict_cache()
    return path


# ═════════════════════════════════════════════════════════════════════════════
#  Train Schedule DB
# ═════════════════════════════════════════════════════════════════════════════

class TrainScheduleDB:
    """Loads Adra Junction CSVs once and provides fast in-memory lookups."""

    def __init__(self) -> None:
        self._detailed: list[dict] = []
        self._schedule: list[dict] = []
        self._load()

    # ── Loading ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        for path, attr in ((TIMETABLE_CSV, "_detailed"), (SCHEDULE_CSV, "_schedule")):
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as fh:
                        rows = list(csv.DictReader(fh))
                    setattr(self, attr, rows)
                    logger.info(f"Loaded {len(rows)} rows from {os.path.basename(path)}")
                except Exception as exc:
                    logger.error(f"Cannot load {path}: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _norm(s: str) -> str:
        return str(s).replace(" ", "").strip()

    def _row_to_dict(self, row: dict) -> dict:
        """Normalise a CSV row into a canonical train dict."""
        return {
            "Train_No":       self._norm(row.get("Train No", "")),
            "Train_Name":     str(row.get("Train Name", "Unknown")),
            "From":           str(row.get("From", "N/A")),
            "To":             str(row.get("To",   "N/A")),
            "Via":            str(row.get("Via",  "N/A")),
            "Arrival_Time":   str(row.get("Arrival Time",   "--")),
            "Departure_Time": str(row.get("Departure Time", "--")),
            "Platform_No":    str(row.get("Platform", row.get("Platform_No", "1"))),
            "Line_Type":      str(row.get("Line Type", "Main Line")),
            "Days":           str(row.get("Days of Operation", "Daily")),
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def lookup(self, train_no: str) -> dict | None:
        """Find a train by number (spaces stripped from both sides)."""
        target = self._norm(train_no)
        for row in self._detailed or self._schedule:
            if self._norm(row.get("Train No", "")) == target:
                return self._row_to_dict(row)
        return None

    def get_all_trains(self) -> list[dict]:
        source = self._detailed or self._schedule
        return [self._row_to_dict(r) for r in source]

    def get_todays_trains(self) -> list[dict]:
        today = datetime.now().strftime("%a")   # "Mon", "Tue", …
        return [
            t for t in self.get_all_trains()
            if "Daily" in t["Days"] or today in t["Days"]
        ]

    def get_upcoming_trains(self, limit: int = PRE_GEN_LOOKAHEAD) -> list[dict]:
        """Return the next `limit` trains arriving at or after now (±10 min)."""
        now_mins = datetime.now().hour * 60 + datetime.now().minute
        upcoming = []
        for t in self.get_todays_trains():
            arr = t["Arrival_Time"]
            if arr in ("--", "N/A", ""):
                continue
            try:
                h, m   = map(int, arr.split(":"))
                t_mins = h * 60 + m
                if t_mins >= now_mins - 10:
                    upcoming.append((t_mins, t))
            except (ValueError, IndexError):
                pass
        upcoming.sort(key=lambda x: x[0])
        return [t for _, t in upcoming[:limit]]


# ═════════════════════════════════════════════════════════════════════════════
#  Announcement Engine (RPi 3B+ Optimised)
# ═════════════════════════════════════════════════════════════════════════════

class AnnouncementEngine:
    """
    Generates Indian-Railways-style 3-language announcements.

    Audio pipeline (mirrors ark.py exactly):
      1. Slice project.mp3 into skeleton parts once on first call.
      2. Generate 6 TTS clips (en/bn/hi × train-name / platform) in parallel.
      3. Merge all 13 parts in order and export to WAV.
      4. Play via ffplay in a daemon thread so the caller returns immediately.

    RPi 3B+ limits:
      • ThreadPoolExecutor: max 2 workers (TTS_MAX_WORKERS)
      • TTS cache on disk: max 50 files (LRU eviction)
      • Pre-generate only PRE_GEN_LOOKAHEAD upcoming trains
      • gc.collect() after every heavy AudioSegment operation
      • Temp WAV files (late / custom) auto-deleted after playback
    """

    def __init__(self, firebase_client=None, schedule_db: TrainScheduleDB | None = None):
        self.fb            = firebase_client
        self.schedule_db   = schedule_db or TrainScheduleDB()
        self._skeleton: dict[int, "AudioSegment"] = {}
        self._skeleton_ok  = False
        self._skeleton_lk  = threading.Lock()
        self._pregenerated: dict[str, str] = {}
        # Shared thread pool — capped for 1 GB RAM
        self._pool = ThreadPoolExecutor(max_workers=TTS_MAX_WORKERS,
                                        thread_name_prefix="tts")

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_and_play(self, train_id: str) -> dict:
        """Full pipeline: lookup → compute delay → generate audio → play."""
        train_data = self.schedule_db.lookup(train_id)
        if train_data is None:
            msg = f"Train {train_id} not found in timetable."
            logger.warning(msg)
            return {"train_data": None, "delay_minutes": 0,
                    "status": "unknown",  "message": msg, "audio_file": None}

        delay_info = self._compute_delay(train_data)
        train_no   = self.schedule_db._norm(train_id)

        # Use pre-generated file if available
        audio_file = self._pregenerated.get(train_no)
        if audio_file and os.path.exists(audio_file):
            logger.info(f"Using pre-generated announcement for {train_no}")
        else:
            audio_file = self._generate_audio(train_data)

        # Final fallback: raw project.mp3
        if not audio_file or not os.path.exists(audio_file):
            logger.warning("Audio generation failed — falling back to project.mp3")
            if os.path.exists(PROJECT_MP3):
                audio_file = PROJECT_MP3

        # Play in background so gate/signal logic is not blocked
        if audio_file:
            threading.Thread(target=_play, args=(audio_file,), daemon=True).start()

        return {
            "train_data": train_data,
            "audio_file": audio_file,
            **delay_info,
        }

    def pregenerate_todays_announcements(self) -> None:
        """Pre-generate the next few upcoming announcements in a background thread."""
        def _worker():
            upcoming = self.schedule_db.get_upcoming_trains(PRE_GEN_LOOKAHEAD)
            if not upcoming:
                logger.info("No upcoming trains — skipping pre-generation.")
                return
            logger.info(f"Pre-generating {len(upcoming)} announcement(s) …")
            for i, train in enumerate(upcoming, 1):
                no = train["Train_No"]
                if no in self._pregenerated:
                    continue
                data = self.schedule_db.lookup(no)
                if data:
                    path = self._generate_audio(data)
                    if path:
                        self._pregenerated[no] = path
                        logger.info(f"  [{i}/{len(upcoming)}] Pre-generated: {no}")
            gc.collect()
            logger.info(f"Pre-generation done — {len(self._pregenerated)} file(s) ready.")

        threading.Thread(target=_worker, daemon=True).start()

    def generate_late_announcement(self, train_data: dict, delay_minutes: int) -> str | None:
        """Generate and auto-play a delay announcement, then delete the file."""
        if not TTS_AVAILABLE or not PYDUB_AVAILABLE or delay_minutes <= 0:
            return None
        try:
            chime = self._load_chime()
            no_spoken  = " ".join(list(train_data["Train_No"]))
            name       = train_data["Train_Name"]
            arrival    = train_data.get("Arrival_Time", "N/A")

            texts = {
                "hi": (
                    f"Yatri kripya dhyan de. Gadi sankhya {no_spoken}, {name}, "
                    f"apne nirdharit samay {arrival} se {delay_minutes} minute "
                    f"deri se chal rahi hai. Asuvidha ke liye hume khed hai."
                ),
                "en": (
                    f"May I have your attention please. Train number {no_spoken}, "
                    f"{name}, scheduled to arrive at {arrival}, is running "
                    f"late by {delay_minutes} minutes. We regret the inconvenience."
                ),
                "bn": (
                    f"Jatrira onugroho kore shunben. Gari sankhya {no_spoken}, "
                    f"{name}, nirdharito somoy {arrival} er {delay_minutes} "
                    f"minute deri te cholche. Apnader oshubidhar jonno amra "
                    f"antorik bhabe dukkhito."
                ),
            }
            tts_paths = self._tts_parallel(texts)

            seg_hi = AudioSegment.from_mp3(tts_paths["hi"])
            seg_en = AudioSegment.from_mp3(tts_paths["en"])
            seg_bn = AudioSegment.from_mp3(tts_paths["bn"])
            final  = chime + seg_hi + chime + seg_en + chime + seg_bn

            out = os.path.join(_DIR, f"Late_{train_data['Train_No']}.wav")
            final.export(out, format="wav")
            del final, seg_hi, seg_en, seg_bn, chime
            gc.collect()

            def _play_and_delete(p):
                _play(p)
                try:
                    os.remove(p)
                except OSError:
                    pass

            threading.Thread(target=_play_and_delete, args=(out,), daemon=True).start()
            return out

        except Exception as exc:
            logger.error(f"Late announcement failed: {exc}")
            return None

    def announce_custom_text(self, text: str) -> str | None:
        """Speak arbitrary custom text (en + hi) and auto-delete the WAV."""
        if not text or not TTS_AVAILABLE or not PYDUB_AVAILABLE:
            return None
        try:
            chime = self._load_chime()
            tts_paths = self._tts_parallel({"en": text, "hi": text})
            seg_en = AudioSegment.from_mp3(tts_paths["en"])
            seg_hi = AudioSegment.from_mp3(tts_paths["hi"])
            final  = chime + seg_en + chime + seg_hi
            out    = os.path.join(_DIR, "Custom_Announcement.wav")
            final.export(out, format="wav")
            del final, seg_en, seg_hi, chime
            gc.collect()

            def _play_and_delete(p):
                _play(p)
                try:
                    os.remove(p)
                except OSError:
                    pass

            threading.Thread(target=_play_and_delete, args=(out,), daemon=True).start()
            return out

        except Exception as exc:
            logger.error(f"Custom announcement failed: {exc}")
            return None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _load_chime(self) -> "AudioSegment":
        if PYDUB_AVAILABLE and os.path.exists(LATE_MP3):
            audio = AudioSegment.from_mp3(LATE_MP3)
            chime = audio[:1000]
            del audio
            return chime
        return AudioSegment.silent(duration=1000)

    def _tts_parallel(self, lang_text_map: dict[str, str]) -> dict[str, str]:
        """Generate multiple TTS clips in parallel using the shared pool."""
        futures = {
            self._pool.submit(_cached_tts, text, lang): lang
            for lang, text in lang_text_map.items()
        }
        results = {}
        for fut in as_completed(futures):
            lang = futures[fut]
            try:
                results[lang] = fut.result()
            except Exception as exc:
                logger.error(f"TTS failed for lang={lang}: {exc}")
        return results

    def _ensure_skeleton(self) -> bool:
        """Load skeleton slices from project.mp3 exactly once (thread-safe)."""
        if self._skeleton_ok:
            return True
        if not PYDUB_AVAILABLE or not os.path.exists(PROJECT_MP3):
            logger.warning("Cannot build skeleton — pydub or project.mp3 missing.")
            return False
        with self._skeleton_lk:
            if self._skeleton_ok:
                return True
            try:
                audio = AudioSegment.from_mp3(PROJECT_MP3)
                for start, end, part in SKELETON_PARTS:
                    self._skeleton[part] = audio[start:end]
                del audio   # free full file; keep only slices
                gc.collect()
                self._skeleton_ok = True
                logger.info("Audio skeleton loaded from project.mp3")
                return True
            except Exception as exc:
                logger.error(f"Skeleton load failed: {exc}")
                return False

    def _generate_audio(self, train_data: dict) -> str | None:
        """
        Build the full 13-part announcement (mirrors ark.py generate_announcement_audio).

        Parts breakdown:
          Skeleton parts (from project.mp3 slices): 1, 3, 5, 8, 9, 11, 13
          TTS parts (generated per train):           2, 4, 6, 7, 10, 12
        """
        if not TTS_AVAILABLE or not PYDUB_AVAILABLE:
            logger.info(f"[SIM] Would generate audio for {train_data['Train_No']}")
            return None
        if not self._ensure_skeleton():
            return None

        no         = train_data["Train_No"]
        no_spoken  = " ".join(list(str(no)))   # "12282" → "1 2 2 8 2"
        name       = train_data["Train_Name"]
        platform   = train_data.get("Platform_No", "1")
        out        = os.path.join(_DIR, f"Announcement_{no}.wav")

        if os.path.exists(out):
            logger.info(f"Announcement already cached on disk: {out}")
            return out

        try:
            # Generate 6 TTS clips in parallel (capped at TTS_MAX_WORKERS=2)
            # Matching ark.py Part-2, 4, 6, 7, 10, 12 exactly
            tts_jobs: dict[int, tuple[str, str]] = {
                2:  (f"{no_spoken}  {name}", "en"),
                4:  (platform,               "en"),
                6:  (f"{no_spoken}  {name}", "bn"),
                7:  (platform,               "bn"),
                10: (f"{no_spoken}  {name}", "hi"),
                12: (platform,               "hi"),
            }

            # Submit all jobs to the shared pool
            futures_map: dict = {}
            for part_num, (text, lang) in tts_jobs.items():
                futures_map[self._pool.submit(_cached_tts, text, lang)] = part_num

            tts_segs: dict[int, "AudioSegment"] = {}
            for fut in as_completed(futures_map):
                part_num = futures_map[fut]
                try:
                    tts_segs[part_num] = AudioSegment.from_mp3(fut.result())
                except Exception as exc:
                    logger.error(f"Part {part_num} TTS failed: {exc}")

            # Merge parts 1–13 in order (skeleton where available, TTS otherwise)
            combined = AudioSegment.empty()
            for i in range(1, 14):
                if i in self._skeleton:
                    combined += self._skeleton[i]
                elif i in tts_segs:
                    combined += tts_segs[i]
                # else: part missing → skip silently (graceful degradation)

            combined.export(out, format="wav")
            del combined, tts_segs
            gc.collect()

            logger.info(f"Announcement written: {out}")
            return out

        except Exception as exc:
            logger.error(f"Audio generation failed for {no}: {exc}")
            return None

    def _compute_delay(self, train_data: dict) -> dict:
        arrival_str = train_data.get("Arrival_Time", "--")
        now         = datetime.now()

        if arrival_str in ("--", "N/A", ""):
            return {
                "delay_minutes": 0,
                "status": "originating",
                "message": (
                    f"🚆 {train_data['Train_Name']} ({train_data['Train_No']}) "
                    f"originates here. Platform {train_data['Platform_No']}."
                ),
            }

        try:
            sched = datetime.strptime(arrival_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
        except ValueError:
            try:
                sched = datetime.strptime(arrival_str, "%H:%M:%S").replace(
                    year=now.year, month=now.month, day=now.day
                )
            except ValueError:
                return {
                    "delay_minutes": 0,
                    "status": "unknown",
                    "message": f"Train {train_data['Train_No']} detected (schedule parse error).",
                }

        diff = (now - sched).total_seconds() / 60.0
        delay = int(max(0, diff))

        if diff > 2:
            return {
                "delay_minutes": delay,
                "status": "delayed",
                "message": (
                    f"🚆 {train_data['Train_Name']} ({train_data['Train_No']}) "
                    f"running {delay} min late. Scheduled: {arrival_str}. "
                    f"Platform {train_data['Platform_No']}."
                ),
            }
        if diff < -2:
            early = abs(int(diff))
            return {
                "delay_minutes": 0,
                "status": "early",
                "message": (
                    f"🚆 {train_data['Train_Name']} ({train_data['Train_No']}) "
                    f"arriving {early} min early! Platform {train_data['Platform_No']}."
                ),
            }
        return {
            "delay_minutes": 0,
            "status": "on_time",
            "message": (
                f"🚆 {train_data['Train_Name']} ({train_data['Train_No']}) "
                f"on time at {now.strftime('%H:%M')}. Platform {train_data['Platform_No']}."
            ),
        }
