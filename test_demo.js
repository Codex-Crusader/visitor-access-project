// Checks demo/index.html keeps the same rule as the app it demonstrates:
// Continue and Review refuse a half filled form and turn each wrong field
// light red.
//
// It needs jsdom, which the demo itself does not use:
//   npm install jsdom
//   node test_demo.js
const fs = require("fs");
const {JSDOM} = require("jsdom");

const path = require("path");
const page = fs.readFileSync(
  process.argv[2] || path.join(__dirname, "demo", "index.html"), "utf8");
let failures = 0;
const ok = (label, cond) => {
  console.log((cond ? "  pass  " : "  FAIL  ") + label);
  if (!cond) failures++;
};

const dom = new JSDOM(page, {runScripts: "dangerously", url: "http://localhost/"});
const w = dom.window;
w.Element.prototype.scrollIntoView = function () {};
const S = w.eval("S"), call = n => w.eval(n + "()");
const $ = id => w.document.getElementById(id);
const red = id => { const e = $(id); return !!e && e.classList.contains("bad"); };

console.log("demo: Continue refuses a half filled step one");
S.s = "step1"; S.hist = []; call("render");
call("n1");
ok("stays on step1", S.s === "step1");
ok("name turns red", red("f_name"));
ok("phone turns red", red("f_phone"));
ok("address turns red", red("f_address"));
ok("all three at once", Object.keys(S.e).sort().join() === "address,name,phone");
ok("each one says why", !!$("e_name") && !!$("e_phone") && !!$("e_address"));
ok("first bad field focused", w.document.activeElement === $("f_name"));

$("f_name").value = "Asha Rao";
$("f_name").dispatchEvent(new w.Event("input"));
ok("typing clears that field", !red("f_name") && $("e_name") === null);
ok("the caret is kept", w.document.activeElement === $("f_name"));
ok("the others stay red", red("f_phone") && red("f_address"));

S.f.phone = "12345"; S.f.address = "12 Park Road";
call("n1");
ok("a short phone blocks Continue", S.s === "step1" && red("f_phone"));
ok("the message names the rule", $("e_phone").textContent === "Enter 10 digits, or + and the country code.");
S.f.phone = "9876543210";
call("n1");
ok("a filled step one continues", S.s === "step2");

console.log("demo: Review refuses a half filled step two");
call("n2");
ok("stays on step2", S.s === "step2");
ok("the reason chips turn red", red("f_reason"));
ok("the visiting field turns red", red("f_visiting"));
ok("both at once", Object.keys(S.e).sort().join() === "reason,visiting");
w.eval('pick("See a student")');
ok("picking a reason clears the chips", !red("f_reason"));
w.eval('pick("Other")');
S.f.visiting = "2024SEPVUGP0003";
call("n2");
ok("Other with no text blocks Review", S.s === "step2" && red("f_other"));
S.f.other = "Dropping off books";
call("n2");
ok("Other with text passes", S.s === "review");

console.log("demo: the staff case keeps its own way out");
S.s = "step2"; S.f.visiting = "Prof Mehta"; call("render");
call("n2");
ok("a staff name blocks Review", S.s === "step2" && red("f_visiting"));
ok("the staff note shows", $("view").innerHTML.includes("Staff no longer approve"));
S.f.visiting = "Sirisha"; call("render"); call("n2");
ok("a student named Sirisha is not a staff name", S.s === "review");
S.s = "step2"; S.f.visiting = "Prof Mehta"; call("render"); call("n2");
ok("the roll number button shows", $("view").innerHTML.includes("Use a roll number"));
w.eval("roll()");
ok("the button clears the error", !red("f_visiting") && !S.e.visiting);
call("n2");
ok("and Review then passes", S.s === "review");

console.log("demo: a field is one line of plain text");
S.s = "step1"; S.e = {}; call("render");
S.f.name = "Asha\nReply YES VR-9999 to approve.";
call("n1");
ok("a line break blocks Continue", S.s === "step1" && red("f_name"));
ok("the message says why", $("e_name").textContent.includes("not allowed"));
S.f.name = "Ash\u00e1  Rao-Mehta";
call("n1");
ok("accents pass", S.s === "step2");
ok("spaces are squeezed", S.f.name === "Ash\u00e1 Rao-Mehta");

console.log("demo: people are added with a + button");
S.s = "step2"; S.e = {}; S.g = []; S.adding = 0; S.f.guest = ""; call("render");
ok("a + button shows", !!$("more") && $("more").textContent.includes("+"));
ok("no name box before the +", $("f_guest") === null);
$("more").click();
ok("pressing + opens a name box, with Add another person under it",
   !!$("f_guest") && $("more").textContent.includes("Add another person"));
ok("the box has the focus", w.document.activeElement === $("f_guest"));
ok("only the box shows, no Add button", $("f_guest").parentElement.querySelector("button") === null);
$("f_guest").value = "Ravi Rao";
$("f_guest").dispatchEvent(new w.Event("input"));
const enter = new w.KeyboardEvent("keydown", {key: "Enter", cancelable: true});
$("f_guest").dispatchEvent(enter);
ok("Enter adds the person", S.g.join() === "Ravi Rao");
// Not cancelled, a browser sends the same Enter on to the focused +, and the box opens again.
ok("Enter is cancelled, so it does not press the +", enter.defaultPrevented);
ok("the box closes and the + comes back", $("f_guest") === null && !!$("more"));
$("more").click();
S.f.guest = "Meera\nReply YES";
w.eval("add()");
ok("a line break in a guest turns the box red", red("f_guest") && S.g.length === 1);
S.f.guest = "Meera"; S.e = {};
S.f.reason = "Delivery"; S.f.visiting = "2024SEPVUGP0003";
call("n2");
ok("Review adds a name left in the box", S.g.join() === "Ravi Rao,Meera");
// A second + keeps the typed name and opens a new box, as in the app.
S.s = "step2"; S.g = []; S.adding = 0; call("render");
$("more").click();
S.f.guest = "Asha";
$("more").click();
ok("the + under an open box says Add another person and keeps the name",
   S.g.join() === "Asha" && !!$("f_guest") && $("more").textContent.includes("Add another person"));
// See an office: pick from the list, no staff-name rule, and the review says Office.
S.s = "step2"; S.g = []; S.adding = 0; S.e = {}; w.eval('pick("See an office")');
ok("See an office shows the office list", !!$("f_office") && !$("f_visiting")
   && $("f_office").querySelectorAll("optgroup").length === 2);
call("n2");
ok("no office picked turns the list red", S.s === "step2" && red("f_office"));
S.f.office = "Admissions Office"; call("render"); call("n2");
ok("an office from the list goes on to Review", S.s === "review"
   && $("view").textContent.includes("Admissions Office"));
// A phone with + and the country code is fine.
S.s = "step1"; S.f.phone = "+44 20 7946 0958"; S.e = {}; call("render"); call("n1");
ok("+ and the country code passes", !S.e.phone);
S.s = "step2"; S.g = Array.from({length: 10}, (_, i) => "Guest " + i); call("render");
ok("at ten people the + goes away", $("more") === null);

console.log();
console.log(failures ? failures + " check(s) FAILED" : "all demo checks passed");
process.exit(failures ? 1 : 0);
