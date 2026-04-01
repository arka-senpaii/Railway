import os
import time
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db

# Configuration
CREDENTIALS_FILE = "railway-c8909-firebase-adminsdk-fbsvc-37c2f1e82f.json"
DATABASE_URL = "https://railway-c8909-default-rtdb.firebaseio.com"
SCHEDULE_CSV = "adrajn.csv"

def main():
    try:
        cred = credentials.Certificate(CREDENTIALS_FILE)
        firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})
    except ValueError:
        pass # App already initialized

    print("Seeding Firebase Database with schedules from CSV...")
    
    if not os.path.exists(SCHEDULE_CSV):
        print(f"Error: {SCHEDULE_CSV} not found in this directory.")
        return

    df = pd.read_csv(SCHEDULE_CSV, dtype=str)
    schedules = {}
    
    for _, row in df.iterrows():
        train_no = str(row.get("Train No", "")).strip()
        if not train_no:
            continue
            
        schedules[train_no] = {
            "name": str(row.get("Train Name", "Unknown")),
            "scheduled_arrival": str(row.get("Arrival Time", "--")),
            "platform": str(row.get("Platform", "1")), # Default to 1 if not in this CSV
            "days_of_operation": str(row.get("Days of Operation", "Daily"))
        }

    # Push to Firebase
    db.reference("/schedules").set(schedules)
    print(f"✅ Successfully seeded {len(schedules)} trains into Firebase RTDB!")

if __name__ == "__main__":
    main()
