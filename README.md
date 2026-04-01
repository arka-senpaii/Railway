# 🚂 Smart Railway Automation System

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Firebase](https://img.shields.io/badge/Firebase-Realtime-orange.svg)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-3B+-red.svg)
![HTML5](https://img.shields.io/badge/Frontend-HTML5%20%7C%20JS-yellow.svg)

An enterprise-grade IoT railway crossing automation system powered by a Raspberry Pi 3B+. This system offers complete automation through sensor integration, a real-time web dashboard hosted via Firebase, and a multilingual announcement engine for passenger updates.

---

## 🌟 Key Features

* **Real-time Live Dashboard:** A modern, glassmorphism web interface reflecting real-time physical states of the station, gate, traffic lights, and incoming trains.
* **Intelligent Train Tracking:** Uses a KY-032 IR sensor for physical block detection and MFRC522 RFID components for train identification.
* **Live Station Timetable:** A dynamic web table syncs securely with the Raspberry Pi to display scheduled arrivals for the current day, automatically highlighting approaching trains.
* **Multilingual Audio Announcements:** Text-to-Speech (TTS) engine dynamically structures spoken sequences in English, Bengali, and Hindi. Intelligently spaces train numbers (e.g., `1 2 2 8 2`) for precise spelling playback. Includes safe fallback to standard station audio (`project.mp3`) if local generation encounters issues.
* **Station Master Manual Override:** Remotely trigger passenger announcements or override gate & traffic light behaviors securely from the web dashboard.
* **Delay Detection:** Computes scheduling differences logic against physical arrival and auto-generates separate "Late Train" chimes and announcements.
* **Offline Resilience:** Implements an asynchronous queueing system so the Raspberry Pi retains actions during internet outages and flushes them to Firebase once online.

---

## 🏗 System Architecture

The project splits into a **Hardware Controller** (Python) and a **Command Dashboard** (HTML/JS), tethered by **Firebase Realtime Database**.

| Layer | Technology |
|-------|-----------|
| **Controller** | Raspberry Pi 3B+ |
| **Backend Logic**| Python 3.9+ |
| **Realtime Sync**| Firebase Realtime Database (`firebase-admin` / SDK 10+) |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript |
| **Text-to-Speech**| Google Text-to-Speech (`gTTS`) |
| **Audio Processing**| `pydub`, `playsound`, `ffplay` |
| **Hardware Components**| KY-032 IR Sensor, MFRC522 RFID, SG90 Servo, LEDs |

---

## 📂 Project Structure

```text
SmartRailway/
├── raspberry_pi/           # Raspberry Pi Main Controller
│   ├── main.py             # Core state-machine loop
│   ├── config.py           # PIN declarations & Constants
│   ├── sensors.py          # IR sensor & RFID handling
│   ├── actuators.py        # Servo, LEDs, Buzzers
│   ├── firebase_client.py  # Database wrapper & queueing logic
│   ├── announcement.py     # Multilingual TTS formulation & audio execution
│   ├── manual_mode.py      # Background thread for dashboard overrides
│   ├── requirements.txt    # Python 3 dependencies list
│   ├── adrajndet.csv       # Indian Railways detailed lookup index
│   ├── adrajn.csv          # General junction timetable
│   ├── project.mp3         # Fallback default skeletal audio
│   └── late.mp3            # Native chime for delay warning
├── dashboard/              # Web Controller Interface
│   ├── index.html          # Dashboard Markup
│   ├── style.css           # Modern Web Design attributes
│   └── app.js              # Real-time state listeners & UI rendering
├── docs/                   # Full Technical Documentation
│   ├── CIRCUIT_DIAGRAM.md  # Raspberry Pi GPIO schematics
│   ├── FIREBASE_SETUP.md   # Deployment walkthrough for database setup
│   └── ALGORITHM.md        # State machine flowcharts & step-by-step logic
└── README.md               # Repository Overview (This File)
```

---

## 🚀 Quick Start / Installation

### 1. Hardware Initialization
Connect the IR Sensor, RFID reader, Servo Motor, and Traffic LEDs according to the GPIO pinouts mapped in `config.py`. For exact schematics, refer to [CIRCUIT_DIAGRAM.md](docs/CIRCUIT_DIAGRAM.md).

### 2. Firebase Connectivity
Ensure you have created a Realtime Database on Firebase.
1. Download your service account credentials file from GCP/Firebase console.
2. Rename it to match `config.py` (e.g., `serviceAccountKey.json`) and drop it into `raspberry_pi/`.
3. In `dashboard/app.js`, swap the `firebaseConfig` object variables with your public configuration keys.
4. Complete setup directions are found in [FIREBASE_SETUP.md](docs/FIREBASE_SETUP.md).

### 3. Deploying the Controller (Raspberry Pi)
Open an SSH terminal to your Raspberry Pi and clone the repository.
```bash
# Navigate to controller directory
cd SmartRailway/raspberry_pi

# Install dependencies
pip install -r requirements.txt

# Start the Automation Engine
python main.py
```
> **Tip:** You can append `--simulate` to the command to run the controller without native hardware components via internal desktop emulation.

### 4. Booting the Dashboard
The dashboard is entirely static and client-side (Serverless). Simply open `SmartRailway/dashboard/index.html` on your desktop/mobile browser to view the Command Center. If the Python controller is online, you will instantly see live telemetry and today's schedule populate.

---

## 🎮 Usage Guide

- **Auto Mode:** Leave the Python script running. The system will detect trains on the track natively, cycle the traffic lights yellow-to-red, close the mechanical servos, pull the respective ID over RFID, play scheduled passenger audio natively, and write telemetry out to the web in under 400ms.
- **Manual Mode:** From the dashboard, flip the **"Enable Override"** switch. You now control the physical servo gate (Open/Close) and traffic lights directly.
- **Station Master Announcements:** Even when in auto mode, you can type a specific train number into the dashboard and click `Play Announcement`. The Raspberry Pi will intercept the trigger and forcefully announce it across the station speakers via text-to-speech formulation!

---

## 📝 License
Configured and documented under the MIT License — Suitable for University / Hackathon submissions and educational implementations.
`n# Railway
