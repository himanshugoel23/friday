# ruff: noqa: E501
"""Landing page variant C (docs/ROBIN_LANDING_BRIEF.md). Generated look, static content. The token {{VARIANT}} is replaced by the router."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><meta name="color-scheme" content="light"><title>Robin waitlist</title>
<meta name="description" content="A day with Robin, in three moments. Join the waitlist.">
<style>
*{box-sizing:border-box}html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 var(--sans);overflow-x:hidden;padding-bottom:92px}
.w{max-width:1100px;margin:0 auto;padding:0 20px}.n{max-width:640px;margin-left:auto;margin-right:auto}
a{color:var(--link)}img,svg{max-width:100%}
:focus-visible{outline:3px solid var(--focus);outline-offset:3px;border-radius:6px}
h1,h2,h3,p{margin:0}
.top{display:flex;justify-content:space-between;align-items:center;padding:14px 0 0}
.brand{display:flex;align-items:center;gap:9px;font-weight:800;font-size:23px;letter-spacing:.2px;color:var(--brandtxt)}
.brand svg{width:34px;height:34px;flex:none}
button.lang{min-height:44px;padding:0 16px;border-radius:999px;border:1.5px solid var(--langb);background:var(--langbg);color:var(--langc);font:600 15px var(--sans);cursor:pointer}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:56px;padding:0 28px;border-radius:16px;background:var(--btn);color:var(--btnc);font:800 19px var(--sans);text-decoration:none;border:0;cursor:pointer;box-shadow:var(--btnsh)}
.btn:hover{filter:brightness(1.06)}
.sec{padding:52px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:26px;padding:26px 22px;box-shadow:0 14px 34px rgba(40,50,45,.09)}
/* form */
#join{scroll-margin-top:12px}
.card h2.promise{font:var(--hfont);font-size:25px;line-height:1.25;margin:0 0 6px;color:var(--ink)}
label{display:block;font-weight:700;margin:16px 0 6px;font-size:16px}
input[type=text],input[type=tel]{width:100%;min-height:56px;padding:12px 14px;font:18px var(--sans);border:2px solid var(--inb);border-radius:14px;background:var(--inbg);color:var(--ink)}
input::placeholder{font-size:15px;color:#6b6f6c}input:focus{outline:3px solid var(--focus);outline-offset:1px;border-color:var(--focus)}
button.go{margin-top:16px;width:100%;min-height:58px;font-size:20px}button.go[disabled]{opacity:.65;cursor:wait}
.err{color:var(--err);font-weight:600;font-size:16px;min-height:48px;margin-top:8px;line-height:1.35}
.fine{font-size:15px;color:var(--mut);margin:8px 0 0;line-height:1.5}.fine.b{font-weight:700;color:var(--ink)}.fine a{color:var(--mut)}
.hp{position:absolute;left:-9999px;top:auto;width:1px;height:1px;overflow:hidden}
.ok{display:none;text-align:center;padding:6px 0}.ok p{font-size:19px;line-height:1.5;margin:10px 0 18px}.ok svg{width:64px;height:64px}
a.share{min-width:220px}
/* faq */
.faqs{display:grid;gap:12px;max-width:760px;margin:0 auto}
details.faq{background:var(--card);border:1px solid var(--line);border-radius:18px;overflow:hidden}
details.faq summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:60px;padding:14px 18px;font-weight:700;font-size:18px;line-height:1.3}
details.faq summary::-webkit-details-marker{display:none}
details.faq summary:after{content:"+";flex:none;width:32px;height:32px;border-radius:50%;background:var(--faqi);color:var(--faqc);display:grid;place-items:center;font-size:22px;font-weight:600;line-height:1}
details.faq[open] summary:after{content:"\2212"}
details.faq p{padding:0 18px 18px;color:var(--mut);font-size:17px}
/* scam + footer */
.scam{font-size:15.5px;color:var(--mut);line-height:1.6;max-width:640px;margin:0 auto;text-align:center}.scam a{color:var(--mut);text-underline-offset:3px}
.foot{padding:30px 0 40px;font-size:15px;color:var(--mut);text-align:center;line-height:1.6}.foot p{max-width:620px;margin:0 auto 10px}.foot a{color:var(--mut)}
/* phone mock-up */
.ph{width:228px;border:7px solid #1f2b29;border-radius:34px;background:var(--chatbg);overflow:hidden;position:relative;box-shadow:0 20px 40px rgba(20,35,30,.28);color:#1d2a27;text-align:left}
.ph:before{content:"";position:absolute;top:0;left:50%;width:52px;height:10px;margin-left:-26px;background:#1f2b29;border-radius:0 0 10px 10px;z-index:2}
.bar{background:var(--bar);color:#fff;padding:22px 12px 9px;display:flex;align-items:center;gap:9px;font-weight:700;font-size:15px;line-height:1.15}
.bar small{display:block;font-weight:400;font-size:11.5px;opacity:.92}
.av{width:32px;height:32px;border-radius:50%;background:var(--avbg);color:#1b2b27;display:grid;place-items:center;font-weight:800;font-size:16px;flex:none}
.chat{padding:11px 9px 13px;display:flex;flex-direction:column;gap:8px}
.m{font-size:14px;line-height:1.32;padding:8px 11px;border-radius:13px;max-width:90%;color:#1d2a27;box-shadow:0 1px 1px rgba(0,0,0,.1)}
.in{background:#fff;border-top-left-radius:3px;align-self:flex-start}.out{background:var(--outbub);border-top-right-radius:3px;align-self:flex-end}
.vn{display:flex;align-items:center;gap:7px;min-width:164px}
.pl{width:0;height:0;border-left:11px solid var(--wave);border-top:7px solid transparent;border-bottom:7px solid transparent;flex:none;margin-left:2px}
.wv{display:flex;align-items:center;gap:2px;height:24px;flex:1}.wv s{display:block;width:3px;border-radius:2px;background:var(--wave);transform-origin:center}
.dur{font-size:11.5px;color:#4a5a56}
.sticky{position:fixed;left:0;right:0;bottom:0;z-index:20;padding:12px 16px calc(12px + env(safe-area-inset-bottom));background:linear-gradient(rgba(255,255,255,0),var(--bg) 38%);transition:opacity .25s}
.sticky.hide{opacity:0;pointer-events:none}.sticky .btn{display:flex;width:100%;max-width:520px;margin:0 auto}
.js .rv{opacity:0;transform:translateY(20px);transition:opacity .7s ease,transform .7s ease}.js .rv.on{opacity:1;transform:none}
@media (min-width:760px){.sticky{display:none}body{padding-bottom:0}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*:before,*:after{animation:none!important;transition:none!important}.js .rv{opacity:1;transform:none}}

:root{--bg:#fbf8f3;--ink:#16343a;--mut:#455d62;--link:#0f5c63;--brandtxt:#0f5c63;--btn:#0f5c63;--btnc:#fff;--btnsh:0 10px 22px rgba(15,92,99,.28);
--card:#fff;--line:#e8e0d2;--inb:#c4bbab;--inbg:#fff;--err:#9c2b1f;--focus:#0f5c63;--langb:#c8bfae;--langbg:#fff;--langc:#16343a;
--faqi:#fdeab5;--faqc:#0f5c63;--bar:#075e54;--avbg:#f6b31c;--chatbg:#efe7dd;--outbub:#d9fdd3;--wave:#128c7e;--gold:#f6b31c;--lil:#e8e0f6;--blush:#fde4e1;
--hfont:800 26px/1.2 "Avenir Next","Century Gothic","Segoe UI",system-ui,"Noto Sans Devanagari","Nirmala UI",sans-serif;
--sans:"Avenir Next","Segoe UI",system-ui,-apple-system,Roboto,"Noto Sans","Noto Sans Devanagari","Nirmala UI",Mangal,Helvetica,Arial,sans-serif}
.btn{border-radius:14px}
.hero{text-align:center;background:linear-gradient(180deg,#fff3d6 0,#fbf8f3 100%)}
.hero .top{text-align:left}
h1{font:800 40px/1.08 var(--sans);letter-spacing:-.8px;margin:26px auto 12px;max-width:14em;color:#0f3f46}
h1 em{font-style:normal;color:#0f5c63;background:linear-gradient(transparent 66%,#f6b31c 66%)}
.sub{font-size:20px;line-height:1.5;color:#34505a;margin:0 auto 22px;max-width:28em}
.tour{padding:22px 0 40px;position:relative}
.arc{display:none;width:100%;height:auto;margin-bottom:-6px}
.mcs{position:relative;display:grid;gap:20px}
.mcs:before{content:"";position:absolute;left:26px;top:30px;bottom:30px;border-left:5px dotted #eab52c}
.mc{position:relative;display:grid;grid-template-columns:56px 1fr;column-gap:14px;row-gap:10px;text-align:left;align-items:start}
.sunic{grid-row:1;grid-column:1;width:56px;height:56px;position:relative;z-index:1}
.sunic svg{display:block;width:56px;height:56px}
.mc h2{grid-column:2;font:800 22px/1.25 var(--sans);color:#0f3f46;align-self:center;min-height:56px;display:flex;align-items:center}
.mb{grid-column:2;border-radius:28px;padding:18px 14px 20px;display:flex;flex-direction:column;align-items:center;gap:12px;border:1px solid var(--line)}
.mb.t{background:#fff6dc}.mb.u{background:var(--lil)}.mb.m{background:#fff}
.who{font-weight:800;font-size:14px;letter-spacing:.4px;text-transform:uppercase;color:#0f3f46;padding:6px 14px;border-radius:999px;background:#fff;border:1.5px solid #0f5c63}
.u .who{background:#fff;border-color:#5b4a96;color:#3b2f6b}
.phw{position:relative;padding-top:10px}
.prev{position:absolute;left:-6px;top:0;z-index:3;background:#f6b31c;color:#2a2008;font:800 13px var(--sans);padding:5px 12px;border-radius:999px;box-shadow:0 2px 6px rgba(0,0,0,.2)}
.u .ph{--bar:#0f5c63;--chatbg:#f3effb;--outbub:#fff}
.u .bar{background:#0f5c63}
.lk{display:flex;align-items:center;gap:9px;background:#fff;border-radius:10px;padding:8px;min-width:150px}
.lk i{width:34px;height:34px;border-radius:8px;background:#d7ecea;display:grid;place-items:center;flex:none}
.lk b{display:block;height:6px;border-radius:3px;background:#cfd6d4;margin:3px 0;width:90px}.lk b+b{width:60px}
.out.fw{background:#d9fdd3;padding:6px}
.fwl{font-size:11.5px;color:#4a5a56;margin:0 0 4px 2px}
.cb{display:block;margin-top:8px;text-align:center;background:#0f5c63;color:#fff;font-weight:800;border-radius:10px;padding:8px}
.u .m.in{background:#fff;max-width:96%}
.js .mc .m{opacity:0}
.js .mc.on .m{animation:pop .5s ease forwards;animation-delay:calc(var(--n)*.8s + .35s)}
@keyframes pop{from{opacity:0;transform:translateY(8px) scale(.97)}to{opacity:1;transform:none}}
.mc.on .wv s{animation:eq 1.3s ease-in-out infinite;animation-delay:calc(var(--i)*-.11s)}
@keyframes eq{50%{transform:scaleY(.4)}}
.capv{text-align:center;font-size:16px;color:var(--mut);margin-top:22px}
.how{background:#f1ece2}
.hs{display:grid;gap:12px;list-style:none;margin:0;padding:0}
.hsi{display:flex;align-items:center;gap:14px;background:#fff;border-radius:18px;padding:14px 18px;font-weight:700;font-size:19px;border:1px solid var(--line)}
.hsi b{flex:none;width:42px;height:42px;border-radius:50%;background:#0f5c63;color:#fff;display:grid;place-items:center;font:800 20px var(--sans)}
.hsi svg{flex:none;width:42px;height:42px;margin-left:auto}
@media (reduced-motion:reduce){}
@media (prefers-reduced-motion:reduce){.js .mc .m{opacity:1}}
@media (min-width:900px){
 h1{font-size:56px;max-width:none}.hero{padding-bottom:6px}
 .tour .w{max-width:1100px}.arc{display:block}
 .mcs{grid-template-columns:repeat(3,1fr);gap:22px}.mcs:before{display:none}
 .mc{display:flex;flex-direction:column;text-align:center;row-gap:12px}.sunic{display:none}
 .mc h2{justify-content:center;text-align:center;min-height:64px;font-size:21px}
 .hs{grid-template-columns:repeat(3,1fr)}.hsi{flex-direction:column;text-align:center;padding:22px}.hsi svg{margin:0}
 .card h2.promise{font-size:28px}
}
</style></head><body>
<header class="hero"><div class="w">
<div class="top"><span class="brand"><svg viewBox="0 0 40 40" aria-hidden="true"><rect x="2" y="2" width="36" height="36" rx="12" fill="#0f5c63"/><path d="M11 15a9 9 0 0 1 9-5h2a9 9 0 0 1 0 18h-5l-5 4 1-5a9 9 0 0 1-2-7z" fill="#f6b31c"/><circle cx="17" cy="19" r="1.8" fill="#0f5c63"/><circle cx="24" cy="19" r="1.8" fill="#0f5c63"/></svg>Robin</span><button class="lang" id="lang" type="button">हिंदी / Hinglish</button></div>
<h1 data-t="h1">A day with Robin, in <em>three moments.</em></h1><p class="sub" data-t="sub">Real WhatsApp, real voice notes. See what your parents get, and what you get.</p><a class="btn" href="#join" data-t="btn">Join the waitlist</a>
</div></header>

<section class="tour"><div class="w"><svg class="arc" viewBox="0 0 1000 134" aria-hidden="true"><path d="M167 100 Q500 -44 833 100" fill="none" stroke="#eab52c" stroke-width="5" stroke-linecap="round" stroke-dasharray="1 13"/><g transform="translate(139 72)"><svg viewBox="0 0 56 56" width="56" height="56" aria-hidden="true"><circle cx="28" cy="28" r="26" fill="#fff" stroke="#eab52c" stroke-width="3"/><path d="M15 36 H41" stroke="#0f5c63" stroke-width="3" stroke-linecap="round"/><path d="M18 36 a10 10 0 0 1 20 0z" fill="#f6b31c"/><g stroke="#f6b31c" stroke-width="3" stroke-linecap="round"><path d="M28 18 v-4"/><path d="M16 23 l-3 -3"/><path d="M40 23 l3 -3"/></g></svg></g><g transform="translate(472 0)"><svg viewBox="0 0 56 56" width="56" height="56" aria-hidden="true"><circle cx="28" cy="28" r="26" fill="#fff" stroke="#eab52c" stroke-width="3"/><circle cx="28" cy="28" r="8" fill="#f6b31c"/><g stroke="#f6b31c" stroke-width="3" stroke-linecap="round"><path d="M28 12 v4"/><path d="M28 40 v4"/><path d="M12 28 h4"/><path d="M40 28 h4"/><path d="M17 17 l3 3"/><path d="M36 36 l3 3"/><path d="M39 17 l-3 3"/><path d="M17 39 l3 -3"/></g></svg></g><g transform="translate(805 72)"><svg viewBox="0 0 56 56" width="56" height="56" aria-hidden="true"><circle cx="28" cy="28" r="26" fill="#fff" stroke="#eab52c" stroke-width="3"/><path d="M15 37 H41" stroke="#0f5c63" stroke-width="3" stroke-linecap="round"/><path d="M18 37 a10 10 0 0 1 20 0z" fill="#e8825a"/><path d="M20 42 H36" stroke="#e8825a" stroke-width="3" stroke-linecap="round" opacity=".55"/></svg></g></svg><div class="mcs">
<article class="mc rv"><span class="sunic"><svg viewBox="0 0 56 56" width="56" height="56" aria-hidden="true"><circle cx="28" cy="28" r="26" fill="#fff" stroke="#eab52c" stroke-width="3"/><path d="M15 36 H41" stroke="#0f5c63" stroke-width="3" stroke-linecap="round"/><path d="M18 36 a10 10 0 0 1 20 0z" fill="#f6b31c"/><g stroke="#f6b31c" stroke-width="3" stroke-linecap="round"><path d="M28 18 v-4"/><path d="M16 23 l-3 -3"/><path d="M40 23 l3 -3"/></g></svg></span><h2 data-t="m1">Morning: hello and medicine nudge</h2><div class="mb t"><span class="who" data-t="whoT">Their phone</span><div class="phw"><span class="prev" data-t="prev">Preview</span><div class="ph"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div><div class="chat"><div class="m in vn" style="--n:0"><i class="pl"></i><span class="wv" aria-hidden="true"><s style="height:6px;--i:0"></s><s style="height:10px;--i:1"></s><s style="height:16px;--i:2"></s><s style="height:9px;--i:3"></s><s style="height:14px;--i:4"></s><s style="height:20px;--i:5"></s><s style="height:12px;--i:6"></s><s style="height:8px;--i:7"></s><s style="height:15px;--i:8"></s><s style="height:19px;--i:9"></s><s style="height:11px;--i:10"></s><s style="height:7px;--i:11"></s></span><span class="dur">0:06</span></div><div class="m in" style="--n:1" data-t="x1">Namaste! Did you take your medicine?</div><div class="m out" style="--n:2" data-t="x2">Yes</div></div></div></div></div></article>
<article class="mc rv"><span class="sunic"><svg viewBox="0 0 56 56" width="56" height="56" aria-hidden="true"><circle cx="28" cy="28" r="26" fill="#fff" stroke="#eab52c" stroke-width="3"/><circle cx="28" cy="28" r="8" fill="#f6b31c"/><g stroke="#f6b31c" stroke-width="3" stroke-linecap="round"><path d="M28 12 v4"/><path d="M28 40 v4"/><path d="M12 28 h4"/><path d="M40 28 h4"/><path d="M17 17 l3 3"/><path d="M36 36 l3 3"/><path d="M39 17 l-3 3"/><path d="M17 39 l3 -3"/></g></svg></span><h2 data-t="m2">Afternoon: forward a doubtful link</h2><div class="mb t"><span class="who" data-t="whoT">Their phone</span><div class="phw"><span class="prev" data-t="prev">Preview</span><div class="ph"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div><div class="chat"><div class="m out fw" style="--n:0"><div class="fwl">&#8618; <span data-t="fwd">Forwarded</span></div><div class="lk"><i><svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><g fill="none" stroke="#0f5c63" stroke-width="2.4" stroke-linecap="round"><path d="M10 14 a4 4 0 0 0 5 0 l3 -3 a4 4 0 0 0 -5 -5 l-1 1"/><path d="M14 10 a4 4 0 0 0 -5 0 l-3 3 a4 4 0 0 0 5 5 l1 -1"/></g></svg></i><span><b></b><b></b></span></div></div><div class="m in" style="--n:1" data-t="x3">This looks like a trap.<br>Please do not share any OTP or PIN.</div></div></div></div></div></article>
<article class="mc rv"><span class="sunic"><svg viewBox="0 0 56 56" width="56" height="56" aria-hidden="true"><circle cx="28" cy="28" r="26" fill="#fff" stroke="#eab52c" stroke-width="3"/><path d="M15 37 H41" stroke="#0f5c63" stroke-width="3" stroke-linecap="round"/><path d="M18 37 a10 10 0 0 1 20 0z" fill="#e8825a"/><path d="M20 42 H36" stroke="#e8825a" stroke-width="3" stroke-linecap="round" opacity=".55"/></svg></span><h2 data-t="m3">Evening: your short summary</h2><div class="mb u"><span class="who" data-t="whoY">Your phone</span><div class="phw"><span class="prev" data-t="prev">Preview</span><div class="ph"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div><div class="chat"><div class="m in" style="--n:0"><span data-t="x4">Today: checked in, medicines taken, one message checked</span><span class="cb" data-t="x5">Call</span></div></div></div></div></div></article>
</div><p class="capv" data-t="capv">Preview of how Robin will look.</p></div></section>

<section class="sec how"><div class="w"><ol class="hs n" style="max-width:1000px">
<li class="hsi rv"><b>1</b><span data-t="s1">Join the waitlist</span><svg viewBox="0 0 42 42" aria-hidden="true"><rect x="6" y="9" width="30" height="24" rx="6" fill="#fdeab5"/><path d="M12 18 h18 M12 25 h12" stroke="#0f5c63" stroke-width="3" stroke-linecap="round"/></svg></li>
<li class="hsi rv"><b>2</b><span data-t="s2">We message you at launch</span><svg viewBox="0 0 42 42" aria-hidden="true"><rect x="12" y="4" width="18" height="34" rx="5" fill="#16343a"/><rect x="15" y="9" width="12" height="22" rx="2" fill="#d9fdd3"/><circle cx="21" cy="34" r="1.6" fill="#fff"/></svg></li>
<li class="hsi rv"><b>3</b><span data-t="s3">You set up, they are told</span><svg viewBox="0 0 42 42" aria-hidden="true"><circle cx="21" cy="21" r="17" fill="#e8e0f6"/><path d="M12 22 l7 7 l12 -14" fill="none" stroke="#3b2f6b" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg></li></ol></div></section>

<section class="sec" id="join"><div class="w"><div class="card n">
<div id="formwrap"><h2 class="promise" data-t="promise">Robin keeps in touch with your parents every day, on WhatsApp, in their language, and they stay in charge.</h2>
<form id="f" autocomplete="on" novalidate>
<label for="name" data-t="ln">Your name</label><input id="name" name="name" type="text" maxlength="40" autocomplete="given-name" required>
<label for="phone" data-t="lp">Your WhatsApp number</label><input id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="98765 43210 or +1 415 555 0100" required>
<div class="hp" aria-hidden="true"><label for="website">Website</label><input id="website" name="website" type="text" tabindex="-1" autocomplete="off"></div>
<div class="err" id="err" role="alert"></div>
<button class="btn go" id="go" type="submit" data-t="btn">Join the waitlist</button>
<p class="fine" data-t="cons">We will WhatsApp you about the launch, nothing else. Your number is not sold or shared for ads. Ask us to delete it any time.</p>
<p class="fine b" data-t="nopay">No payment. No price announced yet.</p>
<p class="fine"><a href="privacy" data-t="priv">How we use your details</a></p>
</form></div>
<div class="ok" id="ok" aria-live="polite"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="30" fill="#0f5c63"/><path d="M19 33l9 9 17-20" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>
<p data-t="ok">You are on the list. Know a sibling or friend who looks after their parents too? Send them this page, if you think it would help.</p>
<a class="btn share" id="share" href="#" target="_blank" rel="noopener" data-t="share">Share on WhatsApp</a></div>
</div></div></section>
<section class="sec" style="padding-top:8px"><div class="w"><div class="faqs rv">
<details class="faq"><summary data-t="q1">Is Robin a person?</summary><p data-t="a1">No, an AI assistant. The screens above are previews, not real people.</p></details>
<details class="faq"><summary data-t="q2">Does Robin listen to calls?</summary><p data-t="a2">No. It does not read your parent's chats or record their calls. It only sees what they send it.</p></details>
<details class="faq"><summary data-t="q3">Can my parent say no?</summary><p data-t="a3">Yes. They are told about Robin when you set it up, and can stop it any time.</p></details>
<details class="faq"><summary data-t="q4">What does it cost?</summary><p data-t="a4">Waitlist is free. No price announced yet.</p></details>
<details class="faq"><summary data-t="q5">Is it an emergency service?</summary><p data-t="a5">No. For emergencies call 112. Robin cannot send help by itself.</p></details>
</div></div></section>
<section class="sec" style="padding:8px 0 24px"><div class="w"><p class="scam"><span data-t="sc1">The second moment exists because pressure calls and fake links are in the news: </span><a href="https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud" target="_blank" rel="noopener">The Tribune</a><span data-t="sc2">, </span><a href="https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app" target="_blank" rel="noopener">Free Press Journal</a><span data-t="sc3">.</span></p></div></section>
<footer class="foot"><div class="w"><p data-t="foot">Robin is an AI assistant, not a person. It is not an emergency service: in an emergency call 112. Robin is not live yet.</p><p><a href="privacy" data-t="priv2">How we use your details</a></p></div></footer>
<div class="sticky" id="sticky"><a class="btn" href="#join" data-t="stk">See it first: join the waitlist</a></div>
<script>
document.documentElement.className+=" js";
const T={hi:{"promise":"Robin roz aapke parents se WhatsApp par, unki bhasha mein, haal-chaal leta hai, aur kaman unhi ke haath mein rehti hai.","ln":"Aapka naam","lp":"Aapka WhatsApp number","cons":"Hum aapko sirf launch ke baare mein WhatsApp karenge. Aapka number bechte ya ads ke liye share nahi karte. Kabhi bhi delete karwa sakte hain.","nopay":"Koi payment nahi. Price abhi announce nahi hua.","priv":"Hum aapki details kaise use karte hain","share":"WhatsApp par bhejiye","foot":"Robin ek AI assistant hai, insaan nahi. Ye emergency service nahi hai: emergency mein 112 par call karein. Robin abhi live nahi hai.","h1":"Robin ke saath ek din, <em>teen pal.<\/em>","sub":"Asli WhatsApp, asli voice note. Dekhiye parents ko kya milta hai, aur aapko kya.","btn":"Waitlist mein judiye","stk":"Pehle dekhiye: waitlist mein judiye","m1":"Subah: hello aur dawai ki yaad","m2":"Dopahar: shaky link Robin ko bhejein","m3":"Shaam: aapko chhota summary","whoT":"Unka phone","whoY":"Aapka phone","prev":"Preview","capv":"Preview: Robin aisa dikhega.","x1":"Namaste! Dawai li?","x2":"Haan","x3":"Ye jaal lag raha hai.<br>Kripya OTP ya PIN kisi se share na karein.","x4":"Aaj: check-in hua, dawai li, ek message check kiya","x5":"Call","fwd":"Forwarded","s1":"Waitlist mein judiye","s2":"Launch par hum message karenge","s3":"Aap set up karein, unhe bataya jaye","sc1":"Doosra pal isliye hai kyunki dabav waali calls aur nakli links khabron mein hain: ","sc2":", ","sc3":".","q1":"Kya Robin insaan hai?","a1":"Nahi, AI assistant. Upar ki screens preview hain, asli log nahi.","q2":"Kya Robin calls sunta hai?","a2":"Nahi. Ye chats nahi padhta aur calls record nahi karta. Sirf wahi dekhta hai jo parent use bhejte hain.","q3":"Kya mere parent mana kar sakte hain?","a3":"Haan. Set up par unhe Robin ke baare mein bataya jata hai, aur wo kabhi bhi rok sakte hain.","q4":"Isme kitna kharcha hai?","a4":"Waitlist free hai. Price abhi announce nahi hua.","q5":"Kya ye emergency service hai?","a5":"Nahi. Emergency mein 112. Robin khud madad nahi bhej sakta.","ok":"Aap list mein hain. Koi bhai-behen ya dost jo apne parents ka khayal rakhta ho? Sahi lage to ye page unhe bhej dijiye.","priv2":"Hum aapki details kaise use karte hain"}};
const ERR={"en":{"name":"Please add your name.","phone":"That number does not look right. Add your WhatsApp number with country code if you are abroad.","busy":"That did not go through. Please try again in a minute."},"hi":{"name":"Apna naam likhiye.","phone":"Ye number sahi nahi lag raha. Videsh mein hain to country code ke saath WhatsApp number likhiye.","busy":"Ye nahi ho paya. Ek minute baad dobara try karein."}};
const MSG={"en":"Robin keeps in touch with your parents every day, on WhatsApp, in their language, and they stay in charge. Join the waitlist: ","hi":"Robin roz aapke parents se WhatsApp par, unki bhasha mein, haal-chaal leta hai, aur kaman unhi ke haath mein rehti hai. Waitlist mein judiye: "};
const EN={};document.querySelectorAll("[data-t]").forEach(e=>{EN[e.dataset.t]=e.innerHTML});T.en=EN;
let cur="en";
function setLang(l){cur=l;document.documentElement.lang=l==="hi"?"hi-Latn":"en";
document.querySelectorAll("[data-t]").forEach(e=>{const v=T[l][e.dataset.t];if(v!==undefined)e.innerHTML=v});
const b=document.getElementById("lang");b.textContent=l==="hi"?"English":"हिंदी / Hinglish";b.setAttribute("aria-label",l==="hi"?"Switch to English":"Switch to Hindi in Roman letters");
const sh=document.getElementById("share");if(sh)sh.href="https://wa.me/?text="+encodeURIComponent(MSG[l]+location.origin+location.pathname+"?src=share")}
document.getElementById("lang").onclick=()=>setLang(cur==="en"?"hi":"en");
const src=new URLSearchParams(location.search).get("src")||"";
if("IntersectionObserver" in window){
const rv=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.add("on");rv.unobserve(e.target)}}),{threshold:.12});
document.querySelectorAll(".rv").forEach(e=>rv.observe(e));
const st=document.getElementById("sticky"),io=new IntersectionObserver(es=>{st.classList.toggle("hide",es[0].isIntersecting)});io.observe(document.getElementById("join"))}
else{document.querySelectorAll(".rv").forEach(e=>e.classList.add("on"))}
document.getElementById("f").addEventListener("submit",async ev=>{ev.preventDefault();
const err=document.getElementById("err"),E=ERR[cur],g=id=>document.getElementById(id).value.trim();err.textContent="";
const body={name:g("name"),phone:g("phone"),website:g("website"),src:src,v:"{{VARIANT}}",consent:true};
if(!body.name){err.textContent=E.name;document.getElementById("name").focus();return}
if(body.phone.replace(/\D/g,"").length<8){err.textContent=E.phone;document.getElementById("phone").focus();return}
const b=document.getElementById("go");b.disabled=true;
try{const r=await fetch("join",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
if(!r.ok){const j=await r.json().catch(()=>({}));err.textContent=E[j.field]||E.busy;b.disabled=false;return}
document.getElementById("formwrap").style.display="none";document.getElementById("ok").style.display="block";
const st=document.getElementById("sticky");if(st)st.style.display="none";
document.getElementById("join").scrollIntoView({block:"center"})}
catch(e){err.textContent=E.busy;b.disabled=false}});
</script></body></html>
"""
