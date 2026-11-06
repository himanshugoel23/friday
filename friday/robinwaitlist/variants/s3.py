# ruff: noqa: E501
"""Landing page variant S3 (docs/ROBIN_LANDING_BRIEF.md, revision 2). English only. The token {{VARIANT}} is replaced by the router."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><meta name="color-scheme" content="light"><meta name="theme-color" content="#111615"><title>Robin waitlist</title>
<meta name="description" content="Unknown, missed or urgent: Robin helps with the call. Join the waitlist.">
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

:root{--bg:#f3f0e8;--ink:#141a19;--mut:#434b49;--link:#0d6b47;--acc:#0d6b47;--btn:#3ddc97;--btnc:#06150e;--btnsh:0 10px 26px rgba(61,220,151,.28);--brandc:#f2f0ea;
--card:#fff;--line:#dedad0;--inb:#aaa69a;--inbg:#fff;--err:#9c2b1f;--focus:#0d6b47;--rad:12px;--rad2:20px;--rad3:12px;--bezel:#323c3a;--bar:#232c2a;--avbg:#3ddc97;
--chatbg:#1a2120;--outbub:#1f4a3a;--footbg:#111615;--footc:#c9ccc6;
--hfont:700 24px var(--sans);
--sans:"Avenir Next","Segoe UI",-apple-system,BlinkMacSystemFont,Roboto,"Helvetica Neue","Noto Sans","Noto Sans Devanagari","Nirmala UI",Arial,sans-serif}
body{font-variant-numeric:tabular-nums}
.dk{background:radial-gradient(80% 50% at 85% 0,#1d2b27 0,#111615 70%);color:#f2f0ea;overflow:hidden}
.dk .top{padding:18px 0}
.hero{padding:26px 0 8px;position:relative}
h1{font:700 35px/1.08 var(--sans);letter-spacing:-1px;max-width:13em}
.sub{margin:16px 0 26px;font-size:19px;line-height:1.55;color:#cfd6d2;max-width:31em}
.trust{margin-top:20px;font-size:15.5px;color:#aab6b1;max-width:31em;line-height:1.55}
.wvl{display:block;margin:30px 0 4px;color:#3ddc97;opacity:.38;max-width:100%;height:auto}
.tl{position:relative;display:grid;gap:34px;padding-left:34px;margin:10px 0 0}
.tl:before{content:"";position:absolute;left:7px;top:10px;bottom:10px;width:2px;background:linear-gradient(#3ddc97,rgba(61,220,151,.15))}
.mo{position:relative;display:flex;flex-direction:column;gap:12px}
.mo .lb{display:flex;align-items:center;gap:10px;font:700 13px var(--sans);letter-spacing:1.5px;text-transform:uppercase;color:#3ddc97}
.mo .lb:before{content:"";position:absolute;left:-34px;top:2px;width:16px;height:16px;border-radius:50%;background:#111615;border:3px solid #3ddc97}
.mo .ds{font-size:17px;line-height:1.5;color:#cfd6d2;max-width:24em}
.mo .ph{border-color:var(--bezel)}
.dk .m{background:#27312f;color:#ecebe4;box-shadow:none}.dk .out{background:#1f4a3a}
.dk .m .cap{color:#aeb8b4;border-color:#3b4644}.dk .m .fw{color:#9fa9a5}
.dk .alertc{background:#27312f;color:#ecebe4;box-shadow:none;border:1px solid #38433f}.dk .alertc b{color:#9fa9a5}.dk .alertc .cb{background:#3ddc97;color:#06150e}
.dk .chip.cor{background:#5b2a22;color:#ffc9bd}.dk .chip.grn{background:#1d4a38;color:#aef0cd}.dk .chip.amb{background:#5a4513;color:#ffe2a1}
.sm{padding:4px 2px;font-size:13.5px;line-height:1.6;color:#d8d6ce}.sm div{display:flex;justify-content:space-between;gap:10px;border-top:1px solid #38433f;padding:6px 0}.sm div:first-of-type{border-top:0}.sm span:first-child{color:#9fa9a5}
.light{background:var(--bg)}
.js .tl .m,.js .tl .alertc,.js .tl .sm{opacity:0}
.js .tl .mo.on .m,.js .tl .mo.on .alertc,.js .tl .mo.on .sm{animation:pop .6s ease forwards;animation-delay:calc(var(--n)*.8s + .3s)}
@keyframes pop{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.pg{display:grid;gap:14px}
.pi{display:flex;gap:16px;align-items:center;background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px}
.pi svg{flex:none;stroke:#0d6b47}.pi h3{font:650 19px/1.3 var(--sans)}
.sup{margin-top:24px;color:var(--mut);font-size:17px}.sup p+p{margin-top:4px}
.eyebrow{margin-bottom:14px}
.hw{display:grid;gap:12px}.hw li{display:flex;gap:16px;align-items:center;padding:16px 18px;border-radius:14px;background:#e8e4d9}
.hw b{font:700 22px var(--sans);color:#0d6b47;min-width:24px}.hw span{font:650 19px/1.3 var(--sans)}
.cs{display:grid;gap:16px}
.cc{background:#fff;border:1px solid var(--line);border-radius:18px;overflow:hidden;display:flex;flex-direction:column}
.rep{padding:22px}.rep .tag{font:700 12px var(--sans);letter-spacing:1.4px;text-transform:uppercase;color:#8a5a00;margin-bottom:10px}
.rep h3{font:650 19px/1.35 var(--sans);margin-bottom:12px}.rep .src{font-size:14.5px;color:var(--mut)}.rep .src span{font-weight:700;color:var(--ink)}
.rl{display:inline-block;margin-top:12px;font-weight:700;color:var(--link);text-underline-offset:3px;min-height:24px;font-size:15.5px}
.rob{margin-top:auto;padding:16px 22px 20px;background:#111615;color:#e6e8e3;font-size:16px;line-height:1.5}.rob b{color:#3ddc97}
.note{margin-top:18px;font-size:15px;color:var(--mut)}
@media (min-width:760px){
 h1{font-size:60px}.hero{padding-top:40px}.sub{font-size:21px}
 .tl.h{grid-template-columns:1fr 1fr;padding-left:0;gap:30px;margin-top:18px}.tl.h:before{left:0;right:0;top:8px;bottom:auto;width:auto;height:2px;background:linear-gradient(90deg,#3ddc97,rgba(61,220,151,.15))}
 .tl.h .mo{padding-top:34px}.tl.h .mo .lb:before{left:0;top:-30px}.tl.h .mo .lb{margin-top:0}
 .tl.h2{grid-template-columns:1fr 1fr;padding-left:0;gap:30px}.tl.h2:before{left:0;right:0;top:8px;bottom:auto;width:auto;height:2px;background:linear-gradient(90deg,#3ddc97,rgba(61,220,151,.15))}
 .tl.h2 .mo{padding-top:34px}.tl.h2 .mo .lb:before{left:0;top:-30px}
 .mo{flex-direction:column}
 .pg{grid-template-columns:repeat(4,1fr)}.pi{flex-direction:column;align-items:flex-start;padding:24px}
 .hw{grid-template-columns:repeat(3,1fr)}.hw li{flex-direction:column;align-items:flex-start;padding:24px}
 .cs{grid-template-columns:repeat(3,1fr)}
 .hgrid{display:grid;grid-template-columns:1fr 1.05fr;gap:40px;align-items:start}.hgrid .tl{margin-top:8px}
 .wvl{margin-top:44px}
}
</style></head><body>
<div class="dk"><header class="hero"><div class="w"><div class="top"><span class="brand"><svg viewBox="0 0 40 40" aria-hidden="true"><rect x="1.5" y="1.5" width="37" height="37" rx="10" fill="#3ddc97"/><path d="M12 28 V12 h9 a6 6 0 0 1 0 12 h-9 M20 24 l7 4" fill="none" stroke="#06150e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>Robin</span></div>
<div class="hgrid"><div><h1>Unknown, missed or urgent: Robin helps with the call</h1>
<p class="sub">Robin answers calls your parents cannot take, highlights urgent ones you missed, and alerts you when a call looks risky.</p>
<a class="btn" href="#join">Join the waitlist</a><p class="trust">Your parents are told, can stop it any time, and Robin does not read their chats or record their phone calls.</p></div>
<ol class="tl h"><li class="mo rv"><span class="lb">Unknown call</span><div class="ph"><div class="bar"><span class="av" style="color:#06150e">R</span><span>Robin<small>AI assistant</small></span></div><div class="chat"><div class="m out" style="--n:0"><span class="fw">&#8618; Forwarded</span>+91 98&#8226;&#8226;&#8226;&#8226;&#8226; &#8226;&#8226;210</div><div class="m in" style="--n:1"><span class="chip amb">Looks like a known scam pattern</span><span class="hi" lang="hi">यह स्कैम जैसा लगता है। OTP या PIN किसी को न बताएं। पहले अपने बेटे से बात करें।</span><span class="cap">Looks like a scam. Do not share your OTP or PIN. Talk to your son first.</span></div></div></div><p class="ds">Your parent forwards the number or the message; Robin gives a plain answer.</p></li><li class="mo rv"><span class="lb">Missed call</span><div class="ph"><div class="bar"><span class="av" style="color:#06150e">R</span><span>Robin<small>Your phone</small></span></div><div class="chat"><div class="alertc" style="--n:0;margin:0"><span class="chip cor">Urgent</span><b>MISSED CALL &middot; MOM</b>Robin: this sounds urgent. I will ring you again.<span class="cb">Call Mom</span></div></div></div><p class="ds">You miss your parent's call; if it sounds urgent, Robin highlights it and keeps ringing you on a schedule.</p></li></ol></div></div></header>
<section style="padding:22px 0 64px"><div class="w"><svg class="wvl" viewBox="0 0 368 26" width="368" height="26" aria-hidden="true"><rect x="0" y="9.5" width="3" height="7.1" rx="1.5" fill="currentColor"/><rect x="8" y="7.1" width="3" height="11.8" rx="1.5" fill="currentColor"/><rect x="16" y="3.5" width="3" height="18.9" rx="1.5" fill="currentColor"/><rect x="24" y="7.7" width="3" height="10.6" rx="1.5" fill="currentColor"/><rect x="32" y="4.7" width="3" height="16.5" rx="1.5" fill="currentColor"/><rect x="40" y="1.2" width="3" height="23.6" rx="1.5" fill="currentColor"/><rect x="48" y="5.9" width="3" height="14.2" rx="1.5" fill="currentColor"/><rect x="56" y="8.3" width="3" height="9.5" rx="1.5" fill="currentColor"/><rect x="64" y="4.1" width="3" height="17.7" rx="1.5" fill="currentColor"/><rect x="72" y="1.8" width="3" height="22.5" rx="1.5" fill="currentColor"/><rect x="80" y="6.5" width="3" height="13.0" rx="1.5" fill="currentColor"/><rect x="88" y="8.9" width="3" height="8.3" rx="1.5" fill="currentColor"/><rect x="96" y="5.3" width="3" height="15.4" rx="1.5" fill="currentColor"/><rect x="104" y="2.4" width="3" height="21.3" rx="1.5" fill="currentColor"/><rect x="112" y="7.1" width="3" height="11.8" rx="1.5" fill="currentColor"/><rect x="120" y="9.5" width="3" height="7.1" rx="1.5" fill="currentColor"/><rect x="128" y="5.9" width="3" height="14.2" rx="1.5" fill="currentColor"/><rect x="136" y="3.5" width="3" height="18.9" rx="1.5" fill="currentColor"/><rect x="144" y="7.7" width="3" height="10.6" rx="1.5" fill="currentColor"/><rect x="152" y="10.0" width="3" height="5.9" rx="1.5" fill="currentColor"/><rect x="160" y="9.5" width="3" height="7.1" rx="1.5" fill="currentColor"/><rect x="168" y="7.1" width="3" height="11.8" rx="1.5" fill="currentColor"/><rect x="176" y="3.5" width="3" height="18.9" rx="1.5" fill="currentColor"/><rect x="184" y="7.7" width="3" height="10.6" rx="1.5" fill="currentColor"/><rect x="192" y="4.7" width="3" height="16.5" rx="1.5" fill="currentColor"/><rect x="200" y="1.2" width="3" height="23.6" rx="1.5" fill="currentColor"/><rect x="208" y="5.9" width="3" height="14.2" rx="1.5" fill="currentColor"/><rect x="216" y="8.3" width="3" height="9.5" rx="1.5" fill="currentColor"/><rect x="224" y="4.1" width="3" height="17.7" rx="1.5" fill="currentColor"/><rect x="232" y="1.8" width="3" height="22.5" rx="1.5" fill="currentColor"/><rect x="240" y="6.5" width="3" height="13.0" rx="1.5" fill="currentColor"/><rect x="248" y="8.9" width="3" height="8.3" rx="1.5" fill="currentColor"/><rect x="256" y="5.3" width="3" height="15.4" rx="1.5" fill="currentColor"/><rect x="264" y="2.4" width="3" height="21.3" rx="1.5" fill="currentColor"/><rect x="272" y="7.1" width="3" height="11.8" rx="1.5" fill="currentColor"/><rect x="280" y="9.5" width="3" height="7.1" rx="1.5" fill="currentColor"/><rect x="288" y="5.9" width="3" height="14.2" rx="1.5" fill="currentColor"/><rect x="296" y="3.5" width="3" height="18.9" rx="1.5" fill="currentColor"/><rect x="304" y="7.7" width="3" height="10.6" rx="1.5" fill="currentColor"/><rect x="312" y="10.0" width="3" height="5.9" rx="1.5" fill="currentColor"/><rect x="320" y="9.5" width="3" height="7.1" rx="1.5" fill="currentColor"/><rect x="328" y="7.1" width="3" height="11.8" rx="1.5" fill="currentColor"/><rect x="336" y="3.5" width="3" height="18.9" rx="1.5" fill="currentColor"/><rect x="344" y="7.7" width="3" height="10.6" rx="1.5" fill="currentColor"/><rect x="352" y="4.7" width="3" height="16.5" rx="1.5" fill="currentColor"/><rect x="360" y="1.2" width="3" height="23.6" rx="1.5" fill="currentColor"/></svg>
<ol class="tl h2"><li class="mo rv"><span class="lb">Parent cannot pick up</span><div class="ph"><div class="bar"><span class="av" style="color:#06150e">R</span><span>Robin<small>AI assistant</small></span></div><div class="chat"><div class="alertc" style="--n:0;margin:0"><span class="chip grn">Answered by Robin</span><b>CALL SUMMARY</b><div class="sm"><div><span>Caller</span><span>Courier (said)</span></div><div><span>Reason</span><span>Parcel at the gate</span></div><div><span>Robin</span><span>Answered as an AI assistant</span></div></div></div></div></div><p class="ds">Robin answers as an AI assistant, asks who is calling and why, and sends your parent a summary.</p></li><li class="mo rv"><span class="lb">SOS</span><div class="ph"><div class="bar"><span class="av" style="color:#06150e">R</span><span>Robin<small>Your phone</small></span></div><div class="chat"><div class="alertc" style="--n:0;margin:0"><span class="chip cor">SOS</span><b>SOS &middot; MOM</b>You and your named contact were alerted.<span class="cb">Call Mom</span></div></div></div><p class="ds">Hold the button; you and your named contact are alerted at once.</p></li></ol></div></section></div>

<div class="light"><section class="sec"><div class="w"><ul class="pg rv"><li class="pi"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#0d6b47" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8 h7 l3 8 l-4 3 a20 20 0 0 0 9 9 l3 -4 l8 3 v7 a4 4 0 0 1 -4 4 C21 38 8 25 8 12 a4 4 0 0 1 4 -4z"/></svg><h3>Parent can't pick up? Robin answers</h3></li><li class="pi"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#0d6b47" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 8 h6 l3 8 l-4 3 a20 20 0 0 0 9 9 l3 -4 l8 3 v6 a4 4 0 0 1 -4 4 C20 37 8 24 9 12 a4 4 0 0 1 4 -4z"/><path d="M30 6 l8 8 M38 6 l-8 8"/></svg><h3>Urgent missed calls, highlighted for you</h3></li><li class="pi"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#0d6b47" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="14" y="5" width="20" height="38" rx="5"/><path d="M21 38 h6"/><path d="M24 14 v10"/><circle cx="24" cy="29" r="1"/></svg><h3>Risky call alerts, optional Android app</h3></li><li class="pi"><svg viewBox="0 0 48 48" width="44" height="44" aria-hidden="true" fill="none" stroke="#0d6b47" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="24" cy="24" r="17"/><circle cx="24" cy="24" r="9"/><path d="M24 20 v5"/><circle cx="24" cy="29" r=".8"/></svg><h3>One-press SOS to you</h3></li></ul>
<div class="sup"><p>Plus a friendly daily check-in and medicine reminders.</p><p>Also helps with calls that sound like a family member asking for money.</p></div></div></section>

<section class="sec" style="padding-top:0"><div class="w"><p class="eyebrow">How it works</p><ol class="hw rv"><li><b>1</b><span>Set up call forwarding, once</span></li><li><b>2</b><span>Robin answers, sends a summary</span></li><li><b>3</b><span>Urgent ones are highlighted</span></li></ol></div></section>

<section class="sec" style="padding-top:0"><div class="w"><p class="eyebrow">Reported cases</p><ul class="cs"><li class="cc rv"><div class="rep"><p class="tag">Digital-arrest call</p><h3>Chandigarh's elderly woman loses Rs 2.5 crore in digital arrest fraud</h3><p class="src"><span>The Tribune</span> <time>4 Jun 2025</time></p><a class="rl" href="https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><p class="rob"><b>Robin's moment:</b> your parent forwards the number or message; Robin explains the pattern and alerts you.</p></li><li class="cc rv"><div class="rep"><p class="tag">Fake KYC and a remote-access app</p><h3>Mumbai: Senior citizen loses Rs 3.95 lakh to KYC fraud after downloading AnyDesk app</h3><p class="src"><span>Free Press Journal</span> <time>12 Jan 2022</time></p><a class="rl" href="https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><p class="rob"><b>Robin's moment:</b> with the optional Android app, a remote-access app being opened can alert you.</p></li><li class="cc rv"><div class="rep"><p class="tag">Call showing a bank's name</p><h3>UPI Limit Scam Costs Pensioner Couple Nearly ₹6 Lakh In Indore</h3><p class="src"><span>Free Press Journal</span> <time>30 Sep 2026</time></p><a class="rl" href="https://www.freepressjournal.in/indore/upi-limit-scam-costs-pensioner-couple-nearly-6-lakh-in-indore" target="_blank" rel="noopener">Read the report <span aria-hidden="true">&#8599;</span></a></div><p class="rob"><b>Robin's moment:</b> it never calls a money request safe, and tells you.</p></li></ul><p class="note">News reports, linked in full. Robin is not mentioned in them.</p></div></section>

<section class="sec" style="padding-top:8px"><div class="w"><div class="faqs rv">
<details class="faq"><summary>How does Robin answer my parent's calls?</summary><p>You set up call forwarding on their phone once. When they cannot pick up, Robin answers as an AI assistant, asks who is calling and why, and sends them a summary.</p></details>
<details class="faq"><summary>Is this surveillance?</summary><p>No. Parents are told, can stop it any time, and Robin does not read chats or record calls on their phone. You see alerts and summaries.</p></details>
<details class="faq"><summary>Is Robin a person?</summary><p>No, an AI assistant. No human desk at launch.</p></details>
<details class="faq"><summary>Can my parent say no?</summary><p>Yes, at any time. Robin then tells you.</p></details>
<details class="faq"><summary>What does it cost?</summary><p>Waitlist is free. No price is announced yet.</p></details>
<details class="faq"><summary>Is it an emergency service?</summary><p>No. In an emergency call 112. SOS alerts you; it does not replace emergency help.</p></details>
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
<div class="ok" id="ok" aria-live="polite"><svg viewBox="0 0 64 64" aria-hidden="true"><circle cx="32" cy="32" r="30" fill="#0d6b47"/><path d="M19 33l9 9 17-20" fill="none" stroke="#fff" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>
<p>You are on the list. One useful step today: agree one rule with your parents, that if a caller pressures them about money or arrest, they hang up and call you on the number they already have.</p><a class="btn share" id="share" href="#" target="_blank" rel="noopener">Share on WhatsApp</a></div>
</div></div></section></div>
<footer class="foot"><div class="w"><p>Robin is an AI assistant, not a person. It is not an emergency service: in an emergency call 112. Robin is not live yet.</p><p><a href="privacy">How we use your details</a></p></div></footer>
<div class="sticky" id="sticky"><a class="btn" href="#join">Join the waitlist for call help</a></div>
<script>
document.documentElement.className+=" js";
const ERR={name:"Please add your name.",phone:"That number does not look right. If you are abroad, add the country code.",busy:"That did not go through. Please try again in a minute."};
const MSG="Robin answers calls your parents cannot take, highlights urgent ones you missed, and alerts you when a call looks risky. Join the waitlist: ";
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
