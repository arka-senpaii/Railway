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

## 7. Populate Sample Schedule Data

In the Firebase Console → Realtime Database, click **"+"** to add:

```
schedules/
├── 22812/
│   ├── name: "Rajdhani Express (via Adra)"
│   ├── scheduled_arrival: "08:15"
│   └── platform: "4"
├── 12282/
│   ├── name: "Duronto Express"
│   ├── scheduled_arrival: "04:10"
│   └── platform: "4"
├── 12883/
│   ├── name: "Rupasi Bangla Express"
│   ├── scheduled_arrival: "10:51"
│   └── platform: "1"
```

The Python code primarily uses the local CSV data (`adrajndet.csv`) for schedule lookup, so this Firebase schedule data is optional and used for cloud-based fallback.

---

## 8. Required Database Structure

The system automatically creates these nodes:

```
/train       → { id, status, delay, timestamp }
/gate        → { status, timestamp }
/traffic_light → { state, timestamp }
/manual_override → { enabled, gate, traffic_light }
/logs        → { auto-keyed log entries }
/schedules   → { train_id: { name, scheduled_arrival, platform } }
```
