/* global saveFile, askForKey */  // from shared.js, which admin.html loads first
const CALL_TIMEOUT = 75000;  // a sleeping free server can take ~50s to wake
const SEARCH_WAIT = 300;     // ms after the last key press before a search runs

const el = i => document.getElementById(i);
const main = el("main");
const ESC = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
const x = s => String(s ?? "").replace(/[&<>"']/g, c => ESC[c]);
const when = t => t ? new Date(t).toLocaleString([], {day:"numeric", month:"short",
  hour:"2-digit", minute:"2-digit"}) : "—";

// The filters, in the order of the tiles. "waiting" is pending and escalated.
const FILTERS = [
  ["all", "All"], ["waiting", "Waiting"], ["approved", "Approved"],
  ["inside", "Inside"], ["closed", "Closed"], ["declined", "Declined"],
  ["expired", "Expired"],
];
// Each status as [the pill's data-tone, the word on the pill].
const STATUS = {
  pending: ["wait", "Waiting"], escalated: ["wait", "With backup"],
  approved: ["go", "Approved"], inside: ["go", "Inside"],
  declined: ["stop", "Declined"], closed: ["done", "Closed"],
  expired: ["done", "Expired"],
};

let section = "visits"; // the open tab: "visits", "numbers" or "guards"
let rows = [];
let next = null;
let filter = "all";
let query = "";
let counts = {};
let approvers = [];
let notice = "";
let info = "";          // a good-news line, such as "key sent"
let editing = null;     // the reason whose approvers are being changed
let fieldErrors = {};
let draft = null;       // the numbers typed in the open editor
let approverNote = "";
let guards = [];
let gateDesk = "";
let guardErrors = {};
let shownKey = null;    // {name, key}: a guard's new key, shown once
let removing = null;    // the number of the guard whose removal waits for a second tap
let loading = false;
// Each list request gets a number. An answer to an older one is dropped.
let asked = 0;
let searchTimer = null;

class WrongKey extends Error {}

function key() {
  try { return localStorage.getItem("adminkey") || ""; } catch { return ""; }
}

function setKey(value) {
  try { localStorage.setItem("adminkey", value); } catch { /* this page view only */ }
}

function forgetKey(why = "") {
  try { localStorage.removeItem("adminkey"); } catch { /* it was never stored */ }
  rows = []; next = null; counts = {}; approvers = []; guards = []; shownKey = null; notice = why;
  for (const reference in photos) delete photos[reference];
  render();
}

async function call(url, body = null) {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), CALL_TIMEOUT);
  let r, data;
  const headers = {"X-Admin-Key": key()};
  const options = {headers, signal: stop.signal};
  if (body) {
    headers["Content-Type"] = "application/json";
    Object.assign(options, {method: "POST", body: JSON.stringify(body)});
  }
  try {
    r = await fetch(url, options);
    data = await r.json().catch(() => ({}));
  } catch (err) {
    throw err.name === "AbortError"
      ? new Error("The server did not answer. Check your connection and try again.")
      : err;
  } finally {
    clearTimeout(timer);
  }
  if (r.status === 403) throw new WrongKey("That admin key is not right. Type it again.");
  if (!r.ok) throw Object.assign(new Error(data.error || `Something went wrong (${r.status})`),
    {fields: data.fields || {}});
  return data;
}

function count(name) {
  if (name === "all") return Object.values(counts).reduce((a, b) => a + b, 0);
  if (name === "waiting") return (counts.pending || 0) + (counts.escalated || 0);
  return counts[name] || 0;
}

function renderTiles() {
  el("tiles").innerHTML = FILTERS.map(([name, label]) =>
    `<button class="tile" data-filter="${name}">
       <b>${count(name)}</b><span>${label}</span></button>`).join("");
  for (const tile of el("tiles").children) {
    tile.setAttribute("aria-pressed", tile.dataset.filter === filter ? "true" : "false");
  }
}

const plus = v => v.guests.length ? ` +${v.guests.length}` : "";
const DECIDER = {main: "the approver", backup: "the backup approver"};

// [tone, line] for who decided. An old decision names only the role.
function decision(v) {
  if (!v.decided_at) return ["", ""];
  if (v.decided_by === "auto") return ["go", "Approved automatically: no one answered in time"];
  const [tone, word] = v.status === "declined" ? ["stop", "Declined"] : ["go", "Approved"];
  const who = DECIDER[v.decided_by];
  return [tone, who ? `${word} by ${who}${v.decided_phone ? ` ${v.decided_phone}` : ""}` : word];
}

function item(v) {
  const [main1, backup] = v.approvers || [];
  const [tone, word] = STATUS[v.status] || ["", v.status];
  const [byTone, byLine] = decision(v);
  return `<details><summary>
      <span><b>${x(v.name)}${plus(v)}</b><small>${x(v.phone)}</small>
        ${byLine ? `<small class="by" data-tone="${byTone}">${x(byLine)}</small>` : ""}</span>
      <span class="mid"><b>${x(v.reason)}</b><small>Visiting ${x(v.visiting)}</small></span>
      <span class="side"><code>${x(v.reference)}</code><br>
        <span class="pill" data-tone="${tone}">${x(word)}</span></span>
    </summary>
    <div class="more"><dl>
      <dt>Address</dt><dd>${x(v.address)}</dd>
      <dt>Reason</dt><dd>${x(v.reason)}</dd>
      <dt>Visiting</dt><dd>${x(v.visiting)}</dd>
      <dt>With</dt><dd>${v.guests.length ? x(v.guests.join(", ")) : "No one"}</dd>
      <dt>Approvers now</dt><dd>${x(main1)}${backup && backup !== main1 ? `, backup ${x(backup)}` : " (also the backup)"}</dd>
      <dt>Requested</dt><dd>${when(v.created_at)}</dd>
      <dt>Pass valid until</dt><dd>${when(v.expires_at)}</dd>
      <dt>Sent to backup</dt><dd>${when(v.escalated_at)}</dd>
      <dt>Decided</dt><dd>${when(v.decided_at)}</dd>
      <dt>Decision</dt><dd>${x(byLine || "Not decided yet")}</dd>
      <dt>Entered</dt><dd>${when(v.entered_at)}${v.entered_by ? ` by ${x(v.entered_by)}` : ""}</dd>
      <dt>Gate photo</dt><dd>${when(v.photo_at)}${photoLine(v)}</dd>
      <dt>Exited</dt><dd>${when(v.exited_at)}${v.exited_by ? ` by ${x(v.exited_by)}` : ""}</dd>
    </dl></div></details>`;
}

// The gate page's photo loads only when the admin asks, then stays for this page view.
const photos = {};
function photoLine(v) {
  if (photos[v.reference]) {
    return `<span class="shot"><img src="${x(photos[v.reference])}" alt="The visitor at the gate"></span>`;
  }
  if (v.photo_stored) {
    return ` <button class="small" data-photo="${x(v.reference)}">View photo</button><span class="shot"></span>`;
  }
  return v.photo_at ? " (in the guard's WhatsApp chat)" : "";
}

async function showPhoto(button) {
  const box = button.nextElementSibling;
  button.disabled = true;
  try {
    const answer = await call(`/api/admin/photo/${encodeURIComponent(button.dataset.photo)}`);
    photos[button.dataset.photo] = answer.photo;
    box.innerHTML = `<img src="${x(answer.photo)}" alt="The visitor at the gate">`;
    button.hidden = true;
  } catch (err) {
    if (err instanceof WrongKey) return forgetKey(err.message);
    box.textContent = ` ${err.message}`;
    button.disabled = false;
  }
}

function renderList() {
  el("list").innerHTML = rows.length
    ? rows.map(item).join("")
    : `<div class="empty">${loading ? "Loading…" : query ? "No request matches that search." : "No requests here."}</div>`;
  el("found").textContent = rows.length
    ? `Showing ${rows.length} ${rows.length === 1 ? "request" : "requests"}${next ? ". Show more loads the next ones." : "."}`
    : "";
  const more = el("more");
  more.hidden = !next;
  more.disabled = loading;
  more.textContent = loading ? "Loading…" : "Show more";
}

function approverRow(a) {
  if (a.reason !== editing) {
    return `<tr><td>${x(a.reason)}</td><td>${x(a.main)}</td><td>${x(a.backup)}</td>
      <td><button class="small" data-edit="${x(a.reason)}">Change</button></td></tr>`;
  }
  const field = (name, label, value) => `<div>
      <label for="ap-${name}">${label}</label>
      <input id="ap-${name}" type="tel" inputmode="tel" autocomplete="off" value="${x(value)}"
        placeholder="+919876543210">
      ${fieldErrors[name] ? `<p class="err">${x(fieldErrors[name])}</p>` : ""}</div>`;
  const typed = draft || a;
  return `<tr><td colspan="4"><b>${x(a.reason)}</b>
      <div class="pair">${field("main", "Approver", typed.main)}${field("backup", "Backup approver", typed.backup)}</div>
      <div class="pair" style="margin-top:12px">
        <button class="btn" id="ap-save">Save both numbers</button>
        <button class="btn plain" id="ap-cancel">Cancel</button></div></td></tr>`;
}

function renderApprovers() {
  el("approvers").innerHTML = `<table><thead><tr><th>Reason</th><th>Approver</th><th>Backup</th><th></th></tr></thead>
    <tbody>${approvers.map(approverRow).join("")}</tbody></table>`;
  el("approver-note").innerHTML = approverNote ? `<div class="note good">${x(approverNote)}</div>` : "";
  if (editing) {
    el("ap-save").onclick = () => void saveApprovers();
    el("ap-cancel").onclick = () => { editing = null; draft = null; fieldErrors = {}; renderApprovers(); };
  }
}

async function saveApprovers() {
  const main1 = el("ap-main").value.trim(), backup = el("ap-backup").value.trim();
  draft = {main: main1, backup};
  fieldErrors = {};
  if (!main1) fieldErrors.main = "Type the approver's number.";
  if (!backup) fieldErrors.backup = "Type the backup approver's number.";
  if (fieldErrors.main || fieldErrors.backup) return renderApprovers();
  el("ap-save").disabled = true;
  // The admin can open another reason meanwhile. The answer speaks for this one.
  const reason = editing;
  try {
    const saved = await call("/api/admin/approvers", {reason, main: main1, backup});
    approvers = saved.approvers;
    approverNote = `Saved. New requests for ${reason} now go to these two numbers.`;
    if (editing === reason) { editing = null; draft = null; }
  } catch (err) {
    if (err instanceof WrongKey) return forgetKey(err.message);
    if (editing === reason) {
      fieldErrors = err.fields && Object.keys(err.fields).length ? err.fields : {backup: err.message};
    }
  }
  renderApprovers();
}

function guardRow(g) {
  const added = new Date(g.added_at).toLocaleDateString([], {day: "numeric", month: "short", year: "numeric"});
  const actions = removing === g.phone
    ? `<b>Remove ${x(g.name)}?</b>
       <button class="small" data-remove-now="${x(g.phone)}">Remove</button>
       <button class="small" data-keep>Keep</button>`
    : `<button class="small" data-newkey="${x(g.phone)}">New key</button>
       <button class="small" data-remove="${x(g.phone)}">Remove</button>`;
  return `<tr><td>${x(g.name)}</td><td>${x(g.phone)}</td><td>${added}</td><td class="acts">${actions}</td></tr>`;
}

function renderGuards() {
  el("guard-table").innerHTML = `<table><thead><tr><th>Name</th><th>WhatsApp number</th><th>Added</th><th></th></tr></thead>
    <tbody><tr><td>Gate desk</td><td>${x(gateDesk)}</td><td colspan="2">Set as GUARD on the server. Uses the shared gate key.</td></tr>
    ${guards.map(guardRow).join("")}</tbody></table>`;
  el("guard-note").innerHTML = shownKey
    ? `<div class="note good">The gate key for ${x(shownKey.name)} is <code class="key">${x(shownKey.key)}</code>
       Give it to ${x(shownKey.name)} now. This page shows it only once. ${x(shownKey.name)} types it on the gate page.</div>`
    : "";
  for (const name of ["name", "phone"]) {
    el(`g-${name}-err`).textContent = guardErrors[name] || "";
  }
}

// A guard call answers with the new list, and a new key when one was made.
async function guardCall(url, body) {
  guardErrors = {};
  shownKey = null;
  try {
    const answer = await call(url, body);
    guards = answer.guards;
    gateDesk = answer.gate_desk;
    if (answer.key) shownKey = {name: answer.name, key: answer.key};
    return true;
  } catch (err) {
    if (err instanceof WrongKey) { forgetKey(err.message); return false; }
    guardErrors = Object.keys(err.fields || {}).length ? err.fields : {phone: err.message};
    return false;
  } finally {
    removing = null;
    if (key()) renderGuards();
  }
}

async function addGuard() {
  const name = el("g-name").value.trim(), phone = el("g-phone").value.trim();
  guardErrors = {};
  if (!name) guardErrors.name = "Type the guard's name.";
  if (!phone) guardErrors.phone = "Type the guard's WhatsApp number.";
  if (guardErrors.name || guardErrors.phone) { shownKey = null; return renderGuards(); }
  el("g-add").disabled = true;
  if (await guardCall("/api/admin/guards", {name, phone})) {
    el("g-name").value = "";
    el("g-phone").value = "";
  }
  if (el("g-add")) el("g-add").disabled = false;
}

function renderTabs() {
  for (const tab of el("tabs").children) {
    const open = tab.dataset.section === section;
    tab.setAttribute("aria-selected", open ? "true" : "false");
    el(tab.dataset.section).hidden = !open;
  }
}

function renderNotice() {
  el("notice").innerHTML = notice ? `<div class="note bad">${x(notice)}</div>` : "";
}

// Asks the server to send the admin key to the admin WhatsApp. The page never sees the key.
async function sendKey() {
  const button = el("forgot");
  button.disabled = true;
  button.textContent = "Sending…";
  const [ok, data] = await askForKey("admin");
  notice = ok ? "" : data.error;
  info = ok
    ? `We sent the admin key by WhatsApp to the admin number that ends in ${data.sent_to}.`
      + " It can take a minute. If it does not arrive, send KEY from that phone to the app's WhatsApp number."
    : "";
  render();
}

function render() {
  const haveKey = !!key();
  el("nav").hidden = !haveKey;
  if (!haveKey) {
    main.innerHTML = `<div class="keybox">
        ${notice ? `<div class="note bad">${x(notice)}</div>` : ""}
        ${info ? `<div class="note good">${x(info)}</div>` : ""}
        <label for="k">Admin key</label>
        <input id="k" type="password" autocomplete="current-password" enterkeyhint="go">
        <button class="btn" id="save">Open the list</button>
        <button class="btn plain" id="forgot">Forgot admin key?</button>
        <p class="hint">The admin key is not the gate key.</p></div>`;
    el("save").onclick = saveKey;
    el("forgot").onclick = () => void sendKey();
    el("k").onkeydown = e => { if (e.key === "Enter") saveKey(); };
    el("k").focus();
    return;
  }
  // The search box is built once, so typing never loses focus to a redraw.
  if (!el("list")) {
    main.innerHTML = `
      <div id="notice"></div>
      <div class="tabs" id="tabs" role="tablist">
        <button role="tab" data-section="visits" aria-controls="visits">Visits</button>
        <button role="tab" data-section="numbers" aria-controls="numbers">Approver numbers</button>
        <button role="tab" data-section="guards" aria-controls="guards">Guards</button>
      </div>
      <section id="visits" role="tabpanel">
      <div class="tiles" id="tiles"></div>
      <div class="bar"><input id="q" type="search" placeholder="Search name, phone, code or person visited"
        aria-label="Search" autocomplete="off" spellcheck="false"></div>
      <p class="found" id="found"></p>
      <div class="list" id="list"></div>
      <button class="btn plain" id="more" hidden>Show more</button>
      </section>
      <section id="numbers" role="tabpanel" hidden>
      <h2>Who approves each reason</h2>
      <div id="approver-note"></div>
      <div class="wrap" id="approvers"></div>
      <p class="hint">Each reason needs two different numbers, with + and the country code.
        A change works at once: the old numbers can no longer decide that reason's requests,
        including requests already sent to them. While the app uses Meta's test number, also
        add each new number to the recipient list in Meta's API Setup page.</p>
      <p class="hint" id="rules"></p>
      </section>
      <section id="guards" role="tabpanel" hidden>
      <h2>Who can record entry and exit</h2>
      <div id="guard-note"></div>
      <div class="wrap" id="guard-table"></div>
      <h2 class="gap">Add a guard</h2>
      <div class="pair">
        <div><label for="g-name">Name</label>
          <input id="g-name" autocomplete="off" maxlength="60"><p class="err" id="g-name-err"></p></div>
        <div><label for="g-phone">WhatsApp number</label>
          <input id="g-phone" type="tel" inputmode="tel" autocomplete="off" placeholder="+919876543210">
          <p class="err" id="g-phone-err"></p></div>
      </div>
      <button class="btn" id="g-add">Add guard and make a key</button>
      <p class="hint">Each guard gets a gate key of their own, so the log names who let each visitor
        in and out. A guard can also use IN and OUT from their WhatsApp number, and gets a message when
        a request is approved. WhatsApp delivers that message only if the guard wrote to the app's
        number in the last 24 hours. A guard who loses their key sends KEY from their phone to the
        app's WhatsApp number, or you tap New key. Remove stops the key and the WhatsApp commands at once.
        While the app uses Meta's test number, also add each guard's number to the recipient list
        in Meta's API Setup page.</p>
      </section>`;
    el("tabs").onclick = e => {
      const hit = e.target.closest("[data-section]");
      if (hit) { section = hit.dataset.section; renderTabs(); }
    };
    el("tiles").onclick = e => {
      const hit = e.target.closest("[data-filter]");
      if (hit && hit.dataset.filter !== filter) { filter = hit.dataset.filter; void load(); }
    };
    el("q").oninput = e => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { query = e.target.value.trim(); void load(); }, SEARCH_WAIT);
    };
    el("more").onclick = () => void load(true);
    el("list").onclick = e => {
      const hit = e.target.closest("[data-photo]");
      if (hit) void showPhoto(hit);
    };
    el("g-add").onclick = () => void addGuard();
    el("guard-table").onclick = e => {
      const hit = e.target.closest("button");
      if (!hit) return;
      const d = hit.dataset;
      if (d.newkey) void guardCall("/api/admin/guards/new-key", {phone: d.newkey});
      else if (d.removeNow) void guardCall("/api/admin/guards/remove", {phone: d.removeNow});
      else { removing = d.remove || null; shownKey = null; renderGuards(); }
    };
    el("approvers").onclick = e => {
      const hit = e.target.closest("[data-edit]");
      if (hit) { editing = hit.dataset.edit; draft = null; fieldErrors = {}; approverNote = ""; renderApprovers(); }
    };
  }
  renderNotice();
  renderTabs();
  renderTiles();
  renderList();
  renderApprovers();
  renderGuards();
}

// Loads the first page again, or with more=true the page after the last one.
async function load(more = false) {
  const mine = ++asked;
  loading = true;
  if (!more) { rows = []; next = null; }
  renderTiles();
  renderList();
  const params = new URLSearchParams({status: filter});
  if (query) params.set("q", query);
  if (more && next) params.set("after", next);
  try {
    const page = await call(`/api/admin/visits?${params}`);
    if (mine !== asked) return;
    rows = more ? rows.concat(page.visits) : page.visits;
    next = page.next;
    notice = "";
  } catch (err) {
    if (mine !== asked) return;
    if (err instanceof WrongKey) { loading = false; return forgetKey(err.message); }
    notice = err.message;
  }
  loading = false;
  render();
}

async function loadSummary() {
  try {
    const s = await call("/api/admin/summary");
    counts = s.counts;
    approvers = s.approvers;
    guards = s.guards || [];
    gateDesk = s.gate_desk || "";
    if (el("rules")) {
      const auto = s.auto_approve_minutes
        ? ` A request made ${s.work_days.join(", ")}, ${s.work_hours[0]}:00 to ${s.work_hours[1]}:00,`
          + ` is approved automatically after ${s.auto_approve_minutes} minutes with no answer.`
        : "";
      el("rules").textContent = `A request goes to the backup approver after ${s.escalate_minutes} minutes`
        + ` with no answer.${auto} A pass works for ${s.pass_hours} hours after the request.`
        + ` Records are deleted after ${s.retain_days} days.`;
    }
  } catch (err) {
    if (err instanceof WrongKey) return forgetKey(err.message);
    notice = err.message;
  }
  if (key()) render();
}

function refresh() {
  void loadSummary();
  void load();
}

function saveKey() {
  const value = el("k").value.trim();
  if (!value) {
    notice = "Type the key first.";
    render();
    return;
  }
  setKey(value);
  notice = "";
  info = "";
  render();
  refresh();
}

async function downloadCsv() {
  try {
    const r = await fetch("/api/admin/export.csv", {headers: {"X-Admin-Key": key()}});
    if (r.status === 403) return forgetKey("That admin key is not right. Type it again.");
    if (r.ok) return await saveFile(r);
    notice = `Could not download (${r.status})`;
  } catch (err) {
    notice = err.message;
  }
  renderNotice();
}

el("refresh").onclick = refresh;
el("csv").onclick = () => void downloadCsv();
el("rekey").onclick = () => forgetKey();
render();
if (key()) refresh();
