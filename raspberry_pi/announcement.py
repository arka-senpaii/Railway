"""
Smart Railway Automation System — Announcement Engine
======================================================
Uses real Adra Junction timetable data (adrajndet.csv) and the
Indian Railways announcement style with:
  - 13-part audio skeleton extracted from project.mp3
  - TTS in English, Bengali, and Hindi via gTTS
  - Delay/on-time logic based on scheduled arrival times
  - Day-of-week filtering

Audio sequence:
  Part‑1  : English intro chime   ("May I have your attention please…")
  Part‑2  : [TTS‑EN] Train No + Name
  Part‑3  : "…is arriving on…"
  Part‑4  : [TTS‑EN] Platform No
  Part‑5  : Bengali intro         ("Jatrira onugroho kore shunben…")
  Part‑6  : [TTS‑BN] Train No + Name
  Part‑7  : [TTS‑BN] Platform No
  Part‑8  : "…platform e asche…"
  Part‑9  : Hindi intro           ("Kripya dhyan de…")
  Part‑10 : [TTS‑HI] Train No + Name
  Part‑11 : "…platform kramank…"
  Part‑12 : [TTS‑HI] Platform No
  Part‑13 : "…par aa rahi hai" + closing chime
"""

import os
import logging
import threading
from datetime import datetime

import pandas as pd

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

# Try multiple playback methods depending on OS
PLAY_FUNCTION = None

if platform.system() == "Linux":
    # On Raspberry Pi, ffplay (part of ffmpeg) is the most reliable way 
    # to output audio to the AV jack/HDMI without GUI overhead like playsound.
    def _play_linux(filepath):
        try:
            subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", filepath], check=True)
        except Exception as e:
            logger.warning(f"Audio playback failed on Pi (is ffmpeg installed?): {e}")
    PLAY_FUNCTION = _play_linux
else:
    # Windows / Mac fallback for local testing
    def _play_other(filepath):
        try:
            import os
            logger.info(f"Opening audio file with default OS player: {filepath}")
            if hasattr(os, 'startfile'):
                os.startfile(filepath)  # Windows
            else:
                subprocess.run(['open', filepath])  # Mac
        except Exception as e:
            logger.warning(f"Audio playback failed on fallback OS: {e}")
    PLAY_FUNCTION = _play_other


# ─── Audio skeleton timestamps from project.mp3 ─────────────────────────────
SKELETON_PARTS = [
    # (start_ms, end_ms, part_number)
    (0,     5221,  1),   # English intro chime
    (11213, 13438, 3),   # "is arriving on"
    (14437, 17342, 5),   # Bengali intro
    (23925, 25559, 8),   # "platform e asche"
    (25889, 28247, 9),   # Hindi intro "Kripya dhyan de"
    (34584, 36206, 11),  # "platform kramank"
    (36885, 38440, 13),  # "par aa rahi hai" + closing
]

# ─── Data paths (relative to script directory) ───────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TIMETABLE_CSV = os.path.join(SCRIPT_DIR, "adrajndet.csv")
SCHEDULE_CSV = os.path.join(SCRIPT_DIR, "adrajn.csv")
ANNOUNCEMENT_MP3 = os.path.join(SCRIPT_DIR, "project.mp3")
LATE_MP3 = os.path.join(SCRIPT_DIR, "late.mp3")


class TrainScheduleDB:
    """
    Loads the Adra Junction timetable CSVs and provides
    lookup by train number, with day-of-week filtering.
    """

    def __init__(self):
        self.detailed_df = None
        self.schedule_df = None
        self._load()

    def _load(self):
        """Load CSV files into pandas DataFrames."""
        try:
            if os.path.exists(TIMETABLE_CSV):
                self.detailed_df = pd.read_csv(TIMETABLE_CSV, dtype={"Train No": str})
                logger.info(f"Loaded {len(self.detailed_df)} rows from adrajndet.csv")
            else:
                logger.warning(f"Timetable file not found: {TIMETABLE_CSV}")

            if os.path.exists(SCHEDULE_CSV):
                self.schedule_df = pd.read_csv(SCHEDULE_CSV, dtype={"Train No": str})
                logger.info(f"Loaded {len(self.schedule_df)} rows from adrajn.csv")
            else:
                logger.warning(f"Schedule file not found: {SCHEDULE_CSV}")
        except Exception as exc:
            logger.error(f"Failed to load train data: {exc}")

    def lookup(self, train_no: str) -> dict | None:
        """
        Look up a train by number. Returns a dict with schedule details
        or None if not found.
        Handles train numbers with spaces (e.g. '2 2 8 1 2' matches '22812').
        """
        train_no = str(train_no).replace(" ", "").strip()

        # Try detailed timetable first (has platform, line type, departure)
        if self.detailed_df is not None:
            matches = self.detailed_df[
                self.detailed_df["Train No"].astype(str).str.replace(" ", "", regex=False).str.strip() == train_no
            ]
            if not matches.empty:
                row = matches.iloc[0]
                return {
                    "Train_No": str(row.get("Train No", train_no)).replace(" ", ""),
                    "Train_Name": str(row.get("Train Name", "Unknown")),
                    "From": str(row.get("From", "N/A")),
                    "To": str(row.get("To", "N/A")),
                    "Arrival_Time": str(row.get("Arrival Time", "--")),
                    "Departure_Time": str(row.get("Departure Time", "--")),
                    "Platform_No": str(row.get("Platform", "1")),
                    "Line_Type": str(row.get("Line Type", "Main Line")),
                    "Days": str(row.get("Days of Operation", "Daily")),
                }

        # Fallback to basic schedule
        if self.schedule_df is not None:
            matches = self.schedule_df[
                self.schedule_df["Train No"].astype(str).str.replace(" ", "", regex=False).str.strip() == train_no
            ]
            if not matches.empty:
                row = matches.iloc[0]
                return {
                    "Train_No": str(row.get("Train No", train_no)).replace(" ", ""),
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
        """Check if a train runs on the current day."""
        if not isinstance(days_str, str):
            return False
        if "Daily" in days_str:
            return True
        today_short = datetime.now().strftime("%a")  # "Mon", "Tue", …
        return today_short in days_str

    def get_todays_trains(self) -> list[dict]:
        """Return all trains that run today, sorted by arrival time."""
        results = []
        df = self.detailed_df if self.detailed_df is not None else self.schedule_df
        if df is None:
            return results

        for _, row in df.iterrows():
            days = str(row.get("Days of Operation", ""))
            if self.runs_today(days):
                results.append({
                    "Train_No": str(row.get("Train No", "")).replace(" ", ""),
                    "Train_Name": str(row.get("Train Name", "")),
                    "Arrival_Time": str(row.get("Arrival Time", "--")),
                    "Platform_No": str(row.get("Platform", row.get("Platform_No", "1"))),
                })

        return results


class AnnouncementEngine:
    """
    Generates Indian-Railways-style announcements in 3 languages
    (English → Bengali → Hindi) using audio skeletons from project.mp3
    and gTTS for dynamic parts (train number, name, platform).
    """

    def __init__(self, firebase_client=None, schedule_db: TrainScheduleDB = None):
        self.fb = firebase_client
        self.schedule_db = schedule_db or TrainScheduleDB()
        self._skeleton_generated = False
        self._lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────────────

    def generate_and_play(self, train_id: str) -> dict:
        """
        Full pipeline: look up train → compute delay → generate audio → play.

        Parameters
        ----------
        train_id : str
            The scanned train number (e.g. "12282").

        Returns
        -------
        dict  with keys: train_data, delay_minutes, status, message, audio_file
        """
        train_data = self.schedule_db.lookup(train_id)

        if train_data is None:
            msg = f"Train {train_id} not found in timetable."
            logger.warning(msg)
            return {"train_data": None, "delay_minutes": 0,
                    "status": "unknown", "message": msg, "audio_file": None}

        # Compute delay
        delay_info = self._compute_delay(train_data)

        # Generate announcement audio
        audio_file = self._generate_audio(train_data)
        
        # Fallback to default file if generation failed
        if not audio_file or not os.path.exists(audio_file):
            logger.warning("Audio generation failed or unavailable. Falling back to default project.mp3.")
            if os.path.exists(ANNOUNCEMENT_MP3):
                audio_file = ANNOUNCEMENT_MP3

        # Play in background
        if audio_file and PLAY_FUNCTION:
            threading.Thread(
                target=PLAY_FUNCTION, args=(audio_file,), daemon=True
            ).start()

        # Update Firebase gate status (train approaching → gate closing)
        if self.fb:
            self.fb.update_gate_status("CLOSED")

        return {
            "train_data": train_data,
            **delay_info,
            "audio_file": audio_file,
        }

    def generate_late_announcement(self, train_data: dict, delay_minutes: int) -> str | None:
        """
        Generate a separate delay announcement (chime → Hindi → English → Bengali)
        using late.mp3 as the chime source, matching the pattern from
        announcement_logic.py in the Train folder.

        Returns the path to the generated WAV file, or None on failure.
        """
        if not TTS_AVAILABLE or not PYDUB_AVAILABLE:
            logger.warning("TTS or pydub not available — skipping late announcement.")
            return None

        if delay_minutes <= 0:
            return None

        try:
            # Load chime from late.mp3
            if os.path.exists(LATE_MP3):
                audio = AudioSegment.from_mp3(LATE_MP3)
                chime = audio[:1000]  # first 1 second
            else:
                chime = AudioSegment.silent(duration=1000)

            train_no = train_data["Train_No"]
            train_no_spoken = " ".join(list(str(train_no)))
            train_name = train_data["Train_Name"]
            arrival = train_data.get("Arrival_Time", "N/A")

            # Hindi
            text_hi = (
                f"Yatri kripya dhyan de. Gadi sankhya {train_no_spoken}, {train_name}, "
                f"apne nirdharit samay {arrival} se {delay_minutes} minute "
                f"deri se chal rahi hai. Asuvidha ke liye hume khed hai."
            )
            hi_path = os.path.join(SCRIPT_DIR, "temp_hi.mp3")
            gTTS(text=text_hi, lang='hi', tld='co.in', slow=False).save(hi_path)
            audio_hi = AudioSegment.from_mp3(hi_path)

            # English
            text_en = (
                f"May I have your attention please. Train number {train_no_spoken}, "
                f"{train_name}, scheduled to arrive at {arrival}, is running "
                f"late by {delay_minutes} minutes. We regret the inconvenience."
            )
            en_path = os.path.join(SCRIPT_DIR, "temp_en.mp3")
            gTTS(text=text_en, lang='en', tld='co.in', slow=False).save(en_path)
            audio_en = AudioSegment.from_mp3(en_path)

            # Bengali
            text_bn = (
                f"Jatrira onugroho kore shunben. Gari sankhya {train_no_spoken}, "
                f"{train_name}, nirdharito somoy {arrival} er {delay_minutes} "
                f"minute deri te cholche. Apnader oshubidhar jonno amra "
                f"antorik bhabe dukkhito."
            )
            bn_path = os.path.join(SCRIPT_DIR, "temp_bn.mp3")
            gTTS(text=text_bn, lang='bn', tld='co.in', slow=False).save(bn_path)
            audio_bn = AudioSegment.from_mp3(bn_path)

            # Combine: Chime → Hindi → Chime → English → Chime → Bengali
            final = chime + audio_hi + chime + audio_en + chime + audio_bn

            output_path = os.path.join(SCRIPT_DIR, f"Late_Announcement_{train_no}.wav")
            final.export(output_path, format="wav")

            # Cleanup temp files
            for f in [hi_path, en_path, bn_path]:
                if os.path.exists(f):
                    os.remove(f)

            logger.info(f"Late announcement generated: {output_path}")
            return output_path

        except Exception as exc:
            logger.error(f"Late announcement generation failed: {exc}")
            return None

    # ── Internal ─────────────────────────────────────────────────────────────

    def _compute_delay(self, train_data: dict) -> dict:
        """Compare scheduled arrival with current time to determine delay."""
        arrival_str = train_data.get("Arrival_Time", "--")
        now = datetime.now()
        actual_str = now.strftime("%H:%M")

        if arrival_str in ("--", "N/A", ""):
            # Origin station — no arrival, only departure
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
        """Extract static audio parts from project.mp3 if not done yet."""
        if self._skeleton_generated:
            return True

        if not PYDUB_AVAILABLE or not os.path.exists(ANNOUNCEMENT_MP3):
            logger.warning("Cannot generate skeleton — pydub or project.mp3 missing.")
            return False

        with self._lock:
            if self._skeleton_generated:
                return True

            try:
                audio = AudioSegment.from_mp3(ANNOUNCEMENT_MP3)
                for start, end, part_num in SKELETON_PARTS:
                    part_path = os.path.join(SCRIPT_DIR, f"Part-{part_num}.mp3")
                    segment = audio[start:end]
                    segment.export(part_path, format="mp3")

                self._skeleton_generated = True
                logger.info("Audio skeleton generated from project.mp3")
                return True
            except Exception as exc:
                logger.error(f"Skeleton generation failed: {exc}")
                return False

    def _generate_audio(self, train_data: dict) -> str | None:
        """
        Generate the full 13-part announcement audio for a train.
        Returns the output file path or None.
        """
        if not TTS_AVAILABLE or not PYDUB_AVAILABLE:
            logger.info("[SIM] Would generate audio for: "
                        f"{train_data['Train_No']} {train_data['Train_Name']}")
            return None

        if not self._ensure_skeleton():
            return None

        train_no = train_data["Train_No"]
        train_no_spoken = " ".join(list(str(train_no)))
        train_name = train_data["Train_Name"]
        platform = train_data.get("Platform_No", "1")

        try:
            # Part‑2: English TTS — Train No + Name
            p2 = os.path.join(SCRIPT_DIR, "Part-2.mp3")
            gTTS(text=f"{train_no_spoken}  {train_name}", lang='en', slow=False).save(p2)

            # Part‑4: English TTS — Platform No
            p4 = os.path.join(SCRIPT_DIR, "Part-4.mp3")
            gTTS(text=str(platform), lang='en', slow=False).save(p4)

            # Part‑6: Bengali TTS — Train No + Name
            p6 = os.path.join(SCRIPT_DIR, "Part-6.mp3")
            gTTS(text=f"{train_no_spoken}  {train_name}", lang='bn', slow=False).save(p6)

            # Part‑7: Bengali TTS — Platform No
            p7 = os.path.join(SCRIPT_DIR, "Part-7.mp3")
            gTTS(text=str(platform), lang='bn', slow=False).save(p7)

            # Part‑10: Hindi TTS — Train No + Name
            p10 = os.path.join(SCRIPT_DIR, "Part-10.mp3")
            gTTS(text=f"{train_no_spoken}  {train_name}", lang='hi', slow=False).save(p10)

            # Part‑12: Hindi TTS — Platform No
            p12 = os.path.join(SCRIPT_DIR, "Part-12.mp3")
            gTTS(text=str(platform), lang='hi', slow=False).save(p12)

            # Merge all 13 parts in order
            combined = AudioSegment.empty()
            for i in range(1, 14):
                part_path = os.path.join(SCRIPT_DIR, f"Part-{i}.mp3")
                if os.path.exists(part_path):
                    combined += AudioSegment.from_mp3(part_path)

            output = os.path.join(SCRIPT_DIR, f"Announcement_{train_no}.mp3")
            combined.export(output, format="mp3")

            # Clean up dynamic TTS parts
            for p in [p2, p4, p6, p7, p10, p12]:
                if os.path.exists(p):
                    os.remove(p)

            logger.info(f"Announcement audio generated: {output}")
            return output

        except Exception as exc:
            logger.error(f"Audio generation failed: {exc}")
            return None
