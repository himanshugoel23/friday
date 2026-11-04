# ruff: noqa: E501
"""The public page: the DESIGN tells the story (illustrated scenes, phone mock-ups, big numbers), a few words per screen,
then name + WhatsApp number only. English + Roman Hinglish toggle. Copy is PENDING founder approval (docs/ROBIN_WAITLIST.md).
News cards link to the publishers' own pages; the opening scene is a scene, not a testimonial. Fixed light theme with dark story panels."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><meta name="color-scheme" content="light"><title>Robin: for the parents you cannot call every hour</title>
<meta name="description" content="Robin checks in on your parents every day and warns you when something looks wrong. Join the waitlist.">
<style>
:root{--cream:#fff8ee;--ink:#23303a;--mut:#6b655b;--teal:#0f766e;--teal2:#14b8a6;--gold:#f2a93b;--rose:#d9534f;--night:#101826;--night2:#1b2740;--card:#fff;--line:#ecdfc8}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--cream);color:var(--ink);font:17px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;overflow-x:hidden}
.w{max-width:560px;margin:0 auto;padding:0 20px}
.sec{padding:44px 0}.dark{background:var(--night);color:#f6f1e7}.dark2{background:linear-gradient(180deg,var(--night2),var(--night));color:#f6f1e7}
.top{display:flex;justify-content:space-between;align-items:center;padding:16px 0 0}
.brand{font-weight:800;font-size:22px;letter-spacing:.3px;display:flex;align-items:center;gap:8px}.dot{width:12px;height:12px;border-radius:50%;background:var(--teal2);box-shadow:0 0 0 4px rgba(20,184,166,.2)}
button.lang{background:none;border:1px solid var(--line);border-radius:999px;color:inherit;padding:6px 12px;font-size:14px;cursor:pointer}.dark button.lang{border-color:#3a4660}
h1{font:800 44px/1.05 Georgia,"Times New Roman",serif;margin:18px 0 10px;letter-spacing:-.5px}h1 em{font-style:normal;color:var(--teal)}
h2{font:800 32px/1.1 Georgia,serif;margin:0 0 8px;letter-spacing:-.3px}.kick{font-weight:700;font-size:13px;letter-spacing:1.6px;text-transform:uppercase;color:var(--gold);margin:0 0 8px}
.sub{font-size:20px;color:var(--mut);margin:0 0 6px}.dark .sub{color:#c8c0b2}
.hero svg{width:100%;height:auto;display:block;margin-top:8px}
.cta{display:block;text-align:center;margin:18px 0 0;padding:16px;border-radius:14px;background:var(--teal);color:#fff;font-weight:800;font-size:19px;text-decoration:none;box-shadow:0 8px 20px rgba(15,118,110,.28)}
.cap{font-size:15px;color:var(--mut);margin:10px 0 0;text-align:center}.dark .cap{color:#b7ae9f}
/* phone mock */
.phones{display:flex;gap:14px;justify-content:center;align-items:flex-start;margin-top:22px}
.ph{padding-bottom:10px;width:158px;border:6px solid #2d3a4a;border-radius:28px;background:#ece5dd;overflow:hidden;box-shadow:0 14px 30px rgba(0,0,0,.25);position:relative}
.ph:before{content:"";position:absolute;top:0;left:50%;width:46px;height:9px;margin-left:-23px;background:#2d3a4a;border-radius:0 0 8px 8px;z-index:2}
.bar{background:var(--teal);color:#fff;font-weight:700;font-size:12px;padding:18px 10px 7px;display:flex;align-items:center;gap:6px}.bar i{width:18px;height:18px;border-radius:50%;background:#fff;display:inline-block}
.chat{padding:10px 7px;min-height:176px;display:flex;flex-direction:column;gap:7px}
.b{font-size:12px;line-height:1.3;padding:7px 9px;border-radius:10px;max-width:92%;color:#1e2a30}.in{background:#fff;border-top-left-radius:2px}.out{background:#d9fdd3;align-self:flex-end;border-top-right-radius:2px}
.wave{display:flex;align-items:center;gap:2px;height:18px}.wave s{display:block;width:3px;background:#3b8f6a;border-radius:2px}.play{width:0;height:0;border-left:9px solid #3b8f6a;border-top:6px solid transparent;border-bottom:6px solid transparent;margin-right:4px}
.alert{margin:8px 7px 0;background:#fff;border-radius:12px;border-left:5px solid var(--rose);padding:9px 9px 10px;color:#1e2a30;font-size:12px;line-height:1.3;box-shadow:0 4px 10px rgba(0,0,0,.1)}
.alert b{display:block;font-size:12px;color:var(--rose);margin-bottom:3px}.alert .btn{margin-top:8px;background:var(--teal);color:#fff;text-align:center;font-weight:700;border-radius:8px;padding:6px 0}
.who{text-align:center;font-weight:700;font-size:13px;margin-top:8px;color:#d7cfc0}
.ring{position:relative}.ring:after{content:"";position:absolute;inset:-8px;border-radius:34px;border:2px solid rgba(217,83,79,.55);animation:pulse 1.6s infinite}
@keyframes pulse{0%{transform:scale(.96);opacity:.9}100%{transform:scale(1.08);opacity:0}}
.callid{background:#fff;color:#1e2a30;border-radius:14px;padding:12px 10px;margin:8px 7px;text-align:center}.callid b{display:block;font-size:14px}.callid span{font-size:11px;color:#8a8479}
.callid .row{display:flex;justify-content:space-around;margin-top:10px}.callid .row i{width:30px;height:30px;border-radius:50%;display:block}
/* news */
.stats{display:grid;gap:12px;margin-top:18px}.stat{display:flex;align-items:center;gap:14px;text-decoration:none;color:inherit;background:var(--night2);border:1px solid #2b3855;border-radius:16px;padding:14px 16px}
.stat strong{font:800 32px/1 Georgia,serif;color:var(--gold);min-width:116px}.stat span{font-size:14px;line-height:1.35;color:#d8d0c1}.stat small{display:block;color:#8d95a8;font-size:12px;margin-top:3px}
/* night tiles + features */
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:20px}.tile{background:var(--night2);border:1px solid #2b3855;border-radius:16px;padding:14px 8px;text-align:center;font-size:14px;font-weight:600}.tile svg{width:44px;height:44px;display:block;margin:0 auto 8px}
.feat{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:20px}.f{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px 10px;text-align:center;font-weight:700;font-size:16px}.f svg{width:46px;height:46px;display:block;margin:0 auto 8px}
.q{font:800 28px/1.18 Georgia,serif;text-align:center;margin:0}
/* form */
.card{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:22px;box-shadow:0 10px 30px rgba(35,48,58,.08)}
label{display:block;font-weight:700;margin:14px 0 6px;font-size:15px}
input[type=text],input[type=tel]{width:100%;padding:15px 13px;font-size:18px;border:1.5px solid var(--line);border-radius:12px;background:var(--cream);color:var(--ink)}
input:focus{outline:2px solid var(--teal2);border-color:var(--teal2)}
button.go{margin-top:16px;width:100%;padding:16px;font-size:19px;font-weight:800;border:0;border-radius:14px;background:var(--teal);color:#fff;cursor:pointer;box-shadow:0 8px 20px rgba(15,118,110,.28)}button.go[disabled]{opacity:.6}
.err{color:#b3261e;font-size:15px;min-height:20px;margin-top:8px}.fine{font-size:13px;color:var(--mut);margin:10px 0 0}.fine a{color:var(--mut)}
.hp{position:absolute;left:-9999px;height:0;overflow:hidden}.ok{display:none;text-align:center}.ok h3{font:800 28px/1.15 Georgia,serif;margin:0 0 12px}
.todo{display:flex;gap:12px;align-items:flex-start;text-align:left;background:var(--cream);border-radius:14px;padding:12px;margin:10px 0;font-size:16px}.todo i{font-style:normal;font-size:24px}
a.share{display:inline-block;margin-top:8px;padding:13px 18px;border-radius:12px;background:var(--teal);color:#fff;text-decoration:none;font-weight:800}
.honest{font-size:13px;color:var(--mut);text-align:center;margin:18px 0 8px}
.sticky{position:fixed;left:0;right:0;bottom:0;padding:10px 16px calc(10px + env(safe-area-inset-bottom));background:linear-gradient(rgba(255,248,238,0),var(--cream) 40%);z-index:5;transition:opacity .2s}
.sticky a{display:block;max-width:528px;margin:0 auto;text-align:center;padding:15px;border-radius:14px;background:var(--teal);color:#fff;font-weight:800;font-size:18px;text-decoration:none;box-shadow:0 8px 20px rgba(15,118,110,.3)}
.rv{opacity:0;transform:translateY(22px);transition:opacity .6s ease,transform .6s ease}.rv.on{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){.rv{opacity:1;transform:none;transition:none}.ring:after{animation:none}}
@media (min-width:700px){h1{font-size:54px}.sticky{display:none}}
</style></head><body>

<section class="hero"><div class="w">
<div class="top"><span class="brand"><span class="dot"></span>Robin</span><button class="lang" id="lang" type="button">हिंदी / Hinglish</button></div>
<h1 data-t="h1">Mom is alone.<br><em>You are far.</em></h1>
<p class="sub" data-t="hs">Robin is there when you cannot be.</p>
<svg viewBox="0 0 360 250" role="img" aria-label="A mother at home, her child in a distant city, a dotted line between them">
<circle cx="180" cy="136" r="112" fill="#fbe5c0"/>
<polygon points="12,96 84,46 156,96" fill="#d9784a"/><rect x="24" y="96" width="120" height="118" rx="8" fill="#fff" stroke="#e8d6b5" stroke-width="2"/>
<rect x="40" y="112" width="88" height="80" rx="6" fill="#ffe0a0"/><line x1="84" y1="112" x2="84" y2="192" stroke="#e7c27a" stroke-width="3"/><line x1="40" y1="152" x2="128" y2="152" stroke="#e7c27a" stroke-width="3"/>
<circle cx="84" cy="150" r="14" fill="#e2ab82"/><path d="M70 143 Q84 128 98 143 Q98 136 84 134 Q70 136 70 143Z" fill="#d6d3cf"/><circle cx="84" cy="130" r="6" fill="#d6d3cf"/>
<path d="M58 192 Q60 164 84 164 Q108 164 110 192Z" fill="#f2a93b"/><rect x="96" y="166" width="9" height="15" rx="2" fill="#23303a"/><rect x="98" y="168" width="5" height="9" rx="1" fill="#7dd3fc"/>
<g stroke="#d9534f" stroke-width="2.5" fill="none" stroke-linecap="round"><path d="M112 160 Q118 166 112 172"/><path d="M118 156 Q127 166 118 176"/></g>
<rect x="214" y="70" width="34" height="146" rx="3" fill="#2f3f55"/><rect x="254" y="104" width="40" height="112" rx="3" fill="#3a4c66"/><rect x="300" y="84" width="34" height="132" rx="3" fill="#2f3f55"/>
<g fill="#ffd27a"><rect x="220" y="84" width="6" height="8"/><rect x="232" y="84" width="6" height="8"/><rect x="220" y="102" width="6" height="8"/><rect x="262" y="118" width="6" height="8"/><rect x="276" y="118" width="6" height="8"/><rect x="262" y="136" width="6" height="8"/><rect x="306" y="98" width="6" height="8"/><rect x="318" y="116" width="6" height="8"/></g>
<rect x="254" y="150" width="40" height="30" rx="3" fill="#ffe9b8"/><circle cx="274" cy="157" r="7" fill="#e2ab82"/><rect x="266" y="164" width="16" height="13" rx="3" fill="#0f766e"/><path d="M262 178 L286 178 L283 171 L265 171Z" fill="#cbd5e1"/>
<path d="M150 120 C190 30 262 30 296 140" fill="none" stroke="#0f766e" stroke-width="2.5" stroke-dasharray="3 7" stroke-linecap="round"/>
<g><rect x="190" y="38" width="64" height="24" rx="12" fill="#0f766e"/><text x="222" y="55" text-anchor="middle" font-size="13" font-weight="700" fill="#fff" data-t="km">800 km</text></g>
</svg>
<a class="cta" href="#join" data-t="cta">Join the waitlist</a>
</div></section>

<section class="sec dark2"><div class="w">
<p class="kick rv" data-t="k1">4:10 pm · A Tuesday</p>
<h2 class="rv" data-t="h2a">An unknown number calls her.</h2>
<div class="phones rv"><div class="ph ring"><div class="bar"><i></i><span data-t="ph1">Unknown caller</span></div>
<div class="callid"><b data-t="cid">+92 ··· ····</b><span data-t="cid2">calling…</span><div class="row"><i style="background:#d9534f"></i><i style="background:#22c55e"></i></div></div>
<div class="chat" style="min-height:90px"><div class="b in" data-t="c1">"I am from the police."</div><div class="b in" data-t="c2">"Your son is in trouble."</div><div class="b in" data-t="c3">"Do not tell anyone. Do not hang up."</div></div></div></div>
<p class="cap rv" data-t="cap1">She is 68. She is scared. She does what he says.</p>
</div></section>

<section class="sec dark"><div class="w">
<p class="kick rv" data-t="k2">It has happened</p>
<h2 class="rv" data-t="h2b">Not a story we made up.</h2>
<div class="stats rv">
<a class="stat" href="https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud" target="_blank" rel="noopener"><strong>₹2.5 cr</strong><span data-t="n1">82-year-old, Chandigarh. "Digital arrest" fraud.<small>The Tribune</small></span></a>
<a class="stat" href="https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app" target="_blank" rel="noopener"><strong>₹3.95 lakh</strong><span data-t="n2">Mumbai senior. A "KYC" caller made him install an app.<small>Free Press Journal</small></span></a>
<a class="stat" href="https://www.freepressjournal.in/indore/upi-limit-scam-costs-pensioner-couple-nearly-6-lakh-in-indore" target="_blank" rel="noopener"><strong>₹6 lakh</strong><span data-t="n3">Indore pensioners. A call that showed their bank's name.<small>Free Press Journal</small></span></a></div>
<p class="cap" data-t="nf">Tap a card to read the report.</p>
</div></section>

<section class="sec dark2"><div class="w">
<p class="kick rv" data-t="k3">And the quiet days</p>
<h2 class="rv" data-t="h2c">At 3 am, who finds out first?</h2>
<div class="tiles rv">
<div class="tile"><svg viewBox="0 0 48 48"><rect x="6" y="18" width="36" height="14" rx="7" fill="#f2a93b" transform="rotate(-30 24 25)"/><rect x="24" y="12" width="18" height="14" rx="7" fill="#f6f1e7" transform="rotate(-30 24 25)"/></svg><span data-t="t3a">A missed tablet</span></div>
<div class="tile"><svg viewBox="0 0 48 48"><path d="M30 8a16 16 0 1 0 10 28A13 13 0 0 1 30 8z" fill="#f2a93b"/><circle cx="36" cy="12" r="2" fill="#f6f1e7"/><circle cx="40" cy="20" r="1.5" fill="#f6f1e7"/></svg><span data-t="t3b">A fall in the night</span></div>
<div class="tile"><svg viewBox="0 0 48 48"><rect x="14" y="6" width="20" height="36" rx="4" fill="none" stroke="#f6f1e7" stroke-width="3"/><line x1="8" y1="40" x2="40" y2="8" stroke="#d9534f" stroke-width="4" stroke-linecap="round"/></svg><span data-t="t3c">A phone no one answers</span></div></div>
<p class="cap rv" data-t="cap3">"I am fine, beta." She will not say more.</p>
</div></section>

<section class="sec"><div class="w">
<p class="q rv" data-t="q">You cannot be there every day.<br><span style="color:var(--teal)">Robin can.</span></p>
<div class="phones rv" style="margin-top:26px">
<div><div class="ph"><div class="bar"><i></i><span data-t="p1h">Robin</span></div><div class="chat">
<div class="b out"><div class="wave"><span class="play"></span><s style="height:6px"></s><s style="height:12px"></s><s style="height:16px"></s><s style="height:9px"></s><s style="height:14px"></s><s style="height:7px"></s><s style="height:11px"></s></div></div>
<div class="b in" data-t="p1b">Namaste Maa! Did you take your tablet today?</div><div class="b out" data-t="p1c">Yes, beta.</div></div></div><div class="who" data-t="w1" style="color:var(--ink)">Maa's WhatsApp</div></div>
<div><div class="ph" style="background:#fdf6ec"><div class="bar" style="background:#23303a"><i></i><span data-t="p2h">You</span></div>
<div class="alert"><b data-t="a1">Robin · now</b><span data-t="a2">Maa has been on a call with a stranger for 22 minutes.</span><div class="btn" data-t="a3">Call Maa</div></div>
<div class="alert" style="border-left-color:var(--teal)"><b style="color:var(--teal)" data-t="a4">Robin · 9 am</b><span data-t="a5">Maa is fine. Tablet taken.</span></div></div><div class="who" data-t="w2" style="color:var(--ink)">Your phone</div></div></div>
<p class="cap rv" style="color:var(--mut)" data-t="cap4">She talks. You know.</p>
<div class="feat rv">
<div class="f"><svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="9" fill="#f2a93b"/><g stroke="#f2a93b" stroke-width="3" stroke-linecap="round"><line x1="24" y1="5" x2="24" y2="11"/><line x1="24" y1="37" x2="24" y2="43"/><line x1="5" y1="24" x2="11" y2="24"/><line x1="37" y1="24" x2="43" y2="24"/><line x1="10" y1="10" x2="14" y2="14"/><line x1="34" y1="34" x2="38" y2="38"/><line x1="38" y1="10" x2="34" y2="14"/><line x1="14" y1="34" x2="10" y2="38"/></g></svg><span data-t="f1">Daily check-in</span></div>
<div class="f"><svg viewBox="0 0 48 48"><rect x="6" y="18" width="36" height="14" rx="7" fill="#0f766e" transform="rotate(-30 24 25)"/><rect x="24" y="12" width="18" height="14" rx="7" fill="#99f6e4" transform="rotate(-30 24 25)"/></svg><span data-t="f2">Medicine reminders</span></div>
<div class="f"><svg viewBox="0 0 48 48"><path d="M24 5 L40 11 V24 C40 33 33 40 24 43 C15 40 8 33 8 24 V11Z" fill="#0f766e"/><path d="M16 24 l6 6 l11 -12" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg><span data-t="f3">Scam help</span></div>
<div class="f"><svg viewBox="0 0 48 48"><path d="M24 6c-8 0-13 6-13 14v8l-4 6h34l-4-6v-8c0-8-5-14-13-14z" fill="#d9534f"/><circle cx="24" cy="41" r="4" fill="#d9534f"/></svg><span data-t="f4">Alerts to you</span></div></div>
</div></section>

<section class="sec" id="join" style="padding-top:8px"><div class="w"><div class="card"><div id="formwrap">
<h2 style="font-size:28px" data-t="jh">Be the first to know.</h2><p class="fine" style="font-size:15px;margin:0 0 4px" data-t="jf">Robin opens soon. One WhatsApp message. No payment.</p>
<form id="f" autocomplete="on" novalidate>
<label for="name" data-t="ln">Your name</label><input id="name" name="name" type="text" maxlength="40" autocomplete="given-name" required>
<label for="phone" data-t="lp">Your WhatsApp number</label><input id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="98765 43210  /  +1 415 555 0100" required>
<div class="hp"><label for="website">Website</label><input id="website" name="website" type="text" tabindex="-1" autocomplete="off"></div>
<div class="err" id="err" role="alert"></div>
<button class="go" id="go" type="submit" data-t="btn">Join the waitlist</button>
<p class="fine" data-t="cons">By joining you agree that Robin may message you on WhatsApp about the launch. Your details are used only for this and deleted on request.</p>
<p class="fine"><a href="privacy" data-t="priv">How we use your details</a></p></form></div>
<div class="ok" id="ok"><h3 data-t="ok1">You are on the list.</h3>
<div class="todo"><i>📞</i><span data-t="ok2">Tonight, call your parents. Ask: "Has anyone ever called asking for money, an OTP or to install an app?"</span></div>
<div class="todo"><i>🛑</i><span data-t="ok3">Tell them: no officer "arrests" anyone on a phone or video call. Hang up, and call you.</span></div>
<a class="share" id="share" href="#" data-t="share">Send this to a sibling</a></div></div>
<p class="honest" data-t="honest">Robin is not live yet, and it is not an emergency service. In an emergency call 112. Robin is an AI assistant.</p></div></section>

<div class="sticky" id="sticky"><a href="#join" data-t="stk">Join the waitlist</a></div>
<script>
const T={en:{},hi:{
h1:"Maa akeli hain.<br><em>Aap door hain.</em>",hs:"Jab aap nahi ho sakte, Robin hai.",km:"800 km",km2:"",cta:"Waitlist mein judiye",
k1:"Dopahar 4:10 · ek mangalwar",h2a:"Ek anjaan number se unhe call aata hai.",ph1:"Anjaan caller",cid2:"call aa rahi hai…",c1:"\"Main police se bol raha hoon.\"",c2:"\"Aapka beta musibat mein hai.\"",c3:"\"Kisi ko mat batana. Phone mat kaatna.\"",cap1:"Wo 68 saal ki hain. Wo dar gayi hain. Wo wahi karti hain jo wo kehta hai.",
k2:"Ye ho chuka hai",h2b:"Humne ye kahani nahi banayi.",n1:"82 saal ki mahila, Chandigarh. \"Digital arrest\" fraud.<small>The Tribune</small>",n2:"Mumbai ke senior. \"KYC\" wale caller ne app install karwayi.<small>Free Press Journal</small>",n3:"Indore ke pensioners. Bank ka naam dikhane wali call.<small>Free Press Journal</small>",nf:"Report padhne ke liye card dabaiye.",
k3:"Aur shaant din",h2c:"Raat 3 baje, sabse pehle kise pata chalega?",t3a:"Chhooti hui dawai",t3b:"Raat mein gir jaana",t3c:"Phone jo koi nahi uthata",cap3:"\"Main theek hoon, beta.\" Wo aur kuch nahi kahengi.",
q:"Aap har din wahan nahi ho sakte.<br><span style=\"color:var(--teal)\">Robin ho sakta hai.</span>",p1b:"Namaste Maa! Aaj dawai li?",p1c:"Haan, beta.",w1:"Maa ka WhatsApp",p2h:"Aap",a1:"Robin · abhi",a2:"Maa 22 minute se ek ajnabi se baat kar rahi hain.",a3:"Maa ko call karein",a4:"Robin · subah 9 baje",a5:"Maa theek hain. Dawai li.",w2:"Aapka phone",cap4:"Wo baat karti hain. Aapko pata chalta hai.",
f1:"Roz ka check-in",f2:"Dawai ke reminder",f3:"Scam se madad",f4:"Aapko alert",
jh:"Sabse pehle khabar paiye.",jf:"Robin jald khulega. Ek WhatsApp message. Koi payment nahi.",ln:"Aapka naam",lp:"Aapka WhatsApp number",btn:"Waitlist mein judiye",cons:"Judne par aap maante hain ki Robin launch ke baare mein aapko WhatsApp par message kar sakta hai. Aapki details sirf isi ke liye use hongi aur kehne par delete ho jayengi.",priv:"Hum aapki details kaise use karte hain",
ok1:"Aap list mein hain.",ok2:"Aaj raat apne parents ko call kijiye. Poochiye: \"Kya kisi ne kabhi paise, OTP ya koi app install karne ke liye call kiya?\"",ok3:"Unhe batayiye: koi officer phone ya video call par kisi ko \"arrest\" nahi karta. Phone kaat dein, aur aapko call karein.",share:"Kisi bhai-behen ko bhejiye",
honest:"Robin abhi live nahi hai, aur ye emergency service nahi hai. Emergency mein 112 par call karein. Robin ek AI assistant hai.",stk:"Waitlist mein judiye"}};
const EN={};document.querySelectorAll("[data-t]").forEach(e=>{EN[e.dataset.t]=e.innerHTML});T.en=EN;
let cur="en";function setLang(l){cur=l;document.documentElement.lang=l==="hi"?"hi-Latn":"en";document.querySelectorAll("[data-t]").forEach(e=>{const v=T[l][e.dataset.t];if(v!==undefined&&v!=="")e.innerHTML=v});document.getElementById("lang").textContent=l==="hi"?"English":"हिंदी / Hinglish"}
document.getElementById("lang").onclick=()=>setLang(cur==="en"?"hi":"en");
const src=new URLSearchParams(location.search).get("src")||"";
const errs={en:{name:"Please enter your name.",phone:"Please enter a valid WhatsApp number.",busy:"Something went wrong. Please try again in a minute."},hi:{name:"Apna naam likhiye.",phone:"Sahi WhatsApp number likhiye.",busy:"Kuch gadbad hui. Ek minute baad dobara try karein."}};
const rv=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("on");rv.unobserve(e.target)}}),{threshold:.15});document.querySelectorAll(".rv").forEach(e=>rv.observe(e));
const io=new IntersectionObserver(es=>{document.getElementById("sticky").style.opacity=es[0].isIntersecting?"0":"1";document.getElementById("sticky").style.pointerEvents=es[0].isIntersecting?"none":"auto"});io.observe(document.getElementById("join"));
document.getElementById("f").addEventListener("submit",async ev=>{ev.preventDefault();const err=document.getElementById("err");err.textContent="";
const g=id=>document.getElementById(id).value.trim();const body={name:g("name"),phone:g("phone"),website:g("website"),src:src,v:"{{VARIANT}}",consent:true};const E=errs[cur];
if(!body.name){err.textContent=E.name;return}if(body.phone.replace(/\D/g,"").length<8){err.textContent=E.phone;return}
const b=document.getElementById("go");b.disabled=true;
try{const r=await fetch("join",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});if(!r.ok){const j=await r.json().catch(()=>({}));err.textContent=(E[j.field]||E.busy);b.disabled=false;return}
document.getElementById("formwrap").style.display="none";document.getElementById("ok").style.display="block";document.getElementById("sticky").style.display="none";
const msg=cur==="hi"?"Robin: un parents ke liye jinhe aap har ghante call nahi kar sakte. Waitlist mein judiye: ":"Robin: for the parents you cannot call every hour. Join the waitlist: ";
document.getElementById("share").href="https://wa.me/?text="+encodeURIComponent(msg+location.origin+location.pathname+"?src=share");document.getElementById("join").scrollIntoView()}catch(e){err.textContent=E.busy;b.disabled=false}});
</script></body></html>
"""

PRIVACY = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>Robin waitlist: how we use your details</title>
<style>body{font:17px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;max-width:640px;margin:0 auto;padding:20px 16px 48px;background:#fff8ee;color:#23303a}h1{font-size:26px}a{color:inherit}</style></head><body>
<h1>How we use your details</h1>
<p><strong>What we ask for:</strong> your name and WhatsApp number. We also count page visits per day and per link, without saving your address or device.</p>
<p><strong>Why:</strong> only to message you on WhatsApp about the Robin waitlist and launch. We do not sell your details and do not share them for advertising.</p>
<p><strong>Where it is kept:</strong> on our own server, in a protected file. Only the Robin team can read it.</p>
<p><strong>How long:</strong> until Robin has launched and you have been invited, plus 90 days, or until you ask us to delete it.</p>
<p><strong>Delete or change it:</strong> {CONTACT}</p>
<p><strong>Not an emergency service:</strong> Robin is not live yet. In an emergency call 112.</p>
<p><a href=".">Back to the waitlist</a></p></body></html>
"""
