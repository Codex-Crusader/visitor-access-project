const CALL_TIMEOUT = 75000;  // a sleeping free server can take ~50s to wake

const el = i => document.getElementById(i);
// These two are in gate.html from the start, so they are looked up once.
// The gate key box is built by render(), so that one stays a lookup.
const out = el("out"), codeBox = el("code");
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

function render() {
  // The key comes first. Without it nothing else can work, so nothing else shows.
  const haveKey = !!key();
  el("entry").hidden = !haveKey;
  el("sub").textContent = haveKey
    ? "Type the code on the visitor's pass."
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

  if (busy) {
    out.innerHTML = working(busy);
    return;
  }

  if (!visit) {
    out.innerHTML = `
      ${notice ? problem(notice) : ""}
      <button class="btn plain" onclick="downloadLog()">Download visit log</button>
      <button class="btn plain" onclick="forgetKey()">Change gate key</button>`;
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
render();
