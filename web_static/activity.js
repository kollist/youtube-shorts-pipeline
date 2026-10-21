// Activity - turns the raw output of a job into something readable: a plain-language headline, a progress bar, a list of steps that tick off,
// and any error in red. Every raw line is still kept in the "Technical log" underneath (closed by default).
//
// feed(text, cls) is called for every log line. A line is matched against RULES; the first rule that matches decides the step ("stage"),
// the message, and - when the line carries "3/8"-style numbers - the progress. Lines no rule knows about are shown as the latest message.

const Activity = (() => {
  const $ = (id) => document.getElementById(id);
  const NOISE = [/MallocStackLogging/, /^INFO:\s/, /unauthenticated requests to the HF Hub/i, /FutureWarning|UserWarning|DeprecationWarning/, /^\s*$/, /it\/s\]|s\/it\]/, /^\[web\] Done/];
  // [regex, stage, message(match) -> string, progress(match) -> [i, n] | null]
  const RULES = [
    [/\[auto\] Step (\d)\/(\d) - (.+)/, (m) => ({ stage: null, msg: `Step ${m[1]} of ${m[2]}: ${m[3]}` })],
    [/\[scp\] (SCP-\d+) - author credit: (.+?) -/, (m) => ({ stage: "Fetching the SCP article", msg: `${m[1]} by ${m[2]}` })],
    [/\[scp\] Saved (\d+) scenes/, (m) => ({ stage: "Writing the tape script", msg: `${m[1]} scenes written` })],
    [/\[series\] Writing episode (\d+): '(.+)'/, (m) => ({ stage: "Writing the script", msg: `Episode ${m[1]}: ${m[2]}` })],
    [/\[series\] (Writing the series bible.*)/, (m) => ({ stage: "Planning the series", msg: m[1] })],
    [/\[series\] (Draft written.*)/, (m) => ({ stage: "Writing the script", msg: "Editing the draft" })],
    [/\[images\] Scene (\d+)\/(\d+)/, (m) => ({ stage: "Making pictures", msg: `Picture ${m[1]} of ${m[2]}`, prog: [+m[1], +m[2]] })],
    [/\[images\] Using the/, () => ({ stage: "Making pictures", msg: "Starting the picture model" })],
    [/\[story\] Speaking the lines/, () => ({ stage: "Recording the voices", msg: "Speaking the lines" })],
    [/\[story\] Scene (\d+)\/(\d+): animating/, (m) => ({ stage: "Animating the scenes", msg: `Scene ${m[1]} of ${m[2]}`, prog: [+m[1], +m[2]] })],
    [/\[story\] Adding captions/, () => ({ stage: "Final render", msg: "Adding captions and sound" })],
    [/\[horror\] Voices/, () => ({ stage: "Recording the voices", msg: "Narrator and whisper" })],
    [/\[fx\] frame (\d+)\/(\d+)/, (m) => ({ stage: "Damaging the tape", msg: `Frame ${m[1]} of ${m[2]}`, prog: [+m[1], +m[2]] })],
    [/\[horror\] Degrading/, () => ({ stage: "Damaging the tape", msg: "Applying the tape effect" })],
    [/\[horror\] Sound design/, () => ({ stage: "Sound design", msg: "Placing the sounds" })],
    [/\[horror\] (\d+) foley cues/, (m) => ({ stage: "Sound design", msg: `${m[1]} sound effects placed on spoken words` })],
    [/\[horror\] Final render/, () => ({ stage: "Final render", msg: "Burning in captions" })],
    [/\[horror\] (\d+) scenes, story ([\d.]+)s/, (m) => ({ stage: "Recording the voices", msg: `${m[1]} scenes, about ${Math.round(m[2])} seconds` })],
    [/\[pipeline\] Downloading/, () => ({ stage: "Downloading the video", msg: "Downloading…" })],
    [/\[transcribe\] Loading Whisper/, () => ({ stage: "Transcribing", msg: "Loading the speech model" })],
    [/\[transcribe\] Window (\d+)\/(\d+)/, (m) => ({ stage: "Transcribing", msg: `Part ${m[1]} of ${m[2]}`, prog: [+m[1], +m[2]] })],
    [/\[transcribe\] Transcribing/, () => ({ stage: "Transcribing", msg: "Listening to the video (this takes a while)" })],
    [/\[highlights\] (.+)/, (m) => ({ stage: "Finding the loud moments", msg: m[1] })],
    [/\[select_clips\] (.+)/, (m) => ({ stage: "Choosing the best clips", msg: m[1] })],
    [/\[cut_clips\] (.+)/, (m) => ({ stage: "Cutting the clips", msg: m[1] })],
    [/\[upload\]\s+\.\.\.(\d+)% uploaded/, (m) => ({ stage: "Uploading", msg: `${m[1]}% uploaded`, prog: [+m[1], 100] })],
    [/\[upload\] (.+)/, (m) => ({ stage: "Uploading", msg: m[1] })],
    [/\[queue\] (.+)/, (m) => ({ stage: "Daily queue", msg: m[1] })],
    [/\[pipeline\] (.+)/, (m) => ({ stage: "Processing", msg: m[1] })],
  ];
  const ERROR = /(\[web\] Error|Traceback|Error:|failed|FAILED|Could not|couldn't)/;

  let st = null, timer = null;
  const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  function render() {
    if (!st) return;
    $("act-idle").hidden = true; $("act-card").hidden = false;
    const active = st.stages[st.stages.length - 1];
    $("act-title").textContent = st.finished ? (st.failed ? "Stopped with a problem" : "Finished") : (active ? active.name : "Starting…");
    $("act-title").className = "act-title " + (st.finished ? (st.failed ? "bad" : "good") : "");
    $("act-sub").textContent = st.finished ? (st.failed ? "See the message below, or open the technical log." : `Done in ${fmt(st.end - st.start)}.`) : (st.msg || "");
    const p = !st.finished && active && active.prog ? active.prog : null;
    const bar = $("act-bar");
    bar.classList.toggle("indet", !st.finished && !p);
    $("act-fill").style.width = st.finished ? (st.failed ? "100%" : "100%") : (p ? `${Math.round((p[0] / p[1]) * 100)}%` : "35%");
    bar.classList.toggle("bad", !!st.failed);
    $("act-steps").innerHTML = st.stages.map((s, i) => {
      const last = i === st.stages.length - 1, done = !last || (st.finished && !st.failed);
      const extra = s.prog && s.prog[1] !== 100 ? ` <em>${Math.min(s.prog[0], s.prog[1])}/${s.prog[1]}</em>` : "";
      return `<li class="${done ? "done" : "now"}"><b>${done ? "✓" : "●"}</b>${s.name}${extra}</li>`;
    }).join("");
    $("act-alerts").innerHTML = st.alerts.slice(-3).map((a) => `<div class="act-alert">${a.replace(/</g, "&lt;")}</div>`).join("");
    $("act-elapsed").textContent = fmt(((st.finished ? st.end : Date.now()) - st.start) / 1000);
  }

  function reset() {
    clearInterval(timer);
    st = { start: Date.now(), stages: [], msg: "", alerts: [], finished: false, failed: false };
    const d = $("act-details"); if (d) d.open = false;
    timer = setInterval(() => st && !st.finished && render(), 1000);
    render();
  }

  function feed(text, cls) {
    if (!st) reset();
    if (NOISE.some((rx) => rx.test(text))) return;
    for (const [rx, fn] of RULES) {
      const m = text.match(rx);
      if (!m) continue;
      const r = fn(m), cur = st.stages[st.stages.length - 1];
      if (r.stage && (!cur || cur.name !== r.stage)) st.stages.push({ name: r.stage, prog: null });
      const stage = st.stages[st.stages.length - 1];
      if (stage && r.prog) stage.prog = r.prog;
      st.msg = r.msg;
      if (ERROR.test(text) && !/Done|Finished/.test(text)) st.alerts.push(text.replace(/^\[\w+\]\s*/, ""));
      render();
      return;
    }
    if (cls === "err" || ERROR.test(text)) { st.alerts.push(text.replace(/^\[web\]\s*/, "")); $("act-details").open = false; }
    else st.msg = text.replace(/^\[\w+\]\s*/, "").slice(0, 140);
    render();
  }

  function finish(failed) {
    if (!st) return;
    st.finished = true; st.failed = !!failed || st.alerts.some((a) => /error|traceback/i.test(a)); st.end = Date.now();
    clearInterval(timer);
    if (st.failed) $("act-details").open = true;          // something went wrong: show the raw log so it can be read
    render();
  }

  return { reset, feed, finish };
})();
