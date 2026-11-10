// Accounts tab: connect YouTube / Facebook + Instagram / TikTok step by step. Keys go to the server's .env and are never shown again.
const accountsEl = document.getElementById("accounts-content");

// Which set of channels this tab is setting up ("default" = the main one). Remembered between visits; the server decides what each series posts to.
let currentAccount = "default";
try { currentAccount = localStorage.getItem("shorts.account") || "default"; } catch (e) { /* private window: stay on the main account */ }
const acctQuery = () => (currentAccount && currentAccount !== "default" ? `?account=${encodeURIComponent(currentAccount)}` : "");

async function accountsApi(path, body) {
  const res = await fetch(path + acctQuery(), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Something went wrong.");
  return data;
}

async function loadAccounts() {
  let data;
  try { data = await (await fetch("/api/accounts" + acctQuery())).json(); } catch (e) { accountsEl.textContent = "Could not reach the server."; return; }
  if (!data.platforms) { accountsEl.textContent = data.detail || "Could not load this account."; return; }
  if (!data.accounts.some((a) => a.id === currentAccount)) { currentAccount = "default"; return loadAccounts(); }
  accountsEl.innerHTML = accountBarHtml(data) + data.platforms.map(cardHtml).join("");
  wireAccountBar(data);
  accountsEl.querySelectorAll(".ac-card").forEach((card) => wireCard(card, data.platforms.find((p) => p.id === card.dataset.id)));
}

function accountBarHtml(data) {
  const cur = data.accounts.find((a) => a.id === data.account) || data.accounts[0];
  const opts = data.accounts.map((a) => `<option value="${escapeHtml(a.id)}" ${a.id === data.account ? "selected" : ""}>${escapeHtml(a.label)}${a.id === "default" ? "" : " (" + escapeHtml(a.id) + ")"}</option>`).join("");
  const uses = cur.series.length ? `Used by: ${cur.series.map(escapeHtml).join(", ")}` : "No series posts here yet (set \"account\" in the series' series.json).";
  return `<div class="ac-bar">
    <label>Account <select class="ac-switch">${opts}</select></label>
    <button type="button" class="ac-newbtn">＋ New account</button>
    <span class="ac-uses">${uses}</span>
    <form class="ac-new" hidden>
      <input class="ac-new-id" placeholder="id, e.g. alkhobeer" maxlength="31" pattern="[a-z0-9][a-z0-9_\\-]*" required>
      <input class="ac-new-label" placeholder="name shown here, e.g. الخبير" maxlength="60">
      <button type="submit">Create</button><span class="ac-new-out"></span>
    </form>
    ${data.account === "default" ? "" : `<div class="ac-note"><b>Separate logins:</b> everything you connect below belongs only to “${escapeHtml(cur.label)}”. It never uses the main account's Page, Instagram or TikTok login, so a missing step shows as “not connected” instead of posting to the wrong place.</div>`}
  </div>`;
}

function wireAccountBar(data) {
  const sel = accountsEl.querySelector(".ac-switch"), form = accountsEl.querySelector(".ac-new"), out = accountsEl.querySelector(".ac-new-out");
  sel.addEventListener("change", () => { currentAccount = sel.value; try { localStorage.setItem("shorts.account", currentAccount); } catch (e) { /* fine */ } loadAccounts(); });
  accountsEl.querySelector(".ac-newbtn").addEventListener("click", () => { form.hidden = !form.hidden; });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await fetch("/api/accounts/create", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: form.querySelector(".ac-new-id").value, label: form.querySelector(".ac-new-label").value }) });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || "Could not create it.");
      currentAccount = d.id; try { localStorage.setItem("shorts.account", currentAccount); } catch (e2) { /* fine */ }
      loadAccounts();
    } catch (err) { out.textContent = err.message; out.className = "ac-new-out bad"; }
  });
}

function cardHtml(p) {
  const chips = p.status.map((s) => `<span class="ac-chip ${s.configured ? "ok" : "off"}" title="${s.configured ? "" : escapeHtml("Missing: " + s.missing.join(", "))}">${escapeHtml(s.label)}: ${s.configured ? "connected" : "not connected"}</span>`).join("");
  const keys = p.keys.map((k) => `<label class="ac-key">${escapeHtml(k.label)}
      <input type="${k.secret ? "password" : "text"}" data-env="${k.env}" autocomplete="off" placeholder="${k.inherited ? "uses the main account's key ✓ (type to use a different one)" : k.set ? "saved ✓ (type to replace)" : ""}"></label>`).join("");
  const tests = p.covers.map((c) => `<button type="button" data-act="test" data-name="${c}">Test ${escapeHtml((p.status.find((s) => s.name === c) || { label: c }).label)}</button>`).join("");
  let login = "";
  if (p.login === "youtube") login = (p.notes && p.notes.length && p.client_secret_present)
    ? `<div class="ac-block"><span class="ac-chip ok">shared Google OAuth file found ✓</span>
      <button type="button" data-act="ytlogin">Log in with this channel's Google account (opens a browser window)</button></div>`
    : `<div class="ac-block"><b>Google OAuth file</b> ${p.client_secret_present ? '<span class="ac-chip ok">client_secret.json found ✓</span>' : ""}
      <textarea class="ac-json" rows="4" placeholder='Paste the contents of the downloaded JSON file here ({"installed": {...}})'></textarea>
      <button type="button" data-act="ytsecret">Save file</button> <button type="button" data-act="ytlogin">Log in (opens a browser window)</button></div>`;
  if (p.login === "meta") login = `<div class="ac-block"><label class="ac-key">User token from the Graph API Explorer<input type="password" class="ac-token" autocomplete="off"></label>
      <label class="ac-key">Page ID (only if you manage several Pages)<input type="text" class="ac-page"></label>
      <button type="button" data-act="metalogin">Log in</button></div>`;
  if (p.login === "tiktok") login = `<div class="ac-block"><button type="button" data-act="ttlink">Get login link</button>
      <label class="ac-key">Address you land on after approving (contains ?code=…)<input type="text" class="ac-pasted"></label>
      <button type="button" data-act="ttfinish">Finish login</button></div>`;
  return `<div class="ac-card" data-id="${p.id}">
    <div class="ac-head"><h3>${escapeHtml(p.label)}</h3><span class="ac-level ${p.level.toLowerCase()}">${escapeHtml(p.level)} · ${escapeHtml(p.time)}</span>${chips}</div>
    <div class="ac-needs">${escapeHtml(p.needs)}</div>
    ${p.notes && p.notes.length ? `<ul class="ac-notes">${p.notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("")}</ul>` : ""}
    ${stepsHtml(p)}
    ${keys ? `<div class="ac-keys">${keys}<button type="button" data-act="savekeys">Save keys</button></div>` : ""}
    ${login}
    <div class="ac-actions">${tests}</div>
    <div class="ac-out" aria-live="polite"></div>
  </div>`;
}

function stepsHtml(p) {
  const list = `<ol class="ac-steps">${p.steps.map((s) => `<li>${escapeHtml(s.text)}${s.url ? ` <a href="${s.url}" target="_blank" rel="noopener">open ↗</a>` : ""}</li>`).join("")}</ol>`;
  // another account shares the developer apps: the one-time steps are already done, so they are folded away
  return p.notes && p.notes.length ? `<details class="ac-fold"><summary>One-time setup steps (already done for the main account)</summary>${list}</details>` : list;
}

function wireCard(card, p) {
  const out = card.querySelector(".ac-out");
  const say = (msg, bad) => { out.textContent = msg; out.className = "ac-out" + (bad ? " bad" : " good"); };
  card.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]"); if (!b) return;
    const act = b.dataset.act; b.disabled = true;
    try {
      if (act === "savekeys") {
        const values = {}; card.querySelectorAll("[data-env]").forEach((i) => { values[i.dataset.env] = i.value; });
        const r = await accountsApi(`/api/accounts/${p.id}/keys`, { values });
        say(r.saved.length ? `Saved: ${r.saved.join(", ")}` : "Nothing to save (empty boxes keep what is already saved).");
        card.querySelectorAll("[data-env]").forEach((i) => { if (i.value) { i.value = ""; i.placeholder = "saved ✓ (type to replace)"; } });
      } else if (act === "ytsecret") {
        const r = await fetch("/api/accounts/youtube/client-secret", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ json: card.querySelector(".ac-json").value }) }).then(async (x) => { const d = await x.json().catch(() => ({})); if (!x.ok) throw new Error(d.detail || "Something went wrong."); return d; });
        say(`Saved ${r.saved}. Now press Log in.`); card.querySelector(".ac-json").value = "";
      } else if (act === "ytlogin") {
        say("Waiting for you to approve in the browser window that just opened…");
        await accountsApi("/api/accounts/youtube/login"); say("YouTube connected ✓"); loadAccounts();
      } else if (act === "metalogin") {
        const r = await accountsApi("/api/accounts/meta/login", { user_token: card.querySelector(".ac-token").value, page_id: card.querySelector(".ac-page").value });
        say(`Connected: Page “${r.page}”${r.instagram_user_id ? " + its Instagram account ✓" : " (no Instagram account is linked to this Page yet)"}`); loadAccounts();
      } else if (act === "ttlink") {
        const r = await accountsApi("/api/accounts/tiktok/link"); window.open(r.url, "_blank", "noopener");
        say("TikTok's page opened in a new tab. Approve, then copy the full address from the address bar (the page may show an error, that's fine) and paste it below.");
      } else if (act === "ttfinish") {
        const r = await accountsApi("/api/accounts/tiktok/finish", { pasted: card.querySelector(".ac-pasted").value });
        say("TikTok connected ✓ (permissions: " + r.scopes + ")"); loadAccounts();
      } else if (act === "test") {
        const r = await (await fetch(`/api/social/test/${b.dataset.name}${acctQuery()}`, { method: "POST" })).json();
        say(r.ok ? r.message : r.error, !r.ok);
      }
    } catch (err) { say(err.message, true); }
    b.disabled = false;
  });
}

// opened straight on #accounts (page load): app.js ran before this file existed, so load now
if (location.hash === "#accounts") loadAccounts();
