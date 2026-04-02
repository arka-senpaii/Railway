# Firebase Setup Guide — Smart Railway Automation System

## 1. Create a Firebase Project

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Click **"Add project"** → enter name (e.g. `SmartRailway`)
3. Disable Google Analytics (optional for hackathon) → **Create Project**

---

## 2. Enable Realtime Database

1. In the left sidebar → **Build** → **Realtime Database**
2. Click **"Create Database"**
3. Choose location (e.g. `us-central1`)
4. Select **"Start in test mode"** (allows open read/write for 30 days)
5. Click **Enable**

---

## 3. Get Service Account Key (for Raspberry Pi)

1. Click the ⚙️ gear icon → **Project settings**
2. Go to **"Service accounts"** tab
3. Click **"Generate new private key"** → **Generate key**
4. A JSON file downloads (e.g. `railway-xxxxx-firebase-adminsdk-xxxxx.json`)
5. Rename it to **`serviceAccountKey.json`**
6. Copy it to `SmartRailway/raspberry_pi/serviceAccountKey.json`

---

## 4. Get Web API Config (for Dashboard)

1. In Project settings → **"General"** tab
2. Scroll to **"Your apps"** → click the **</> (Web)** icon
3. Register app name, e.g. `SmartRailwayDashboard`
4. Copy the `firebaseConfig` object shown:

```javascript
const firebaseConfig = {
  apiKey: "AIza...",
  authDomain: "your-project.firebaseapp.com",
  databaseURL: "https://your-project-default-rtdb.firebaseio.com",
  projectId: "your-project",
  storageBucket: "your-project.appspot.com",
  messagingSenderId: "123456789",
  appId: "1:123456789:web:abc123"
};
```

5. Paste this into `SmartRailway/dashboard/app.js` where indicated.

---

## 5. Update Python Config

Open `SmartRailway/raspberry_pi/config.py` and update:

```python
FIREBASE_CREDENTIALS_PATH = "serviceAccountKey.json"
FIREBASE_DATABASE_URL = "https://your-project-default-rtdb.firebaseio.com"
```

---

## 6. Database Security Rules

For the hackathon demo, use these permissive rules:

```json
{
  "rules": {
    ".read": true,
    ".write": true
  }
}
```

> ⚠️ **For production**, restrict writes to authenticated users:
> ```json
> {
>   "rules": {
>     "train": { ".read": true, ".write": "auth != null" },
>     "gate": { ".read": true, ".write": "auth != null" },
>     "traffic_light": { ".read": true, ".write": "auth != null" },
>     "manual_override": { ".read": "auth != null", ".write": "auth != null" },
>     "logs": { ".read": true, ".write": "auth != null" },
>     "schedules": { ".read": true, ".write": "auth != null" }
>   }
> }
> ```

---

## 7. Master Timetable Uploading

You do NOT need to add anything manually to Firebase for schedules. 
When you run `main.py` on the Raspberry Pi with your credentials, the backend natively consumes the massive `adrajn.csv` and `adrajndet.csv` data and uses `self.firebase.push_timetable()` to seed all of your `[From, To, Arrival, Name, Days]` data into the cloud natively. All UI dynamically hooks into this.

---

## 8. Database Architecture Reference

The system operates off a flattened node-leaf structure for blazing fast real-time overrides and UI updating:

```
/current_gate_status       → "OPEN" or "CLOSED" (Real-time physical servo state)
/gate_status               → "OPEN" or "CLOSED" (UI Command override for motors)
/manual_mode               → 1 or 0 (Toggles Station Master override panel)
/timetable                 → [ Array of ~50 trains ] (Pushed by Pi at boot)
/current_train             → "12282" (Highlights the timetable explicitly)
/trigger_announcement      → "12282" (Command pushed by Station Master to speak)
/custom_announcement       → "Alert: Platform 2 is closed." (TTS string request)
```
