const REASONS = ["See a student", "See an office", "Delivery", "Event", "Other"];
// With this reason the visitor picks an office from the list the server sends.
const OFFICE = "See an office";
// Gap between status checks: often while waiting, less once approved or inside.
const POLL_GAP = {pending:5000, escalated:5000, approved:10000, inside:30000};
const POLL_SLOWEST = 60000;   // slowest gap after repeated failures
const POLL_TIMEOUT = 10000;   // give up on one status check
const SEND_TIMEOUT = 75000;   // a sleeping free server can take ~50s to wake
const LIVE_VIEWS = ["status", "home", "inout"];
const MAX_GUESTS = 10;        // the server keeps no more than this
const S = {s:"home", f:{name:"",phone:"",address:"",reason:"",other:"",office:"",visiting:"",guest:""}, g:[], e:{}, adding:0,
  visit:null, cfg:{gate_desk_phone:"",escalate_minutes:15,retain_days:90,pass_hours:48,offices:[]}, err:"", hist:[], sheet:0,
  wait:POLL_GAP.pending, down:0, seen:"", timer:0, busy:0};

const el = i=>document.getElementById(i);
const ESC={"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
const x=s=>String(s).replace(/[&<>"']/g,c=>ESC[c]);
const set=(k,v)=>{S.f[k]=v;if(S.e[k]){delete S.e[k];unmark(k)}};
// A pass past its expiry time reads as expired at once, even offline.
const EXPIRING=["pending","escalated","approved"];
const st=()=>{
  const v=S.visit;
  if(!v)return "none";
  return EXPIRING.includes(v.status)&&v.expires_at&&Date.now()>=Date.parse(v.expires_at)?"expired":v.status;
};
const waiting=()=>st()==="pending"||st()==="escalated";
const live=()=>waiting()||st()==="approved"||st()==="inside";
const gap=()=>POLL_GAP[st()]||POLL_GAP.pending;
const hasPass=()=>st()==="approved"||st()==="inside";
const hm=t=>t?new Date(t).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}):"—";
const dayHm=t=>t?new Date(t).toLocaleString([],{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}):"—";
const plus=(t,m)=>hm(new Date(new Date(t).getTime()+m*60000).toISOString());

function go(s,remember=1){if(remember)S.hist.push(S.s);S.s=s;S.sheet=0;render();el("view").scrollTop=0}
function back(){S.s=S.hist.pop()||"home";S.sheet=0;render()}

const T={home:["",0],step1:["Request a Visit",1],step2:["Request a Visit",1],review:["Review",1],sending:["",0],
  status:["Checking on My Request",1],inout:["Getting In and Out",1],privacy:["My Information and Privacy",1],help:["Getting Help",1]};
const word=()=>({pending:"Not approved yet",escalated:"Not approved yet",approved:"Approved",expired:"Pass expired",
  declined:"Declined",inside:"Inside campus",closed:"Visit complete"}[st()]||"");
const reasonText=()=>S.f.reason==="Other"?(S.f.other.trim()||"Other"):S.f.reason;
// True when the visitor picks an office from a list. With no offices set up, they type the place.
const officeList=()=>S.f.reason===OFFICE&&(S.cfg.offices||[]).length>0;
const visitingText=()=>officeList()?S.f.office:S.f.visiting;
// The chosen office is set after drawing, in mark(): the list stays plain options.
const officeOption=o=>`<option value="${x(o)}">${x(o)}</option>`;
// Grouped by tag when the server sends groups. One group with no tag needs no heading.
const officeOptions=()=>{
  const groups=S.cfg.office_groups||[];
  if(!groups.length||(groups.length===1&&!groups[0].tag))return S.cfg.offices.map(officeOption).join("");
  return groups.map(g=>`<optgroup label="${x(g.tag||"Other offices")}">${g.offices.map(officeOption).join("")}</optgroup>`).join("");
};
const ICONS={
 check:'<path d="M20 6 9 17l-5-5"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 cross:'<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>'};
const ico=n=>`<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`;
const fact=(k,v)=>`<div><span>${k}</span><b>${x(v||"—")}</b></div>`;
// mark() adds the aria attributes after render, so the template stays valid HTML.
const flag=k=>S.e[k]?"bad":"";
const note=k=>S.e[k]?`<div class="bad-note" id="e_${k}">${x(S.e[k])}</div>`:"";
// A + button opens a box for one name, and stays under it for the next person.
// The server keeps ten guests, so the + goes at ten, counting the name in the box.
const guestBox=()=>{
  const box=S.adding
    ?`<div class="add-row"><input id="f_guest" class="${flag("guest")}" value="${x(S.f.guest)}"
      oninput="set('guest',this.value)" placeholder="Their name" aria-label="Name of the person with you" enterkeyhint="done">
      </div>${note("guest")}`
    :"";
  const room=S.g.length+(S.adding?1:0)<MAX_GUESTS;
  return box+(room?`<button type="button" class="add-person" id="more" onclick="openAdd()"><span class="plus" aria-hidden="true">+</span>${S.adding?"Add another person":"Add a person"}</button>`:"");
};
const gate=()=>S.cfg.gate_desk_phone?`<a class="btn plain" href="tel:${x(S.cfg.gate_desk_phone)}">Call gate desk</a>`:"";

const offlineNote=()=>S.down
  ? `<p class="sm" style="color:var(--wait)">No connection right now. This is the copy saved on
     this phone${S.seen?`, last checked with the campus system at ${hm(S.seen)}`:""}. It may be out
     of date. This page keeps trying, and updates by itself once you are back online.</p>`
  : "";

// How far the tracker's line runs. mark() sets it, so the template has no computed CSS.
const railPct=()=>{const v=S.visit;return !v?0:v.decided_at?100:v.escalated_at?60:25};

function tracker(){
  const v=S.visit, esc=!!v.escalated_at, done=!!v.decided_at;
  return `<ul class="track"><span class="rail"><b></b></span>
    <li data-at="done"><b class="t">Request sent</b><span>${hm(v.created_at)}</span></li>
    <li data-at="${esc||done?"done":"now"}"><b class="t">Approver</b>
      <span>${esc?"No answer by "+hm(v.escalated_at):done?"Replied at "+hm(v.decided_at):"Sent on WhatsApp, no reply yet"}</span></li>
    ${esc?`<li data-at="${done?"done":"now"}"><b class="t">Asked again</b><span>Sent again at ${hm(v.escalated_at)}</span></li>`:""}
    <li data-at="${done?"done":""}"><b class="t">Decision</b>
      <span>${done?word()+" at "+hm(v.decided_at):"Not yet"}</span></li>
  </ul>`;
}

// The live card's color on the home screen: green with a pass, red when it ended without one.
const liveTone=()=>["approved","inside"].includes(st())?"go":["declined","expired"].includes(st())?"stop":"";

function homeView(){
  const card=S.visit&&st()!=="closed"?`<button class="live" data-tone="${liveTone()}" onclick="go('status')">
      <b>${word()}</b><span>${x(S.visit.reference)}</span></button>`:"";
  return `<div class="hero"><h2>Campus Visitor Access</h2><p class="heroP">Ask to visit, then watch the decision happen.</p></div>
    ${card}
    <div class="menu">
      <button onclick="go('step1')">Request a Visit<i>&rsaquo;</i></button>
      <button onclick="go('status')">Checking on My Request<i>&rsaquo;</i></button>
      <button onclick="go('inout')">Getting In and Out<i>&rsaquo;</i></button>
      <button onclick="go('privacy')">My Information and Privacy<i>&rsaquo;</i></button>
      <button onclick="go('help')">Getting Help<i>&rsaquo;</i></button>
    </div>`;
}

function step1View(){
  return `<div class="steps"><i class="on"></i><i></i></div>
    <label for="f_name">Your name</label>
    <input id="f_name" class="${flag("name")}" value="${x(S.f.name)}" oninput="set('name',this.value)">
    ${note("name")}
    <label for="f_phone">Phone</label>
    <input id="f_phone" inputmode="tel" type="tel" class="${flag("phone")}" value="${x(S.f.phone)}" oninput="set('phone',this.value)">
    ${note("phone")}
    <label for="f_address">Address</label>
    <input id="f_address" class="${flag("address")}" value="${x(S.f.address)}" oninput="set('address',this.value)">
    ${note("address")}
    <button class="btn" onclick="n1()">Continue</button>
    <button class="btn plain" onclick="S.sheet=1;render()">Finish later</button>`;
}

// The office list when there is one. Else a box to type the office or the student.
function placeField(){
  if(officeList())return `<label for="f_office">Which office?</label>
    <select id="f_office" class="${flag("office")}" onchange="set('office',this.value)">
      <option value="">Choose an office</option>
      ${officeOptions()}
    </select>
    ${note("office")}
    <p class="sm">The office's own approver gets your request.</p>`;
  const office=S.f.reason===OFFICE;
  return `<label for="f_visiting">${office?"Which office?":"Who are you visiting?"}</label>
    <input id="f_visiting" class="${flag("visiting")}" value="${x(S.f.visiting)}" oninput="set('visiting',this.value)" placeholder="${office?"Office name":"Student name or roll number"}">
    ${note("visiting")}
    ${S.e.visiting===STAFF
      ?`<p class="sm">Staff no longer approve visits. Give the student name or the roll number.</p>`
      :`<p class="sm">We pick the approver for you.</p>`}`;
}

function step2View(){
  return `<div class="steps"><i class="on"></i><i class="on"></i></div>
    <label>Reason</label>
    <div class="chips ${S.e.reason?"bad":""}" id="f_reason">${REASONS.map(r=>
      `<button type="button" aria-pressed="false" onclick="pick('${r}')">${r}</button>`).join("")}</div>
    ${note("reason")}
    ${S.f.reason==="Other"?`<input id="f_other" style="margin-top:10px" class="${flag("other")}" value="${x(S.f.other)}" oninput="set('other',this.value)" placeholder="Say briefly why">
      ${note("other")}`:""}
    ${placeField()}
    <label>Anyone with you?</label>
    <p class="sm">Up to ${MAX_GUESTS} people.</p>
    ${S.g.map((g,i)=>`<div class="guest">${x(g)}<button onclick="drop(${i})">Remove</button></div>`).join("")}
    ${guestBox()}
    <button class="btn" onclick="n2()">Review</button>
    <button class="btn plain" onclick="S.sheet=1;render()">Finish later</button>`;
}

function reviewView(){
  return `${S.err?`<div class="state bad">${ico("cross")}<div><h3>Not sent</h3><p>${x(S.err)}</p></div></div>`:""}
    <div class="facts">
      ${fact("Name",S.f.name)}${fact("Phone",S.f.phone)}${fact("Address",S.f.address)}
      ${fact("Reason",reasonText())}${fact(S.f.reason===OFFICE?"Office":"Visiting",visitingText())}${S.g.length?fact("With you",S.g.join(", ")):""}
    </div>
    <p class="sm">No answer in ${S.cfg.escalate_minutes} minutes, and it is sent again, to a backup approver if there is one. You do not fill this in again.</p>
    <button class="btn" onclick="send()">Send request</button>
    <button class="btn plain" onclick="back()">Edit</button>`;
}

// What the status screen shows for each status. A request still waiting shows waitingView.
const STATUS_VIEWS={
  declined:v=>`<div class="state bad">${ico("cross")}<div><h3>Declined</h3><p>The approver turned down this visit.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}${fact("Decided",hm(v.decided_at))}</div>
      <button class="btn" onclick="again()">New request</button>${gate()}`,
  expired:v=>`<div class="state bad">${ico("cross")}<div><h3>Pass expired</h3><p>A request works for ${S.cfg.pass_hours} hours. This one ended at ${dayHm(v.expires_at)}. Send a new request to visit.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}</div>
      <button class="btn" onclick="again()">New request</button>${gate()}`,
  closed:v=>`<div class="state good">${ico("check")}<div><h3>Visit complete</h3><p>You checked out at ${hm(v.exited_at)}. This pass is closed and will not open again.</p></div></div>
      <div class="facts">${fact("Entered",hm(v.entered_at))}${fact("Exited",hm(v.exited_at))}</div>
      <button class="btn" onclick="again()">New request</button>`,
  inside:v=>`<div class="state good">${ico("check")}<div><h3>Inside campus</h3><p>You entered at ${hm(v.entered_at)}. Show the pass again on the way out.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}${fact("Entered",hm(v.entered_at))}</div>
      <button class="btn" onclick="go('inout')">Open pass</button>${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`,
  approved:v=>`<div class="state good">${ico("check")}<div><h3>Approved</h3><p>Show your pass at the gate.</p></div></div>
      ${tracker()}<div class="facts">${fact("Valid until",dayHm(v.expires_at))}</div>
      <button class="btn" onclick="go('inout')">Open pass</button>${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`,
};

function waitingView(v){
  const asked=st()==="escalated";
  return `<div class="state wait">${ico("clock")}<div><h3>Not approved yet</h3><p>Do not enter until this says Approved.</p></div></div>
      ${offlineNote()}
      ${tracker()}
      <div class="facts">${fact("Reference",v.reference)}
        ${fact("With",asked?"Approver, asked again":"Approver")}
        ${asked?"":fact("Asked again at",plus(v.created_at,S.cfg.escalate_minutes))}
        ${v.guests.length?fact("With you",v.guests.join(", ")):""}</div>
      ${gate()}`;
}

function statusView(){
  if(!S.visit) return `<h2>Nothing sent yet</h2><button class="btn" onclick="go('step1')">Request a Visit</button>`;
  return (STATUS_VIEWS[st()]||waitingView)(S.visit);
}

// The two sides of the pass: the entry code before the visitor is in, the exit code once inside.
const PASS_SIDES={
  in:{arrow:"&darr;",label:"Entry pass",code:"entry_code",way:"Coming in",
    tip:"Show this at the gate. The guard looks it up and takes your photo, then lets you in."},
  out:{arrow:"&uarr;",label:"Exit pass",code:"exit_code",way:"On your way out",
    tip:"Show this exit code on the way out. It is new: the code you came in with no longer opens the gate."},
};

function passView(out){
  const v=S.visit, side=PASS_SIDES[out?"out":"in"];
  return `${offlineNote()}
      <div class="pass ${out?"out":"in"}">
      <span class="ptop"><span class="pass-arrow">${side.arrow}</span>${side.label}</span>
      <b>${x(v[side.code]||"—")}</b>
      <span class="pass-cut"></span>
      <span class="pass-foot">${x(v.name||"Visitor")}${v.guests.length?" +"+v.guests.length:""} &middot; ${out?"inside now":"until "+x(dayHm(v.expires_at))}</span>
      <span class="pass-way">${side.way}</span></div>
      <p class="sm">The guard checks this code with the campus system, so a canceled pass does
        not work, even if this screen still shows it.${S.seen?` Last checked ${hm(S.seen)}.`:""}</p>
      <p class="sm">${side.tip}</p>
      ${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`;
}

function inoutView(){
  if(st()==="expired") return `<h2>Pass expired</h2><p>This pass ended at ${dayHm(S.visit.expires_at)}. The code no longer works.</p>
      <button class="btn" onclick="again()">New request</button>`;
  if(st()==="closed") return `<h2>Pass closed</h2><p>You checked out at ${hm(S.visit.exited_at)}. This code no longer works.</p>
      <button class="btn" onclick="again()">New request</button>`;
  if(!hasPass()) return `<h2>No pass yet</h2><p>Your pass appears here once a request is approved.</p>
      <button class="btn" onclick="go(S.visit?'status':'step1')">${S.visit?"Check my request":"Request a Visit"}</button>`;
  return passView(st()==="inside");
}

function privacyView(){
  return `<h2>What we ask for</h2>
    <div class="facts">${["Name","Phone","Address","Reason","Who you are visiting","A photo at the gate"].map(i=>`<div><span>${i}</span></div>`).join("")}</div>
    <p class="sm">At the gate, the guard takes one photo of you before letting
    you in, on the gate desk page or on the campus guards' WhatsApp. A photo on
    the gate desk page is kept by this app with your visit, and only the campus
    super admins can see it. They can download it with the visit log, and the
    campus then keeps that copy. A photo on WhatsApp stays in that WhatsApp chat.
    No ID number, no vehicle number.</p>
    <p class="sm">When your visit is approved, the campus guards get a WhatsApp
    message with your name, your guests, the reason and who you are visiting.
    Not your phone number or address. That message stays in their WhatsApp chats.</p>
    <p class="sm">The campus keeps your request, the gate desk photo, and the times you entered and left,
    for ${S.cfg.retain_days===1?"one day":S.cfg.retain_days+" days"}. After that this app
    deletes it automatically. A copy that an admin downloaded before then is kept by the campus.
    The gate desk can see these details while your visit is open. Once you
    check out, the gate desk sees only the times you came and went.</p>
    <p class="sm">This phone keeps a copy of your pass, so it opens without a
    signal: your name, your guests, the code and the times. Not your phone
    number or address. The copy is deleted when you check out or start
    a new request. It also keeps the campus office list and the gate desk
    number, so the form opens without a signal.</p>`;
}

const helpView=()=>`<h2>Getting help</h2>
    <div class="facts">${fact("Gate desk",S.cfg.gate_desk_phone)}</div>
    ${gate()}`;

// One function for each screen. view() draws the screen the visitor is on.
const VIEWS={home:homeView,step1:step1View,step2:step2View,review:reviewView,
  sending:()=>`<div class="spin"></div><p style="text-align:center">Sending</p>`,
  status:statusView,inout:inoutView,privacy:privacyView,help:helpView};

function view(){
  const draw=VIEWS[S.s];
  return draw?draw():"";
}

// The same rules as the server, checked first to name the wrong field.
const MAX=200;
const STAFF="Name a student, not a staff member.";
// Whole words only, so a student named Sirisha or Madhuri is not refused.
const STAFF_WORDS=/\b(prof|professor|dr|sir|madam|ma'am)\b/i;
const STEP1=["name","phone","address"];
const STEP2=["reason","other","office","visiting","guest"];
// Line breaks and invisible characters would forge lines in the approver's message.
const NOT_TEXT=/[\p{C}\p{Zl}\p{Zp}]/u;
const tidy=t=>String(t||"").trim().replace(/\s+/g," ");

function needed(key,label){
  const raw=S.f[key]||"";
  if(raw.length>MAX)return `${label} is too long. Use ${MAX} characters or fewer.`;
  if(NOT_TEXT.test(raw))return `${label} has characters that are not allowed.`;
  if(!tidy(raw))return `${label} is required.`;
  return "";
}

function unmark(key){
  const box=el("f_"+key);
  if(box){box.classList.remove("bad");box.removeAttribute("aria-invalid");box.removeAttribute("aria-describedby")}
  const message=el("e_"+key);
  if(message)message.remove();
}

// What render() cannot put in the markup: changing attributes, the line height, two handlers.
function mark(){
  const office=el("f_office");
  if(office)office.value=S.f.office;
  Object.keys(S.f).forEach(k=>{
    const box=el("f_"+k);
    if(!box)return;
    if(S.e[k]){box.setAttribute("aria-invalid","true");box.setAttribute("aria-describedby","e_"+k)}
    else{box.removeAttribute("aria-invalid");box.removeAttribute("aria-describedby")}
  });
  const chips=el("f_reason");
  if(chips)chips.querySelectorAll("button").forEach((b,i)=>
    b.setAttribute("aria-pressed",String(S.f.reason===REASONS[i])));
  const bar=document.querySelector(".rail b");
  if(bar)bar.style.height=railPct()+"%";
  const guest=el("f_guest");
  if(guest)guest.onkeydown=e=>{
    // Canceled, or the same Enter presses the + that add() focuses, and the box opens again.
    if(e.key==="Enter"){e.preventDefault();add()}
    else if(e.key==="Escape"){closeAdd();render();const more=el("more");if(more)more.focus()}
  };
  const sheet=document.querySelector(".sheet");
  if(sheet)sheet.onclick=e=>{if(e.target===sheet){S.sheet=0;render()}};
}

// Marks every wrong field at once. True when the step may go on.
function settle(keys,found){
  keys.forEach(k=>delete S.e[k]);
  Object.assign(S.e,found);
  const first=keys.find(k=>S.e[k]);
  if(!first)return true;
  render();
  const box=el("f_"+first);
  if(box){box.scrollIntoView({block:"nearest"});box.focus()}
  return false;
}

// The same rule as the server: 10 digits, or + and the country code for a visitor from abroad.
function newKey(){
  const bytes=new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes,b=>Number(b).toString(16).padStart(2,"0")).join("");
}

function phoneOk(phone){
  const n=phone.replace(/\D/g,"").length;
  return phone.startsWith("+")?n>=8&&n<=15:n===10;
}

function n1(){
  const found={};
  const name=needed("name","Your name");
  if(name)found.name=name;

  const phone=needed("phone","Phone");
  if(phone)found.phone=phone;
  else if(!phoneOk(tidy(S.f.phone)))found.phone="Enter 10 digits, or + and the country code.";

  const address=needed("address","Address");
  if(address)found.address=address;

  if(!settle(STEP1,found))return;
  STEP1.forEach(k=>S.f[k]=tidy(S.f[k]));
  go("step2");
}

// What is wrong with the reason, as {field: message}.
function reasonProblems(){
  if(!S.f.reason)return {reason:"Choose a reason for the visit."};
  const other=S.f.reason==="Other"?needed("other","A short reason"):"";
  return other?{other}:{};
}

// What is wrong with the office or the student, as {field: message}.
function placeProblems(){
  if(officeList())return S.cfg.offices.includes(S.f.office)?{}:{office:"Choose the office you are visiting."};
  if(!tidy(S.f.visiting))return {visiting:S.f.reason===OFFICE?"Name the office you are visiting.":"Name the student you are visiting."};
  const who=needed("visiting","This");
  if(who)return {visiting:who};
  // An office visit may name a staff member. Only a student visit may not.
  return S.f.reason!==OFFICE&&STAFF_WORDS.test(S.f.visiting)?{visiting:STAFF}:{};
}

function n2(){
  // A name typed but not added yet still counts.
  const typed=S.adding&&tidy(S.f.guest);
  const guest=typed?needed("guest","That name"):"";
  const found={...reasonProblems(),...placeProblems(),...(guest?{guest}:{})};
  if(!settle(STEP2,found))return;
  if(typed)S.g.push(typed);
  closeAdd();
  S.f.other=tidy(S.f.other);
  S.f.visiting=tidy(S.f.visiting);
  S.err="";
  // A new key for each reviewed form. Send again after a slow answer reuses it, so the
  // approver gets one request, not two.
  S.key=newKey();
  go("review");
}

function pick(r){
  S.f.reason=r;
  delete S.e.reason;
  delete S.e.office;
  if(r!==OFFICE)S.f.office="";
  if(r!=="Other")S.f.other="";
  else delete S.e.other;
  render();
  if(r==="Other"){const i=el("f_other");if(i)i.focus()}
}
function openAdd(){
  // A name in the open box is kept first, so each + adds one more person.
  if(S.adding&&tidy(S.f.guest)){
    const bad=needed("guest","That name");
    if(bad){settle(["guest"],{guest:bad});return}
    S.g.push(tidy(S.f.guest));
    S.f.guest="";
  }
  S.adding=1;
  render();
  const box=el("f_guest");
  if(box)box.focus();
}
function closeAdd(){S.adding=0;S.f.guest="";delete S.e.guest}
// An empty box just closes. A bad name turns red and stays.
function add(){
  const v=tidy(S.f.guest);
  if(v){
    const bad=needed("guest","That name");
    if(bad){settle(["guest"],{guest:bad});return}
    if(S.g.length<MAX_GUESTS)S.g.push(v);
  }
  closeAdd();
  render();
  const more=el("more");
  if(more)more.focus();
}
function drop(i){S.g.splice(i,1);render()}
function home(){S.s="home";S.hist=[];S.sheet=0;render();el("view").scrollTop=0}
function again(){forget();S.g=[];closeAdd();S.e={};S.err="";go("step1",0)}

// The last pass stays on the phone for a weak signal. No phone number, no address.
const PASS_FIELDS=["token","reference","status","name","guests","created_at","decided_at","expires_at",
  "entered_at","exited_at","entry_code","exit_code"];
function keep(v){
  S.visit=v;S.seen=new Date().toISOString();
  // A finished pass is not kept: the phone must never show a dead code offline.
  if(v.status==="closed"||v.status==="expired"){forget(v);return}
  try{
    localStorage.setItem("tok",v.token);
    localStorage.setItem("pass",JSON.stringify({seen:S.seen,
      visit:Object.fromEntries(PASS_FIELDS.filter(k=>k in v).map(k=>[k,v[k]]))}));
  }catch{/* private mode: this page view only */}
}
function forget(v=null){
  S.visit=v;
  try{localStorage.removeItem("tok");localStorage.removeItem("pass")}catch{/* nothing stored */}
}
function saved(){
  try{
    const p=JSON.parse(localStorage.getItem("pass")||"null");
    if(p&&p.visit&&p.visit.token===localStorage.getItem("tok"))return p;
  }catch{/* unreadable: start clean */}
  return null;
}

// A refused request, with the HTTP status the server gave.
class Refused extends Error{constructor(message,status,data={}){super(message);this.status=status;this.data=data}}
const unknown=err=>err instanceof Refused&&err.status===404;

// Give up on a stalled request instead of hanging forever.
/** @returns {Promise<*>} the server's JSON answer */
async function load(url,options={},ms=POLL_TIMEOUT){
  const stop=new AbortController();
  const timer=setTimeout(()=>stop.abort(),ms);
  try{
    const r=await fetch(url,{...options,signal:stop.signal});
    const data=await r.json().catch(()=>({}));
    if(!r.ok)throw new Refused(data.error||`Request failed (${r.status})`,r.status,data);
    return data;
  }finally{clearTimeout(timer)}
}

async function send(){
  go("sending");
  try{
    S.visit=await load("/api/requests",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:S.f.name,phone:S.f.phone,address:S.f.address,
        reason:reasonText(),visiting:visitingText(),office:officeList()?S.f.office:"",guests:S.g,
        request_key:S.key})},SEND_TIMEOUT);
    S.err="";
    dropDraft();
    keep(S.visit);
    S.hist=["home"];
    go("status",0);
  }catch(err){
    // The office list on this page was old. Take the server's list and ask again.
    if(err instanceof Refused&&Array.isArray(err.data.offices)){
      keepCfg({...S.cfg,offices:err.data.offices,office_groups:err.data.office_groups||[]});
      S.f.office="";
      S.err="";
      S.hist=["home","step1"];
      go("step2",0);
      settle(STEP2,officeList()?{office:err.message}:{visiting:err.message});
      return;
    }
    S.err=err.message;
    S.hist=["home"];
    go("review",0);
  }
}

// One request at a time, never while hidden. Asks again at once when shown or back online.
async function poll(){
  clearTimeout(S.timer);
  if(S.busy)return;
  if(S.visit&&live()&&!document.hidden){
    S.busy=1;
    try{await checkVisit(S.visit.token)}finally{S.busy=0}
  }
  S.timer=setTimeout(()=>void poll(),S.wait);
}

// One status check. New request may drop this visit meanwhile. Its answer then changes nothing.
async function checkVisit(token){
  const same=()=>S.visit&&S.visit.token===token;
  try{
    const v=await load(`/api/visit/${token}`);
    if(same())gotVisit(v);
  }catch(err){
    if(same())lostVisit(err);
  }
}

function gotVisit(v){
  const changed=v.status!==S.visit.status;
  keep(v);
  S.wait=gap();
  if(S.down){S.down=0;render()}
  else if(changed&&LIVE_VIEWS.includes(S.s))render();
}

// No answer: check less often, and show that this is the saved copy.
function lostVisit(err){
  if(unknown(err)){forget();render();return}
  S.wait=Math.min(S.wait*2,POLL_SLOWEST);
  if(!S.down){S.down=1;if(LIVE_VIEWS.includes(S.s))render()}
}
function pollNow(){if(!document.hidden){S.wait=gap();void poll()}}

function render(){
  const [t,b]=T[S.s]||["",0];
  el("nav").innerHTML=(b?`<button class="back" onclick="back()">&lsaquo;</button>`:"")+(t?`<h1>${t}</h1>`:"");
  el("view").innerHTML=view();
  el("over").innerHTML=S.sheet?`<div class="sheet">
    <div class="box"><h2>Finish later?</h2><p>What you typed stays on this phone for one week. Nothing is sent.</p>
    <button class="btn plain" onclick="S.sheet=0;render()">Keep filling</button>
    <button class="btn alt" onclick="saveDraft();S.sheet=0;S.s='home';S.hist=[];render()">Save and exit</button></div></div>`:"";
  mark();
}

// "Finish later" keeps the form on this phone, never on the server, and only for a few days.
const DRAFT_DAYS=7;  // one week, as the Finish later box says
function saveDraft(){
  try{localStorage.setItem("draft",JSON.stringify({at:Date.now(),f:S.f,g:S.g}))}catch{/* this page view only */}
}
function dropDraft(){
  try{localStorage.removeItem("draft")}catch{/* nothing stored */}
}
function restoreDraft(){
  let d=null;
  try{d=JSON.parse(localStorage.getItem("draft")||"null")}catch{/* nothing stored */}
  if(!d||!d.f||Date.now()-d.at>DRAFT_DAYS*86400000){dropDraft();return}
  Object.assign(S.f,d.f);
  S.g=Array.isArray(d.g)?d.g.slice(0,MAX_GUESTS):[];
}

// A finished or unknown visit is not reopened. A failed call keeps the saved pass.
function openSaved(answer){
  if(answer.status==="rejected"){
    if(unknown(answer.reason))forget();
    else S.down=1;
    return;
  }
  const v=answer.value;
  if(v.status==="closed")forget();
  else if(v.status==="expired")forget(v);
  else keep(v);
}

// The last settings this phone got, so the office list and the gate desk number work offline.
function savedCfg(){
  try{
    const c=JSON.parse(localStorage.getItem("cfg")||"null");
    if(c&&Array.isArray(c.offices))S.cfg=c;
  }catch{/* the built-in defaults */}
}
function keepCfg(c){
  S.cfg=c;
  try{localStorage.setItem("cfg",JSON.stringify(c))}catch{/* this page view only */}
}

async function start(){
  // The last pass and settings this phone saw show at once, before any network answer.
  savedCfg();
  const p=saved();
  if(p){S.visit=p.visit;S.seen=p.seen}
  else restoreDraft();
  render();
  // Both questions go out together: one round trip of waiting, not two.
  let tok=S.visit&&S.visit.token;
  try{tok=tok||localStorage.getItem("tok")}catch{/* nothing stored */}
  const [cfg,visit]=await Promise.allSettled([load("/api/config"),tok?load(`/api/visit/${tok}`):null]);
  // No answer keeps the saved settings, or the built-in defaults, which are good enough to start.
  if(cfg.status==="fulfilled")keepCfg(cfg.value);
  if(tok)openSaved(visit);
  render();
  window.addEventListener("online",pollNow);
  document.addEventListener("visibilitychange",pollNow);
  if("serviceWorker" in window.navigator)window.navigator.serviceWorker.register("/sw.js").catch(()=>{});
  void poll();
}
void start();
