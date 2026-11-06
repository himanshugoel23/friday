# ruff: noqa: E501
"""Landing page variant S2 (docs/ROBIN_LANDING_BRIEF.md, revision 2). English only. The token {{VARIANT}} is replaced by the router."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><meta name="color-scheme" content="light"><meta name="theme-color" content="#fbfaf6"><title>Robin waitlist</title>
<meta name="description" content="Reported scams, and what Robin does at each moment. Join the waitlist.">
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

:root{--bg:#fbfaf6;--ink:#1b1d1e;--mut:#464b4c;--link:#7b2d2d;--acc:#7b2d2d;--btn:#1b1d1e;--btnc:#fff;--btnsh:0 10px 22px rgba(27,29,30,.2);--brandc:#1b1d1e;
--card:#fff;--line:#dcd8cd;--inb:#aaa699;--inbg:#fff;--err:#9c2b1f;--focus:#7b2d2d;--rad:6px;--rad2:10px;--rad3:8px;--bezel:#2b2f30;--bar:#1f5a3a;--avbg:#1f5a3a;
--chatbg:#f1f3ee;--outbub:#e5ecdf;--footbg:#1b1d1e;--footc:#d4d2c9;--gr:#e8f0e9;--grl:#bcd3c2;--grt:#1f5a3a;
--serif:Georgia,"Times New Roman","Noto Serif",serif;--hfont:700 24px var(--serif);
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue","Noto Sans","Noto Sans Devanagari","Nirmala UI",Arial,sans-serif}
.top{border-bottom:1px solid var(--ink);padding:16px 0}
.hero{padding:34px 0 8px}
h1{font:700 36px/1.08 var(--serif);letter-spacing:-.8px;max-width:13em}
.sub{margin:16px 0 24px;font-size:19px;line-height:1.55;max-width:34em;color:#323637}
.trust{margin-top:18px;font-size:15.5px;color:var(--mut);max-width:34em;padding-top:14px;border-top:1px solid var(--line)}
.pairs{display:grid;gap:44px;margin-top:34px}
.pair{display:grid;gap:0;justify-items:stretch}
.rep{background:#fff;border:1px solid var(--ink);border-top:5px solid var(--acc);padding:22px 22px 20px;position:relative}
.rep .tag{display:inline-block;font:700 12px var(--sans);letter-spacing:1.3px;text-transform:uppercase;color:var(--acc);margin-bottom:12px}
.rep h3{font:700 23px/1.25 var(--serif);margin-bottom:14px}
.rep .src{font-size:14.5px;color:var(--mut);padding-top:12px;border-top:1px solid var(--line)}.rep .src span{font:700 13px var(--sans);letter-spacing:1.2px;text-transform:uppercase;color:var(--ink)}
.rl{display:inline-block;margin-top:12px;font-weight:700;color:var(--link);text-underline-offset:3px;min-height:24px;font-size:15.5px}
.cn{height:44px;display:flex;justify-content:center}.cn svg{height:44px;width:24px;overflow:visible}
.fr{background:var(--gr);border:1px solid var(--grl);border-radius:14px;padding:18px 16px 20px;display:flex;flex-direction:column;gap:14px}
.fr .mo{font-size:15.5px;line-height:1.5;color:#223b2c}.fr .mo b{font-weight:700;color:var(--grt)}
.scr{background:var(--chatbg);border-radius:18px;overflow:hidden;box-shadow:0 8px 22px rgba(20,50,30,.14);border:1px solid #d3ddd4;max-width:360px;width:100%;align-self:center}
.scr .bar{padding:12px 14px 10px}
.st{display:flex;align-items:center;gap:8px;font:600 13px var(--sans);color:var(--grt);padding:0 12px 12px}.st i{width:8px;height:8px;border-radius:50%;background:#2d8a58}
.scr .alertc{margin:12px}
.js .pair .m,.js .pair .alertc,.js .pair .st{opacity:0}
.js .pair.on .m,.js .pair.on .alertc,.js .pair.on .st{animation:pop .6s ease forwards;animation-delay:calc(var(--n)*.8s + .3s)}
@keyframes pop{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.note{margin-top:26px;font-size:15px;color:var(--mut);text-align:center}
.calls{background:#efece3;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.calls .w{display:flex;gap:20px;align-items:flex-start}.calls p{font:500 20px/1.5 var(--serif);max-width:38em}.calls p+p{margin-top:10px;font:400 17px/1.5 var(--sans);color:var(--mut)}
.pm{display:grid;gap:0;counter-reset:p;border-top:2px solid var(--ink)}
.pm li{counter-increment:p;padding:18px 0 18px 46px;border-bottom:1px solid var(--line);font:600 21px/1.3 var(--serif);position:relative}
.pm li:before{content:counter(p,decimal-leading-zero);position:absolute;left:0;top:19px;font:700 15px var(--sans);color:var(--acc);letter-spacing:.5px}
.hw{display:grid;gap:0}.hw li{display:flex;gap:16px;padding:16px 0;border-bottom:1px solid var(--line);align-items:baseline}
.hw b{font:700 14px var(--sans);width:30px;height:30px;border-radius:50%;background:var(--ink);color:#fff;display:grid;place-items:center;flex:none;align-self:center}.hw span{font:600 20px/1.3 var(--serif)}
.two{display:grid;gap:44px}
.hd{font:700 13px var(--sans);letter-spacing:1.6px;text-transform:uppercase;color:var(--acc);margin-bottom:6px}
@media (min-width:760px){
 h1{font-size:60px}.hero{padding-top:50px}.pair{grid-template-columns:1fr 64px 1fr;align-items:stretch}
 .cn{height:auto;width:64px;align-items:center}.cn svg{width:64px;height:24px}
 .rep{display:flex;flex-direction:column}.rep h3{font-size:26px}.rep .src{margin-top:auto}
 .fr{justify-content:center}
 .two{grid-template-columns:1fr 1fr;gap:70px}
}

.cnh{display:none}.cnv{display:block}
@media (min-width:760px){.cnh{display:block}.cnv{display:none}}
</style></head><body>
<header class="hero"><div class="w"><div class="top"><span class="brand"><svg viewBox="0 0 40 40" aria-hidden="true"><rect x="1.5" y="1.5" width="37" height="37" rx="10" fill="#7b2d2d"/><path d="M12 28 V12 h9 a6 6 0 0 1 0 12 h-9 M20 24 l7 4" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>Robin</span></div>
<div style="padding-top:34px"><h1>These scams happened. Here is how Robin helps.</h1>
<p class="sub">Robin helps protect your parents from phone scams and emergencies. See three reported cases and what Robin does at each moment.</p>
<a class="btn" href="#join">Join the waitlist</a><p class="trust">Your parents are told, can stop it any time, and Robin does not read their chats or record their phone calls.</p></div>
<ul class="pairs"><li class="pair rv"><div class="rep"><p class="tag">Digital-arrest call</p><h3>Chandigarh's elderly woman loses Rs 2.5 crore in digital arrest fraud</h3><p class="src"><span>The Tribune</span> <time>4 Jun 2025</time></p><a class="rl" href="https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><div class="cn"><span class="cnv"><svg viewBox="0 0 24 44" aria-hidden="true"><path d="M12 0 V36" stroke="#7b2d2d" stroke-width="2"/><path d="M5 30 L12 40 L19 30" fill="none" stroke="#7b2d2d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="cnh"><svg viewBox="0 0 64 24" aria-hidden="true"><path d="M0 12 H54" stroke="#7b2d2d" stroke-width="2"/><path d="M46 5 L56 12 L46 19" fill="none" stroke="#7b2d2d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div><div class="fr"><p class="mo"><b>Moment:</b> the caller says an 'arrest' is under way. Your parent forwards the number to Robin; Robin replies that no agency arrests anyone on a phone or video call, and alerts you.</p><div class="scr"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div><div class="chat"><div class="m out" style="--n:0"><span class="fw">&#8618; Forwarded</span>+91 98&#8226;&#8226;&#8226;&#8226;&#8226; &#8226;&#8226;210</div><div class="m in" style="--n:1"><span class="chip amb">Looks like a known scam pattern</span><span class="hi" lang="hi">फोन या वीडियो कॉल पर कोई एजेंसी गिरफ्तारी नहीं करती।</span><span class="cap">No agency arrests anyone on a phone or video call.</span></div></div><p class="st" style="--n:2"><i></i>Alert sent to you</p></div></div></li><li class="pair rv"><div class="rep"><p class="tag">Fake KYC and a remote-access app</p><h3>Mumbai: Senior citizen loses Rs 3.95 lakh to KYC fraud after downloading AnyDesk app</h3><p class="src"><span>Free Press Journal</span> <time>12 Jan 2022</time></p><a class="rl" href="https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><div class="cn"><span class="cnv"><svg viewBox="0 0 24 44" aria-hidden="true"><path d="M12 0 V36" stroke="#7b2d2d" stroke-width="2"/><path d="M5 30 L12 40 L19 30" fill="none" stroke="#7b2d2d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="cnh"><svg viewBox="0 0 64 24" aria-hidden="true"><path d="M0 12 H54" stroke="#7b2d2d" stroke-width="2"/><path d="M46 5 L56 12 L46 19" fill="none" stroke="#7b2d2d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div><div class="fr"><p class="mo"><b>Moment:</b> a caller asks to install a screen-sharing app. With the optional Android app, Robin flags it and alerts you with a [Call parent] button.</p><div class="scr"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div><div class="alertc" style="--n:0"><b>ROBIN ALERT &middot; OPTIONAL ANDROID APP</b>A screen-sharing app was opened on your parent's phone.<span class="cb">Call parent</span></div></div></div></li><li class="pair rv"><div class="rep"><p class="tag">Call showing a bank's name</p><h3>UPI Limit Scam Costs Pensioner Couple Nearly ₹6 Lakh In Indore</h3><p class="src"><span>Free Press Journal</span> <time>30 Sep 2026</time></p><a class="rl" href="https://www.freepressjournal.in/indore/upi-limit-scam-costs-pensioner-couple-nearly-6-lakh-in-indore" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><div class="cn"><span class="cnv"><svg viewBox="0 0 24 44" aria-hidden="true"><path d="M12 0 V36" stroke="#7b2d2d" stroke-width="2"/><path d="M5 30 L12 40 L19 30" fill="none" stroke="#7b2d2d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="cnh"><svg viewBox="0 0 64 24" aria-hidden="true"><path d="M0 12 H54" stroke="#7b2d2d" stroke-width="2"/><path d="M46 5 L56 12 L46 19" fill="none" stroke="#7b2d2d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div><div class="fr"><p class="mo"><b>Moment:</b> the screen shows a bank's name. Robin never calls a money request safe; it advises hanging up and calling the number on the card, and alerts you.</p><div class="scr"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div><div class="chat"><div class="m in" style="--n:0"><span class="hi" lang="hi">कॉल काट दें और कार्ड पर छपे नंबर पर खुद फोन करें।</span><span class="cap">Hang up and call the number printed on your card.</span></div></div><p class="st" style="--n:1"><i></i>Alert sent to you</p></div></div></li></ul><p class="note">News reports, linked in full. Robin is not mentioned in them.</p></div></header>

<section class="sec calls" style="margin-top:56px"><div class="w"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#7b2d2d" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8 h7 l3 8 l-4 3 a20 20 0 0 0 9 9 l3 -4 l8 3 v7 a4 4 0 0 1 -4 4 C21 38 8 25 8 12 a4 4 0 0 1 4 -4z"/></svg><div><p>Calls your parent cannot take: set up call forwarding once, and Robin answers as an AI assistant and sends a summary. If it sounds urgent, your missed call is highlighted.</p><p>Also helps with calls that sound like a family member asking for money.</p></div></div></section>

<section class="sec"><div class="w two"><div><p class="hd">What Robin does</p><ul class="pm"><li>Spots known scam patterns in forwards</li><li>Alerts you when money is involved</li><li>Highlights urgent missed calls</li><li>Answers when your parent cannot</li></ul><p class="fine" style="margin-top:14px">Plus a friendly daily check-in and medicine reminders.</p></div>
<div><p class="hd">How it works</p><ol class="hw"><li><b>1</b><span>Forward it to Robin</span></li><li><b>2</b><span>Robin explains, in their language</span></li><li><b>3</b><span>You are alerted if it matters</span></li></ol></div></div></section>

<section class="sec" style="padding-top:8px"><div class="w"><div class="faqs rv">
<details class="faq"><summary>Do these cases mean Robin would have prevented them?</summary><p>No one can promise that. Robin helps spot warning signs and tells you early; your parent still decides.</p></details>
<details class="faq"><summary>Is this surveillance?</summary><p>No. Parents are told, can stop it any time, and Robin does not read chats or record calls. You see alerts and summaries, not messages.</p></details>
<details class="faq"><summary>Is Robin a person?</summary><p>No, an AI assistant. No human desk at launch.</p></details>
<details class="faq"><summary>Can my parent say no?</summary><p>Yes, at any time. Robin then tells you.</p></details>
<details class="faq"><summary>What does it cost?</summary><p>Waitlist is free. No price is announced yet.</p></details>
<details class="faq"><summary>Is it an emergency service?</summary><p>No. Call 112 in an emergency. The SOS button alerts you; it does not replace emergency help.</p></details>
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
<div class="ok" id="ok" aria-live="polite"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="30" fill="#1f5a3a"/><path d="M19 33l9 9 17-20" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>
<p>You are on the list. Know a sibling who looks after the same parents? Send them this page if you think it would help.</p><a class="btn share" id="share" href="#" target="_blank" rel="noopener">Share on WhatsApp</a></div>
</div></div></section>
<footer class="foot"><div class="w"><p>Robin is an AI assistant, not a person. It is not an emergency service: in an emergency call 112. Robin is not live yet.</p><p><a href="privacy">How we use your details</a></p></div></footer>
<div class="sticky" id="sticky"><a class="btn" href="#join">See how Robin responds: join the waitlist</a></div>
<script>
document.documentElement.className+=" js";
const ERR={name:"Please add your name.",phone:"That number does not look right. If you are abroad, add the country code.",busy:"That did not go through. Please try again in a minute."};
const MSG="Reported phone scams, and what Robin does at each moment. Join the waitlist: ";
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
