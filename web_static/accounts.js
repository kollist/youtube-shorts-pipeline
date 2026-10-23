// Accounts tab: connect YouTube / Facebook + Instagram / TikTok step by step. Keys go to the server's .env and are never shown again.
const accountsEl = document.getElementById("accounts-content");

async function accountsApi(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Something went wrong.");
  return data;
}

async function loadAccounts() {
  let data;
  try { data = await (await fetch("/api/accounts")).json(); } catch (e) { accountsEl.textContent = "Could not reach the server."; return; }
  accountsEl.innerHTML = data.platforms.map(cardHtml).join("");
  accountsEl.querySelectorAll(".ac-card").forEach((card) => wireCard(card, data.platforms.find((p) => p.id === card.dataset.id)));
}

function cardHtml(p) {
  const chips = p.status.map((s) => `<span class="ac-chip ${s.configured ? "ok" : "off"}" title="${s.configured ? "" : escapeHtml("Missing: " + s.missing.join(", "))}">${escapeHtml(s.label)}: ${s.configured ? "connected" : "not connected"}</span>`).join("");
  const keys = p.keys.map((k) => `<label class="ac-key">${escapeHtml(k.label)}
      <input type="${k.secret ? "password" : "text"}" data-env="${k.env}" autocomplete="off" placeholder="${k.set ? "saved ✓ (type to replace)" : ""}"></label>`).join("");
  const tests = p.covers.map((c) => `<button type="button" data-act="test" data-name="${c}">Test ${escapeHtml((p.status.find((s) => s.name === c) || { label: c }).label)}</button>`).join("");
  let login = "";
  if (p.login === "youtube") login = `<div class="ac-block"><b>Google OAuth file</b> ${p.client_secret_present ? '<span class="ac-chip ok">client_secret.json found ✓</span>' : ""}
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
    <ol class="ac-steps">${p.steps.map((s) => `<li>${escapeHtml(s.text)}${s.url ? ` <a href="${s.url}" target="_blank" rel="noopener">open ↗</a>` : ""}</li>`).join("")}</ol>
    ${keys ? `<div class="ac-keys">${keys}<button type="button" data-act="savekeys">Save keys</button></div>` : ""}
    ${login}
    <div class="ac-actions">${tests}</div>
    <div class="ac-out" aria-live="polite"></div>
  </div>`;
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
        const r = await accountsApi("/api/accounts/youtube/client-secret", { json: card.querySelector(".ac-json").value });
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
        const r = await (await fetch(`/api/social/test/${b.dataset.name}`, { method: "POST" })).json();
        say(r.ok ? r.message : r.error, !r.ok);
      }
    } catch (err) { say(err.message, true); }
    b.disabled = false;
  });
}

// opened straight on #accounts (page load): app.js ran before this file existed, so load now
if (location.hash === "#accounts") loadAccounts();
