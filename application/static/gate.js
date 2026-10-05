/* global saveFile, askForKey */  // from shared.js, which gate.html loads first
const CALL_TIMEOUT = 75000;  // a sleeping free server can take ~50s to wake
const BOARD_EVERY = 30000;   // how often the lists refresh by themselves
const LONG_HOURS = 8;        // inside longer than this is marked on the board
const PHOTO_SIDE = 640;      // the photo's long side in pixels, about 30-40 KB as JPEG
const PHOTO_QUALITY = 0.6;

const el = i => document.getElementById(i);
// These are in gate.html from the start, so they are looked up once.
// The gate key box is built by render(), so that one stays a lookup.
const out = el("out"), codeBox = el("code"), boardBox = el("board"), tools = el("tools");
// Built once. Inside the callback it was a new object for every escaped letter.
const ESC = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
const x = s => String(s).replace(/[&<>"']/g, c => ESC[c]);
const hm = t => t ? new Date(t).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"}) : "—";
const dayHm = t => t ? new Date(t).toLocaleString([], {weekday:"short", hour:"2-digit", minute:"2-digit"}) : "—";

// The visitor's pass shows an entry code, and after entry an exit code, such
// as KT-4821. The guard may type it as kt4821 or KT 4821. A reference is
// VR-40221, or VR-4022 from before references had five digits. WhatsApp
// accepts the digits alone, so this page does too.
const PASS_CODE = /^([A-HJ-NP-Z]{2})-?(\d{4})$/;
const REFERENCE = /^(?:VR-?)?(\d{4,5})$/;
const tidy = text => {
  const squeezed = text.replace(/\s+/g, "").toUpperCase();
  const ref = REFERENCE.exec(squeezed);
  if (ref) return `VR-${ref[1]}`;
  const code = PASS_CODE.exec(squeezed);
  return code ? `${code[1]}-${code[2]}` : squeezed;
};

let visit = null;
// The photo of the visitor on screen, as a JPEG data URL. It belongs to this
// pass only, so every new pass, Next visitor and each entry clears it.
let photo = "";
let notice = "";
let keySent = "";
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

// A wrong key comes back as its own kind of error, so every caller can send
// the guard back to the key box. Before, a saved wrong key stayed saved: the
// lists only said they could not load, and the key box was hidden.
class WrongKey extends Error {}

function forgetKey(why = "") {
  try { localStorage.removeItem("gatekey"); } catch { /* it was never stored */ }
  visit = null;
  photo = "";
  notice = why;
  board = null;
  boardAt = null;
  boardError = "";
  render();
}

const BANNER = {
  approved: ["good", "Let them in", "Pass is valid."],
  inside:   ["good", "Inside now", "Record the exit when they leave."],
  closed:   ["bad", "Pass closed", "This visit is over. The code no longer works."],
  declined: ["bad", "Declined", "Do not let them in."],
  pending:  ["wait", "Not approved yet", "Do not let them in."],
  escalated:["wait", "Not approved yet", "Do not let them in."],
  expired:  ["bad", "Pass expired", "Do not let them in. They must send a new request."],
};

const svg = d => `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICON = {
  good: svg('<circle cx="12" cy="12" r="10"/><path d="m7.5 12.5 3 3 6-6.5"/>'),
  wait: svg('<circle cx="12" cy="12" r="10"/><path d="M12 7v5l3 2"/>'),
  bad:  svg('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/>'),
};
const banner = (tone, title, line) =>
  `<div class="state ${tone}">${ICON[tone]}<div><h2>${x(title)}</h2><p>${x(line)}</p></div></div>`;

const fact = (k, v) => `<div><span>${k}</span><b>${x(v || "—")}</b></div>`;

// The entry needs a photo of the visitor, taken here, before Record entry works.
function entryStep() {
  return `<label class="btn plain" for="cam">${photo ? "Take the photo again" : "Take a photo of the visitor"}</label>
    <input id="cam" type="file" accept="image/*" capture="environment" hidden>
    ${photo ? `<img class="shot" src="${x(photo)}" alt="The photo of the visitor">` : ""}
    ${photo ? `<button class="btn go" id="enter" onclick="act('entry')">Record entry</button>`
            : `<button class="btn go" id="enter" disabled>Record entry</button>`}
    ${photo ? "" : `<p class="sub">The entry needs a photo of the visitor.</p>`}`;
}

// The button needs the code from the visitor's pass: the entry code records
// the entry, and the exit code the exit. A tap on the board opens the pass by
// reference, which shows who it is and records nothing.
const NEED = {
  approved: ["entry", null,
             "To record the entry, type the entry code on the visitor's pass."],
  inside:   ["exit", `<button class="btn" onclick="act('exit')">Record exit</button>`,
             "To record the exit, type the exit code on the visitor's pass. It shows there once they are inside."],
};

function nextStep(v) {
  const [kind, button, hint] = NEED[v.status] || [];
  if (!kind) return "";
  if (v.code_kind !== kind) return `<p class="sub">${hint}</p>`;
  return kind === "entry" ? entryStep() : button;
}
const problem = t => banner("bad", "Cannot do that", t);
const working = t => `<div class="state wait"><span class="spin"></span><div><h2>${x(t)}</h2><p>This can take up to a minute if the server was asleep.</p></div></div>`;

// The try covers the network only. A server that answers and refuses is not a
// failure of the call, so those two refusals are raised after the try ends.
async function call(url, options) {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), CALL_TIMEOUT);
  let r, data;
  try {
    const headers = {...(options || {}).headers, "X-Gate-Key": key()};
    r = await fetch(url, {...options, headers, signal: stop.signal});
    data = await r.json().catch(() => ({}));
  } catch (err) {
    throw err.name === "AbortError"
      ? new Error("The server did not answer. Check your connection and try again.")
      : err;
  } finally {
    clearTimeout(timer);
  }
  if (r.status === 403) throw new WrongKey("That gate key is not right. Type it again.");
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
  return `<button class="row" data-long="${!!long}" data-ref="${x(v.reference)}">
      <span><b>${x(v.name)}${plus(v)}</b><small>Visiting ${x(v.visiting)}</small></span>
      <span class="side"><code>${x(v.reference)}</code><small>${side}</small></span></button>`;
}

function section(title, list, empty, line) {
  return `<h2 class="sec">${title}<span class="count">${list.length}</span></h2>
    <div class="list">${list.length ? list.map(line).join("") : `<div class="empty">${empty}</div>`}</div>`;
}

// The badge in the header: green while the lists are fresh, amber after a
// failed refresh.
function renderLive() {
  const live = el("live");
  live.hidden = !key() || (!board && !boardError);
  live.classList.toggle("off", !!boardError);
  el("liveText").textContent = boardError ? "Offline" : "Live";
}

function renderBoard() {
  renderLive();
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
      : `Updated ${hm(boardAt)}. Tap a name to see who it is.`}</p>
    ${board.you ? `<p class="updated">This page uses the key of ${x(board.you)}.</p>` : ""}`;
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
    renderLive();
    out.innerHTML = `
      ${notice ? problem(notice) : ""}
      ${keySent ? banner("good", "Key sent", keySent) : ""}
      <label for="k">Gate key</label>
      <input id="k" class="key" type="password" autocomplete="current-password" enterkeyhint="go">
      <button class="btn" onclick="saveKey()">Save key</button>
      <button class="btn plain" id="forgot" onclick="sendKey()">Forgot gate key?</button>
      <p class="sub">Lost the key the admin made for you alone? Send KEY from your phone to the app's WhatsApp number. You get a new key.</p>`;
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

  // Once the visit is over the server sends times and nothing else, so the
  // desk stops showing the visitor's name, phone number and address.
  const closed = visit.status === "closed";
  const details = closed ? "" : `
      ${fact("Name", visit.name)}
      ${fact("Phone", visit.phone)}
      ${fact("Visiting", visit.visiting)}
      ${fact("Reason", visit.reason)}
      ${visit.guests && visit.guests.length ? fact("With", visit.guests.join(", ")) : ""}
      ${visit.decided_at ? fact(visit.status === "declined" ? "Declined" : "Approved", hm(visit.decided_at)) : ""}
      ${visit.status === "approved" && visit.expires_at ? fact("Valid until", dayHm(visit.expires_at)) : ""}`;

  out.innerHTML = `
    ${notice ? problem(notice) : ""}
    ${banner(tone, title, line)}
    <div class="facts">
      ${visit.code ? fact(visit.code_kind === "entry" ? "Entry code" : "Exit code", visit.code) : ""}
      ${fact("Reference", visit.reference)}
      ${details}
      ${visit.entered_at ? fact("Entered", hm(visit.entered_at)) : ""}
      ${visit.exited_at ? fact("Exited", hm(visit.exited_at)) : ""}
    </div>
    ${nextStep(visit)}
    <button class="btn plain" onclick="clear_()">Next visitor</button>`;
  const cam = el("cam");
  if (cam) cam.onchange = () => void takePhoto(cam.files[0]);
}

// Redraws the phone photo as a small JPEG with no metadata. Tests replace it: jsdom has no canvas.
async function shrink(file) {
  let picture;
  try {
    picture = await createImageBitmap(file);
  } catch {
    throw new Error("That file is not a photo. Take it again.");
  }
  const scale = Math.min(1, PHOTO_SIDE / Math.max(picture.width, picture.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(picture.width * scale);
  canvas.height = Math.round(picture.height * scale);
  canvas.getContext("2d").drawImage(picture, 0, 0, canvas.width, canvas.height);
  picture.close();
  return canvas.toDataURL("image/jpeg", PHOTO_QUALITY);
}

async function takePhoto(file) {
  if (!file || !visit) return;
  const forCode = visit.code;
  notice = "";
  let shot = "", problem = "";
  try {
    shot = await shrink(file);
  } catch (err) {
    problem = err.message;
  }
  // The guard may have moved to another pass while the photo was shrinking.
  if (!visit || visit.code !== forCode) return;
  photo = shot;
  notice = problem;
  render();
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
    if (err instanceof WrongKey) return forgetKey(err.message);
    boardError = err.message;
  }
  if (!busy) renderBoard();
}

// Asks the server to send the gate key to the gate desk WhatsApp. The page never sees the key.
async function sendKey() {
  el("forgot").disabled = true;
  el("forgot").textContent = "Sending…";
  const [ok, data] = await askForKey("gate");
  notice = ok ? "" : data.error;
  keySent = ok
    ? `We sent the gate key by WhatsApp to the gate desk number that ends in ${data.sent_to}.`
      + " It can take a minute. If it does not arrive, send KEY from that phone to the app's WhatsApp number."
    : "";
  render();
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
  keySent = "";
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
  await show(code);
}

// Opens a pass by the code the guard typed, or by reference after a tap.
async function show(key) {
  visit = null;
  photo = "";
  notice = "";
  busy = "Checking the pass";
  render();
  try {
    visit = await call(`/api/pass/${encodeURIComponent(key)}`);
  } catch (err) {
    busy = "";
    if (err instanceof WrongKey) return forgetKey(err.message);
    notice = err.message;
  }
  busy = "";
  render();
}

// A tap on a name in either list shows who it is. The code box stays empty,
// ready for the code on the visitor's pass, which the buttons need.
function openPass(reference) {
  codeBox.value = "";
  window.scrollTo(0, 0);
  void show(reference).then(() => codeBox.focus());
}

async function act(action) {
  const code = visit.code;
  notice = "";
  busy = action === "entry" ? "Recording the entry" : "Recording the exit";
  render();
  const options = {method: "POST"};
  if (action === "entry") {
    Object.assign(options, {headers: {"Content-Type": "application/json"},
                            body: JSON.stringify({photo})});
  }
  try {
    visit = await call(`/api/pass/${encodeURIComponent(code)}/${action}`, options);
    photo = "";
  } catch (err) {
    busy = "";
    if (err instanceof WrongKey) return forgetKey(err.message);
    notice = err.message;
    // The refusal above is what the guard needs. A failed re-read adds nothing.
    try { visit = await call(`/api/pass/${encodeURIComponent(code)}`); } catch { /* keep the refusal */ }
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
    if (r.status === 403) {
      busy = "";
      return forgetKey("That gate key is not right. Type it again.");
    }
    if (r.ok) await saveFile(r);
    else notice = `Could not download (${r.status})`;
  } catch (err) {
    notice = err.message;
  }
  busy = "";
  render();
}

function clear_() {
  visit = null;
  photo = "";
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
el("rekey").onclick = () => forgetKey();
// A hidden tab does not need fresh lists. It catches up when shown again.
setInterval(() => { if (!document.hidden) void loadBoard(); }, BOARD_EVERY);
document.addEventListener("visibilitychange", () => { if (!document.hidden) void loadBoard(); });
render();
void loadBoard();
