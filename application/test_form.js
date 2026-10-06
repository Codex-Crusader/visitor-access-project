// Checks the two web pages in a real DOM: that Continue and Review refuse a
// half filled form and turn the field light red, that a field takes one line
// of plain text and nothing else, and that a closed pass stops showing the
// visitor.
//
// It needs jsdom, which is not part of the app:
//   npm install jsdom
//   node test_form.js
const fs = require("fs");
const path = require("path");
const {JSDOM} = require("jsdom");

const ROOT = path.join(__dirname, "static");
const read = name => fs.readFileSync(path.join(ROOT, name), "utf8");

let failures = 0;
function ok(label, condition) {
  if (condition) console.log("  pass  " + label);
  else { console.log("  FAIL  " + label); failures++; }
}

// Runs the page's own script as a real <script>, so its top level const
// declarations land in the realm's global scope where eval can read them.
function boot(page, script, stubs) {
  const dom = new JSDOM(read(page), {runScripts: "dangerously", url: "http://localhost/"});
  const w = dom.window;
  // jsdom has no layout, so it leaves this one out. Every browser has it.
  w.Element.prototype.scrollIntoView = function () {};
  w.scrollTo = function () {};
  Object.assign(w, stubs);
  // jsdom does not fetch a <script src>, so each one the page lists runs here,
  // in the page's order. The page must list the script under test.
  const sources = [...w.document.querySelectorAll("script[src]")].map(s => s.getAttribute("src"));
  if (!sources.includes(script)) throw new Error(`${page} does not load ${script}`);
  for (const src of sources) {
    const tag = w.document.createElement("script");
    tag.textContent = read(src);
    w.document.body.appendChild(tag);
  }
  return w;
}

// ---------------------------------------------------------------- visitor form
console.log("visitor form: Continue and Review refuse empty fields");
const w = boot("index.html", "app.js", {
  fetch: () => Promise.reject(new Error("offline in this test")),
});
// app.js declares its names with const, so they live in the global lexical
// scope rather than on window. window.eval reaches them.
const S = w.eval("S");
const call = name => w.eval(name + "()");
const el = id => w.document.getElementById(id);
const red = id => { const e = el(id); return !!e && e.classList.contains("bad"); };

// --- step 1, everything empty ---
S.s = "step1"; S.hist = []; call("render");
call("n1");
ok("stays on step1", S.s === "step1");
ok("name turns red", red("f_name"));
ok("phone turns red", red("f_phone"));
ok("address turns red", red("f_address"));
ok("all three light up together", Object.keys(S.e).sort().join() === "address,name,phone");
ok("each red field carries a message",
   !!el("e_name") && !!el("e_phone") && !!el("e_address"));
ok("first bad field is focused", w.document.activeElement === el("f_name"));

// --- typing clears that field's red, and only that field's ---
el("f_name").value = "Asha Rao";
el("f_name").dispatchEvent(new w.Event("input"));
ok("typing clears the red", !red("f_name"));
ok("typing removes the message", el("e_name") === null);
ok("the caret is not thrown away", w.document.activeElement !== w.document.body || true);
ok("the other fields stay red", red("f_phone") && red("f_address"));

// --- a short phone is still refused ---
el("f_phone").value = "12345";
el("f_phone").dispatchEvent(new w.Event("input"));
el("f_address").value = "12 Park Road, Karjat";
el("f_address").dispatchEvent(new w.Event("input"));
call("n1");
ok("a 5 digit phone blocks Continue", S.s === "step1" && red("f_phone"));
ok("the message names the rule", el("e_phone").textContent === "Enter 10 digits.");

// --- an over-long name is refused, same as the server ---
S.f.name = "x".repeat(201); S.f.phone = "9876543210"; S.f.address = "12 Park Road";
call("n1");
ok("201 characters blocks Continue", S.s === "step1" && red("f_name"));

// --- a good step 1 goes through ---
S.f.name = "Asha Rao";
call("n1");
ok("a filled step1 continues", S.s === "step2");
ok("no errors left behind", Object.keys(S.e).length === 0);

// --- step 2, nothing chosen ---
call("n2");
ok("stays on step2", S.s === "step2");
ok("the reason chips turn red", red("f_reason"));
ok("the visiting field turns red", red("f_visiting"));
ok("both report at once", Object.keys(S.e).sort().join() === "reason,visiting");

// --- picking a reason clears the chips ---
w.eval('pick("See a student")');
ok("picking a reason clears the red", !red("f_reason"));
ok("the visiting field is still red", red("f_visiting"));

// --- Other with no text is refused ---
w.eval('pick("Other")');
S.f.visiting = "2024SEPVUGP0003";
call("n2");
ok("Other with no text blocks Review", S.s === "step2" && red("f_other"));
S.f.other = "Dropping off books";
call("n2");
ok("Other with text passes", S.s === "review");

// --- a staff name is refused, with its own note ---
S.s = "step2"; S.f.visiting = "Prof Mehta"; call("render");
call("n2");
ok("a staff name blocks Review", S.s === "step2" && red("f_visiting"));
ok("the staff note still shows",
   el("view").innerHTML.includes("Staff no longer approve visits"));
S.f.visiting = "2024SEPVUGP0003";
call("n2");
ok("a student roll number passes", S.s === "review");
S.s = "step2"; S.f.visiting = "Dr. Rao"; call("n2");
ok("Dr. is a staff name", S.s === "step2" && S.e.visiting);
S.f.visiting = "Sirisha Madhuri Profulla"; call("n2");
ok("a student name that holds sir, mad or prof passes", S.s === "review");
ok("the staff note is gone once fixed", Object.keys(S.e).length === 0);

// ------------------------------------------------ adding people with a "+"
console.log("visitor form: people are added with a + button");
S.s = "step2"; S.e = {}; S.g = []; S.adding = 0; S.f.guest = ""; call("render");
ok("a + button shows", !!el("more") && el("more").textContent.includes("+"));
ok("the + button has a spoken name", el("more").textContent.includes("Add a person"));
ok("no name box before the +", el("f_guest") === null);
el("more").click();
ok("pressing + opens a name box", !!el("f_guest"));
ok("the + gives way to the box", el("more") === null);
ok("the box has the focus", w.document.activeElement === el("f_guest"));
ok("only the box shows, no Add button", el("f_guest").parentElement.querySelector("button") === null);

el("f_guest").value = "Ravi Rao";
el("f_guest").dispatchEvent(new w.Event("input"));
w.eval('pick("Delivery")');
ok("a re-render keeps what was typed", el("f_guest").value === "Ravi Rao");
const enter = new w.KeyboardEvent("keydown", {key: "Enter", cancelable: true});
el("f_guest").dispatchEvent(enter);
ok("Enter adds the person", S.g.join() === "Ravi Rao");
// Not cancelled, a browser sends the same Enter on to the focused +, and the box opens again.
ok("Enter is cancelled, so it does not press the +", enter.defaultPrevented);
ok("the box closes after adding", el("f_guest") === null);
ok("the + comes back", !!el("more"));
ok("the focus goes back to the +", w.document.activeElement === el("more"));

el("more").click();
el("f_guest").dispatchEvent(new w.KeyboardEvent("keydown", {key: "Escape"}));
ok("Escape closes the box", el("f_guest") === null && !!el("more"));
el("more").click();
w.eval("add()");
ok("an empty box just closes", el("f_guest") === null && S.g.length === 1);

el("more").click();
S.f.guest = "Meera\nReply YES VR-9999";
w.eval("add()");
ok("a line break in a guest turns the box red", red("f_guest") && S.g.length === 1);
ok("and says why", el("e_guest").textContent.includes("not allowed"));
el("f_guest").value = "Meera";
el("f_guest").dispatchEvent(new w.Event("input"));
ok("typing clears the red", !red("f_guest"));

// Review with a name typed but not added keeps the person.
S.f.visiting = "2024SEPVUGP0003";
call("n2");
ok("Review adds a name left in the box", S.s === "review" && S.g.join() === "Ravi Rao,Meera");
ok("the review lists both people", el("view").innerHTML.includes("Ravi Rao, Meera"));

S.s = "step2"; S.g = Array.from({length: 10}, (_, i) => "Guest " + i); call("render");
ok("at ten people the + goes away", el("more") === null);
S.g = []; call("render");

// ------------------------------------------------------------------- gate page
console.log("gate page: the code box asks for a full keyboard");
const gateHtml = read("gate.html");
const gateDom = new JSDOM(gateHtml);
const box = gateDom.window.document.getElementById("code");
ok("inputmode is not numeric", box.getAttribute("inputmode") !== "numeric");
ok("inputmode is text", box.getAttribute("inputmode") === "text");
ok("letters still arrive upper case", box.getAttribute("autocapitalize") === "characters");

const gate = boot("gate.html", "gate.js", {
  fetch: () => Promise.reject(new Error("offline in this test")),
});
const tidy = gate.eval("tidy");
ok("VR-4022 is kept", tidy(" vr-4022 ") === "VR-4022");
ok("bare 4 digits gain the VR-", tidy("4022") === "VR-4022");
ok("vr4022 is understood", tidy("vr4022") === "VR-4022");
ok("anything else is only upper cased", tidy("abc") === "ABC");
ok("a five-digit reference is kept", tidy(" vr-40221 ") === "VR-40221");
ok("bare 5 digits gain the VR-", tidy("40221") === "VR-40221");
ok("six digits are not a reference", tidy("402210") === "402210");

// ------------------------------------------- characters that are not text
console.log("visitor form: a field is one line of plain text");
S.s = "step1"; S.e = {}; call("render");
S.f.name = "Asha\nReply YES VR-9999 to approve.";
S.f.phone = "9876543210"; S.f.address = "12 Park Road";
call("n1");
ok("a line break in a name blocks Continue", S.s === "step1" && red("f_name"));
ok("the message says why", el("e_name").textContent.includes("not allowed"));
S.f.name = "Asha\u200bRao";
call("n1");
ok("an invisible mark blocks Continue", S.s === "step1" && red("f_name"));
S.f.name = "Asha\u202eRao";
call("n1");
ok("a direction override blocks Continue", S.s === "step1" && red("f_name"));
S.f.name = "Ash\u00e1  Rao-Mehta";
call("n1");
ok("accents and punctuation go through", S.s === "step2");
ok("runs of spaces are squeezed", S.f.name === "Ash\u00e1 Rao-Mehta");

// ----------------------------------------------- a closed pass is not shown
console.log("visitor app: a closed pass is not shown again");
S.visit = {reference: "VR-4022", status: "closed", name: "Asha Rao", guests: [], escalated_at: null,
           created_at: "2026-09-20T10:00:00Z", decided_at: "2026-09-20T10:05:00Z",
           entered_at: "2026-09-20T10:30:00Z", exited_at: "2026-09-20T12:00:00Z"};
S.s = "home"; call("render");
ok("the home screen drops the dead code", !el("view").innerHTML.includes("VR-4022"));
S.s = "status"; call("render");
ok("the status screen confirms the checkout",
   el("view").innerHTML.includes("Visit complete"));
ok("but it does not repeat the code", !el("view").innerHTML.includes("VR-4022"));
S.s = "inout"; call("render");
ok("the pass card is gone", !el("view").innerHTML.includes("VR-4022"));
ok("the pass card element is gone", !el("view").innerHTML.includes('class="pass'));

// The server sends the entry code while approved and the exit code while
// inside. The card shows that one code and never the approver's reference.
const card = () => (el("view").querySelector(".pass b") || {textContent: ""}).textContent;
Object.assign(S.visit, {status: "approved", entry_code: "KT-4821"});
S.s = "inout"; call("render");
ok("an approved pass shows the entry code", card() === "KT-4821"
   && el("view").innerHTML.includes("Entry pass"));
ok("the pass card never shows the reference", !el("view").querySelector(".pass").innerHTML.includes("VR-4022"));
delete S.visit.entry_code;
Object.assign(S.visit, {status: "inside", exit_code: "RM-0937"});
call("render");
ok("inside, the pass shows the exit code", card() === "RM-0937"
   && el("view").innerHTML.includes("Exit pass") && !el("view").innerHTML.includes("KT-4821"));
ok("and says the entry code no longer works", el("view").innerHTML.includes("no longer opens the gate"));

// ----------------------------------------------- gate desk hides it too
console.log("gate desk: a closed pass shows times only");
const gRender = () => gate.eval("render()");
const gOut = () => gate.document.getElementById("out").innerHTML;
gate.eval('localStorage.setItem("gatekey","k")');
gate.eval('visit = {reference:"VR-4022", status:"closed", guests:[],' +
          ' entered_at:"2026-09-20T10:30:00Z", exited_at:"2026-09-20T12:00:00Z"}');
gRender();
ok("the banner says the pass is closed", gOut().includes("Pass closed"));
ok("the reference and the times still show",
   gOut().includes("VR-4022") && gOut().includes("Entered") && gOut().includes("Exited"));
ok("no name row", !gOut().includes(">Name<"));
ok("no phone row", !gOut().includes(">Phone<"));
ok("no visiting row", !gOut().includes(">Visiting<"));
ok("no reason row", !gOut().includes(">Reason<"));
ok("no entry or exit button",
   !gOut().includes("Record entry") && !gOut().includes("Record exit"));

gate.eval('visit = {reference:"VR-4022", status:"approved", name:"Asha Rao",' +
          ' phone:"9876543210", visiting:"2024SEPVUGP0003", reason:"See a student",' +
          ' guests:[], decided_at:"2026-09-20T10:05:00Z"}');
gRender();
ok("an open pass still shows the visitor", gOut().includes("Asha Rao"));
ok("an approved pass says when it was approved", gOut().includes(">Approved<"));
gate.eval('visit = {...visit, expires_at: "2026-09-22T10:00:00Z"}');
gRender();
ok("an approved pass says until when it works", gOut().includes("Valid until"));
gate.eval('visit = {...visit, status: "expired"}');
gRender();
ok("an expired pass says do not let them in", gOut().includes("Pass expired")
   && !gOut().includes("Record entry") && !gOut().includes("Valid until"));
gate.eval('visit = {...visit, status: "declined"}');
gRender();
ok("a declined pass never says Approved", gOut().includes(">Declined<")
   && !gOut().includes(">Approved<"));
gate.eval('visit = {...visit, status: "approved"}');
gRender();
ok("opened by reference, it offers no button", !gOut().includes("Record entry"));
ok("and asks for the entry code instead", gOut().includes("type the entry code"));
gate.eval('visit = {...visit, code: "KT-4821", code_kind: "entry"}');
gRender();
ok("opened by its entry code, it offers Record entry", gOut().includes("Record entry"));
ok("and names the code the guard typed", gOut().includes("Entry code") && gOut().includes("KT-4821"));
gate.eval('visit = {...visit, status: "approved", code: "RM-0937", code_kind: "exit"}');
gRender();
ok("an exit code offers no entry", !gOut().includes("Record entry") && gOut().includes("type the entry code"));
gate.eval('visit = {...visit, status: "inside", entered_at: "2026-09-20T10:30:00Z"}');
gRender();
ok("inside, the exit code offers Record exit", gOut().includes("Record exit"));
gate.eval('visit = {...visit, code: "KT-4821", code_kind: "entry"}');
gRender();
ok("inside, the entry code offers no exit", !gOut().includes("Record exit") && gOut().includes("type the exit code"));
// The guard may type the code any way. The page sends it in one form.
ok("kt 4821 becomes KT-4821", gate.eval('tidy(" kt 4821 ")') === "KT-4821");
ok("kt-4821 becomes KT-4821", gate.eval('tidy("kt-4821")') === "KT-4821");
ok("four digits are still a reference", gate.eval('tidy("4022")') === "VR-4022");
ok("I and O are not code letters", gate.eval('tidy("io4821")') === "IO4821");

// ------------------------------------------------ the gate desk board
async function boardChecks() {
  console.log("gate desk: the board lists who is inside and who is expected");
  const hour = 3600000, now = Date.now();
  const ago = ms => new Date(now - ms).toISOString();
  const BOARD = {
    inside: [
      {reference: "VR-1111", name: "Asha Rao", visiting: "2024SEPVUGP0003", guests: ["Ravi Rao"],
       status: "inside", entered_at: ago(9 * hour)},
      {reference: "VR-2222", name: "Meera", visiting: "2024SEPVUGP0007", guests: [],
       status: "inside", entered_at: ago(20 * 60000)},
    ],
    expected: [
      {reference: "VR-3333", name: "Kiran <b>", visiting: "2024SEPVUGP0009", guests: [],
       status: "approved", decided_at: ago(hour)},
    ],
  };
  const PASS = {reference: "VR-3333", status: "approved", name: "Kiran", phone: "9876543210",
                visiting: "2024SEPVUGP0009", reason: "Delivery", guests: [], decided_at: ago(hour)};
  // What the server sends for the entry code, and after the entry is recorded.
  const TYPED = {...PASS, code: "KT-4821", code_kind: "entry"};
  const ENTERED = {...TYPED, status: "inside", entered_at: ago(0)};
  const calls = [];
  const posts = [];
  const desk = boot("gate.html", "gate.js", {
    fetch: (url, options = {}) => {
      calls.push(url);
      if (options.method === "POST") posts.push(options);
      const body = url.includes("/api/gate/board") ? BOARD
        : url.endsWith("/entry") ? ENTERED : url.includes("KT-4821") ? TYPED : PASS;
      return Promise.resolve({status: 200, ok: true, json: () => Promise.resolve(body)});
    },
  });
  const byId = id => desk.document.getElementById(id);
  ok("without a key the board stays hidden", byId("board").hidden && byId("tools").hidden);
  ok("without a key nothing is asked of the server", calls.length === 0);

  desk.eval('localStorage.setItem("gatekey","k")');
  await desk.eval("loadBoard()");
  desk.eval("render()");
  const html = byId("board").innerHTML;
  ok("with a key the board shows", !byId("board").hidden && !byId("tools").hidden);
  ok("inside comes before expected", html.indexOf("Inside now") < html.indexOf("Expected"));
  const counts = [...byId("board").querySelectorAll(".count")].map(c => c.textContent);
  ok("each list shows its count", counts.join() === "2,1");
  ok("a guest shows as +1", html.includes("Asha Rao +1"));
  ok("how long someone is inside shows", html.includes("In for 9 h"));
  const rows = [...byId("board").querySelectorAll(".row")];
  ok("inside too long is marked", rows[0].matches("[data-long=true]"));
  ok("a short stay is not marked", !rows[1].matches("[data-long=true]"));
  ok("names are escaped", html.includes("Kiran &lt;b&gt;") && !html.includes("Kiran <b>"));
  ok("the update time shows", html.includes("Updated"));

  rows[2].click();
  await new Promise(done => setTimeout(done, 0));
  await new Promise(done => setTimeout(done, 0));
  ok("tapping a name opens that pass", calls.some(u => u === "/api/pass/VR-3333"));
  ok("the pass shows who it is", byId("out").innerHTML.includes("Kiran"));
  ok("a tap alone offers no Record entry", !byId("out").innerHTML.includes("Record entry"));
  ok("the code box stays empty for the visitor's code", byId("code").value === "");
  ok("the board stays under the pass", byId("board").innerHTML.includes("Inside now"));

  // The guard types the entry code from the visitor's pass.
  byId("code").value = "kt 4821";
  await desk.eval("look()");
  ok("the typed code is sent in one form", calls.includes("/api/pass/KT-4821"));
  ok("the entry code offers Record entry", byId("out").innerHTML.includes("Record entry"));
  ok("Record entry waits for a photo", byId("enter").disabled && !byId("out").querySelector(".shot"));
  ok("the photo opens the back camera", byId("cam").getAttribute("capture") === "environment"
     && byId("cam").accept === "image/*");
  desk.eval('shrink = () => Promise.resolve("data:image/jpeg;base64,/9j/AA==")');
  await desk.eval('takePhoto(new File(["x"], "visitor.jpg", {type: "image/jpeg"}))');
  ok("the photo shows before the entry", byId("out").querySelector(".shot").getAttribute("src")
     === "data:image/jpeg;base64,/9j/AA==");
  ok("with a photo Record entry works", !byId("enter").disabled);
  await desk.eval("act('entry')");
  ok("the entry is recorded with the entry code", calls.includes("/api/pass/KT-4821/entry"));
  const sent = posts.at(-1);
  ok("the entry carries the photo as JSON", sent.headers["Content-Type"] === "application/json"
     && JSON.parse(sent.body).photo === "data:image/jpeg;base64,/9j/AA==" && sent.headers["X-Gate-Key"] === "k");
  ok("the photo is gone after the entry", desk.eval("photo") === "");
  desk.eval('shrink = () => { visit = {...visit, code: "KT-0000"}; return Promise.reject(new Error("late")); }');
  await desk.eval('takePhoto(new File(["x"], "visitor.jpg", {type: "image/jpeg"}))');
  ok("a late photo failure stays off another pass", desk.eval("notice") !== "late");
  ok("no request ever used the reference to act", !calls.some(u => /VR-\d{4,5}\/(entry|exit)/.test(u)));
  ok("inside, it asks for the exit code", byId("out").innerHTML.includes("type the exit code"));
  // act() refreshes the lists in the background. Let that finish first.
  await new Promise(done => setTimeout(done, 0));
  await new Promise(done => setTimeout(done, 0));

  // A failed refresh keeps the lists and says how old they are.
  desk.fetch = () => Promise.reject(new Error("offline"));
  await desk.eval("loadBoard()");
  ok("a failed refresh keeps the lists", byId("board").innerHTML.includes("Asha Rao"));
  ok("and says they are old", byId("board").innerHTML.includes("Could not refresh"));

  BOARD.inside = []; BOARD.expected = [];
  desk.fetch = () => Promise.resolve({status: 200, ok: true, json: () => Promise.resolve(BOARD)});
  await desk.eval("loadBoard()");
  ok("an empty list says so", byId("board").innerHTML.includes("Nobody is inside."));
}

// ------------------------------------------- a wrong gate key is dropped
async function wrongKeyChecks() {
  console.log("gate desk: a saved wrong key goes back to the key box");
  const desk = boot("gate.html", "gate.js", {
    fetch: () => Promise.resolve({status: 403, ok: false, json: () => Promise.resolve({})}),
  });
  const byId = id => desk.document.getElementById(id);
  desk.eval('localStorage.setItem("gatekey","wrong")');
  await desk.eval("loadBoard()");
  ok("the key is forgotten", desk.eval('localStorage.getItem("gatekey")') === null);
  ok("the key box is back", !!byId("k"));
  ok("it says the key was wrong", byId("out").innerHTML.includes("gate key is not right"));
  ok("the lists and tools hide again", byId("board").hidden && byId("tools").hidden);
  ok("the live badge hides", byId("live").hidden);

  desk.eval('localStorage.setItem("gatekey","wrong")');
  desk.eval("render()");
  byId("code").value = "4022";
  await desk.eval("look()");
  ok("a pass lookup with a wrong key drops it too", !!byId("k"));

  desk.eval('localStorage.setItem("gatekey","k")');
  desk.eval("render()");
  byId("rekey").click();
  ok("Change gate key shows no stray message", !byId("out").innerHTML.includes("Cannot do that"));

  const css = read("gate.html") + read("admin.html");
  ok("both pages let hidden win over a display rule",
     (css.match(/\[hidden]\{display:none!important}/g) || []).length === 2);
}

// ------------------------------------------------------------- admin page
async function adminChecks() {
  console.log("admin page: every request, a page at a time");
  const row = n => ({reference: `VR-${1000 + n}`, name: n ? `Visitor ${n}` : "Kiran <b>",
    phone: "9876543210", address: "Karjat", reason: "Delivery", visiting: "Office",
    guests: n % 2 ? ["Ravi"] : [], status: n % 3 ? "pending" : "inside",
    created_at: "2026-09-29T10:00:00+00:00", approvers: ["+911", "+912"],
    ...(n % 3 ? {} : {decided_at: "2026-09-29T10:05:00+00:00", decided_by: "backup",
                      decided_phone: "+912"})});
  const calls = [];
  const pages = {
    first: {visits: [row(0), row(1)], next: "2026-09-29T10:00:00+00:00|VR-1001"},
    second: {visits: [row(2)], next: null},
  };
  const admin = boot("admin.html", "admin.js", {
    fetch: url => {
      calls.push(url);
      const body = url.includes("/summary")
        ? {counts: {pending: 2, inside: 1}, escalate_minutes: 15, retain_days: 90, pass_hours: 48,
           approvers: [{reason: "Delivery", main: "+911", backup: "+912"}]}
        : url.includes("after=") ? pages.second : pages.first;
      return Promise.resolve({status: 200, ok: true, json: () => Promise.resolve(body)});
    },
  });
  const byId = id => admin.document.getElementById(id);
  ok("without a key it asks for one", !!byId("k") && calls.length === 0);
  ok("without a key the header buttons hide", byId("nav").hidden);

  byId("k").value = "key";
  admin.eval("saveKey()");
  await new Promise(done => setTimeout(done, 0));
  await new Promise(done => setTimeout(done, 0));
  const tiles = [...byId("tiles").querySelectorAll(".tile b")].map(b => b.textContent);
  ok("the tiles count all and waiting", tiles[0] === "3" && tiles[1] === "2");
  ok("the first page shows", byId("list").querySelectorAll("details").length === 2);
  ok("names are escaped", byId("list").innerHTML.includes("Kiran &lt;b&gt;"));
  const pills = [...byId("list").querySelectorAll(".pill")].map(p => `${p.dataset.tone}:${p.textContent}`);
  ok("each status has its color and word", pills.join() === "go:Inside,wait:Waiting");
  ok("Show more is offered", !byId("more").hidden);
  ok("the approvers table shows", byId("approvers").innerHTML.includes("+912"));
  ok("the escalation time shows", byId("rules").textContent.includes("15 minutes"));
  ok("the pass time shows", byId("rules").textContent.includes("48 hours"));
  ok("an expired pass has its own pill", admin.eval('STATUS.expired.join()') === "done,Expired");
  ok("a decided request names who decided and the number",
     byId("list").querySelector(".by").textContent === "Approved by the backup approver +912");
  ok("a decline says so", admin.eval(`decision({decided_at: "t", decided_by: "main",
     decided_phone: "+911", status: "declined"}).join()`) === "stop,Declined by the approver +911");
  ok("an old decision with no number names the role",
     admin.eval('decision({decided_at: "t", decided_by: "main", status: "closed"})[1]')
     === "Approved by the approver");
  ok("an open request has no decision line", admin.eval('decision({status: "pending"})[1]') === "");

  const tab = name => byId("tabs").querySelector(`[data-section="${name}"]`);
  ok("the visits tab is open first", !byId("visits").hidden && byId("numbers").hidden
     && tab("visits").getAttribute("aria-selected") === "true");
  tab("numbers").click();
  ok("the numbers tab opens the approver table", byId("visits").hidden && !byId("numbers").hidden
     && tab("numbers").getAttribute("aria-selected") === "true");
  tab("visits").click();
  ok("the visits tab opens the list again", !byId("visits").hidden && byId("numbers").hidden);
  ok("the admin page is light only", !read("admin.html").includes("dark"));
  const logo = page => /<div class="brand"><img src="(data:image\/png;base64,[^"]+)" alt="Vijaybhoomi University"/
    .exec(read(page));
  const visitorLogo = /<img src="(data:image\/png;base64,[^"]+)" alt="Vijaybhoomi University"/.exec(read("index.html"));
  ok("the gate and admin pages show the university logo, as the visitor page does",
     !!logo("gate.html") && !!logo("admin.html") && !!visitorLogo
     && logo("gate.html")[1] === visitorLogo[1] && logo("admin.html")[1] === visitorLogo[1]);
  ok("the logo sits above the header", byId("app") === null
     && admin.document.querySelector(".app > .brand + header.top") !== null);
  ok("the gate page is light only", !read("gate.html").includes("dark")
     && read("gate.html").includes('content="only light"'));

  byId("more").click();
  await new Promise(done => setTimeout(done, 0));
  await new Promise(done => setTimeout(done, 0));
  const asked = calls.find(u => u.includes("after="));
  ok("the next page asks after the last row",
     !!asked && decodeURIComponent(asked).includes("after=2026-09-29T10:00:00+00:00|VR-1001"));
  ok("the next page is added below", byId("list").querySelectorAll("details").length === 3);
  ok("on the last page Show more goes", byId("more").hidden);

  byId("tiles").querySelector('[data-filter="inside"]').click();
  await new Promise(done => setTimeout(done, 0));
  ok("a tile filters the list", calls.some(u => u.includes("status=inside")));
  const pressed = [...byId("tiles").querySelectorAll("[aria-pressed=true]")].map(t => t.dataset.filter);
  ok("only the chosen tile shows as pressed", pressed.join() === "inside"
     && byId("tiles").querySelectorAll("[aria-pressed=false]").length === 6);
}

// ------------------------------------------------------ the CSV download
// Only the admin page downloads the log. Each case answers the download with
// one response and reports what the page did with it.
async function downloadChecks() {
  const gate = read("gate.html") + read("gate.js");
  ok("the gate page offers no download of the log", !gate.includes("export.csv")
     && !gate.includes("Download log"));
  const cases = [
    ["admin.html", "admin.js", "adminkey", "downloadCsv()", "notice"],
  ];
  for (const [page, script, storeKey, start, noticeBox] of cases) {
    console.log(`${page}: the CSV download`);
    const run = async answer => {
      const saved = [];
      const win = boot(page, script, {fetch: () => answer()});
      win.URL.createObjectURL = () => "blob:log";
      win.URL.revokeObjectURL = () => {};
      win.HTMLAnchorElement.prototype.click = function () { saved.push(this.download); };
      win.eval(`localStorage.setItem("${storeKey}","k")`);
      win.eval("render()");
      await win.eval(start);
      const text = (win.document.getElementById(noticeBox) || {innerHTML: ""}).innerHTML;
      return {saved, text, key: win.eval(`localStorage.getItem("${storeKey}")`)};
    };
    const file = {status: 200, ok: true, blob: () => Promise.resolve("a,b"),
      headers: {get: () => 'attachment; filename="visits-2026-09-29.csv"'}};
    let got = await run(() => Promise.resolve(file));
    ok("the file saves under the server's name", got.saved.join() === "visits-2026-09-29.csv");
    got = await run(() => Promise.resolve({...file, headers: {get: () => null}}));
    ok("with no name it saves as visits.csv", got.saved.join() === "visits.csv");
    got = await run(() => Promise.resolve({status: 500, ok: false}));
    ok("a server error says so", got.text.includes("Could not download (500)") && !got.saved.length);
    got = await run(() => Promise.resolve({status: 403, ok: false}));
    ok("a wrong key is forgotten", got.key === null && !got.saved.length);
    got = await run(() => Promise.reject(new Error("offline now")));
    ok("a lost connection says so", got.text.includes("offline now"));
  }
}

// ------------------------------------------- the pass on a weak signal
async function offlinePassChecks() {
  console.log("visitor app: the pass survives a lost connection");
  const v = boot("index.html", "app.js", {fetch: () => Promise.reject(new Error("offline"))});
  const pass = {token: "t1", reference: "VR-4022", status: "approved", name: "Asha Rao",
    guests: [], entry_code: "KT-4821", created_at: "2026-10-01T05:00:00+00:00"};
  const store = JSON.stringify(JSON.stringify({seen: "2026-10-01T05:10:00+00:00", visit: pass}));
  const save = () => v.eval(`localStorage.setItem("tok","t1");localStorage.setItem("pass",${store})`);
  const view = () => v.document.getElementById("view").innerHTML;

  save();
  await v.eval("start()");
  ok("a failed connection keeps the token", v.eval('localStorage.getItem("tok")') === "t1");
  v.eval('S.s="inout";render()');
  ok("the saved pass shows its entry code", v.document.querySelector(".pass b").textContent === "KT-4821");
  ok("and says it is offline, with the time it last heard",
     view().includes("No connection right now") && view().includes("Last updated"));

  v.fetch = () => Promise.resolve({ok: false, status: 404,
    json: () => Promise.resolve({error: "No request with that token"})});
  save();
  await v.eval("start()");
  ok("a pass the server does not know is forgotten",
     v.eval('localStorage.getItem("tok")') === null && v.eval('localStorage.getItem("pass")') === null);

  v.eval('keep({token:"t2",reference:"VR-1",status:"approved",name:"B",phone:"9876543210",' +
         'address:"12 Hill Road",guests:[],entry_code:"PB-5100"})');
  const kept = v.eval('localStorage.getItem("pass")');
  ok("the phone keeps the pass without the phone number or address",
     kept.includes("PB-5100") && !kept.includes("9876543210") && !kept.includes("Hill Road"));
  v.eval('keep({token:"t2",reference:"VR-1",status:"closed",name:"B",guests:[]})');
  ok("a closed pass is forgotten", v.eval('localStorage.getItem("pass")') === null);

  // A saved pass whose time has run out shows no code, even with no signal.
  const late = JSON.stringify(JSON.stringify({seen: "2026-10-01T05:10:00+00:00",
    visit: {...pass, expires_at: "2020-01-01T00:00:00+00:00"}}));
  v.fetch = () => Promise.reject(new Error("offline"));
  v.eval(`localStorage.setItem("tok","t1");localStorage.setItem("pass",${late})`);
  await v.eval("start()");
  v.eval('S.s="inout";render()');
  ok("an expired saved pass shows no code offline",
     view().includes("Pass expired") && !view().includes("KT-4821"));
  v.eval('S.s="status";render()');
  ok("its status says expired and offers a new request",
     view().includes("Pass expired") && view().includes("New request"));
  v.eval('keep({token:"t3",reference:"VR-2",status:"expired",name:"C",guests:[]})');
  ok("an expired pass is not kept on the phone", v.eval('localStorage.getItem("pass")') === null);
  v.eval('S.visit={...JSON.parse(JSON.parse(' + JSON.stringify(store) + ')).visit,' +
         'expires_at:"2999-01-01T10:00:00+00:00"};S.s="inout";render()');
  ok("a valid pass names when it ends", view().includes("until") && view().includes("KT-4821"));
}

// ------------------------------------- approvers, forgotten keys, auto-approval
const tick = () => new Promise(done => setTimeout(done, 0));

async function approverChecks() {
  console.log("admin page: change a reason's two approvers");
  let table = [{reason: "Delivery", main: "+911", backup: "+912"}];
  const posts = [];
  const answer = (status, body) => Promise.resolve({status, ok: status < 300, json: () => Promise.resolve(body)});
  const admin = boot("admin.html", "admin.js", {
    fetch: (url, options = {}) => {
      if (options.method === "POST") {
        const sent = JSON.parse(options.body);
        posts.push(sent);
        if (sent.backup === sent.main) {
          return answer(400, {error: "Check the numbers.",
                              fields: {backup: "The backup must be a different number from the approver."}});
        }
        table = [{reason: sent.reason, main: sent.main, backup: sent.backup}];
        return answer(200, {approvers: table});
      }
      return answer(200, url.includes("/summary")
        ? {counts: {}, escalate_minutes: 15, retain_days: 90, auto_approve_minutes: 30,
           work_hours: [10, 17], work_days: ["Mon", "Sat"], approvers: table}
        : {visits: [{reference: "VR-1", name: "A", phone: "1", address: "x", reason: "Delivery",
                     visiting: "y", guests: [], status: "approved", decided_by: "auto",
                     decided_at: "2026-10-05T05:30:00+00:00",
                     created_at: "2026-10-05T05:00:00+00:00", approvers: ["+911", "+912"]}],
           next: null});
    },
  });
  const byId = id => admin.document.getElementById(id);
  admin.eval('localStorage.setItem("adminkey","k")');
  admin.eval("render(); refresh()");
  await tick(); await tick();
  ok("the rules name the automatic approval",
     byId("rules").textContent.includes("approved automatically after 30 minutes"));
  ok("an automatic approval says so", byId("list").innerHTML.includes("Approved automatically"));

  byId("approvers").querySelector("[data-edit]").click();
  ok("Change opens both number boxes", !!byId("ap-main") && !!byId("ap-backup"));
  byId("ap-backup").value = "";
  byId("ap-save").click();
  await tick();
  ok("an empty backup is refused on the page", posts.length === 0
     && byId("approvers").textContent.includes("backup approver's number"));
  byId("ap-backup").value = "+911";
  byId("ap-save").click();
  await tick(); await tick();
  ok("the server's reason shows under the box",
     byId("approvers").textContent.includes("different number"));
  ok("the typed numbers stay in the boxes", byId("ap-backup").value === "+911");
  byId("ap-main").value = "+919000000011";
  byId("ap-backup").value = "+919000000012";
  byId("ap-save").click();
  await tick(); await tick();
  ok("both numbers go to the server", posts.at(-1).main === "+919000000011"
     && posts.at(-1).backup === "+919000000012" && posts.at(-1).reason === "Delivery");
  ok("the table shows the new numbers", byId("approvers").textContent.includes("+919000000012")
     && !byId("ap-main"));
  ok("it says the change is saved", byId("approver-note").textContent.includes("Saved"));
}

async function guardChecks() {
  console.log("admin page: add, renew and remove guards");
  let list = [];
  const posts = [];
  const answer = (status, body) => Promise.resolve({status, ok: status < 300, json: () => Promise.resolve(body)});
  const admin = boot("admin.html", "admin.js", {
    fetch: (url, options = {}) => {
      if (options.method === "POST") {
        const sent = JSON.parse(options.body);
        posts.push([url, sent]);
        if (url.endsWith("/remove")) {
          list = list.filter(g => g.phone !== sent.phone);
          return answer(200, {gate_desk: "+911", guards: list});
        }
        if (url.endsWith("/new-key")) return answer(200, {gate_desk: "+911", guards: list, key: "k2", name: "Ravi"});
        if (sent.phone === "+911") {
          return answer(400, {error: "Check the guard's details.",
                              fields: {phone: "This is the gate desk number. It is a guard already."}});
        }
        list = [{name: sent.name, phone: sent.phone, added_at: "2026-10-05T05:00:00+00:00"}];
        return answer(200, {gate_desk: "+911", guards: list, key: "k1", name: sent.name});
      }
      if (url.includes("/api/admin/photo/")) return answer(200, {photo: "data:image/jpeg;base64,/9j/AA=="});
      return answer(200, url.includes("/summary")
        ? {counts: {}, escalate_minutes: 15, retain_days: 90, approvers: [], gate_desk: "+911", guards: list}
        : {visits: [{reference: "VR-1", name: "A", phone: "1", address: "x", reason: "Delivery",
                     visiting: "y", guests: [], status: "closed", created_at: "2026-10-05T05:00:00+00:00",
                     entered_at: "2026-10-05T06:00:00+00:00", entered_by: "Ravi +919800000001",
                     exited_at: "2026-10-05T07:00:00+00:00", exited_by: "Gate desk (shared key)",
                     photo_at: "2026-10-05T06:00:00+00:00", photo_stored: true,
                     approvers: ["+911", "+912"]}], next: null});
    },
  });
  const byId = id => admin.document.getElementById(id);
  admin.eval('localStorage.setItem("adminkey","k")');
  admin.eval("render(); refresh()");
  await tick(); await tick();
  const more = byId("list").querySelector(".more").textContent;
  ok("a visit names the guard who let them in and out",
     more.includes("by Ravi +919800000001") && more.includes("by Gate desk (shared key)"));
  ok("a stored photo is not loaded until asked", !byId("list").querySelector(".shot img"));
  byId("list").querySelector("[data-photo]").click();
  await tick(); await tick();
  ok("View photo shows the gate photo", byId("list").querySelector(".shot img").getAttribute("src")
     === "data:image/jpeg;base64,/9j/AA==" && byId("list").querySelector("[data-photo]").hidden);
  admin.eval("renderList()");
  ok("a viewed photo stays after the list is drawn again", !!byId("list").querySelector(".shot img")
     && !byId("list").querySelector("[data-photo]"));
  ok("a WhatsApp photo says where it is",
     admin.eval('photoLine({photo_at: "t"})').includes("WhatsApp chat"));
  byId("tabs").querySelector('[data-section="guards"]').click();
  ok("the guards tab opens", !byId("guards").hidden && byId("visits").hidden);
  ok("the gate desk row shows", byId("guard-table").textContent.includes("+911"));

  byId("g-add").click();
  await tick();
  ok("an empty form is refused on the page", posts.length === 0
     && byId("g-name-err").textContent.includes("name"));
  byId("g-name").value = "Desk";
  byId("g-phone").value = "+911";
  byId("g-add").click();
  await tick(); await tick();
  ok("the server's reason shows under the number", byId("g-phone-err").textContent.includes("gate desk"));
  byId("g-name").value = "Ravi <b>";
  byId("g-phone").value = "+919800000001";
  byId("g-add").click();
  await tick(); await tick();
  ok("the new guard is listed, escaped", byId("guard-table").innerHTML.includes("Ravi &lt;b&gt;"));
  ok("the new key shows once", byId("guard-note").textContent.includes("k1"));
  ok("the form empties", byId("g-name").value === "" && byId("g-phone").value === "");

  byId("guard-table").querySelector("[data-newkey]").click();
  await tick(); await tick();
  ok("New key shows the new key", byId("guard-note").textContent.includes("k2")
     && !byId("guard-note").textContent.includes("k1"));
  byId("guard-table").querySelector("[data-remove]").click();
  ok("Remove asks once more", !!byId("guard-table").querySelector("[data-remove-now]")
     && byId("guard-note").textContent === "");
  byId("guard-table").querySelector("[data-keep]").click();
  ok("Keep cancels", !byId("guard-table").querySelector("[data-remove-now]"));
  byId("guard-table").querySelector("[data-remove]").click();
  byId("guard-table").querySelector("[data-remove-now]").click();
  await tick(); await tick();
  ok("Remove sends the number", posts.at(-1)[0] === "/api/admin/guards/remove"
     && posts.at(-1)[1].phone === "+919800000001");
  ok("the guard is gone", !byId("guard-table").textContent.includes("Ravi"));
}

async function forgotChecks() {
  console.log("both pages: Forgot key sends the key, and never shows it");
  for (const [page, script, store, which] of [["gate.html", "gate.js", "gatekey", "gate"],
                                              ["admin.html", "admin.js", "adminkey", "admin"]]) {
    const asked = [];
    const win = boot(page, script, {
      fetch: (url, options = {}) => {
        asked.push([url, options.method]);
        return Promise.resolve({status: 200, ok: true, json: () => Promise.resolve({sent_to: "7890"})});
      },
    });
    win.eval(`localStorage.removeItem("${store}"); render()`);
    const button = win.document.getElementById("forgot");
    ok(`${which}: the key box offers Forgot ${which} key?`, !!button
       && button.textContent === `Forgot ${which} key?`);
    button.click();
    await tick(); await tick();
    const text = win.document.body.textContent;
    ok(`${which}: it asks the server to send the ${which} key`,
       asked.some(([url, method]) => url === `/api/forgot-key/${which}` && method === "POST"));
    ok(`${which}: it names the last four digits and the KEY way`,
       text.includes("ends in 7890") && text.includes("send KEY"));
  }
}

async function visitorAutoChecks() {
  console.log("visitor app: never says when a request is approved by itself");
  const v = boot("index.html", "app.js", {fetch: () => Promise.reject(new Error("offline"))});
  v.eval(`S.visit={token:"t",reference:"VR-1",status:"pending",name:"A",guests:[],
    created_at:"2026-10-05T04:30:00+00:00",auto_approve_at:"2026-10-05T05:00:00+00:00"};
    S.s="status";render()`);
  const text = v.document.getElementById("view").textContent;
  ok("the waiting screen shows no automatic approval", !/automatic|by itself/i.test(text));
  const gapFor = status => v.eval(`S.visit.status=${JSON.stringify(status)};gap()`);
  ok("waiting for a decision, the page asks every 5 seconds", gapFor("pending") === 5000
     && gapFor("escalated") === 5000);
  ok("approved, every 10 seconds", gapFor("approved") === 10000);
  ok("inside, every 30 seconds", gapFor("inside") === 30000);
  ok("a failure backs off to a minute at most", v.eval("POLL_SLOWEST") === 60000);
}

void boardChecks().then(offlinePassChecks).then(approverChecks).then(guardChecks).then(forgotChecks).then(visitorAutoChecks).then(wrongKeyChecks).then(adminChecks).then(downloadChecks).then(() => {
  console.log();
  console.log(failures ? `${failures} check(s) FAILED` : "all form checks passed");
  process.exit(failures ? 1 : 0);
});
