const REASONS = ["See a student", "See an office", "Delivery", "Event", "Other"];
const POLL_EVERY = 3000;      // normal gap between status checks
const POLL_SLOWEST = 30000;   // slowest gap after repeated failures
const POLL_TIMEOUT = 10000;   // give up on one status check
const SEND_TIMEOUT = 75000;   // a sleeping free server can take ~50s to wake
const LIVE_VIEWS = ["status", "home", "inout"];
const MAX_GUESTS = 10;        // the server keeps no more than this
const S = {s:"home", f:{name:"",phone:"",address:"",reason:"",other:"",visiting:"",guest:""}, g:[], e:{}, adding:0,
  visit:null, cfg:{gate_desk_phone:"",escalate_minutes:15,retain_days:90,pass_hours:48}, err:"", hist:[], sheet:0,
  wait:POLL_EVERY, down:0, seen:"", timer:0, busy:0};

const el = i=>document.getElementById(i);
// Built once. Inside the callback it was a new object for every escaped letter.
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
const hasPass=()=>st()==="approved"||st()==="inside";
const hm=t=>t?new Date(t).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}):"—";
const dayHm=t=>t?new Date(t).toLocaleString([],{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}):"—";
const plus=(t,m)=>hm(new Date(new Date(t).getTime()+m*60000).toISOString());

function go(s,keep=1){if(keep)S.hist.push(S.s);S.s=s;S.sheet=0;render();el("view").scrollTop=0}
function back(){S.s=S.hist.pop()||"home";S.sheet=0;render()}

const T={home:["",0],step1:["Request a Visit",1],step2:["Request a Visit",1],review:["Review",1],sending:["",0],
  status:["Checking on My Request",1],inout:["Getting In and Out",1],privacy:["My Information and Privacy",1],help:["Getting Help",1]};
const word=()=>({pending:"Not approved yet",escalated:"Not approved yet",approved:"Approved",expired:"Pass expired",
  declined:"Declined",inside:"Inside campus",closed:"Visit complete"}[st()]||"");
const reasonText=()=>S.f.reason==="Other"?(S.f.other.trim()||"Other"):S.f.reason;
const ICONS={
 check:'<path d="M20 6 9 17l-5-5"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 cross:'<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>'};
const ico=n=>`<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`;
const fact=(k,v)=>`<div><span>${k}</span><b>${x(v||"—")}</b></div>`;
// The class name goes in the markup. The two aria attributes are added after
// the markup is in the page, by mark(), because an attribute that appears and
// disappears cannot be written into a template and still read as valid HTML.
const flag=k=>S.e[k]?"bad":"";
const note=k=>S.e[k]?`<div class="bad-note" id="e_${k}">${x(S.e[k])}</div>`:"";
// A "+" button first. Pressing it opens a box for one more name. Enter or Done
// adds the name, closes the box and brings the "+" back. The server keeps ten guests at
// most, so the "+" goes away at ten rather than letting an eleventh vanish.
const guestBox=()=>S.adding
  ?`<div class="add-row"><input id="f_guest" class="${flag("guest")}" value="${x(S.f.guest)}"
      oninput="set('guest',this.value)" placeholder="Their name" aria-label="Name of the person with you" enterkeyhint="done">
      </div>${note("guest")}`
  :S.g.length<MAX_GUESTS
    ?`<button type="button" class="add-person" id="more" onclick="openAdd()"><span class="plus" aria-hidden="true">+</span>Add a person</button>`
    :"";
const gate=()=>S.cfg.gate_desk_phone?`<a class="btn plain" href="tel:${x(S.cfg.gate_desk_phone)}">Call gate desk</a>`:"";

const offlineNote=()=>S.down
  ? `<p class="sm" style="color:var(--wait)">No connection right now. This page keeps trying,
     and updates by itself once you are back online.${S.seen?` Last updated ${hm(S.seen)}.`:""}</p>`
  : "";

// How far the blue line has run down the tracker. mark() writes it on to the
// bar after the markup is in the page, so the template holds no computed CSS.
const railPct=()=>{const v=S.visit;return !v?0:v.decided_at?100:v.escalated_at?60:25};

function tracker(){
  const v=S.visit, esc=!!v.escalated_at, done=!!v.decided_at;
  return `<ul class="track"><span class="rail"><b></b></span>
    <li data-at="done"><b class="t">Request sent</b><span>${hm(v.created_at)}</span></li>
    <li data-at="${esc||done?"done":"now"}"><b class="t">First approver</b>
      <span>${esc?"No answer by "+hm(v.escalated_at):done?"Replied at "+hm(v.decided_at):"Sent on WhatsApp, no reply yet"}</span></li>
    ${esc?`<li data-at="${done?"done":"now"}"><b class="t">Backup approver</b><span>Took over at ${hm(v.escalated_at)}</span></li>`:""}
    <li data-at="${done?"done":""}"><b class="t">Decision</b>
      <span>${done?word()+" at "+hm(v.decided_at):"Not yet"}</span></li>
  </ul>`;
}

function view(){
  switch(S.s){
  case "home": return `<div class="hero"><h2>Campus Visitor Access</h2><p class="heroP">Ask to visit, then watch the decision happen.</p></div>
    ${S.visit&&st()!=="closed"?`<button class="live" data-tone="${["approved","inside"].includes(st())?"go":["declined","expired"].includes(st())?"stop":""}" onclick="go('status')">
      <b>${word()}</b><span>${x(S.visit.reference)}</span></button>`:""}
    <div class="menu">
      <button onclick="go('step1')">Request a Visit<i>&rsaquo;</i></button>
      <button onclick="go('status')">Checking on My Request<i>&rsaquo;</i></button>
      <button onclick="go('inout')">Getting In and Out<i>&rsaquo;</i></button>
      <button onclick="go('privacy')">My Information and Privacy<i>&rsaquo;</i></button>
      <button onclick="go('help')">Getting Help<i>&rsaquo;</i></button>
    </div>`;

  case "step1": return `<div class="steps"><i class="on"></i><i></i></div>
    <label for="f_name">Your name</label>
    <input id="f_name" class="${flag("name")}" value="${x(S.f.name)}" oninput="set('name',this.value)">
    ${note("name")}
    <label for="f_phone">Phone</label>
    <input id="f_phone" inputmode="numeric" class="${flag("phone")}" value="${x(S.f.phone)}" oninput="set('phone',this.value)">
    ${note("phone")}
    <label for="f_address">Address</label>
    <input id="f_address" class="${flag("address")}" value="${x(S.f.address)}" oninput="set('address',this.value)">
    ${note("address")}
    <button class="btn" onclick="n1()">Continue</button>
    <button class="btn plain" onclick="S.sheet=1;render()">Finish later</button>`;

  case "step2":
    return `<div class="steps"><i class="on"></i><i class="on"></i></div>
    <label>Reason</label>
    <div class="chips ${S.e.reason?"bad":""}" id="f_reason">${REASONS.map(r=>
      `<button type="button" aria-pressed="false" onclick="pick('${r}')">${r}</button>`).join("")}</div>
    ${note("reason")}
    ${S.f.reason==="Other"?`<input id="f_other" style="margin-top:10px" class="${flag("other")}" value="${x(S.f.other)}" oninput="set('other',this.value)" placeholder="Say briefly why">
      ${note("other")}`:""}
    <label for="f_visiting">Who are you visiting?</label>
    <input id="f_visiting" class="${flag("visiting")}" value="${x(S.f.visiting)}" oninput="set('visiting',this.value)" placeholder="Student name or roll number">
    ${note("visiting")}
    ${S.e.visiting===STAFF
      ?`<p class="sm">Staff no longer approve visits. Give the student name or the roll number.</p>`
      :`<p class="sm">We pick the approver for you.</p>`}
    <label>Anyone with you?</label>
    ${S.g.map((g,i)=>`<div class="guest">${x(g)}<button onclick="drop(${i})">Remove</button></div>`).join("")}
    ${guestBox()}
    <button class="btn" onclick="n2()">Review</button>
    <button class="btn plain" onclick="S.sheet=1;render()">Finish later</button>`;

  case "review": return `${S.err?`<div class="state bad">${ico("cross")}<div><h3>Not sent</h3><p>${x(S.err)}</p></div></div>`:""}
    <div class="facts">
      ${fact("Name",S.f.name)}${fact("Phone",S.f.phone)}${fact("Address",S.f.address)}
      ${fact("Reason",reasonText())}${fact("Visiting",S.f.visiting)}${S.g.length?fact("With you",S.g.join(", ")):""}
    </div>
    <p class="sm">No answer in ${S.cfg.escalate_minutes} minutes, and it moves to a backup approver. You do not fill this in again.</p>
    <button class="btn" onclick="send()">Send request</button>
    <button class="btn plain" onclick="back()">Edit</button>`;

  case "sending": return `<div class="spin"></div><p style="text-align:center">Sending</p>`;

  case "status":{
    if(!S.visit) return `<h2>Nothing sent yet</h2><button class="btn" onclick="go('step1')">Request a Visit</button>`;
    const v=S.visit;
    if(st()==="declined") return `<div class="state bad">${ico("cross")}<div><h3>Declined</h3><p>The approver turned down this visit.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}${fact("Decided",hm(v.decided_at))}</div>
      <button class="btn" onclick="again()">New request</button>${gate()}`;
    if(st()==="expired") return `<div class="state bad">${ico("cross")}<div><h3>Pass expired</h3><p>A request works for ${S.cfg.pass_hours} hours. This one ended at ${dayHm(v.expires_at)}. Send a new request to visit.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}</div>
      <button class="btn" onclick="again()">New request</button>${gate()}`;
    if(st()==="closed") return `<div class="state good">${ico("check")}<div><h3>Visit complete</h3><p>You checked out at ${hm(v.exited_at)}. This pass is closed and will not open again.</p></div></div>
      <div class="facts">${fact("Entered",hm(v.entered_at))}${fact("Exited",hm(v.exited_at))}</div>
      <button class="btn" onclick="again()">New request</button>`;
    if(st()==="inside") return `<div class="state good">${ico("check")}<div><h3>Inside campus</h3><p>You entered at ${hm(v.entered_at)}. Show the pass again on the way out.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}${fact("Entered",hm(v.entered_at))}</div>
      <button class="btn" onclick="go('inout')">Open pass</button>${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`;
    if(st()==="approved") return `<div class="state good">${ico("check")}<div><h3>Approved</h3><p>Show your pass at the gate.</p></div></div>
      ${tracker()}<div class="facts">${fact("Valid until",dayHm(v.expires_at))}</div>
      <button class="btn" onclick="go('inout')">Open pass</button>${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`;
    return `<div class="state wait">${ico("clock")}<div><h3>Not approved yet</h3><p>Do not enter until this says Approved.</p></div></div>
      ${offlineNote()}
      ${tracker()}
      <div class="facts">${fact("Reference",v.reference)}
        ${fact("With",st()==="escalated"?"Backup approver":"First approver")}
        ${st()==="escalated"?"":fact("Backup takes over",plus(v.created_at,S.cfg.escalate_minutes))}
        ${v.guests.length?fact("With you",v.guests.join(", ")):""}</div>
      ${gate()}`;}

  case "inout":{
    if(st()==="expired") return `<h2>Pass expired</h2><p>This pass ended at ${dayHm(S.visit.expires_at)}. The code no longer works.</p>
      <button class="btn" onclick="again()">New request</button>`;
    if(st()==="closed") return `<h2>Pass closed</h2><p>You checked out at ${hm(S.visit.exited_at)}. This code no longer works.</p>
      <button class="btn" onclick="again()">New request</button>`;
    if(!hasPass()) return `<h2>No pass yet</h2><p>Your pass appears here once a request is approved.</p>
      <button class="btn" onclick="go(S.visit?'status':'step1')">${S.visit?"Check my request":"Request a Visit"}</button>`;
    const out=st()==="inside";
    return `${offlineNote()}
      <div class="pass ${out?"out":"in"}">
      <span class="ptop"><span class="pass-arrow">${out?"&uarr;":"&darr;"}</span>${out?"Exit pass":"Entry pass"}</span>
      <b>${x((out?S.visit.exit_code:S.visit.entry_code)||"—")}</b>
      <span class="pass-cut"></span>
      <span class="pass-foot">${x(S.visit.name||"Visitor")}${S.visit.guests.length?" +"+S.visit.guests.length:""} &middot; ${out?"inside now":"until "+x(dayHm(S.visit.expires_at))}</span>
      <span class="pass-way">${out?"On your way out":"Coming in"}</span></div>
      <p class="sm">${out?"Show this exit code on the way out. It is new: the code you came in with no longer opens the gate.":"Show this at the gate. The guard looks it up and takes your photo, then lets you in."}</p>
      ${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`;}

  case "privacy": return `<h2>What we ask for</h2>
    <div class="facts">${["Name","Phone","Address","Reason","Who you are visiting","A photo at the gate"].map(i=>`<div><span>${i}</span></div>`).join("")}</div>
    <p class="sm">At the gate, the guard takes one photo of you on the campus
    guards' WhatsApp before letting you in. The photo stays in that WhatsApp chat. This
    app keeps the time it was taken and WhatsApp's id for it, not the photo
    itself. No ID number, no vehicle number.</p>
    <p class="sm">When your visit is approved, the campus guards get a WhatsApp
    message with your name, your guests, the reason and who you are visiting.
    Not your phone number or address. That message stays in their WhatsApp chats.</p>
    <p class="sm">The campus keeps your request, and the times you entered and left,
    for ${S.cfg.retain_days===1?"one day":S.cfg.retain_days+" days"}. After that it is
    deleted automatically.
    The gate desk can see these details while your visit is open. Once you
    check out, the gate desk sees only the times you came and went.</p>
    <p class="sm">This phone keeps a copy of your pass, so it opens without a
    signal: your name, your guests, the code and the times. Not your phone
    number or address. The copy is deleted when you check out or start
    a new request.</p>`;

  case "help": return `<h2>Getting help</h2>
    <div class="facts">${fact("Gate desk",S.cfg.gate_desk_phone)}</div>
    ${gate()}`;
  }
  return "";
}

// The server refuses anything empty or over 200 characters, so the form
// refuses the same things first and says which field is wrong.
const MAX=200;
const STAFF="Name a student, not a staff member.";
// Whole words only, so a student named Sirisha or Madhuri is not refused.
const STAFF_WORDS=/\b(prof|professor|dr|sir|madam|ma'am)\b/i;
const STEP1=["name","phone","address"];
const STEP2=["reason","other","visiting","guest"];
// Line breaks, control codes, invisible marks and the overrides that make
// text run the other way. They are not part of a name or an address, and the
// approver's WhatsApp message is built out of these fields, so a line break
// here would let a visitor forge an extra line in it. The server refuses the
// same set, so this only saves a round trip.
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

// Everything render() cannot put in the markup: attributes that come and go, a
// height that is a number, and the two handlers that need their own event.
// The template stays plain HTML, and this finishes the page off.
function mark(){
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
    if(e.key==="Enter")add();
    else if(e.key==="Escape"){closeAdd();render();const more=el("more");if(more)more.focus()}
  };
  const sheet=document.querySelector(".sheet");
  if(sheet)sheet.onclick=e=>{if(e.target===sheet){S.sheet=0;render()}};
}

// Every field is checked, so three empty boxes turn red together rather than
// one at a time. Returns true when the step may go on.
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

function n1(){
  const found={};
  const name=needed("name","Your name");
  if(name)found.name=name;

  const phone=needed("phone","Phone");
  if(phone)found.phone=phone;
  else if(tidy(S.f.phone).replace(/\D/g,"").length!==10)found.phone="Enter 10 digits.";

  const address=needed("address","Address");
  if(address)found.address=address;

  if(!settle(STEP1,found))return;
  STEP1.forEach(k=>S.f[k]=tidy(S.f[k]));
  go("step2");
}

function n2(){
  const found={};
  if(!S.f.reason)found.reason="Choose a reason for the visit.";
  else if(S.f.reason==="Other"){
    const other=needed("other","A short reason");
    if(other)found.other=other;
  }

  if(!tidy(S.f.visiting))found.visiting="Name the student you are visiting.";
  else{
    const who=needed("visiting","This");
    if(who)found.visiting=who;
    else if(STAFF_WORDS.test(S.f.visiting))found.visiting=STAFF;
  }

  // A name typed in the open box but not added yet still counts. Pressing
  // Review must not quietly lose the person.
  const typed=S.adding&&tidy(S.f.guest)?needed("guest","That name"):"";
  if(typed)found.guest=typed;

  if(!settle(STEP2,found))return;
  if(S.adding&&tidy(S.f.guest))S.g.push(tidy(S.f.guest));
  closeAdd();
  S.f.other=tidy(S.f.other);
  S.f.visiting=tidy(S.f.visiting);
  S.err="";
  go("review");
}

function pick(r){
  S.f.reason=r;
  delete S.e.reason;
  if(r!=="Other")S.f.other="";
  else delete S.e.other;
  render();
  if(r==="Other"){const i=el("f_other");if(i)i.focus()}
}
function openAdd(){
  S.adding=1;
  render();
  const box=el("f_guest");
  if(box)box.focus();
}
function closeAdd(){S.adding=0;S.f.guest="";delete S.e.guest}
// Adds the name in the box. An empty box just closes again. A name that
// breaks the field rules turns red and stays, the same as every other field.
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

// The phone keeps the last pass it saw, so the pass opens with a weak signal
// or none. Only what the pass and status screens draw is kept: no phone
// number and no address. A closed or unknown pass is forgotten.
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
class Refused extends Error{constructor(message,status){super(message);this.status=status}}
const unknown=err=>err instanceof Refused&&err.status===404;

// Give up on a stalled request instead of hanging forever.
/** @returns {Promise<*>} the server's JSON answer */
async function load(url,options={},ms=POLL_TIMEOUT){
  const stop=new AbortController();
  const timer=setTimeout(()=>stop.abort(),ms);
  try{
    const r=await fetch(url,{...options,signal:stop.signal});
    const data=await r.json().catch(()=>({}));
    if(!r.ok)throw new Refused(data.error||`Request failed (${r.status})`,r.status);
    return data;
  }finally{clearTimeout(timer)}
}

async function send(){
  go("sending");
  try{
    S.visit=await load("/api/requests",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:S.f.name,phone:S.f.phone,address:S.f.address,
        reason:reasonText(),visiting:S.f.visiting,guests:S.g})},SEND_TIMEOUT);
    S.err="";
    keep(S.visit);
    S.hist=["home"];
    go("status",0);
  }catch(err){
    S.err=err.message;
    S.hist=["home"];
    go("review",0);
  }
}

// One request at a time. The next is scheduled only after this one ends,
// so a slow connection never stacks up overlapping polls. A hidden page does
// not ask at all, and the page asks at once when it shows again or the
// phone comes back online, instead of waiting out a long backoff.
async function poll(){
  clearTimeout(S.timer);
  if(S.busy)return;
  if(S.visit&&live()&&!document.hidden){
    S.busy=1;
    try{
      const v=await load(`/api/visit/${S.visit.token}`);
      const changed=v.status!==S.visit.status;
      keep(v);
      S.wait=POLL_EVERY;
      if(S.down){S.down=0;render()}
      else if(changed&&LIVE_VIEWS.includes(S.s))render();
    }catch(err){
      if(unknown(err)){forget();render()}
      else{
        S.wait=Math.min(S.wait*2,POLL_SLOWEST);
        if(!S.down){S.down=1;if(LIVE_VIEWS.includes(S.s))render()}
      }
    }finally{S.busy=0}
  }
  S.timer=setTimeout(()=>void poll(),S.wait);
}
function pollNow(){if(!document.hidden){S.wait=POLL_EVERY;void poll()}}

function render(){
  const [t,b]=T[S.s]||["",0];
  el("nav").innerHTML=(b?`<button class="back" onclick="back()">&lsaquo;</button>`:"")+(t?`<h1>${t}</h1>`:"");
  el("view").innerHTML=view();
  el("over").innerHTML=S.sheet?`<div class="sheet">
    <div class="box"><h2>Finish later?</h2><p>Everything you typed is saved. Nothing is sent.</p>
    <button class="btn plain" onclick="S.sheet=0;render()">Keep filling</button>
    <button class="btn alt" onclick="S.sheet=0;S.s='home';S.hist=[];render()">Save and exit</button></div></div>`:"";
  mark();
}

async function start(){
  // The last pass this phone saw shows at once, before any network answer.
  const p=saved();
  if(p){S.visit=p.visit;S.seen=p.seen}
  render();
  // Both questions go out together: one round trip of waiting, not two.
  let tok=S.visit&&S.visit.token;
  try{tok=tok||localStorage.getItem("tok")}catch{/* nothing stored */}
  const [cfg,visit]=await Promise.allSettled([load("/api/config"),tok?load(`/api/visit/${tok}`):null]);
  // No settings mean the built-in defaults, which are good enough to start.
  if(cfg.status==="fulfilled")S.cfg=cfg.value;
  if(tok){
    // A finished or unknown visit is not reopened. A failed connection keeps
    // the saved pass, and the poll below tries again.
    if(visit.status==="fulfilled"){
      if(visit.value.status==="closed")forget();
      else if(visit.value.status==="expired")forget(visit.value);
      else keep(visit.value);
    }
    else if(unknown(visit.reason))forget();
    else S.down=1;
  }
  render();
  window.addEventListener("online",pollNow);
  document.addEventListener("visibilitychange",pollNow);
  if("serviceWorker" in window.navigator)window.navigator.serviceWorker.register("/sw.js").catch(()=>{});
  void poll();
}
void start();
