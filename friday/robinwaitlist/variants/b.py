# ruff: noqa: E501
"""Landing page variant B (docs/ROBIN_LANDING_BRIEF.md). Generated look, static content. The token {{VARIANT}} is replaced by the router."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><meta name="color-scheme" content="light"><title>Robin waitlist</title>
<meta name="description" content="Support that lets your parents stay in charge. Join the Robin waitlist.">
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

:root{--bg:#fdf8ec;--ink:#13302f;--mut:#41575a;--link:#0b4f55;--brandtxt:#fdf8ec;--btn:#f29a1f;--btnc:#1a2b29;--btnsh:0 10px 24px rgba(242,154,31,.38);
--card:#fffdf6;--line:#ecd9bd;--inb:#c9b79a;--inbg:#fffdf6;--err:#9c2b1f;--focus:#0b4f55;--langb:rgba(253,248,236,.55);--langbg:transparent;--langc:#fdf8ec;
--faqi:#fbe3b4;--faqc:#0b4f55;--bar:#0b4f55;--avbg:#f29a1f;--chatbg:#f3ead6;--outbub:#fde7b8;--wave:#0b4f55;--teal:#0b4f55;--saf:#f29a1f;--clay:#c97b5a;
--hfont:800 27px/1.2 ui-rounded,"Avenir Next","Nunito","Segoe UI",system-ui,"Noto Sans Devanagari","Nirmala UI",sans-serif;
--sans:ui-rounded,"Avenir Next","Nunito","Segoe UI",system-ui,-apple-system,Roboto,"Noto Sans","Noto Sans Devanagari","Nirmala UI",Mangal,Helvetica,Arial,sans-serif}
.btn{border-radius:999px}
.hero{background:radial-gradient(120% 80% at 80% 0,#146870 0,#0b4f55 55%,#093f44 100%);color:#fdf8ec;border-radius:0 0 44px 44px;overflow:hidden}
h1{font:800 38px/1.1 var(--sans);letter-spacing:-.5px;margin:6px 0 14px}h1 em{font-style:normal;color:#ffc766}
.sub{font-size:20px;line-height:1.5;color:#e6eee9;margin:0 0 22px;max-width:30em}
.hgrid{display:grid;gap:18px;padding:20px 0 48px}
.vis{position:relative;width:100%;max-width:400px;height:470px;margin:0 auto}
.vis .glow{position:absolute;left:0;bottom:0;width:260px;height:260px;border-radius:50%;background:radial-gradient(circle,#ffc766 0,rgba(255,199,102,.15) 70%,transparent 72%)}
.vis .par{position:absolute;left:-8px;bottom:0;width:200px;height:270px}
.vis .ph{position:absolute;right:0;top:0}
.pcap{position:absolute;right:0;bottom:4px;width:168px;text-align:right;font:800 21px/1.2 var(--sans);color:#ffc766}
.ctl{background:#fffdf6;padding:10px 10px 12px;border-top:1px solid #e3d6bb}
.sw{display:flex;align-items:center;gap:10px;width:100%;min-height:48px;border:0;background:none;font:700 15px var(--sans);color:#13302f;cursor:pointer;padding:0 4px}
.sw i{width:46px;height:26px;border-radius:13px;background:#f29a1f;position:relative;flex:none;transition:background .25s}
.sw i:after{content:"";position:absolute;top:3px;left:23px;width:20px;height:20px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.3);transition:left .25s}
.paused .sw i{background:#8a9a98}.paused .sw i:after{left:3px}
.stopb{width:100%;min-height:50px;margin-top:6px;border-radius:14px;border:2.5px solid #0b4f55;background:#fff;color:#0b4f55;font:800 17px var(--sans);cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px}
.stopb:before{content:"";width:12px;height:12px;border-radius:2px;background:#0b4f55}
.paused .stopb{background:#0b4f55;color:#fff}.paused .stopb:before{width:0;height:0;border-radius:0;background:none;border-left:11px solid #fff;border-top:7px solid transparent;border-bottom:7px solid transparent}
.s-off{display:none}.paused .s-on{display:none}.paused .s-off{display:inline}
.ph:not(.paused) .wv s{animation:eq 1.3s ease-in-out infinite;animation-delay:calc(var(--i)*-.11s)}
@keyframes eq{50%{transform:scaleY(.4)}}
.paused .chat{opacity:.5}.chat{transition:opacity .3s}
.cards{display:grid;gap:16px;list-style:none;margin:0;padding:0}
.pc{background:var(--card);border:2px solid var(--line);border-radius:28px;overflow:hidden}
.pc svg{display:block;width:100%;height:auto}
.pc div{padding:16px 20px 22px;font:800 21px/1.25 var(--sans);color:var(--teal)}
.how{background:#f6e8d3}
.st{display:grid;gap:16px;list-style:none;margin:0;padding:0;counter-reset:s}
.sti{background:#fffdf6;border-radius:26px;overflow:hidden;border:2px solid #ecd9bd}
.sti svg{display:block;width:100%;height:auto}
.sti div{display:flex;gap:14px;align-items:center;padding:14px 18px 20px;font-weight:700;font-size:19px;line-height:1.3}
.sti b{flex:none;width:40px;height:40px;border-radius:50%;background:var(--teal);color:#ffc766;display:grid;place-items:center;font:800 19px var(--sans)}
details.faq summary{font-family:var(--sans)}
@media (min-width:760px){
 h1{font-size:56px}.hgrid{grid-template-columns:1.1fr .9fr;align-items:center;gap:30px;padding:48px 0 70px}
 .cards{grid-template-columns:repeat(3,1fr)}.st{grid-template-columns:repeat(3,1fr)}
 .card h2.promise{font-size:28px}
}
</style></head><body>
<header class="hero"><div class="w">
<div class="top"><span class="brand"><svg viewBox="0 0 40 40" aria-hidden="true"><rect x="2" y="2" width="36" height="36" rx="12" fill="#f29a1f"/><path d="M11 15a9 9 0 0 1 9-5h2a9 9 0 0 1 0 18h-5l-5 4 1-5a9 9 0 0 1-2-7z" fill="#0b4f55"/><circle cx="17" cy="19" r="1.8" fill="#f29a1f"/><circle cx="24" cy="19" r="1.8" fill="#f29a1f"/></svg>Robin</span><button class="lang" id="lang" type="button">हिंदी / Hinglish</button></div>
<div class="hgrid"><div class="htxt"><h1 data-t="h1">Support that lets them stay <em>in charge.</em></h1><p class="sub" data-t="sub">Robin is a helper your parents can talk to, in their language, and stop whenever they like.</p><a class="btn" href="#join" data-t="btn">Get on the waitlist</a></div>
<div class="vis"><div class="glow"></div><svg class="par" viewBox="0 0 200 270" aria-hidden="true"><g transform="translate(100 270) scale(1.95)"><circle cx="0" cy="-101" r="9" fill="#c9c4bc"/><path d="M-46 0 V-20 Q-46 -47 -16 -50 L-8 -51 H8 L16 -50 Q46 -47 46 -20 V0Z" fill="#f29a1f"/><path d="M-32 -47 L-10 -50 Q8 -22 40 -6 L40 0 L8 0 Q-12 -22 -34 -36Z" fill="#c97b5a"/><rect x="-7" y="-60" width="14" height="14" rx="5" fill="#c98f68"/><circle cx="-17" cy="-71" r="3.5" fill="#c98f68"/><circle cx="17" cy="-71" r="3.5" fill="#c98f68"/><ellipse cx="0" cy="-73" rx="17" ry="19.5" fill="#c98f68"/><path d="M-18 -76 Q-20 -97 0 -96 Q20 -97 18 -76 Q12 -87 0 -86 Q-12 -87 -18 -76Z" fill="#c9c4bc"/><circle cx="-6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="-11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><circle cx="11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><path d="M-8 -66 Q0 -53 8 -66Z" fill="#8a3b2a"/><path d="M-6 -66 H6 Q0 -62 -6 -66Z" fill="#fff"/></g></svg>
<div class="ph" id="ph"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div>
<div class="chat"><div class="m in" data-t="mB1">Namaste! Did you take your medicine?</div>
<div class="m out vn"><i class="pl"></i><span class="wv" aria-hidden="true"><s style="height:6px;--i:0"></s><s style="height:10px;--i:1"></s><s style="height:16px;--i:2"></s><s style="height:9px;--i:3"></s><s style="height:14px;--i:4"></s><s style="height:20px;--i:5"></s><s style="height:12px;--i:6"></s><s style="height:8px;--i:7"></s><s style="height:15px;--i:8"></s><s style="height:19px;--i:9"></s><s style="height:11px;--i:10"></s><s style="height:7px;--i:11"></s></span><span class="dur">0:05</span></div>
<div class="m in" data-t="mB2">Lovely. Have a good day!</div></div>
<div class="ctl"><button class="sw" id="sw" type="button" role="switch" aria-checked="true"><i></i><span class="s-on" data-t="swon">On</span><span class="s-off" data-t="swoff">Paused</span></button>
<button class="stopb" id="stopb" type="button"><span class="s-on" data-t="stop">Stop Robin</span><span class="s-off" data-t="start">Turn Robin on</span></button></div></div>
<p class="pcap" data-t="cap">Their phone. Their call.</p></div></div></div></header>

<section class="sec"><div class="w"><ul class="cards">
<li class="pc rv"><svg viewBox="0 0 240 150" aria-hidden="true"><rect width="240" height="150" fill="#fde7b8"/><g transform="translate(86 24) scale(1.2)"><rect x="0" y="0" width="64" height="34" rx="17" fill="#f29a1f"/><circle cx="47" cy="17" r="13" fill="#fff"/></g><g transform="translate(86 86) scale(1.2)"><rect x="0" y="0" width="64" height="34" rx="17" fill="#8a9a98"/><circle cx="17" cy="17" r="13" fill="#fff"/></g><g fill="#0b4f55"><rect x="38" y="95" width="9" height="22" rx="3"/><rect x="52" y="95" width="9" height="22" rx="3"/></g><path d="M44 35 l16 10 l-16 10z" fill="#0b4f55" transform="translate(-4 0)"/></svg><div data-t="p1">They can say stop, anytime</div></li>
<li class="pc rv"><svg viewBox="0 0 240 150" aria-hidden="true"><rect width="240" height="150" fill="#d4e8e6"/><circle cx="60" cy="70" r="46" fill="#f6fbf9" opacity=".6"/><g transform="translate(80 150) scale(1.05)"><circle cx="0" cy="-101" r="9" fill="#b9b4ac"/><path d="M-46 0 V-20 Q-46 -47 -16 -50 L-8 -51 H8 L16 -50 Q46 -47 46 -20 V0Z" fill="#0b4f55"/><path d="M-32 -47 L-10 -50 Q8 -22 40 -6 L40 0 L8 0 Q-12 -22 -34 -36Z" fill="#f29a1f"/><rect x="-7" y="-60" width="14" height="14" rx="5" fill="#c98f68"/><circle cx="-17" cy="-71" r="3.5" fill="#c98f68"/><circle cx="17" cy="-71" r="3.5" fill="#c98f68"/><ellipse cx="0" cy="-73" rx="17" ry="19.5" fill="#c98f68"/><path d="M-18 -76 Q-20 -97 0 -96 Q20 -97 18 -76 Q12 -87 0 -86 Q-12 -87 -18 -76Z" fill="#b9b4ac"/><circle cx="-6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="-11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><circle cx="11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><path d="M-8 -66 Q0 -53 8 -66Z" fill="#8a3b2a"/><path d="M-6 -66 H6 Q0 -62 -6 -66Z" fill="#fff"/><path d="M38 -34 Q50 -48 30 -60" fill="none" stroke="#0b4f55" stroke-width="11" stroke-linecap="round"/><rect x="21" y="-88" width="13" height="24" rx="3.5" fill="#27323a" transform="rotate(12 27 -76)"/><circle cx="30" cy="-62" r="6" fill="#c98f68"/></g><g><rect x="124" y="30" width="100" height="38" rx="18" fill="#fde7b8"/><path d="M138 68 l-10 12 l20 -12z" fill="#fde7b8"/><path d="M140 42 l11 7 l-11 7z" fill="#0b4f55"/><rect x="160.0" y="44.0" width="3.4" height="10" rx="1.7" fill="#0b4f55"/><rect x="166.5" y="40.0" width="3.4" height="18" rx="1.7" fill="#0b4f55"/><rect x="173.0" y="36.0" width="3.4" height="26" rx="1.7" fill="#0b4f55"/><rect x="179.5" y="42.0" width="3.4" height="14" rx="1.7" fill="#0b4f55"/><rect x="186.0" y="38.0" width="3.4" height="22" rx="1.7" fill="#0b4f55"/><rect x="192.5" y="43.0" width="3.4" height="12" rx="1.7" fill="#0b4f55"/><rect x="199.0" y="37.0" width="3.4" height="24" rx="1.7" fill="#0b4f55"/><rect x="205.5" y="41.0" width="3.4" height="16" rx="1.7" fill="#0b4f55"/><rect x="212.0" y="45.0" width="3.4" height="8" rx="1.7" fill="#0b4f55"/><rect x="218.5" y="42.0" width="3.4" height="14" rx="1.7" fill="#0b4f55"/></g></svg><div data-t="p2">Voice notes in their language</div></li>
<li class="pc rv"><svg viewBox="0 0 240 150" aria-hidden="true"><rect width="240" height="150" fill="#f4e0cc"/><rect x="26" y="22" width="80" height="110" rx="12" fill="#fffdf6" stroke="#13302f" stroke-width="4"/><rect x="34" y="30" width="64" height="10" rx="5" fill="#0b4f55"/><circle cx="44" cy="52" r="7" fill="#0b4f55"/><path d="M40.5 52 l2.5 2.5 l5 -5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><rect x="56" y="49" width="34" height="6" rx="3" fill="#cdd8d6"/><circle cx="44" cy="74" r="7" fill="#0b4f55"/><path d="M40.5 74 l2.5 2.5 l5 -5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><rect x="56" y="71" width="28" height="6" rx="3" fill="#cdd8d6"/><circle cx="44" cy="96" r="7" fill="#0b4f55"/><path d="M40.5 96 l2.5 2.5 l5 -5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><rect x="56" y="93" width="22" height="6" rx="3" fill="#cdd8d6"/><rect x="134" y="22" width="80" height="110" rx="12" fill="#fffdf6" stroke="#13302f" stroke-width="4"/><rect x="142" y="30" width="64" height="10" rx="5" fill="#0b4f55"/><circle cx="152" cy="52" r="7" fill="#0b4f55"/><path d="M148.5 52 l2.5 2.5 l5 -5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><rect x="164" y="49" width="34" height="6" rx="3" fill="#cdd8d6"/><circle cx="152" cy="74" r="7" fill="#0b4f55"/><path d="M148.5 74 l2.5 2.5 l5 -5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><rect x="164" y="71" width="28" height="6" rx="3" fill="#cdd8d6"/><circle cx="152" cy="96" r="7" fill="#0b4f55"/><path d="M148.5 96 l2.5 2.5 l5 -5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><rect x="164" y="93" width="22" height="6" rx="3" fill="#cdd8d6"/><path d="M112 78 h16" stroke="#c97b5a" stroke-width="4" stroke-linecap="round" stroke-dasharray="1 8"/></svg><div data-t="p3">They see what you see</div></li></ul></div></section>

<section class="sec how"><div class="w"><ol class="st">
<li class="sti rv"><svg viewBox="0 0 240 140" aria-hidden="true"><rect width="240" height="140" fill="#d4e8e6"/><g transform="translate(84 140) scale(1.0)"><path d="M-46 0 V-20 Q-46 -47 -16 -50 L-8 -51 H8 L16 -50 Q46 -47 46 -20 V0Z" fill="#f29a1f"/><rect x="-7" y="-60" width="14" height="14" rx="5" fill="#d79d77"/><circle cx="-17" cy="-71" r="3.5" fill="#d79d77"/><circle cx="17" cy="-71" r="3.5" fill="#d79d77"/><ellipse cx="0" cy="-73" rx="17" ry="19.5" fill="#d79d77"/><path d="M-18 -76 Q-20 -97 0 -96 Q20 -97 18 -76 Q12 -87 0 -86 Q-12 -87 -18 -76Z" fill="#2b2321"/><circle cx="-6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="-11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><circle cx="11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><path d="M-6.5 -65 Q0 -59 6.5 -65" fill="none" stroke="#8a3b2a" stroke-width="1.9" stroke-linecap="round"/><path d="M36 -38 Q42 -18 24 -12" fill="none" stroke="#f29a1f" stroke-width="11" stroke-linecap="round"/><rect x="12" y="-40" width="16" height="27" rx="3.5" fill="#27323a"/><rect x="14" y="-37" width="12" height="21" rx="2" fill="#dff5e9"/><ellipse cx="22" cy="-12" rx="8" ry="5.5" fill="#d79d77"/></g><g transform="translate(140 40)"><rect width="70" height="48" rx="8" fill="#fffdf6"/><path d="M0 8 l35 24 l35 -24" fill="none" stroke="#0b4f55" stroke-width="4" stroke-linejoin="round"/></g></svg><div><b>1</b><span data-t="s1">You invite Robin for them</span></div></li>
<li class="sti rv"><svg viewBox="0 0 240 140" aria-hidden="true"><rect width="240" height="140" fill="#fde7b8"/><rect x="64" y="14" width="112" height="112" rx="22" fill="#13302f"/><rect x="70" y="22" width="100" height="96" rx="16" fill="#f3ead6"/><circle cx="90" cy="46" r="12" fill="#f29a1f"/><text x="90" y="52" text-anchor="middle" font-family="Arial,sans-serif" font-weight="800" font-size="16" fill="#1a2b29">R</text><rect x="108" y="36" width="52" height="20" rx="10" fill="#fff"/><rect x="82" y="68" width="76" height="8" rx="4" fill="#fff"/><rect x="82" y="84" width="58" height="8" rx="4" fill="#fff"/><rect x="82" y="100" width="40" height="8" rx="4" fill="#fff"/></svg><div><b>2</b><span data-t="s2">Robin introduces itself, openly</span></div></li>
<li class="sti rv"><svg viewBox="0 0 240 140" aria-hidden="true"><rect width="240" height="140" fill="#f4e0cc"/><g transform="translate(80 140) scale(1.0)"><path d="M-46 0 V-20 Q-46 -47 -16 -50 L-8 -51 H8 L16 -50 Q46 -47 46 -20 V0Z" fill="#0b4f55"/><rect x="-7" y="-60" width="14" height="14" rx="5" fill="#c98f68"/><circle cx="-17" cy="-71" r="3.5" fill="#c98f68"/><circle cx="17" cy="-71" r="3.5" fill="#c98f68"/><ellipse cx="0" cy="-73" rx="17" ry="19.5" fill="#c98f68"/><path d="M-18 -76 Q-20 -97 0 -96 Q20 -97 18 -76 Q12 -87 0 -86 Q-12 -87 -18 -76Z" fill="#c9c4bc"/><circle cx="-6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="-11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><circle cx="11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><path d="M-6.5 -65 Q0 -59 6.5 -65" fill="none" stroke="#8a3b2a" stroke-width="1.9" stroke-linecap="round"/><g fill="none" stroke="#3a3430" stroke-width="1.5"><circle cx="-7" cy="-74" r="5.5"/><circle cx="7" cy="-74" r="5.5"/><path d="M-1.5 -74 H1.5"/></g><path d="M36 -38 Q42 -18 24 -12" fill="none" stroke="#0b4f55" stroke-width="11" stroke-linecap="round"/><rect x="12" y="-40" width="16" height="27" rx="3.5" fill="#27323a"/><rect x="14" y="-37" width="12" height="21" rx="2" fill="#fde7b8"/><ellipse cx="22" cy="-12" rx="8" ry="5.5" fill="#c98f68"/></g><g transform="translate(138 52) scale(1.25)"><rect x="0" y="0" width="64" height="34" rx="17" fill="#f29a1f"/><circle cx="47" cy="17" r="13" fill="#fff"/></g></svg><div><b>3</b><span data-t="s3">They keep the final say</span></div></li></ol></div></section>

<section class="sec" id="join"><div class="w"><div class="card n">
<div id="formwrap"><h2 class="promise" data-t="promise">Robin keeps in touch with your parents every day, on WhatsApp, in their language, and they stay in charge.</h2>
<form id="f" autocomplete="on" novalidate>
<label for="name" data-t="ln">Your name</label><input id="name" name="name" type="text" maxlength="40" autocomplete="given-name" required>
<label for="phone" data-t="lp">Your WhatsApp number</label><input id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="98765 43210 or +1 415 555 0100" required>
<div class="hp" aria-hidden="true"><label for="website">Website</label><input id="website" name="website" type="text" tabindex="-1" autocomplete="off"></div>
<div class="err" id="err" role="alert"></div>
<button class="btn go" id="go" type="submit" data-t="btn">Get on the waitlist</button>
<p class="fine" data-t="cons">We will WhatsApp you about the launch, nothing else. Your number is not sold or shared for ads. Ask us to delete it any time.</p>
<p class="fine b" data-t="nopay">No payment. No price announced yet.</p>
<p class="fine"><a href="privacy" data-t="priv">How we use your details</a></p>
</form></div>
<div class="ok" id="ok" aria-live="polite"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="30" fill="#0b4f55"/><path d="M19 33l9 9 17-20" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>
<p data-t="ok">You are on the list. We will message you when it opens. Today, try asking your parent one open question: what part of the day would you like a little help with? Their answer is the best setup guide.</p>
<a class="btn share" id="share" href="#" target="_blank" rel="noopener" data-t="share">Share on WhatsApp</a></div>
</div></div></section>
<section class="sec" style="padding-top:8px"><div class="w"><div class="faqs rv">
<details class="faq"><summary data-t="q1">Will my parent feel watched?</summary><p data-t="a1">Robin tells them who set it up and what it does. It does not read their chats or record their calls, and they can stop it by saying so.</p></details>
<details class="faq"><summary data-t="q2">Is Robin a person?</summary><p data-t="a2">No, an AI assistant. No human desk at launch.</p></details>
<details class="faq"><summary data-t="q3">Can my parent say no?</summary><p data-t="a3">Yes, at any time, by voice note, text or on a call. Robin then tells you, so you can talk to them.</p></details>
<details class="faq"><summary data-t="q4">What does it cost?</summary><p data-t="a4">Waitlist is free. No price announced yet.</p></details>
<details class="faq"><summary data-t="q5">Is it an emergency service?</summary><p data-t="a5">No. Call 112 in an emergency. The SOS button alerts you; it does not replace emergency help.</p></details>
</div></div></section>
<section class="sec" style="padding:8px 0 24px"><div class="w"><p class="scam"><span data-t="sc1">Good judgement still gets pressured by callers who sound official. News examples: </span><a href="https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud" target="_blank" rel="noopener">The Tribune</a><span data-t="sc2">, </span><a href="https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app" target="_blank" rel="noopener">Free Press Journal</a><span data-t="sc3">. Robin gives a second opinion, they decide.</span></p></div></section>
<footer class="foot"><div class="w"><p data-t="foot">Robin is an AI assistant, not a person. It is not an emergency service: in an emergency call 112. Robin is not live yet.</p><p><a href="privacy" data-t="priv2">How we use your details</a></p></div></footer>
<div class="sticky" id="sticky"><a class="btn" href="#join" data-t="stk">Get on the waitlist</a></div>
<script>
document.documentElement.className+=" js";
const T={hi:{"promise":"Robin roz aapke parents se WhatsApp par, unki bhasha mein, haal-chaal leta hai, aur kaman unhi ke haath mein rehti hai.","ln":"Aapka naam","lp":"Aapka WhatsApp number","cons":"Hum aapko sirf launch ke baare mein WhatsApp karenge. Aapka number bechte ya ads ke liye share nahi karte. Kabhi bhi delete karwa sakte hain.","nopay":"Koi payment nahi. Price abhi announce nahi hua.","priv":"Hum aapki details kaise use karte hain","share":"WhatsApp par bhejiye","foot":"Robin ek AI assistant hai, insaan nahi. Ye emergency service nahi hai: emergency mein 112 par call karein. Robin abhi live nahi hai.","h1":"Madad aisi, ki <em>kaman unke haath mein.<\/em>","sub":"Robin aisa saathi hai jisse parents apni bhasha mein baat kar sakte hain, aur jab chahein rok sakte hain.","btn":"Waitlist mein naam likhwayiye","stk":"Waitlist mein judiye","cap":"Unka phone. Unka faisla.","mB1":"Namaste! Dawai li?","mB2":"Bahut achha. Aapka din achha rahe!","swon":"Chalu","swoff":"Ruka hua","stop":"Robin band karo","start":"Robin chalu karo","p1":"Wo kabhi bhi 'band karo' bol sakte hain","p2":"Unki apni bhasha, voice note mein","p3":"Jo aap dekhen, wo bhi dekhein","s1":"Aap unke liye Robin bulate hain","s2":"Robin khud apna parichay deta hai","s3":"Aakhri faisla unka rehta hai","sc1":"Achhi samajh waale log bhi official lagne wale callers ke dabav mein aa jaate hain. Khabar: ","sc2":", ","sc3":". Robin doosri raay deta hai, faisla unka.","q1":"Kya mere parent ko lagega ki unpar nazar hai?","a1":"Robin unhe batata hai ki kisne set up kiya aur ye kya karta hai. Ye unki chats nahi padhta, calls record nahi karta, aur wo bol kar ise rok sakte hain.","q2":"Kya Robin insaan hai?","a2":"Nahi, ek AI assistant. Launch par koi human desk nahi.","q3":"Kya mere parent mana kar sakte hain?","a3":"Haan, kabhi bhi, voice note, text ya call par. Phir Robin aapko batata hai, taaki aap unse baat kar sakein.","q4":"Isme kitna kharcha hai?","a4":"Waitlist free hai. Price abhi announce nahi hua.","q5":"Kya ye emergency service hai?","a5":"Nahi. Emergency mein 112. SOS button aapko alert karta hai; ye emergency madad ki jagah nahi leta.","ok":"Aap list mein hain. Khulte hi message karenge. Aaj apne parent se ek khula sawal poochiye: din ke kis hisse mein thodi madad achhi lagegi? Unka jawab hi sabse achha setup guide hai.","priv2":"Hum aapki details kaise use karte hain"}};
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

const ph=document.getElementById("ph"),sw=document.getElementById("sw");
function tog(){const p=ph.classList.toggle("paused");sw.setAttribute("aria-checked",p?"false":"true")}
sw.onclick=tog;document.getElementById("stopb").onclick=tog;
</script></body></html>
"""
