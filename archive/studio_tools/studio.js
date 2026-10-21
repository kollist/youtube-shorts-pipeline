// Studio tab - four video engines behind one gallery of tools:
//   1. Stock-footage video   (MoneyPrinterTurbo, MIT)         - topic -> script -> footage -> voice -> subtitles -> video
//   2. Stickman explainer    (kaomei/stickman-video-director) - topic -> 5-stage script -> stickman pictures -> video
//   3. Seedance prompt library (ZeroLu/awesome-seedance, MIT) - cinematic prompts: copy, make a still, use as script style
//   4. Wan2GP bridge         (deepbeepmeep/Wan2GP)            - real motion for a picture, on a GPU machine (lives inside each Series episode)

const studioContentEl = document.getElementById("studio-content");
let studio = { status: null, seedance: null, open: null, query: "", category: "All", fillerFiles: [], styleKey: "2A" };

function startStudioAction(action, extra) {
  terminalEl.innerHTML = "";
  setRunningUI(true);
  setStatus("running", "running");
  window.studioReturnPending = true;
  location.hash = "#run";
  openRunSocket({ action, ...extra }, false);
}

async function loadStudio() {
  try {
    const [st, fl] = await Promise.all([fetch("/api/studio/status"), fetch("/api/filler-files")]);
    if (st.ok) studio.status = await st.json();
    if (fl.ok) studio.fillerFiles = (await fl.json()).files || [];
  } catch (e) { return; }
  renderStudio();
}

const sEsc = (t) => escapeHtml(String(t ?? ""));

function toolTiles() {
  const s = studio.status;
  const mpt = s.mpt.running ? "helper running" : s.mpt.installed ? "installed" : "needs setup (once)";
  const tiles = [
    ["footage", "Stock-footage video", "Topic in, finished video out: script, matching footage, voice, subtitles and music.", `MoneyPrinterTurbo · ${mpt}`, "linear-gradient(150deg,#1e3a2f,#0b1511)"],
    ["stickman", "Stickman explainer", "A 60-second explainer with a consistent stick figure, written with a proven 5-stage hook structure.", `stickman-video-director · ${Object.keys(s.stickman.styles).length} styles`, "linear-gradient(150deg,#2b2a3f,#0d0d14)"],
    ["blender", "3D explainer (free)", "Clean 3D scale explainers - 'how tall is...', 'what if...' - rendered in Blender on this Mac, with checked numbers and a narrator.", s.blender ? "Blender installed · renders ~10+ min" : "needs Blender (one-time install)", "linear-gradient(150deg,#1c3a3a,#08120f)"],
    ["parable", "Parable story", "A tiny original fable with animal characters, the moral in one line, then the same lesson in real life - ending on a question that gets comments.", "Claude writes it · pictures drawn locally", "linear-gradient(150deg,#1f2c3a,#0a0e14)"],
    ["motion", "Motion graphics (free)", "Animated yearbook pages, phone chats, lock-screen texts and glowing-eyed faces - drawn by code, no AI model, no cost, no GPU.", "drawn locally · voice by edge-tts", "linear-gradient(150deg,#3a1d22,#0f0809)"],
    ["seedance", "Prompt library", `${s.seedance.count} cinematic prompts: copy them, turn one into a picture, or use one as the style of your next script.`, "awesome-seedance", "linear-gradient(150deg,#3b2a1c,#120d09)"],
    ["wan", "Real motion", "Turn pictures into real video clips with the free daily credits of Kling or Google Flow (Series → an episode → Animate with free web tools), or with Wan2GP if you have a GPU. Nothing here costs money.", "free web tools · Wan2GP bridge", "linear-gradient(150deg,#1d2f3f,#0a1118)"],
  ];
  return tiles.map(([key, title, desc, meta, gradient]) => `
    <article class="st-tile" data-act="open-tool" data-tool="${key}" style="background-image:${gradient}">
      <div class="st-tile-meta">${sEsc(meta)}</div>
      <div><h3>${sEsc(title)}</h3><p>${sEsc(desc)}</p></div>
    </article>`).join("");
}

function resultsStrip() {
  const vids = studio.status.faceless;
  if (!vids.length) return "";
  return `<h2 class="s-h2">Your finished videos</h2>
    <div class="st-results">${vids.map((v) => `
      <div class="st-result">
        <video src="/media/faceless/${encodeURIComponent(v.file)}" controls preload="metadata"></video>
        <div class="st-result-body"><b>${sEsc(v.title)}</b><span class="s-note">${v.size_mb} MB</span>
          <button class="s-btn" data-act="post-faceless" data-file="${sEsc(v.file)}">Post…</button>
          <button class="s-btn s-danger" data-act="delete-faceless" data-file="${sEsc(v.file)}" title="Delete this video">Delete</button></div>
      </div>`).join("")}</div>`;
}

function stillsStrip() {
  const stills = studio.status.stills || [];
  if (!stills.length) return "";
  return `<h2 class="s-h2">Pictures from the prompt library</h2>
    <div class="st-stills">${stills.map((f) => `<a href="/media/stills/${encodeURIComponent(f)}" target="_blank" rel="noopener"><img src="/media/stills/${encodeURIComponent(f)}" loading="lazy" alt=""></a>`).join("")}</div>`;
}

function renderStudio() {
  if (!studio.status) return;
  studioContentEl.innerHTML = `
    <div class="s-hero"><div><h1>Studio</h1><p>Video engines wired into this app. Pick a tool.</p></div></div>
    <div class="st-grid">${toolTiles()}</div>
    ${resultsStrip()}
    ${stillsStrip()}
    ${studio.open ? toolModal(studio.open) : ""}`;
  document.body.classList.toggle("s-lock", !!studio.open);
}

// ------------------------------------------------------------ tool panels

function toolModal(tool) {
  const body = { footage: footagePanel, stickman: stickmanPanel, blender: blenderPanel, parable: parablePanel, motion: motionPanel, seedance: seedancePanel, wan: wanPanel }[tool]();
  return `<div class="s-studio-bg" data-act="close-tool"></div>
    <div class="s-studio s-create st-modal" role="dialog"><button class="s-x" data-act="close-tool" aria-label="Close">✕</button>${body}</div>`;
}

function footagePanel() {
  const s = studio.status.mpt;
  const setup = !s.installed ? `
    <div class="s-box"><div class="s-label">One-time setup</div>
      <p class="s-note">Downloads MoneyPrinterTurbo (MIT licence) into <code>third_party/</code> and installs it in its own environment - a few hundred MB, a few minutes. Nothing is installed into your main environment.</p>
      <div class="s-row"><button class="s-btn primary" data-act="mpt-setup">Install MoneyPrinterTurbo</button></div></div>` : "";
  const files = studio.fillerFiles.map((f) => `<label class="st-check"><input type="checkbox" class="st-local" value="filler/${sEsc(f.filename)}"> ${sEsc(f.filename)}</label>`).join("")
    || `<span class="s-note">No clips yet - add some on the Filler tab.</span>`;
  return `<h2>Stock-footage video</h2>
    <p class="s-note">Engine: <a href="https://github.com/harry0703/MoneyPrinterTurbo" target="_blank" rel="noopener">MoneyPrinterTurbo</a> (MIT). The script and footage keywords are written by this app's own model; the helper finds the footage, speaks it, adds subtitles and music, and assembles the video.</p>
    ${setup}
    <div class="s-form">
      <label class="wide">Topic<input id="ft-topic" type="text" placeholder="3 habits that quietly make you richer" /></label>
      <label class="wide">…or paste your own script (skips the AI writer)<textarea id="ft-script" rows="3"></textarea></label>
      <label>Footage from<select id="ft-source"><option value="pexels">Pexels stock footage (free key)</option><option value="local">My own clips</option></select></label>
      <label>Voice<select id="ft-voice">${studio.status.mpt.voices.map((v) => `<option>${sEsc(v)}</option>`).join("")}</select></label>
      <label>Length<select id="ft-seconds"><option value="30">about 30 s</option><option value="45" selected>about 45 s</option><option value="60">about 60 s</option></select></label>
      <label>Shape<select id="ft-aspect"><option value="9:16">Vertical 9:16</option><option value="16:9">Wide 16:9</option></select></label>
      <div class="wide s-note" id="ft-pexels-note">${s.pexels_key ? "Pexels key found." : "No Pexels key yet: add a free one to <code>.env</code> as <code>PEXELS_API_KEY</code> (pexels.com/api), then restart the server."}</div>
      <div class="wide" id="ft-local" style="display:none"><div class="s-label" style="margin-bottom:6px">Your clips</div><div class="st-checks">${files}</div></div>
      <label class="st-check wide"><input type="checkbox" id="ft-subs" checked> Subtitles</label>
      <label class="st-check wide"><input type="checkbox" id="ft-music" checked> Background music</label>
    </div>
    <button class="s-btn primary" data-act="run-footage" ${s.installed ? "" : "disabled"}>${s.installed ? "Generate video" : "Install first"}</button>`;
}

function stickmanPanel() {
  const st = studio.status.stickman;
  const order = ["1A", "1B", "2A", "2B", "3", "4"];
  const styles = order.filter((k) => st.styles[k]).map((k) => [k, st.styles[k]]).map(([k, name]) =>
    `<button type="button" class="s-pitch ${k === studio.styleKey ? "on" : ""}" data-act="pick-style" data-style="${k}"><b>${sEsc(k)}</b><span>${sEsc(name)}</span></button>`).join("");
  return `<h2>Stickman explainer</h2>
    <p class="s-note">Method: <a href="https://github.com/kaomei/stickman-video-director" target="_blank" rel="noopener">stickman-video-director</a> (MIT) - a 5-stage structure (hook → shatter the assumption → insider secret → ultimate truth → discussion), ~10-second beats, and a frozen character look. It's written as a story in the <b>Series</b> tab, where you make the pictures and render the video. It also saves its beats as plain clip prompts (<code>clip_prompts.md</code>) you can paste into a hosted video model.</p>
    <div class="s-pitches">${styles}</div>
    <div class="s-form">
      <label class="wide">Topic<input id="sk-topic" type="text" placeholder="Why do we procrastinate even when we know better?" /></label>
      <label>Length<select id="sk-seconds"><option value="30">30 s (3 beats)</option><option value="60" selected>60 s (6 beats)</option><option value="90">90 s (9 beats)</option></select></label>
      <label>Narrator voice<select id="sk-voice">${st.voices.map((v) => `<option ${v === "adult_man" ? "selected" : ""}>${sEsc(v)}</option>`).join("")}</select></label>
    </div>
    <button class="s-btn primary" data-act="run-stickman">Write the explainer</button>`;
}

function blenderPanel() {
  const voices = studio.status.stickman.voices;
  if (!studio.status.blender) {
    return `<h2>3D explainer (free)</h2><p class="s-note">This needs Blender, a free 3D program, installed once on this Mac. In a terminal run <code>brew install --cask blender</code>, then restart the server. Everything else is already in this app.</p>`;
  }
  return `<h2>3D explainer (free)</h2>
    <p class="s-note">Type a "how big / how tall / what if" question. Claude writes the narration and a Blender scene (one composed 3D shot per sentence), checks it with a quick test render, then renders the video on this Mac - expect ten minutes or more. It lists every number it used and how it derived it, so <b>check the facts</b> in the result before you post. The look is clean and simple, not film-studio CGI.</p>
    <div class="s-form">
      <label class="wide">Question<input id="bl-topic" type="text" placeholder="How tall would a stack of a billion dollar bills be?" /></label>
      <label>Narrator voice<select id="bl-voice">${voices.map((v) => `<option ${v === "adult_man" ? "selected" : ""}>${sEsc(v)}</option>`).join("")}</select></label>
      <label class="st-check wide"><input type="checkbox" id="bl-music" checked> Background music</label>
    </div>
    <button class="s-btn primary" data-act="run-blender">Write and render the 3D video</button>`;
}

function parablePanel() {
  const voices = studio.status.stickman.voices;
  return `<h2>Parable story</h2>
    <p class="s-note">Fable → moral → "and this is how it works on people" → a question for the comments. The writer invents the fable (it never claims it's ancient or from a real source). It saves a story in the <b>Series</b> tab, where you make the pictures (about 40 s each, free, on this Mac) and render the video. Type the lesson you want it to prove.</p>
    <div class="s-form">
      <label class="wide">The lesson / idea<input id="pb-theme" type="text" placeholder="people who spread fear are the ones who control you" /></label>
      <label>Narrator voice<select id="pb-voice">${voices.map((v) => `<option ${v === "adult_man" ? "selected" : ""}>${sEsc(v)}</option>`).join("")}</select></label>
    </div>
    <button class="s-btn primary" data-act="run-parable">Write the parable</button>`;
}

function motionPanel() {
  const voices = studio.status.stickman.voices;
  return `<h2>Motion graphics (free)</h2>
    <p class="s-note">The same look as the code-made "Yearbook" short: generated faces on aged pages, a phone chat with typing dots, a lock-screen text, MISSING stamps, a zoom into glowing eyes. Claude (your subscription) writes the script, this app draws every frame, edge-tts speaks it. Nothing is paid and nothing is uploaded. Takes ~3-4 minutes to draw. Best for creepy / mystery / text-message stories; it's not a general-purpose video maker.</p>
    <div class="s-form">
      <label class="wide">Story idea<input id="mg-topic" type="text" placeholder="A group chat that keeps receiving messages from a number that was disconnected in 2009" /></label>
      <label>Narrator voice<select id="mg-voice">${voices.map((v) => `<option ${v === "adult_man" ? "selected" : ""}>${sEsc(v)}</option>`).join("")}</select></label>
      <label class="st-check wide"><input type="checkbox" id="mg-music" checked> Background music</label>
    </div>
    <button class="s-btn primary" data-act="run-motion">Write and draw the video</button>`;
}

function seedancePanel() {
  const lib = studio.seedance;
  if (!lib) { fetch("/api/studio/seedance").then((r) => r.json()).then((d) => { studio.seedance = d; renderStudio(); }); return `<h2>Prompt library</h2><p class="s-note">Loading…</p>`; }
  const cats = ["All", ...new Set(lib.prompts.map((p) => p.category))];
  const q = studio.query.toLowerCase();
  const list = lib.prompts.filter((p) => (studio.category === "All" || p.category === studio.category)
    && (!q || (p.title + " " + p.prompt + " " + p.category).toLowerCase().includes(q)));
  const refId = localStorage.getItem("seedanceRef");
  return `<h2>Prompt library</h2>
    <p class="s-note">${sEsc(lib.attribution)} These are prompts for ByteDance's Seedance video model - which runs on their servers, not here. Here you can copy one to use there, turn one into a picture with the local image model, or use one as the <b>shot style</b> for your next AI-written episode.</p>
    <div class="s-row wrap" style="margin:10px 0"><input id="sd-search" type="text" placeholder="Search prompts…" value="${sEsc(studio.query)}" style="max-width:260px">
      ${cats.map((c) => `<button class="discover-pill ${c === studio.category ? "on" : ""}" data-act="sd-cat" data-cat="${sEsc(c)}">${sEsc(c)}</button>`).join("")}</div>
    <div class="st-prompts">${list.map((p) => `
      <div class="st-prompt">
        <div class="s-meta">${sEsc(p.category)}${p.source ? " · " + sEsc(p.source) : ""}</div>
        <h4>${sEsc(p.title)}</h4>
        <p class="s-note">${sEsc(p.description)}</p>
        <pre>${sEsc(p.prompt.slice(0, 420))}${p.prompt.length > 420 ? "…" : ""}</pre>
        <div class="s-row wrap">
          <button class="s-btn" data-act="sd-copy" data-id="${sEsc(p.id)}">Copy prompt</button>
          <button class="s-btn" data-act="sd-still" data-id="${sEsc(p.id)}">Make a still</button>
          <button class="s-btn ${refId === p.id ? "primary" : ""}" data-act="sd-ref" data-id="${sEsc(p.id)}">${refId === p.id ? "✓ Style for next script" : "Use as script style"}</button>
          ${p.source_url ? `<a class="s-note" href="${sEsc(p.source_url)}" target="_blank" rel="noopener">source</a>` : ""}
        </div>
      </div>`).join("") || `<div class="s-note">No prompts match.</div>`}</div>`;
}

function wanPanel() {
  const models = Object.values(studio.status.wan.models).map((m) => `<li>${sEsc(m)}</li>`).join("");
  return `<h2>Real motion</h2>
    <div class="s-box"><div class="s-label">Option 1 - free web tools (recommended)</div>
      <p class="s-note">Series → open an episode → <b>Animate with free web tools</b>. Claude writes a motion prompt for every scene and marks the 3-4 best to animate. For each: download the picture, paste it with the prompt into the image-to-video of Kling or Google Flow (their free daily credits - allowances change, check their pages), download the ~5 s clip and drop it on the scene. About 10 minutes a day, no cost, no account with us.</p></div>
    <div class="s-label" style="margin:16px 0 4px">Option 2 - Wan2GP (free software, needs an NVIDIA GPU you already have)</div>
    <p class="s-note"><a href="https://github.com/deepbeepmeep/Wan2GP" target="_blank" rel="noopener">Wan2GP</a> turns a still picture into a few seconds of real video (moving hair, blinking eyes, travelling camera). It needs an NVIDIA graphics card, so it <b>can't run on your Mac</b> - you run it on a GPU machine you control (a PC you own, or a free Colab or Kaggle GPU) and this app exchanges files with it.</p>
    <div class="s-box"><div class="s-label">How it works</div>
      <ol class="s-note" style="margin:0;padding-left:18px;line-height:1.7">
        <li>Series → open an episode → <b>Wan clips</b> → <b>Download job pack</b> (a zip of your pictures + a queue file).</li>
        <li>On the GPU machine: <code>python wgp.py --process wan_jobs.zip --dry-run</code>, then without <code>--dry-run</code>.</li>
        <li>Upload each finished clip against its scene number. <b>Render video</b> then uses it for that scene.</li>
      </ol>
      <div class="s-label" style="margin-top:12px">Models offered in the pack</div><ul class="s-note" style="margin:0;padding-left:18px">${models}</ul></div>
    <div class="s-box"><div class="s-label">Licence - please read</div>
      <p class="s-note">Wan2GP's <b>software</b> is licensed for non-commercial use, so this app never copies or bundles it - you install it yourself. The <b>videos it produces</b> may be used commercially, but a commercial release must say it was made with WanGP; this app adds that line to the description automatically when Wan clips are used.</p></div>
    <p class="s-note">The job-file format follows WanGP's own docs but hasn't been tested against a real install (no GPU here) - the <code>--dry-run</code> step will tell you if anything needs adjusting.</p>`;
}

// ------------------------------------------------------------ events

studioContentEl.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.disabled) return;
  const act = el.dataset.act;
  if (act === "open-tool") { studio.open = el.dataset.tool; renderStudio(); }
  else if (act === "close-tool") { studio.open = null; renderStudio(); }
  else if (act === "mpt-setup") startStudioAction("mpt_setup", {});
  else if (act === "run-footage") {
    const source = document.getElementById("ft-source").value;
    const local = [...studioContentEl.querySelectorAll(".st-local:checked")].map((c) => c.value);
    const topic = document.getElementById("ft-topic").value.trim(), script = document.getElementById("ft-script").value.trim();
    if (!topic && !script) { alert("Give a topic, or paste a script."); return; }
    if (source === "local" && !local.length) { alert("Tick at least one of your clips."); return; }
    studio.open = null;
    startStudioAction("faceless_generate", { topic, script, source, local_files: local, voice: document.getElementById("ft-voice").value,
      seconds: +document.getElementById("ft-seconds").value, aspect: document.getElementById("ft-aspect").value,
      subtitles: document.getElementById("ft-subs").checked, music: document.getElementById("ft-music").checked });
  } else if (act === "pick-style") { studio.styleKey = el.dataset.style; renderStudio(); }
  else if (act === "run-stickman") {
    const topic = document.getElementById("sk-topic").value.trim();
    if (!topic) { alert("What's the topic?"); return; }
    studio.open = null;
    window.seriesReturnPending = true;       // finish on the Series tab, where the new story appears
    startStudioAction("explainer_create", { topic, style: studio.styleKey, seconds: +document.getElementById("sk-seconds").value,
                                            voice: document.getElementById("sk-voice").value });
    window.studioReturnPending = false;
  } else if (act === "run-blender") {
    const topic = document.getElementById("bl-topic").value.trim();
    if (!topic) { alert("What's the question?"); return; }
    studio.open = null;
    startStudioAction("blender_create", { topic, voice: document.getElementById("bl-voice").value, music: document.getElementById("bl-music").checked });
  } else if (act === "run-parable") {
    const theme = document.getElementById("pb-theme").value.trim();
    if (!theme) { alert("What lesson should the parable prove?"); return; }
    studio.open = null;
    window.seriesReturnPending = true;       // finish on the Series tab, where the new story appears
    startStudioAction("parable_create", { theme, voice: document.getElementById("pb-voice").value });
    window.studioReturnPending = false;
  } else if (act === "run-motion") {
    const topic = document.getElementById("mg-topic").value.trim();
    if (!topic) { alert("What's the story idea?"); return; }
    studio.open = null;
    startStudioAction("motion_create", { topic, voice: document.getElementById("mg-voice").value, music: document.getElementById("mg-music").checked });
  } else if (act === "sd-cat") { studio.category = el.dataset.cat; renderStudio(); }
  else if (act === "sd-copy") {
    const p = studio.seedance.prompts.find((x) => x.id === el.dataset.id);
    copyToClipboard(Promise.resolve(p.prompt), el);
  } else if (act === "sd-still") {
    studio.open = null;
    startStudioAction("seedance_still", { id: el.dataset.id });
  } else if (act === "sd-ref") {
    const same = localStorage.getItem("seedanceRef") === el.dataset.id;
    try { same ? localStorage.removeItem("seedanceRef") : localStorage.setItem("seedanceRef", el.dataset.id); } catch (err) {}
    renderStudio();
  } else if (act === "delete-faceless") {
    const file = el.dataset.file, v = (studio.status.faceless || []).find((x) => x.file === file);
    if (!confirm(`Delete "${(v && v.title) || file}"?\n\nThe video file is removed from this computer. This can't be undone.`)) return;
    el.disabled = true; el.textContent = "Deleting…";
    const res = await fetch(`/api/studio/faceless/${encodeURIComponent(file)}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json().catch(() => ({})); alert(d.detail || "Could not delete."); }
    loadStudio();
  } else if (act === "post-faceless") {
    const file = el.dataset.file, v = (studio.status.faceless || []).find((x) => x.file === file);
    openPostDialog({ title: (v && v.title) || file, captionReq: { kind: "studio", file },
      cleanupLabel: "Delete this video after it posts",
      send: async (platforms, privacy, captions, cleanup) => {
      const res = await fetch("/api/studio/faceless/post", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file, platforms, privacy, captions, cleanup }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Could not post");
      return data;
    } });
  }
});

studioContentEl.addEventListener("input", (e) => {
  if (e.target.id === "sd-search") { studio.query = e.target.value; const pos = e.target.selectionStart; renderStudio(); const box = document.getElementById("sd-search"); box.focus(); box.setSelectionRange(pos, pos); }
});
studioContentEl.addEventListener("change", (e) => {
  if (e.target.id === "ft-source") {
    document.getElementById("ft-local").style.display = e.target.value === "local" ? "" : "none";
    document.getElementById("ft-pexels-note").style.display = e.target.value === "pexels" ? "" : "none";
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && studio.open && document.getElementById("page-studio").classList.contains("active")) { studio.open = null; renderStudio(); }
});
window.addEventListener("hashchange", () => { if (location.hash !== "#studio") document.body.classList.remove("s-lock"); });
if (location.hash === "#studio") loadStudio();
