"""
Quick script to update Firebase with the exact gate/manual_mode data.
This sets the root-level fields without touching any other nodes.
"""

import firebase_admin
from firebase_admin import credentials, db

CREDENTIALS_FILE = "railway-c8909-firebase-adminsdk-fbsvc-37c2f1e82f.json"
DATABASE_URL = "https://railway-c8909-default-rtdb.firebaseio.com"

def main():
    try:
        cred = credentials.Certificate(CREDENTIALS_FILE)
        firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})
    except ValueError:
        pass  # App already initialized

    # Exact data to write — nothing else will be changed
    data = {
        "current_gate_status": "OPEN",
        "gate_status": "CLOSED",
        "manual_mode": 1
    }

    # Use update() so it only writes these keys without deleting other root nodes
    db.reference("/").update(data)
    print("✅ Firebase updated successfully with:")
    for k, v in data.items():
        print(f"   {k}: {v}")

if __name__ == "__main__":
    main()
