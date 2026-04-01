"""
Test script — generate an announcement for a train.
Usage: python test_announcement.py [train_no]
Default: 22812 (Rajdhani Express via Adra)
"""

import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

from announcement import AnnouncementEngine, TrainScheduleDB

train_id = sys.argv[1] if len(sys.argv) > 1 else "22812"

print(f"\n{'='*60}")
print(f"  Testing announcement for Train No: {train_id}")
print(f"{'='*60}\n")

schedule_db = TrainScheduleDB()

# Test lookup
data = schedule_db.lookup(train_id)
if data:
    print(f"✅ Train found:")
    for k, v in data.items():
        print(f"   {k}: {v}")
else:
    print(f"❌ Train {train_id} NOT found in timetable!")
    print("   Check your CSV files.")
    sys.exit(1)

# Generate announcement (no Firebase needed)
print(f"\n🔊 Generating announcement...")
engine = AnnouncementEngine(firebase_client=None, schedule_db=schedule_db)
result = engine.generate_and_play(train_id)

print(f"\n📋 Result:")
print(f"   Status:  {result.get('status')}")
print(f"   Delay:   {result.get('delay_minutes')} min")
print(f"   Message: {result.get('message')}")
print(f"   Audio:   {result.get('audio_file', 'None (TTS/pydub not available)')}")
print()
