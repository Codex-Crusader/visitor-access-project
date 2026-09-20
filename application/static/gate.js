const $ = i => document.getElementById(i);
const x = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const hm = t => t ? new Date(t).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"}) : "—";

let visit = null;
let notice = "";

function key() {
  try { return localStorage.getItem("gatekey") || ""; } catch (err) { return ""; }
}

function setKey(value) {
  try { localStorage.setItem("gatekey", value); } catch (err) {}
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

async function call(url, options) {
  const r = await fetch(url, {...options, headers: {"X-Gate-Key": key()}});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
}

function render() {
  if (!key()) {
    $("out").innerHTML = `
      <div class="state wait"><h2>Gate key needed</h2><p>Type the key your admin gave you. It is stored on this device only.</p></div>
      <label for="k">Gate key</label>
      <input id="k" type="password" style="text-transform:none;letter-spacing:normal;font-size:1rem">
      <button class="btn" onclick="saveKey()">Save key</button>`;
    return;
  }
  if (!visit) {
    $("out").innerHTML = notice
      ? `<div class="state bad"><h2>Cannot do that</h2><p>${x(notice)}</p></div>`
      : "";
    return;
  }
  const [tone, title, line] = BANNER[visit.status] || ["wait", visit.status, ""];
  const buttons =
    visit.status === "approved" ? `<button class="btn go" onclick="act('entry')">Record entry</button>` :
    visit.status === "inside"   ? `<button class="btn" onclick="act('exit')">Record exit</button>` : "";

  $("out").innerHTML = `
    ${notice ? `<div class="state bad"><h2>Cannot do that</h2><p>${x(notice)}</p></div>` : ""}
    <div class="state ${tone}"><h2>${x(title)}</h2><p>${x(line)}</p></div>
    <div class="facts">
      ${fact("Code", visit.reference)}
      ${fact("Name", visit.name)}
      ${fact("Phone", visit.phone)}
      ${fact("Visiting", visit.visiting)}
      ${fact("Reason", visit.reason)}
      ${visit.guests.length ? fact("With", visit.guests.join(", ")) : ""}
      ${fact("Approved", hm(visit.decided_at))}
      ${visit.entered_at ? fact("Entered", hm(visit.entered_at)) : ""}
      ${visit.exited_at ? fact("Exited", hm(visit.exited_at)) : ""}
    </div>
    ${buttons}
    <button class="btn plain" onclick="clear_()">Next visitor</button>`;
}

function saveKey() {
  const value = $("k").value.trim();
  if (!value) return;
  setKey(value);
  render();
  $("code").focus();
}

async function look() {
  const code = $("code").value.trim().toUpperCase();
  if (!code) return;
  visit = null;
  notice = "";
  try {
    visit = await call(`/api/pass/${encodeURIComponent(code)}`);
  } catch (err) {
    notice = err.message;
  }
  render();
}

async function act(action) {
  notice = "";
  try {
    visit = await call(`/api/pass/${encodeURIComponent(visit.reference)}/${action}`, {method: "POST"});
  } catch (err) {
    notice = err.message;
    try {
      visit = await call(`/api/pass/${encodeURIComponent(visit.reference)}`);
    } catch (ignored) {}
  }
  render();
}

function clear_() {
  visit = null;
  notice = "";
  $("code").value = "";
  render();
  $("code").focus();
}

$("look").onclick = look;
$("code").onkeydown = e => { if (e.key === "Enter") look(); };
render();
$("code").focus();
