// Series tab - poster grid -> series page with an episode strip -> an episode "studio".
// Writing, picture-making and rendering run as background jobs on the Run tab (they stream
// their log there), then return here.

const seriesContentEl = document.getElementById("series-content");
let seriesData = { series: [], pitches: [] };
let seriesView = { slug: null, number: null, creating: false };   // what's open
let studioStage = "auto";
let createKind = "story";                 // "story" (AI-written) or "scp" (Foundation tapes) in the create dialog
                                          // which video the studio stage shows

function startSeriesAction(action, extra) {
  resetOutput();
  setRunningUI(true);
  setStatus("running", "running");
  window.seriesReturnPending = true;       // handleRunMessage sends you back here when it finishes
  location.hash = "#run";
  openRunSocket({ action, ...extra }, false);
}

async function loadSeries() {
  try {
    const res = await fetch("/api/series");
    if (!res.ok) return;
    seriesData = await res.json();
  } catch (e) { return; }
  renderSeries();
}

const mediaUrl = (rel) => `/media/stories/${rel.split("/").map(encodeURIComponent).join("/")}`;
const firstImage = (ep) => ep && ep.images ? Object.values(ep.images)[0] : null;
const seriesCover = (s) => { for (const ep of s.episodes) { const i = firstImage(ep); if (i) return i; } return null; };
const gradientFor = (text) => { let h = 0; for (const c of text) h = (h * 31 + c.charCodeAt(0)) % 360; return `linear-gradient(160deg, hsl(${h} 35% 16%), hsl(${(h + 40) % 360} 40% 7%))`; };
const bg = (rel, fallbackText) => rel ? `background-image:url('${mediaUrl(rel)}')` : `background-image:${gradientFor(fallbackText)}`;
const epPictures = (ep) => `${(ep.images_done || []).length}/${ep.scene_count || 0}`;

function seriesProgress(s) {
  const scripted = s.episodes.filter((e) => e.has_script);
  const total = scripted.reduce((n, e) => n + e.scene_count, 0);
  const done = scripted.reduce((n, e) => n + e.images_done.length, 0);
  return total ? done / total : 0;
}

// ---------------------------------------------------------------- views

function viewList() {
  const cards = seriesData.series.map((s) => {
    const ready = s.episodes.filter((e) => e.video).length;
    return `<article class="s-poster" data-act="open-series" data-slug="${escapeHtml(s.slug)}" style="${bg(seriesCover(s), s.title)}">
      <div class="s-poster-top">${s.standalone ? "Single story" : escapeHtml(s.genre || "Series")}</div>
      <div class="s-poster-bottom">
        <h3>${escapeHtml(s.title)}</h3>
        <div class="s-meta">${s.episodes.length} episode${s.episodes.length > 1 ? "s" : ""} · ${ready} ready</div>
        <div class="s-bar"><i style="width:${Math.round(seriesProgress(s) * 100)}%"></i></div>
      </div>
    </article>`;
  }).join("");
  return `
    <div class="s-hero">
      <div><h1>Series</h1><p>AI story videos: a cast, a look and a plan - one 60-second episode at a time.</p></div>
      <button class="s-btn primary" data-act="new-series">＋ Create series</button>
    </div>
    <div class="s-grid">
      <article class="s-poster s-new" data-act="new-series"><div class="s-plus">＋</div><div class="s-meta">New series</div></article>
      ${cards}
    </div>`;
}

function viewSeries(s) {
  const cover = seriesCover(s);
  const nextEp = s.episodes.find((e) => !e.video && !e.posted);
  const eps = s.episodes.map((ep) => {
    const img = firstImage(ep);
    const dots = [ep.has_script, ep.has_script && ep.images_done.length === ep.scene_count, !!ep.preview, !!ep.video]
      .map((on, i) => `<i class="${on ? "on" : ""}" title="${["script", "pictures", "preview", "video"][i]}"></i>`).join("");
    return `<article class="s-ep ${ep.has_script ? "" : "planned"}" data-act="open-ep" data-slug="${escapeHtml(s.slug)}" data-number="${ep.number}" style="${ep.has_script ? bg(img, ep.title || "") : ""}">
      <div class="s-poster-top">PART ${ep.number}</div>
      ${ep.has_script ? "" : `<div class="s-plus small">＋</div>`}
      <div class="s-poster-bottom">
        <h4>${escapeHtml(ep.title || ep.planned_title || "Untitled")}</h4>
        <div class="s-meta">${ep.has_script ? `pictures ${epPictures(ep)}` : "not written yet"}</div>
        <div class="s-dots">${dots}</div>
      </div>
    </article>`;
  }).join("");
  return `
    <button class="s-back" data-act="back">← All series</button>
    <header class="s-banner" style="${bg(cover, s.title)}">
      <div class="s-banner-in">
        <div class="s-meta">${escapeHtml(s.format === "scp" ? "SCP Foundation · CC BY-SA 3.0" : (s.genre || (s.standalone ? "Single story" : "Series")))}</div>
        <h1>${escapeHtml(s.title)}</h1>
        ${s.logline ? `<p>${escapeHtml(s.logline)}</p>` : ""}
        <div class="s-chips">${s.characters.map((c) => `<span>${escapeHtml(c)}</span>`).join("")}</div>
        ${s.standalone ? "" : `<div class="s-row wrap"><button class="s-btn" data-act="toggle-add">＋ Add episode</button></div>
        <div class="s-add" hidden>
          <input id="add-hint" type="text" placeholder="${s.format === "scp" ? "SCP numbers, e.g. 096, 049" : "Optional idea for the new episode (empty = the AI continues the story)"}" />
          <button class="s-btn primary" data-act="add-episode" data-slug="${escapeHtml(s.slug)}" data-scp="${s.format === "scp" ? 1 : 0}">Add</button>
          <span class="s-note s-add-status"></span>
        </div>`}
        <button class="s-btn s-danger" data-act="delete-series" data-slug="${escapeHtml(s.slug)}" title="Delete this whole ${s.standalone ? "story" : "series"}">Delete ${s.standalone ? "story" : "series"}</button>
        ${nextEp ? `<button class="s-btn primary s-big" data-act="auto-next" data-slug="${escapeHtml(s.slug)}" data-number="${nextEp.number}">▶ Make episode ${nextEp.number} - one click</button>
        <div class="s-note">Writes it, makes the pictures and renders the video (about 15-40 min on this Mac). Then you review it and press Post.</div>` : `<div class="s-note">Every episode has a video ✓</div>`}
      </div>
    </header>
    <h2 class="s-h2">Episodes</h2>
    <div class="s-strip">${eps}</div>`;
}

function studioStageHtml(ep) {
  const mode = studioStage === "auto" ? (ep.video ? "final" : ep.preview ? "preview" : "board") : studioStage;
  const tabs = [ep.video ? ["final", "Final"] : null, ep.preview ? ["preview", "Preview"] : null, ["board", "Storyboard"]].filter(Boolean)
    .map(([k, label]) => `<button class="s-tab ${k === mode ? "on" : ""}" data-act="stage" data-stage="${k}">${label}</button>`).join("");
  let stage;
  if (mode === "final" && ep.video) stage = `<video src="${mediaUrl(ep.video)}?t=${ep.video.length}" controls autoplay muted playsinline></video>`;
  else if (mode === "preview" && ep.preview) stage = `<video src="${mediaUrl(ep.preview)}" controls playsinline></video>`;
  else {
    const img = firstImage(ep);
    stage = img ? `<div class="s-stage-img" style="background-image:url('${mediaUrl(img)}')"><span>Storyboard</span></div>`
                : `<div class="s-stage-img" style="background-image:${gradientFor(ep.title || "")}"><span>No pictures yet</span></div>`;
  }
  return `<div class="s-stage">${stage}</div><div class="s-tabs">${tabs}</div>`;
}

function viewStudio(s, ep) {
  const scp = s.format === "scp";
  const left = ep.scene_count - ep.images_done.length;
  const steps = [["Script", ep.has_script], ["Pictures", ep.has_script && !left, ep.has_script ? epPictures(ep) : ""], ["Preview", !!ep.preview], ["Video", !!ep.video]]
    .map(([name, on, extra]) => `<div class="s-step ${on ? "on" : ""}"><b></b>${name}${extra ? ` <em>${extra}</em>` : ""}</div>`).join("");
  const tiles = Array.from({ length: ep.scene_count }, (_, k) => {
    const i = k + 1, img = ep.images && ep.images[i];
    const moving = (ep.motion_clips || []).includes(i);
    return img ? `<div class="s-tile" style="background-image:url('${mediaUrl(img)}')"><span>${i}${moving ? " 🎬" : ""}</span><button data-act="redo" data-scene="${i}" title="Remake this picture">↻</button></div>`
               : `<div class="s-tile empty"><span>${i}</span></div>`;
  }).join("");
  const post = ep.video ? `
    <div class="s-box">
      <div class="s-label">Publish</div>
      <div class="s-row">
        <button class="s-btn primary" data-act="post">Post…</button>
      </div>
      <div class="s-note s-post-result"></div>
    </div>` : "";
  return `
  <div class="s-studio-bg" data-act="close-studio"></div>
  <div class="s-studio" role="dialog">
    <button class="s-x" data-act="close-studio" aria-label="Close">✕</button>
    <div class="s-studio-left">${studioStageHtml(ep)}</div>
    <div class="s-studio-right" data-slug="${escapeHtml(s.slug)}" data-number="${ep.number}">
      <div class="s-meta">${s.standalone ? "Single story" : `${escapeHtml(s.title)} · PART ${ep.number}`}</div>
      <h2>${escapeHtml(ep.title || ep.planned_title)}</h2>
      ${ep.has_script ? `<blockquote>“${escapeHtml(ep.hook || "")}”</blockquote><p class="s-note">${escapeHtml(ep.summary || "")}</p>` : `<p class="s-note">${escapeHtml(ep.planned_summary || "")}</p>`}
      <div class="s-steps">${steps}</div>
      ${(ep.video || (ep.images_done && ep.images_done.length)) ? `<div class="s-row wrap"><button class="s-btn s-danger" data-act="clear-ep" title="Deletes this episode's video and pictures; keeps the script">Delete this episode's video &amp; pictures</button></div>` : ""}
      ${ep.posted ? `<div class="s-box"><b>Posted ✓</b> <span class="s-note">${Object.entries((ep.posted.results) || {}).map(([n, r]) => r.url ? `<a href="${r.url}" target="_blank" rel="noopener">${n}</a>` : n).join(" · ")} · its video and pictures were deleted to save space; the script is kept.</span></div>` : ""}
      ${ep.video || ep.posted ? "" : `<div class="s-row wrap"><button class="s-btn primary s-big" data-act="auto-ep">▶ Make this episode - one click</button></div>
      <div class="s-note">${ep.has_script ? (left ? "Makes the missing pictures, then renders the video." : "Renders the video.") : "Writes it, makes the pictures, renders the video."}</div>`}
      ${ep.has_script ? `
      <div class="s-label">Storyboard <span class="s-note">· tap ↻ on a picture to remake it</span></div>
      <div class="s-tiles">${tiles}</div>
      <div class="s-row wrap">
        ${scp ? "" : `<button class="s-btn" data-act="preview">▶ Preview (fast)</button>`}
        <button class="s-btn primary" data-act="images" ${left ? "" : "disabled"}>${left ? `Make ${left} picture${left > 1 ? "s" : ""} · ~${Math.max(1, Math.round(left * 0.75))} min` : "Pictures done ✓"}</button>
        <button class="s-btn primary" data-act="render" ${left ? "disabled" : ""}>${scp ? "Render tape" : "Render video"}</button>
      </div>` : `
      <div class="s-row wrap"><button class="s-btn primary" data-act="write">${scp ? "✦ Fetch from the wiki &amp; adapt" : "✦ Write with AI"}</button></div>`}
      ${post}
      ${ep.has_script && ep.images_done.length ? animateBox(s, ep) : ""}
            ${scp ? "" : `<details class="s-box"><summary>Script tools</summary>
        <div class="s-row wrap" style="margin-top:10px">
          ${ep.has_script ? `<button class="s-btn" data-act="rewrite">Rewrite with AI</button>` : ""}
          <button class="s-btn" data-act="copy-prompt">Copy writing prompt</button>
          <button class="s-btn" data-act="paste">Paste a script…</button>
        </div>
        <div class="s-paste" style="display:none">
          <textarea rows="6" placeholder="Paste the episode JSON the outside model returned…"></textarea>
          <button class="s-btn primary" data-act="save-paste">Check &amp; save</button><span class="s-note s-paste-status"></span>
        </div>
      </details>`}
    </div>
  </div>`;
}

// Real animation with the FREE daily credits of web tools (Kling, Google Flow/Veo, Dreamina...). Nothing is automated on the tool's
// side: you paste each prompt there with the picture, download the clip, and drop it on its scene. Scenes without a clip keep
// the app's own depth-parallax motion, so animate only the "hero" shots.
function animateBox(s, ep) {
  const have = (ep.motion_clips || []).length;
  return `<details class="s-box s-animate" data-slug="${escapeHtml(s.slug)}" data-number="${ep.number}" data-clips="${(ep.motion_clips || []).join(",")}"><summary>Animate with free web tools ${have ? `(${have} clips in use)` : ""}</summary>
    <p class="s-note">Free daily credits on Kling or Google Flow turn a picture into a ~5 second moving clip. Claude writes a motion prompt for each scene and marks the best 3-4 to animate. For each one: download the picture, paste it with the prompt into the tool's <b>image-to-video</b>, download the clip, drop it here. Free allowances change often - check the tool's page.</p>
    <div class="s-row wrap"><button class="s-btn primary" data-act="shots-plan">Write motion prompts with Claude</button><span class="s-note s-shots-status"></span></div>
    <div class="s-shots" data-loaded="0"></div></details>`;
}

async function loadShots(box) {
  const list = box.querySelector(".s-shots");
  if (list.dataset.loaded === "1") return;
  list.dataset.loaded = "1";
  const res = await fetch(`/api/series/${encodeURIComponent(box.dataset.slug)}/episode/${box.dataset.number}/shots`);
  if (res.ok) renderShots(box, (await res.json()).shots);
}

function renderShots(box, shots) {
  const clips = (box.dataset.clips || "").split(",").filter(Boolean).map(Number);
  box.querySelector(".s-shots").innerHTML = shots.map((x) => `
    <div class="s-shot ${x.hero ? "hero" : ""}">
      ${x.has_picture ? `<a href="/media/stories/${x.picture}" download="scene${x.scene}.png"><img src="/media/stories/${x.picture}" alt="Scene ${x.scene}" loading="lazy"></a>` : ""}
      <div class="s-shot-head"><b>Scene ${x.scene}</b> ${clips.includes(x.scene) ? `<span class="series-chip ok">clip in use 🎬</span>` : ""} ${x.hero ? `<span class="series-chip ok">animate this one</span>` : `<span class="series-chip">keeps depth motion</span>`} <span class="s-note">~${x.seconds}s of narration</span></div>
      <textarea data-shot-prompt="${x.scene}" rows="6">${escapeHtml(x.prompt)}</textarea>
      <div class="s-row wrap">
        <button class="s-btn" data-act="shot-copy" data-scene="${x.scene}">Copy prompt</button>
        ${x.has_picture ? `<a class="s-btn" href="/media/stories/${x.picture}" download="scene${x.scene}.png">Download picture</a>` : ""}
        <label class="s-btn">Upload clip<input type="file" accept="video/*" data-motion-scene="${x.scene}" hidden></label>
      </div></div>`).join("") || `<p class="s-note">Press the button above to write the prompts.</p>`;
}

seriesContentEl.addEventListener("change", async (e) => {
  const clip = e.target.closest("[data-motion-scene]");
  if (clip && clip.files.length) {
    const box = clip.closest(".s-animate"), status = box.querySelector(".s-shots-status");
    status.textContent = `Uploading scene ${clip.dataset.motionScene}…`;
    const form = new FormData();
    form.append("file", clip.files[0]);
    const res = await fetch(`/api/series/${encodeURIComponent(box.dataset.slug)}/episode/${box.dataset.number}/motion/${clip.dataset.motionScene}`, { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { status.textContent = data.detail || "Upload failed."; return; }
    await loadSeries();
    return;
  }
  const promptBox = e.target.closest("[data-shot-prompt]");
  if (promptBox) {
    const box = promptBox.closest(".s-animate");
    await fetch(`/api/series/${encodeURIComponent(box.dataset.slug)}/episode/${box.dataset.number}/shots/${promptBox.dataset.shotPrompt}/prompt`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: promptBox.value }) });
    return;
  }
});

function viewCreate() {
  const scp = createKind === "scp";
  const pitches = seriesData.pitches.map((p, i) => `
    <button type="button" class="s-pitch" data-act="pitch" data-i="${i}">
      <b>${escapeHtml(p.title)}</b><span>${escapeHtml(p.genre)}</span><em>${escapeHtml(p.premise.slice(0, 120))}…</em>
    </button>`).join("");
  const kinds = `<div class="s-kinds">
      <button type="button" class="s-tab ${scp ? "" : "on"}" data-act="set-kind" data-kind="story">AI story series</button>
      <button type="button" class="s-tab ${scp ? "on" : ""}" data-act="set-kind" data-kind="scp">SCP Foundation tapes</button></div>`;
  const body = scp ? `
    <p class="s-note">Each episode is a creepy Foundation "orientation tape" adapted from one SCP wiki article: the containment procedures become the rules, and the entity creeps closer in every picture.
    The credit to the author and the CC BY-SA 3.0 licence are added for you everywhere it matters. You can add more SCPs to the series any time.</p>
    <div class="s-form">
      <label>Series name<input id="series-title" type="text" value="Foundation Tapes" /></label>
      <label class="wide">SCP numbers (any order)<input id="scp-numbers" type="text" placeholder="173, 096, 049, 106, 3008" /></label>
    </div>` : `
    <p class="s-note">Pick a pitch or write your own. The AI writes the cast, the look and a planned arc; you then write or generate each episode.</p>
    <div class="s-pitches">${pitches}</div>
    <div class="s-form">
      <label>Title<input id="series-title" type="text" placeholder="The Yearbook" /></label>
      <label>Genre<input id="series-genre" type="text" placeholder="romance / supernatural thriller" /></label>
      <label class="wide">Premise - include the hook line you want episode 1 to open with<textarea id="series-premise" rows="4"></textarea></label>
      <label>Planned episodes<input id="series-episodes" type="number" min="3" max="12" value="6" /></label>
    </div>`;
  return `
  <div class="s-studio-bg" data-act="close-create"></div>
  <div class="s-studio s-create" role="dialog">
    <button class="s-x" data-act="close-create" aria-label="Close">✕</button>
    <h2>Create a series</h2>
    ${kinds}
    ${body}
    <label class="st-check"><input type="checkbox" id="series-then-ep" checked> Also make episode 1 right away (${scp ? "fetches the article, makes pictures, renders the tape" : "writes it, makes pictures, renders"})</label>
    <div class="s-row wrap">
      <button class="s-btn primary" data-act="create">Create series</button>
      ${scp ? "" : `<button class="s-btn" data-act="surprise" title="Pick one of the pitches at random and start it">🎲 Surprise me</button>`}
    </div>
  </div>`;
}

// ---------------------------------------------------------------- render + events

function renderSeries() {
  const s = seriesData.series.find((x) => x.slug === seriesView.slug);
  const ep = s && s.episodes.find((e) => e.number === seriesView.number);
  let html = s ? viewSeries(s) : viewList();
  if (seriesView.creating) html += viewCreate();
  else if (s && ep) html += viewStudio(s, ep);
  seriesContentEl.innerHTML = html;
  seriesContentEl.querySelectorAll(".s-animate").forEach(loadShots);
  document.body.classList.toggle("s-lock", !!(seriesView.creating || (s && ep)));
}

seriesContentEl.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.disabled) return;
  if (e.target.closest(".s-studio") && el.classList.contains("s-studio-bg")) return;
  const act = el.dataset.act;
  const right = seriesContentEl.querySelector(".s-studio-right");
  const base = right ? { slug: right.dataset.slug, number: +right.dataset.number } : null;

  if (act === "open-series") { seriesView = { slug: el.dataset.slug, number: null, creating: false }; renderSeries(); window.scrollTo(0, 0); }
  else if (act === "back") { seriesView = { slug: null, number: null, creating: false }; renderSeries(); }
  else if (act === "open-ep") { seriesView.number = +el.dataset.number; studioStage = "auto"; renderSeries(); }
  else if (act === "close-studio") { seriesView.number = null; renderSeries(); }
  else if (act === "new-series") { seriesView.creating = true; renderSeries(); }
  else if (act === "close-create") { seriesView.creating = false; renderSeries(); }
  else if (act === "stage") { studioStage = el.dataset.stage; renderSeries(); }
  else if (act === "pitch") {
    const p = seriesData.pitches[+el.dataset.i];
    document.getElementById("series-title").value = p.title;
    document.getElementById("series-genre").value = p.genre;
    document.getElementById("series-premise").value = p.premise;
    seriesContentEl.querySelectorAll(".s-pitch").forEach((b) => b.classList.toggle("on", b === el));
  } else if (act === "set-kind") { createKind = el.dataset.kind; renderSeries(); }
  else if (act === "toggle-add") { const f = seriesContentEl.querySelector(".s-add"); f.hidden = !f.hidden; if (!f.hidden) f.querySelector("input").focus(); }
  else if (act === "add-episode") {
    const hint = document.getElementById("add-hint").value.trim(), status = seriesContentEl.querySelector(".s-add-status");
    if (el.dataset.scp === "1" && !hint) { status.textContent = "Type an SCP number first."; return; }
    el.disabled = true; status.textContent = el.dataset.scp === "1" ? "Adding…" : "The AI is planning the next chapter…";
    const res = await fetch(`/api/series/${encodeURIComponent(el.dataset.slug)}/episodes`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hint }) });
    const data = await res.json().catch(() => ({}));
    el.disabled = false;
    if (!res.ok) { status.textContent = data.detail || "Could not add the episode."; return; }
    await loadSeries();
  } else if (act === "create") {
    if (createKind === "scp") {
      const numbers = document.getElementById("scp-numbers").value.trim();
      if (!numbers) { alert("Type at least one SCP number, like 173."); return; }
      seriesView.creating = false;
      startSeriesAction("series_create", { kind: "scp", title: document.getElementById("series-title").value.trim(), scp_numbers: numbers,
                                           then_episode: !!document.getElementById("series-then-ep")?.checked });
      return;
    }
    const title = document.getElementById("series-title").value.trim();
    const premise = document.getElementById("series-premise").value.trim();
    if (!title || !premise) { alert("Give the series a title and a premise (or pick a pitch)."); return; }
    seriesView.creating = false;
    startSeriesAction("series_create", { title, premise, genre: document.getElementById("series-genre").value.trim(),
                                         episodes: parseInt(document.getElementById("series-episodes").value, 10) || 6,
                                         then_episode: !!document.getElementById("series-then-ep")?.checked });
  } else if (act === "delete-series") {
    if (!confirm("Delete this whole " + (seriesData.series.find((x) => x.slug === el.dataset.slug) || {}).title + "?\n\nEvery script, picture and video in it is removed from this computer. This can't be undone.")) return;
    const res = await fetch(`/api/series/${encodeURIComponent(el.dataset.slug)}`, { method: "DELETE" });
    if (!res.ok) { const d = await res.json().catch(() => ({})); alert(d.detail || "Could not delete."); return; }
    seriesView = { slug: null, number: null, creating: false };
    await loadSeries();
  } else if (act === "surprise") {
    const p = seriesData.pitches[Math.floor(Math.random() * seriesData.pitches.length)];
    seriesView.creating = false;
    startSeriesAction("series_create", { title: p.title, premise: p.premise, genre: p.genre, episodes: 6, then_episode: true });
  } else if (act === "auto-next") {
    seriesView = { slug: el.dataset.slug, number: +el.dataset.number, creating: false }; studioStage = "auto";   // reopens on this episode when it's done
    startSeriesAction("series_auto", { slug: el.dataset.slug, number: +el.dataset.number });
  } else if (!base) { return; }
  else if (act === "clear-ep") {
    if (!confirm("Delete this episode's video and pictures?\n\nThe script is kept, so you can remake it later (the pictures will come out different).")) return;
    const res = await fetch(`/api/series/${encodeURIComponent(base.slug)}/episode/${base.number}/clear`, { method: "POST" });
    if (!res.ok) { const d = await res.json().catch(() => ({})); alert(d.detail || "Could not delete."); return; }
    await loadSeries();
  } else if (act === "auto-ep") { studioStage = "auto"; startSeriesAction("series_auto", base); }
  else if (act === "write" || act === "rewrite") {
    if (act === "rewrite" && !confirm("Replace this episode's script with a new one? (Pictures already made are kept.)")) return;
    startSeriesAction("series_episode", base);
  } else if (act === "shots-plan") {
    const box = el.closest(".s-animate"), status = box.querySelector(".s-shots-status");
    el.disabled = true; status.textContent = "Claude is reading the scenes…";
    const res = await fetch(`/api/series/${encodeURIComponent(box.dataset.slug)}/episode/${box.dataset.number}/shots/plan`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    el.disabled = false;
    if (!res.ok) { status.textContent = data.detail || "Could not write the prompts."; return; }
    status.textContent = "Done - edit any prompt, then copy it.";
    renderShots(box, data.shots);
  } else if (act === "shot-copy") {
    const box = el.closest(".s-animate"), ta = box.querySelector(`[data-shot-prompt="${el.dataset.scene}"]`);
    copyToClipboard(Promise.resolve(ta.value), el);
  } else if (act === "preview") startSeriesAction("story_preview", base);
  else if (act === "images") startSeriesAction("story_images", base);
  else if (act === "render") startSeriesAction("story_render", base);
  else if (act === "redo") {
    if (confirm(`Remake picture ${el.dataset.scene}? (About a minute.)`)) startSeriesAction("story_images", { ...base, only: [+el.dataset.scene], force: true });
  } else if (act === "copy-prompt") {
    copyToClipboard(fetch(`/api/series/${encodeURIComponent(base.slug)}/episode/${base.number}/prompt`)
      .then((r) => r.json()).then((p) => `${p.system}\n\n---\n\n${p.user}`), el);
  } else if (act === "paste") {
    const box = seriesContentEl.querySelector(".s-paste");
    box.style.display = box.style.display === "none" ? "" : "none";
  } else if (act === "save-paste") {
    const status = seriesContentEl.querySelector(".s-paste-status");
    status.textContent = "Checking…";
    const res = await fetch(`/api/series/${encodeURIComponent(base.slug)}/episode/${base.number}/script`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raw: seriesContentEl.querySelector(".s-paste textarea").value }) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { status.textContent = data.detail || "Could not use that script."; return; }
    loadSeries();
  } else if (act === "post") {
    const s = seriesData.series.find((x) => x.slug === base.slug), ep = s && s.episodes.find((x) => x.number === base.number);
    openPostDialog({ title: (ep && ep.title) || "this episode", captionReq: { kind: "series", ...base },
      cleanupLabel: "Delete this episode's video and pictures after it posts (the script is kept)",
      send: async (platforms, privacy, captions, cleanup) => {
      const res = await fetch("/api/series/post", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...base, platforms, privacy, captions, cleanup }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Could not post.");
      return data;
    } });
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !document.getElementById("page-series").classList.contains("active")) return;
  if (seriesView.creating) { seriesView.creating = false; renderSeries(); }
  else if (seriesView.number) { seriesView.number = null; renderSeries(); }
});
window.addEventListener("hashchange", () => document.body.classList.remove("s-lock"));

if (location.hash === "#series") loadSeries();
