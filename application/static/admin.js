/* global saveFile, askForKey */  // from shared.js, which admin.html loads first
const CALL_TIMEOUT = 75000;  // a sleeping free server can take ~50s to wake
const SEARCH_WAIT = 300;     // ms after the last key press before a search runs

const el = i => document.getElementById(i);
const main = el("main");
const ESC = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
const x = s => String(s ?? "").replace(/[&<>"']/g, c => ESC[c]);
// One formatter each, made once: making one for every row is the slow part of a long list.
const WHEN_FORMAT = new Intl.DateTimeFormat([], {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"});
const DAY_FORMAT = new Intl.DateTimeFormat([], {day: "numeric", month: "short", year: "numeric"});
const when = t => t ? WHEN_FORMAT.format(new Date(t)) : "—";
const day = t => DAY_FORMAT.format(new Date(t));

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
// The approvers and the offices share a tab. The allow list and the blacklist sit together.
const TABS = [
  ["visits", "Visits"], ["numbers", "Approvers"], ["staff", "Allow list"],
  ["blacklist", "Blacklist"], ["guards", "Guards"], ["admins", "Admins"],
];

// The lists with an add form and a Delete button. Each form field is [name, label, type].
const PHONE = ["phone", "WhatsApp number", "tel"];
const TAG = ["tag", "Tag (you may leave it empty)", "text"];
const FORMS = {
  staff: {prefix: "s", url: "/api/admin/staff", button: "Add to the allow list and make a code",
          fields: [["name", "Name", "text"], PHONE, TAG]},
  offices: {prefix: "o", url: "/api/admin/offices", button: "Add office",
            fields: [["name", "Office name", "text"], ["main", "Approver", "tel"],
                     ["backup", "Backup approver (you may leave it empty)", "tel"], TAG]},
  guards: {prefix: "g", url: "/api/admin/guards", button: "Add guard and make a key",
           fields: [["name", "Name", "text"], PHONE]},
  admins: {prefix: "a", url: "/api/admin/admins", button: "Add admin and make a key",
           fields: [["name", "Name", "text"], PHONE]},
  blacklist: {prefix: "b", url: "/api/admin/blacklist", button: "Add to the blacklist", tone: "stop",
              fields: [["name", "Name", "text"], ["phone", "Phone number", "tel"],
                       ["reason", "Reason (you may leave it empty)", "text"]]},
};
// The fields a form needs. A backup approver and a ban's reason may stay empty.
const MISSING = {name: "Type the name.", phone: "Type the phone number.",
                 main: "Type the approver's number."};
// One person as approver and backup: the table says so, rather than the number twice.
const backupCell = row => row.backup === row.main ? `<span class="fixed">Same as approver</span>` : x(row.backup);

let section = "visits"; // the open tab
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
// What the server's lists hold. Every change answers with all of them.
const EMPTY_TEAM = {gate_desk: "", guards: [], main_admin: "", admins: [], you: "",
                    offices: [], staff: [], staff_entries: [], blacklist: [], blocked: [],
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

function forgetKey(why = "") {
  try { localStorage.removeItem("adminkey"); } catch { /* it was never stored */ }
  rows = []; next = null; counts = {}; approvers = []; notes = {}; notice = why; info = "";
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

// Asks before a delete, a ban or a bulk decision. Resolves true only for the first button.
function confirmDelete(line, yes = "Delete", tone = "stop") {
  return new Promise(done => {
    el("over").innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sure">
      <div class="box"><h2 id="sure">Are you sure?</h2><p>${x(line)}</p>
        <button class="btn ${tone}" id="sure-yes">${x(yes)}</button>
        <button class="btn plain" id="sure-no">Cancel</button></div></div>`;
    const sheet = el("over").firstElementChild;
    const close = answer => { el("over").innerHTML = ""; done(answer); };
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

function item(v) {
  const [main1, backup] = v.approvers || [];
  const [tone, word] = STATUS[v.status] || ["", v.status];
  const [byTone, byLine] = decision(v);
  const body = `<details><summary>
      <span><b>${x(v.name)}${plus(v)}</b><small>${x(v.phone)}</small>
        ${byLine ? `<small class="by" data-tone="${byTone}">${x(byLine)}</small>` : ""}</span>
      <span class="mid"><b>${x(v.reason)}</b><small>Visiting ${x(v.visiting)}</small></span>
      <span class="side"><code>${x(v.reference)}</code><br>
        <span class="pill" data-tone="${tone}">${x(word)}</span></span>
    </summary>
    <div class="more"><dl>
      <dt>Address</dt><dd>${x(v.address)}</dd>
      <dt>Reason</dt><dd>${x(v.reason)}</dd>
      ${v.office ? `<dt>Office</dt><dd>${x(v.office)}</dd>` : `<dt>Visiting</dt><dd>${x(v.visiting)}</dd>`}
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
    </dl>
    <button class="small del ban" data-ban="${x(v.phone)}" data-name="${x(v.name)}">Blacklist this number</button>
    </div></details>`;
  if (!pickable(v)) return body;
  return `<div class="pickrow"><label class="tick"><input type="checkbox" data-pick-ref="${x(v.reference)}"
      ${picked.has(v.reference) ? "checked" : ""} aria-label="Select ${x(v.name)} ${x(v.reference)}"></label>${body}</div>`;
}

// The gate page's photo loads only when the admin asks, then stays for this page view.
const photos = {};
function photoLine(v) {
  if (photos[v.reference]) {
    return `<span class="shot"><img src="${x(photos[v.reference])}" alt="The visitor at the gate"></span>`;
  }
  if (v.photo_stored) {
    return ` <button class="small edit" data-photo="${x(v.reference)}">View photo</button><span class="shot"></span>`;
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
// The waiting requests chosen on screen, by reference. The list pages 50 at a time.
const picked = new Set();
let bulkNote = null;
const pickable = v => team.super && (v.status === "pending" || v.status === "escalated");

function renderBulk() {
  const open = rows.filter(pickable);
  // A row that left the screen, or stopped waiting, leaves the selection too.
  for (const reference of [...picked]) {
    if (!open.some(v => v.reference === reference)) picked.delete(reference);
  }
  el("bulk").hidden = !open.length;
  const all = open.length && picked.size === open.length;
  el("pick-all").textContent = all ? "Clear the selection" : `Select all ${open.length} waiting on screen`;
  el("picked-count").textContent = `${picked.size} selected`;
  el("bulk-yes").textContent = picked.size ? `Approve ${picked.size}` : "Approve";
  el("bulk-no").textContent = picked.size ? `Decline ${picked.size}` : "Decline";
  el("bulk-yes").disabled = el("bulk-no").disabled = !picked.size;
  el("bulk-note").innerHTML = bulkNote ? `<div class="note ${bulkNote.tone}">${bulkNote.html}</div>` : "";
}

function pickAll() {
  const open = rows.filter(pickable);
  if (picked.size === open.length) picked.clear();
  else for (const v of open) picked.add(v.reference);
  renderList();
}

async function bulkDecide(decision) {
  const references = [...picked];
  const n = references.length;
  const what = `${n} ${n === 1 ? "request" : "requests"}`;
  const line = decision === "approve"
    ? `Approve ${what}? Each guard gets one WhatsApp message with the list.`
    : `Decline ${what}? The visitors see Declined.`;
  const verb = decision === "approve" ? "Approve" : "Decline";
  if (!(await confirmDelete(line, `${verb} ${n}`, decision === "approve" ? "go" : "stop"))) return;
  try {
    const answer = await call("/api/admin/decide", {references, decision});
    picked.clear();
    const skipped = answer.skipped.map(s => `${x(s.reference)}: ${x(s.why)}`).join("<br>");
    bulkNote = {tone: answer.skipped.length ? "bad" : "good",
      html: `${decision === "approve" ? "Approved" : "Declined"} ${answer.decided.length}.`
        + (skipped ? ` Not changed:<br>${skipped}` : "")};
    refresh();
  } catch (err) {
    if (err instanceof WrongKey) return forgetKey(err.message);
    bulkNote = {tone: "bad", html: x(err.message)};
    renderBulk();
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
  renderBulk();
}

function approverRow(a) {
  if (a.reason !== editing) {
    return `<tr><td>${x(a.reason)}</td><td>${x(a.main)}</td><td>${backupCell(a)}</td>
      <td class="acts"><button class="small edit" data-edit="${x(a.reason)}">Change</button></td></tr>`;
  }
  const field = (name, label, value) => `<div>
      <label for="ap-${name}">${label}</label>
      <input id="ap-${name}" type="tel" inputmode="tel" autocomplete="off" value="${x(value)}"
        placeholder="+919876543210">
      ${fieldErrors[name] ? `<p class="err">${x(fieldErrors[name])}</p>` : ""}</div>`;
  // The approver as their own backup shows an empty backup box.
  const typed = draft || {...a, backup: a.backup === a.main ? "" : a.backup};
  return `<tr><td colspan="4"><b>${x(a.reason)}</b>
      <div class="pair">${field("main", "Approver", typed.main)}${field("backup", "Backup approver (you may leave it empty)", typed.backup)}</div>
      <div class="pair" style="margin-top:12px">
        <button class="btn" id="ap-save">Save</button>
        <button class="btn plain" id="ap-cancel">Cancel</button></div></td></tr>`;
}

function renderApprovers() {
  el("approvers").innerHTML = `<table><thead><tr><th>Reason</th><th>Approver</th><th>Backup</th><th></th></tr></thead>
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
  draft = {main: main1, backup};
  fieldErrors = {};
  if (!main1) fieldErrors.main = "Type the approver's number.";
  if (fieldErrors.main) return renderApprovers();
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

// ------------------------------------------- staff, offices, guards and admins
const del = (data, label) => `<button class="small del" ${data} data-label="${x(label)}">Delete</button>`;
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
  const rows = team[kind].filter(row => shows(kind, row))
    .sort((a, b) => (a.tag === "") - (b.tag === "") || byText(a.tag, b.tag) || byText(a.name, b.name));
  if (!team[kind].length) return `<tr><td colspan="${columns}" class="fixed">${empty}</td></tr>`;
  if (!rows.length) return `<tr><td colspan="${columns}" class="fixed">Nothing matches the tag or the search.</td></tr>`;
  const shown = rows.slice(0, views[kind].limit);
  const rest = rows.length - shown.length;
  const more = rest ? `<tr class="more-row"><td colspan="${columns}"><button class="small edit" data-more="${kind}">
      Show ${Math.min(PAGE, rest)} more, of ${rest} not shown</button></td></tr>` : "";
  if (views[kind].tag !== null) return shown.map(line).join("") + more;
  // One pass for every tag's count: O(n), not O(n) again for each tag. The count is of every
  // matching row, also the rows not shown yet.
  const counts = countTags(rows);
  let out = "";
  shown.forEach((row, i) => {
    if (i === 0 || row.tag !== shown[i - 1].tag) {
      out += `<tr class="group"><td colspan="${columns}">${x(row.tag || "No tag")} <span>${counts.get(row.tag)}</span></td></tr>`;
    }
    out += line(row);
  });
  return out + more;
}

function countTags(rows) {
  const counts = new Map();
  for (const row of rows) counts.set(row.tag, (counts.get(row.tag) || 0) + 1);
  return counts;
}

const tagButton = (kind, row, label) =>
  `<button class="small edit" data-retag="${kind}" data-id="${x(row[KEY_OF[kind]])}" data-tag="${x(row.tag)}"
    data-label="${x(label)}">Tag</button>`;
const tagCell = row => row.tag ? x(row.tag) : `<span class="fixed">No tag</span>`;

// The tag filter: All, each tag with its count, No tag. A chosen tag can be renamed.
function renderTagBar(kind) {
  const {prefix} = FORMS[kind];
  const chosen = views[kind].tag;
  const counts = countTags(team[kind]);
  const count = tag => counts.get(tag) || 0;
  const chip = (tag, label, n) => `<button ${tag === null ? "data-all" : `data-filter-tag="${x(tag)}"`}
    aria-pressed="${chosen === tag}">${x(label)} <span>${n}</span></button>`;
  el(`${prefix}-chips`).innerHTML = (team[kind].length ? chip(null, "All", team[kind].length)
    + tagsOf(kind).map(tag => chip(tag, tag, count(tag))).join("")
    + (count("") ? chip("", "No tag", count("")) : "") : "")
    + (chosen ? `<button class="small edit" data-rename>Rename this tag</button>` : "");
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
    const close = answer => { el("over").innerHTML = ""; done(answer); };
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

function onTagBar(kind, e) {
  const hit = e.target.closest("button");
  if (!hit) return;
  if (hit.hasAttribute("data-rename")) return void renameTag(kind);
  views[kind].tag = hit.hasAttribute("data-all") ? null : hit.dataset.filterTag;
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
    tagged("staff", "No one is on the allow list yet.", 6, p => `<tr><td>${x(p.name)}</td><td>${x(p.phone)}</td>
        <td><code>${x(p.code)}</code></td><td>${tagCell(p)}</td><td>${day(p.added_at)}</td>
        <td class="acts">${tagButton("staff", p, p.name)}
          ${del(`data-delete="staff" data-id="${x(p.code)}"`, `${p.name} ${p.code}`)}</td></tr>`)),
  offices: () => table(["Office", "Approver", "Backup", "Tag", ""],
    tagged("offices", "No offices yet. Visitors type the office's name.", 5, o => `<tr><td>${x(o.name)}</td>
        <td>${x(o.main)}</td><td>${backupCell(o)}</td><td>${tagCell(o)}</td>
        <td class="acts">${tagButton("offices", o, o.name)}
          ${del(`data-delete="offices" data-id="${x(o.name)}"`, o.name)}</td></tr>`)),
  blacklist: () => table(["Name", "Phone number", "Reason", "Added", ""], team.blacklist.length
    ? team.blacklist.map(b => `<tr><td>${x(b.name)}</td><td>${x(b.phone)}</td><td>${x(b.reason || "—")}</td>
        <td>${day(b.added_at)}</td>
        <td class="acts">${del(`data-delete="blacklist" data-id="${x(b.phone)}"`, `${b.name} ${b.phone}`)}</td></tr>`).join("")
    : `<tr><td colspan="5" class="fixed">No number is on the blacklist.</td></tr>`),
  guards: () => table(["Name", "WhatsApp number", "Added", ""],
    `<tr><td>Gate desk</td><td>${x(team.gate_desk)}</td>
       <td colspan="2" class="fixed">Set as GUARD on the server. Uses the shared gate key.</td></tr>`
    + team.guards.map(g => `<tr><td>${x(g.name)}</td><td>${x(g.phone)}</td><td>${day(g.added_at)}</td>
        <td class="acts">${newKey("guards", g.phone)}
          ${del(`data-delete="guards" data-id="${x(g.phone)}"`, `${g.name} ${g.phone}`)}</td></tr>`).join("")),
  admins: () => table(["Name", "WhatsApp number", "Added", ""],
    `<tr><td>Main admin${you("Main admin (ADMIN_KEY)")}${SUPER}</td><td>${x(team.main_admin)}</td>
       <td colspan="2" class="fixed">Set as ADMIN_PHONE on the server. Uses ADMIN_KEY.</td></tr>`
    + team.admins.map(a => `<tr><td>${x(a.name)}${you(`${a.name} ${a.phone}`)}${a.super ? SUPER : ""}</td>
        <td>${x(a.phone)}</td><td>${day(a.added_at)}</td><td class="acts">${adminActions(a)}</td></tr>`).join("")),
};

const SUPER = ` <span class="you super">Super admin</span>`;

// Only a super admin may act on a super admin: a new key would let anyone take their place.
function adminActions(a) {
  const label = `${a.name} ${a.phone}`;
  if (a.super && !team.super) return `<span class="fixed">Only a super admin can change this.</span>`;
  const role = team.super && label !== team.you
    ? `<button class="small ${a.super ? "del" : "go"}" data-super="${x(a.phone)}" data-on="${!a.super}" data-label="${x(label)}">
        ${a.super ? "Remove super admin" : "Make super admin"}</button>` : "";
  return `${role} ${newKey("admins", a.phone)} ${del(`data-delete="admins" data-id="${x(a.phone)}"`, label)}`;
}

async function setSuper(phone, on, label) {
  const line = on
    ? `Make ${label} a super admin? A super admin can approve and decline many requests at once, and change other super admins.`
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

function renderEntries() {
  el("s-entries").innerHTML = table(["When", "Name", "Code", "Recorded by"], team.staff_entries.length
    ? team.staff_entries.map(e => `<tr><td>${when(e.entered_at)}</td><td>${x(e.name)}</td>
        <td><code>${x(e.code)}</code></td><td>${x(e.entered_by)}</td></tr>`).join("")
    : `<tr><td colspan="4" class="fixed">No entries yet.</td></tr>`);
  labelCells(el("s-entries"));
}

const DAY = 86400000;
const recent = () => team.blocked.filter(a => Date.now() - Date.parse(a.at) < DAY).length;

// Each time the blacklist stopped someone. The alert shows on every tab for a day.
function renderBlocked() {
  el("b-attempts").innerHTML = table(["When", "Name", "Phone number", "What happened", "Where"],
    team.blocked.length
      ? team.blocked.map(a => `<tr><td>${when(a.at)}</td><td>${x(a.name)}</td><td>${x(a.phone)}</td>
          <td>${x(a.what)}${a.detail ? ` <code>${x(a.detail)}</code>` : ""}</td><td>${x(a.by_whom)}</td></tr>`).join("")
      : `<tr><td colspan="5" class="fixed">The blacklist has stopped no one yet.</td></tr>`);
  labelCells(el("b-attempts"));
  const count = recent();
  el("alert").innerHTML = count
    ? `<div class="note bad alert"><span>The blacklist stopped ${count === 1 ? "one attempt" : `${count} attempts`}
        in the last 24 hours.</span><button class="small" data-section="blacklist">See who</button></div>`
    : "";
  el("tabs").querySelector('[data-section="blacklist"]').innerHTML =
    `Blacklist${count ? ` <span class="count">${count}</span>` : ""}`;
}

function renderTeam() {
  for (const kind of Object.keys(views)) renderTagged(kind);
  for (const [kind, form] of Object.entries(FORMS)) {
    if (!(kind in views)) {
      el(`${form.prefix}-table`).innerHTML = TABLES[kind]();
      labelCells(el(`${form.prefix}-table`));
    }
    const note = notes[kind];
    el(`${form.prefix}-note`).innerHTML = note ? `<div class="note ${note.tone}">${note.html}</div>` : "";
    for (const [name] of form.fields) {
      el(`${form.prefix}-${name}-err`).textContent = formErrors[kind][name] || "";
    }
  }
  renderEntries();
  renderBlocked();
  el("a-changes").innerHTML = table(["When", "Who", "What", "Details"], team.changes.length
    ? team.changes.map(c => `<tr><td>${when(c.at)}</td><td>${x(c.by_whom)}</td><td>${x(c.action)}</td>
        <td>${x(c.detail || "—")}</td></tr>`).join("")
    : `<tr><td colspan="4" class="fixed">No changes yet.</td></tr>`);
  labelCells(el("a-changes"));
  el("you").textContent = team.you ? `Signed in as ${team.you}${team.super ? " (super admin)" : ""}` : "";
  if (el("list")) renderBulk();
}

const LAYOUT = {2: "pair", 3: "trio", 4: "quad"};

function form(kind) {
  const {prefix, fields, button} = FORMS[kind];
  return `<div class="${LAYOUT[fields.length]}">${fields.map(([name, label, type]) => `<div>
      <label for="${prefix}-${name}">${label}</label>
      <input id="${prefix}-${name}" type="${type}" ${type === "tel" ? `inputmode="tel" placeholder="+919876543210"`
        : `maxlength="${name === "tag" ? 40 : 60}"`}
        autocomplete="off"><p class="err" id="${prefix}-${name}-err"></p>
      ${name === "tag" ? `<div class="tagpick" id="${prefix}-tagpick"></div>` : ""}</div>`).join("")}</div>
    <button class="btn${FORMS[kind].tone ? ` ${FORMS[kind].tone}` : ""}" id="${prefix}-add">${button}</button>`;
}

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
  section = "blacklist";
  renderTabs();
  window.scrollTo(0, 0);
}

function onTableClick(e) {
  const hit = e.target.closest("button");
  if (!hit) return;
  const d = hit.dataset;
  if (d.delete) void remove(d.delete, d.id, d.label);
  else if (d.newkey) void renewKey(d.newkey, d.id);
  else if (d.retag) void retag(d.retag, d.id, d.tag, d.label);
  else if (d.more) { views[d.more].limit += PAGE; renderTagged(d.more); }
  else if (d.super) void setSuper(d.super, d.on === "true", d.label);
}

// ------------------------------------------------------------------- the page
function renderTabs() {
  for (const tab of el("tabs").children) {
    const open = tab.dataset.section === section;
    tab.setAttribute("aria-selected", open ? "true" : "false");
    el(tab.dataset.section).hidden = !open;
  }
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
  <section id="visits" role="tabpanel">
  <div class="tiles" id="tiles"></div>
  <div class="bar"><input id="q" type="search" placeholder="Search name, phone, code or person visited"
    aria-label="Search" autocomplete="off" spellcheck="false"></div>
  <p class="found" id="found"></p>
  <div id="bulk-note"></div>
  <div class="bulk" id="bulk" hidden>
    <button class="small edit" id="pick-all"></button><span id="picked-count"></span>
    <button class="btn go" id="bulk-yes" disabled>Approve</button>
    <button class="btn stop" id="bulk-no" disabled>Decline</button>
  </div>
  <div class="list" id="list"></div>
  <button class="btn plain" id="more" hidden>Show more</button>
  </section>
  <section id="staff" role="tabpanel" hidden>
  <h2>The allow list: staff and faculty who enter without a request</h2>
  <div id="s-note"></div>
  ${listBar("staff", "allow list")}
  <div class="wrap" id="s-table"></div>
  <h2 class="gap">Add to the allow list</h2>
  ${form("staff")}
  <p class="hint">Each person on the allow list gets a 7-digit code. At the gate, they say it to the
    guard. The guard sends the code to the app's WhatsApp number, or types it on the gate page, and
    the entry is recorded at once. The person then gets a WhatsApp message about the entry, so a
    code used by someone else is noticed. The guard's reply names the person, so the guard can
    check the face. A number on the blacklist cannot be on the allow list.</p>
  <p class="hint">A tag, such as a department, puts people into groups. Tap a tag in use, or type a
    new one. Tag on a row moves that person to another tag, and their code stays the same. Tap a
    tag above the list to see only that tag, and Rename this tag to rename it for everyone.</p>
  <h2 class="gap">Recent entries</h2>
  <div class="wrap" id="s-entries"></div>
  <p class="hint">The last 100 entries. Download staff entries saves all of them as a CSV file, with
    the date in its own column, so a spreadsheet filter shows one day. Download log at the top saves
    this file and the visit log together.</p>
  <button id="s-download" class="small edit">Download staff entries</button>
  </section>
  <section id="numbers" role="tabpanel" hidden>
  <h2>Who approves each reason</h2>
  <div id="approver-note"></div>
  <div class="wrap" id="approvers"></div>
  <p class="hint">Each reason needs an approver's number, with + and the country code. A
    backup is a second person who gets the request when nobody answers in time. With no
    backup, the approver gets a reminder instead.
    A change works at once: the old numbers can no longer decide that reason's requests,
    including requests already sent to them. See an office is not in this table: each office
    below has its own approvers. A request with no office goes to the numbers for Other.
    While the app uses Meta's test number, also add each new number to the recipient list in
    Meta's API Setup page.</p>
  <p class="hint" id="rules"></p>
  <h2 class="gap" id="offices">Offices a visitor can pick</h2>
  <div id="o-note"></div>
  ${listBar("offices", "offices")}
  <div class="wrap" id="o-table"></div>
  <h2 class="gap">Add an office</h2>
  ${form("offices")}
  <p class="hint">A visitor who picks See an office then picks one of these offices. The request
    goes to that office's approver, and to its backup if nobody answers. With no offices here, the
    visitor types the office's name, and the request goes to the approvers for Other above.</p>
  <p class="hint">A tag, such as a building, puts offices into groups, here and in the visitor's
    list. Tap a tag in use, or type a new one. Tag on a row moves that office to another tag. Tap a
    tag above the list to see only that tag, and Rename this tag to rename it for every office.</p>
  </section>
  <section id="guards" role="tabpanel" hidden>
  <h2>Who can record entry and exit</h2>
  <div id="g-note"></div>
  <div class="wrap" id="g-table"></div>
  <h2 class="gap">Add a guard</h2>
  ${form("guards")}
  <p class="hint">Each guard gets a gate key of their own, so the log names who let each visitor
    in and out. A guard can also use IN and OUT from their WhatsApp number, and gets a message when
    a request is approved. WhatsApp delivers that message only if the guard wrote to the app's
    number in the last 24 hours. A guard who loses their key sends KEY from their phone to the
    app's WhatsApp number, or you tap New key. Delete stops the key and the WhatsApp commands at once.
    While the app uses Meta's test number, also add each guard's number to the recipient list
    in Meta's API Setup page.</p>
  </section>
  <section id="admins" role="tabpanel" hidden>
  <h2>Who can open this page</h2>
  <div id="a-note"></div>
  <div class="wrap" id="a-table"></div>
  <h2 class="gap">Add an admin</h2>
  ${form("admins")}
  <p class="hint">Each admin gets an admin key of their own and sees everything on this page. An admin
    who loses their key sends KEY from their phone to the app's WhatsApp number, or another admin
    taps New key. A guard's number cannot be an admin, and an admin's number cannot be a guard.
    Nobody can delete themselves.</p>
  <p class="hint">A super admin can also approve and decline many waiting requests at once on the
    Visits tab. The main admin is always a super admin, and a super admin can make another admin
    one. Only a super admin can make a new key for, delete, or change a super admin.</p>
  <h2 class="gap">Recent changes</h2>
  <div class="wrap" id="a-changes"></div>
  <p class="hint">Who added or deleted a guard, admin, office, allow list or blacklist entry,
    changed approvers, or made a new key, also by KEY on WhatsApp. Keys never show here. The last
    100 show here, and Download log saves all of them. A change you did not expect can mean a lost
    phone or key: make a new key for that person, or delete them.</p>
  </section>
  <section id="blacklist" role="tabpanel" hidden>
  <h2>Numbers that may not visit</h2>
  <div id="b-note"></div>
  <div class="wrap" id="b-table"></div>
  <h2 class="gap">Add to the blacklist</h2>
  ${form("blacklist")}
  <p class="hint">A number on the blacklist cannot send a request: the visitor page says only that
    the number cannot request a visit. The gate refuses an entry for a pass with that number, also
    a pass approved before, on the gate page and on WhatsApp, and allow list codes for that number
    stop. The app matches the last 10 digits, so 98765 43210 and +919876543210 are one number.
    Each visit's details also have a "Blacklist this number" button. The blacklist cannot stop a
    person who uses another phone, or who comes as a guest on someone else's request.</p>
  <h2 class="gap">Blocked attempts</h2>
  <div class="wrap" id="b-attempts"></div>
  <p class="hint">Each time the blacklist stopped someone: a request on the visitor page, a pass
    checked at the gate with its entry code, or an allow list code. Where names the guard. The last
    100 show here, and Download log saves all of them. Tap Refresh to see new ones.</p>
  </section>`;

function render() {
  const haveKey = !!key();
  el("nav").hidden = !haveKey;
  if (!haveKey) {
    el("you").textContent = "";
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
  // The search box is built once, so typing never loses focus to a redraw.
  if (!el("list")) {
    main.innerHTML = `
      <div id="notice"></div>
      <div id="alert"></div>
      <div id="gaps"></div>
      <div class="tabs" id="tabs" role="tablist">${TABS.map(([name, label]) =>
        `<button role="tab" data-section="${name}" aria-controls="${name}">${label}</button>`).join("")}</div>
      ${PANELS}`;
    el("tabs").onclick = e => {
      const hit = e.target.closest("[data-section]");
      if (hit) { section = hit.dataset.section; renderTabs(); }
    };
    el("alert").onclick = e => {
      if (!e.target.closest("[data-section]")) return;
      section = "blacklist";
      renderTabs();
      el("b-attempts").scrollIntoView({block: "start"});
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
      const photo = e.target.closest("[data-photo]");
      if (photo) void showPhoto(photo);
      const banned = e.target.closest("[data-ban]");
      if (banned) void ban(banned);
    };
    el("list").onchange = e => {
      const box = e.target.closest("[data-pick-ref]");
      if (!box) return;
      if (box.checked) picked.add(box.dataset.pickRef);
      else picked.delete(box.dataset.pickRef);
      bulkNote = null;
      renderBulk();
    };
    el("pick-all").onclick = pickAll;
    el("s-download").onclick = () => void downloadLogs(["staff"]);
    el("bulk-yes").onclick = () => void bulkDecide("approve");
    el("bulk-no").onclick = () => void bulkDecide("decline");
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
  renderNotice();
  renderTabs();
  renderTiles();
  renderList();
  renderApprovers();
  renderTeam();
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
    for (const name of Object.keys(team)) if (name in s) team[name] = s[name];
    renderGaps(s.setup_gaps || []);
    if (el("rules")) {
      const auto = s.auto_approve_minutes
        ? ` A request made ${s.work_days.join(", ")}, ${s.work_hours[0]}:00 to ${s.work_hours[1]}:00,`
          + ` is approved automatically after ${s.auto_approve_minutes} minutes with no answer.`
        : "";
      el("rules").textContent = `A request is sent again, to the backup or as a reminder, after ${s.escalate_minutes} minutes`
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
  info = "";
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

el("refresh").onclick = refresh;
el("csv").onclick = () => void downloadLogs();
el("rekey").onclick = () => forgetKey();
render();
if (key()) refresh();
