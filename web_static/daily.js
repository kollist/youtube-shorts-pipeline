// Daily job tab: pause/resume the automatic poster, edit the SCP queue, hold an episode until a date.
const dailyEl = document.getElementById("daily-content");

async function dailyApi(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { alert(data.detail || "Something went wrong."); return null; }
  return data;
}

async function loadDaily() {
  try { renderDaily(await (await fetch("/api/daily")).json()); } catch (e) { dailyEl.textContent = "Could not reach the server."; }
}

function renderDaily(d) {
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const eps = d.episodes.map((e) => {
    const state = e.posted ? "posted" : e.hold ? `held until ${esc(e.hold)}` : e.built ? (e.number === d.ready ? "next to post" : "built, waiting") : "not built";
    const hold = e.posted ? "" : e.hold
      ? `<button class="s-btn" data-release="${e.number}">Release</button>`
      : `<input type="date" data-hold-date="${e.number}"> <button class="s-btn" data-hold="${e.number}">Hold until</button>`;
    return `<tr><td>${e.number}</td><td>${esc(e.scp)} ${esc(e.title)}</td><td>${state}</td><td>${e.tiktok ? esc(e.tiktok) + (e.tiktok === "posted by hand" ? "" : ` <button class="s-btn" data-resend="${e.number}">Resend</button>`) + (e.tiktok.startsWith("in your inbox") ? ` <button class="s-btn" data-mark="${e.number}" data-plats="tiktok">I posted it by hand</button>` : "") : ""}</td><td>${hold} ${e.posted ? "" : `<button class="s-btn" data-mark="${e.number}" data-plats="">I posted this by hand</button>`}</td></tr>`;
  }).join("");
  const recent = d.recent.map((r) => `<li><b>${esc(r.kind)}</b> ${r.episode ? "ep " + r.episode : ""} <span class="s-note">${esc(r.at)} ${esc(r.title || r.error || "")}</span></li>`).join("");
  dailyEl.innerHTML = `
    <div class="daily-status ${d.paused ? "paused" : "running"}">
      <b>${d.paused ? "⏸ Paused - nothing will build or post" : "▶ Running"}</b>
      <button class="s-btn ${d.paused ? "primary" : ""}" id="daily-toggle">${d.paused ? "Resume" : "Pause"}</button>
      <span class="s-note">Now ${esc(d.now_et)} US Eastern - ${esc(d.window)}</span>
    </div>
    <h3>Queue (built top to bottom, one per day)</h3>
    <textarea id="daily-queue" rows="3" placeholder="SCP numbers, e.g. 939, 087, 023">${esc(d.queue.join(", "))}</textarea>
    <div class="s-row"><button class="s-btn primary" id="daily-save">Save queue</button><span class="s-note">${d.queue.length} left</span></div>
    <h3>Episodes</h3>
    <table class="daily-table"><tr><th>#</th><th>SCP</th><th>State</th><th>TikTok draft</th><th></th></tr>${eps}</table>
    <h3>Recent activity</h3><ul class="daily-recent">${recent || "<li class='s-note'>Nothing yet.</li>"}</ul>`;
  dailyEl.querySelector("#daily-toggle").onclick = async () => { const r = await dailyApi("/api/daily/pause", { paused: !d.paused }); if (r) renderDaily(r); };
  dailyEl.querySelector("#daily-save").onclick = async () => {
    const q = dailyEl.querySelector("#daily-queue").value.split(/[\s,;]+/).filter(Boolean);
    const r = await dailyApi("/api/daily/queue", { queue: q }); if (r) renderDaily(r);
  };
  dailyEl.querySelectorAll("[data-hold]").forEach((b) => b.onclick = async () => {
    const until = dailyEl.querySelector(`[data-hold-date="${b.dataset.hold}"]`).value;
    if (!until) { alert("Pick a date first."); return; }
    const r = await dailyApi("/api/daily/hold", { episode: +b.dataset.hold, until }); if (r) renderDaily(r);
  });
  dailyEl.querySelectorAll("[data-resend]").forEach((b) => b.onclick = async () => {
    b.disabled = true; b.textContent = "Sending (1-2 min)...";
    const r = await dailyApi("/api/daily/tiktok-resend", { episode: +b.dataset.resend });
    if (r) { alert(r.note); loadDaily(); } else { b.disabled = false; b.textContent = "Resend"; }
  });
  dailyEl.querySelectorAll("[data-mark]").forEach((b) => b.onclick = async () => {
    if (!b.dataset.plats && !confirm(`Mark episode ${b.dataset.mark} as posted on every platform? The daily job will never post it.`)) return;
    const r = await dailyApi("/api/daily/mark-posted", { episode: +b.dataset.mark, platforms: b.dataset.plats ? [b.dataset.plats] : [] });
    if (r) renderDaily(r);
  });
  dailyEl.querySelectorAll("[data-release]").forEach((b) => b.onclick = async () => {
    const r = await dailyApi("/api/daily/hold", { episode: +b.dataset.release, until: null }); if (r) renderDaily(r);
  });
}
