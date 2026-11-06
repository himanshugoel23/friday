# ruff: noqa: E501
"""Landing page variant A (docs/ROBIN_LANDING_BRIEF.md). Generated look, static content. The token {{VARIANT}} is replaced by the router."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><meta name="color-scheme" content="light"><title>Robin waitlist</title>
<meta name="description" content="Robin says hello to your parents on WhatsApp every day. Join the waitlist.">
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

:root{--bg:#fbf4e4;--ink:#21302b;--mut:#4c5a54;--link:#0b5f5f;--brand:#0e6b6b;--brandtxt:#0a5252;--btn:#0e6b6b;--btnc:#fff;--btnsh:0 10px 22px rgba(14,107,107,.28);
--card:#fffdf7;--line:#eadfc4;--inb:#cdbf9d;--inbg:#fffaf0;--err:#9c2b1f;--focus:#0e6b6b;--langb:#c9bb98;--langbg:rgba(255,253,247,.7);--langc:#21302b;
--faqi:#e0ebdc;--faqc:#0a5252;--bar:#2f7d62;--avbg:#f0a830;--chatbg:#efe8d8;--outbub:#e3f3dc;--wave:#2f7d62;--gold:#f0a830;--sage:#dfe9dc;--terra:#c4673b;
--hfont:700 30px/1.15 Georgia,"Iowan Old Style","Palatino Linotype","Noto Serif Devanagari",serif;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans","Noto Sans Devanagari","Nirmala UI",Mangal,Helvetica,Arial,sans-serif}
.hero{background:linear-gradient(180deg,#ffeabb 0%,#fdf1d3 38%,#fbf4e4 100%);background-size:100% 160%;animation:dawn 14s ease-in-out infinite alternate}
@keyframes dawn{to{background-position:0 100%}}
.hgrid{display:grid;gap:22px;padding:20px 0 44px}
h1{font:700 40px/1.08 Georgia,"Iowan Old Style","Palatino Linotype","Noto Serif Devanagari",serif;letter-spacing:-.4px;color:#1d2b26;margin:6px 0 14px}
h1 em{font-style:normal;background:linear-gradient(transparent 64%,#f6cd72 64%);padding:0 2px}
.sub{font-size:20px;line-height:1.5;color:#34443e;margin:0 0 22px;max-width:30em}
.scene{position:relative;width:100%;max-width:400px;margin:0 auto;aspect-ratio:400/384;border-radius:34px;overflow:hidden;box-shadow:0 22px 50px rgba(90,70,20,.2);border:5px solid #fffdf7}
.scene>svg{position:absolute;inset:0;width:100%;height:100%;display:block}
.scene .ph{position:absolute;left:50%;top:7%;transform:translateX(-50%) rotate(-2deg)}
.steam path{animation:steam 3.5s ease-in-out infinite;opacity:.6}.steam path:nth-child(2){animation-delay:1.1s}
@keyframes steam{0%,100%{opacity:.15;transform:translateY(2px)}50%{opacity:.7;transform:translateY(-3px)}}
.moms{display:grid;gap:16px;margin:0;padding:0;list-style:none}
.mom{display:flex;align-items:center;gap:18px;background:var(--card);border:1px solid var(--line);border-radius:24px;padding:16px 20px;font:700 22px/1.25 Georgia,"Iowan Old Style","Noto Serif Devanagari",serif;color:#21302b}
.mom svg{width:84px;height:84px;flex:none}
.steps{display:grid;gap:18px;margin:0;padding:0;list-style:none}
.step{background:var(--card);border:1px solid var(--line);border-radius:26px;overflow:hidden}
.step svg{display:block;width:100%;height:auto}
.step div{display:flex;gap:14px;align-items:center;padding:16px 18px 20px;font-weight:700;font-size:19px;line-height:1.3}
.step b{flex:none;width:38px;height:38px;border-radius:50%;background:var(--gold);color:#2a2008;display:grid;place-items:center;font:800 19px var(--sans)}
.fadein{animation:fi 1.2s ease both}@keyframes fi{from{opacity:0;transform:translateY(10px)}}
.band{background:linear-gradient(180deg,#e9f0e4,#f3efdc)}
.talk{background:var(--sage);border-radius:30px;padding:30px 20px}
@media (min-width:760px){
 h1{font-size:56px}.hgrid{grid-template-columns:1.05fr 1fr;align-items:center;gap:40px;padding:40px 0 64px}
 .moms{grid-template-columns:repeat(3,1fr)}.mom{flex-direction:column;text-align:center;padding:26px 18px;font-size:23px}.mom svg{width:104px;height:104px}
 .steps{grid-template-columns:repeat(3,1fr)}
 .card h2.promise{font-size:28px}
}
</style></head><body>
<header class="hero"><div class="w">
<div class="top"><span class="brand"><svg viewBox="0 0 40 40" aria-hidden="true"><rect x="2" y="2" width="36" height="36" rx="12" fill="#0e6b6b"/><path d="M11 15a9 9 0 0 1 9-5h2a9 9 0 0 1 0 18h-5l-5 4 1-5a9 9 0 0 1-2-7z" fill="#fff"/><circle cx="17" cy="19" r="1.8" fill="#0e6b6b"/><circle cx="24" cy="19" r="1.8" fill="#0e6b6b"/></svg>Robin</span><button class="lang" id="lang" type="button">हिंदी / Hinglish</button></div>
<div class="hgrid"><div class="htxt fadein"><h1 data-t="h1">Know how your <em>parents</em> are doing.</h1><p class="sub" data-t="sub">Robin says hello to your parents on WhatsApp every day, and tells you if something looks off.</p><a class="btn" href="#join" data-t="btn">Join the waitlist</a></div>
<div class="scene fadein" style="animation-delay:.25s"><svg viewBox="0 0 400 440" preserveAspectRatio="xMidYMin slice" aria-hidden="true">
<defs><linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffe6ad"/><stop offset="1" stop-color="#fdf3da"/></linearGradient>
<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#bfe4ee"/><stop offset="1" stop-color="#e6f4ef"/></linearGradient><clipPath id="win"><rect x="36" y="34" width="150" height="170" rx="12"/></clipPath></defs>
<rect width="400" height="440" fill="url(#wall)"/>
<rect x="30" y="28" width="162" height="182" rx="16" fill="#fffdf7"/>
<g clip-path="url(#win)"><rect x="36" y="34" width="150" height="170" fill="url(#sky)"/><circle cx="120" cy="92" r="22" fill="#f6b73c"/><line x1="147.0" y1="92.0" x2="154.0" y2="92.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="141.8" y1="107.9" x2="147.5" y2="112.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="128.3" y1="117.7" x2="130.5" y2="124.3" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="111.7" y1="117.7" x2="109.5" y2="124.3" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="98.2" y1="107.9" x2="92.5" y2="112.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="93.0" y1="92.0" x2="86.0" y2="92.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="98.2" y1="76.1" x2="92.5" y2="72.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="111.7" y1="66.3" x2="109.5" y2="59.7" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="128.3" y1="66.3" x2="130.5" y2="59.7" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="141.8" y1="76.1" x2="147.5" y2="72.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><path d="M36 178 Q80 150 120 172 T186 160 V204 H36Z" fill="#9ccaa8"/><path d="M36 192 Q90 172 140 190 T186 184 V204 H36Z" fill="#7fb592"/>
<rect x="104" y="146" width="5" height="26" fill="#9b6b43"/><circle cx="106" cy="138" r="16" fill="#6fae85"/></g>
<path d="M107 34 V204 M36 119 H186" stroke="#fffdf7" stroke-width="6"/>
<path d="M192 70 L352 336 L236 336 L192 180Z" fill="#fff7d8" opacity=".55"/>
<rect x="246" y="102" width="138" height="9" rx="4" fill="#c79a68"/><rect x="262" y="66" width="26" height="36" rx="6" fill="#a9c4ae"/><rect x="296" y="74" width="22" height="28" rx="5" fill="#f0b94f"/><rect x="326" y="62" width="32" height="40" rx="7" fill="#d98b63"/>
<rect x="268" y="62" width="14" height="5" rx="2" fill="#7da18a"/><rect x="332" y="58" width="20" height="5" rx="2" fill="#b9694a"/>
<path d="M330 150 q-8 -34 12 -46 q4 26 -12 46z M330 150 q18 -26 36 -20 q-8 22 -36 20z" fill="#6fae85" opacity="0"/>
<rect x="0" y="334" width="400" height="106" fill="#8fb59c"/><rect x="0" y="326" width="400" height="14" fill="#ead6ae"/><rect x="0" y="340" width="400" height="4" fill="#7da18a"/>
<g><rect x="136" y="300" width="128" height="26" rx="7" fill="#fffdf7" stroke="#d9c9a0" stroke-width="2"/>
<g><rect x="141.0" y="304" width="14.6" height="18" rx="4" fill="#f0a830"/><rect x="158.4" y="304" width="14.6" height="18" rx="4" fill="#a9c4ae"/><rect x="175.8" y="304" width="14.6" height="18" rx="4" fill="#f0a830"/><rect x="193.2" y="304" width="14.6" height="18" rx="4" fill="#a9c4ae"/><rect x="210.6" y="304" width="14.6" height="18" rx="4" fill="#f0a830"/><rect x="228.0" y="304" width="14.6" height="18" rx="4" fill="#a9c4ae"/><rect x="245.4" y="304" width="14.6" height="18" rx="4" fill="#c4673b"/></g></g>
<g transform="translate(54 326)"><ellipse cx="0" cy="0" rx="34" ry="6" fill="#fffdf7" stroke="#d9c9a0" stroke-width="2"/><path d="M-22 -26 H22 V-8 Q22 2 0 2 Q-22 2 -22 -8Z" fill="#fff" stroke="#e0d2ac" stroke-width="2"/><path d="M22 -22 q14 0 14 9 q0 9 -14 9" fill="none" stroke="#e0d2ac" stroke-width="3"/><rect x="-18" y="-24" width="36" height="6" fill="#c4673b" opacity=".9"/></g>
<g class="steam" transform="translate(54 292)" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round"><path d="M-8 0 q-8 -10 0 -18 q8 -8 0 -16"/><path d="M8 0 q-8 -10 0 -18 q8 -8 0 -16"/></g>
<g transform="translate(346 326)"><ellipse cx="0" cy="0" rx="34" ry="6" fill="#fffdf7" stroke="#d9c9a0" stroke-width="2"/><path d="M-22 -26 H22 V-8 Q22 2 0 2 Q-22 2 -22 -8Z" fill="#fff" stroke="#e0d2ac" stroke-width="2"/><path d="M-22 -22 q-14 0 -14 9 q0 9 14 9" fill="none" stroke="#e0d2ac" stroke-width="3"/><rect x="-18" y="-24" width="36" height="6" fill="#0e6b6b" opacity=".85"/></g>
<g class="steam" transform="translate(346 292)" fill="none" stroke="#fff" stroke-width="3.5" stroke-linecap="round"><path d="M-8 0 q-8 -10 0 -18 q8 -8 0 -16"/><path d="M8 0 q-8 -10 0 -18 q8 -8 0 -16"/></g>
</svg>
<div class="ph"><div class="bar"><span class="av">R</span><span>Robin<small>AI assistant</small></span></div>
<div class="chat"><div class="m in vn"><i class="pl"></i><span class="wv" aria-hidden="true"><s style="height:6px;--i:0"></s><s style="height:10px;--i:1"></s><s style="height:16px;--i:2"></s><s style="height:9px;--i:3"></s><s style="height:14px;--i:4"></s><s style="height:20px;--i:5"></s><s style="height:12px;--i:6"></s><s style="height:8px;--i:7"></s><s style="height:15px;--i:8"></s><s style="height:19px;--i:9"></s><s style="height:11px;--i:10"></s><s style="height:7px;--i:11"></s></span><span class="dur">0:08</span></div>
<div class="m in" data-t="mA1">Namaste! Did you take your medicine?</div>
<div class="m out vn"><i class="pl"></i><span class="wv" aria-hidden="true"><s style="height:6px;--i:0"></s><s style="height:10px;--i:1"></s><s style="height:16px;--i:2"></s><s style="height:9px;--i:3"></s><s style="height:14px;--i:4"></s><s style="height:20px;--i:5"></s><s style="height:12px;--i:6"></s><s style="height:8px;--i:7"></s><s style="height:15px;--i:8"></s><s style="height:19px;--i:9"></s><s style="height:11px;--i:10"></s><s style="height:7px;--i:11"></s></span><span class="dur">0:03</span></div></div></div></div></div></div></header>

<section class="sec"><div class="w"><ul class="moms">
<li class="mom rv"><svg viewBox="0 0 96 96" aria-hidden="true"><circle cx="48" cy="48" r="46" fill="#dfe9dc"/><rect x="29" y="14" width="38" height="68" rx="9" fill="#21302b"/><rect x="33" y="22" width="30" height="52" rx="4" fill="#fffdf7"/><rect x="37" y="30" width="22" height="14" rx="6" fill="#e3f3dc"/><g fill="#2f7d62"><rect x="40" y="35" width="2.4" height="4" rx="1"/><rect x="44" y="33" width="2.4" height="8" rx="1"/><rect x="48" y="31.5" width="2.4" height="11" rx="1"/><rect x="52" y="34" width="2.4" height="6" rx="1"/></g><rect x="37" y="50" width="16" height="9" rx="4" fill="#eee7d6"/><rect x="43" y="62" width="14" height="8" rx="4" fill="#f6b73c"/></svg><span data-t="p1">A daily hello, by voice note</span></li>
<li class="mom rv"><svg viewBox="0 0 96 96" aria-hidden="true"><circle cx="48" cy="48" r="46" fill="#fbe6b9"/><rect x="12" y="34" width="72" height="30" rx="8" fill="#fffdf7" stroke="#d9c9a0" stroke-width="2"/><rect x="15.5" y="38" width="8.5" height="22" rx="3" fill="#f0a830"/><rect x="25.5" y="38" width="8.5" height="22" rx="3" fill="#a9c4ae"/><rect x="35.5" y="38" width="8.5" height="22" rx="3" fill="#f0a830"/><rect x="45.5" y="38" width="8.5" height="22" rx="3" fill="#a9c4ae"/><rect x="55.5" y="38" width="8.5" height="22" rx="3" fill="#f0a830"/><rect x="65.5" y="38" width="8.5" height="22" rx="3" fill="#a9c4ae"/><rect x="75.5" y="38" width="8.5" height="22" rx="3" fill="#c4673b"/><ellipse cx="30" cy="25" rx="9" ry="4.5" fill="#0e6b6b" transform="rotate(-25 30 25)"/><ellipse cx="66" cy="75" rx="9" ry="4.5" fill="#fff" stroke="#d9c9a0" stroke-width="2" transform="rotate(20 66 75)"/></svg><span data-t="p2">Medicine reminders, refill heads-up</span></li>
<li class="mom rv"><svg viewBox="0 0 96 96" aria-hidden="true"><circle cx="48" cy="48" r="46" fill="#d6e8e6"/><path d="M14 24 H62 a8 8 0 0 1 8 8 v16 a8 8 0 0 1 -8 8 H34 l-12 10 v-10 h-8 a8 8 0 0 1 -8 -8 V32 a8 8 0 0 1 8 -8z" transform="translate(2 0)" fill="#fffdf7"/><g fill="none" stroke="#0e6b6b" stroke-width="4" stroke-linecap="round"><path d="M30 40 h-3 a6 6 0 0 1 0 -12 h6"/><path d="M42 36 h3 a6 6 0 0 1 0 12 h-6"/><path d="M31 38 h12"/></g><circle cx="68" cy="68" r="17" fill="#f0a830"/><text x="68" y="76" text-anchor="middle" font-family="Georgia,serif" font-weight="700" font-size="24" fill="#2a2008">?</text></svg><span data-t="p3">Doubtful message? They ask Robin</span></li></ul></div></section>

<section class="sec band"><div class="w"><ol class="steps">
<li class="step rv"><svg viewBox="0 0 220 150" aria-hidden="true"><rect width="220" height="150" fill="#e1eadd"/><rect x="150" y="34" width="46" height="62" rx="4" fill="#cfe3e6"/><path d="M173 34 V96 M150 65 H196" stroke="#fff" stroke-width="4"/><g transform="translate(78 124) scale(0.92)"><path d="M-20 -70 Q-23 -99 0 -99 Q23 -99 20 -70 L24 -42 Q15 -40 12 -50 L-12 -50 Q-15 -40 -24 -42Z" fill="#2b2321"/><path d="M-46 0 V-20 Q-46 -47 -16 -50 L-8 -51 H8 L16 -50 Q46 -47 46 -20 V0Z" fill="#0e6b6b"/><rect x="-7" y="-60" width="14" height="14" rx="5" fill="#d79d77"/><circle cx="-17" cy="-71" r="3.5" fill="#d79d77"/><circle cx="17" cy="-71" r="3.5" fill="#d79d77"/><ellipse cx="0" cy="-73" rx="17" ry="19.5" fill="#d79d77"/><path d="M-18 -76 Q-20 -97 0 -96 Q20 -97 18 -76 Q12 -87 0 -86 Q-12 -87 -18 -76Z" fill="#2b2321"/><circle cx="-6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="-11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><circle cx="11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><path d="M-6.5 -65 Q0 -59 6.5 -65" fill="none" stroke="#8a3b2a" stroke-width="1.9" stroke-linecap="round"/><path d="M36 -38 Q42 -18 24 -12" fill="none" stroke="#0e6b6b" stroke-width="11" stroke-linecap="round"/><rect x="12" y="-40" width="16" height="27" rx="3.5" fill="#27323a"/><rect x="14" y="-37" width="12" height="21" rx="2" fill="#dff5e9"/><ellipse cx="22" cy="-12" rx="8" ry="5.5" fill="#d79d77"/></g><rect x="0" y="122" width="220" height="28" fill="#c79a68"/><rect x="0" y="122" width="220" height="5" fill="#d9b186"/><path d="M118 122 l8 -40 h54 l8 40z" fill="#3a4a45"/><rect x="128" y="86" width="44" height="30" rx="2" fill="#f4f1e6"/><rect x="134" y="94" width="26" height="4" rx="2" fill="#2f7d62"/><rect x="134" y="102" width="18" height="4" rx="2" fill="#f0a830"/><rect x="180" y="104" width="18" height="18" rx="3" fill="#c4673b"/><path d="M189 104 q-12 -14 -6 -24 q4 10 6 24 q10 -14 16 -22 q2 12 -16 22z" fill="#6fae85"/></svg><div><b>1</b><span data-t="s1">You set it up</span></div></li>
<li class="step rv"><svg viewBox="0 0 220 150" aria-hidden="true"><rect width="220" height="150" fill="#fbe9c4"/><circle cx="184" cy="30" r="12" fill="#f6b73c"/><line x1="201.0" y1="30.0" x2="208.0" y2="30.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="196.0" y1="42.0" x2="201.0" y2="47.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="184.0" y1="47.0" x2="184.0" y2="54.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="172.0" y1="42.0" x2="167.0" y2="47.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="167.0" y1="30.0" x2="160.0" y2="30.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="172.0" y1="18.0" x2="167.0" y2="13.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="184.0" y1="13.0" x2="184.0" y2="6.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><line x1="196.0" y1="18.0" x2="201.0" y2="13.0" stroke="#f6b73c" stroke-width="3" stroke-linecap="round"/><rect x="14" y="30" width="46" height="40" rx="3" fill="#fffdf7"/><rect x="20" y="38" width="34" height="3" fill="#d98b63"/><rect x="20" y="48" width="34" height="3" fill="#a9c4ae"/><g transform="translate(112 150) scale(1.0)"><circle cx="0" cy="-101" r="9" fill="#b9b4ac"/><path d="M-46 0 V-20 Q-46 -47 -16 -50 L-8 -51 H8 L16 -50 Q46 -47 46 -20 V0Z" fill="#d98b63"/><path d="M-32 -47 L-10 -50 Q8 -22 40 -6 L40 0 L8 0 Q-12 -22 -34 -36Z" fill="#f0a830"/><rect x="-7" y="-60" width="14" height="14" rx="5" fill="#c98f68"/><circle cx="-17" cy="-71" r="3.5" fill="#c98f68"/><circle cx="17" cy="-71" r="3.5" fill="#c98f68"/><ellipse cx="0" cy="-73" rx="17" ry="19.5" fill="#c98f68"/><path d="M-18 -76 Q-20 -97 0 -96 Q20 -97 18 -76 Q12 -87 0 -86 Q-12 -87 -18 -76Z" fill="#b9b4ac"/><circle cx="-6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="-11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><circle cx="11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><path d="M-8 -66 Q0 -53 8 -66Z" fill="#8a3b2a"/><path d="M-6 -66 H6 Q0 -62 -6 -66Z" fill="#fff"/><path d="M38 -34 Q50 -48 30 -60" fill="none" stroke="#d98b63" stroke-width="11" stroke-linecap="round"/><rect x="21" y="-88" width="13" height="24" rx="3.5" fill="#27323a" transform="rotate(12 27 -76)"/><circle cx="30" cy="-62" r="6" fill="#c98f68"/></g><g><rect x="132" y="22" width="76" height="30" rx="14" fill="#e3f3dc"/><path d="M150 52 l-8 10 l16 -10z" fill="#e3f3dc"/><path d="M144 33 l9 5 l-9 5z" fill="#2f7d62"/><g fill="#2f7d62"><rect x="162" y="33" width="3" height="10" rx="1.5"/><rect x="168" y="30" width="3" height="16" rx="1.5"/><rect x="174" y="34" width="3" height="8" rx="1.5"/><rect x="180" y="29" width="3" height="18" rx="1.5"/><rect x="186" y="33" width="3" height="10" rx="1.5"/><rect x="192" y="35" width="3" height="6" rx="1.5"/></g></g></svg><div><b>2</b><span data-t="s2">They chat by voice note</span></div></li>
<li class="step rv"><svg viewBox="0 0 220 150" aria-hidden="true"><rect width="220" height="150" fill="#d6e8e6"/><g transform="translate(66 150) scale(0.95)"><path d="M-46 0 V-20 Q-46 -47 -16 -50 L-8 -51 H8 L16 -50 Q46 -47 46 -20 V0Z" fill="#f0a830"/><rect x="-7" y="-60" width="14" height="14" rx="5" fill="#e0a982"/><circle cx="-17" cy="-71" r="3.5" fill="#e0a982"/><circle cx="17" cy="-71" r="3.5" fill="#e0a982"/><ellipse cx="0" cy="-73" rx="17" ry="19.5" fill="#e0a982"/><path d="M-18 -76 Q-20 -97 0 -96 Q20 -97 18 -76 Q12 -87 0 -86 Q-12 -87 -18 -76Z" fill="#2b2321"/><circle cx="-6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="6.5" cy="-74" r="1.9" fill="#2a2320"/><circle cx="-11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><circle cx="11" cy="-67" r="3.2" fill="#e8786a" opacity=".28"/><path d="M-6.5 -65 Q0 -59 6.5 -65" fill="none" stroke="#8a3b2a" stroke-width="1.9" stroke-linecap="round"/><path d="M36 -38 Q42 -18 24 -12" fill="none" stroke="#f0a830" stroke-width="11" stroke-linecap="round"/><rect x="12" y="-40" width="16" height="27" rx="3.5" fill="#27323a"/><rect x="14" y="-37" width="12" height="21" rx="2" fill="#dff5e9"/><ellipse cx="22" cy="-12" rx="8" ry="5.5" fill="#e0a982"/></g><g><rect x="118" y="26" width="86" height="96" rx="14" fill="#fffdf7" stroke="#cfdcd8" stroke-width="2"/><circle cx="136" cy="50" r="8" fill="#2f7d62"/><path d="M132 50 l3 3 l6 -6" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><rect x="150" y="47" width="40" height="6" rx="3" fill="#cfd8d3"/><circle cx="136" cy="72" r="8" fill="#2f7d62"/><path d="M132 72 l3 3 l6 -6" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><rect x="150" y="69" width="34" height="6" rx="3" fill="#cfd8d3"/><circle cx="136" cy="94" r="8" fill="#2f7d62"/><path d="M132 94 l3 3 l6 -6" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/><rect x="150" y="91" width="28" height="6" rx="3" fill="#cfd8d3"/><rect x="132" y="100" width="58" height="16" rx="8" fill="#0e6b6b"/></g></svg><div><b>3</b><span data-t="s3">You get a calm summary</span></div></li></ol></div></section>

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
<div class="ok" id="ok" aria-live="polite"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="30" fill="#2f7d62"/><path d="M19 33l9 9 17-20" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>
<p data-t="ok">You are on the list. We will message you on WhatsApp when your spot opens. One small thing for today: pick a time of day your parents like to chat, so you can set it as their daily hello.</p>
<a class="btn share" id="share" href="#" target="_blank" rel="noopener" data-t="share">Share on WhatsApp</a></div>
</div></div></section>
<section class="sec" style="padding-top:8px"><div class="w"><div class="faqs rv">
<details class="faq"><summary data-t="q1">Is Robin a person?</summary><p data-t="a1">No. Robin is an AI assistant. There is no human desk at launch, and Robin never pretends to be a person.</p></details>
<details class="faq"><summary data-t="q2">Does Robin listen to calls?</summary><p data-t="a2">No. Robin does not read your parent's chats and does not record their phone calls.</p></details>
<details class="faq"><summary data-t="q3">Can my parent say no?</summary><p data-t="a3">Yes. Robin introduces itself to them when you set it up, and they can stop it any time by saying so.</p></details>
<details class="faq"><summary data-t="q4">What does it cost?</summary><p data-t="a4">Joining the waitlist is free. No price is announced yet.</p></details>
<details class="faq"><summary data-t="q5">Is it an emergency service?</summary><p data-t="a5">No. In an emergency call 112. Robin has an SOS button that alerts you, but it is not a rescue service.</p></details>
</div></div></section>
<section class="sec" style="padding:8px 0 24px"><div class="w"><p class="scam"><span data-t="sc1">Why scam help? Calls and messages that pressure seniors into sending money keep appearing in the news, for example in </span><a href="https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud" target="_blank" rel="noopener">The Tribune</a><span data-t="sc2"> and </span><a href="https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app" target="_blank" rel="noopener">Free Press Journal</a><span data-t="sc3">.</span></p></div></section>
<footer class="foot"><div class="w"><p data-t="foot">Robin is an AI assistant, not a person. It is not an emergency service: in an emergency call 112. Robin is not live yet.</p><p><a href="privacy" data-t="priv2">How we use your details</a></p></div></footer>
<div class="sticky" id="sticky"><a class="btn" href="#join" data-t="stk">Join the waitlist, it is free</a></div>
<script>
document.documentElement.className+=" js";
const T={hi:{"promise":"Robin roz aapke parents se WhatsApp par, unki bhasha mein, haal-chaal leta hai, aur kaman unhi ke haath mein rehti hai.","ln":"Aapka naam","lp":"Aapka WhatsApp number","cons":"Hum aapko sirf launch ke baare mein WhatsApp karenge. Aapka number bechte ya ads ke liye share nahi karte. Kabhi bhi delete karwa sakte hain.","nopay":"Koi payment nahi. Price abhi announce nahi hua.","priv":"Hum aapki details kaise use karte hain","share":"WhatsApp par bhejiye","foot":"Robin ek AI assistant hai, insaan nahi. Ye emergency service nahi hai: emergency mein 112 par call karein. Robin abhi live nahi hai.","h1":"<em>Parents<\/em> ka haal, roz pata rahe.","sub":"Robin roz WhatsApp par aapke parents ko hello bolta hai, aur kuch theek na lage to aapko batata hai.","btn":"Waitlist mein judiye","stk":"Waitlist mein judiye, free hai","mA1":"Namaste! Dawai li?","p1":"Roz ka hello, voice note mein","p2":"Dawai ke reminder, refill ki khabar","p3":"Shak ho to Robin se poochein","s1":"Aap set up karte hain","s2":"Wo voice note mein baat karte hain","s3":"Aapko shaant summary milti hai","sc1":"Scam help kyun? Seniors par paise bhejne ka dabav daalne wali calls aur messages khabron mein aate rehte hain, jaise ","sc2":" aur ","sc3":" mein.","q1":"Kya Robin insaan hai?","a1":"Nahi. Robin ek AI assistant hai. Launch par koi human desk nahi hai, aur Robin insaan hone ka dikhawa nahi karta.","q2":"Kya Robin calls sunta hai?","a2":"Nahi. Robin aapke parent ki chats nahi padhta aur unki phone calls record nahi karta.","q3":"Kya mere parent mana kar sakte hain?","a3":"Haan. Set up ke time Robin unhe apna parichay deta hai, aur wo kabhi bhi bol kar ise rok sakte hain.","q4":"Isme kitna kharcha hai?","a4":"Waitlist free hai. Price abhi announce nahi hua.","q5":"Kya ye emergency service hai?","a5":"Nahi. Emergency mein 112 par call karein. Robin ke SOS button se aapko alert jata hai, par ye rescue service nahi hai.","ok":"Aap list mein hain. Spot khulte hi hum WhatsApp par batayenge. Aaj ke liye ek chhoti baat: socho aapke parents ko din mein kab baat karna pasand hai, wahi unke daily hello ka time hoga.","priv2":"Hum aapki details kaise use karte hain"}};
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
