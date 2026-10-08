/* global saveFile, askForKey */  // from shared.js, which admin.html loads first
const CALL_TIMEOUT = 75000;  // a sleeping free server can take ~50s to wake
const SEARCH_WAIT = 300;     // ms after the last key press before a search runs
const IDLE_MINUTES = 30;     // no click or key press for this long signs the page out

const el = i => document.getElementById(i);
const main = el("main");
const ESC = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
const x = s => String(s ?? "").replace(/[&<>"']/g, c => ESC[c]);
// One formatter each, made once: making one for every row is the slow part of a long list.
const WHEN_FORMAT = new Intl.DateTimeFormat([], {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"});
const DAY_FORMAT = new Intl.DateTimeFormat([], {day: "numeric", month: "short", year: "numeric"});
const TIME_FORMAT = new Intl.DateTimeFormat([], {hour: "2-digit", minute: "2-digit"});
const LONG_DAY = new Intl.DateTimeFormat([], {weekday: "long", day: "numeric", month: "long"});
const when = t => t ? WHEN_FORMAT.format(new Date(t)) : "—";
const day = t => DAY_FORMAT.format(new Date(t));
const clock = t => TIME_FORMAT.format(new Date(t));

// The filters, in the order of the tiles. "waiting" is pending and escalated.
const FILTERS = [
  ["all", "All"], ["waiting", "Waiting"], ["approved", "Approved"],
  ["inside", "Inside"], ["closed", "Closed"], ["declined", "Declined"],
  ["expired", "Expired"],
];
// Each status as [the pill's data-tone, the word on the pill].
const STATUS = {
  pending: ["wait", "Waiting"], escalated: ["wait", "Asked again"],
  approved: ["go", "Approved"], inside: ["go", "Inside"],
  declined: ["stop", "Declined"], closed: ["done", "Closed"],
  expired: ["done", "Expired"],
};

// The side menu, grouped by how often each part is used. A one-item row is a group heading.
const ICONS = {
  today: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  visits: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  staff: '<circle cx="9" cy="8" r="4"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6M16 11l2 2 4-4"/>',
  blacklist: '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>',
  numbers: '<path d="M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 9h4a1 1 0 0 1 1 1v11M8 8h3M8 12h3M8 16h3M2 21h20"/>',
  guards: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  admins: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3"/>',
  log: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
};
const MENU = [
  ["Daily"], ["today", "Today"], ["visits", "Visits"],
  ["People"], ["staff", "Allow list"], ["blacklist", "Blacklist"],
  ["Setup"], ["numbers", "Approvers & offices"], ["guards", "Guards"], ["admins", "Admins"],
  ["log", "Change log"],
];
const SECTIONS = Object.fromEntries(MENU.filter(m => m.length === 2));

// The lists with an add form and a Delete button. Each form field is [name, label, type].
const PHONE = ["phone", "WhatsApp number", "tel"];
const TAG = ["tag", "Tag (you may leave it empty)", "text"];
const FORMS = {
  staff: {prefix: "s", url: "/api/admin/staff", title: "Add to the allow list", open: "Add person",
          button: "Add and make a code", fields: [["name", "Name", "text"], PHONE, TAG]},
  offices: {prefix: "o", url: "/api/admin/offices", title: "Add an office", open: "Add office",
            button: "Add office", fields: [["name", "Office name", "text"], ["main", "Approver", "tel"],
                                          ["backup", "Backup approver (you may leave it empty)", "tel"], TAG]},
  guards: {prefix: "g", url: "/api/admin/guards", title: "Add a guard", open: "Add guard",
           button: "Add guard and make a key", fields: [["name", "Name", "text"], PHONE]},
  admins: {prefix: "a", url: "/api/admin/admins", title: "Add an admin", open: "Add admin",
           button: "Add admin and make a key", fields: [["name", "Name", "text"], PHONE]},
  blacklist: {prefix: "b", url: "/api/admin/blacklist", title: "Add to the blacklist", open: "Add number",
              button: "Add to the blacklist", tone: "stop",
              fields: [["name", "Name", "text"], ["phone", "Phone number", "tel"],
                       ["reason", "Reason (you may leave it empty)", "text"]]},
};
// The fields a form needs. A backup approver and a ban's reason may stay empty.
const MISSING = {name: "Type the name.", phone: "Type the phone number.",
                 main: "Type the approver's number."};
// One person as approver and backup: the table says so, rather than the number twice.
const backupCell = row => row.backup === row.main ? `<span class="fixed">Same as approver</span>` : x(row.backup);

// The open part, from the address, so Refresh and Back keep the place.
const fromHash = () => SECTIONS[window.location.hash.slice(1)] ? window.location.hash.slice(1) : "";
let section = fromHash() || "today";
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
// Minutes before a working-hours request approves by itself, where no time is set. 0 is never.
let autoDefault = 30;
// The waiting requests for the Today page: the first page of them.
let waiting = [];
let waitingMore = false;
// What the server's lists hold. Every change answers with all of them.
const EMPTY_TEAM = {gate_desk: "", guards: [], main_admin: "", admins: [], you: "",
                    offices: [], staff: [], staff_entries: [], staff_today: [], blacklist: [], blocked: [],
                    changes: [], super: false};
let team = {...EMPTY_TEAM};
const formErrors = {staff: {}, offices: {}, guards: {}, admins: {}, blacklist: {}};
// One note per list, as {tone, html}: a new key or code shows here once.
let notes = {};
let loading = false;
// The two long lists can be cut down by tag and by search. null shows every tag, "" no tag.
// Each shows PAGE rows at first, so a redraw costs the same for 200 or 20,000 people.
const PAGE = 200;
const views = {staff: {tag: null, q: "", limit: PAGE}, offices: {tag: null, q: "", limit: PAGE}};
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

// The page signs out by itself after IDLE_MINUTES with no click or key press, also in a
// hidden tab: the last use is stored, so it is checked when the tab is seen again.
const SEEN = "adminseen";
let seenWritten = 0;

function touch(now = Date.now()) {
  if (now - seenWritten < 30000) return;
  seenWritten = now;
  try { localStorage.setItem(SEEN, String(now)); } catch { /* this page view only */ }
}

function idle() {
  if (!key()) return false;
  let seen = 0;
  try { seen = Number(localStorage.getItem(SEEN)) || 0; } catch { /* nothing stored */ }
  if (!seen || Date.now() - seen < IDLE_MINUTES * 60000) return false;
  forgetKey("", `Signed out after ${IDLE_MINUTES} minutes with no use. Type your key to open the page again.`);
  return true;
}

function forgetKey(why = "", note = "") {
  try { localStorage.removeItem("adminkey"); localStorage.removeItem(SEEN); } catch { /* never stored */ }
  seenWritten = 0;
  rows = []; next = null; counts = {}; approvers = []; notes = {}; notice = why; info = note;
  waiting = []; waitingMore = false;
  team = {...EMPTY_TEAM};
  for (const reference in photos) delete photos[reference];
  el("over").innerHTML = "";
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
    {fields: data.fields || {}, status: r.status});
  return data;
}

// A box keeps the keyboard inside it while open, and hands the focus back when it closes.
function holdFocus(sheet) {
  const opener = document.activeElement;
  sheet.addEventListener("keydown", e => {
    if (e.key !== "Tab") return;
    const stops = [...sheet.querySelectorAll("button, input")];
    const first = stops[0], last = stops[stops.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  return () => { if (opener && document.contains(opener)) opener.focus(); };
}

// Asks before a deletion, a ban or a bulk decision. Resolves true only for the first button.
function confirmDelete(line, yes = "Delete", tone = "stop") {
  return new Promise(done => {
    el("over").innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sure">
      <div class="box"><h2 id="sure">Are you sure?</h2><p>${x(line)}</p>
        <button class="btn ${tone}" id="sure-yes">${x(yes)}</button>
        <button class="btn plain" id="sure-no">Cancel</button></div></div>`;
    const sheet = el("over").firstElementChild;
    const giveBack = holdFocus(sheet);
    const close = answer => { el("over").innerHTML = ""; giveBack(); done(answer); };
    el("sure-yes").onclick = () => close(true);
    el("sure-no").onclick = () => close(false);
    sheet.onclick = e => { if (e.target === sheet) close(false); };
    sheet.onkeydown = e => { if (e.key === "Escape") close(false); };
    el("sure-no").focus();
  });
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
const DECIDER = {main: "the approver", backup: "the backup approver", blacklist: "the blacklist"};

// [tone, line] for who decided. An old decision names only the role.
function decision(v) {
  if (!v.decided_at) return ["", ""];
  if (v.decided_by === "auto") return ["go", "Approved automatically: no one answered in time"];
  const [tone, word] = v.status === "declined" ? ["stop", "Declined"] : ["go", "Approved"];
  // A super admin's bulk decision names that admin.
  if (v.decided_by === "admin") return [tone, `${word} by ${v.decided_phone || "an admin"} on the admin page`];
  const who = DECIDER[v.decided_by];
  return [tone, who ? `${word} by ${who}${v.decided_phone ? ` ${v.decided_phone}` : ""}` : word];
}

// The open part of a visit row: every detail, then the blacklist button.
function visitMore(v, byLine) {
  const [main1, backup] = v.approvers || [];
  return `<div class="more"><dl>
      <dt>Address</dt><dd>${x(v.address)}</dd>
      <dt>Reason</dt><dd>${x(v.reason)}</dd>
      ${v.office ? `<dt>Office</dt><dd>${x(v.office)}</dd>` : `<dt>Visiting</dt><dd>${x(v.visiting)}</dd>`}
      <dt>With</dt><dd>${v.guests.length ? x(v.guests.join(", ")) : "No one"}</dd>
      <dt>Approvers now</dt><dd>${x(main1)}${backup && backup !== main1 ? `, backup ${x(backup)}` : " (also the backup)"}</dd>
      <dt>Requested</dt><dd>${when(v.created_at)}</dd>
      <dt>Pass valid until</dt><dd>${when(v.expires_at)}</dd>
      <dt>Asked again</dt><dd>${when(v.escalated_at)}</dd>
      <dt>Decided</dt><dd>${when(v.decided_at)}</dd>
      <dt>Decision</dt><dd>${x(byLine || "Not decided yet")}</dd>
      <dt>Entered</dt><dd>${when(v.entered_at)}${v.entered_by ? ` by ${x(v.entered_by)}` : ""}</dd>
      <dt>Gate photo</dt><dd>${when(v.photo_at)}${photoLine(v)}</dd>
      <dt>Exited</dt><dd>${when(v.exited_at)}${v.exited_by ? ` by ${x(v.exited_by)}` : ""}</dd>
    </dl>
    <button class="small del ban" data-ban="${x(v.phone)}" data-name="${x(v.name)}">Blacklist this number</button>
    </div>`;
}

function item(v) {
  const [tone, word] = STATUS[v.status] || ["", v.status];
  const [byTone, byLine] = decision(v);
  const body = `<details class="visit"><summary>
      <span><b>${x(v.name)}${plus(v)}</b><small>${x(v.phone)}</small>
        ${byLine ? `<small class="by" data-tone="${byTone}">${x(byLine)}</small>` : ""}</span>
      <span class="mid"><b>${x(v.reason)}</b><small>Visiting ${x(v.visiting)}</small></span>
      <span class="side-col"><code>${x(v.reference)}</code><br>
        <span class="pill" data-tone="${tone}">${x(word)}</span></span>
    </summary>
    ${visitMore(v, byLine)}</details>`;
  if (!pickable(v)) return body;
  return `<div class="pickrow"><label class="tick"><input type="checkbox" data-pick-ref="${x(v.reference)}"
      aria-label="Select ${x(v.name)} ${x(v.reference)}"></label>${body}</div>`;
}

// The gate page's photo loads only when the admin asks, then stays for this page view.
const photos = {};
function photoLine(v) {
  if (photos[v.reference]) {
    return `<span class="shot"><img src="${x(photos[v.reference])}" alt="The visitor at the gate"></span>`;
  }
  if (v.photo_stored) {
    return team.super
      ? ` <button class="small edit" data-photo="${x(v.reference)}">View photo</button><span class="shot"></span>`
      : " (stored: a super admin can view it)";
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

// ------------------------------------------------- bulk decisions, super admins only
// The waiting requests chosen on screen, by reference. Today and Visits share the choice.
const picked = new Set();
let bulkNote = null;
const pickable = v => team.super && (v.status === "pending" || v.status === "escalated");
// Ticks the boxes of the chosen requests in a list just drawn.
function tickPicked(box) {
  for (const tick of box.querySelectorAll("[data-pick-ref]")) tick.checked = picked.has(tick.dataset.pickRef);
}

const BULKS = {
  visits: {box: "bulk", all: "pick-all", count: "picked-count", yes: "bulk-yes", no: "bulk-no",
           note: "bulk-note", rows: () => rows},
  today: {box: "t-bulk", all: "t-pick-all", count: "t-picked", yes: "t-yes", no: "t-no",
          note: "t-note", rows: () => waiting},
};

function renderBulk() {
  if (!el("bulk")) return;
  // A row that left the screen, or stopped waiting, leaves the selection too.
  const open = new Set([...rows, ...waiting].filter(pickable).map(v => v.reference));
  for (const reference of [...picked]) if (!open.has(reference)) picked.delete(reference);
  for (const b of Object.values(BULKS)) drawBulk(b);
}

// One bulk bar: Select all, the count, Approve and Decline.
function drawBulk(b) {
  const mine = b.rows().filter(pickable);
  const n = picked.size;
  el(b.box).hidden = !mine.length;
  const all = mine.length && mine.every(v => picked.has(v.reference));
  el(b.all).textContent = all ? "Clear the selection" : `Select all ${mine.length} waiting on screen`;
  el(b.count).textContent = `${n} selected`;
  el(b.yes).textContent = n ? `Approve ${n}` : "Approve";
  el(b.no).textContent = n ? `Decline ${n}` : "Decline";
  el(b.yes).disabled = el(b.no).disabled = !n;
  el(b.note).innerHTML = bulkNote ? `<div class="note ${bulkNote.tone}">${bulkNote.html}</div>` : "";
}

function pickAll(which = "visits") {
  const mine = BULKS[which].rows().filter(pickable);
  if (mine.every(v => picked.has(v.reference))) for (const v of mine) picked.delete(v.reference);
  else for (const v of mine) picked.add(v.reference);
  renderList();
  renderToday();
}

// The words and color for each bulk choice.
const BULK = {
  approve: {verb: "Approve", done: "Approved", tone: "go",
    ask: what => `Approve ${what}? Each guard gets one WhatsApp message with the list.`},
  decline: {verb: "Decline", done: "Declined", tone: "stop",
    ask: what => `Decline ${what}? The visitors see Declined.`},
};

async function bulkDecide(choice) {
  const references = [...picked];
  const n = references.length;
  const words = BULK[choice];
  const what = `${n} ${n === 1 ? "request" : "requests"}`;
  if (!(await confirmDelete(words.ask(what), `${words.verb} ${n}`, words.tone))) return;
  try {
    const answer = await call("/api/admin/decide", {references, decision: choice});
    picked.clear();
    const skipped = answer.skipped.map(s => `${x(s.reference)}: ${x(s.why)}`).join("<br>");
    bulkNote = {tone: answer.skipped.length ? "bad" : "good",
      html: `${words.done} ${answer.decided.length}.`
        + (skipped ? ` Not changed:<br>${skipped}` : "")};
    refresh();
  } catch (err) {
    if (err instanceof WrongKey) return forgetKey(err.message);
    bulkNote = {tone: "bad", html: x(err.message)};
    renderBulk();
  }
}

function renderList() {
  if (!el("list")) return;
  el("list").innerHTML = rows.length
    ? rows.map(item).join("")
    : `<div class="empty">${loading ? "Loading…" : query ? "No request matches that search." : "No requests here."}</div>`;
  tickPicked(el("list"));
  el("found").textContent = rows.length
    ? `Showing ${rows.length} ${rows.length === 1 ? "request" : "requests"}${next ? ". Show more loads the next ones." : "."}`
    : "";
  const more = el("more");
  more.hidden = !next;
  more.disabled = loading;
  more.textContent = loading ? "Loading…" : "Show more";
  renderBulk();
}

// ------------------------------------------------------------------- Today
const DAY_MS = 86400000;
const recentBlocks = () => team.blocked.filter(a => Date.now() - Date.parse(a.at) < DAY_MS);

function stat(go, n, label, tone) {
  return `<button class="stat" data-go="${go}" data-tone="${n ? tone : ""}"><b>${n}</b> <span>${label}</span></button>`;
}

// Staff today, from the server: each person who moved since midnight, or is still in from a
// night shift, once, newest first. Cut down by the chips and the search, and shown STAFF_PAGE rows at a time.
const STAFF_PAGE = 25;
const staffDay = {show: "entry", q: "", limit: STAFF_PAGE};
const STAFF_SHOWS = [["entry", "On campus"], ["exit", "Left"], ["all", "All today"]];
const onCampus = () => team.staff_today.filter(p => p.last_kind === "entry");

function staffMatches(p) {
  if (staffDay.show !== "all" && p.last_kind !== staffDay.show) return false;
  const q = staffDay.q.toLowerCase();
  return !q || [p.name, p.code, p.tag].some(v => String(v || "").toLowerCase().includes(q));
}

// A time from yesterday, as after a night shift, shows its date.
const dayClock = t => new Date(t).toDateString() === new Date().toDateString() ? clock(t) : when(t);

function staffRow(p) {
  const [tone, state] = p.last_kind === "entry" ? ["go", "In since"] : ["stop", "Out at"];
  const first = p.last_kind === "exit" && p.first_in ? ` · First in ${dayClock(p.first_in)}` : "";
  return `<li><span><b>${x(p.name)}</b><small>${p.tag ? `${x(p.tag)} · ` : ""}<code>${x(p.code)}</code>${first}
    · ${x(p.last_by)}</small></span><span class="pill" data-tone="${tone}">${state} ${dayClock(p.last_at)}</span></li>`;
}

function renderStaffToday() {
  const all = team.staff_today;
  const inside = onCampus().length;
  const n = {entry: inside, exit: all.length - inside, all: all.length};
  el("t-staff-chips").innerHTML = STAFF_SHOWS.map(([show, label]) =>
    `<button data-show="${show}">${label} <span>${n[show]}</span></button>`).join("");
  for (const chip of el("t-staff-chips").children) {
    chip.setAttribute("aria-pressed", chip.dataset.show === staffDay.show ? "true" : "false");
  }
  const found = all.filter(staffMatches);
  const shown = found.slice(0, staffDay.limit);
  const empty = !all.length ? "No staff came in yet today."
    : staffDay.q ? "No one today matches the search."
    : staffDay.show === "entry" ? "No staff member is on campus now." : "No staff member left yet today.";
  el("t-staff").innerHTML = shown.length
    ? `<ul class="mini">${shown.map(staffRow).join("")}</ul>`
      + (found.length > shown.length
        ? `<button class="small edit" data-staff-more>Show more (${found.length - shown.length} left)</button>` : "")
    : `<p class="fixed">${empty}</p>`;
}

function renderToday() {
  if (!el("t-list")) return;
  const blocks = recentBlocks();
  el("today-date").textContent = LONG_DAY.format(new Date());
  el("stats").innerHTML = stat("visits:waiting", count("waiting"), "Waiting for a decision", "wait")
    + stat("visits:inside", count("inside"), "Visitors inside now", "go")
    + stat("staff", onCampus().length, "Staff on campus now", "go")
    + stat("blacklist", blocks.length, "Blocked in 24 hours", "stop");
  el("t-count").textContent = waiting.length ? `${waiting.length}${waitingMore ? "+" : ""}` : "";
  el("t-count").hidden = !waiting.length;
  el("t-list").innerHTML = waiting.length ? waiting.map(item).join("")
    : `<div class="empty">Nothing is waiting. New requests show here.</div>`;
  tickPicked(el("t-list"));
  renderStaffToday();
  el("t-blocked").innerHTML = blocks.length
    ? `<ul class="mini">${blocks.slice(0, 5).map(a => `<li><span><b>${x(a.name)}</b>
        <small>${x(a.what)}</small></span><time>${clock(a.at)}</time></li>`).join("")}</ul>`
    : `<p class="fixed">The blacklist stopped no one in the last 24 hours.</p>`;
  renderBulk();
}

async function loadWaiting() {
  try {
    const page = await call("/api/admin/visits?status=waiting");
    waiting = page.visits || [];
    waitingMore = !!page.next;
  } catch (err) {
    if (err instanceof WrongKey) return forgetKey(err.message);
    // The Visits list shows the same failure, so Today stays quiet.
  }
  if (key()) renderToday();
}

// ------------------------------------------------------------------- approvers
// When requests approve by themselves. null uses the server's default.
const autoWords = m => m ? `After ${m} min` : "Never";
const autoCell = m => m === null || m === undefined
  ? `${autoWords(autoDefault)} <span class="fixed">(default)</span>` : autoWords(m);
const AUTO_HINT = () => `Only for a request made in working hours with no answer. Empty: the default,
  ${autoWords(autoDefault).toLowerCase()}. 0: never.`;

function approverRow(a) {
  if (a.reason !== editing) {
    return `<tr><td>${x(a.reason)}</td><td>${x(a.main)}</td><td>${backupCell(a)}</td><td>${autoCell(a.auto_minutes)}</td>
      <td class="acts"><button class="small edit" data-edit="${x(a.reason)}">Change</button></td></tr>`;
  }
  const field = (name, label, value) => `<div>
      <label for="ap-${name}">${label}</label>
      <input id="ap-${name}" type="tel" inputmode="tel" autocomplete="off" value="${x(value)}"
        placeholder="+919876543210">
      ${fieldErrors[name] ? `<p class="err">${x(fieldErrors[name])}</p>` : ""}</div>`;
  // The approver as their own backup shows an empty backup box.
  const typed = draft || {...a, backup: a.backup === a.main ? "" : a.backup, auto: a.auto_minutes ?? ""};
  return `<tr><td colspan="5"><b>${x(a.reason)}</b>
      <div class="pair">${field("main", "Approver", typed.main)}${field("backup", "Backup approver (you may leave it empty)", typed.backup)}</div>
      <div class="pair"><div>
        <label for="ap-auto">Approve by itself after (minutes)</label>
        <input id="ap-auto" type="text" inputmode="numeric" maxlength="4" autocomplete="off" value="${x(typed.auto)}">
        <p class="hint">${AUTO_HINT()}</p>
        ${fieldErrors.auto_minutes ? `<p class="err">${x(fieldErrors.auto_minutes)}</p>` : ""}</div></div>
      <div class="pair gap-top">
        <button class="btn" id="ap-save">Save</button>
        <button class="btn plain" id="ap-cancel">Cancel</button></div></td></tr>`;
}

function renderApprovers() {
  if (!el("approvers")) return;
  el("approvers").innerHTML = `<table><thead><tr><th>Reason</th><th>Approver</th><th>Backup</th>
    <th>Approves by itself</th><th></th></tr></thead>
    <tbody>${approvers.map(approverRow).join("")}</tbody></table>`;
  el("approver-note").innerHTML = approverNote ? `<div class="note good">${x(approverNote)}</div>` : "";
  labelCells(el("approvers"));
  if (editing) {
    el("ap-save").onclick = () => void saveApprovers();
    el("ap-cancel").onclick = () => { editing = null; draft = null; fieldErrors = {}; renderApprovers(); };
  }
}

async function saveApprovers() {
  const main1 = el("ap-main").value.trim(), backup = el("ap-backup").value.trim();
  const auto = el("ap-auto").value.trim();
  draft = {main: main1, backup, auto};
  fieldErrors = {};
  if (!main1) fieldErrors.main = "Type the approver's number.";
  if (fieldErrors.main) return renderApprovers();
  el("ap-save").disabled = true;
  // The admin can open another reason meanwhile. The answer speaks for this one.
  const reason = editing;
  try {
    const saved = await call("/api/admin/approvers", {reason, main: main1, backup, auto_minutes: auto});
    approvers = saved.approvers;
    approverNote = `Saved. New and open requests for ${reason} now go to these numbers.`;
    if (editing === reason) { editing = null; draft = null; }
  } catch (err) {
    if (err instanceof WrongKey) return forgetKey(err.message);
    if (editing === reason) {
      fieldErrors = err.fields && Object.keys(err.fields).length ? err.fields : {backup: err.message};
    }
  }
  renderApprovers();
}

// ------------------------------------------- staff, offices, guards and admins
const del = (kind, id, label) =>
  `<button class="small del" data-delete="${kind}" data-id="${x(id)}" data-label="${x(label)}">Delete</button>`;
const newKey = (kind, phone) => `<button class="small warn" data-newkey="${kind}" data-id="${x(phone)}">New key</button>`;
const you = label => label === team.you ? `<span class="you">You</span>` : "";
const table = (heads, body) => `<table><thead><tr>${heads.map(h => `<th>${h}</th>`).join("")}</tr></thead>
  <tbody>${body}</tbody></table>`;

// On a phone each row turns into a card, and each cell shows its column name.
function labelCells(box) {
  const heads = [...box.querySelectorAll("thead th")].map(th => th.textContent);
  for (const row of box.querySelectorAll("tbody tr")) {
    [...row.children].forEach((cell, i) => {
      if (heads[i] && !cell.hasAttribute("colspan")) cell.dataset.label = heads[i];
    });
  }
}

// ------------------------------------------------ tags on the two long lists
// One comparer for every sort: a new one for each pair of names is slow on a long list.
const byText = new Intl.Collator(undefined, {sensitivity: "base"}).compare;
const tagsOf = kind => [...new Set(team[kind].map(r => r.tag).filter(Boolean))].sort(byText);
const KEY_OF = {staff: "code", offices: "name"};

function shows(kind, row) {
  const {tag, q} = views[kind];
  if (tag !== null && row.tag !== tag) return false;
  const wanted = q.toLowerCase();
  return !wanted || [row.name, row.phone, row.code, row.main, row.backup, row.tag]
    .some(field => String(field || "").toLowerCase().includes(wanted));
}

// The rows that pass the filter. Under All, each tag gets a heading, the untagged last.
function tagged(kind, empty, columns, line) {
  const matches = team[kind].filter(row => shows(kind, row))
    .sort((a, b) => (a.tag === "") - (b.tag === "") || byText(a.tag, b.tag) || byText(a.name, b.name));
  if (!team[kind].length) return `<tr><td colspan="${columns}" class="fixed">${empty}</td></tr>`;
  if (!matches.length) return `<tr><td colspan="${columns}" class="fixed">Nothing matches the tag or the search.</td></tr>`;
  const shown = matches.slice(0, views[kind].limit);
  const rest = matches.length - shown.length;
  const more = rest ? `<tr class="more-row"><td colspan="${columns}"><button class="small edit" data-more="${kind}">
      Show ${Math.min(PAGE, rest)} more, of ${rest} not shown</button></td></tr>` : "";
  if (views[kind].tag !== null) return shown.map(line).join("") + more;
  // One pass for every tag's count: O(n), not O(n) again for each tag. The count is of every
  // matching row, also the rows not shown yet.
  const perTag = countTags(matches);
  let out = "";
  shown.forEach((row, i) => {
    if (i === 0 || row.tag !== shown[i - 1].tag) {
      out += `<tr data-group="${x(row.tag)}"><td colspan="${columns}">${x(row.tag || "No tag")} <span>${perTag.get(row.tag)}</span></td></tr>`;
    }
    out += line(row);
  });
  return out + more;
}

function countTags(list) {
  const perTag = new Map();
  for (const row of list) perTag.set(row.tag, (perTag.get(row.tag) || 0) + 1);
  return perTag;
}

const tagButton = (kind, row, label) =>
  `<button class="small edit" data-retag="${kind}" data-id="${x(row[KEY_OF[kind]])}" data-tag="${x(row.tag)}"
    data-label="${x(label)}">Tag</button>`;
const tagCell = row => row.tag ? x(row.tag) : `<span class="fixed">No tag</span>`;

// The tag filter: All, each tag with its count, No tag. A chosen tag can be renamed.
function renderTagBar(kind) {
  const {prefix} = FORMS[kind];
  const chosen = views[kind].tag;
  const perTag = countTags(team[kind]);
  const countOf = tag => perTag.get(tag) || 0;
  const chip = (tag, label, n) => `<button data-all="${tag === null ? "yes" : "no"}" data-filter-tag="${x(tag ?? "")}">
    ${x(label)} <span>${n}</span></button>`;
  el(`${prefix}-chips`).innerHTML = (team[kind].length ? chip(null, "All", team[kind].length)
    + tagsOf(kind).map(tag => chip(tag, tag, countOf(tag))).join("")
    + (countOf("") ? chip("", "No tag", countOf("")) : "") : "")
    + (chosen ? `<button class="small edit" data-rename>Rename this tag</button>` : "");
  for (const chip of el(`${prefix}-chips`).querySelectorAll("[data-filter-tag]")) {
    const tag = chip.dataset.all === "yes" ? null : chip.dataset.filterTag;
    chip.setAttribute("aria-pressed", tag === chosen ? "true" : "false");
  }
  el(`${prefix}-tagpick`).innerHTML = pickChips(kind);
}

const pickChips = kind => tagsOf(kind).map(tag =>
  `<button type="button" class="pick" data-pick="${x(tag)}">${x(tag)}</button>`).join("");

// Asks for a tag: tap one in use, or type a new one. Resolves the tag, or null for Cancel.
function askTag(title, current, kind) {
  return new Promise(done => {
    el("over").innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="tag-title">
      <div class="box"><h2 id="tag-title">${x(title)}</h2>
        <label for="tag-new">Tag</label>
        <input id="tag-new" maxlength="40" autocomplete="off" value="${x(current)}">
        <div class="tagpick" id="tag-pick">${pickChips(kind)}</div>
        <p class="hint">Tap a tag in use, or type a new one. Leave it empty for no tag.</p>
        <button class="btn" id="tag-save">Save</button>
        <button class="btn plain" id="tag-no">Cancel</button></div></div>`;
    const sheet = el("over").firstElementChild;
    const giveBack = holdFocus(sheet);
    const close = answer => { el("over").innerHTML = ""; giveBack(); done(answer); };
    el("tag-save").onclick = () => close(el("tag-new").value.trim());
    el("tag-no").onclick = () => close(null);
    el("tag-new").onkeydown = e => { if (e.key === "Enter") close(el("tag-new").value.trim()); };
    el("tag-pick").onclick = e => {
      const pick = e.target.closest("[data-pick]");
      if (pick) el("tag-new").value = pick.dataset.pick;
    };
    sheet.onclick = e => { if (e.target === sheet) close(null); };
    sheet.onkeydown = e => { if (e.key === "Escape") close(null); };
    el("tag-new").focus();
  });
}

const tagLine = (label, tag) => `${x(label)} now has ${tag ? `the tag ${x(tag)}` : "no tag"}.`;

async function retag(kind, id, current, label) {
  const tag = await askTag(`Tag for ${label}`, current, kind);
  if (tag === null || tag === current) return;
  const answer = await teamCall(kind, `${FORMS[kind].url}/tag`, {[KEY_OF[kind]]: id, tag});
  if (answer) {
    notes[kind] = {tone: "good", html: tagLine(label, answer.tag)};
    renderTeam();
  }
}

async function renameTag(kind) {
  const old = views[kind].tag;
  const tag = await askTag(`Rename the tag ${old}`, old, kind);
  if (tag === null || tag === old) return;
  const answer = await teamCall(kind, "/api/admin/tags/rename", {list: kind, old, new: tag});
  if (answer) {
    views[kind].tag = answer.tag;
    notes[kind] = {tone: "good", html: `Every ${x(old)} row ${answer.tag ? `now has the tag ${x(answer.tag)}` : "now has no tag"}.`};
    renderTeam();
  }
}

// Asks for an office's time to approve by itself. Resolves the typed text, or null for Cancel.
function askMinutes(title, current) {
  return new Promise(done => {
    el("over").innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="auto-title">
      <div class="box"><h2 id="auto-title">${x(title)}</h2>
        <label for="auto-new">Approve by itself after (minutes)</label>
        <input id="auto-new" type="text" inputmode="numeric" maxlength="4" autocomplete="off" value="${x(current)}">
        <p class="hint">${AUTO_HINT()}</p>
        <button class="btn" id="auto-save">Save</button>
        <button class="btn plain" id="auto-no">Cancel</button></div></div>`;
    const sheet = el("over").firstElementChild;
    const giveBack = holdFocus(sheet);
    const close = answer => { el("over").innerHTML = ""; giveBack(); done(answer); };
    el("auto-save").onclick = () => close(el("auto-new").value.trim());
    el("auto-no").onclick = () => close(null);
    el("auto-new").onkeydown = e => { if (e.key === "Enter") close(el("auto-new").value.trim()); };
    sheet.onclick = e => { if (e.target === sheet) close(null); };
    sheet.onkeydown = e => { if (e.key === "Escape") close(null); };
    el("auto-new").focus();
  });
}

async function setOfficeAuto(name, current) {
  const minutes = await askMinutes(`When ${name} approves by itself`, current);
  if (minutes === null || minutes === current) return;
  const answer = await teamCall("offices", "/api/admin/offices/auto", {name, auto_minutes: minutes});
  if (answer) {
    const office = team.offices.find(o => o.name === name);
    notes.offices = {tone: "good", html: `${x(name)}: ${autoCell(office ? office.auto_minutes : null)}.`
      + " Open requests that approve by themselves have the new time."};
    renderTeam();
  }
}

function onTagBar(kind, e) {
  const hit = e.target.closest("button");
  if (!hit) return;
  if (hit.hasAttribute("data-rename")) return void renameTag(kind);
  views[kind].tag = hit.dataset.all === "yes" ? null : hit.dataset.filterTag;
  views[kind].limit = PAGE;
  renderTagged(kind);
}

// Draws one long list and its tag chips. Search and the chips redraw only their own list.
function renderTagged(kind) {
  const {prefix} = FORMS[kind];
  renderTagBar(kind);
  el(`${prefix}-table`).innerHTML = TABLES[kind]();
  labelCells(el(`${prefix}-table`));
}

const TABLES = {
  staff: () => table(["Name", "WhatsApp number", "Code", "Tag", "Added", ""],
    tagged("staff", "No one is on the allow list yet. Tap Add person.", 6, p => `<tr><td>${x(p.name)}</td><td>${x(p.phone)}</td>
        <td><code>${x(p.code)}</code></td><td>${tagCell(p)}</td><td>${day(p.added_at)}</td>
        <td class="acts">${tagButton("staff", p, p.name)}
          ${del("staff", p.code, `${p.name} ${p.code}`)}</td></tr>`)),
  offices: () => table(["Office", "Approver", "Backup", "Approves by itself", "Tag", ""],
    tagged("offices", "No offices yet. Visitors type the office's name.", 6, o => `<tr><td>${x(o.name)}</td>
        <td>${x(o.main)}</td><td>${backupCell(o)}</td><td>${autoCell(o.auto_minutes)}</td><td>${tagCell(o)}</td>
        <td class="acts"><button class="small edit" data-auto="${x(o.name)}" data-minutes="${x(o.auto_minutes ?? "")}">Time</button>
          ${tagButton("offices", o, o.name)}
          ${del("offices", o.name, o.name)}</td></tr>`)),
  blacklist: () => table(["Name", "Phone number", "Reason", "Added", ""], team.blacklist.length
    ? team.blacklist.map(b => `<tr><td>${x(b.name)}</td><td>${x(b.phone)}</td><td>${x(b.reason || "—")}</td>
        <td>${day(b.added_at)}</td>
        <td class="acts">${del("blacklist", b.phone, `${b.name} ${b.phone}`)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="fixed">No number is on the blacklist.</td></tr>`),
  guards: () => table(["Name", "WhatsApp number", "Added", ""],
    `<tr><td>Gate desk</td><td>${x(team.gate_desk)}</td>
       <td colspan="2" class="fixed">Set on the server by the host. Uses the shared gate key.</td></tr>`
    + team.guards.map(g => `<tr><td>${x(g.name)}</td><td>${x(g.phone)}</td><td>${day(g.added_at)}</td>
        <td class="acts">${newKey("guards", g.phone)}
          ${del("guards", g.phone, `${g.name} ${g.phone}`)}</td></tr>`).join("")),
  admins: () => table(["Name", "WhatsApp number", "Added", ""],
    `<tr><td>Main admin${you("Main admin")}${SUPER}</td><td>${x(team.main_admin)}</td>
       <td colspan="2" class="fixed">Set on the server by the host. Uses the main admin key.</td></tr>`
    + team.admins.map(a => `<tr><td>${x(a.name)}${you(`${a.name} ${a.phone}`)}${a.super ? SUPER : ""}</td>
        <td>${x(a.phone)}</td><td>${day(a.added_at)}</td><td class="acts">${adminActions(a)}</td></tr>`).join("")),
};

const SUPER = ` <span class="you super">Super admin</span>`;

// Only a super admin may act on a super admin: a new key would let anyone take their place.
function adminActions(a) {
  const label = `${a.name} ${a.phone}`;
  // An admin opens everything, so only a super admin adds, renews or removes one.
  if (!team.super) return `<span class="fixed">Only a super admin can change this.</span>`;
  const role = team.super && label !== team.you
    ? `<button class="small ${a.super ? "del" : "go"}" data-super="${x(a.phone)}" data-on="${!a.super}" data-label="${x(label)}">
        ${a.super ? "Remove super admin" : "Make super admin"}</button>` : "";
  return `${role} ${newKey("admins", a.phone)} ${del("admins", a.phone, label)}`;
}

async function setSuper(phone, on, label) {
  const line = on
    ? `Make ${label} a super admin? A super admin can approve and decline many requests at once, download the logs, and change other super admins.`
    : `Take away super admin from ${label}? They stay an admin.`;
  if (!(await confirmDelete(line, on ? "Make super admin" : "Take it away", on ? "go" : "stop"))) return;
  if (await teamCall("admins", "/api/admin/admins/super", {phone, super: on})) {
    notes.admins = {tone: "good", html: `${x(label)} ${on ? "is now a super admin" : "is no longer a super admin"}.`};
    renderTeam();
  }
}

// What each Delete removes, and what the "Are you sure?" box says about it.
const DELETES = {
  staff: [id => ({code: id}), l => `Delete ${l} from the allow list? The code stops working at once. Past entries stay in the log.`],
  offices: [id => ({name: id}), l => `Delete the office ${l}? Visitors can no longer pick it. Its open requests go to the approvers for Other.`],
  blacklist: [id => ({phone: id}), l => `Take ${l} off the blacklist? The number can request a visit and enter again.`],
  guards: [id => ({phone: id}), l => `Delete the guard ${l}? Their key and their WhatsApp commands stop at once.`],
  admins: [id => ({phone: id}), l => `Delete the admin ${l}? Their admin key stops at once.`],
};

const MOVE_PILLS = {entry: `<span class="pill" data-tone="go">In</span>`,
                    exit: `<span class="pill" data-tone="stop">Out</span>`};

function renderEntries() {
  el("s-entries").innerHTML = table(["When", "In or out", "Name", "Code", "Recorded by"], team.staff_entries.length
    ? team.staff_entries.map(e => `<tr><td>${when(e.entered_at)}</td><td>${MOVE_PILLS[e.kind] || ""}</td>
        <td>${x(e.name)}</td><td><code>${x(e.code)}</code></td><td>${x(e.entered_by)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="fixed">No entries yet.</td></tr>`);
  labelCells(el("s-entries"));
}

// Each time the blacklist stopped someone. The alert shows on every part for a day.
function renderBlocked() {
  el("b-attempts").innerHTML = table(["When", "Name", "Phone number", "What happened", "Where"],
    team.blocked.length
      ? team.blocked.map(a => `<tr><td>${when(a.at)}</td><td>${x(a.name)}</td><td>${x(a.phone)}</td>
          <td>${x(a.what)}${a.detail ? ` <code>${x(a.detail)}</code>` : ""}</td><td>${x(a.by_whom)}</td></tr>`).join("")
      : `<tr><td colspan="5" class="fixed">The blacklist has stopped no one yet.</td></tr>`);
  labelCells(el("b-attempts"));
  const blocks = recentBlocks().length;
  el("alert").innerHTML = blocks
    ? `<div class="note bad alert"><span>The blacklist stopped ${blocks === 1 ? "one attempt" : `${blocks} attempts`}
        in the last 24 hours.</span><button class="small" data-section="blacklist">See who</button></div>`
    : "";
  renderMenu();
}

// Each add form's table, note and field errors.
function renderForms() {
  for (const [kind, spec] of Object.entries(FORMS)) {
    if (!(kind in views)) {
      el(`${spec.prefix}-table`).innerHTML = TABLES[kind]();
      labelCells(el(`${spec.prefix}-table`));
    }
    const note = notes[kind];
    el(`${spec.prefix}-note`).innerHTML = note ? `<div class="note ${note.tone}">${note.html}</div>` : "";
    for (const [name] of spec.fields) {
      el(`${spec.prefix}-${name}-err`).textContent = formErrors[kind][name] || "";
    }
    // A form with a problem stays open, so the admin sees why.
    if (Object.keys(formErrors[kind]).length) el(`${spec.prefix}-form`).hidden = false;
  }
}

function renderChanges() {
  el("a-changes").innerHTML = table(["When", "Who", "What", "Details"], team.changes.length
    ? team.changes.map(c => `<tr><td>${when(c.at)}</td><td>${x(c.by_whom)}</td><td>${x(c.action)}</td>
        <td>${x(c.detail || "—")}</td></tr>`).join("")
    : `<tr><td colspan="4" class="fixed">No changes yet.</td></tr>`);
  labelCells(el("a-changes"));
}

function renderTeam() {
  if (!el("s-table")) return;
  for (const kind of Object.keys(views)) renderTagged(kind);
  renderForms();
  renderEntries();
  renderBlocked();
  renderChanges();
  el("you").textContent = team.you ? `Signed in as ${team.you}${team.super ? " (super admin)" : ""}` : "";
  // The logs hold every visitor's details and face: only a super admin downloads them.
  el("csv").hidden = el("s-download").hidden = !team.super;
  main.querySelector('[data-open="a"]').hidden = !team.super;
  renderToday();
  renderBulk();
}

// The add form, closed until its button opens it, so the list is the first thing on screen.
function form(kind) {
  const {prefix, fields, button, title, tone} = FORMS[kind];
  return `<div class="addbox" id="${prefix}-form" hidden><h3>${title}</h3>
    <div class="fields" data-cols="${fields.length}">${fields.map(([name, label, type]) => `<div>
      <label for="${prefix}-${name}">${label}</label>
      ${type === "tel"
        ? `<input id="${prefix}-${name}" type="tel" inputmode="tel" placeholder="+919876543210" autocomplete="off">`
        : `<input id="${prefix}-${name}" type="text" maxlength="${name === "tag" ? 40 : 60}" autocomplete="off">`}<p class="err" id="${prefix}-${name}-err"></p>
      ${name === "tag" ? `<div class="tagpick" id="${prefix}-tagpick"></div>` : ""}</div>`).join("")}</div>
    <div class="row-acts"><button class="btn${tone ? ` ${tone}` : ""}" id="${prefix}-add">${button}</button>
      <button class="btn plain" data-close="${prefix}">Cancel</button></div></div>`;
}

// A part's title row: what it is for, and its main button.
const head = (title, line, button = "") => `<header class="page-head"><div><h2>${title}</h2>
  <p>${line}</p></div>${button ? `<div class="head-acts">${button}</div>` : ""}</header>`;
const opener = kind => `<button class="btn inline ${FORMS[kind].tone || "edit"}" data-open="${FORMS[kind].prefix}">
  ${FORMS[kind].open}</button>`;
const help = (title, ...lines) => `<details class="help"><summary>${title}</summary>
  ${lines.map(line => `<p>${line}</p>`).join("")}</details>`;

// The search box and tag chips above a long list. Built once, so typing keeps the focus.
const listBar = (kind, what) => `<div class="bar"><input id="${FORMS[kind].prefix}-q" type="search"
    placeholder="Search name, number${kind === "staff" ? ", code" : ""} or tag" aria-label="Search the ${what}"
    autocomplete="off" spellcheck="false"></div>
  <div class="chips" id="${FORMS[kind].prefix}-chips"></div>`;

// The note after an add or a new key. A key is shown only this once.
function addedNote(kind, answer) {
  const name = x(answer.name);
  if (answer.code) {
    return `${name} is on the allow list with the code <code class="key">${x(answer.code)}</code>
      Tell ${name} the code. At the gate, they say it to the guard, who sends it on WhatsApp.`;
  }
  if (answer.key) {
    const which = kind === "admins" ? "admin" : "gate";
    return `The ${which} key for ${name} is <code class="key">${x(answer.key)}</code>
      Give it to ${name} now. This page shows it only once. ${name} types it on the ${which} page.
      If you cannot give it in person, ${name} sends KEY from their own WhatsApp to the app's
      number, and the app replies with a new key that only they see.`;
  }
  if (kind === "blacklist") {
    const declined = (answer.declined || []).length;
    return `${name} is on the blacklist. The number cannot request a visit, and the gate refuses its passes.`
      + (declined ? ` ${declined === 1 ? "Its waiting request was" : `Its ${declined} waiting requests were`} declined.` : "");
  }
  return `Saved. Visitors can now pick ${name}.`;
}

// A change to a list. The answer holds every list, and a new key or code when one was made.
async function teamCall(kind, url, body) {
  formErrors[kind] = {};
  notes[kind] = null;
  try {
    const answer = await call(url, body);
    Object.assign(team, answer);
    return answer;
  } catch (err) {
    if (err instanceof WrongKey) { forgetKey(err.message); return null; }
    if (Object.keys(err.fields || {}).length) formErrors[kind] = err.fields;
    else notes[kind] = {tone: "bad", html: x(err.message)};
    // Another admin changed this list meanwhile. Show the list as it is now.
    if (err.status === 404 || err.status === 409) void loadSummary();
    return null;
  } finally {
    if (key()) renderTeam();
  }
}

async function add(kind) {
  const {prefix, fields, url} = FORMS[kind];
  const body = Object.fromEntries(fields.map(([name]) => [name, el(`${prefix}-${name}`).value.trim()]));
  // The reason for a ban is the only field that may stay empty.
  formErrors[kind] = Object.fromEntries(fields.filter(([name]) => !body[name] && MISSING[name])
    .map(([name]) => [name, MISSING[name]]));
  if (Object.keys(formErrors[kind]).length) { notes[kind] = null; return renderTeam(); }
  el(`${prefix}-add`).disabled = true;
  const answer = await teamCall(kind, url, body);
  if (answer) {
    let html = addedNote(kind, {...answer, name: answer.name || body.name});
    // A new row the filter hides would look lost, so the note says why.
    const made = kind in views && team[kind].find(row => row[KEY_OF[kind]] === (answer.code || body.name));
    if (made && !shows(kind, made)) html += " It does not show below because of the tag or the search.";
    notes[kind] = {tone: "good", html};
    for (const [name] of fields) el(`${prefix}-${name}`).value = "";
    el(`${prefix}-form`).hidden = true;
    renderTeam();
  }
  if (el(`${prefix}-add`)) el(`${prefix}-add`).disabled = false;
}

async function remove(kind, id, label) {
  const [body, line] = DELETES[kind];
  if (!(await confirmDelete(line(label)))) return;
  if (await teamCall(kind, `${FORMS[kind].url}/remove`, body(id))) {
    notes[kind] = {tone: "good", html: `Deleted ${x(label)}.`};
    renderTeam();
  }
}

async function renewKey(kind, phone) {
  const answer = await teamCall(kind, `${FORMS[kind].url}/new-key`, {phone});
  if (answer) {
    notes[kind] = {tone: "good", html: addedNote(kind, answer)};
    renderTeam();
  }
}

// A visit's number goes on the blacklist, after one more question.
async function ban(button) {
  const {ban: phone, name} = button.dataset;
  if (!(await confirmDelete(`Put ${name} ${phone} on the blacklist? The number can no longer request a visit, and the gate refuses its passes.`, "Add to blacklist"))) return;
  const answer = await teamCall("blacklist", FORMS.blacklist.url, {name, phone, reason: ""});
  if (answer) {
    notes.blacklist = {tone: "good", html: addedNote("blacklist", {...answer, name})};
    renderTeam();
    void load();
  }
  goTo("blacklist");
}

function onTableClick(e) {
  const hit = e.target.closest("button");
  if (!hit) return;
  const d = hit.dataset;
  if (d.delete) void remove(d.delete, d.id, d.label);
  else if (d.newkey) void renewKey(d.newkey, d.id);
  else if (d.retag) void retag(d.retag, d.id, d.tag, d.label);
  else if (d.auto) void setOfficeAuto(d.auto, d.minutes);
  else if (d.more) { views[d.more].limit += PAGE; renderTagged(d.more); }
  else if (d.super) void setSuper(d.super, d.on === "true", d.label);
}

// ------------------------------------------------------------------- the page
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

function buildMenu() {
  el("tabs").innerHTML = MENU.map(([name, label]) => label === undefined
    ? `<p data-group="${name}">${name}</p>`
    : `<button role="tab" data-section="${name}" aria-controls="${name}">${icon(name)}<span>${label}</span>${name === "blacklist"
          ? ` <span class="count" id="blocked-count" hidden></span>` : ""}</button>`).join("");
}

// Only the count changes, so a refresh never moves the keyboard focus out of the menu.
function renderMenu() {
  const blocks = recentBlocks().length;
  el("blocked-count").textContent = blocks ? String(blocks) : "";
  el("blocked-count").hidden = !blocks;
}

function renderTabs() {
  for (const tab of el("tabs").querySelectorAll("[data-section]")) {
    tab.setAttribute("aria-selected", tab.dataset.section === section ? "true" : "false");
  }
  for (const name of Object.keys(SECTIONS)) {
    if (el(name)) el(name).hidden = name !== section;
  }
  el("where").textContent = key() ? SECTIONS[section] : "";
}

// Opens a part, and keeps it in the address, so Back returns to the part before.
function goTo(name, visitsFilter = null) {
  closeMenu();
  if (visitsFilter && visitsFilter !== filter) { filter = visitsFilter; void load(); }
  section = name;
  if (window.location.hash.slice(1) !== name) window.location.hash = name;
  renderTabs();
  window.scrollTo(0, 0);
}

function openMenu() {
  el("side").classList.add("open");
  el("scrim").classList.add("open");
  el("menu").setAttribute("aria-expanded", "true");
}

function closeMenu() {
  el("side").classList.remove("open");
  el("scrim").classList.remove("open");
  el("menu").setAttribute("aria-expanded", "false");
}

// Server settings still at a demo value. Only the server's host can change them, so it is a
// closed list with a count, not a box in the way of the daily work.
function renderGaps(gaps) {
  if (!el("gaps")) return;
  el("gaps").innerHTML = gaps.length ? `<details class="note warn"><summary>Before real use:
      ${gaps.length} server ${gaps.length === 1 ? "setting is" : "settings are"} still a demo value</summary>
      <ul>${gaps.map(g => `<li>${x(g)}</li>`).join("")}</ul>
      <p>The host changes these on the server, in the Render Environment page. See Step 7 in
        docs/setup.md.</p></details>` : "";
}

function renderNotice() {
  el("notice").innerHTML = (notice ? `<div class="note bad">${x(notice)}</div>` : "")
    + (info ? `<div class="note good">${x(info)}</div>` : "");
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

const PANELS = `
  <section id="today" hidden>
  <header class="page-head"><div><h2>Today</h2><p id="today-date"></p></div></header>
  <div id="gaps"></div>
  <div class="stats" id="stats"></div>
  <div class="cols">
    <div class="card">
      <div class="card-head"><div><h3>Waiting for a decision <span class="pill" data-tone="wait" id="t-count"></span></h3>
        <p>The approver decides on WhatsApp. A super admin can also decide here.</p></div>
        <button class="link" data-go="visits:waiting">See all in Visits</button></div>
      <div id="t-note"></div>
      <div class="bulk" id="t-bulk" hidden>
        <button class="small edit" id="t-pick-all"></button><span id="t-picked"></span>
        <button class="btn go" id="t-yes" disabled>Approve</button>
        <button class="btn stop" id="t-no" disabled>Decline</button>
      </div>
      <div class="list" id="t-list"></div>
    </div>
    <div>
      <div class="card">
        <div class="card-head"><div><h3>Staff today</h3>
          <p>A scan records an entry, the next one within 16 hours an exit.</p></div>
          <button class="link" data-go="staff">Allow list</button></div>
        <div class="bar"><input id="t-staff-q" type="search" placeholder="Search name, code or tag"
          aria-label="Search today's staff" autocomplete="off" spellcheck="false"></div>
        <div class="chips" id="t-staff-chips"></div>
        <div class="scroll" id="t-staff"></div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Blocked in the last 24 hours</h3><button class="link" data-go="blacklist">Blacklist</button></div>
        <div id="t-blocked"></div>
      </div>
    </div>
  </div>
  </section>
  <section id="visits" hidden>
  ${head("Visits", "Every request, newest first. Tap a request for its details, times and gate photo.")}
  <div class="tiles" id="tiles"></div>
  <div class="bar"><input id="q" type="search" placeholder="Search name, phone, code or person visited"
    aria-label="Search" autocomplete="off" spellcheck="false"></div>
  <p class="found" id="found"></p>
  <div id="bulk-note" role="status" aria-live="polite"></div>
  <div class="bulk" id="bulk" hidden>
    <button class="small edit" id="pick-all"></button><span id="picked-count"></span>
    <button class="btn go" id="bulk-yes" disabled>Approve</button>
    <button class="btn stop" id="bulk-no" disabled>Decline</button>
  </div>
  <div class="list" id="list"></div>
  <button class="btn plain" id="more" hidden>Show more</button>
  </section>
  <section id="staff" hidden>
  ${head("Allow list", "Staff and faculty who enter with a 7-digit code, without a request.", opener("staff"))}
  <div id="s-note"></div>
  ${form("staff")}
  ${listBar("staff", "allow list")}
  <div class="wrap" id="s-table"></div>
  <div class="card-head gap-top"><h3>Recent entries</h3>
    <button id="s-download" class="small edit" hidden>Download staff entries</button></div>
  <div class="wrap" id="s-entries"></div>
  ${help("How the allow list works",
    `Each person on the allow list gets a 7-digit code. At the gate, they say it to the guard. The
    guard sends the code to the app's WhatsApp number, or types it on the gate page in Staff code
    mode, and the entry is recorded at once. The person then gets a WhatsApp message about the
    entry, so a code used by someone else is noticed. The guard's reply names the person, so the
    guard can check the face. A number on the blacklist cannot be on the allow list.`,
    `A tag, such as a department, puts people into groups. Tap a tag in use, or type a new one. Tag
    on a row moves that person to another tag, and their code stays the same. Tap a tag above the
    list to see only that tag, and Rename this tag to rename it for everyone.`,
    `Recent entries shows the last 100. A super admin can download all of them with Download staff
    entries: a CSV file with the date in its own column, so a spreadsheet filter shows one day.`)}
  </section>
  <section id="blacklist" hidden>
  ${head("Blacklist", "Numbers that may not request a visit or enter.", opener("blacklist"))}
  <div id="b-note"></div>
  ${form("blacklist")}
  <div class="wrap" id="b-table"></div>
  <h3 class="sub">Blocked attempts</h3>
  <div class="wrap" id="b-attempts"></div>
  ${help("How the blacklist works",
    `A number on the blacklist cannot send a request: the visitor page says only that the number
    cannot request a visit. The gate refuses an entry for a pass with that number, also a pass
    approved before, on the gate page and on WhatsApp, and allow list codes for that number stop.
    The app compares the full number with its country code. A number with no country code is
    Indian, so 98765 43210 and +919876543210 are one number.`,
    `Each visit's details also have a Blacklist this number button. The blacklist cannot stop a
    person who uses another phone, or who comes as a guest on someone else's request.`,
    `Blocked attempts lists each time the blacklist stopped someone: a request on the visitor page,
    a pass checked at the gate, or an allow list code. Where names the guard. The last 100 show here.`)}
  </section>
  <section id="numbers" hidden>
  ${head("Approvers & offices", "Who gets each request on WhatsApp, and the offices a visitor can pick.")}
  <div class="card">
    <div class="card-head"><div><h3>Who approves each reason</h3>
      <p>See an office is not here: each office below has its own approvers.</p></div></div>
    <div id="approver-note"></div>
    <div class="wrap" id="approvers"></div>
    <p class="hint" id="rules"></p>
  </div>
  <div class="card" id="offices">
    <div class="card-head"><div><h3>Offices a visitor can pick</h3>
      <p>Each office has its own approver, and a backup if you add one.</p></div>${opener("offices")}</div>
    <div id="o-note"></div>
    ${form("offices")}
    ${listBar("offices", "offices")}
    <div class="wrap" id="o-table"></div>
  </div>
  ${help("How approvers work",
    `Each reason and each office needs an approver's number, with + and the country code. A backup
    is a second person who gets the request when nobody answers in time. With no backup, the
    approver gets a reminder instead.`,
    `A change works at once. New requests go to the new numbers, and each open request goes to the
    new number at once. The old numbers can no longer decide those requests. Deleting an office
    sends its open requests to the approvers for Other.`,
    `A visitor who picks See an office then picks one of the offices. With no offices here, the
    visitor types the office's name, and the request goes to the approvers for Other. A tag, such
    as a building, puts offices into groups, here and in the visitor's list.`,
    `Approves by itself: a request made in working hours with no answer is approved after this
    time. Change it for a reason, or tap Time on an office. Empty uses the default. 0 means a
    person must always decide. A change also moves the open requests that wait for it.`,
    `While the app uses Meta's test number, also add each new number to the recipient list in
    Meta's API Setup page.`)}
  </section>
  <section id="guards" hidden>
  ${head("Guards", "Who can record entry and exit, each with a gate key of their own.", opener("guards"))}
  <div id="g-note"></div>
  ${form("guards")}
  <div class="wrap" id="g-table"></div>
  ${help("How guards work",
    `Each guard gets a gate key of their own, so the log names who let each visitor in and out. A
    guard can also use IN and OUT from their WhatsApp number, and gets a message when a request is
    approved. WhatsApp delivers that message only if the guard wrote to the app's number in the last
    24 hours.`,
    `A guard who loses their key sends KEY from their phone to the app's WhatsApp number, or you tap
    New key. Delete stops the key and the WhatsApp commands at once. While the app uses Meta's test
    number, also add each guard's number to the recipient list in Meta's API Setup page.`)}
  </section>
  <section id="admins" hidden>
  ${head("Admins", "Who can open this page.", opener("admins"))}
  <div id="a-note"></div>
  ${form("admins")}
  <div class="wrap" id="a-table"></div>
  ${help("How admins work",
    `Each admin gets an admin key of their own. Only a super admin adds, renews or deletes an
    admin. An admin who loses their key sends KEY from their phone to the app's WhatsApp number. A guard's number cannot be an
    admin, and an admin's number cannot be a guard. Nobody can delete themselves.`,
    `A super admin can also approve and decline many waiting requests at once, see the gate
    photos, and download the logs. The main admin is always a super admin, and a super admin can make another admin one.
    Only a super admin can make a new key for, delete, or change a super admin.`,
    `The page signs out by itself after ${IDLE_MINUTES} minutes with no use. On a shared computer,
    tap Sign out when you finish.`)}
  </section>
  <section id="log" hidden>
  ${head("Change log", "Who changed what on this page, or by KEY on WhatsApp. Keys never show here.")}
  <div class="wrap" id="a-changes"></div>
  ${help("How the change log works",
    `It lists who added or deleted a guard, admin, office, allow list or blacklist entry, changed
    approvers, or made a new key. The last 100 show here, and Download logs saves all of them.`,
    `A change you did not expect can mean a lost phone or key: make a new key for that person, or
    delete them.`)}
  </section>`;

function bindPanels() {
  main.onclick = e => {
    const go = e.target.closest("[data-go]");
    if (go) { const [name, f] = go.dataset.go.split(":"); return goTo(name, f || null); }
    const jump = e.target.closest("[data-section]");
    if (jump) { goTo(jump.dataset.section); return el("b-attempts").scrollIntoView({block: "start"}); }
    const open = e.target.closest("[data-open]");
    if (open) {
      el(`${open.dataset.open}-form`).hidden = false;
      return el(`${open.dataset.open}-name`).focus();
    }
    const close = e.target.closest("[data-close]");
    if (close) el(`${close.dataset.close}-form`).hidden = true;
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
  for (const box of [el("list"), el("t-list")]) {
    box.addEventListener("click", e => {
      const photo = e.target.closest("[data-photo]");
      if (photo) void showPhoto(photo);
      const banned = e.target.closest("[data-ban]");
      if (banned) void ban(banned);
    });
    box.onchange = e => {
      const tick = e.target.closest("[data-pick-ref]");
      if (!tick) return;
      if (tick.checked) picked.add(tick.dataset.pickRef);
      else picked.delete(tick.dataset.pickRef);
      bulkNote = null;
      renderList();
      renderToday();
    };
  }
  el("pick-all").onclick = () => pickAll("visits");
  el("t-pick-all").onclick = () => pickAll("today");
  el("t-staff-chips").onclick = e => {
    const hit = e.target.closest("[data-show]");
    if (hit) { staffDay.show = hit.dataset.show; staffDay.limit = STAFF_PAGE; renderStaffToday(); }
  };
  let staffTyping = null;
  el("t-staff-q").oninput = e => {
    clearTimeout(staffTyping);
    staffTyping = setTimeout(() => {
      staffDay.q = e.target.value.trim();
      staffDay.limit = STAFF_PAGE;
      renderStaffToday();
    }, SEARCH_WAIT);
  };
  el("t-staff").onclick = e => {
    if (e.target.closest("[data-staff-more]")) { staffDay.limit += STAFF_PAGE; renderStaffToday(); }
  };
  for (const id of ["bulk-yes", "t-yes"]) el(id).onclick = () => void bulkDecide("approve");
  for (const id of ["bulk-no", "t-no"]) el(id).onclick = () => void bulkDecide("decline");
  el("s-download").onclick = () => void downloadLogs(["staff"]);
  for (const [kind, {prefix}] of Object.entries(FORMS)) {
    el(`${prefix}-add`).onclick = () => void add(kind);
    el(`${prefix}-table`).onclick = onTableClick;
  }
  for (const kind of Object.keys(views)) {
    const {prefix} = FORMS[kind];
    // Waits for a pause in typing, as the visits search does, then redraws this list only.
    let typing = null;
    el(`${prefix}-q`).oninput = e => {
      clearTimeout(typing);
      typing = setTimeout(() => {
        views[kind].q = e.target.value.trim();
        views[kind].limit = PAGE;
        renderTagged(kind);
      }, SEARCH_WAIT);
    };
    el(`${prefix}-chips`).onclick = e => onTagBar(kind, e);
    el(`${prefix}-tagpick`).onclick = e => {
      const pick = e.target.closest("[data-pick]");
      if (pick) el(`${prefix}-tag`).value = pick.dataset.pick;
    };
  }
  el("approvers").onclick = e => {
    const hit = e.target.closest("[data-edit]");
    if (hit) { editing = hit.dataset.edit; draft = null; fieldErrors = {}; approverNote = ""; renderApprovers(); }
  };
}

function render() {
  const haveKey = !!key();
  el("nav").hidden = el("side").hidden = el("menu").hidden = !haveKey;
  el("shell").classList.toggle("out", !haveKey);
  if (!haveKey) {
    el("you").textContent = "";
    el("where").textContent = "";
    closeMenu();
    main.innerHTML = `<div class="keybox">
        <div class="hero"><h2>Sign in</h2><p>Type your admin key to see every request.</p></div>
        ${notice ? `<div class="note bad">${x(notice)}</div>` : ""}
        ${info ? `<div class="note good">${x(info)}</div>` : ""}
        <label for="k">Admin key</label>
        <input id="k" type="password" autocomplete="current-password" enterkeyhint="go">
        <button class="btn" id="save">Open the list</button>
        <button class="btn plain" id="forgot">Forgot admin key?</button>
        <p class="hint">The admin key is not the gate key. "Forgot admin key?" sends the main
          admin key to the main admin's WhatsApp.</p>
        <p class="hint">Did another admin add you? Send KEY from your own WhatsApp to the app's
          number. The app replies with your own admin key. Type it here.</p></div>`;
    el("save").onclick = saveKey;
    el("forgot").onclick = () => void sendKey();
    el("k").onkeydown = e => { if (e.key === "Enter") saveKey(); };
    el("k").focus();
    return;
  }
  // The parts are built once, so typing in a search box never loses focus to a redraw.
  if (!el("list")) {
    main.innerHTML = `<div id="notice" role="status" aria-live="polite"></div><div id="alert"></div>${PANELS}`;
    bindPanels();
  }
  renderNotice();
  renderMenu();
  renderTabs();
  renderTiles();
  renderList();
  renderApprovers();
  renderTeam();
}

// Loads the first page again, or with more=true the page after the last one.
// The filter, the search, and where the next page starts.
function visitQuery(more) {
  const params = new URLSearchParams({status: filter});
  if (query) params.set("q", query);
  if (more && next) params.set("after", next);
  return params;
}

async function load(more = false) {
  const mine = ++asked;
  loading = true;
  if (!more) { rows = []; next = null; }
  if (el("list")) { renderTiles(); renderList(); }
  try {
    const page = await call(`/api/admin/visits?${visitQuery(more)}`);
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

// The server's timing rules, in one line above the approvers.
function renderRules(s) {
  if (!el("rules")) return;
  const auto = s.work_days
    ? ` A request made ${s.work_days.join(", ")}, ${s.work_hours[0]}:00 to ${s.work_hours[1]}:00,`
      + " with no answer, is approved automatically after the time in its row."
    : "";
  el("rules").textContent = `A request is sent again, to the backup or as a reminder, after ${s.escalate_minutes} minutes`
    + ` with no answer.${auto} A pass works for ${s.pass_hours} hours after the request.`
    + ` Records are deleted after ${s.retain_days} days.`;
}

async function loadSummary() {
  try {
    const s = await call("/api/admin/summary");
    counts = s.counts;
    approvers = s.approvers;
    autoDefault = s.auto_approve_minutes ?? autoDefault;
    for (const name of Object.keys(team)) if (name in s) team[name] = s[name];
    renderGaps(s.setup_gaps || []);
    renderRules(s);
  } catch (err) {
    if (err instanceof WrongKey) return forgetKey(err.message);
    notice = err.message;
  }
  if (key()) render();
}

function refresh() {
  info = "";
  void loadSummary();
  void load();
  void loadWaiting();
}

function saveKey() {
  const value = el("k").value.trim();
  if (!value) {
    notice = "Type the key first.";
    render();
    return;
  }
  setKey(value);
  seenWritten = 0;
  touch();
  notice = "";
  info = "";
  render();
  refresh();
}

// The two logs: the visits with their photos as a ZIP, and the staff entries as a CSV.
const LOGS = {visits: "/api/admin/export.zip", staff: "/api/admin/staff-entries.csv"};

// Saves each log in turn. A failed one says so, and the others still save.
async function downloadLogs(which = ["visits", "staff"]) {
  const saved = [];
  const failed = [];
  for (const log of which) {
    try {
      const r = await fetch(LOGS[log], {headers: {"X-Admin-Key": key()}});
      if (r.status === 403) return forgetKey("That admin key is not right. Type it again.");
      if (r.ok) saved.push(await saveFile(r));
      else failed.push(`Could not download (${r.status})`);
    } catch (err) {
      failed.push(err.message);
    }
  }
  notice = failed.join(" ");
  info = saved.length > 1
    ? `Saved ${saved.join(" and ")}. If the browser asks, allow this site to download more than one file.`
    : saved.length ? `Saved ${saved[0]}.` : "";
  renderNotice();
}

el("tabs").onclick = e => {
  const hit = e.target.closest("[data-section]");
  if (hit) goTo(hit.dataset.section);
};
el("menu").onclick = () => (el("side").classList.contains("open") ? closeMenu() : openMenu());
el("scrim").onclick = closeMenu;
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && el("side").classList.contains("open")) { closeMenu(); el("menu").focus(); }
});
el("refresh").onclick = () => { closeMenu(); refresh(); };
el("csv").onclick = () => void downloadLogs();
el("rekey").onclick = () => forgetKey();
window.addEventListener("hashchange", () => {
  const name = fromHash();
  if (name && name !== section) { section = name; renderTabs(); }
});
// Clicks and key presses count as use. Background reloads do not.
document.addEventListener("click", () => touch(), true);
document.addEventListener("keydown", () => touch(), true);
document.addEventListener("visibilitychange", () => { if (!document.hidden) idle(); });
window.addEventListener("focus", () => idle());
setInterval(idle, 60000);
// Sign out in one tab signs out the others.
window.addEventListener("storage", e => { if (e.key === "adminkey" && !e.newValue && el("list")) forgetKey(); });
buildMenu();
renderTabs();
render();
if (key() && !idle()) { touch(); refresh(); }
