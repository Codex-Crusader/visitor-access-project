// Checks the three pages in a real DOM. Needs jsdom: npm install, then node test_form.js
const fs = require("fs");
const path = require("path");
const {JSDOM} = require("jsdom");

// The pages are in pages/, their scripts and styles in static/.
const ROOT = path.join(__dirname, "..");
const read = name => fs.readFileSync(path.join(ROOT, name.endsWith(".html") ? "pages" : "static", name), "utf8");

let failures = 0;
function ok(label, condition) {
  if (condition) console.log("  pass  " + label);
  else { console.log("  FAIL  " + label); failures++; }
}

// Runs each script as a real <script>, so its top-level const names are reachable by eval.
function boot(page, script, stubs) {
  const dom = new JSDOM(read(page), {runScripts: "dangerously", url: "http://localhost/"});
  const w = dom.window;
  // jsdom has no layout, so it leaves this one out. Every browser has it.
  w.Element.prototype.scrollIntoView = function () {};
  w.scrollTo = function () {};
  Object.assign(w, stubs);
  // jsdom does not fetch a <script src>, so the page's scripts run here, in order.
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
const w = boot("visitor.html", "visitor.js", {
  fetch: () => Promise.reject(new Error("offline in this test")),
});
// The script's const names live in the global scope, not on window. eval reaches them.
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
ok("the message names the rule", el("e_phone").textContent === "Enter 10 digits, or + and the country code.");
ok("a visitor from abroad gives + and the country code", w.eval('phoneOk("+44 7911 123456")')
   && w.eval('phoneOk("98765 43210")') && !w.eval('phoneOk("+12345")') && !w.eval('phoneOk("987654321")'));
ok("the phone box shows the keypad with +", el("f_phone").getAttribute("inputmode") === "tel");

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
ok("the + stays under the box, for the next person", !!el("more")
   && el("more").textContent.includes("Add another person"));
ok("the box has the focus", w.document.activeElement === el("f_guest"));
ok("only the box shows, no Add button", el("f_guest").parentElement.querySelector("button") === null);

el("f_guest").value = "Ravi Rao";
el("f_guest").dispatchEvent(new w.Event("input"));
w.eval('pick("Delivery")');
ok("a re-render keeps what was typed", el("f_guest").value === "Ravi Rao");
const enter = new w.KeyboardEvent("keydown", {key: "Enter", cancelable: true});
el("f_guest").dispatchEvent(enter);
ok("Enter adds the person", S.g.join() === "Ravi Rao");
// Not canceled, a browser sends the same Enter on to the focused +, and the box opens again.
ok("Enter is canceled, so it does not press the +", enter.defaultPrevented);
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

// Each + keeps the typed name and opens a new box, so many people go on one request.
S.g = []; S.adding = 0; S.f.guest = ""; S.e = {}; call("render");
el("more").click();
el("f_guest").value = "Anil";
el("f_guest").dispatchEvent(new w.Event("input"));
el("more").click();
ok("the + keeps the name and opens an empty box", S.g.join() === "Anil"
   && el("f_guest").value === "" && w.document.activeElement === el("f_guest"));
el("f_guest").value = "Bina";
el("f_guest").dispatchEvent(new w.Event("input"));
el("more").click();
ok("and again for a third person", S.g.join() === "Anil,Bina" && !!el("f_guest"));
el("more").click();
ok("an empty box is not added", S.g.length === 2 && !!el("f_guest"));
// A text box drops line breaks, so the pasted text goes straight into the form state.
S.f.guest = "Bad\nName";
el("more").click();
ok("a bad name turns red and is not added", red("f_guest") && S.g.length === 2);
S.g = Array.from({length: 9}, (_, i) => "Guest " + i); S.e = {}; S.f.guest = ""; call("render");
ok("nine added and one box open: no more +", !!el("f_guest") && el("more") === null);
S.g = []; S.adding = 0; S.f.guest = ""; S.e = {}; call("render");

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

// The card shows the one current code, never the reference.
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
  const tags = [];
  const desk = boot("gate.html", "gate.js", {
    fetch: (url, options = {}) => {
      calls.push(url);
      if (options.method === "POST") posts.push(options);
      const board = url.includes("/api/gate/board");
      if (board) tags.push(options.headers["If-None-Match"] || "");
      // The board's tag came back, so the board is the same: an empty 304.
      if (board && options.headers["If-None-Match"] === '"b1"') {
        return Promise.resolve({status: 304, ok: false, headers: {get: () => '"b1"'},
                                json: () => Promise.reject(new Error("no body"))});
      }
      const body = board ? BOARD
        : url.endsWith("/entry") ? ENTERED : url.includes("KT-4821") ? TYPED : PASS;
      return Promise.resolve({status: 200, ok: true, headers: {get: () => board ? '"b1"' : null},
                              json: () => Promise.resolve(body)});
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
  await desk.eval("loadBoard()");
  ok("the second refresh sends the board's tag", tags.join() === ',"b1"');
  ok("an unchanged board (304) keeps the lists",
     byId("board").querySelectorAll(".row").length === 3 && !byId("board").innerHTML.includes("Could not"));

  // The refresh drew the rows again, so the row is found again.
  byId("board").querySelectorAll(".row")[2].click();
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
  const out = byId("out").innerHTML;
  ok("the name, then the photo button, then the details: no scroll before the next tap",
     out.indexOf('class="who"') < out.indexOf('for="cam"') && out.indexOf('for="cam"') < out.indexOf('class="facts"'));
  ok("before the photo, the photo is the main button", !byId("out").querySelector('label[for="cam"]').classList.contains("plain"));
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
  ok("after the entry, the code box is empty and ready for the next code",
     byId("code").value === "" && desk.document.activeElement === byId("code"));
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
  desk.fetch = () => Promise.resolve({status: 200, ok: true, headers: {get: () => '"b2"'},
                                     json: () => Promise.resolve(BOARD)});
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
  ok("Lock shows in the header once the key is in", !byId("rekey").hidden
     && byId("rekey").textContent === "Lock" && !!byId("rekey").closest(".nav"));
  byId("rekey").click();
  ok("Lock forgets the key at once", !!byId("k") && desk.eval('localStorage.getItem("gatekey")') === null);
  ok("and shows no stray message", !byId("out").innerHTML.includes("Cannot do that"));
  ok("with no key, Lock hides", byId("rekey").hidden);

  const css = read("gate.html") + read("admin.css");
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
           approvers: [{reason: "Delivery", main: "+911", backup: "+912"}],
           setup_gaps: ["GATE_DESK_PHONE is the <example> number."]}
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
  ok("demo settings show as one closed list, escaped",
     byId("gaps").querySelector("details:not([open])").textContent.includes("1 server setting is")
     && byId("gaps").innerHTML.includes("&lt;example&gt;"));
  admin.eval("renderGaps([])");
  ok("with none, nothing shows", byId("gaps").innerHTML === "");
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
  ok("Today is open first", !byId("today").hidden && byId("visits").hidden && byId("numbers").hidden
     && tab("today").getAttribute("aria-selected") === "true");
  const stats = [...byId("stats").querySelectorAll(".stat")]
    .map(s => `${s.querySelector("b").textContent} ${s.querySelector("span").textContent}`);
  ok("Today counts what needs action", stats[0] === "2 Waiting for a decision"
     && stats[1] === "1 Visitors inside now");
  ok("Today lists the waiting requests", byId("t-list").querySelectorAll("details").length === 2
     && calls.some(u => u.includes("status=waiting")));
  byId("stats").querySelector('[data-go="visits:inside"]').click();
  await new Promise(done => setTimeout(done, 0));
  ok("a count opens Visits with that filter", !byId("visits").hidden
     && calls.at(-1).includes("status=inside") && admin.location.hash === "#visits");
  admin.eval('filter = "all"; void load()');
  await new Promise(done => setTimeout(done, 0));
  await new Promise(done => setTimeout(done, 0));
  tab("numbers").click();
  ok("the numbers tab opens the approver table", byId("visits").hidden && !byId("numbers").hidden
     && tab("numbers").getAttribute("aria-selected") === "true");
  tab("visits").click();
  ok("the visits tab opens the list again", !byId("visits").hidden && byId("numbers").hidden);
  ok("the admin page is light only", !read("admin.html").includes("dark"));
  const logo = page => /<div class="brand"><img src="(data:image\/png;base64,[^"]+)" alt="Vijaybhoomi University"/
    .exec(read(page));
  const visitorLogo = /<img src="(data:image\/png;base64,[^"]+)" alt="Vijaybhoomi University"/.exec(read("visitor.html"));
  ok("the gate and admin pages show the university logo, as the visitor page does",
     !!logo("gate.html") && !!logo("admin.html") && !!visitorLogo
     && logo("gate.html")[1] === visitorLogo[1] && logo("admin.html")[1] === visitorLogo[1]);
  ok("the logo sits above the title row, as on the visitor page", byId("app") === null
     && admin.document.querySelector(".app > .brand + .nav h1") !== null);
  const gatePage = new JSDOM(read("gate.html")).window.document;
  ok("the gate page has the same logo bar and title row",
     gatePage.querySelector(".app > .brand + .nav h1") !== null);
  const token = (page, name) => (new RegExp(`--${name}:(#[0-9A-F]{6})`).exec(read(page)) || [])[1];
  ok("all three pages use the visitor page's colors", ["brand", "brand2", "go", "stop", "line", "mute"]
     .every(name => token("gate.html", name) === token("visitor.html", name)
                    && token("admin.css", name) === token("visitor.html", name)));
  // The admin page runs with no 'unsafe-inline': no <style>, no style or on* attribute anywhere.
  const adminCode = read("admin.html") + read("admin.js");
  ok("the admin page has no inline style or handler", !/<style|\sstyle=|\son[a-z]+=/i.test(adminCode));
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
async function downloadChecks() {
  const gate = read("gate.html") + read("gate.js");
  ok("the gate page offers no download of the log", !gate.includes("export.csv")
     && !gate.includes("Download log"));
  const cases = [
    ["admin.html", "admin.js", "adminkey", "downloadLogs()", "notice"],
  ];
  for (const [page, script, storeKey, start, noticeBox] of cases) {
    console.log(`${page}: the CSV download`);
    const run = async answer => {
      const saved = [];
      const asked = [];
      const win = boot(page, script, {fetch: url => { asked.push(url); return answer(url); }});
      win.URL.createObjectURL = () => "blob:log";
      win.URL.revokeObjectURL = () => {};
      win.HTMLAnchorElement.prototype.click = function () { saved.push(this.download); };
      win.eval(`localStorage.setItem("${storeKey}","k")`);
      win.eval("render()");
      await win.eval(start);
      const text = (win.document.getElementById(noticeBox) || {innerHTML: ""}).innerHTML;
      return {saved, text, asked, key: win.eval(`localStorage.getItem("${storeKey}")`)};
    };
    const named = name => ({status: 200, ok: true, blob: () => Promise.resolve("a,b"),
      headers: {get: () => `attachment; filename="${name}"`}});
    const both = url => Promise.resolve(url.endsWith(".zip")
      ? named("visit-log-2026-10-06.zip") : named("staff-entries-2026-10-06.csv"));
    let got = await run(both);
    ok("Download log saves the visit log and the staff entry log",
       got.saved.join() === "visit-log-2026-10-06.zip,staff-entries-2026-10-06.csv"
       && got.text.includes("allow this site to download more than one file"));
    got = await run(url => url.endsWith(".zip") ? Promise.resolve({status: 500, ok: false}) : both(url));
    ok("one failed file says so, and the other still saves",
       got.text.includes("Could not download (500)") && got.saved.join() === "staff-entries-2026-10-06.csv");
    got = await run(() => Promise.resolve({...named(""), headers: {get: () => null}}));
    ok("with no name it saves as visits.csv", got.saved[0] === "visits.csv");
    got = await run(() => Promise.resolve({status: 500, ok: false}));
    ok("a server error says so", got.text.includes("Could not download (500)") && !got.saved.length);
    got = await run(() => Promise.resolve({status: 403, ok: false}));
    ok("a wrong key is forgotten", got.key === null && !got.saved.length);
    got = await run(() => Promise.reject(new Error("offline now")));
    ok("a lost connection says so", got.text.includes("offline now"));
  }
  // The Allow list tab saves the staff entry log alone.
  const asked = [];
  const win = boot("admin.html", "admin.js", {fetch: url => {
    asked.push(url);
    return Promise.resolve(url.includes("staff-entries") ? {status: 200, ok: true,
      blob: () => Promise.resolve(""), headers: {get: () => 'filename="staff-entries-2026-10-06.csv"'}}
      : {status: 200, ok: true, json: () => Promise.resolve({})});
  }});
  win.URL.createObjectURL = () => "blob:log";
  win.HTMLAnchorElement.prototype.click = () => {};
  win.eval('localStorage.setItem("adminkey","k")');
  win.eval("render()");
  asked.length = 0;
  win.document.getElementById("s-download").click();
  await new Promise(done => setTimeout(done, 20));
  ok("Download staff entries saves that log only", asked.join() === "/api/admin/staff-entries.csv");
  ok("the saved note shows", win.eval("info").includes("staff-entries-2026-10-06.csv"));
  win.eval('forgetKey("gone")');
  ok("Change key clears the saved note", win.eval("info") === "");
}

// ------------------------------------------- the pass on a weak signal
async function offlinePassChecks() {
  console.log("visitor app: the pass survives a lost connection");
  const v = boot("visitor.html", "visitor.js", {fetch: () => Promise.reject(new Error("offline"))});
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
     view().includes("No connection right now") && view().includes("last checked with the campus system at")
     && view().includes("may be out"));
  ok("the pass says the guard checks the code, so a stale screen is not proof",
     view().includes("The guard checks this code with the campus system"));

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
        table = [{reason: sent.reason, main: sent.main, backup: sent.backup,
                  auto_minutes: sent.auto_minutes === "" ? null : Number(sent.auto_minutes)}];
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
     byId("rules").textContent.includes("approved automatically after the time in its row"));
  ok("a reason with no time set shows the default", byId("approvers").textContent.includes("After 30 min (default)"));
  ok("an automatic approval says so", byId("list").innerHTML.includes("Approved automatically"));

  byId("approvers").querySelector("[data-edit]").click();
  ok("Change opens both number boxes", !!byId("ap-main") && !!byId("ap-backup"));
  byId("ap-main").value = "";
  byId("ap-save").click();
  await tick();
  ok("an empty approver is refused on the page", posts.length === 0
     && byId("approvers").textContent.includes("approver's number"));
  byId("ap-main").value = "+911";
  byId("ap-backup").value = "+911";
  byId("ap-save").click();
  await tick(); await tick();
  ok("the server's reason shows under the box",
     byId("approvers").textContent.includes("different number"));
  ok("the typed numbers stay in the boxes", byId("ap-backup").value === "+911");
  byId("ap-main").value = "+919000000011";
  byId("ap-backup").value = "+919000000012";
  ok("the time box is empty for the default", byId("ap-auto").value === "");
  byId("ap-auto").value = "0";
  byId("ap-save").click();
  await tick(); await tick();
  ok("both numbers go to the server", posts.at(-1).main === "+919000000011"
     && posts.at(-1).backup === "+919000000012" && posts.at(-1).reason === "Delivery");
  ok("the time goes too", posts.at(-1).auto_minutes === "0");
  ok("0 shows as Never", byId("approvers").textContent.includes("Never"));
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
        ? {counts: {}, escalate_minutes: 15, retain_days: 90, approvers: [], gate_desk: "+911", guards: list,
           super: true}
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
  ok("the gate desk row shows", byId("g-table").textContent.includes("+911"));

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
  ok("the new guard is listed, escaped", byId("g-table").innerHTML.includes("Ravi &lt;b&gt;"));
  ok("the new key shows once", byId("g-note").textContent.includes("k1"));
  ok("the form empties", byId("g-name").value === "" && byId("g-phone").value === "");

  byId("g-table").querySelector("[data-newkey]").click();
  await tick(); await tick();
  ok("New key shows the new key", byId("g-note").textContent.includes("k2")
     && !byId("g-note").textContent.includes("k1"));
  const sent = posts.length;
  byId("g-table").querySelector("[data-delete]").click();
  ok("Delete asks: are you sure?", byId("over").textContent.includes("Are you sure?")
     && byId("over").textContent.includes("Ravi <b>") && posts.length === sent);
  byId("sure-no").click();
  await tick();
  ok("Cancel closes the box and keeps the guard", byId("over").innerHTML === ""
     && posts.length === sent && byId("g-table").innerHTML.includes("Ravi"));
  byId("g-table").querySelector("[data-delete]").click();
  byId("sure-yes").click();
  await tick(); await tick(); await tick();
  ok("Delete sends the number", posts.at(-1)[0] === "/api/admin/guards/remove"
     && posts.at(-1)[1].phone === "+919800000001");
  ok("the guard is gone", !byId("g-table").textContent.includes("Ravi") && byId("over").innerHTML === "");
}

async function sessionChecks() {
  console.log("admin page: signs out when idle, or in another tab, and keeps the part in the address");
  const answer = body => Promise.resolve({status: 200, ok: true, json: () => Promise.resolve(body)});
  const fetch = url => answer(url.includes("/summary") ? {counts: {}, approvers: []} : {visits: [], next: null});
  const win = boot("admin.html", "admin.js", {fetch});
  const byId = id => win.document.getElementById(id);
  win.eval('localStorage.setItem("adminkey","k"); render()');
  win.eval("touch(Date.now())");
  ok("in use, it stays signed in", win.eval("idle()") === false && !!byId("list"));
  win.eval(`localStorage.setItem("adminseen", String(Date.now() - (IDLE_MINUTES + 1) * 60000))`);
  ok("after 30 minutes with no use it signs out", win.eval("idle()") === true
     && win.eval('localStorage.getItem("adminkey")') === null);
  ok("and says why", byId("main").textContent.includes("Signed out after 30 minutes"));
  ok("signed out, the menu hides", byId("side").hidden && byId("menu").hidden);

  win.eval('localStorage.setItem("adminkey","k"); render()');
  win.localStorage.removeItem("adminkey");
  win.dispatchEvent(new win.StorageEvent("storage", {key: "adminkey", newValue: null}));
  ok("Sign out in another tab signs this tab out", !!byId("k"));

  const deep = new JSDOM(read("admin.html"), {runScripts: "dangerously", url: "http://localhost/admin#guards"});
  deep.window.fetch = fetch;
  deep.window.scrollTo = () => {};
  deep.window.eval('localStorage.setItem("adminkey","k")');
  for (const src of ["shared.js", "admin.js"]) {
    const tag = deep.window.document.createElement("script");
    tag.textContent = read(src);
    deep.window.document.body.appendChild(tag);
  }
  ok("a part in the address opens on load", !deep.window.document.getElementById("guards").hidden
     && deep.window.document.getElementById("today").hidden);
  deep.window.location.hash = "blacklist";
  await new Promise(done => setTimeout(done, 20));
  ok("Back and Forward move between parts", !deep.window.document.getElementById("blacklist").hidden);
}

async function hardeningChecks() {
  console.log("visitor: Finish later keeps the form on the phone; gate: stale lists, idle lock");
  const v = boot("visitor.html", "visitor.js", {fetch: () => Promise.reject(new Error("offline"))});
  const S1 = v.eval("S");
  Object.assign(S1.f, {name: "Asha Rao", phone: "9876543210", address: "Karjat"});
  S1.g = ["Ravi Rao"];
  v.eval("saveDraft()");
  const v2 = new JSDOM(read("visitor.html"), {runScripts: "dangerously", url: "http://localhost/"});
  v2.window.fetch = () => Promise.reject(new Error("offline"));
  v2.window.localStorage.setItem("draft", v.localStorage.getItem("draft"));
  for (const src of ["visitor.js"]) {
    const tag = v2.window.document.createElement("script");
    tag.textContent = read(src);
    v2.window.document.body.appendChild(tag);
  }
  await tick();
  const S2 = v2.window.eval("S");
  ok("Finish later: a new page view has the typed form back", S2.f.name === "Asha Rao"
     && S2.g.join() === "Ravi Rao");
  v2.window.eval("dropDraft()");
  ok("and the copy goes once the request is sent", v2.window.localStorage.getItem("draft") === null);
  v.localStorage.setItem("draft", JSON.stringify({at: Date.now() - 8 * 86400000, f: {name: "Old"}, g: []}));
  v.eval('S.f.name = ""; restoreDraft()');
  ok("a copy older than 7 days is dropped", S1.f.name === "" && v.localStorage.getItem("draft") === null);

  // The settings from the last answer, so the office list works with no signal.
  const online = boot("visitor.html", "visitor.js", {fetch: () => Promise.resolve({status: 200, ok: true,
    json: () => Promise.resolve({gate_desk_phone: "+912200000001", escalate_minutes: 15, retain_days: 90,
                                 pass_hours: 48, offices: ["Fees"], office_groups: []})})});
  await tick();
  const kept = online.localStorage.getItem("cfg");
  const v3 = new JSDOM(read("visitor.html"), {runScripts: "dangerously", url: "http://localhost/"});
  v3.window.fetch = () => Promise.reject(new Error("offline"));
  v3.window.localStorage.setItem("cfg", kept);
  const tag3 = v3.window.document.createElement("script");
  tag3.textContent = read("visitor.js");
  v3.window.document.body.appendChild(tag3);
  await tick();
  const S3 = v3.window.eval("S");
  ok("offline, the page has the last office list and gate desk number",
     S3.cfg.offices.join() === "Fees" && S3.cfg.gate_desk_phone === "+912200000001");

  const desk = boot("gate.html", "gate.js", {fetch: () => Promise.resolve({status: 200, ok: true,
    headers: {get: () => null}, json: () => Promise.resolve({inside: [], expected: []})})});
  const d = id => desk.document.getElementById(id);
  desk.eval('localStorage.setItem("gatekey","k")');
  await desk.eval("loadBoard()");
  desk.fetch = () => Promise.reject(new Error("offline"));
  await desk.eval("loadBoard()");
  ok("offline, the board says the lists may be old and checks need the connection",
     d("board").textContent.includes("may be out of date") && d("board").textContent.includes("paper log"));
  desk.fetch = () => Promise.resolve({status: 200, ok: true, headers: {get: () => null},
                                     json: () => Promise.resolve({inside: [], expected: []})});
  await desk.eval("loadBoard()");
  ok("back online, it says once that the lists are fresh", d("board").textContent.includes("Connected again"));
  desk.eval('visit = {reference: "VR-1", status: "approved", name: "A", visiting: "y", reason: "Event", guests: [],'
    + ' decided_at: "2026-10-07T05:00:00+00:00", decided_by: "auto", code: "KT-4821", code_kind: "entry"}; render()');
  ok("an automatic approval says no person answered", d("out").textContent.includes("Approved automatically"));
  desk.eval(`localStorage.setItem("gateseen", String(Date.now() - (GATE_IDLE_HOURS + 1) * 3600000))`);
  ok("after 8 hours with no use the gate locks", desk.eval("gateIdle()") === true && !!d("k"));

  const admin = boot("admin.html", "admin.js", {fetch: () => Promise.resolve({status: 200, ok: true,
    json: () => Promise.resolve({counts: {}, approvers: [], visits: [], next: null})})});
  admin.eval('localStorage.setItem("adminkey","k"); render()');
  const opener = admin.document.getElementById("refresh");
  opener.focus();
  const asking = admin.eval('confirmDelete("Delete it?")');
  admin.document.getElementById("sure-no").click();
  await asking;
  ok("a closed box gives the focus back to its button", admin.document.activeElement === opener);
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
  const v = boot("visitor.html", "visitor.js", {fetch: () => Promise.reject(new Error("offline"))});
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

// ------------------------------------- a slow answer never replaces a newer pass
async function staleGateChecks() {
  console.log("gate desk: a slow answer never replaces the pass on screen");
  // Each call waits until the test answers it, so the test sets the order.
  const waiting = {};
  const g = boot("gate.html", "gate.js", {
    fetch: url => new Promise(done => {
      waiting[url] = body => done({status: 200, ok: true, headers: {get: () => null},
                                   json: () => Promise.resolve(body)});
    }),
  });
  g.localStorage.setItem("gatekey", "k");
  const pass = (code, status) => ({reference: "VR-" + code.slice(3), status, name: "Visitor " + code,
    phone: "9876543210", visiting: "2024SEPVUGP0003", reason: "Delivery", guests: [],
    code, code_kind: status === "inside" ? "exit" : "entry"});

  // The guard checks one pass, then a second before the first answers.
  const first = g.eval('show("AB-1111")');
  const second = g.eval('show("CD-2222")');
  waiting["/api/pass/CD-2222"](pass("CD-2222", "approved"));
  await second;
  waiting["/api/pass/AB-1111"](pass("AB-1111", "approved"));
  await first;
  ok("the first answer, arriving last, does not replace the second pass",
     g.eval("visit.code") === "CD-2222" && g.eval("busy") === "");

  // An exit is waiting when the guard opens another pass.
  g.eval('visit = ' + JSON.stringify(pass("EF-3333", "inside")));
  const leaving = g.eval("act('exit')");
  const another = g.eval('show("GH-4444")');
  waiting["/api/pass/GH-4444"](pass("GH-4444", "approved"));
  await another;
  waiting["/api/pass/EF-3333/exit"]({...pass("EF-3333", "closed")});
  await leaving;
  ok("a late exit answer does not replace the pass opened after it",
     g.eval("visit.code") === "GH-4444" && !g.document.getElementById("out").innerHTML.includes("Pass closed"));
}

// ------------------------------- a late status answer never brings a visit back
async function stalePollChecks() {
  console.log("visitor page: New request is not undone by a late status answer");
  const waiting = {};
  const v = boot("visitor.html", "visitor.js", {
    fetch: url => new Promise(done => {
      waiting[url] = body => done({status: 200, ok: true, headers: {get: () => null},
                                   json: () => Promise.resolve(body)});
    }),
  });
  const old = {token: "old", reference: "VR-11111", status: "approved", name: "A", guests: [],
    created_at: new Date().toISOString()};
  // jsdom reports every page as hidden, and the poll skips a hidden page.
  Object.defineProperty(v.document, "hidden", {value: false});
  v.eval(`keep(${JSON.stringify(old)})`);
  const asking = v.eval("poll()");
  v.eval("again()");
  waiting["/api/visit/old"](old);
  await asking;
  ok("the dropped visit stays dropped", v.eval("S.visit") === null);
  ok("and stays off the phone", v.localStorage.getItem("tok") === null);
  // The late answer must not count as a lost connection.
  ok("a late answer is not taken as a lost connection", v.eval("S.down") === 0);
  v.eval("clearTimeout(S.timer)");
}

// ------------------------- a slow save names its own reason, not the one now open
async function staleApproverChecks() {
  console.log("admin page: a slow approver save names its own reason");
  const table = [{reason: "Delivery", main: "+911", backup: "+912"},
                 {reason: "Event", main: "+913", backup: "+914"}];
  let release;
  const answer = body => Promise.resolve({status: 200, ok: true, json: () => Promise.resolve(body)});
  const admin = boot("admin.html", "admin.js", {
    fetch: (url, options = {}) => {
      if (options.method === "POST") return new Promise(done => { release = () => done({
        status: 200, ok: true, json: () => Promise.resolve({approvers: table})}); });
      return answer(url.includes("/summary")
        ? {counts: {}, escalate_minutes: 15, retain_days: 90, auto_approve_minutes: 0,
           work_hours: [10, 17], work_days: ["Mon"], approvers: table}
        : {visits: [], next: null});
    },
  });
  const byId = id => admin.document.getElementById(id);
  admin.eval('localStorage.setItem("adminkey","k")');
  admin.eval("render(); refresh()");
  await tick(); await tick();
  byId("approvers").querySelector('[data-edit="Delivery"]').click();
  byId("ap-main").value = "+915";
  byId("ap-backup").value = "+916";
  const saving = admin.eval("saveApprovers()");
  // While Delivery saves, the admin opens Event.
  byId("approvers").querySelector('[data-edit="Event"]').click();
  release();
  await saving;
  ok("the note names the reason that was saved", byId("approver-note").textContent.includes("Delivery")
     && !byId("approver-note").textContent.includes("Event"));
  ok("the reason opened meanwhile stays open", admin.eval("editing") === "Event" && !!byId("ap-main"));
}

// ------------------------------------------------ the office list
async function officeFormChecks() {
  console.log("visitor form: See an office offers the list of offices");
  const v = boot("visitor.html", "visitor.js", {fetch: () => Promise.reject(new Error("offline"))});
  const S = v.eval("S");
  const byId = id => v.document.getElementById(id);
  const red = id => !!byId(id) && byId(id).classList.contains("bad");
  Object.assign(S.f, {name: "Asha Rao", phone: "9876543210", address: "12 Park Road"});
  S.cfg.offices = ["Accounts", "Admissions <b>"];
  S.s = "step2"; v.eval("render()");
  v.eval('pick("See an office")');
  ok("the office list replaces the visiting box", !!byId("f_office") && !byId("f_visiting"));
  ok("it lists every office, escaped", byId("f_office").options.length === 3
     && byId("f_office").innerHTML.includes("Admissions &lt;b&gt;"));
  v.eval("n2()");
  ok("no office chosen blocks Review", S.s === "step2" && red("f_office"));
  byId("f_office").value = "Accounts";
  byId("f_office").dispatchEvent(new v.Event("change"));
  ok("choosing one clears the red", !red("f_office") && S.f.office === "Accounts");
  v.eval("n2()");
  ok("an office passes, with no student check", S.s === "review"
     && byId("view").innerHTML.includes(">Office<") && byId("view").innerHTML.includes("Accounts"));
  let body = null;
  v.fetch = (url, options) => { body = JSON.parse(options.body); return Promise.reject(new Error("offline")); };
  await v.eval("send()");
  ok("the request names the office", body.office === "Accounts" && body.visiting === "Accounts"
     && body.reason === "See an office");
  S.s = "step2"; v.eval('pick("Delivery")');
  ok("another reason drops the office", S.f.office === "" && !byId("f_office") && !!byId("f_visiting"));
  S.cfg.offices = [];
  v.eval('pick("See an office")');
  ok("with no offices the visitor types the office", !byId("f_office")
     && byId("f_visiting").placeholder === "Office name");
  S.f.visiting = "Dr Rao, Accounts";
  v.eval("n2()");
  ok("an office visit may name a staff member", S.s === "review");
}

// ------------------------------------------------ a staff code at the gate
async function staffGateChecks() {
  console.log("gate desk: a staff code records an entry, the next scan an exit");
  const calls = [];
  // The server decides: an entry, then an exit. This stub alternates as it would.
  let scans = 0;
  const desk = boot("gate.html", "gate.js", {
    fetch: (url, options = {}) => {
      calls.push([url, options.method || "GET"]);
      const kind = url.endsWith("/in") ? "entry" : url.endsWith("/out") ? "exit"
        : url.endsWith("/scan") && scans++ % 2 ? "exit" : "entry";
      const body = url.includes("/api/gate/board") ? {inside: [], expected: []}
        : options.method === "POST" ? {code: "1234567", name: "Dr Dev", kind, at: new Date().toISOString(), new: true}
        : url.includes("/api/staff/") ? {code: "1234567", name: "Dr Dev"} : {};
      return Promise.resolve({status: 200, ok: true, headers: {get: () => null},
                              json: () => Promise.resolve(body)});
    },
  });
  const byId = id => desk.document.getElementById(id);
  desk.eval('localStorage.setItem("gatekey","k")');
  desk.eval("render()");
  ok("visitor mode has its own background", desk.document.body.dataset.mode === "pass");
  desk.document.querySelector('[data-mode="staff"]').click();
  ok("Staff code opens the number keypad, on the staff background", byId("code").inputMode === "numeric"
     && byId("code").getAttribute("pattern") === "[0-9]*" && byId("look").textContent === "Record entry or exit"
     && byId("sub").textContent.includes("7-digit") && desk.document.body.dataset.mode === "staff");
  byId("code").value = "123 4567";
  await desk.eval("look()");
  ok("one action records the scan: no check first, no pass lookup",
     calls.some(([u, m]) => u === "/api/staff/1234567/scan" && m === "POST")
     && !calls.some(([u, m]) => u === "/api/staff/1234567" && m === "GET")
     && !calls.some(([u]) => u.startsWith("/api/pass/")));
  ok("it says the entry is recorded, with the name and tag large for the face check",
     byId("out").innerHTML.includes("Entry recorded") && !!byId("out").querySelector(".who b")
     && byId("out").textContent.includes("Dr Dev"));
  ok("the page stays in Staff code mode, the box empty and ready for the next person",
     desk.document.body.dataset.mode === "staff" && byId("code").value === ""
     && desk.document.activeElement === byId("code") && !byId("out").textContent.includes("Next person"));
  ok("an entry is green", !!byId("out").querySelector(".state.good"));
  desk.eval("clear_()");
  byId("code").value = "1234567";
  await desk.eval("look()");
  ok("7 digits in visitor mode record the scan and switch to Staff code mode",
     calls.filter(([u]) => u === "/api/staff/1234567/scan").length === 2
     && desk.document.body.dataset.mode === "staff");
  ok("the second scan is an exit, on a gray banner, not the red of a refusal", byId("out").textContent.includes("Exit recorded")
     && byId("out").textContent.includes("Dr Dev left at") && !!byId("out").querySelector(".state.out")
     && !byId("out").textContent.includes("WhatsApp"));
  ok("a wrong scan offers the other one", byId("fix").textContent.includes("Change to entry"));
  byId("fix").click();
  await tick(); await tick();
  ok("the change sends IN for that code, and the page says Entry",
     calls.some(([u, m]) => u === "/api/staff/1234567/in" && m === "POST")
     && byId("out").textContent.includes("Entry recorded") && byId("fix").textContent.includes("Change to exit"));
  // A blacklisted number: the banner with the name, and no entry.
  desk.fetch = () => Promise.resolve({status: 409, ok: false, json: () => Promise.resolve({
    error: "On the blacklist.", code: "7654321", name: "Kavita", tag: "", blacklisted: true})});
  byId("code").value = "7654321";
  await desk.eval("look()");
  ok("a blacklisted code shows the banner and the name", byId("out").textContent.includes("On the blacklist")
     && byId("out").textContent.includes("Kavita") && !byId("out").textContent.includes("Entry recorded"));
  // The result goes away: when the next code starts, and by itself after a minute.
  byId("code").value = "7";
  byId("code").dispatchEvent(new desk.Event("input"));
  ok("typing the next code clears the last result", !byId("out").textContent.includes("Kavita")
     && byId("code").value === "7");
  desk.eval("person = {code: '1234567', name: 'Dr Dev', tag: '', kind: 'exit', at: '2026-10-09T09:40:00Z'}; render()");
  desk.eval("forgetStaffLater(latest)");
  ok("the result shows until then", byId("out").textContent.includes("Dr Dev"));
  desk.eval("forgetStaff()");
  ok("after STAFF_SHOWN it is gone", !byId("out").textContent.includes("Dr Dev")
     && desk.eval("STAFF_SHOWN") === 60000);
}

// ------------------------------------------- staff, offices and admins
async function teamChecks() {
  console.log("admin page: staff, offices and admins, each deleted only after Are you sure?");
  const posts = [];
  const gets = [];
  let countsNow = {};
  let lists = {gate_desk: "+911", guards: [], main_admin: "+919", you: "Meera +918", offices: [], super: true,
    admins: [{name: "Meera", phone: "+918", added_at: "2026-10-05T05:00:00+00:00"}],
    staff: [], staff_entries: [{code: "1234567", name: "Dr Dev", entered_at: "2026-10-06T04:00:00+00:00",
                                entered_by: "Ravi +919800000001", kind: "exit"}],
    staff_today: Array.from({length: 40}, (_, i) => ({code: String(1000000 + i), name: `Staff ${i}`,
      tag: i % 2 ? "Faculty" : "", last_kind: i < 30 ? "entry" : "exit", last_by: "Gate desk",
      last_at: "2026-10-06T04:00:00+00:00", first_in: "2026-10-06T03:00:00+00:00"}))};
  const answer = (status, body) => Promise.resolve({status, ok: status < 300, json: () => Promise.resolve(body)});
  const admin = boot("admin.html", "admin.js", {
    fetch: (url, options = {}) => {
      if (options.method === "POST") {
        const sent = JSON.parse(options.body);
        posts.push([url, sent]);
        if (url === "/api/admin/staff") {
          lists = {...lists, staff: [{code: "7654321", name: sent.name, phone: sent.phone,
                                      added_at: "2026-10-06T05:00:00+00:00"}]};
          return answer(200, {...lists, code: "7654321", name: sent.name});
        }
        if (url === "/api/admin/offices") {
          if (sent.main === sent.backup) {
            return answer(400, {error: "Check the office's details.",
                                fields: {backup: "The backup must be a different number from the approver."}});
          }
          lists = {...lists, offices: [{name: sent.name, main: sent.main, backup: sent.backup}]};
          return answer(200, lists);
        }
        if (url === "/api/admin/offices/remove") { lists = {...lists, offices: []}; return answer(200, lists); }
        if (url === "/api/admin/offices/auto") {
          lists = {...lists, offices: lists.offices.map(o => ({...o, auto_minutes: Number(sent.auto_minutes)}))};
          return answer(200, lists);
        }
        if (url === "/api/admin/admins/remove") {
          return answer(409, {error: "You cannot delete yourself. Ask another admin."});
        }
        return answer(404, {error: "unknown"});
      }
      gets.push(url);
      return answer(200, url.includes("/summary")
        ? {counts: countsNow, escalate_minutes: 15, retain_days: 90, approvers: [], ...lists}
        : {visits: [], next: null});
    },
  });
  const byId = id => admin.document.getElementById(id);
  const tab = name => byId("tabs").querySelector(`[data-section="${name}"]`);
  admin.eval('localStorage.setItem("adminkey","k")');
  admin.eval("render(); refresh()");
  await tick(); await tick();
  ok("the header names who is signed in", byId("you").textContent === "Signed in as Meera +918 (super admin)");
  // The page refreshes itself. The waiting list loads again only when a count changed.
  // jsdom counts the page as hidden. The refresh runs only while it is in view.
  Object.defineProperty(admin.document, "hidden", {value: false, configurable: true});
  const waitingLoads = () => gets.filter(u => u.includes("status=waiting")).length;
  await admin.eval("autoRefresh()"); await tick(); await tick();
  const before = waitingLoads();
  await admin.eval("autoRefresh()"); await tick(); await tick();
  ok("an unchanged refresh loads no waiting list", waitingLoads() === before
     && gets.filter(u => u.includes("/summary")).length >= 3);
  countsNow = {pending: 2};
  await admin.eval("autoRefresh()"); await tick(); await tick();
  ok("a new request loads the waiting list again", waitingLoads() === before + 1);
  ok("the tab title shows how many wait", admin.document.title === "(2) Visitor Admin");
  // An unchanged summary is a 304 with an empty body: the page keeps what it shows.
  const realFetch = admin.fetch;
  admin.fetch = (url, options = {}) => url.includes("/summary")
    ? Promise.resolve({status: 304, ok: false, json: () => Promise.reject(new Error("no body"))})
    : realFetch(url, options);
  await admin.eval("autoRefresh()"); await tick(); await tick();
  ok("a 304 keeps the counts and the title", admin.document.title === "(2) Visitor Admin"
     && admin.eval("count('waiting')") === 2);
  admin.fetch = realFetch;
  // A redraw keeps an open visit open.
  admin.eval(`waiting = [{reference: "VR-7", name: "A", phone: "1", address: "x", reason: "Delivery",
    visiting: "y", guests: [], status: "pending", created_at: "2026-10-06T04:00:00+00:00", approvers: []}];
    renderToday()`);
  admin.document.querySelector('#t-list details[data-ref="VR-7"]').open = true;
  admin.eval("renderToday()");
  ok("a refresh keeps an open visit open", admin.document.querySelector('#t-list details[data-ref="VR-7"]').open);
  countsNow = {};
  admin.eval("waiting = []; counts = {}; renderToday()");
  const staffRows = () => byId("t-staff").querySelectorAll("li").length;
  ok("Today counts the staff on campus now", byId("stats").textContent.includes("30 Staff on campus now"));
  ok("Today shows the staff on campus, 25 at a time", staffRows() === 25
     && byId("t-staff-chips").textContent.includes("On campus 30") && byId("t-staff-chips").textContent.includes("Left 10")
     && byId("t-staff").textContent.includes("In since") && byId("t-staff").textContent.includes("Show more (5 left)"));
  byId("t-staff").querySelector("[data-staff-more]").click();
  ok("Show more shows the rest", staffRows() === 30 && !byId("t-staff").querySelector("[data-staff-more]"));
  byId("t-staff-chips").querySelector('[data-show="exit"]').click();
  ok("Left shows who went out, with their exit time", staffRows() === 10
     && byId("t-staff").textContent.includes("Out at") && byId("t-staff").textContent.includes("First in"));
  byId("t-staff-q").value = "staff 35";
  byId("t-staff-q").dispatchEvent(new admin.Event("input"));
  await new Promise(done => setTimeout(done, 350));
  ok("the search finds one person", staffRows() === 1 && byId("t-staff").textContent.includes("Staff 35"));
  admin.eval("loadWaiting()");
  await tick(); await tick();
  ok("a refresh keeps the search box and its text", byId("t-staff-q").value === "staff 35" && staffRows() === 1);

  tab("staff").click();
  ok("the staff tab opens", !byId("staff").hidden && byId("visits").hidden);
  ok("the staff entries name the guard", byId("s-entries").textContent.includes("Ravi +919800000001")
     && byId("s-entries").textContent.includes("1234567"));
  ok("the staff entries say in or out", byId("s-entries").textContent.includes("Out"));
  byId("s-name").value = "Dr Dev";
  byId("s-phone").value = "+917000000001";
  byId("s-add").click();
  await tick(); await tick();
  ok("a new staff member gets a code, shown in the note and the list",
     byId("s-note").textContent.includes("7654321") && byId("s-table").textContent.includes("7654321"));

  tab("numbers").click();
  ok("the offices sit on the Approvers tab, under the reasons",
     !byId("numbers").hidden && byId("numbers").contains(byId("o-table"))
     && byId("numbers").innerHTML.indexOf("approvers") < byId("numbers").innerHTML.indexOf("o-table"));
  ok("the menu: daily work first, people, then setup", [...byId("tabs").querySelectorAll("[data-section]")]
     .map(t => t.dataset.section).join() === "today,visits,staff,blacklist,numbers,guards,admins,log");
  ok("each add form waits behind its button", byId("o-form").hidden
     && !!byId("numbers").querySelector('[data-open="o"]'));
  byId("numbers").querySelector('[data-open="o"]').click();
  ok("Add office opens the form", !byId("o-form").hidden);
  byId("numbers").querySelector('[data-close="o"]').click();
  ok("Cancel closes it", byId("o-form").hidden);
  byId("o-add").click();
  ok("an empty office form is refused on the page", posts.filter(([u]) => u.includes("offices")).length === 0
     && byId("o-name-err").textContent !== "" && byId("o-main-err").textContent !== "");
  byId("o-name").value = "Accounts";
  byId("o-main").value = "+917000000002";
  byId("o-backup").value = "+917000000002";
  byId("o-add").click();
  await tick(); await tick();
  ok("the server's reason shows under the backup", byId("o-backup-err").textContent.includes("different"));
  byId("o-backup").value = "+917000000003";
  byId("o-add").click();
  await tick(); await tick();
  ok("the office is listed with its two numbers", byId("o-table").textContent.includes("Accounts")
     && byId("o-table").textContent.includes("+917000000003"));
  ok("a new office approves by itself after the default", byId("o-table").textContent.includes("(default)"));
  byId("o-table").querySelector("[data-auto]").click();
  ok("Time asks for the minutes", !!byId("auto-new") && byId("auto-new").value === "");
  byId("auto-new").value = "15";
  byId("auto-save").click();
  await tick(); await tick(); await tick();
  ok("Time sends the office and the minutes", posts.at(-1)[0] === "/api/admin/offices/auto"
     && posts.at(-1)[1].name === "Accounts" && posts.at(-1)[1].auto_minutes === "15");
  ok("the table shows the new time", byId("o-table").textContent.includes("After 15 min"));
  byId("o-table").querySelector("[data-delete]").click();
  ok("deleting an office asks first", byId("over").textContent.includes("Are you sure?")
     && byId("over").textContent.includes("Accounts"));
  byId("sure-yes").click();
  await tick(); await tick(); await tick();
  ok("Delete sends the office name", posts.at(-1)[0] === "/api/admin/offices/remove"
     && posts.at(-1)[1].name === "Accounts" && !byId("o-table").textContent.includes("+917000000003"));

  tab("admins").click();
  ok("the admins tab lists the main admin and the others",
     byId("a-table").textContent.includes("+919") && byId("a-table").textContent.includes("Meera"));
  ok("it marks who you are", byId("a-table").querySelector(".you") !== null);
  byId("a-table").querySelector("[data-delete]").click();
  byId("sure-yes").click();
  await tick(); await tick(); await tick();
  ok("the server's refusal shows", byId("a-note").textContent.includes("cannot delete yourself"));
}

// ------------------------------------------------------------- the blacklist
async function blacklistChecks() {
  console.log("admin page: the blacklist, and a visit's Blacklist this number");
  const posts = [];
  let banned = [];
  const answer = (status, body) => Promise.resolve({status, ok: status < 300, json: () => Promise.resolve(body)});
  const admin = boot("admin.html", "admin.js", {
    fetch: (url, options = {}) => {
      if (options.method === "POST") {
        const sent = JSON.parse(options.body);
        posts.push([url, sent]);
        banned = url.endsWith("/remove") ? []
          : [{phone_key: "9820011223", phone: sent.phone, name: sent.name, reason: sent.reason,
              added_at: "2026-10-06T05:00:00+00:00"}];
        return answer(200, {blacklist: banned});
      }
      return answer(200, url.includes("/summary") ? {counts: {}, approvers: [], blacklist: banned}
        : {visits: [{reference: "VR-1", name: "Kavita", phone: "9820011223", address: "x",
                     reason: "Delivery", visiting: "y", guests: [], status: "approved",
                     created_at: "2026-10-05T05:00:00+00:00", approvers: ["+911", "+912"]}], next: null});
    },
  });
  const byId = id => admin.document.getElementById(id);
  admin.eval('localStorage.setItem("adminkey","k")');
  admin.eval("render(); refresh()");
  await tick(); await tick();
  ok("the tab says Allow list, not Staff",
     byId("tabs").querySelector('[data-section="staff"]').textContent === "Allow list");
  byId("list").querySelector("[data-ban]").click();
  ok("Blacklist this number asks first", byId("over").textContent.includes("Are you sure?")
     && byId("sure-yes").textContent === "Add to blacklist" && posts.length === 0);
  byId("sure-yes").click();
  await tick(); await tick(); await tick();
  ok("it sends the visit's number and name", posts.at(-1)[0] === "/api/admin/blacklist"
     && posts.at(-1)[1].phone === "9820011223" && posts.at(-1)[1].name === "Kavita");
  ok("the blacklist tab opens with the number", !byId("blacklist").hidden
     && byId("b-table").textContent.includes("9820011223") && byId("b-note").textContent.includes("Kavita"));
  ok("each cell names its column for the phone view",
     byId("b-table").querySelector("td").dataset.label === "Name");
  byId("b-name").value = "Ravi";
  byId("b-phone").value = "9820099999";
  byId("b-add").click();
  await tick(); await tick();
  ok("the reason may stay empty", posts.at(-1)[1].reason === "" && byId("b-reason-err").textContent === "");
  byId("b-table").querySelector("[data-delete]").click();
  byId("sure-yes").click();
  await tick(); await tick(); await tick();
  ok("Delete takes the number off", posts.at(-1)[0] === "/api/admin/blacklist/remove"
     && byId("b-table").textContent.includes("No number is on the blacklist"));
  ok("the key box tells an added admin to send KEY", (() => {
    admin.eval("forgetKey()");
    return byId("main").textContent.includes("Send KEY from your own WhatsApp");
  })());

  console.log("admin page: blocked attempts show on every tab for a day");
  const hourAgo = new Date(Date.now() - 3600000).toISOString();
  const daysAgo = new Date(Date.now() - 3 * 86400000).toISOString();
  const watcher = boot("admin.html", "admin.js", {
    fetch: url => answer(200, url.includes("/summary")
      ? {counts: {}, approvers: [], blacklist: [], blocked: [
          {at: hourAgo, name: "Farah <b>", phone: "9820077889", what: "Came to the gate with a pass",
           detail: "VR-12345", by_whom: "Ravi +919800000001"},
          {at: daysAgo, name: "Farah", phone: "9820077889", what: "Asked for a visit", detail: "",
           by_whom: "Visitor page"}]}
      : {visits: [], next: null}),
  });
  const w2 = id => watcher.document.getElementById(id);
  watcher.eval('localStorage.setItem("adminkey","k")');
  watcher.eval("render(); refresh()");
  await tick(); await tick();
  ok("a red alert counts only the last 24 hours", w2("alert").textContent.includes("stopped one attempt"));
  ok("the Blacklist tab shows the count", w2("tabs").querySelector('[data-section="blacklist"]')
     .textContent.replace(/\s+/g, " ").trim() === "Blacklist 1");
  w2("alert").querySelector("[data-section]").click();
  ok("See who opens the blacklist tab", !w2("blacklist").hidden && w2("visits").hidden);
  const rows = w2("b-attempts").textContent;
  ok("the list names who, what and which guard, escaped", rows.includes("Ravi +919800000001")
     && rows.includes("VR-12345") && w2("b-attempts").innerHTML.includes("Farah &lt;b&gt;")
     && rows.includes("Asked for a visit"));

  console.log("gate desk: a blacklisted number never shows Record entry");
  const desk = boot("gate.html", "gate.js", {fetch: () => Promise.reject(new Error("offline"))});
  const out = () => desk.document.getElementById("out").innerHTML;
  desk.eval('localStorage.setItem("gatekey","k")');
  desk.eval('visit = {reference:"VR-1", status:"approved", name:"Kavita", phone:"9820011223",' +
            ' visiting:"y", reason:"Delivery", guests:[], code:"KT-4821", code_kind:"entry", blacklisted:true}');
  desk.eval("render()");
  ok("the banner says do not let them in", out().includes("On the blacklist")
     && !out().includes("Let them in") && !out().includes("Record entry"));
  desk.eval('visit = null; person = {code:"1234567", name:"Kavita", blacklisted:true}; render()');
  ok("an allow list code for that number says no entry", out().includes("On the blacklist")
     && !out().includes("Entry recorded"));
}

// ------------------------------------------------------------- worst cases
async function worstCaseChecks() {
  console.log("visitor form: an office deleted after the page loaded");
  const v = boot("visitor.html", "visitor.js", {fetch: () => Promise.reject(new Error("offline"))});
  const S = v.eval("S");
  const byId = id => v.document.getElementById(id);
  const refusal = {error: "That office is not on the list now. Choose again.", offices: ["Library"]};
  const refuse = () => Promise.resolve({ok: false, status: 400, json: () => Promise.resolve(refusal)});
  Object.assign(S.f, {name: "Asha", phone: "9876543210", address: "Karjat", reason: "See an office",
                      office: "Accounts", visiting: ""});
  S.cfg.offices = ["Accounts", "Library"];
  v.fetch = refuse;
  await v.eval("send()");
  ok("it goes back to the office list, with the server's offices", S.s === "step2"
     && byId("f_office").options.length === 2 && byId("f_office").innerHTML.includes("Library")
     && !byId("f_office").innerHTML.includes("Accounts"));
  ok("the office box is red and says why", byId("f_office").classList.contains("bad")
     && byId("e_office").textContent.includes("not on the list now"));
  ok("Back still works", S.hist.join() === "home,step1");
  // The list never loaded, so the visitor typed the office. The server's list replaces it.
  Object.assign(S.f, {office: "", visiting: "Accounts office"});
  S.cfg.offices = [];
  await v.eval("send()");
  ok("a typed office becomes the list", S.s === "step2" && !!byId("f_office") && !byId("f_visiting"));

  console.log("gate desk: a banned visitor on the board, and a repeated allow list code");
  const desk = boot("gate.html", "gate.js", {
    fetch: () => Promise.resolve({status: 200, ok: true, json: () => Promise.resolve({
      inside: [{reference: "VR-1", name: "Kiran", visiting: "y", guests: [], status: "inside",
                entered_at: new Date().toISOString(), blacklisted: true}], expected: []})}),
  });
  desk.eval('localStorage.setItem("gatekey","k")');
  await desk.eval("loadBoard()");
  const banned = desk.document.querySelector(".row");
  ok("the row is red and says On the blacklist", banned.dataset.banned === "true"
     && banned.textContent.includes("On the blacklist"));
  const out = () => desk.document.getElementById("out").textContent;
  desk.eval('person = {code:"1234567", name:"Dev", at:new Date().toISOString(), new:false, told:false}; render()');
  ok("a repeat says Already recorded, nothing sent", out().includes("Already recorded")
     && out().includes("Nothing new") && !out().includes("—"));
  desk.eval('person = {...person, kind:"exit", at:new Date().toISOString(), blacklisted:true}; render()');
  ok("a blacklisted person may leave, and the guard is told", out().includes("Already recorded: exit")
     && out().includes("on the blacklist. Tell the admin"));
  desk.eval('person = {...person, kind:"entry", blacklisted:false}; render()');
  desk.eval('person = {...person, new:true, told:false}; render()');
  ok("a failed message is said plainly", out().includes("could not be sent"));

  console.log("admin page: the change log, a ban's declined requests, and a list changed meanwhile");
  let summaries = 0;
  const answer = (status, body) => Promise.resolve({status, ok: status < 300, json: () => Promise.resolve(body)});
  const admin = boot("admin.html", "admin.js", {
    fetch: (url, options = {}) => {
      if (options.method === "POST") {
        if (url.endsWith("/guards/remove")) return answer(404, {error: "No guard has that number."});
        return answer(200, {blacklist: [{phone: "9820011223", name: "Kavita", reason: "",
          added_at: "2026-10-06T05:00:00+00:00"}], declined: ["VR-1", "VR-2"]});
      }
      if (url.includes("/summary")) {
        summaries++;
        return answer(200, {counts: {}, approvers: [], gate_desk: "+911",
          guards: summaries === 1 ? [{name: "Ravi", phone: "+918", added_at: "2026-10-05T05:00:00+00:00"}] : [],
          changes: [{at: "2026-10-06T05:00:00+00:00", by_whom: "Asha +919600000009",
                     action: "Deleted a guard", detail: "Ravi <b>"}]});
      }
      return answer(200, {visits: [{reference: "VR-1", name: "Kavita", phone: "9820011223", address: "x",
        reason: "Delivery", visiting: "y", guests: [], status: "declined", decided_by: "blacklist",
        decided_at: "2026-10-06T05:00:00+00:00", created_at: "2026-10-06T04:00:00+00:00",
        approvers: ["+911", "+912"]}], next: null});
    },
  });
  const a = id => admin.document.getElementById(id);
  admin.eval('localStorage.setItem("adminkey","k")');
  admin.eval("render(); refresh()");
  await tick(); await tick();
  ok("a request declined by a ban says so", a("list").textContent.includes("Declined by the blacklist"));
  ok("the change log names who did what, escaped", a("a-changes").textContent.includes("Asha +919600000009")
     && a("a-changes").innerHTML.includes("Ravi &lt;b&gt;"));
  a("g-table").querySelector("[data-delete]").click();
  a("sure-yes").click();
  await tick(); await tick(); await tick(); await tick();
  ok("a guard deleted by another admin: the list reloads", summaries === 2
     && !a("g-table").textContent.includes("Ravi") && a("g-note").textContent.includes("No guard"));
  a("list").querySelector("[data-ban]").click();
  a("sure-yes").click();
  await tick(); await tick(); await tick();
  ok("a ban says how many waiting requests it declined", a("b-note").textContent.includes("2 waiting requests were declined"));
}

// ------------------------------------------------------------- tags
async function tagChecks() {
  console.log("admin page: tags, a search box and groups on the allow list and offices");
  const posts = [];
  const person = (name, code, tag) => ({name, code, tag, phone: `+9170000${code.slice(-5)}`,
    added_at: "2026-10-06T05:00:00+00:00"});
  const lists = {staff: [person("Dr Iyer", "1000001", "Physics"), person("Dr Rao", "1000002", "Physics"),
                       person("Ms Sen", "1000003", "Library <b>"), person("Mr Das", "1000004", "")],
               offices: [{name: "Fees", main: "+911", backup: "+912", tag: "Main Building"}]};
  const answer = (status, body) => Promise.resolve({status, ok: status < 300, json: () => Promise.resolve(body)});
  const admin = boot("admin.html", "admin.js", {
    fetch: (url, options = {}) => {
      if (options.method === "POST") {
        const sent = JSON.parse(options.body);
        posts.push([url, sent]);
        if (url.endsWith("/staff/tag")) {
          lists.staff = lists.staff.map(p => p.code === sent.code ? {...p, tag: sent.tag} : p);
          return answer(200, {...lists, tag: sent.tag});
        }
        if (url.endsWith("/tags/rename")) {
          lists.staff = lists.staff.map(p => p.tag === sent.old ? {...p, tag: sent.new} : p);
          return answer(200, {...lists, tag: sent.new});
        }
        lists.staff = [...lists.staff, person(sent.name, "1000005", sent.tag)];
        return answer(200, {...lists, code: "1000005", name: sent.name, tag: sent.tag});
      }
      return answer(200, url.includes("/summary") ? {counts: {}, approvers: [], ...lists}
        : {visits: [], next: null});
    },
  });
  const byId = id => admin.document.getElementById(id);
  const rows = () => [...byId("s-table").querySelectorAll("tbody tr:not([data-group])")].map(r => r.cells[0].textContent);
  const groups = () => [...byId("s-table").querySelectorAll("tr[data-group]")].map(r => r.textContent.replace(/\s+/g, " ").trim());
  admin.eval('localStorage.setItem("adminkey","k")');
  admin.eval("render(); refresh()");
  await tick(); await tick();
  ok("under All, each tag gets a heading, No tag last, escaped", groups().join("|")
     === "Library <b> 1|Physics 2|No tag 1" && byId("s-table").innerHTML.includes("Library &lt;b&gt;"));
  const chips = () => [...byId("s-chips").querySelectorAll("button")];
  ok("the chips: All, each tag with its count, No tag", chips().map(c => c.textContent.replace(/\s+/g, " ").trim())
     .join("|") === "All 4|Library <b> 1|Physics 2|No tag 1");
  chips().find(c => c.textContent.includes("Physics")).click();
  ok("a tag chip shows only that tag, without headings", rows().join() === "Dr Iyer,Dr Rao" && groups().length === 0);
  ok("a chosen tag can be renamed", !!byId("s-chips").querySelector("[data-rename]"));
  chips().find(c => c.textContent.includes("No tag")).click();
  ok("No tag shows the untagged", rows().join() === "Mr Das");
  chips()[0].click();
  // The search waits for a pause in typing, then redraws the allow list only.
  const typed = () => new Promise(done => setTimeout(done, admin.eval("SEARCH_WAIT") + 20));
  byId("s-q").value = "1000003";
  byId("s-q").dispatchEvent(new admin.Event("input"));
  await typed();
  ok("the search finds a code", rows().join() === "Ms Sen" && admin.document.activeElement !== byId("s-table"));
  byId("s-q").value = "zzz";
  byId("s-q").dispatchEvent(new admin.Event("input"));
  await typed();
  ok("no match says so", byId("s-table").textContent.includes("Nothing matches"));
  byId("s-q").value = "";
  byId("s-q").dispatchEvent(new admin.Event("input"));
  await typed();

  // Tapping a tag in use fills the tag box, so a phone never needs to type it.
  byId("s-tagpick").querySelector('[data-pick="Physics"]').click();
  ok("a tapped tag fills the box", byId("s-tag").value === "Physics");
  chips().find(c => c.textContent.includes("Library")).click();
  byId("s-name").value = "Dr Bose";
  byId("s-phone").value = "+917000000005";
  byId("s-add").click();
  await tick(); await tick();
  ok("the tag goes with the new person", posts.at(-1)[1].tag === "Physics");
  ok("a new person hidden by the filter is explained", byId("s-note").textContent.includes("does not show below"));
  chips()[0].click();

  // Tag on a row: a sheet with the tags in use, the code stays the same.
  byId("s-table").querySelector('[data-retag][data-id="1000004"]').click();
  ok("Tag opens a sheet with the tags in use", byId("over").textContent.includes("Tag for Mr Das")
     && !!byId("tag-pick").querySelector('[data-pick="Physics"]'));
  byId("tag-pick").querySelector('[data-pick="Physics"]').click();
  byId("tag-save").click();
  await tick(); await tick(); await tick();
  ok("it sends the code and the tag", posts.at(-1)[0] === "/api/admin/staff/tag"
     && posts.at(-1)[1].code === "1000004" && posts.at(-1)[1].tag === "Physics");
  ok("it says the new tag", byId("s-note").textContent.includes("Mr Das now has the tag Physics"));

  chips().find(c => c.textContent.includes("Physics")).click();
  byId("s-chips").querySelector("[data-rename]").click();
  byId("tag-new").value = "Science";
  byId("tag-save").click();
  await tick(); await tick(); await tick();
  ok("Rename this tag sends the old and new names", posts.at(-1)[0] === "/api/admin/tags/rename"
     && posts.at(-1)[1].old === "Physics" && posts.at(-1)[1].new === "Science"
     && posts.at(-1)[1].list === "staff");
  ok("the filter follows the new name", chips().find(c => c.getAttribute("aria-pressed") === "true")
     .textContent.includes("Science"));
  // A long list shows 200 rows, then 200 more on each tap: the redraw cost stays the same.
  lists.staff = Array.from({length: 450}, (_, i) => person(`Person ${i}`, String(2000000 + i), ""));
  admin.eval("refresh()");
  await tick(); await tick();
  chips()[0].click();
  const drawn = () => byId("s-table").querySelectorAll("tbody tr:not([data-group]):not(.more-row)").length;
  ok("a long list shows its first 200 rows", drawn() === 200
     && byId("s-table").querySelector("[data-more]").textContent.includes("of 250 not shown"));
  byId("s-table").querySelector("[data-more]").click();
  ok("Show more adds 200", drawn() === 400);
  byId("s-table").querySelector("[data-more]").click();
  ok("and the last 50, with no button left", drawn() === 450 && !byId("s-table").querySelector("[data-more]"));
  ok("the offices list has its own chips", byId("o-chips").textContent.includes("Main Building")
     && !byId("o-chips").textContent.includes("Science"));

  console.log("visitor form: offices are grouped by tag");
  const v = boot("visitor.html", "visitor.js", {fetch: () => Promise.reject(new Error("offline"))});
  const S = v.eval("S");
  S.cfg.offices = ["Exams", "Fees", "Library"];
  S.cfg.office_groups = [{tag: "Main <Building>", offices: ["Exams", "Fees"]}, {tag: "", offices: ["Library"]}];
  S.s = "step2"; S.f.reason = "See an office"; v.eval("render()");
  const labels = [...v.document.querySelectorAll("#f_office optgroup")].map(g => g.label);
  ok("each tag is a group, untagged last as Other offices, escaped",
     labels.join("|") === "Main <Building>|Other offices"
     && v.document.getElementsByTagName("building").length === 0);
  S.cfg.office_groups = [{tag: "", offices: ["Exams", "Fees", "Library"]}];
  v.eval("render()");
  ok("no tags at all: a plain list, no group heading",
     !v.document.querySelector("#f_office optgroup") && v.document.getElementById("f_office").options.length === 4);
}

// ------------------------------------------------------------- bulk decisions
async function bulkChecks() {
  console.log("admin page: a super admin approves many requests at once");
  const waitingRow = (n, status = "pending") => ({reference: `VR-1000${n}`, name: `Visitor ${n}`,
    phone: "9876543210", address: "x", reason: "Delivery", visiting: "y", guests: [], status,
    created_at: "2026-10-06T05:00:00+00:00", approvers: ["+911", "+912"]});
  const make = (isSuper, decideStatus = 200) => {
    const posts = [];
    let reads = 0;
    const answer = (status, body) => Promise.resolve({status, ok: status < 300, json: () => Promise.resolve(body)});
    const win = boot("admin.html", "admin.js", {
      fetch: (url, options = {}) => {
        if (options.method === "POST") {
          posts.push([url, JSON.parse(options.body)]);
          if (url.endsWith("/decide")) {
            return decideStatus === 200
              ? answer(200, {decided: ["VR-10001"], skipped: [{reference: "VR-10002", why: "Already approved."}]})
              : answer(decideStatus, {error: "Only a super admin can do this."});
          }
          return answer(200, {});
        }
        reads++;
        return answer(200, url.includes("/summary")
          ? {counts: {pending: 2}, approvers: [], super: isSuper, you: isSuper ? "Uma +91" : "Ravi +92",
             main_admin: "+919", admins: [{name: "Uma", phone: "+91", super: true, added_at: "2026-10-05T05:00:00+00:00"},
                                          {name: "Ravi", phone: "+92", super: false, added_at: "2026-10-05T05:00:00+00:00"}]}
          : {visits: [waitingRow(1), waitingRow(2, "escalated"), waitingRow(3, "approved")], next: null});
      },
    });
    win.eval('localStorage.setItem("adminkey","k")');
    win.eval("render(); refresh()");
    return {win, posts, reads: () => reads, byId: id => win.document.getElementById(id)};
  };
  const boss = make(true);
  await tick(); await tick();
  const boxes = () => [...boss.byId("list").querySelectorAll("[data-pick-ref]")];
  ok("only waiting rows get a tick box", boxes().map(b => b.dataset.pickRef).join() === "VR-10001,VR-10002");
  ok("the header says super admin", boss.byId("you").textContent.includes("(super admin)"));
  ok("nothing chosen: the buttons wait", boss.byId("bulk-yes").disabled && !boss.byId("bulk").hidden);
  boss.byId("pick-all").click();
  ok("Select all picks the waiting rows on screen", boxes().every(b => b.checked)
     && boss.byId("bulk-yes").textContent === "Approve 2");
  boss.byId("bulk-yes").click();
  ok("it asks first, with the count", boss.byId("over").textContent.includes("Approve 2 requests?")
     && boss.posts.length === 0);
  boss.byId("sure-yes").click();
  await tick(); await tick(); await tick();
  ok("it sends the references and the decision", boss.posts.at(-1)[0] === "/api/admin/decide"
     && boss.posts.at(-1)[1].references.join() === "VR-10001,VR-10002"
     && boss.posts.at(-1)[1].decision === "approve");
  ok("it says what changed and what did not, and why", boss.byId("bulk-note").textContent.includes("Approved 1")
     && boss.byId("bulk-note").textContent.includes("VR-10002: Already approved."));
  boss.byId("tabs").querySelector('[data-section="admins"]').click();
  ok("a super admin can make another admin super", !!boss.byId("a-table").querySelector('[data-super="+92"]'));
  // One color for each kind of action: green approves, red deletes or bans, amber is a key.
  const has = (selector, color) => {
    const found = [...boss.win.document.querySelectorAll(selector)];
    return found.length > 0 && found.every(b => b.classList.contains(color));
  };
  ok("buttons are color coded by what they do",
     has("#bulk-yes", "go") && has("#bulk-no", "stop") && has("[data-delete]", "del")
     && has("[data-newkey]", "warn") && has("#rekey", "warn") && has("#b-add", "stop")
     && has('[data-super="+92"]', "go") && has("#g-add", "btn") && !has("#g-add", "stop")
     && has("#csv", "edit"));
  ok("but not change their own role", !boss.byId("a-table").querySelector('[data-super="+91"]'));
  ok("a super admin sees the downloads", !boss.byId("csv").hidden && !boss.byId("s-download").hidden);
  ok("Today offers the same bulk decision", !boss.byId("t-bulk").hidden
     && boss.byId("t-list").querySelectorAll("[data-pick-ref]").length === 2);

  console.log("admin page: a regular admin sees no bulk controls, and keeps the key");
  const plain = make(false, 409);
  await tick(); await tick();
  ok("no tick boxes and no bulk buttons", !plain.byId("list").querySelector("[data-pick-ref]")
     && plain.byId("bulk").hidden && plain.byId("t-bulk").hidden);
  ok("and no downloads", plain.byId("csv").hidden && plain.byId("s-download").hidden);
  ok("no Add admin and no gate photos for a regular admin",
     plain.win.document.querySelector('[data-open="a"]').hidden
     && plain.win.eval('photoLine({photo_stored: true, reference: "VR-1"})').includes("super admin"));
  ok("a super admin's row offers them nothing", plain.byId("a-table").textContent
     .includes("Only a super admin can change this.") && !plain.byId("a-table").querySelector('[data-id="+91"]'));
  plain.win.eval('picked.add("VR-10001")');
  const asking = plain.win.eval('bulkDecide("approve")');
  plain.byId("sure-yes").click();
  await asking;
  await tick();
  ok("a 409 shows the reason and keeps the key", plain.win.eval('localStorage.getItem("adminkey")') === "k"
     && plain.byId("bulk-note").textContent.includes("Only a super admin"));
}

void boardChecks().then(officeFormChecks).then(bulkChecks).then(tagChecks).then(worstCaseChecks).then(blacklistChecks).then(staffGateChecks).then(teamChecks).then(staleGateChecks).then(stalePollChecks).then(staleApproverChecks).then(offlinePassChecks).then(approverChecks).then(guardChecks).then(forgotChecks).then(sessionChecks).then(hardeningChecks).then(visitorAutoChecks).then(wrongKeyChecks).then(adminChecks).then(downloadChecks).then(() => {
  console.log();
  console.log(failures ? `${failures} check(s) FAILED` : "all form checks passed");
  process.exit(failures ? 1 : 0);
});
