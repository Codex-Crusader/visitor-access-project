/* global saveFile */  // from download.js, which admin.html loads first
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
];
// Each status as [the pill's data-tone, the word on the pill].
const STATUS = {
  pending: ["wait", "Waiting"], escalated: ["wait", "With backup"],
  approved: ["go", "Approved"], inside: ["go", "Inside"],
  declined: ["stop", "Declined"], closed: ["done", "Closed"],
};

let rows = [];
let next = null;
let filter = "all";
let query = "";
let counts = {};
let approvers = [];
let notice = "";
let loading = false;
// Each list request gets a number. An answer to an older request, for example
// a search the admin has since changed, is thrown away.
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
  rows = []; next = null; counts = {}; approvers = []; notice = why;
  render();
}

async function call(url) {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), CALL_TIMEOUT);
  let r, data;
  try {
    r = await fetch(url, {headers: {"X-Admin-Key": key()}, signal: stop.signal});
    data = await r.json().catch(() => ({}));
  } catch (err) {
    throw err.name === "AbortError"
      ? new Error("The server did not answer. Check your connection and try again.")
      : err;
  } finally {
    clearTimeout(timer);
  }
  if (r.status === 403) throw new WrongKey("That admin key is not right. Type it again.");
  if (!r.ok) throw new Error(data.error || `Something went wrong (${r.status})`);
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

function item(v) {
  const [main1, backup] = v.approvers || [];
  const [tone, word] = STATUS[v.status] || ["", v.status];
  return `<details><summary>
      <span><b>${x(v.name)}${plus(v)}</b><small>${x(v.phone)}</small></span>
      <span class="mid"><b>${x(v.reason)}</b><small>Visiting ${x(v.visiting)}</small></span>
      <span class="side"><code>${x(v.reference)}</code><br>
        <span class="pill" data-tone="${tone}">${x(word)}</span></span>
    </summary>
    <div class="more"><dl>
      <dt>Address</dt><dd>${x(v.address)}</dd>
      <dt>Reason</dt><dd>${x(v.reason)}</dd>
      <dt>Visiting</dt><dd>${x(v.visiting)}</dd>
      <dt>With</dt><dd>${v.guests.length ? x(v.guests.join(", ")) : "No one"}</dd>
      <dt>Approvers</dt><dd>${x(main1)}${backup && backup !== main1 ? `, backup ${x(backup)}` : " (also the backup)"}</dd>
      <dt>Requested</dt><dd>${when(v.created_at)}</dd>
      <dt>Sent to backup</dt><dd>${when(v.escalated_at)}</dd>
      <dt>Decided</dt><dd>${when(v.decided_at)}</dd>
      <dt>Entered</dt><dd>${when(v.entered_at)}</dd>
      <dt>Gate photo</dt><dd>${when(v.photo_at)}</dd>
      <dt>Exited</dt><dd>${when(v.exited_at)}</dd>
    </dl></div></details>`;
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

function renderApprovers() {
  el("approvers").innerHTML = `<table><thead><tr><th>Reason</th><th>Approver</th><th>Backup</th></tr></thead>
    <tbody>${approvers.map(a => `<tr><td>${x(a.reason)}</td><td>${x(a.main)}</td><td>${x(a.backup)}</td></tr>`).join("")}</tbody></table>`;
}

function renderNotice() {
  el("notice").innerHTML = notice ? `<div class="note bad">${x(notice)}</div>` : "";
}

function render() {
  const haveKey = !!key();
  el("nav").hidden = !haveKey;
  if (!haveKey) {
    main.innerHTML = `<div class="keybox">
        ${notice ? `<div class="note bad">${x(notice)}</div>` : ""}
        <label for="k">Admin key</label>
        <input id="k" type="password" autocomplete="current-password" enterkeyhint="go">
        <button class="btn" id="save">Open the list</button>
        <p class="hint">This is ADMIN_KEY, or the gate key while ADMIN_KEY is not set.</p></div>`;
    el("save").onclick = saveKey;
    el("k").onkeydown = e => { if (e.key === "Enter") saveKey(); };
    el("k").focus();
    return;
  }
  // The search box is built once, so typing never loses focus to a redraw.
  if (!el("list")) {
    main.innerHTML = `
      <div id="notice"></div>
      <div class="tiles" id="tiles"></div>
      <div class="bar"><input id="q" type="search" placeholder="Search name, phone, code or person visited"
        aria-label="Search" autocomplete="off" spellcheck="false"></div>
      <p class="found" id="found"></p>
      <div class="list" id="list"></div>
      <button class="btn plain" id="more" hidden>Show more</button>
      <h2>Who approves each reason</h2>
      <div class="wrap" id="approvers"></div>
      <p class="hint" id="rules"></p>`;
    el("tiles").onclick = e => {
      const hit = e.target.closest("[data-filter]");
      if (hit && hit.dataset.filter !== filter) { filter = hit.dataset.filter; void load(); }
    };
    el("q").oninput = e => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { query = e.target.value.trim(); void load(); }, SEARCH_WAIT);
    };
    el("more").onclick = () => void load(true);
  }
  renderNotice();
  renderTiles();
  renderList();
  renderApprovers();
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
    if (el("rules")) {
      el("rules").textContent = `A request goes to the backup approver after ${s.escalate_minutes} minutes`
        + ` with no answer. Records are deleted after ${s.retain_days} days.`;
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
