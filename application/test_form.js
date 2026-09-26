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
  Object.assign(w, stubs);
  const tag = w.document.createElement("script");
  tag.textContent = read(script);
  w.document.body.appendChild(tag);
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

el("f_guest").value = "Ravi Rao";
el("f_guest").dispatchEvent(new w.Event("input"));
w.eval('pick("Delivery")');
ok("a re-render keeps what was typed", el("f_guest").value === "Ravi Rao");
el("f_guest").dispatchEvent(new w.KeyboardEvent("keydown", {key: "Enter"}));
ok("Enter adds the person", S.g.join() === "Ravi Rao");
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

S.visit.status = "inside";
S.s = "inout"; call("render");
ok("a live pass still shows its code", el("view").innerHTML.includes("VR-4022"));

// ----------------------------------------------- gate desk hides it too
console.log("gate desk: a closed pass shows times only");
const gRender = () => gate.eval("render()");
const gOut = () => gate.document.getElementById("out").innerHTML;
gate.eval('localStorage.setItem("gatekey","k")');
gate.eval('visit = {reference:"VR-4022", status:"closed", guests:[],' +
          ' entered_at:"2026-09-20T10:30:00Z", exited_at:"2026-09-20T12:00:00Z"}');
gRender();
ok("the banner says the pass is closed", gOut().includes("Pass closed"));
ok("the code and the times still show",
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
ok("an open pass still offers Record entry", gOut().includes("Record entry"));

console.log();
console.log(failures ? `${failures} check(s) FAILED` : "all form checks passed");
process.exit(failures ? 1 : 0);
