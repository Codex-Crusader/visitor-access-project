const CALL_TIMEOUT = 75000;  // a sleeping free server can take ~50s to wake
const BOARD_EVERY = 30000;   // how often the lists refresh by themselves
const LONG_HOURS = 8;        // inside longer than this is marked on the board

const el = i => document.getElementById(i);
// These are in gate.html from the start, so they are looked up once.
// The gate key box is built by render(), so that one stays a lookup.
const out = el("out"), codeBox = el("code"), boardBox = el("board"), tools = el("tools");
// Built once. Inside the callback it was a new object for every escaped letter.
const ESC = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
const x = s => String(s).replace(/[&<>"']/g, c => ESC[c]);
const hm = t => t ? new Date(t).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"}) : "—";

// A pass code is VR-0000. WhatsApp already accepts the four digits on their
// own, so the gate page accepts them too and puts the VR- back.
const CODE = /^(?:VR[- ]?)?(\d{4})$/i;
const tidy = text => {
  const trimmed = text.trim();
  const found = CODE.exec(trimmed);
  return found ? `VR-${found[1]}` : trimmed.toUpperCase();
};

let visit = null;
let notice = "";
let busy = "";
// The last lists the server sent, when they came, and why the latest refresh
// failed, if it did. A failed refresh keeps the old lists on screen.
let board = null;
let boardAt = null;
let boardError = "";

function key() {
  try { return localStorage.getItem("gatekey") || ""; } catch { return ""; }
}

function setKey(value) {
  // A browser with storage blocked keeps the key for this page view only.
  try { localStorage.setItem("gatekey", value); } catch { /* nothing to undo */ }
}

function forgetKey() {
  try { localStorage.removeItem("gatekey"); } catch { /* it was never stored */ }
  visit = null;
  notice = "";
  board = null;
  boardAt = null;
  boardError = "";
  render();
}

const BANNER = {
  approved: ["good", "Let them in", "Pass is valid. Record the entry."],
  inside:   ["good", "Inside now", "Record the exit when they leave."],
  closed:   ["bad", "Pass closed", "This visit is over. The code no longer works."],
  declined: ["bad", "Declined", "Do not let them in."],
  pending:  ["wait", "Not approved yet", "Do not let them in."],
  escalated:["wait", "Not approved yet", "Do not let them in."],
};

const fact = (k, v) => `<div><span>${k}</span><b>${x(v || "—")}</b></div>`;
const problem = t => `<div class="state bad"><h2>Cannot do that</h2><p>${x(t)}</p></div>`;
const working = t => `<div class="state wait"><h2>${x(t)}</h2><p>This can take up to a minute if the server was asleep.</p></div>`;

// The try covers the network only. A server that answers and refuses is not a
// failure of the call, so those two refusals are raised after the try ends.
async function call(url, options) {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), CALL_TIMEOUT);
  let r, data;
  try {
    r = await fetch(url, {...options, headers: {"X-Gate-Key": key()}, signal: stop.signal});
    data = await r.json().catch(() => ({}));
  } catch (err) {
    throw err.name === "AbortError"
      ? new Error("The server did not answer. Check your connection and try again.")
      : err;
  } finally {
    clearTimeout(timer);
  }
  if (r.status === 403) throw new Error("That gate key is not right. Check it and save it again.");
  if (!r.ok) throw new Error(data.error || `Something went wrong (${r.status})`);
  return data;
}

// "2 h 10 min" since a time, for how long someone has been inside.
function since(t, now) {
  const minutes = Math.max(0, Math.floor((now - new Date(t).getTime()) / 60000));
  const h = Math.floor(minutes / 60), m = minutes % 60;
  return h ? `${h} h ${m} min` : `${m} min`;
}

const plus = v => v.guests && v.guests.length ? ` +${v.guests.length}` : "";

function row(v, side, long) {
  return `<button class="row${long ? " long" : ""}" data-ref="${x(v.reference)}">
      <span><b>${x(v.name)}${plus(v)}</b><small>Visiting ${x(v.visiting)}</small></span>
      <span class="side"><code>${x(v.reference)}</code><small>${side}</small></span></button>`;
}

function section(title, list, empty, line) {
  return `<h2 class="sec">${title}<span class="count">${list.length}</span></h2>
    <div class="list">${list.length ? list.map(line).join("") : `<div class="empty">${empty}</div>`}</div>`;
}

function renderBoard() {
  if (!board) {
    boardBox.innerHTML = boardError ? problem(`Could not load the lists. ${boardError}`) : "";
    return;
  }
  const now = Date.now();
  // Inside comes first. At the end of the day it is the list that matters:
  // everyone on it has still to be let out.
  boardBox.innerHTML =
    section("Inside now", board.inside, "Nobody is inside.", v => {
      const long = now - new Date(v.entered_at).getTime() > LONG_HOURS * 3600000;
      return row(v, `In for ${since(v.entered_at, now)}`, long);
    }) +
    section("Expected", board.expected, "Nobody approved is on the way.",
      v => row(v, `Approved ${hm(v.decided_at)}`, false)) +
    `<p class="updated">${boardError
      ? `Could not refresh. These lists are from ${hm(boardAt)}. ${x(boardError)}`
      : `Updated ${hm(boardAt)}. Tap a name to open the pass.`}</p>`;
}

function render() {
  // The key comes first. Without it nothing else can work, so nothing else shows.
  const haveKey = !!key();
  el("entry").hidden = !haveKey;
  boardBox.hidden = !haveKey;
  tools.hidden = !haveKey;
  el("sub").textContent = haveKey
    ? "Type the code on the visitor's pass, or tap a name below."
    : "First, type the gate key your admin gave you.";

  if (!haveKey) {
    out.innerHTML = `
      ${notice ? problem(notice) : ""}
      <label for="k">Gate key</label>
      <input id="k" type="password" style="text-transform:none;letter-spacing:normal;font-size:1rem"
             enterkeyhint="go">
      <button class="btn" onclick="saveKey()">Save key</button>`;
    const box = el("k");
    box.onkeydown = e => { if (e.key === "Enter") saveKey(); };
    box.focus();
    return;
  }

  renderBoard();

  if (busy) {
    out.innerHTML = working(busy);
    return;
  }

  if (!visit) {
    out.innerHTML = notice ? problem(notice) : "";
    return;
  }

  const [tone, title, line] = BANNER[visit.status] || ["wait", visit.status, ""];
  const buttons =
    visit.status === "approved" ? `<button class="btn go" onclick="act('entry')">Record entry</button>` :
    visit.status === "inside"   ? `<button class="btn" onclick="act('exit')">Record exit</button>` : "";

  // Once the visit is over the server sends times and nothing else, so the
  // desk stops showing the visitor's name, phone number and address.
  const closed = visit.status === "closed";
  const details = closed ? "" : `
      ${fact("Name", visit.name)}
      ${fact("Phone", visit.phone)}
      ${fact("Visiting", visit.visiting)}
      ${fact("Reason", visit.reason)}
      ${visit.guests && visit.guests.length ? fact("With", visit.guests.join(", ")) : ""}
      ${fact("Approved", hm(visit.decided_at))}`;

  out.innerHTML = `
    ${notice ? problem(notice) : ""}
    <div class="state ${tone}"><h2>${x(title)}</h2><p>${x(line)}</p></div>
    <div class="facts">
      ${fact("Code", visit.reference)}
      ${details}
      ${visit.entered_at ? fact("Entered", hm(visit.entered_at)) : ""}
      ${visit.exited_at ? fact("Exited", hm(visit.exited_at)) : ""}
    </div>
    ${buttons}
    <button class="btn plain" onclick="clear_()">Next visitor</button>`;
}

// Refreshes the two lists. It never touches the pass on screen, so a guard in
// the middle of an entry is not interrupted.
async function loadBoard() {
  if (!key()) return;
  try {
    board = await call("/api/gate/board");
    boardAt = new Date().toISOString();
    boardError = "";
  } catch (err) {
    boardError = err.message;
  }
  if (!busy) renderBoard();
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
  codeBox.focus();
  void loadBoard();
}

async function look() {
  const code = tidy(codeBox.value);
  if (!code) {
    notice = "Type a pass code first.";
    render();
    return;
  }
  visit = null;
  notice = "";
  busy = "Checking the pass";
  render();
  try {
    visit = await call(`/api/pass/${encodeURIComponent(code)}`);
  } catch (err) {
    notice = err.message;
  }
  busy = "";
  render();
}

// A tap on a name in either list opens that pass, the same as typing its code.
function openPass(reference) {
  codeBox.value = reference;
  window.scrollTo(0, 0);
  void look();
}

async function act(action) {
  notice = "";
  busy = action === "entry" ? "Recording the entry" : "Recording the exit";
  render();
  try {
    visit = await call(`/api/pass/${encodeURIComponent(visit.reference)}/${action}`, {method: "POST"});
  } catch (err) {
    notice = err.message;
    // The refusal above is what the guard needs. A failed re-read adds nothing.
    try { visit = await call(`/api/pass/${encodeURIComponent(visit.reference)}`); } catch { /* keep the refusal */ }
  }
  busy = "";
  render();
  // The visitor just moved from one list to the other, or off the board.
  void loadBoard();
}

async function downloadLog() {
  notice = "";
  busy = "Preparing the log";
  render();
  try {
    const r = await fetch("/api/export.csv", {headers: {"X-Gate-Key": key()}});
    if (r.status === 403) notice = "That gate key is not right.";
    else if (!r.ok) notice = `Could not download (${r.status})`;
    else {
      const blob = await r.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "visits.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    }
  } catch (err) {
    notice = err.message;
  }
  busy = "";
  render();
}

function clear_() {
  visit = null;
  notice = "";
  codeBox.value = "";
  render();
  codeBox.focus();
}

el("look").onclick = look;
codeBox.onkeydown = e => { if (e.key === "Enter") void look(); };
boardBox.onclick = e => {
  const hit = e.target.closest("[data-ref]");
  if (hit) openPass(hit.dataset.ref);
};
el("refresh").onclick = () => void loadBoard();
el("log").onclick = () => void downloadLog();
el("rekey").onclick = forgetKey;
// A hidden tab does not need fresh lists. It catches up when shown again.
setInterval(() => { if (!document.hidden) void loadBoard(); }, BOARD_EVERY);
document.addEventListener("visibilitychange", () => { if (!document.hidden) void loadBoard(); });
render();
void loadBoard();
