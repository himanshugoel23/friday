# ruff: noqa: E501
"""Landing page variant S1 (docs/ROBIN_LANDING_BRIEF.md, revision 2). English only. The token {{VARIANT}} is replaced by the router."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><meta name="color-scheme" content="light"><meta name="theme-color" content="#f6f1e7"><title>Robin waitlist</title>
<meta name="description" content="Robin helps protect your parents from phone scams and emergencies. Join the waitlist.">
<style>
*{box-sizing:border-box}html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 var(--sans);overflow-x:hidden;padding-bottom:92px;-webkit-font-smoothing:antialiased}
.w{max-width:1160px;margin:0 auto;padding:0 20px}.n{max-width:640px;margin-left:auto;margin-right:auto}
a{color:var(--link)}svg{max-width:100%}
:focus-visible{outline:3px solid var(--focus);outline-offset:3px;border-radius:6px}
h1,h2,h3,h4,p,ul,ol,figure{margin:0}ul,ol{padding:0;list-style:none}
.top{display:flex;align-items:center;padding:18px 0}
.brand{display:flex;align-items:center;gap:10px;font:700 22px var(--sans);letter-spacing:.3px;color:var(--brandc)}.brand svg{width:30px;height:30px;flex:none}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:56px;padding:0 30px;border-radius:var(--rad);background:var(--btn);color:var(--btnc);font:700 18px var(--sans);letter-spacing:.2px;text-decoration:none;border:0;cursor:pointer;box-shadow:var(--btnsh);transition:transform .2s,filter .2s}
.btn:hover{filter:brightness(1.08);transform:translateY(-1px)}
.sec{padding:64px 0}
.eyebrow{font:700 13px var(--sans);letter-spacing:1.6px;text-transform:uppercase;color:var(--acc)}
/* form */
#join{scroll-margin-top:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--rad2);padding:28px 22px;box-shadow:0 18px 40px rgba(20,25,24,.1)}
.card h2.promise{font:var(--hfont);font-size:24px;line-height:1.28;margin:0 0 4px}
label{display:block;font-weight:600;margin:18px 0 6px;font-size:16px}
input[type=text],input[type=tel]{width:100%;min-height:56px;padding:12px 14px;font:18px var(--sans);border:1.5px solid var(--inb);border-radius:var(--rad3);background:var(--inbg);color:var(--ink)}
input::placeholder{font-size:15px;color:#6b706d}
input:focus{outline:3px solid var(--focus);outline-offset:1px;border-color:var(--focus)}
button.go{margin-top:18px;width:100%;min-height:58px;font-size:19px}button.go[disabled]{opacity:.65;cursor:wait}
.err{color:var(--err);font-weight:600;font-size:16px;min-height:48px;margin-top:8px;line-height:1.35}
.fine{font-size:15px;color:var(--mut);margin:8px 0 0;line-height:1.5}.fine.b{font-weight:700;color:var(--ink)}.fine a{color:var(--mut)}
.hp{position:absolute;left:-9999px;top:auto;width:1px;height:1px;overflow:hidden}
.ok{display:none;text-align:center;padding:6px 0}.ok p{font-size:19px;line-height:1.55;margin:12px 0 20px}.ok svg{width:60px;height:60px}
/* faq */
.faqs{display:grid;gap:10px;max-width:780px;margin:0 auto}
details.faq{background:var(--card);border:1px solid var(--line);border-radius:var(--rad3);overflow:hidden}
details.faq summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:60px;padding:14px 18px;font-weight:650;font-size:18px;line-height:1.3}
details.faq summary::-webkit-details-marker{display:none}
details.faq summary:after{content:"+";flex:none;width:30px;height:30px;border-radius:50%;border:1.5px solid var(--acc);color:var(--acc);display:grid;place-items:center;font-size:20px;font-weight:500;line-height:1}
details.faq[open] summary:after{content:"\2212"}
details.faq p{padding:0 18px 18px;color:var(--mut);font-size:17px}
.foot{padding:34px 0 44px;font-size:15px;line-height:1.6;text-align:center;background:var(--footbg);color:var(--footc)}.foot p{max-width:640px;margin:0 auto 10px}.foot a{color:var(--footc)}
/* phone ui */
.ph{width:236px;border:6px solid var(--bezel);border-radius:34px;background:var(--chatbg);overflow:hidden;position:relative;box-shadow:0 24px 50px rgba(10,18,16,.28);color:#1b2523;text-align:left;flex:none}
.ph:before{content:"";position:absolute;top:0;left:50%;width:50px;height:9px;margin-left:-25px;background:var(--bezel);border-radius:0 0 10px 10px;z-index:2}
.bar{background:var(--bar);color:#fff;padding:21px 12px 9px;display:flex;align-items:center;gap:9px;font-weight:700;font-size:15px;line-height:1.15}
.bar small{display:block;font-weight:400;font-size:11.5px;opacity:.85}
.av{width:30px;height:30px;border-radius:50%;background:var(--avbg);color:#fff;display:grid;place-items:center;font-weight:700;font-size:15px;flex:none}
.chat{padding:11px 9px 13px;display:flex;flex-direction:column;gap:8px}
.m{font-size:13.5px;line-height:1.35;padding:8px 11px;border-radius:12px;max-width:92%;color:#1b2523;box-shadow:0 1px 1px rgba(0,0,0,.08)}
.in{background:#fff;border-top-left-radius:3px;align-self:flex-start}.out{background:var(--outbub);border-top-right-radius:3px;align-self:flex-end}
.m .fw{display:block;font-size:11.5px;color:#55625f;margin-bottom:3px}
.m .hi{display:block;font-size:15px;line-height:1.4;font-weight:600}
.m .cap{display:block;font-size:11.5px;line-height:1.35;color:#4b5855;margin-top:5px;padding-top:5px;border-top:1px solid #e6e1d6;font-style:italic}
.chip{display:inline-block;font:700 11px var(--sans);letter-spacing:.2px;padding:3px 8px;border-radius:999px;margin-bottom:6px}
.chip.amb{background:#fbe9bd;color:#6b4a00}.chip.grn{background:#d9efe2;color:#17573a}.chip.cor{background:#fbdcd4;color:#7a2a1a}
.alertc{background:#fff;border-radius:14px;padding:12px;margin:12px 10px 14px;box-shadow:0 2px 8px rgba(0,0,0,.12);font-size:13.5px;line-height:1.4}
.alertc b{display:block;font-size:12px;letter-spacing:.3px;color:#55625f;margin-bottom:3px;font-weight:700}
.alertc .cb{display:block;margin-top:10px;text-align:center;background:var(--ink);color:#fff;font-weight:700;border-radius:10px;padding:10px;font-size:14px}
.sticky{position:fixed;left:0;right:0;bottom:0;z-index:20;padding:12px 16px calc(12px + env(safe-area-inset-bottom));background:linear-gradient(rgba(255,255,255,0),var(--bg) 40%);transition:opacity .25s}
.sticky.hide{opacity:0;pointer-events:none}.sticky .btn{display:flex;width:100%;max-width:520px;margin:0 auto}
.js .rv{opacity:0;transform:translateY(18px);transition:opacity .7s ease,transform .7s ease}.js .rv.on{opacity:1;transform:none}
@media (min-width:760px){.sticky{display:none}body{padding-bottom:0}.sec{padding:84px 0}.card h2.promise{font-size:27px}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*:before,*:after{animation:none!important;transition:none!important}.js .rv{opacity:1;transform:none}.js .tp .m{opacity:1}}

:root{--bg:#f6f1e7;--ink:#14211f;--mut:#45514e;--link:#8a4f28;--acc:#955630;--btn:#14211f;--btnc:#f6f1e7;--btnsh:0 12px 26px rgba(20,33,31,.22);--brandc:#14211f;
--card:#fffdf8;--line:#e0d7c3;--inb:#b4a98f;--inbg:#fffdf8;--err:#9c2b1f;--focus:#955630;--rad:12px;--rad2:20px;--rad3:12px;--bezel:#26302e;--bar:#14211f;--avbg:#955630;
--chatbg:#e9e3d6;--outbub:#e3ebdc;--footbg:#14211f;--footc:#d6d0c1;
--serif:"Iowan Old Style","Palatino Linotype","Book Antiqua",Palatino,Georgia,"Noto Serif",serif;--hfont:600 24px var(--serif);
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue","Noto Sans","Noto Sans Devanagari","Nirmala UI",Arial,sans-serif}
.hero{padding-bottom:56px;background:radial-gradient(90% 60% at 100% 0,#efe4cf 0,transparent 70%)}
.hg{display:grid;gap:36px}
h1{font:600 35px/1.1 var(--serif);letter-spacing:-.5px;margin:18px 0 16px;max-width:15em}
.sub{font-size:19px;line-height:1.55;color:#33403d;max-width:32em;margin:0 0 26px}
.trust{margin:22px 0 0;padding-left:14px;border-left:3px solid var(--acc);font-size:15.5px;line-height:1.55;color:var(--mut);max-width:30em}
.duo{display:flex;flex-direction:column;align-items:center;gap:30px}
.duo figure{display:flex;flex-direction:column;align-items:center;gap:12px}
.duo figcaption{font:700 12.5px var(--sans);letter-spacing:1.4px;text-transform:uppercase;color:var(--acc)}
.tp .m{opacity:1}.js .tp .m,.js .tp .alertc{opacity:0}
.js .tp.on .m,.js .tp.on .alertc{animation:pop .6s ease forwards;animation-delay:calc(var(--n)*.9s + .3s)}
@keyframes pop{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.ph.light{--chatbg:#f3efe6}
.pg{display:grid;gap:0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.pi{display:flex;gap:18px;align-items:center;padding:22px 4px;border-top:1px solid var(--line)}.pi:first-child{border-top:0}
.pi svg{flex:none}.pi h3{font:600 21px/1.25 var(--serif)}
.sup{margin-top:26px;text-align:center;color:var(--mut);font-size:17px;max-width:34em;margin-left:auto;margin-right:auto}.sup p+p{margin-top:6px}
.band{background:var(--ink);color:#f6f1e7;padding:60px 0;text-align:center}
.band p{font:500 25px/1.4 var(--serif);max-width:24em;margin:0 auto}.band:before{content:"";display:block;width:56px;height:3px;background:#c58352;margin:0 auto 26px}
.hw{display:grid;gap:0}.hw li{padding:22px 0;border-top:1px solid var(--line);display:flex;gap:18px;align-items:baseline}
.hw b{font:600 30px var(--serif);color:var(--acc);min-width:46px}.hw span{font:500 21px/1.3 var(--serif)}
.cs{display:grid;gap:18px;margin-top:22px}
.cc{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;display:flex;flex-direction:column;transition:transform .25s,box-shadow .25s}
.cc:hover{transform:translateY(-3px);box-shadow:0 16px 34px rgba(20,33,31,.12)}
.rep{padding:22px 22px 18px}.rep .tag{font:700 12px var(--sans);letter-spacing:1.4px;text-transform:uppercase;color:var(--acc);margin-bottom:10px}
.rep h3{font:600 20px/1.3 var(--serif);margin-bottom:12px}
.rep .src{font-size:14.5px;color:var(--mut)}.rep .src span{font-weight:700;color:var(--ink)}
.rl{display:inline-block;margin-top:12px;font-weight:700;font-size:15.5px;color:var(--link);text-underline-offset:3px;min-height:24px}
.rob{margin-top:auto;padding:16px 22px 22px;background:#f1ebde;border-top:1px solid var(--line);font-size:16px;line-height:1.5}
.rob b{display:block;font:700 12px var(--sans);letter-spacing:1.4px;text-transform:uppercase;color:#2e6b4d;margin-bottom:6px}
.note{margin-top:20px;font-size:15px;color:var(--mut)}
@media (min-width:760px){
 h1{font-size:58px}.hg{grid-template-columns:1.05fr 1fr;align-items:center;gap:48px}.sub{font-size:21px}
 .duo{flex-direction:row;align-items:flex-start;justify-content:center;gap:26px}.duo figure:nth-child(2){margin-top:70px}
 .pg{grid-template-columns:repeat(4,1fr)}.pi{flex-direction:column;align-items:flex-start;padding:28px 22px;border-top:0;border-left:1px solid var(--line);gap:16px}.pi:first-child{border-left:0}
 .hw{grid-template-columns:repeat(3,1fr);gap:30px}.hw li{flex-direction:column;gap:8px;border-top:2px solid var(--ink);padding-top:18px}
 .cs{grid-template-columns:repeat(3,1fr)}.band p{font-size:34px}
}
</style></head><body>
<header class="hero"><div class="w"><div class="top"><span class="brand"><svg viewBox="0 0 40 40" aria-hidden="true"><rect x="1.5" y="1.5" width="37" height="37" rx="10" fill="#14211f"/><path d="M12 28 V12 h9 a6 6 0 0 1 0 12 h-9 M20 24 l7 4" fill="none" stroke="#f6f1e7" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>Robin</span></div>
<div class="hg"><div><h1>Help protect your parents from phone scams and emergencies</h1>
<p class="sub">Robin helps spot scams, answers calls your parents cannot take, and alerts you on WhatsApp when something looks wrong.</p>
<a class="btn" href="#join">Join the waitlist</a><p class="trust">Your parents are told, can stop it any time, and Robin does not read their chats or record their phone calls.</p></div>
<div class="duo tp rv">
<figure><figcaption>Your parent's WhatsApp</figcaption><div class="ph"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div><div class="chat">
<div class="m out" style="--n:0"><span class="fw">&#8618; Forwarded</span>Your KYC is pending. Share the OTP now or your account will close.</div>
<div class="m in" style="--n:1"><span class="chip amb">Looks like a known scam pattern</span><span class="hi" lang="hi">यह स्कैम जैसा लगता है। OTP या PIN किसी को न बताएं। पहले अपने बेटे से बात करें।</span><span class="cap">Looks like a scam. Do not share your OTP or PIN. Talk to your son first.</span></div></div></div></figure>
<figure><figcaption>Your phone</figcaption><div class="ph light"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div>
<div class="alertc" style="--n:2"><b>ROBIN ALERT</b>Your parent forwarded a message that looks like a known scam pattern.<span class="cb">Call parent</span></div><div style="height:6px"></div></div></figure>
</div></div></div></header>

<section class="sec"><div class="w"><ul class="pg rv">
<li class="pi"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#9a5a30" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M26 8 L38 18 L26 28 V22 C14 22 9 27 6 36 C7 24 13 14 26 14Z"/></svg><h3>Forward anything doubtful, get an answer</h3></li><li class="pi"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#9a5a30" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 8 h6 l3 8 l-4 3 a20 20 0 0 0 9 9 l3 -4 l8 3 v6 a4 4 0 0 1 -4 4 C20 37 8 24 9 12 a4 4 0 0 1 4 -4z"/><path d="M30 6 l8 8 M38 6 l-8 8"/></svg><h3>Urgent missed calls, highlighted for you</h3></li><li class="pi"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#9a5a30" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="14" y="5" width="20" height="38" rx="5"/><path d="M21 38 h6"/><path d="M24 14 v10"/><circle cx="24" cy="29" r="1"/></svg><h3>Risky call alerts, optional Android app</h3></li><li class="pi"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#9a5a30" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="24" cy="24" r="17"/><circle cx="24" cy="24" r="9"/><path d="M24 20 v5"/><circle cx="24" cy="29" r=".8"/></svg><h3>SOS button reaches you fast</h3></li></ul>
<div class="sup"><p>Plus a friendly daily check-in and medicine reminders.</p><p>Also helps with calls that sound like a family member asking for money.</p></div></div></section>

<section class="band"><div class="w"><p class="rv">Your parents are told, can stop it any time, and Robin does not read their chats or record their phone calls.</p></div></section>

<section class="sec"><div class="w"><p class="eyebrow">How it works</p><ol class="hw rv" style="margin-top:6px">
<li><b>01</b><span>You set it up, once</span></li><li><b>02</b><span>Your parent is told, and chooses</span></li><li><b>03</b><span>Robin helps; you get alerts</span></li></ol></div></section>

<section class="sec" style="padding-top:8px"><div class="w"><p class="eyebrow">Reported cases</p><ul class="cs"><li class="cc rv"><div class="rep"><p class="tag">Digital-arrest call</p><h3>Chandigarh's elderly woman loses Rs 2.5 crore in digital arrest fraud</h3><p class="src"><span>The Tribune</span> <time>4 Jun 2025</time></p><a class="rl" href="https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><p class="rob"><b>With Robin</b>Your parent forwards the number or message. Robin explains it matches a known scam pattern and alerts you.</p></li><li class="cc rv"><div class="rep"><p class="tag">Fake KYC and a remote-access app</p><h3>Mumbai: Senior citizen loses Rs 3.95 lakh to KYC fraud after downloading AnyDesk app</h3><p class="src"><span>Free Press Journal</span> <time>12 Jan 2022</time></p><a class="rl" href="https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><p class="rob"><b>With Robin</b>With the optional Android app, Robin can flag a remote-access app being opened and alert you.</p></li><li class="cc rv"><div class="rep"><p class="tag">Call showing a bank's name</p><h3>UPI Limit Scam Costs Pensioner Couple Nearly ₹6 Lakh In Indore</h3><p class="src"><span>Free Press Journal</span> <time>30 Sep 2026</time></p><a class="rl" href="https://www.freepressjournal.in/indore/upi-limit-scam-costs-pensioner-couple-nearly-6-lakh-in-indore" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><p class="rob"><b>With Robin</b>Robin never calls a money request safe. It tells your parent to hang up and call the number on the card, and alerts you.</p></li></ul><p class="note">News reports, linked in full. Robin is not mentioned in them.</p></div></section>

<section class="sec" style="padding-top:8px"><div class="w"><div class="faqs rv">
<details class="faq"><summary>Is Robin a person?</summary><p>No. Robin is an AI assistant. There is no human desk at launch.</p></details>
<details class="faq"><summary>Is this surveillance?</summary><p>No. Your parent is told when you set it up, and can stop it any time by saying so. Robin does not read their chats or record their calls. You get alerts and summaries, not their messages.</p></details>
<details class="faq"><summary>Does Robin listen to calls?</summary><p>Robin does not record your parent's phone calls. It only takes part in a call that is forwarded to Robin's own line, and it says it is an AI assistant first.</p></details>
<details class="faq"><summary>Can my parent say no?</summary><p>Yes, at any time, by voice note, message or on a call. Robin then tells you, so you can talk to them.</p></details>
<details class="faq"><summary>What does it cost?</summary><p>Joining the waitlist is free. No price is announced yet.</p></details>
<details class="faq"><summary>Is it an emergency service?</summary><p>No. In an emergency call 112. The SOS button alerts you and your named contact; it does not replace emergency help.</p></details>
</div></div></section>
<section class="sec " id="join"><div class="w"><div class="card n">
<div id="formwrap"><h2 class="promise">Robin helps protect your parents from phone scams and emergencies, and alerts you when something looks wrong; they stay in charge.</h2>
<form id="f" autocomplete="on" novalidate>
<label for="name">Your name</label><input id="name" name="name" type="text" maxlength="40" autocomplete="given-name" required>
<label for="phone">Your WhatsApp number</label><input id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="98765 43210 or +1 415 555 0100" required>
<div class="hp" aria-hidden="true"><label for="website">Website</label><input id="website" name="website" type="text" tabindex="-1" autocomplete="off"></div>
<div class="err" id="err" role="alert"></div>
<button class="btn go" id="go" type="submit">Join the waitlist</button>
<p class="fine">We will WhatsApp you about the launch, nothing else. Your number is not sold or shared for ads, and we delete it on request.</p><p class="fine b">No payment. No price announced yet.</p>
<p class="fine"><a href="privacy">How we use your details</a></p>
</form></div>
<div class="ok" id="ok" aria-live="polite"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="30" fill="#14211f"/><path d="M19 33l9 9 17-20" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>
<p>You are on the list. We will message you on WhatsApp when your spot opens. One useful thing today: save 1930, India's cybercrime helpline, and cybercrime.gov.in, and share them with your parents.</p><a class="btn share" id="share" href="#" target="_blank" rel="noopener">Share on WhatsApp</a></div>
</div></div></section>
<footer class="foot"><div class="w"><p>Robin is an AI assistant, not a person. It is not an emergency service: in an emergency call 112. Robin is not live yet.</p><p><a href="privacy">How we use your details</a></p></div></footer>
<div class="sticky" id="sticky"><a class="btn" href="#join">Join the waitlist, it is free</a></div>
<script>
document.documentElement.className+=" js";
const ERR={name:"Please add your name.",phone:"That number does not look right. If you are abroad, add the country code.",busy:"That did not go through. Please try again in a minute."};
const MSG="Robin helps protect your parents from phone scams and emergencies, and alerts you when something looks wrong. Join the waitlist: ";
const src=new URLSearchParams(location.search).get("src")||"";
const sh=document.getElementById("share");if(sh)sh.href="https://wa.me/?text="+encodeURIComponent(MSG+location.origin+location.pathname+"?src=share");
if("IntersectionObserver" in window){
const rv=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("on");rv.unobserve(e.target)}}),{threshold:.12});
document.querySelectorAll(".rv").forEach(e=>rv.observe(e));
const st=document.getElementById("sticky"),io=new IntersectionObserver(es=>{st.classList.toggle("hide",es[0].isIntersecting)});io.observe(document.getElementById("join"))}
else{document.querySelectorAll(".rv").forEach(e=>e.classList.add("on"))}
document.getElementById("f").addEventListener("submit",async ev=>{ev.preventDefault();
const err=document.getElementById("err"),g=id=>document.getElementById(id).value.trim();err.textContent="";
const body={name:g("name"),phone:g("phone"),website:g("website"),src:src,v:"{{VARIANT}}",consent:true};
if(!body.name){err.textContent=ERR.name;document.getElementById("name").focus();return}
if(body.phone.replace(/\D/g,"").length<8){err.textContent=ERR.phone;document.getElementById("phone").focus();return}
const b=document.getElementById("go");b.disabled=true;
try{const r=await fetch("join",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
if(!r.ok){const j=await r.json().catch(()=>({}));err.textContent=ERR[j.field]||ERR.busy;b.disabled=false;return}
document.getElementById("formwrap").style.display="none";document.getElementById("ok").style.display="block";
const st=document.getElementById("sticky");if(st)st.style.display="none";
document.getElementById("join").scrollIntoView({block:"center"})}
catch(e){err.textContent=ERR.busy;b.disabled=false}});
</script></body></html>
"""
