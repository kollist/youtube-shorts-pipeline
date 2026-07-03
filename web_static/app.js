const statusEl = document.getElementById("status");
const terminalEl = document.getElementById("terminal");
const runBtn = document.getElementById("run-btn");
const clipsEl = document.getElementById("clips");
const clipCountEl = document.getElementById("clip-count");

const urlInput = document.getElementById("url-input");
const fileInput = document.getElementById("file-input");
const tabs = document.querySelectorAll(".tab");

let source = "url";
let clipCount = 0;

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    source = tab.dataset.source;
    tabs.forEach((t) => t.classList.toggle("active", t === tab));
    urlInput.style.display = source === "url" ? "" : "none";
    fileInput.style.display = source === "file" ? "" : "none";
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

function addClipCard(clip) {
  clipCount += 1;
  clipCountEl.textContent = `(${clipCount})`;

  const card = document.createElement("div");
  card.className = "clip-card";

  const durationSec = Math.round(clip.end - clip.start);
  card.innerHTML = `
    <video src="${clip.url}" controls preload="metadata"></video>
    <div class="clip-body">
      <div class="clip-title">${escapeHtml(clip.title)}</div>
      <div class="clip-meta">${durationSec}s &middot; ${escapeHtml(clip.video_path.split("/").pop())}</div>
      <div class="clip-actions">
        <select class="privacy-select">
          <option value="public" selected>public</option>
          <option value="unlisted">unlisted</option>
          <option value="private">private</option>
        </select>
        <button class="upload-btn">Upload</button>
      </div>
    </div>
  `;

  const uploadBtn = card.querySelector(".upload-btn");
  const privacySelect = card.querySelector(".privacy-select");

  uploadBtn.addEventListener("click", async () => {
    uploadBtn.disabled = true;
    uploadBtn.textContent = "Uploading...";
    try {
      const res = await fetch("/api/upload-clip", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meta_path: clip.meta_path, privacy: privacySelect.value }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
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
    } catch (e) {
      uploadBtn.textContent = "Failed - retry";
      uploadBtn.classList.add("failed");
      uploadBtn.disabled = false;
      logLine(`[upload] ${clip.title}: ${e.message}`, "err");
    }
  });

  clipsEl.appendChild(card);
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

runBtn.addEventListener("click", async () => {
  let videoPath;
  if (source === "url") {
    videoPath = urlInput.value.trim();
    if (!videoPath) {
      logLine("[web] Enter a YouTube URL first.", "err");
      return;
    }
  } else {
    const file = fileInput.files[0];
    if (!file) {
      logLine("[web] Choose a file first.", "err");
      return;
    }
    runBtn.disabled = true;
    try {
      videoPath = await uploadSourceFile(file);
    } catch (e) {
      logLine(`[web] ${e.message}`, "err");
      runBtn.disabled = false;
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
  };

  terminalEl.innerHTML = "";
  clipsEl.innerHTML = "";
  clipCount = 0;
  clipCountEl.textContent = "";
  runBtn.disabled = true;
  setStatus("running", "running");

  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/run`);

  ws.addEventListener("open", () => ws.send(JSON.stringify(config)));

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "log") {
      logLine(msg.line);
    } else if (msg.type === "clip") {
      addClipCard(msg.clip);
    } else if (msg.type === "done") {
      logLine(`[web] Done. ${msg.count} clip(s) produced.`, "sys");
      setStatus("done", "done");
      runBtn.disabled = false;
    } else if (msg.type === "error") {
      logLine(`[web] Error: ${msg.message}`, "err");
      setStatus("error", "error");
      runBtn.disabled = false;
    }
  });

  ws.addEventListener("close", () => {
    if (statusEl.classList.contains("running")) {
      setStatus("idle", "idle");
    }
    runBtn.disabled = false;
  });

  ws.addEventListener("error", () => {
    logLine("[web] WebSocket connection error.", "err");
  });
});
