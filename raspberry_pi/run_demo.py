"""
Quick demo seed — pushes the 3-field structure to Firebase.
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

    print("Sending initial data to Firebase...")

    data = {
        "current_gate_status": "OPEN",
        "gate_status": "CLOSED",
        "manual_mode": 1
    }

    db.reference("/").update(data)
    print("✅ Firebase initialised with:")
    for k, v in data.items():
        print(f"   {k}: {v}")

if __name__ == "__main__":
    main()
