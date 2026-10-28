# ruff: noqa: E501
"""Words the web page shows. WORDING PENDING founder approval (docs/WEB_CHANNEL.md): these are the
only product lines the web channel adds to the chat; everything else is the chatbot's own text."""

CONSENT_TEXT = "AI assistant, test mode. Calls go only to your own number."  # PENDING_FOUNDER_APPROVAL
CONSENT_BUTTON = "Continue"  # PENDING_FOUNDER_APPROVAL
PRIVACY_LINK = "Privacy"  # PENDING_FOUNDER_APPROVAL

PRIVACY_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Privacy</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:0 auto;padding:16px 16px 48px;color:#111b21;background:#fff}
@media(prefers-color-scheme:dark){body{background:#0b141a;color:#e9edef}}</style></head><body>
<h1>Privacy</h1>
<p>Placeholder. The privacy policy and the grievance officer's contact details will be published here
before anyone outside the test group uses Friday. (PENDING founder: business name, officer, address.)</p>
<p>Until then: Friday keeps what you type and say in this chat so it can help you, you can ask it
to show what it remembers, and you can ask it to delete everything.</p>
</body></html>"""

ADMIN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex, nofollow">
<title>Friday web admin</title>
<style>
:root{--bg:#fff;--ink:#111b21;--mut:#667781;--line:#e1e5e8;--acc:#008069}
@media(prefers-color-scheme:dark){:root{--bg:#0b141a;--ink:#e9edef;--mut:#8696a0;--line:#2f3b43}}
body{margin:0;padding:16px;font:15px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--ink);max-width:60rem}
h1{font-size:18px}h2{font-size:15px;margin-top:24px}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid var(--line);padding:6px 4px;text-align:left;font-size:14px;vertical-align:top}
input,button{font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
button.p{background:var(--acc);color:#fff;border-color:var(--acc)}.mut{color:var(--mut)}code{word-break:break-all}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
</style></head><body>
<h1>Friday web channel</h1>
<div id="top" class="mut"></div>
<h2>Invite a tester</h2>
<div class="row"><input id="n" placeholder="Name"><input id="p" placeholder="Own phone +91..." inputmode="tel"><button class="p" id="go">Create link</button></div>
<div id="made"></div>
<h2>Testers</h2><div style="overflow-x:auto"><table id="t"></table></div>
<h2>Feedback</h2><div style="overflow-x:auto"><table id="f"></table></div>
<script>
"use strict";
const API="__API__";
const el=(t,a,...k)=>{const e=document.createElement(t);for(const[x,v]of Object.entries(a||{}))e[x]=v;e.append(...k);return e;};
async function call(path,body){const r=await fetch(API+path,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw new Error(d.detail||r.status);return d;}
async function load(){
  const d=await call("/overview");
  document.getElementById("top").textContent=(d.paused?"KILL SWITCH ON. ":"")+"Today: "+d.today.calls+" calls, about Rs "+d.today.spend_inr+". Caps: "+Object.entries(d.caps).map(([k,v])=>k+" "+v).join(", ");
  const t=document.getElementById("t");t.replaceChildren(el("tr",{},...["Name","Phone","State","Consent","Today","Expires",""].map(h=>el("th",{},h))));
  for(const x of d.testers){const b=el("button",{},"Revoke");b.disabled=!x.active;b.onclick=async()=>{await call("/revoke",{ref:x.id});load();};
    t.append(el("tr",{},el("td",{},x.name),el("td",{},x.phone),el("td",{},x.active?"active":(x.revoked_at?"revoked":"expired")),el("td",{},x.consented_at?"yes":"no"),el("td",{},x.calls_today+" calls, Rs "+x.spend_today_inr),el("td",{},x.expires_at.slice(0,10)),el("td",{},b)));}
  const f=document.getElementById("f");f.replaceChildren(el("tr",{},...["When","Who","Mark","Message","Note"].map(h=>el("th",{},h))));
  for(const x of d.feedback)f.append(el("tr",{},el("td",{},x.ts.replace("T"," ").slice(0,16)),el("td",{},x.tester),el("td",{},x.kind),el("td",{},x.text),el("td",{},x.note)));
}
document.getElementById("go").onclick=async()=>{
  const m=document.getElementById("made");m.replaceChildren();
  try{const d=await call("/invite",{name:document.getElementById("n").value,phone:document.getElementById("p").value});
    m.append(el("p",{},"Link for "+d.tester.name+" (shown once, share it privately):"),el("code",{},d.link));load();}
  catch(e){m.append(el("p",{},e.message));}
};
load();
</script></body></html>"""
