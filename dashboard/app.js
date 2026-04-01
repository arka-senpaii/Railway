/* ═══════════════════════════════════════════════════════════
   Smart Railway Dashboard — Firebase Logic & UI Binding
   Only uses three Firebase fields:
     /current_gate_status  → "OPEN" / "CLOSED"
     /gate_status          → "OPEN" / "CLOSED"  (commanded)
     /manual_mode          → 1 / 0
   ═══════════════════════════════════════════════════════════ */

// ─── Firebase Configuration ────────────────────────────────
const firebaseConfig = {
  apiKey: "AIzaSyD2dBbK8HMAiAZf-FF1Bc5rtQfSUYcz1wk",
  authDomain: "railway-c8909.firebaseapp.com",
  databaseURL: "https://railway-c8909-default-rtdb.firebaseio.com",
  projectId: "railway-c8909",
  storageBucket: "railway-c8909.firebasestorage.app",
  messagingSenderId: "135340384569",
  appId: "1:135340384569:web:2cfb87e142df154ac3c8e8",
  measurementId: "G-4CZBGR6S2R"
};

// ─── DOM References ────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);

const DOM = {
  clock:           $("#clock"),
  connBadge:       $("#connection-badge"),
  // Status strip
  trainStatusText: $("#train-status-text"),
  gateStatusText:  $("#gate-status-text"),
  delayStatusText: $("#delay-status-text"),
  // Traffic light
  lightRed:        $("#light-red"),
  lightYellow:     $("#light-yellow"),
  lightGreen:      $("#light-green"),
  trafficLabel:    $("#traffic-label"),
  // Train info
  trainNo:         $("#info-train-no"),
  trainName:       $("#info-train-name"),
  trainStatus:     $("#info-train-status"),
  trainDelay:      $("#info-train-delay"),
  trainTime:       $("#info-train-time"),
  // Gate
  gateArm:         $("#gate-arm"),
  gateLabel:       $("#gate-label"),
  // Manual controls
  overrideToggle:  $("#override-toggle"),
  btnGateOpen:     $("#btn-gate-open"),
  btnGateClose:    $("#btn-gate-close"),
  btnLightRed:     $("#btn-light-red"),
  btnLightYellow:  $("#btn-light-yellow"),
  btnLightGreen:   $("#btn-light-green"),
  // Station Master
  announceTrainId: $("#announce-train-id"),
  btnAnnounce:     $("#btn-announce"),
  // Log
  logFeed:         $("#log-feed"),
  btnClearLog:     $("#btn-clear-log"),
};

// ─── Clock ─────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  DOM.clock.textContent = now.toLocaleTimeString("en-IN", { hour12: false });
}
setInterval(updateClock, 1000);
updateClock();

// ─── Connection Badge ──────────────────────────────────────
function setConnectionBadge(online) {
  DOM.connBadge.className = online ? "badge badge-online" : "badge badge-offline";
  DOM.connBadge.innerHTML = online
    ? '<span class="pulse-dot"></span> Online'
    : '<span class="pulse-dot"></span> Offline';
}

// ─── Initialize Firebase ───────────────────────────────────
let db = null;
let firebaseReady = false;

try {
  firebase.initializeApp(firebaseConfig);
  db = firebase.database();
  firebaseReady = true;
  setConnectionBadge(true);
  addLog("Firebase connected.", "success");
} catch (err) {
  console.warn("Firebase init failed:", err.message);
  addLog("Firebase not configured — running in demo mode.", "warn");
  loadDemoData();
}

// ─── Local State Tracking ────────────────────────────────────
const localSystemState = {
  currentGate: "OPEN",
  commandedGate: "OPEN",
  currentTrain: null
};

// ─── Firebase Listeners (only 3 fields) ────────────────────
if (firebaseReady) {
  // Connection state
  db.ref(".info/connected").on("value", (snap) => {
    setConnectionBadge(snap.val() === true);
  });

  // current_gate_status — the actual physical gate state
  db.ref("/current_gate_status").on("value", (snap) => {
    const val = snap.val();
    if (val === null) return;
    localSystemState.currentGate = val;
    evaluateSystemUI();
    addLog(`Current gate status: ${val}`, "info");
  });

  // gate_status — the commanded / desired gate state
  db.ref("/gate_status").on("value", (snap) => {
    const val = snap.val();
    if (val === null) return;
    localSystemState.commandedGate = val;
    DOM.gateStatusText.textContent = val;
    evaluateSystemUI();
    addLog(`Gate status (commanded): ${val}`, "info");
  });

  // manual_mode — 1 or 0
  db.ref("/manual_mode").on("value", (snap) => {
    const val = snap.val();
    if (val === null) return;
    const isManual = val === 1;
    DOM.overrideToggle.checked = isManual;
    toggleManualButtons(isManual);
    addLog(`Manual mode: ${isManual ? "ON" : "OFF"}`, isManual ? "warn" : "success");
  });

  // Timetable
  db.ref("/timetable").on("value", (snap) => {
    const val = snap.val();
    if (val) renderTimetable(val);
  });

  // Current train
  db.ref("/current_train").on("value", (snap) => {
    const val = snap.val();
    localSystemState.currentTrain = val;
    evaluateTimetableHighlight();
  });
}

// ─── UI Update Functions ───────────────────────────────────

function renderTimetable(trainList) {
  const tbody = $("#timetable-body");
  const countSpan = $("#timetable-count");
  if (!tbody) return;
  
  if (!trainList || trainList.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; opacity:0.5;">No trains scheduled for today</td></tr>';
    if (countSpan) countSpan.textContent = "0 trains";
    return;
  }

  if (countSpan) countSpan.textContent = `${trainList.length} train${trainList.length !== 1 ? 's' : ''}`;
  
  tbody.innerHTML = trainList.map(t => {
    return `<tr data-train-id="${t.Train_No}">
      <td>${t.Train_No}</td>
      <td>${t.Train_Name}</td>
      <td>${t.Arrival_Time}</td>
      <td>${t.Platform_No}</td>
      <td class="status-cell">Scheduled</td>
    </tr>`;
  }).join('');
  
  evaluateTimetableHighlight();
}

function evaluateTimetableHighlight() {
  const rows = document.querySelectorAll("#timetable-body tr[data-train-id]");
  rows.forEach(row => {
    const trainId = row.getAttribute("data-train-id");
    const statusCell = row.querySelector(".status-cell");
    
    // Check if the currentTrain matches this row
    // Remove spaces from currentTrain in case it's in spaced format
    let activeTrainId = localSystemState.currentTrain || "";
    activeTrainId = activeTrainId.replace(/\s+/g, '');
    let rowTrainId = trainId.replace(/\s+/g, '');
    
    if (activeTrainId && activeTrainId === rowTrainId) {
      row.style.backgroundColor = "rgba(46, 204, 113, 0.2)";
      row.style.borderLeft = "4px solid var(--accent-green)";
      if (statusCell) {
        statusCell.textContent = "Arriving";
        statusCell.style.color = "var(--accent-green)";
        statusCell.style.fontWeight = "bold";
      }
    } else {
      row.style.backgroundColor = "";
      row.style.borderLeft = "";
      if (statusCell) {
        statusCell.textContent = "Scheduled";
        statusCell.style.color = "";
        statusCell.style.fontWeight = "normal";
      }
    }
  });
}

function evaluateSystemUI() {
  const isPhysicallyOpen = localSystemState.currentGate === "OPEN";
  const isCommandedClosed = localSystemState.commandedGate === "CLOSED";

  // Gate Text & Card visuals
  DOM.gateLabel.textContent = isPhysicallyOpen ? "GATE OPEN" : "GATE CLOSED";
  DOM.gateLabel.style.color = isPhysicallyOpen ? "var(--accent-green)" : "var(--accent-red)";
  const card = $("#gate-status-card");
  if (card) {
    card.style.borderColor = isPhysicallyOpen ? "var(--accent-green)" : "var(--accent-red)";
  }

  // Traffic Light, Train Status & Gate Animation derivation
  if (isPhysicallyOpen && !isCommandedClosed) {
    // 1. IDLE (System normal)
    updateTrafficUI("green");
    if (DOM.trainStatusText) DOM.trainStatusText.textContent = "Idle";
    DOM.gateArm.classList.add("open");
    DOM.gateArm.classList.remove("closed", "closing-animation");
    
  } else if (isPhysicallyOpen && isCommandedClosed) {
    // 2. APPROACHING / WARNING (Commanded closed but physically still open)
    updateTrafficUI("yellow");
    if (DOM.trainStatusText) DOM.trainStatusText.textContent = "Approaching";
    DOM.gateArm.classList.remove("open", "closed");
    DOM.gateArm.classList.add("closing-animation"); // Custom intermediate state if added in CSS
    
  } else {
    // 3. PASSING / CLOSED (Physically closed)
    updateTrafficUI("red");
    if (DOM.trainStatusText) DOM.trainStatusText.textContent = "Active";
    DOM.gateArm.classList.add("closed");
    DOM.gateArm.classList.remove("open", "closing-animation");
  }
}

function updateTrafficUI(state) {
  [DOM.lightRed, DOM.lightYellow, DOM.lightGreen].forEach(el => {
    if (el) el.classList.remove("active");
  });

  const labels = {
    red:    "RED — Stop! Gate closed",
    yellow: "YELLOW — Warning",
    green:  "GREEN — Safe to cross",
  };

  switch (state) {
    case "red":
      if (DOM.lightRed) DOM.lightRed.classList.add("active");
      if (DOM.trafficLabel) {
        DOM.trafficLabel.textContent = labels.red;
        DOM.trafficLabel.style.color = "var(--accent-red)";
      }
      break;
    case "yellow":
      if (DOM.lightYellow) DOM.lightYellow.classList.add("active");
      if (DOM.trafficLabel) {
        DOM.trafficLabel.textContent = labels.yellow;
        DOM.trafficLabel.style.color = "var(--accent-yellow)";
      }
      break;
    case "green":
    default:
      if (DOM.lightGreen) DOM.lightGreen.classList.add("active");
      if (DOM.trafficLabel) {
        DOM.trafficLabel.textContent = labels.green;
        DOM.trafficLabel.style.color = "var(--accent-green)";
      }
      break;
  }
}

function toggleManualButtons(enabled) {
  const btns = [
    DOM.btnGateOpen, DOM.btnGateClose,
    DOM.btnLightRed, DOM.btnLightYellow, DOM.btnLightGreen,
    DOM.btnAnnounce, DOM.announceTrainId
  ];
  btns.forEach(btn => { if (btn) btn.disabled = !enabled; });
}

// ─── Manual Override ───────────────────────────────────────
DOM.overrideToggle.addEventListener("change", (e) => {
  const enabled = e.target.checked;
  toggleManualButtons(enabled);

  if (firebaseReady) {
    db.ref("/manual_mode").set(enabled ? 1 : 0);
  }
  addLog(enabled ? "Manual override ENABLED" : "Manual override DISABLED",
         enabled ? "warn" : "success");
});

// Gate buttons — write to gate_status
DOM.btnGateOpen.addEventListener("click", () => {
  if (firebaseReady) db.ref("/gate_status").set("OPEN");
  addLog("Manual: Gate → OPEN", "success");
});
DOM.btnGateClose.addEventListener("click", () => {
  if (firebaseReady) db.ref("/gate_status").set("CLOSED");
  addLog("Manual: Gate → CLOSED", "warn");
});

// Traffic-light buttons (local UI only — not in Firebase)
if (DOM.btnLightRed) {
  DOM.btnLightRed.addEventListener("click", () => {
    updateTrafficUI("red");
    addLog("Manual: Traffic light → RED", "error");
  });
}
if (DOM.btnLightYellow) {
  DOM.btnLightYellow.addEventListener("click", () => {
    updateTrafficUI("yellow");
    addLog("Manual: Traffic light → YELLOW", "warn");
  });
}
if (DOM.btnLightGreen) {
  DOM.btnLightGreen.addEventListener("click", () => {
    updateTrafficUI("green");
    addLog("Manual: Traffic light → GREEN", "success");
  });
}

// Station Master Announcement
if (DOM.btnAnnounce) {
  DOM.btnAnnounce.addEventListener("click", () => {
    const trainId = DOM.announceTrainId.value.trim();
    if (!trainId) return alert("Please enter a Train No first.");
    DOM.announceTrainId.value = "";
    if (firebaseReady) {
      db.ref("/trigger_announcement").set(trainId).then(() => {
         addLog(`Announcement triggered on Pi for train ${trainId}`, "success");
      });
    } else {
      addLog(`(Demo) Announcement requested: ${trainId}`, "info");
    }
  });
}

// Clear log
DOM.btnClearLog.addEventListener("click", () => {
  DOM.logFeed.innerHTML = "";
  addLog("Log cleared.", "info");
});

// ─── Log Helper ────────────────────────────────────────────
function addLog(message, level = "info", timeStr = null) {
  const now = timeStr || new Date().toLocaleTimeString("en-IN", { hour12: false });
  const entry = document.createElement("div");
  entry.className = `log-entry log-${level}`;
  entry.innerHTML = `<time>${now}</time><span>${escapeHtml(message)}</span>`;
  DOM.logFeed.prepend(entry);

  // Keep max 100 entries
  while (DOM.logFeed.children.length > 100) {
    DOM.logFeed.removeChild(DOM.logFeed.lastChild);
  }
}

// ─── Utilities ─────────────────────────────────────────────
function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ─── Demo Data (when Firebase not configured) ──────────────
function loadDemoData() {
  updateGateUI("OPEN");
  updateTrafficUI("green");

  let step = 0;
  setInterval(() => {
    step = (step + 1) % 4;
    switch (step) {
      case 1:
        updateGateUI("CLOSED");
        addLog("Demo: Gate CLOSED", "warn");
        break;
      case 2:
        addLog("Demo: Train passing...", "error");
        break;
      case 3:
        updateGateUI("OPEN");
        addLog("Demo: Gate OPEN — safe to cross", "success");
        break;
    }
  }, 4000);
}
