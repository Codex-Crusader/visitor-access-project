const REASONS = ["See a student", "See an office", "Delivery", "Event", "Other"];
const S = {s:"home", f:{name:"",phone:"",address:"",reason:"",other:"",visiting:""}, g:[], e:{},
  visit:null, cfg:{gate_desk_phone:"",escalate_minutes:30,retain_days:90}, err:"", hist:[], sheet:0};

const $=i=>document.getElementById(i);
const x=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const set=(k,v)=>S.f[k]=v;
const st=()=>S.visit?S.visit.status:"none";
const waiting=()=>st()==="pending"||st()==="escalated";
const live=()=>waiting()||st()==="approved"||st()==="inside";
const hasPass=()=>st()==="approved"||st()==="inside";
const hm=t=>t?new Date(t).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}):"—";
const plus=(t,m)=>hm(new Date(new Date(t).getTime()+m*60000).toISOString());

function go(s,keep=1){if(keep)S.hist.push(S.s);S.s=s;S.sheet=0;render();$("view").scrollTop=0}
function back(){S.s=S.hist.pop()||"home";S.sheet=0;render()}

const T={home:["",0],step1:["Request a Visit",1],step2:["Request a Visit",1],review:["Review",1],sending:["",0],
  status:["Checking on My Request",1],inout:["Getting In and Out",1],privacy:["My Information and Privacy",1],help:["Getting Help",1]};
const word=()=>({pending:"Not approved yet",escalated:"Not approved yet",approved:"Approved",
  declined:"Declined",inside:"Inside campus",closed:"Visit complete"}[st()]||"");
const reasonText=()=>S.f.reason==="Other"?(S.f.other.trim()||"Other"):S.f.reason;
const ICONS={
 check:'<path d="M20 6 9 17l-5-5"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 cross:'<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>'};
const ico=n=>`<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`;
const fact=(k,v)=>`<div><span>${k}</span><b>${x(v||"—")}</b></div>`;
const gate=()=>S.cfg.gate_desk_phone?`<a class="btn plain" href="tel:${x(S.cfg.gate_desk_phone)}">Call gate desk</a>`:"";

function tracker(){
  const v=S.visit, esc=!!v.escalated_at, done=!!v.decided_at;
  const pct=done?100:esc?60:25;
  return `<ul class="track"><span class="rail"><b style="height:${pct}%"></b></span>
    <li class="done"><b class="t">Request sent</b><span>${hm(v.created_at)}</span></li>
    <li class="${esc||done?"done":"now"}"><b class="t">First approver</b>
      <span>${esc?"No answer by "+hm(v.escalated_at):done?"Replied at "+hm(v.decided_at):"Sent on WhatsApp, no reply yet"}</span></li>
    ${esc?`<li class="${done?"done":"now"}"><b class="t">Backup approver</b><span>Took over at ${hm(v.escalated_at)}</span></li>`:""}
    <li class="${done?"done":""}"><b class="t">Decision</b>
      <span>${done?word()+" at "+hm(v.decided_at):"Not yet"}</span></li>
  </ul>`;
}

function view(){
  switch(S.s){
  case "home": return `<div class="hero"><h2>Campus Visitor Access</h2><p class="heroP">Ask to visit, then watch the decision happen.</p></div>
    ${S.visit?`<button class="live ${["approved","inside","closed"].includes(st())?"go":st()==="declined"?"stop":""}" onclick="go('status')">
      <b>${word()}</b><span>${x(S.visit.reference)}</span></button>`:""}
    <div class="menu">
      <button onclick="go('step1')">Request a Visit<i>&rsaquo;</i></button>
      <button onclick="go('status')">Checking on My Request<i>&rsaquo;</i></button>
      <button onclick="go('inout')">Getting In and Out<i>&rsaquo;</i></button>
      <button onclick="go('privacy')">My Information and Privacy<i>&rsaquo;</i></button>
      <button onclick="go('help')">Getting Help<i>&rsaquo;</i></button>
    </div>`;

  case "step1": return `<div class="steps"><i class="on"></i><i></i></div>
    <label for="a">Your name</label><input id="a" value="${x(S.f.name)}" oninput="set('name',this.value)">
    <label for="b">Phone</label>
    <input id="b" inputmode="numeric" class="${S.e.phone?"bad":""}" value="${x(S.f.phone)}" oninput="set('phone',this.value)">
    ${S.e.phone?`<div class="badmsg">${S.e.phone}</div>`:""}
    <label for="c">Address</label><input id="c" value="${x(S.f.address)}" oninput="set('address',this.value)">
    <button class="btn" onclick="n1()">Continue</button>
    <button class="btn plain" onclick="S.sheet=1;render()">Finish later</button>`;

  case "step2":{const nf=S.e.vis;
    return `<div class="steps"><i class="on"></i><i class="on"></i></div>
    <label>Reason</label><div class="chips">${REASONS.map(r=>
      `<button type="button" aria-pressed="${S.f.reason===r}" onclick="pick('${r}')">${r}</button>`).join("")}</div>
    ${S.f.reason==="Other"?`<input id="ro" style="margin-top:10px" value="${x(S.f.other)}" oninput="set('other',this.value)" placeholder="Say briefly why">`:""}
    <label for="v">Who are you visiting?</label>
    <input id="v" class="${nf?"bad":""}" value="${x(S.f.visiting)}" oninput="set('visiting',this.value)" placeholder="Student name or roll number">
    ${nf?`<div class="badmsg">Name a student, not a staff member.</div>
      <p class="sm">Staff no longer approve visits. Give the student name or the roll number.</p>`
      :`<p class="sm">We pick the approver for you.</p>`}
    <label>Anyone with you?</label>
    ${S.g.map((g,i)=>`<div class="guest">${x(g)}<button onclick="drop(${i})">Remove</button></div>`).join("")}
    <div class="addrow"><input id="gn" placeholder="Their name" onkeydown="if(event.key==='Enter'){add()}"><button onclick="add()">Add</button></div>
    <button class="btn" onclick="n2()">Review</button>
    <button class="btn plain" onclick="S.sheet=1;render()">Finish later</button>`;}

  case "review": return `${S.err?`<div class="state bad">${ico("cross")}<div><h3>Not sent</h3><p>${x(S.err)}</p></div></div>`:""}
    <div class="facts">
      ${fact("Name",S.f.name)}${fact("Phone",S.f.phone)}${fact("Address",S.f.address)}
      ${fact("Reason",reasonText())}${fact("Visiting",S.f.visiting)}${S.g.length?fact("With you",S.g.join(", ")):""}
    </div>
    <p class="sm">No answer in ${S.cfg.escalate_minutes} minutes and it moves to a backup approver. You do not fill this in again.</p>
    <button class="btn" onclick="send()">Send request</button>
    <button class="btn plain" onclick="back()">Edit</button>`;

  case "sending": return `<div class="spin"></div><p style="text-align:center">Sending</p>`;

  case "status":{
    if(!S.visit) return `<h2>Nothing sent yet</h2><button class="btn" onclick="go('step1')">Request a Visit</button>`;
    const v=S.visit;
    if(st()==="declined") return `<div class="state bad">${ico("cross")}<div><h3>Declined</h3><p>The approver turned down this visit.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}${fact("Decided",hm(v.decided_at))}</div>
      <button class="btn" onclick="again()">New request</button>${gate()}`;
    if(st()==="closed") return `<div class="state good">${ico("check")}<div><h3>Visit complete</h3><p>You checked out at ${hm(v.exited_at)}. This pass is closed.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}${fact("Entered",hm(v.entered_at))}${fact("Exited",hm(v.exited_at))}</div>
      <button class="btn" onclick="again()">New request</button>`;
    if(st()==="inside") return `<div class="state good">${ico("check")}<div><h3>Inside campus</h3><p>You entered at ${hm(v.entered_at)}. Show the pass again on the way out.</p></div></div>
      <div class="facts">${fact("Reference",v.reference)}${fact("Entered",hm(v.entered_at))}</div>
      <button class="btn" onclick="go('inout')">Open pass</button>${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`;
    if(st()==="approved") return `<div class="state good">${ico("check")}<div><h3>Approved</h3><p>Show your pass at the gate.</p></div></div>
      ${tracker()}<button class="btn" onclick="go('inout')">Open pass</button>${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`;
    return `<div class="state wait">${ico("clock")}<div><h3>Not approved yet</h3><p>Do not enter until this says Approved.</p></div></div>
      ${tracker()}
      <div class="facts">${fact("Reference",v.reference)}
        ${fact("With",st()==="escalated"?"Backup approver":"First approver")}
        ${st()==="escalated"?"":fact("Backup takes over",plus(v.created_at,S.cfg.escalate_minutes))}
        ${v.guests.length?fact("With you",v.guests.join(", ")):""}</div>
      ${gate()}`;}

  case "inout":{
    if(st()==="closed") return `<h2>Pass closed</h2><p>You checked out at ${hm(S.visit.exited_at)}. This code no longer works.</p>
      <button class="btn" onclick="again()">New request</button>`;
    if(!hasPass()) return `<h2>No pass yet</h2><p>Your pass appears here once a request is approved.</p>
      <button class="btn" onclick="go(S.visit?'status':'step1')">${S.visit?"Check my request":"Request a Visit"}</button>`;
    return `<div class="pass"><span class="ptop">${st()==="inside"?"Exit pass":"Entry pass"}</span><b>${x(S.visit.reference)}</b>
      <span class="pcut"></span>
      <span class="pfoot">${x(S.visit.name||"Visitor")}${S.visit.guests.length?" +"+S.visit.guests.length:""} &middot; today</span></div>
      <p class="sm">${st()==="inside"?"Show this again on the way out. The guard closes it.":"Show this at the gate. The guard looks it up."}</p>
      ${gate()}
      <button class="btn plain" onclick="home()">Go to home</button>`;}

  case "privacy": return `<h2>What we ask for</h2>
    <div class="facts">${["Name","Phone","Address","Reason","Who you are visiting"].map(i=>`<div><span>${i}</span></div>`).join("")}</div>
    <p class="sm">No selfie, no ID number, no vehicle number.</p>
    <p class="sm">The campus keeps your request, and the times you entered and left,
    for ${S.cfg.retain_days} days. After that it is deleted automatically.
    The gate desk can see these details while your visit is open.</p>`;

  case "help": return `<h2>Getting help</h2>
    <div class="facts">${fact("Gate desk",S.cfg.gate_desk_phone)}</div>
    ${gate()}`;
  }
  return "";
}

function n1(){const d=S.f.phone.replace(/\D/g,"");if(d.length!==10){S.e.phone="Enter 10 digits.";render();return}delete S.e.phone;go("step2")}
function n2(){
  if(!S.f.reason||!S.f.visiting.trim())return;
  if(S.f.reason==="Other"&&!S.f.other.trim())return;
  if(/prof|dr\.|sir|madam/i.test(S.f.visiting)){S.e.vis=1;render();return}
  delete S.e.vis;
  S.err="";
  go("review");
}
function pick(r){S.f.reason=r;if(r!=="Other")S.f.other="";render();if(r==="Other"){const i=$("ro");if(i)i.focus()}}
function add(){const v=$("gn").value.trim();if(!v)return;S.g.push(v);render()}
function drop(i){S.g.splice(i,1);render()}
function home(){S.s="home";S.hist=[];S.sheet=0;render();$("view").scrollTop=0}
function again(){S.visit=null;localStorage.removeItem("tok");S.g=[];S.err="";go("step1",0)}

async function load(url,options){
  const r=await fetch(url,options);
  const data=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(data.error||`Request failed (${r.status})`);
  return data;
}

async function send(){
  go("sending");
  try{
    S.visit=await load("/api/requests",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:S.f.name,phone:S.f.phone,address:S.f.address,
        reason:reasonText(),visiting:S.f.visiting,guests:S.g})});
    S.err="";
    localStorage.setItem("tok",S.visit.token);
    S.hist=["home"];
    go("status",0);
  }catch(err){
    S.err=err.message;
    S.hist=["home"];
    go("review",0);
  }
}

async function poll(){
  if(!S.visit||!live())return;
  try{
    const v=await load(`/api/visit/${S.visit.token}`);
    const changed=v.status!==S.visit.status;
    S.visit=v;
    if(changed&&["status","home","inout"].includes(S.s))render();
  }catch(err){}
}

function render(){
  const [t,b]=T[S.s]||["",0];
  $("nav").innerHTML=(b?`<button class="back" onclick="back()">&lsaquo;</button>`:"")+(t?`<h1>${t}</h1>`:"");
  $("view").innerHTML=view();
  $("over").innerHTML=S.sheet?`<div class="sheet" onclick="if(event&&event.target===this){S.sheet=0;render()}">
    <div class="box"><h2>Finish later?</h2><p>Everything you typed is saved. Nothing is sent.</p>
    <button class="btn plain" onclick="S.sheet=0;render()">Keep filling</button>
    <button class="btn alt" onclick="S.sheet=0;S.s='home';S.hist=[];render()">Save and exit</button></div></div>`:"";
}

async function start(){
  render();
  try{S.cfg=await load("/api/config")}catch(err){}
  const tok=localStorage.getItem("tok");
  if(tok){
    try{S.visit=await load(`/api/visit/${tok}`)}
    catch(err){localStorage.removeItem("tok")}
  }
  render();
  setInterval(poll,3000);
}
start();
