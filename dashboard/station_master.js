/* ═══════════════════════════════════════════════════════════
   Station Master — Firebase Logic & UI
   ═══════════════════════════════════════════════════════════ */

// ─── Firebase Config ───────────────────────────────────────
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

// ─── DOM Cache ─────────────────────────────────────────────
const $ = (s) => document.querySelector(s);
const DOM = {
  clock:          $("#live-clock"),
  badge:          $("#connection-badge"),
  // Ribbon
  ribbonGate:     $("#ribbon-gate-val"),
  ribbonSignal:   $("#ribbon-signal-val"),
  ribbonMode:     $("#ribbon-mode-val"),
  ribbonTrain:    $("#ribbon-train-val"),
  // Controls
  overrideToggle: $("#sm-override-toggle"),
  overrideHint:   $("#override-hint"),
  btnGateOpen:    $("#sm-btn-gate-open"),
  btnGateClose:   $("#sm-btn-gate-close"),
  btnRed:         $("#sm-btn-red"),
  btnYellow:      $("#sm-btn-yellow"),
  btnGreen:       $("#sm-btn-green"),
  miniRed:        $("#mini-red"),
  miniYellow:     $("#mini-yellow"),
  miniGreen:      $("#mini-green"),
  // Announce
  trainSelect:    $("#sm-train-select"),
  trainInput:     $("#sm-train-input"),
  btnAnnounce:    $("#sm-btn-announce"),
  detailNo:       $("#detail-no"),
  detailName:     $("#detail-name"),
  detailFrom:     $("#detail-from"),
  detailTo:       $("#detail-to"),
  detailArrival:  $("#detail-arrival"),
  detailPlatform: $("#detail-platform"),
  quickGrid:      $("#quick-grid"),
  customInput:    $("#sm-custom-text"),
  btnCustomAnn:   $("#sm-btn-custom-announce"),
  // Timetable
  daySelect:      $("#sm-day-select"),
  trainCount:     $("#sm-train-count"),
  tableBody:      $("#sm-timetable-body"),
  // Log
  logFeed:        $("#sm-log-feed"),
  btnClearLog:    $("#sm-btn-clear-log"),
};

// ─── State ─────────────────────────────────────────────────
const state = {
  currentGate: "OPEN",
  commandedGate: "OPEN",
  manualMode: false,
  currentTrain: null,
  currentSignal: "green",
  timetable: [],
};

// ─── Clock Data ─────────────────────────────────────────────
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// ─── Clock ─────────────────────────────────────────────────
function tickClock() {
  const d = new Date();
  DOM.clock.textContent = d.toLocaleTimeString("en-IN", { hour12: false });
}
setInterval(tickClock, 1000);
tickClock();

// Initialize Day Selector
DOM.daySelect.value = DAYS[new Date().getDay()];

DOM.daySelect.addEventListener("change", () => {
  renderTimetable();
});

// ─── Connection Badge ──────────────────────────────────────
function setBadge(online) {
  DOM.badge.className = online ? "badge badge-online" : "badge badge-offline";
  DOM.badge.innerHTML = online
    ? '<span class="pulse-dot"></span> Online'
    : '<span class="pulse-dot"></span> Offline';
}

// ─── Firebase Init ─────────────────────────────────────────
let db = null;
let ready = false;

try {
  firebase.initializeApp(firebaseConfig);
  db = firebase.database();
  ready = true;
  setBadge(true);
  log("Firebase connected.", "success");
} catch (err) {
  log("Firebase not available — demo mode.", "warn");
}

// ─── Firebase Listeners ────────────────────────────────────
if (ready) {
  db.ref(".info/connected").on("value", (s) => setBadge(s.val() === true));

  db.ref("/current_gate_status").on("value", (s) => {
    if (s.val() === null) return;
    state.currentGate = s.val();
    refreshUI();
    log(`Gate status: ${s.val()}`, "info");
  });

  db.ref("/gate_status").on("value", (s) => {
    if (s.val() === null) return;
    state.commandedGate = s.val();
    refreshUI();
  });

  db.ref("/manual_mode").on("value", (s) => {
    if (s.val() === null) return;
    state.manualMode = s.val() === 1;
    DOM.overrideToggle.checked = state.manualMode;
    toggleControls(state.manualMode);
    DOM.overrideHint.textContent = state.manualMode ? "Manual control active" : "Auto mode active";
    DOM.ribbonMode.textContent = state.manualMode ? "MANUAL" : "AUTO";
    DOM.ribbonMode.style.color = state.manualMode ? "var(--accent-yellow)" : "var(--accent-green)";
    log(`Mode: ${state.manualMode ? "MANUAL" : "AUTO"}`, state.manualMode ? "warn" : "success");
  });

  db.ref("/timetable").on("value", (s) => {
    const val = s.val();
    if (val) {
      state.timetable = Array.isArray(val) ? val : Object.values(val);
      renderTimetable();
      populateTrainSelect();
      populateQuickAnnounce();
    }
  });

  db.ref("/current_train").on("value", (s) => {
    state.currentTrain = s.val();
    const display = state.currentTrain || "None";
    DOM.ribbonTrain.textContent = display;
    DOM.ribbonTrain.style.color = state.currentTrain ? "var(--accent-green)" : "";
    highlightTimetable();
  });
}

// ─── UI Refresh ────────────────────────────────────────────
function refreshUI() {
  const open = state.currentGate === "OPEN";
  const cmdClosed = state.commandedGate === "CLOSED";

  // Ribbon gate
  DOM.ribbonGate.textContent = open ? "OPEN" : "CLOSED";
  DOM.ribbonGate.style.color = open ? "var(--accent-green)" : "var(--accent-red)";

  // Signal derivation
  if (open && !cmdClosed) {
    setSignal("green");
  } else if (open && cmdClosed) {
    setSignal("yellow");
  } else {
    setSignal("red");
  }
}

function setSignal(color) {
  state.currentSignal = color;

  // Ribbon
  DOM.ribbonSignal.textContent = color.toUpperCase();
  DOM.ribbonSignal.style.color = `var(--accent-${color === "yellow" ? "yellow" : color === "red" ? "red" : "green"})`;

  // Mini lights
  [DOM.miniRed, DOM.miniYellow, DOM.miniGreen].forEach(el => el.classList.remove("active"));
  if (color === "red") DOM.miniRed.classList.add("active");
  else if (color === "yellow") DOM.miniYellow.classList.add("active");
  else DOM.miniGreen.classList.add("active");

  // Signal buttons active state
  [DOM.btnRed, DOM.btnYellow, DOM.btnGreen].forEach(b => b.classList.remove("active-signal"));
  if (color === "red") DOM.btnRed.classList.add("active-signal");
  else if (color === "yellow") DOM.btnYellow.classList.add("active-signal");
  else DOM.btnGreen.classList.add("active-signal");
}

// ─── Toggle Controls ───────────────────────────────────────
function toggleControls(enabled) {
  const btns = [DOM.btnGateOpen, DOM.btnGateClose, DOM.btnRed, DOM.btnYellow, DOM.btnGreen];
  btns.forEach(b => { if (b) b.disabled = !enabled; });
  // Announce button is always available (doesn't require manual mode)
  DOM.btnAnnounce.disabled = false;
}

// ─── Train Selector ────────────────────────────────────────
function populateTrainSelect() {
  DOM.trainSelect.innerHTML = '<option value="">— Select a Train —</option>';
  state.timetable.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.Train_No;
    opt.textContent = `${t.Train_No} — ${t.Train_Name}`;
    DOM.trainSelect.appendChild(opt);
  });
}

DOM.trainSelect.addEventListener("change", () => {
  const id = DOM.trainSelect.value;
  if (id) {
    DOM.trainInput.value = "";
    showTrainDetail(id);
  }
});

DOM.trainInput.addEventListener("input", () => {
  const id = DOM.trainInput.value.replace(/\s+/g, "").trim();
  if (id.length >= 4) {
    DOM.trainSelect.value = "";
    showTrainDetail(id);
  }
});

function showTrainDetail(trainNo) {
  trainNo = trainNo.replace(/\s+/g, "");
  const train = state.timetable.find(t => t.Train_No.replace(/\s+/g, "") === trainNo);
  if (train) {
    DOM.detailNo.textContent = train.Train_No;
    DOM.detailName.textContent = train.Train_Name;
    DOM.detailArrival.textContent = train.Arrival_Time || "—";
    DOM.detailPlatform.textContent = train.Platform_No || "1";
    DOM.detailFrom.textContent = train.From || "—";
    DOM.detailTo.textContent = train.To || "—";
  } else {
    DOM.detailNo.textContent = trainNo;
    DOM.detailName.textContent = "Not in today's timetable";
    DOM.detailArrival.textContent = "—";
    DOM.detailPlatform.textContent = "—";
    DOM.detailFrom.textContent = "—";
    DOM.detailTo.textContent = "—";
  }
}

// ─── Quick Announce ────────────────────────────────────────
function populateQuickAnnounce() {
  DOM.quickGrid.innerHTML = "";
  const now = new Date();
  const todayStr = DAYS[now.getDay()];
  const nowMins = now.getHours() * 60 + now.getMinutes();

  const upcoming = state.timetable
    .filter(t => {
      if (!t.Days.includes(todayStr) && !t.Days.includes("Daily")) return false;
      if (!t.Arrival_Time || t.Arrival_Time === "--") return false;
      const [h, m] = t.Arrival_Time.split(":").map(Number);
      return h * 60 + m >= nowMins - 10;
    })
    .sort((a, b) => {
      const [ah, am] = a.Arrival_Time.split(":").map(Number);
      const [bh, bm] = b.Arrival_Time.split(":").map(Number);
      return (ah * 60 + am) - (bh * 60 + bm);
    })
    .slice(0, 4);

  upcoming.forEach(t => {
    const btn = document.createElement("button");
    btn.className = "quick-btn";
    btn.innerHTML = `<span class="qb-no">${t.Train_No}</span> ${t.Arrival_Time}<span class="qb-name">${t.Train_Name}</span>`;
    btn.addEventListener("click", () => triggerAnnouncement(t.Train_No));
    DOM.quickGrid.appendChild(btn);
  });

  if (upcoming.length === 0) {
    DOM.quickGrid.innerHTML = '<span style="font-size:.7rem;color:var(--text-dim);grid-column:span 2;text-align:center;padding:.5rem">No upcoming trains</span>';
  }
}

// ─── Timetable ─────────────────────────────────────────────
function renderTimetable() {
  const selectedDay = DOM.daySelect.value;
  
  const filtered = state.timetable.filter(t => {
    return t.Days.includes(selectedDay) || t.Days.includes("Daily");
  });

  DOM.trainCount.textContent = filtered.length;

  if (!filtered.length) {
    DOM.tableBody.innerHTML = '<tr><td colspan="8" class="empty-msg">No trains for this day</td></tr>';
    return;
  }

  const now = new Date();
  const nowMins = now.getHours() * 60 + now.getMinutes();
  const isToday = selectedDay === DAYS[now.getDay()];

  // Sort by arrival time
  filtered.sort((a, b) => {
      const [ah, am] = (a.Arrival_Time || "00:00").split(":").map(Number);
      const [bh, bm] = (b.Arrival_Time || "00:00").split(":").map(Number);
      return (ah * 60 + am) - (bh * 60 + bm);
  });

  // Find the VERY NEXT upcoming train explicitly
  let nextTrainId = null;
  if (isToday) {
    const nextTrain = filtered.find(t => {
      if (t.Arrival_Time === "--") return false;
      const [th, tm] = t.Arrival_Time.split(":").map(Number);
      return (th * 60 + tm) >= (nowMins - 10);
    });
    if (nextTrain) nextTrainId = nextTrain.Train_No.replace(/\s+/g, '');
  }

  DOM.tableBody.innerHTML = filtered.map(t => {
    const id = t.Train_No.replace(/\s+/g, '');
    let rowClass = "";
    let statusText = "Scheduled";
    let pillClass = "";

    // Calculate time state only for today
    if (isToday && t.Arrival_Time !== "--") {
      const [th, tm] = t.Arrival_Time.split(":").map(Number);
      const tMins = th * 60 + tm;
      
      if (tMins < nowMins - 15) {
        rowClass = "past-train";
        statusText = "Departed";
      } else if (id === nextTrainId && (state.currentTrain || "").replace(/\s+/g, '') !== id) {
        rowClass = "next-train";
        statusText = "Upcoming";
        pillClass = "arriving"; // Reusing cyan styling for pill
      }
    }

    return `
      <tr data-train="${id}" class="${rowClass}">
        <td style="font-family:var(--mono);font-weight:600;color:var(--accent-cyan)">${t.Train_No}</td>
        <td>${t.Train_Name}</td>
        <td>${t.From || '—'}</td>
        <td>${t.To || '—'}</td>
        <td>${t.Arrival_Time || '—'}</td>
        <td>${t.Platform_No || '1'}</td>
        <td><span class="status-pill ${pillClass}" id="pill-${id}">${statusText}</span></td>
        <td><button class="tbl-announce-btn" onclick="triggerAnnouncement('${id}')">📢</button></td>
      </tr>
    `;
  }).join("");

  highlightTimetable();
}

function highlightTimetable() {
  const rows = DOM.tableBody.querySelectorAll("tr[data-train]");
  rows.forEach(row => {
    const id = row.getAttribute("data-train");
    const active = (state.currentTrain || "").replace(/\s+/g, "");
    const pill = row.querySelector(".status-pill");

    if (active && active === id) {
      row.classList.add("arriving-row");
      row.classList.remove("past-train", "next-train");
      if (pill) { pill.textContent = "Arriving"; pill.classList.add("arriving"); }
    } else {
      row.classList.remove("arriving-row");
    }
  });
}

// ─── Actions ───────────────────────────────────────────────

// Manual override toggle
DOM.overrideToggle.addEventListener("change", (e) => {
  const on = e.target.checked;
  toggleControls(on);
  if (ready) db.ref("/manual_mode").set(on ? 1 : 0);
  log(on ? "Manual override ENABLED" : "Manual override DISABLED", on ? "warn" : "success");
});

// Gate buttons
DOM.btnGateOpen.addEventListener("click", () => {
  if (ready) db.ref("/gate_status").set("OPEN");
  log("Gate → OPEN", "success");
});
DOM.btnGateClose.addEventListener("click", () => {
  if (ready) db.ref("/gate_status").set("CLOSED");
  log("Gate → CLOSED", "warn");
});

// Signal buttons (local preview + matches physical via gate commands)
DOM.btnRed.addEventListener("click", () => { setSignal("red"); log("Signal → RED", "error"); });
DOM.btnYellow.addEventListener("click", () => { setSignal("yellow"); log("Signal → YELLOW", "warn"); });
DOM.btnGreen.addEventListener("click", () => { setSignal("green"); log("Signal → GREEN", "success"); });

// Announcement
DOM.btnAnnounce.addEventListener("click", () => {
  const fromSelect = DOM.trainSelect.value;
  const fromInput = DOM.trainInput.value.replace(/\s+/g, "").trim();
  const trainId = fromSelect || fromInput;
  if (!trainId) {
    log("Please select or enter a train number first.", "error");
    return;
  }
  triggerAnnouncement(trainId);
});

// Custom Announcement
DOM.btnCustomAnn.addEventListener("click", () => {
  const text = DOM.customInput.value.trim();
  if (!text) {
    log("Please enter custom text to announce.", "warn");
    return;
  }
  if (ready) {
    db.ref("/custom_announcement").set(text).then(() => {
      log(`📢 Custom Audio Triggered: "${text}"`, "success");
      DOM.customInput.value = "";
    });
  } else {
    log(`(Demo) Custom Audio: ${text}`, "info");
  }
});

function triggerAnnouncement(trainId) {
  trainId = trainId.replace(/\s+/g, "").trim();
  if (!trainId) return;

  if (ready) {
    db.ref("/trigger_announcement").set(trainId).then(() => {
      log(`📢 Announcement triggered on Pi: Train ${trainId}`, "success");
      // Visual feedback
      DOM.btnAnnounce.classList.add("playing");
      setTimeout(() => DOM.btnAnnounce.classList.remove("playing"), 4000);
    });
  } else {
    log(`(Demo) Announcement: ${trainId}`, "info");
  }

  // Show detail
  showTrainDetail(trainId);
}

// Clear log
DOM.btnClearLog.addEventListener("click", () => {
  DOM.logFeed.innerHTML = "";
  log("Log cleared.", "info");
});

// ─── Log ───────────────────────────────────────────────────
function log(message, level = "info") {
  const now = new Date().toLocaleTimeString("en-IN", { hour12: false });
  const el = document.createElement("div");
  el.className = `log-line log-${level}`;
  el.innerHTML = `<time>${now}</time><span>${esc(message)}</span>`;
  DOM.logFeed.prepend(el);
  // Cap at 80 entries
  while (DOM.logFeed.children.length > 80) {
    DOM.logFeed.removeChild(DOM.logFeed.lastChild);
  }
}

function esc(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}
