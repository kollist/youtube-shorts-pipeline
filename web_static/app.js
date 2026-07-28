const statusEl = document.getElementById("status");
const terminalEl = document.getElementById("terminal");
const runBtn = document.getElementById("run-btn");
const stopRunBtn = document.getElementById("stop-run-btn");
const dailyQueueBtn = document.getElementById("daily-queue-btn");
const dailyUploadEl = document.getElementById("daily-upload");
const dailyUploadFields = document.getElementById("daily-upload-fields");
const clipsEl = document.getElementById("clips");
const clipCountEl = document.getElementById("clip-count");

// Both "start a run" buttons share one lock (the server enforces this too -
// run_lock - but disabling both client-side avoids a pointless round trip
// just to be told a run is already in progress).
function setRunningUI(isRunning) {
  runBtn.disabled = isRunning;
  dailyQueueBtn.disabled = isRunning;
  stopRunBtn.style.display = isRunning ? "" : "none";
  stopRunBtn.disabled = false;
  stopRunBtn.textContent = "Stop";
}

stopRunBtn.addEventListener("click", async () => {
  stopRunBtn.disabled = true;
  stopRunBtn.textContent = "Stopping...";
  try {
    const res = await fetch("/api/stop-run", { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      logLine(`[web] ${err.detail || "Could not stop the run."}`, "err");
      stopRunBtn.disabled = false;
      stopRunBtn.textContent = "Stop";
    }
    // On success, leave it disabled/"Stopping..." until the "stopped" message
    // arrives and setRunningUI(false) resets it - the run can take a moment
    // to reach its next safe checkpoint.
  } catch (e) {
    logLine("[web] Could not reach the server to stop the run.", "err");
    stopRunBtn.disabled = false;
    stopRunBtn.textContent = "Stop";
  }
});

dailyUploadEl.addEventListener("change", () => {
  dailyUploadFields.style.display = dailyUploadEl.checked ? "" : "none";
});

dailyQueueBtn.addEventListener("click", () => {
  const config = {
    action: "daily_queue",
    target: parseInt(document.getElementById("daily-target").value, 10) || 20,
    whisper_model: document.getElementById("whisper-model").value,
    min_duration: parseFloat(document.getElementById("min-duration").value),
    max_duration: parseFloat(document.getElementById("max-duration").value),
    upload: dailyUploadEl.checked,
    privacy: document.getElementById("daily-privacy").value,
    spacing_minutes: parseFloat(document.getElementById("daily-spacing").value) || 20,
  };

  terminalEl.innerHTML = "";
  clipsEl.innerHTML = "";
  clipCount = 0;
  clipCountEl.textContent = "";
  autoUploadHalted = false;
  setRunningUI(true);
  setStatus("running", "running");

  openRunSocket(config, false);
});

const urlInput = document.getElementById("url-input");
const fileInput = document.getElementById("file-input");
const tabs = document.querySelectorAll(".tab");
const autoUploadEl = document.getElementById("auto-upload");
const autoPrivacyEl = document.getElementById("auto-privacy");
const autoPrivacyField = document.getElementById("auto-privacy-field");

// --- Page routing (hash-based, client-side only - the live run's WebSocket
// and in-progress state need to survive switching tabs, so this is plain
// show/hide rather than separate server-rendered pages). ---
const pageTabs = document.querySelectorAll(".page-tab");
const pages = document.querySelectorAll(".page");
const VALID_PAGES = new Set(["run", "discover", "input", "filler", "clips", "analytics"]);
let discoverLoadedOnce = false;
let inputLoadedOnce = false;
let fillerLoadedOnce = false;

function showPage(name) {
  if (!VALID_PAGES.has(name)) name = "run";
  pages.forEach((p) => p.classList.toggle("active", p.id === `page-${name}`));
  pageTabs.forEach((t) => t.classList.toggle("active", t.dataset.page === name));
  if (name === "discover" && !discoverLoadedOnce) loadDiscover();
  if (name === "input" && !inputLoadedOnce) loadInputFiles();
  if (name === "filler" && !fillerLoadedOnce) {
    loadFillerFiles();
    loadFillerDiscover();
  }
  if (name === "analytics") loadAnalytics();
}

window.addEventListener("hashchange", () => showPage(location.hash.slice(1)));
// The initial showPage() call is deferred to the end of this file (not here)
// - a loader like loadDiscover() touches its content element synchronously
// (before its first await), so calling it this early would hit the element
// reference's temporal dead zone if the page loads directly on that tab's hash.

let source = "url";
// A file already on the server (from input/), picked via the Input tab's
// "Use" button - browsers won't let JS set a real <input type=file>'s value
// for security reasons, so this bypasses the file picker/upload entirely and
// tells the run to use this existing server-side path directly. Cleared
// whenever the user actually interacts with the native file picker instead.
let selectedInputPath = null;
let clipCount = 0;
let uploadQueue = Promise.resolve();
const allClipEntries = []; // {card, uploadBtn, privacySelect, clip} for every not-yet-uploaded clip currently shown
// YouTube's daily upload cap is account-wide, so once one auto-upload hits it,
// every remaining clip in this run would fail the same way - stop trying
// instead of showing a wall of identical failures.
let autoUploadHalted = false;

const tokenBudgetEl = document.getElementById("token-budget");
const budgetToggle = document.getElementById("budget-toggle");
const budgetSummaryDot = document.getElementById("budget-summary-dot");
const budgetSummaryText = document.getElementById("budget-summary-text");

budgetToggle.addEventListener("click", (e) => {
  e.stopPropagation();
  tokenBudgetEl.classList.toggle("open");
});
document.addEventListener("click", (e) => {
  if (!tokenBudgetEl.contains(e.target) && e.target !== budgetToggle) {
    tokenBudgetEl.classList.remove("open");
  }
});

// Each Groq model has its own daily budget - the first model in the list is
// the one actually in use; the rest are what the pipeline falls back to once
// an earlier one runs out, so a single exhausted model doesn't stop the day.
// The header just shows a compact summary (worst state + how many models
// still have room); click it for the full per-model breakdown.
async function refreshTokenBudget() {
  try {
    const res = await fetch("/api/token-budget");
    if (!res.ok) return;
    const { models } = await res.json();

    tokenBudgetEl.innerHTML = "";
    let available = 0;
    let worstState = "good"; // good -> low -> critical, worst wins
    models.forEach(({ model, used, cap, remaining }) => {
      const exhausted = remaining <= 0;
      if (!exhausted) available += 1;
      const usedPct = Math.min(100, (used / cap) * 100);

      let state = "good";
      if (remaining < cap * 0.05) state = "critical";
      else if (remaining < cap * 0.2) state = "low";
      if (state === "critical") worstState = "critical";
      else if (state === "low" && worstState !== "critical") worstState = "low";

      const row = document.createElement("div");
      row.className = `token-budget-row${exhausted ? " exhausted" : ""}`;
      row.innerHTML = `
        <div class="token-budget-label">
          <span class="model-name">${escapeHtml(model)}</span>
          <span class="figures">${used.toLocaleString()} / ${cap.toLocaleString()}</span>
        </div>
        <div class="token-budget-bar"><div class="token-budget-fill" style="width:${usedPct}%"></div></div>
      `;
      row.querySelector(".token-budget-fill").classList.toggle("critical", state === "critical");
      row.querySelector(".token-budget-fill").classList.toggle("low", state === "low");
      tokenBudgetEl.appendChild(row);
    });

    budgetSummaryDot.className = `budget-dot${worstState !== "good" ? ` ${worstState}` : ""}`;
    budgetSummaryText.textContent = `${available}/${models.length} models`;
  } catch (e) {
    // Non-critical - budget display just stays at its last known value.
  }
}

refreshTokenBudget();

const discoverContentEl = document.getElementById("discover-content");
const discoverRefreshBtn = document.getElementById("discover-refresh-btn");

function useDiscoveredVideo(video) {
  source = "url";
  tabs.forEach((t) => t.classList.toggle("active", t.dataset.source === "url"));
  urlInput.style.display = "";
  fileInput.style.display = "none";
  urlInput.value = video.url;
  location.hash = "#run";
  urlInput.focus();
}

// Fetches the video straight into input/ (same "download" run action the
// Input tab's own URL field uses) without running the pipeline on it yet -
// for queuing up something discovered here to process later from Input.
function downloadDiscoveredVideo(url) {
  terminalEl.innerHTML = "";
  clipsEl.innerHTML = "";
  clipCount = 0;
  clipCountEl.textContent = "";
  autoUploadHalted = false;
  setRunningUI(true);
  setStatus("running", "running");
  location.hash = "#run";
  openRunSocket({ action: "download", url }, false);
}

function buildDiscoverCard(video) {
  const card = document.createElement("div");
  card.className = "discover-card";
  const score = video.shorts_potential;
  card.innerHTML = `
    <img src="${video.thumbnail}" alt="">
    <div class="discover-body">
      <div class="discover-title">${escapeHtml(video.title)}</div>
      <div class="discover-meta">
        <span>${escapeHtml(video.channel)}</span>
        <span>${video.view_velocity.toLocaleString()} views/day</span>
        ${score != null ? `<span class="discover-score">${score}/10</span>` : ""}
      </div>
      ${video.reason ? `<div class="discover-reason">${escapeHtml(video.reason)}</div>` : ""}
      <div class="input-card-actions">
        <button class="discover-use-btn">Use</button>
        <button class="pill-btn discover-download-btn">Download</button>
      </div>
    </div>
  `;
  card.querySelector(".discover-use-btn").addEventListener("click", () => useDiscoveredVideo(video));
  card.querySelector(".discover-download-btn").addEventListener("click", () => downloadDiscoveredVideo(video.url));
  return card;
}

async function loadDiscover() {
  discoverLoadedOnce = true;
  discoverContentEl.innerHTML = `<div class="discover-loading">Loading...</div>`;
  try {
    const res = await fetch("/api/discover");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      discoverContentEl.innerHTML = `<div class="discover-empty">${escapeHtml(err.detail || "Could not load suggestions.")}</div>`;
      return;
    }
    const { videos } = await res.json();
    if (!videos.length) {
      discoverContentEl.innerHTML = `<div class="discover-empty">No videos found.</div>`;
      return;
    }
    discoverContentEl.innerHTML = "";
    videos.forEach((v) => discoverContentEl.appendChild(buildDiscoverCard(v)));
  } catch (e) {
    discoverContentEl.innerHTML = `<div class="discover-empty">Could not load suggestions.</div>`;
  }
}

discoverRefreshBtn.addEventListener("click", loadDiscover);

const selectedInputLabelEl = document.getElementById("selected-input-label");

function clearSelectedInput() {
  selectedInputPath = null;
  selectedInputLabelEl.style.display = "none";
  selectedInputLabelEl.innerHTML = "";
}

function useInputFile(file) {
  source = "file";
  tabs.forEach((t) => t.classList.toggle("active", t.dataset.source === "file"));
  urlInput.style.display = "none";
  fileInput.style.display = "none"; // hidden while a server-side file is selected instead
  fileInput.value = "";
  selectedInputPath = file.path;
  selectedInputLabelEl.innerHTML = `Using <strong>${escapeHtml(file.filename)}</strong> from input/ - <a href="#" id="clear-selected-input">choose a different file</a>`;
  selectedInputLabelEl.style.display = "";
  document.getElementById("clear-selected-input").addEventListener("click", (e) => {
    e.preventDefault();
    clearSelectedInput();
    fileInput.style.display = "";
  });
  location.hash = "#run";
}

function buildInputCard(file) {
  const card = document.createElement("div");
  card.className = "discover-card";
  const statusBits = [
    file.has_transcript ? "Transcribed" : "Not transcribed",
    file.plan_clip_count != null ? `${file.plan_clip_count} clip(s) planned` : "No plan yet",
  ];
  card.innerHTML = `
    ${file.thumbnail ? `<img src="${file.thumbnail}" alt="">` : `<div class="discover-card-noimg"></div>`}
    <div class="discover-body">
      <div class="discover-title">${escapeHtml(file.filename)}</div>
      <div class="discover-meta"><span>${file.size_mb} MB</span></div>
      <div class="discover-meta">${statusBits.map(escapeHtml).join(" &middot; ")}</div>
      <div class="input-card-actions">
        <button class="discover-use-btn">Use</button>
        <button class="pill-btn input-manage-btn">Manage</button>
        <button class="pill-btn input-delete-btn">Delete</button>
      </div>
    </div>
  `;
  card.querySelector(".discover-use-btn").addEventListener("click", () => useInputFile(file));
  card.querySelector(".input-manage-btn").addEventListener("click", () => openInputDetail(file));
  card.querySelector(".input-delete-btn").addEventListener("click", async () => {
    if (!confirm(`Delete ${file.filename} from input/? Its transcript and clip plan (if any) go with it. This can't be undone.`)) return;
    try {
      const res = await fetch(`/api/input-files/${encodeURIComponent(file.filename)}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        logLine(`[web] ${err.detail || "Could not delete this file."}`, "err");
        return;
      }
      card.remove();
      if (!inputContentEl.querySelector(".discover-card")) {
        inputContentEl.innerHTML = `<div class="discover-empty">No video files in input/ yet.</div>`;
      }
    } catch (e) {
      logLine("[web] Could not reach the server to delete this file.", "err");
    }
  });
  return card;
}

const inputContentEl = document.getElementById("input-content");
const inputRefreshBtn = document.getElementById("input-refresh-btn");

async function loadInputFiles() {
  inputLoadedOnce = true;
  inputContentEl.innerHTML = `<div class="discover-loading">Loading...</div>`;
  try {
    const res = await fetch("/api/input-files");
    if (!res.ok) {
      inputContentEl.innerHTML = `<div class="discover-empty">Could not load input files.</div>`;
      return;
    }
    const { files } = await res.json();
    if (!files.length) {
      inputContentEl.innerHTML = `<div class="discover-empty">No video files in input/ yet.</div>`;
      return;
    }
    inputContentEl.innerHTML = "";
    files.forEach((f) => inputContentEl.appendChild(buildInputCard(f)));
  } catch (e) {
    inputContentEl.innerHTML = `<div class="discover-empty">Could not load input files.</div>`;
  }
}

inputRefreshBtn.addEventListener("click", loadInputFiles);

document.getElementById("input-delete-all-btn").addEventListener("click", async () => {
  const count = inputContentEl.querySelectorAll(".discover-card").length;
  if (!count) return;
  if (!confirm(`Delete all ${count} video(s) from input/, plus their transcripts and clip plans? This can't be undone.`)) return;
  try {
    const res = await fetch("/api/input-files", { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      logLine(`[web] ${err.detail || "Could not delete input files."}`, "err");
      return;
    }
    inputContentEl.innerHTML = `<div class="discover-empty">No video files in input/ yet.</div>`;
  } catch (e) {
    logLine("[web] Could not reach the server to delete input files.", "err");
  }
});

const inputDownloadUrlEl = document.getElementById("input-download-url");
const inputDownloadBtn = document.getElementById("input-download-btn");
const inputProgressWrap = document.getElementById("input-progress-wrap");
const inputProgressFill = document.getElementById("input-progress-fill");
const inputProgressStatus = document.getElementById("input-progress-status");

// Which of the Input/Filler tabs' progress bars a "download" run's messages
// should update - both share the same download action/run_lock, so only one
// can ever be active, but the UI still needs to know which bar to drive.
let activeDownloadTarget = null; // 'input' | 'filler'

// Shared by the Input tab's own downloader, its search results' "Download"
// button, and the Filler tab's downloader/search - keeps the download running
// in-place on whichever tab started it (no navigating to Run) with a visible
// progress bar, same run_lock/cancel machinery as any other run.
function startDownload(url, target) {
  if (runBtn.disabled) {
    logLine("[web] A run is already in progress - wait for it to finish first.", "err");
    return;
  }
  activeDownloadTarget = target;
  const wrap = target === "filler" ? fillerProgressWrap : inputProgressWrap;
  const fill = target === "filler" ? fillerProgressFill : inputProgressFill;
  const status = target === "filler" ? fillerProgressStatus : inputProgressStatus;
  wrap.style.display = "";
  fill.style.width = "0%";
  status.textContent = "Starting download...";
  setRunningUI(true);
  setStatus("running", "running");
  openRunSocket({ action: "download", url, target }, false);
}

inputDownloadBtn.addEventListener("click", () => {
  const url = inputDownloadUrlEl.value.trim();
  if (!url) {
    logLine("[web] Paste a YouTube URL first.", "err");
    return;
  }
  startDownload(url, "input");
  inputDownloadUrlEl.value = "";
});

// --- Input tab search: a keyword search (same underlying YouTube search as
// the Filler tab's Discover, not the rights-verified curated Discover tab) -
// each result offers "Use" (send straight to the Run tab, no download needed)
// or "Download" (fetch into input/ with the progress bar above). ---
const inputDiscoverContentEl = document.getElementById("input-discover-content");
const inputDiscoverSearchBtn = document.getElementById("input-discover-search-btn");
const inputDiscoverQueryEl = document.getElementById("input-discover-query");

function buildInputDiscoverCard(video) {
  const card = document.createElement("div");
  card.className = "discover-card";
  card.innerHTML = `
    <img src="${video.thumbnail}" alt="">
    <div class="discover-body">
      <div class="discover-title">${escapeHtml(video.title)}</div>
      <div class="discover-meta">
        <span>${escapeHtml(video.channel)}</span>
        <span>${video.view_count.toLocaleString()} views</span>
      </div>
      <div class="input-card-actions">
        <button class="discover-use-btn">Use</button>
        <button class="pill-btn input-discover-download-btn">Download</button>
      </div>
    </div>
  `;
  card.querySelector(".discover-use-btn").addEventListener("click", () => useDiscoveredVideo(video));
  card.querySelector(".input-discover-download-btn").addEventListener("click", () => startDownload(video.url, "input"));
  return card;
}

async function loadInputDiscover() {
  const q = inputDiscoverQueryEl.value.trim();
  if (!q) {
    inputDiscoverContentEl.innerHTML = `<div class="discover-empty">Type something to search for.</div>`;
    return;
  }
  inputDiscoverContentEl.innerHTML = `<div class="discover-loading">Loading...</div>`;
  try {
    const res = await fetch(`/api/discover-input?q=${encodeURIComponent(q)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      inputDiscoverContentEl.innerHTML = `<div class="discover-empty">${escapeHtml(err.detail || "Could not load results.")}</div>`;
      return;
    }
    const { videos } = await res.json();
    if (!videos.length) {
      inputDiscoverContentEl.innerHTML = `<div class="discover-empty">No videos found.</div>`;
      return;
    }
    inputDiscoverContentEl.innerHTML = "";
    videos.forEach((v) => inputDiscoverContentEl.appendChild(buildInputDiscoverCard(v)));
  } catch (e) {
    inputDiscoverContentEl.innerHTML = `<div class="discover-empty">Could not load results.</div>`;
  }
}

inputDiscoverSearchBtn.addEventListener("click", loadInputDiscover);
inputDiscoverQueryEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadInputDiscover();
});

const inputDiscoverPanel = document.getElementById("input-discover-panel");
const inputDiscoverCollapseBtn = document.getElementById("input-discover-collapse-btn");
inputDiscoverCollapseBtn.addEventListener("click", () => {
  const collapsed = inputDiscoverPanel.classList.toggle("collapsed");
  inputDiscoverCollapseBtn.setAttribute("aria-expanded", String(!collapsed));
});

// --- Filler tab: your own gameplay/background footage for the split-screen
// clip layout - a keyword-search "Discover" (not rights-verified like the
// main Discover tab's curated channels), a URL downloader with a visible
// progress bar, a manual upload, and delete. ---
const fillerContentEl = document.getElementById("filler-content");
const fillerRefreshBtn = document.getElementById("filler-refresh-btn");
const fillerDiscoverContentEl = document.getElementById("filler-discover-content");
const fillerDiscoverRefreshBtn = document.getElementById("filler-discover-refresh-btn");
const fillerDiscoverQueryEl = document.getElementById("filler-discover-query");
const fillerDownloadUrlEl = document.getElementById("filler-download-url");
const fillerDownloadBtn = document.getElementById("filler-download-btn");
const fillerFileInputEl = document.getElementById("filler-file-input");
const fillerProgressWrap = document.getElementById("filler-progress-wrap");
const fillerProgressFill = document.getElementById("filler-progress-fill");
const fillerProgressStatus = document.getElementById("filler-progress-status");

function buildFillerCard(file) {
  const card = document.createElement("div");
  card.className = "discover-card";
  card.innerHTML = `
    ${file.thumbnail ? `<img src="${file.thumbnail}" alt="">` : `<div class="discover-card-noimg"></div>`}
    <div class="discover-body">
      <div class="discover-title">${escapeHtml(file.filename)}</div>
      <div class="discover-meta"><span>${file.size_mb} MB</span></div>
      <button class="pill-btn filler-delete-btn">Delete</button>
    </div>
  `;
  card.querySelector(".filler-delete-btn").addEventListener("click", async () => {
    if (!confirm(`Delete ${file.filename} from filler/? This can't be undone.`)) return;
    try {
      const res = await fetch(`/api/filler-files/${encodeURIComponent(file.filename)}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        logLine(`[web] ${err.detail || "Could not delete this file."}`, "err");
        return;
      }
      card.remove();
    } catch (e) {
      logLine("[web] Could not reach the server to delete this file.", "err");
    }
  });
  return card;
}

async function loadFillerFiles() {
  fillerLoadedOnce = true;
  fillerContentEl.innerHTML = `<div class="discover-loading">Loading...</div>`;
  try {
    const res = await fetch("/api/filler-files");
    if (!res.ok) {
      fillerContentEl.innerHTML = `<div class="discover-empty">Could not load filler files.</div>`;
      return;
    }
    const { files } = await res.json();
    if (!files.length) {
      fillerContentEl.innerHTML = `<div class="discover-empty">No filler footage in filler/ yet - download or upload some above.</div>`;
      return;
    }
    fillerContentEl.innerHTML = "";
    files.forEach((f) => fillerContentEl.appendChild(buildFillerCard(f)));
  } catch (e) {
    fillerContentEl.innerHTML = `<div class="discover-empty">Could not load filler files.</div>`;
  }
}

fillerRefreshBtn.addEventListener("click", loadFillerFiles);

function buildFillerDiscoverCard(video) {
  const card = document.createElement("div");
  card.className = "discover-card";
  card.innerHTML = `
    <img src="${video.thumbnail}" alt="">
    <div class="discover-body">
      <div class="discover-title">${escapeHtml(video.title)}</div>
      <div class="discover-meta">
        <span>${escapeHtml(video.channel)}</span>
        <span>${video.view_count.toLocaleString()} views</span>
      </div>
      <button class="discover-use-btn">Download</button>
    </div>
  `;
  card.querySelector(".discover-use-btn").addEventListener("click", () => startDownload(video.url, "filler"));
  return card;
}

async function loadFillerDiscover() {
  fillerDiscoverContentEl.innerHTML = `<div class="discover-loading">Loading...</div>`;
  try {
    const q = fillerDiscoverQueryEl.value.trim() || "minecraft parkour gameplay no copyright";
    const res = await fetch(`/api/discover-filler?q=${encodeURIComponent(q)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      fillerDiscoverContentEl.innerHTML = `<div class="discover-empty">${escapeHtml(err.detail || "Could not load suggestions.")}</div>`;
      return;
    }
    const { videos } = await res.json();
    if (!videos.length) {
      fillerDiscoverContentEl.innerHTML = `<div class="discover-empty">No videos found.</div>`;
      return;
    }
    fillerDiscoverContentEl.innerHTML = "";
    videos.forEach((v) => fillerDiscoverContentEl.appendChild(buildFillerDiscoverCard(v)));
  } catch (e) {
    fillerDiscoverContentEl.innerHTML = `<div class="discover-empty">Could not load suggestions.</div>`;
  }
}

fillerDiscoverRefreshBtn.addEventListener("click", loadFillerDiscover);
fillerDiscoverQueryEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadFillerDiscover();
});

const fillerDiscoverPanel = document.getElementById("filler-discover-panel");
const fillerDiscoverCollapseBtn = document.getElementById("filler-discover-collapse-btn");
fillerDiscoverCollapseBtn.addEventListener("click", () => {
  const collapsed = fillerDiscoverPanel.classList.toggle("collapsed");
  fillerDiscoverCollapseBtn.setAttribute("aria-expanded", String(!collapsed));
});

fillerDownloadBtn.addEventListener("click", () => {
  const url = fillerDownloadUrlEl.value.trim();
  if (!url) {
    logLine("[web] Paste a YouTube URL first.", "err");
    return;
  }
  startDownload(url, "filler");
  fillerDownloadUrlEl.value = "";
});

fillerFileInputEl.addEventListener("change", async () => {
  const file = fillerFileInputEl.files[0];
  if (!file) return;
  fillerProgressWrap.style.display = "";
  fillerProgressFill.style.width = "100%";
  fillerProgressStatus.textContent = `Uploading ${file.name}...`;
  try {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/upload-filler", { method: "POST", body: form });
    if (!res.ok) throw new Error("Upload failed");
    fillerProgressStatus.textContent = "Uploaded.";
    loadFillerFiles();
  } catch (e) {
    fillerProgressStatus.textContent = "";
    fillerProgressWrap.style.display = "none";
    logLine(`[web] ${e.message}`, "err");
  }
  fillerFileInputEl.value = "";
});

// --- Per-input detail view: transcribe on demand, copy the prompt for an
// outside model, paste its JSON result back as a real validated plan, cut
// clips straight from an existing plan, and see/upload just this file's
// clips - all without needing to run the whole pipeline over again. ---
const inputDetailOverlay = document.getElementById("input-detail-overlay");
const inputDetailTitle = document.getElementById("input-detail-title");
const inputDetailClose = document.getElementById("input-detail-close");
const detailTranscriptArea = document.getElementById("detail-transcript-area");
const detailMaxClipsEl = document.getElementById("detail-max-clips");
const detailPromptArea = document.getElementById("detail-prompt-area");
const detailPasteJson = document.getElementById("detail-paste-json");
const detailSavePlanBtn = document.getElementById("detail-save-plan-btn");
const detailPasteStatus = document.getElementById("detail-paste-status");
const detailPlanArea = document.getElementById("detail-plan-area");
const detailClipsArea = document.getElementById("detail-clips-area");

let currentDetailFile = null;

function closeInputDetail() {
  inputDetailOverlay.style.display = "none";
  currentDetailFile = null;
}
inputDetailClose.addEventListener("click", closeInputDetail);
inputDetailOverlay.addEventListener("click", (e) => {
  if (e.target === inputDetailOverlay) closeInputDetail();
});

async function copyToClipboard(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const original = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = original; }, 1500);
  } catch (e) {
    logLine(`[web] Could not copy to clipboard: ${e.message}`, "err");
  }
}

// Reuses the exact same run pipeline (Run tab's terminal, RunState replay,
// model fallback, etc.) for transcribing or cutting from a plan - these are
// just different "actions" on the same worker, not a separate mini-workflow.
function startInputAction(action, file, extra) {
  closeInputDetail();
  terminalEl.innerHTML = "";
  clipsEl.innerHTML = "";
  clipCount = 0;
  clipCountEl.textContent = "";
  autoUploadHalted = false;
  setRunningUI(true);
  setStatus("running", "running");
  location.hash = "#run";
  openRunSocket({ action, video_path: file.path, ...extra }, false);
}

// Clones the Run tab's Whisper model <select> (same options, single source
// of truth) so the Manage modal can pick a model for this one file without
// touching - or being silently overridden by - whatever's chosen on Run.
function buildWhisperModelSelect(id) {
  const source = document.getElementById("whisper-model");
  const clone = source.cloneNode(true);
  clone.id = id;
  clone.value = source.value; // cloneNode only copies the HTML-default selection, not the live one
  return clone;
}

async function openInputDetail(file) {
  currentDetailFile = file;
  inputDetailTitle.textContent = file.filename;
  inputDetailOverlay.style.display = "flex";
  detailPasteJson.style.display = "none";
  detailSavePlanBtn.style.display = "none";
  detailPasteStatus.textContent = "";

  if (file.has_transcript) {
    detailTranscriptArea.innerHTML = `
      <button class="pill-btn" id="detail-copy-transcript-btn">Copy transcript</button>
      <div class="field-row" style="margin-top:10px;align-items:flex-end">
        <div class="field" style="flex:0 0 auto;min-width:140px">
          <label for="detail-whisper-model">Re-transcribe with a different model</label>
          <span id="detail-whisper-model-slot"></span>
        </div>
        <button class="pill-btn" id="detail-retranscribe-btn">Re-transcribe</button>
      </div>
    `;
    document.getElementById("detail-copy-transcript-btn").addEventListener("click", async (e) => {
      try {
        const res = await fetch(`/api/input-file/${encodeURIComponent(file.stem)}/transcript`);
        const { text } = await res.json();
        copyToClipboard(text, e.target);
      } catch (err) {
        logLine("[web] Could not load transcript.", "err");
      }
    });
    const modelSelect = buildWhisperModelSelect("detail-whisper-model");
    document.getElementById("detail-whisper-model-slot").replaceWith(modelSelect);
    document.getElementById("detail-retranscribe-btn").addEventListener("click", () => {
      startInputAction("transcribe", file, { whisper_model: modelSelect.value });
    });
  } else {
    detailTranscriptArea.innerHTML = `
      <div class="field" style="max-width:200px">
        <label for="detail-whisper-model">Transcription model</label>
        <span id="detail-whisper-model-slot"></span>
      </div>
      <button class="upload-btn" id="detail-transcribe-btn" style="margin-top:10px">Transcribe</button>
    `;
    const modelSelect = buildWhisperModelSelect("detail-whisper-model");
    document.getElementById("detail-whisper-model-slot").replaceWith(modelSelect);
    document.getElementById("detail-transcribe-btn").addEventListener("click", () => {
      startInputAction("transcribe", file, { whisper_model: modelSelect.value });
    });
  }

  if (file.has_transcript) {
    detailMaxClipsEl.style.display = "";
    detailPromptArea.innerHTML = `
      <button class="pill-btn" id="detail-copy-system-btn">Copy system prompt</button>
      <button class="pill-btn" id="detail-copy-user-btn">Copy user prompt (transcript)</button>
    `;
    // Seeded from the Run tab's Max clips field so it starts at whatever
    // you'd get from a full pipeline run, but it's a real, visible, editable
    // field here - not a silently-inherited value the prompt just happens
    // to bake in without you ever having set it for this file.
    detailMaxClipsEl.value = document.getElementById("max-clips").value || "8";
    const minDur = parseFloat(document.getElementById("min-duration").value) || 30;
    const maxDur = parseFloat(document.getElementById("max-duration").value) || 45;
    let cachedPrompt = null;
    const getPrompt = async () => {
      if (cachedPrompt) return cachedPrompt;
      const maxClips = parseInt(detailMaxClipsEl.value, 10) || 8;
      const promptUrl = `/api/input-file/${encodeURIComponent(file.stem)}/prompt?max_clips=${maxClips}&min_duration=${minDur}&max_duration=${maxDur}`;
      const res = await fetch(promptUrl);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || typeof data.system !== "string" || typeof data.user !== "string") {
        throw new Error(data.detail || "Could not build the prompt for this file.");
      }
      cachedPrompt = data;
      return cachedPrompt;
    };
    detailMaxClipsEl.oninput = () => { cachedPrompt = null; };
    document.getElementById("detail-copy-system-btn").addEventListener("click", async (e) => {
      try {
        copyToClipboard((await getPrompt()).system, e.target);
      } catch (err) {
        logLine(`[web] ${err.message}`, "err");
      }
    });
    document.getElementById("detail-copy-user-btn").addEventListener("click", async (e) => {
      try {
        copyToClipboard((await getPrompt()).user, e.target);
      } catch (err) {
        logLine(`[web] ${err.message}`, "err");
      }
    });
    detailPasteJson.style.display = "";
    detailSavePlanBtn.style.display = "";
    detailPasteJson.value = "";
  } else {
    detailMaxClipsEl.style.display = "none";
    detailPromptArea.innerHTML = `<div class="analytics-empty">Transcribe this file first - the prompt needs the transcript.</div>`;
  }

  if (file.plan_clip_count != null) {
    detailPlanArea.innerHTML = `
      <div class="field-hint">${file.plan_clip_count} clip(s) planned.</div>
      <button class="upload-btn" id="detail-cut-btn">Cut clips from plan</button>
    `;
    document.getElementById("detail-cut-btn").addEventListener("click", () => {
      startInputAction("cut_plan", file, {
        plan_path: `clips/${file.stem}_plan.json`,
        transcript_path: file.has_transcript ? `transcripts/${file.stem}.json` : null,
        burn_captions: document.getElementById("burn-captions").checked,
        add_voiceover: document.getElementById("add-voiceover").checked,
      });
    });
  } else {
    detailPlanArea.innerHTML = `<div class="analytics-empty">No plan yet - paste a model's JSON response above, or run the full pipeline on this file from the Run tab.</div>`;
  }

  detailClipsArea.innerHTML = `<div class="analytics-empty">Loading...</div>`;
  try {
    const res = await fetch(`/api/existing-clips?stem=${encodeURIComponent(file.stem)}`);
    const { clips } = await res.json();
    detailClipsArea.innerHTML = clips.length ? "" : `<div class="analytics-empty">No clips cut for this file yet.</div>`;
    clips.forEach((clip) => detailClipsArea.appendChild(buildClipCard(clip, { track: false })));
  } catch (e) {
    detailClipsArea.innerHTML = `<div class="analytics-empty">Could not load clips.</div>`;
  }
}

detailSavePlanBtn.addEventListener("click", async () => {
  if (!currentDetailFile) return;
  const raw = detailPasteJson.value;
  if (!raw.trim()) {
    detailPasteStatus.textContent = "Paste the model's JSON response first.";
    return;
  }
  detailPasteStatus.textContent = "Validating...";
  try {
    const res = await fetch(`/api/input-file/${encodeURIComponent(currentDetailFile.stem)}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw }),
    });
    const data = await res.json();
    if (!res.ok) {
      detailPasteStatus.textContent = data.detail || "Could not validate the pasted plan.";
      return;
    }
    detailPasteStatus.textContent = `Saved - ${data.clips.length} clip(s) validated.`;
    currentDetailFile.plan_clip_count = data.clips.length;
    openInputDetail(currentDetailFile); // refresh the plan/clips sections in place
    loadInputFiles(); // refresh this file's card status badge in the background
  } catch (e) {
    detailPasteStatus.textContent = "Could not reach the server.";
  }
});

autoUploadEl.addEventListener("change", () => {
  autoPrivacyField.style.display = autoUploadEl.checked ? "" : "none";
});

fileInput.addEventListener("change", () => {
  // The user picked a real file through the native picker - that takes over
  // from whatever was selected via the Input tab's "Use" button, if anything.
  if (fileInput.files[0]) clearSelectedInput();
});

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    source = tab.dataset.source;
    tabs.forEach((t) => t.classList.toggle("active", t === tab));
    urlInput.style.display = source === "url" ? "" : "none";
    fileInput.style.display = source === "file" ? "" : "none";
    clearSelectedInput();
  });
});

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = `status ${cls}`;
}

function logLine(text, cls) {
  const line = document.createElement("div");
  if (cls) line.className = cls;
  line.textContent = text;
  terminalEl.appendChild(line);
  terminalEl.scrollTop = terminalEl.scrollHeight;
}

function buildClipCard(clip, { track = true } = {}) {
  const card = document.createElement("div");
  card.className = "clip-card";

  const durationSec = Math.round(clip.end - clip.start);
  const alreadyUploaded = Boolean(clip.youtube_video_id);
  const isSplitScreen = clip.format === "split_screen";
  card.innerHTML = `
    <video src="${clip.url}" controls preload="metadata"></video>
    <div class="clip-body">
      <div class="clip-title">${escapeHtml(clip.title)}</div>
      <div class="clip-meta">${durationSec}s &middot; ${escapeHtml(clip.video_path.split("/").pop())}${isSplitScreen ? " &middot; Split-screen" : ""}</div>
      <div class="clip-actions">
        <select class="privacy-select" ${alreadyUploaded ? "disabled" : ""}>
          <option value="public" selected>public</option>
          <option value="unlisted">unlisted</option>
          <option value="private">private</option>
        </select>
        <button class="upload-btn${alreadyUploaded ? " uploaded" : ""}">${alreadyUploaded ? "Uploaded" : "Upload"}</button>
      </div>
      ${!isSplitScreen && !alreadyUploaded
        ? `<div class="split-screen-row" style="margin-top:8px">
             <select class="filler-select"><option value="">Loading filler clips...</option></select>
             <button class="pill-btn split-screen-btn">Make split-screen version</button>
           </div>`
        : ""}
    </div>
  `;

  const uploadBtn = card.querySelector(".upload-btn");
  const privacySelect = card.querySelector(".privacy-select");

  if (alreadyUploaded) {
    uploadBtn.onclick = () => window.open(`https://www.youtube.com/watch?v=${clip.youtube_video_id}`, "_blank");
  } else {
    uploadBtn.addEventListener("click", () => {
      enqueueUpload(card, uploadBtn, privacySelect, clip);
    });
    // Tracked so "Upload all" (on the main Clips tab) can queue every
    // not-yet-uploaded clip currently shown there, without needing to
    // re-derive clip data from the DOM. A per-input detail view shows the
    // same underlying clips too, but opts out (track: false) - otherwise
    // the same clip would be queued twice, and the second attempt would
    // fail (the file/meta are deleted after the first upload succeeds).
    if (track) allClipEntries.push({ card, uploadBtn, privacySelect, clip });
  }

  // Split-tests the Minecraft-style split-screen layout against the normal
  // one on just this clip, instead of committing the whole channel to it -
  // the filler clip itself is chosen from the dropdown, but the start point
  // within it is always random, so reusing the same filler clip still gives
  // a different background each time.
  const splitBtn = card.querySelector(".split-screen-btn");
  const fillerSelect = card.querySelector(".filler-select");
  if (fillerSelect) {
    fetch("/api/filler-files")
      .then((r) => r.json())
      .then(({ files }) => {
        if (!files || !files.length) {
          fillerSelect.innerHTML = `<option value="">No filler clips - add some in the Filler tab</option>`;
          fillerSelect.disabled = true;
          splitBtn.disabled = true;
          return;
        }
        fillerSelect.innerHTML = files
          .map((f) => `<option value="${escapeHtml(f.filename)}">${escapeHtml(f.filename)}</option>`)
          .join("");
      })
      .catch(() => {
        fillerSelect.innerHTML = `<option value="">Could not load filler clips</option>`;
        fillerSelect.disabled = true;
        splitBtn.disabled = true;
      });
  }
  if (splitBtn) {
    splitBtn.addEventListener("click", () => makeSplitScreenVersion(card, splitBtn, fillerSelect, clip, track));
  }

  return card;
}

// Shared by a single card's "Make split-screen version" button and the
// Clips tab's "Split-screen all" bulk button, so the two can't drift -
// returns true/false so a bulk caller can tell success from failure without
// needing to inspect button state itself.
async function makeSplitScreenVersion(card, splitBtn, fillerSelect, clip, track) {
  splitBtn.disabled = true;
  splitBtn.textContent = "Making split-screen version...";
  try {
    const res = await fetch("/api/clips/split-screen", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meta_path: clip.meta_path, filler_filename: fillerSelect.value }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Could not make a split-screen version.");
    card.querySelector(".split-screen-row").remove();
    const newCard = buildClipCard(data, { track });
    card.insertAdjacentElement("afterend", newCard);
    if (track) {
      clipCount += 1;
      clipCountEl.textContent = `(${clipCount})`;
    }
    return true;
  } catch (e) {
    logLine(`[web] ${e.message}`, "err");
    splitBtn.disabled = false;
    splitBtn.textContent = "Make split-screen version";
    return false;
  }
}

document.getElementById("split-all-btn").addEventListener("click", async () => {
  // A fixed snapshot taken now - newly-created split-screen variants get
  // pushed into allClipEntries too (for their own "Upload all" tracking),
  // but iterating a snapshot instead of the live array means this loop
  // never picks up its own output and tries to split it again.
  const targets = allClipEntries.filter(
    ({ clip, uploadBtn }) => clip.format !== "split_screen" && !uploadBtn.classList.contains("uploaded")
  );
  if (!targets.length) {
    logLine("[web] No clips available to split-screen (already split-screen, or already uploaded).", "err");
    return;
  }

  const splitAllBtn = document.getElementById("split-all-btn");
  splitAllBtn.disabled = true;
  let done = 0;
  for (const { card, clip } of targets) {
    splitAllBtn.textContent = `Split-screen all (${done}/${targets.length})...`;
    const splitBtn = card.querySelector(".split-screen-btn");
    const fillerSelect = card.querySelector(".filler-select");
    if (splitBtn && !splitBtn.disabled && fillerSelect && fillerSelect.value) {
      // One at a time, not all at once - the same reasoning as uploadQueue:
      // several ffmpeg encodes running concurrently would hit CPU much
      // harder than doing them in sequence.
      await makeSplitScreenVersion(card, splitBtn, fillerSelect, clip, true);
    } else if (fillerSelect && !fillerSelect.value) {
      logLine(`[web] Skipped "${clip.title}" - no filler clip selected/available yet.`, "err");
    }
    done += 1;
  }
  splitAllBtn.disabled = false;
  splitAllBtn.textContent = "Split-screen all";
});

function addClipCard(clip) {
  clipCount += 1;
  clipCountEl.textContent = `(${clipCount})`;

  const card = buildClipCard(clip);
  clipsEl.appendChild(card);

  if (autoUploadEl.checked && !autoUploadHalted) {
    const uploadBtn = card.querySelector(".upload-btn");
    const privacySelect = card.querySelector(".privacy-select");
    privacySelect.value = autoPrivacyEl.value;
    enqueueUpload(card, uploadBtn, privacySelect, clip);
  }
}

// Clips already sitting in output/ from before this page was opened (a past
// CLI run, or clips left over from before a server restart) - shown on load
// so they don't need a fresh pipeline run just to be reviewed or uploaded.
async function loadExistingClips() {
  try {
    const res = await fetch("/api/existing-clips");
    if (!res.ok) return;
    const { clips } = await res.json();
    clips.forEach((clip) => {
      clipCount += 1;
      clipsEl.appendChild(buildClipCard(clip));
    });
    if (clipCount > 0) clipCountEl.textContent = `(${clipCount})`;
  } catch (e) {
    // Non-critical - existing clips just won't show until a run adds new ones.
  }
}

loadExistingClips();

const analyticsContentEl = document.getElementById("analytics-content");

// Fixed categorical color per hook mechanic (matches select_clips.py's five
// mechanics) - a stable identity color, not reassigned when a mechanic drops
// out of view, and "unknown" gets no vivid hue since it's really an "Other"
// bucket, not a named category.
const MECHANIC_COLORS = {
  open_loop: "var(--cat-1)",
  contrarian: "var(--cat-2)",
  stakes_or_numbers: "var(--cat-3)",
  mid_action: "var(--cat-4)",
  emotional_conflict: "var(--cat-5)",
};
function mechanicColor(mechanic) {
  return MECHANIC_COLORS[mechanic] || "var(--cat-other)";
}

// Local upload log (title, hook_mechanic, duration - things only we know,
// since YouTube has no concept of "hook_mechanic") enriched with real
// view/retention numbers from the YouTube Analytics API wherever available.
// Falls back to local-only counts if that API isn't enabled/authorized yet.
async function loadAnalytics() {
  try {
    const res = await fetch("/api/analytics");
    if (!res.ok) return;
    const {
      total_uploads, tracked_uploads, channel_count_available, live_data_available,
      records_with_stats, mechanic_insight, best_clip, worst_clip, duration_insight,
      title_insight, format_insight, hook_mechanics, recent,
    } = await res.json();

    if (total_uploads === 0) {
      analyticsContentEl.innerHTML = `<div class="analytics-empty">No uploads logged yet - this fills in as clips get uploaded to YouTube.</div>`;
      return;
    }

    const hasLiveNumbers = hook_mechanics.some((h) => h.avg_views != null);
    const barValue = (h) => (h.avg_views != null ? h.avg_views : h.count);
    const maxBarValue = Math.max(...hook_mechanics.map(barValue));

    const hookRows = [...hook_mechanics]
      .sort((a, b) => barValue(b) - barValue(a))
      .map((h) => {
        const color = mechanicColor(h.hook_mechanic);
        return `
        <div class="hook-bar-row">
          <div class="hook-bar-label">
            <span class="mechanic-name"><span class="mechanic-dot" style="background:${color}"></span>${escapeHtml(h.hook_mechanic)} (n=${h.count})</span>
            <span class="figures">${h.avg_views != null ? `${h.avg_view_percentage}% watched &middot; ${h.avg_views} views avg` : `${h.count} uploaded`}</span>
          </div>
          <div class="hook-bar-track"><div class="hook-bar-fill" style="width:${(barValue(h) / maxBarValue) * 100}%;background:${color}"></div></div>
        </div>
      `;
      }).join("");

    // Thumbnail straight from YouTube (i.ytimg.com's standard per-video path) -
    // the local file is long gone by upload time (deleted right after a
    // successful upload), so this is the only way to actually see the clip.
    const recentCards = recent.map((r) => `
      <a class="recent-card" href="${r.url}" target="_blank">
        <img src="https://i.ytimg.com/vi/${r.video_id}/mqdefault.jpg" alt="" loading="lazy">
        <div class="recent-card-body">
          <div class="recent-card-title">${escapeHtml(r.title)}</div>
          <div class="clip-meta">
            <span class="mechanic-dot" style="background:${mechanicColor(r.hook_mechanic)}"></span>${escapeHtml(r.hook_mechanic || "unknown")} &middot; ${r.duration_sec}s${r.views != null ? ` &middot; ${r.views} views &middot; ${r.avg_view_percentage}% watched` : ""}
          </div>
        </div>
      </a>
    `).join("");

    // The verdict - what to actually do with this data, not just a chart to
    // eyeball. Needs real per-clip stats to say anything; below that bar it
    // explains what's missing instead of showing an empty comparison.
    let verdictHtml = "";
    if (mechanic_insight) {
      const mi = mechanic_insight;
      verdictHtml += `
        <div class="verdict-card">
          <span class="mechanic-dot" style="background:${mechanicColor(mi.best_mechanic)}"></span>
          Your strongest hook mechanic is <strong>${escapeHtml(mi.best_mechanic)}</strong>
          at ${mi.best_pct}% avg retention - ${mi.gap} points ahead of
          <strong>${escapeHtml(mi.worst_mechanic)}</strong> (${mi.worst_pct}%).
        </div>`;
    }
    if (best_clip && worst_clip) {
      verdictHtml += `
        <div class="verdict-clips">
          <div class="verdict-clip good">
            <div class="verdict-clip-label">Best performing clip</div>
            <a href="${best_clip.url}" target="_blank">${escapeHtml(best_clip.title)}</a>
            <div class="clip-meta">${best_clip.avg_view_percentage}% watched &middot; ${best_clip.views} views</div>
          </div>
          <div class="verdict-clip bad">
            <div class="verdict-clip-label">Worst performing clip</div>
            <a href="${worst_clip.url}" target="_blank">${escapeHtml(worst_clip.title)}</a>
            <div class="clip-meta">${worst_clip.avg_view_percentage}% watched &middot; ${worst_clip.views} views</div>
          </div>
        </div>`;
    }
    if (duration_insight) {
      const di = duration_insight;
      const shorterWins = di.shorter_avg_pct >= di.longer_avg_pct;
      verdictHtml += `
        <div class="verdict-card">
          Your shorter clips (avg ${di.shorter_avg_duration}s) retain
          <strong>${di.shorter_avg_pct}%</strong> on average vs
          <strong>${di.longer_avg_pct}%</strong> for longer ones (avg ${di.longer_avg_duration}s) -
          ${shorterWins ? "shorter is winning so far." : "longer is winning so far."}
        </div>`;
    }
    if (title_insight) {
      const ti = title_insight;
      const numbersWin = ti.with_number_avg_pct >= ti.without_number_avg_pct;
      verdictHtml += `
        <div class="verdict-card">
          Titles with a concrete number (n=${ti.with_number_count}) retain
          <strong>${ti.with_number_avg_pct}%</strong> on average vs
          <strong>${ti.without_number_avg_pct}%</strong> for titles without one (n=${ti.without_number_count}) -
          ${numbersWin ? "specific numbers are winning so far." : "vaguer titles are winning so far, worth a look."}
        </div>`;
    }
    if (format_insight) {
      const fi = format_insight;
      const splitWins = fi.split_screen_avg_pct >= fi.normal_avg_pct;
      verdictHtml += `
        <div class="verdict-card">
          Split-screen clips (n=${fi.split_screen_count}) retain
          <strong>${fi.split_screen_avg_pct}%</strong> on average vs
          <strong>${fi.normal_avg_pct}%</strong> for the normal format (n=${fi.normal_count}) -
          ${splitWins ? "split-screen is winning so far, might be worth making the default." : "the normal format is still winning - not worth switching yet."}
        </div>`;
    }
    if (!verdictHtml) {
      const need = 2 - (records_with_stats || 0);
      verdictHtml = `<div class="analytics-empty">Not enough clips with real view data yet to draw a conclusion (need at least ${Math.max(need, 2)} - YouTube can take a day or so to process new uploads).</div>`;
    }

    analyticsContentEl.innerHTML = `
      <div>
        <div class="analytics-total-label" style="margin-bottom:10px">Verdict</div>
        ${verdictHtml}
      </div>
      <div>
        <div class="analytics-total">${total_uploads.toLocaleString()}</div>
        <div class="analytics-total-label">${channel_count_available ? "clips uploaded to your channel (all time)" : "clips logged (all time)"}</div>
      </div>
      <div>
        <div class="analytics-total-label" style="margin-bottom:8px">By hook mechanic${channel_count_available ? ` (${tracked_uploads} of ${total_uploads} tracked)` : ""}</div>
        ${hookRows}
      </div>
      <div>
        <div class="analytics-total-label" style="margin-bottom:8px">Recent uploads</div>
        <div class="recent-grid">${recentCards}</div>
      </div>
      ${channel_count_available ? `<div class="analytics-note">The hook-mechanic breakdown only covers clips uploaded through this pipeline since local tracking was added (${tracked_uploads} so far) - it has no way to know the hook mechanic of anything uploaded before that or through other means.</div>` : ""}
      ${!live_data_available ? `<div class="analytics-note">Showing local upload history only - real view/retention numbers need the YouTube Analytics API enabled and authorized.</div>` : ""}
      ${live_data_available && !hasLiveNumbers ? `<div class="analytics-note">YouTube Analytics API is connected, but no view data yet - it can take a day or so to process new uploads.</div>` : ""}
    `;
  } catch (e) {
    // Non-critical - analytics panel just stays at its last known state.
  }
}

loadAnalytics();

// Uploads run one at a time (queued) so auto-upload doesn't fire off several
// large resumable uploads in parallel and starve each other's bandwidth.
function enqueueUpload(card, uploadBtn, privacySelect, clip) {
  if (uploadBtn.disabled) return;
  uploadBtn.disabled = true;
  uploadBtn.textContent = "Queued...";
  uploadQueue = uploadQueue.then(() => startUpload(card, uploadBtn, privacySelect, clip));
}

document.getElementById("upload-all-btn").addEventListener("click", () => {
  // Same halt-on-quota-limit behavior as auto-upload: if one hits YouTube's
  // daily cap mid-batch, stop queuing the rest instead of repeating the same
  // failure for every remaining clip.
  for (const { uploadBtn, privacySelect, clip, card } of allClipEntries) {
    if (autoUploadHalted) break;
    // Skip anything already queued/uploading (disabled) or already uploaded
    // successfully - that button goes back to enabled afterward (it becomes
    // a "view on YouTube" link), so disabled alone can't tell the two apart.
    // "Failed - retry" ones are NOT skipped, they get a fresh attempt.
    if (uploadBtn.disabled || uploadBtn.classList.contains("uploaded")) continue;
    enqueueUpload(card, uploadBtn, privacySelect, clip);
  }
});

document.getElementById("clear-uploaded-btn").addEventListener("click", () => {
  // Just a view cleanup, nothing to delete - the local file/meta are already
  // gone from disk (server deletes them right after a successful upload), so
  // this only removes cards that are already marked "Uploaded" on screen.
  const uploadedCards = [...clipsEl.querySelectorAll(".clip-card")].filter(
    (card) => card.querySelector(".upload-btn")?.classList.contains("uploaded")
  );
  uploadedCards.forEach((card) => card.remove());

  clipCount -= uploadedCards.length;
  clipCountEl.textContent = clipCount > 0 ? `(${clipCount})` : "";

  for (let i = allClipEntries.length - 1; i >= 0; i--) {
    if (uploadedCards.includes(allClipEntries[i].card)) allClipEntries.splice(i, 1);
  }
});

document.getElementById("clear-all-btn").addEventListener("click", async () => {
  // Unlike "Clear uploaded" (a view-only cleanup - those files are already
  // gone from disk), this one actually deletes the not-yet-uploaded clips
  // sitting in output/ - the source video and clip plan are untouched, so
  // they can still be re-cut later, but the cut .mp4 itself is gone for real.
  const pendingCount = allClipEntries.filter(
    (e) => !e.uploadBtn.disabled && !e.uploadBtn.classList.contains("uploaded")
  ).length;
  const uploadInFlight = allClipEntries.some(
    (e) => e.uploadBtn.textContent === "Uploading..." || e.uploadBtn.textContent === "Queued..."
  );
  if (uploadInFlight) {
    logLine("[web] An upload is in progress - wait for it to finish before deleting all clips.", "err");
    return;
  }
  if (!confirm(
    `Delete ${pendingCount} not-yet-uploaded clip(s) from disk? This can't be undone - `
    + `you'd need to re-cut them from the plan to get them back.`
  )) {
    return;
  }

  try {
    const res = await fetch("/api/clips", { method: "DELETE" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      logLine(`[web] ${err.detail || "Could not delete clips."}`, "err");
      return;
    }
    const { deleted } = await res.json();
    clipsEl.innerHTML = "";
    clipCount = 0;
    clipCountEl.textContent = "";
    allClipEntries.length = 0;
    logLine(`[web] Deleted ${deleted} clip(s) from disk.`, "sys");
  } catch (e) {
    logLine("[web] Could not reach the server to delete clips.", "err");
  }
});

async function startUpload(card, uploadBtn, privacySelect, clip) {
  uploadBtn.textContent = "Uploading...";
  try {
    const res = await fetch("/api/upload-clip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ meta_path: clip.meta_path, privacy: privacySelect.value }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (res.status === 429) {
        autoUploadHalted = true;
        logLine(`[web] YouTube's daily upload limit was hit - skipping auto-upload for `
          + `any remaining clips in this run (you can still upload manually once it resets).`, "err");
      }
      throw new Error(err.detail || res.statusText);
    }
    const result = await res.json();
    uploadBtn.textContent = "Uploaded";
    uploadBtn.classList.add("uploaded");
    uploadBtn.onclick = () => window.open(result.url, "_blank");
    uploadBtn.disabled = false;
    privacySelect.disabled = true;
    // Server deletes the local file once it's live on YouTube.
    const video = card.querySelector("video");
    video.removeAttribute("src");
    video.load();
    const notice = document.createElement("div");
    notice.className = "clip-meta";
    notice.textContent = "Local file deleted (uploaded to YouTube)";
    card.querySelector(".clip-body").insertBefore(notice, card.querySelector(".clip-actions"));
    loadAnalytics();
  } catch (e) {
    uploadBtn.textContent = "Failed - retry";
    uploadBtn.classList.add("failed");
    uploadBtn.disabled = false;
    logLine(`[upload] ${clip.title}: ${e.message}`, "err");
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

async function uploadSourceFile(file) {
  logLine(`[web] Uploading ${file.name}...`, "sys");
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/upload-video", { method: "POST", body: form });
  if (!res.ok) throw new Error("File upload failed");
  const data = await res.json();
  logLine(`[web] Upload complete -> ${data.path}`, "sys");
  return data.path;
}

// Shared by both a freshly-started run and a "watch" reconnect that's
// replaying/following an already-active one, so the two paths can't drift.
function handleRunMessage(msg) {
  if (msg.type === "log") {
    logLine(msg.line);
  } else if (msg.type === "clip") {
    addClipCard(msg.clip);
  } else if (msg.type === "download_progress") {
    if (activeDownloadTarget === "filler" && fillerProgressWrap.style.display !== "none") {
      fillerProgressFill.style.width = `${msg.percent != null ? msg.percent : 0}%`;
      fillerProgressStatus.textContent = msg.percent != null ? `Downloading... ${msg.percent}%` : "Downloading...";
    } else if (activeDownloadTarget === "input" && inputProgressWrap.style.display !== "none") {
      inputProgressFill.style.width = `${msg.percent != null ? msg.percent : 0}%`;
      inputProgressStatus.textContent = msg.percent != null ? `Downloading... ${msg.percent}%` : "Downloading...";
    }
  } else if (msg.type === "done") {
    if (msg.video_path) {
      logLine(`[web] Downloaded -> ${msg.video_path}`, "sys");
    } else {
      logLine(`[web] Done. ${msg.count} clip(s) produced.`, "sys");
    }
    setStatus("done", "done");
    setRunningUI(false);
    refreshTokenBudget();
    loadAnalytics();
    // A transcribe/cut_plan action (or a full run) can change a file's
    // transcript/plan status - refresh the Input tab's cards so reopening
    // "Manage" on that file doesn't show stale has_transcript/plan info.
    if (inputLoadedOnce) loadInputFiles();
    if (fillerLoadedOnce && activeDownloadTarget === "filler" && fillerProgressWrap.style.display !== "none") {
      fillerProgressStatus.textContent = "Done.";
      fillerProgressWrap.style.display = "none";
      loadFillerFiles();
    }
    if (activeDownloadTarget === "input" && inputProgressWrap.style.display !== "none") {
      inputProgressStatus.textContent = "Done.";
      inputProgressWrap.style.display = "none";
      loadInputFiles();
    }
    activeDownloadTarget = null;
  } else if (msg.type === "stopped") {
    logLine("[web] Run stopped.", "sys");
    setStatus("stopped", "idle");
    setRunningUI(false);
    refreshTokenBudget();
    loadAnalytics();
    if (inputLoadedOnce) loadInputFiles();
    fillerProgressWrap.style.display = "none";
    inputProgressWrap.style.display = "none";
    activeDownloadTarget = null;
  } else if (msg.type === "error") {
    logLine(`[web] Error: ${msg.message}`, "err");
    setStatus("error", "error");
    setRunningUI(false);
    refreshTokenBudget();
    loadAnalytics();
    fillerProgressWrap.style.display = "none";
    inputProgressWrap.style.display = "none";
    activeDownloadTarget = null;
  }
}

function openRunSocket(config, watch) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/run`);

  ws.addEventListener("open", () => ws.send(JSON.stringify(watch ? { watch: true } : config)));
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "idle") return; // watched, but nothing turned out to be running
    handleRunMessage(msg);
  });
  ws.addEventListener("close", () => {
    if (statusEl.classList.contains("running")) setStatus("idle", "idle");
    setRunningUI(false);
  });
  ws.addEventListener("error", () => {
    logLine("[web] WebSocket connection error.", "err");
  });
}

runBtn.addEventListener("click", async () => {
  let videoPath;
  if (source === "url") {
    videoPath = urlInput.value.trim();
    if (!videoPath) {
      logLine("[web] Enter a YouTube URL first.", "err");
      return;
    }
  } else if (selectedInputPath) {
    // Already on the server (picked via the Input tab) - use it directly,
    // no browser upload needed.
    videoPath = selectedInputPath;
  } else {
    const file = fileInput.files[0];
    if (!file) {
      logLine("[web] Choose a file first.", "err");
      return;
    }
    setRunningUI(true);
    try {
      videoPath = await uploadSourceFile(file);
    } catch (e) {
      logLine(`[web] ${e.message}`, "err");
      setRunningUI(false);
      return;
    }
  }

  const config = {
    video_path: videoPath,
    max_clips: parseInt(document.getElementById("max-clips").value, 10),
    whisper_model: document.getElementById("whisper-model").value,
    min_duration: parseFloat(document.getElementById("min-duration").value),
    max_duration: parseFloat(document.getElementById("max-duration").value),
    burn_captions: document.getElementById("burn-captions").checked,
    add_voiceover: document.getElementById("add-voiceover").checked,
  };

  terminalEl.innerHTML = "";
  clipsEl.innerHTML = "";
  clipCount = 0;
  clipCountEl.textContent = "";
  autoUploadHalted = false;
  setRunningUI(true);
  setStatus("running", "running");

  openRunSocket(config, false);
});

// A run started before this page loaded (an earlier reload, or another tab)
// has no way to tell a brand-new page load about itself unless something
// asks - so ask: replay whatever it's logged so far, then keep watching it
// live, instead of just showing idle while the terminal quietly disagrees.
async function resumeActiveRunIfAny() {
  try {
    const res = await fetch("/api/run-status");
    if (!res.ok) return;
    const { active, log } = await res.json();
    if (!active) return;

    terminalEl.innerHTML = "";
    clipsEl.innerHTML = "";
    clipCount = 0;
    clipCountEl.textContent = "";
    autoUploadHalted = false;
    setRunningUI(true);
    setStatus("running", "running");

    log.forEach(handleRunMessage);
    openRunSocket(null, true);
  } catch (e) {
    // Non-critical - worst case this page just shows idle until the next run.
  }
}
resumeActiveRunIfAny();

// Now that every element reference and loader function above is initialized,
// it's safe to show whichever page the URL hash points to (or "run" if none).
showPage(location.hash.slice(1) || "run");
