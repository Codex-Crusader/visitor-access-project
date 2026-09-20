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
ok("the message names the rule", $("e_phone").textContent === "Enter 10 digits.");
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

console.log();
console.log(failures ? failures + " check(s) FAILED" : "all demo checks passed");
process.exit(failures ? 1 : 0);
