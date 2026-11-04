# ruff: noqa: E501
"""The public page: a short story, three real news reports, then name + WhatsApp number only.
English + Roman Hinglish toggle. Copy is PENDING founder approval (docs/ROBIN_WAITLIST.md).
News cards link to the publishers' own pages so every claim can be checked; the opening scene is clearly a scene, not a testimonial."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><title>Robin: for the parents you cannot call every hour</title>
<meta name="description" content="Robin checks in on your parents every day and warns you when something looks wrong. Join the waitlist.">
<style>
:root{--bg:#fbf7f1;--ink:#1d1b18;--mut:#625b51;--card:#fff;--line:#e8dfd1;--acc:#1f6f5c;--accink:#fff;--dark:#1b1814;--darkink:#f4eee5;--warn:#a1520a}
@media (prefers-color-scheme:dark){:root{--bg:#14110e;--ink:#f3eee6;--mut:#b7ad9f;--card:#1e1a16;--line:#342d25;--acc:#4bb99c;--accink:#08201a;--dark:#0d0b09;--darkink:#f4eee5;--warn:#e3ab5e}}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font:18px/1.65 Georgia,"Times New Roman",serif}
.sans{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:620px;margin:0 auto;padding:18px 20px 96px}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:34px}
.brand{font:700 21px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:.2px}
button.lang{background:none;border:1px solid var(--line);border-radius:999px;color:var(--ink);padding:6px 12px;font:14px -apple-system,sans-serif;cursor:pointer}
.time{font:600 13px -apple-system,sans-serif;letter-spacing:1.5px;color:var(--warn);text-transform:uppercase;margin:0 0 10px}
h1{font-size:36px;line-height:1.18;margin:0 0 18px;font-weight:700}
p{margin:0 0 18px}.big{font-size:22px;line-height:1.5}.soft{color:var(--mut)}
.beat{margin:30px 0}.beat p:last-child{margin-bottom:0}
.dark{background:var(--dark);color:var(--darkink);margin:36px -20px;padding:30px 20px}
.dark h2{font:700 15px -apple-system,sans-serif;letter-spacing:1.4px;text-transform:uppercase;margin:0 0 16px;color:#e3ab5e}
.news{display:block;text-decoration:none;color:inherit;border-top:1px solid #3a342c;padding:16px 0}
.news:first-of-type{border-top:0}.news b{display:block;font-size:19px;line-height:1.4;margin-bottom:4px}.news span{font:13px -apple-system,sans-serif;color:#b9aea0}
.dark .fine{font:13px/1.5 -apple-system,sans-serif;color:#a99d8f;margin:14px 0 0}
.quiet{font-size:24px;line-height:1.45;font-weight:700;margin:30px 0}
ul.pts{padding-left:0;list-style:none;margin:6px 0 22px}ul.pts li{padding:9px 0 9px 28px;position:relative}
ul.pts li:before{content:"";position:absolute;left:4px;top:18px;width:10px;height:10px;border-radius:50%;background:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;margin-top:26px;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.card h3{font:700 22px/1.3 Georgia,serif;margin:0 0 6px}.card .fine{font-size:14px;color:var(--mut)}
label{display:block;font-weight:600;margin:16px 0 6px;font-size:15px}
input[type=text],input[type=tel]{width:100%;padding:14px 12px;font-size:18px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}
button.go{margin-top:18px;width:100%;padding:16px;font-size:19px;font-weight:700;border:0;border-radius:12px;background:var(--acc);color:var(--accink);cursor:pointer}
button.go[disabled]{opacity:.6}.err{color:#b3261e;font-size:15px;margin-top:10px;min-height:20px}
.hp{position:absolute;left:-9999px;height:0;overflow:hidden}.ok{display:none}.ok h3{font:700 24px Georgia,serif;margin:0 0 10px}
.ok p{font-size:17px;margin-bottom:14px}a.share{display:inline-block;margin-top:6px;padding:13px 18px;border-radius:12px;background:var(--acc);color:var(--accink);text-decoration:none;font-weight:700}
.honest{margin-top:26px;font:14px/1.5 -apple-system,sans-serif;color:var(--warn);border-left:3px solid var(--warn);padding-left:12px}
footer{margin-top:20px;font:13px/1.5 -apple-system,sans-serif;color:var(--mut)}footer a{color:var(--mut)}
.sticky{position:fixed;left:0;right:0;bottom:0;padding:10px 16px calc(10px + env(safe-area-inset-bottom));background:linear-gradient(transparent,var(--bg) 35%);display:none}
.sticky a{display:block;max-width:620px;margin:0 auto;text-align:center;padding:15px;border-radius:12px;background:var(--acc);color:var(--accink);font:700 18px -apple-system,sans-serif;text-decoration:none}
@media (max-width:700px){.sticky{display:block}}
</style></head><body><div class="wrap">
<div class="top"><span class="brand">Robin</span><button class="lang" id="lang" type="button">हिंदी / Hinglish</button></div>

<div class="beat"><p class="time" data-t="t1">4:10 pm, a Tuesday</p>
<h1 data-t="h1">Your mother is alone at home. Her phone rings.</h1>
<p class="big" data-t="s1">The man says he is from the police. He says her son is in trouble. He says: do not tell anyone, do not hang up.</p>
<p class="big soft" data-t="s2">She is 68. She is shaking. She does not want to disturb you at work, so she does what he says.</p></div>

<div class="dark"><h2 data-t="nh">This is not a story we made up</h2>
<a class="news" href="https://www.tribuneindia.com/news/chandigarh/sector-10-elderly-woman-loses-2-5-crore-in-digital-arrest-fraud" target="_blank" rel="noopener"><b data-t="n1">An 82-year-old woman in Chandigarh lost Rs 2.5 crore to a "digital arrest" fraud.</b><span>The Tribune</span></a>
<a class="news" href="https://www.freepressjournal.in/amp/mumbai/mumbai-senior-citizen-loses-rs-395-lakh-to-kyc-fraud-after-downloading-anydesk-app" target="_blank" rel="noopener"><b data-t="n2">A senior citizen in Mumbai lost Rs 3.95 lakh after a "KYC" caller made him install an app.</b><span>Free Press Journal</span></a>
<a class="news" href="https://www.freepressjournal.in/indore/upi-limit-scam-costs-pensioner-couple-nearly-6-lakh-in-indore" target="_blank" rel="noopener"><b data-t="n3">A pensioner couple in Indore lost nearly Rs 6 lakh to a call that showed their bank's name.</b><span>Free Press Journal</span></a>
<p class="fine" data-t="nf">Reports by the publishers named above. Tap a card to read the original.</p></div>

<div class="beat"><p class="big" data-t="l1">And on the days when no one scams her, it is quieter, and not better.</p>
<p data-t="l2">She eats dinner alone. She forgets the evening tablet. When you call she says "I am fine, beta", because she does not want you to worry.</p>
<p data-t="l3">You are 800 km away, or in another country, in a meeting you cannot leave. And if she falls at 3 in the morning, who will know first?</p></div>

<p class="quiet" data-t="q1">You cannot be there every day. Robin can.</p>

<p data-t="r1">Robin checks in on your parents every day, in their language. It reminds them about their medicines. When something looks wrong, a strange call, a payment that should not happen, you hear about it in time to ring them.</p>
<ul class="pts"><li data-t="r2">They talk to Robin on WhatsApp, with a voice note if typing is hard.</li>
<li data-t="r3">They forward any suspicious message or number, and get a plain answer.</li>
<li data-t="r4">You set it up and stay in charge. They can always say stop.</li></ul>

<div class="card" id="join"><div id="formwrap"><h3 data-t="jh">Be the first to know when Robin opens.</h3>
<p class="fine" data-t="jf">No payment. We will message you once, on WhatsApp.</p>
<form id="f" autocomplete="on" novalidate>
<label for="name" data-t="ln">Your name</label><input id="name" name="name" type="text" maxlength="40" autocomplete="given-name" required>
<label for="phone" data-t="lp">Your WhatsApp number</label><input id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="98765 43210  /  +1 415 555 0100" required>
<div class="hp"><label for="website">Website</label><input id="website" name="website" type="text" tabindex="-1" autocomplete="off"></div>
<div class="err" id="err" role="alert"></div>
<button class="go" id="go" type="submit" data-t="btn">Join the waitlist</button>
<p class="fine" style="margin-top:12px" data-t="cons">By joining you agree that Robin may message you on WhatsApp about the launch. Your details are used only for this and deleted on request.</p>
<p class="fine"><a href="privacy" data-t="priv">How we use your details</a></p></form></div>
<div class="ok" id="ok"><h3 data-t="ok1">You are on the list. Thank you.</h3>
<p data-t="ok2">While you wait, call your parents tonight and ask one thing: "Has anyone ever called asking for money, an OTP or to install an app?"</p>
<p data-t="ok3">And tell them this: no officer ever "arrests" anyone over a phone or video call. If it happens, hang up and call you.</p>
<a class="share" id="share" href="#" data-t="share">Send this to a sibling on WhatsApp</a></div></div>

<p class="honest" data-t="honest">Robin is not live yet, and it is not an emergency service. In an emergency call 112.</p>
<footer data-t="foot">Robin is an AI assistant. It does not replace you, a doctor or the police.</footer>
</div>
<div class="sticky" id="sticky"><a href="#join" data-t="stk">Join the waitlist</a></div>
<script>
const T={en:{},hi:{
t1:"Dopahar ke 4:10, ek mangalwar",h1:"Aapki maa ghar par akeli hain. Unka phone bajta hai.",
s1:"Aadmi kehta hai wo police se hai. Kehta hai unka beta musibat mein hai. Kehta hai: kisi ko mat batana, phone mat kaatna.",
s2:"Wo 68 saal ki hain. Unke haath kaanp rahe hain. Wo aapko office mein pareshan nahi karna chahtin, isliye wo wahi karti hain jo wo kehta hai.",
nh:"Ye kahani humne nahi banayi",n1:"Chandigarh mein 82 saal ki ek mahila ne \"digital arrest\" fraud mein Rs 2.5 crore ganwa diye.",n2:"Mumbai mein ek senior citizen ne \"KYC\" wale caller ke kehne par app install kiya aur Rs 3.95 lakh ganwa diye.",n3:"Indore mein ek pensioner couple ne apne bank ka naam dikhane wali call par lagbhag Rs 6 lakh ganwa diye.",nf:"Upar likhe publishers ki reports. Original padhne ke liye card dabaiye.",
l1:"Aur jin dino koi scam nahi karta, tab bhi ghar sunsaan rehta hai, aur behtar nahi hota.",l2:"Wo akeli khana khati hain. Shaam ki goli bhool jati hain. Aap call karte hain to kehti hain \"main theek hoon, beta\", kyunki wo nahi chahtin aap chinta karein.",l3:"Aap 800 km door hain, ya kisi aur desh mein, aisi meeting mein jisse nikal nahi sakte. Aur agar raat 3 baje wo gir jayein, to sabse pehle kise pata chalega?",
q1:"Aap har din wahan nahi ho sakte. Robin ho sakta hai.",
r1:"Robin roz aapke parents ka haal poochta hai, unki apni bhasha mein. Dawai yaad dilata hai. Kuch galat lage, koi ajeeb call, koi payment jo nahi honi chahiye, to aapko waqt par khabar milti hai taaki aap unhe call kar sakein.",
r2:"Wo Robin se WhatsApp par baat karte hain, typing mushkil ho to voice note se.",r3:"Koi bhi shak wala message ya number Robin ko forward karein aur saaf jawab payein.",r4:"Setup aap karte hain aur control aapke paas rehta hai. Wo kabhi bhi \"stop\" keh sakte hain.",
jh:"Robin khulte hi sabse pehle khabar paiye.",jf:"Koi payment nahi. Hum aapko WhatsApp par sirf ek message karenge.",ln:"Aapka naam",lp:"Aapka WhatsApp number",btn:"Waitlist mein judiye",
cons:"Judne par aap maante hain ki Robin launch ke baare mein aapko WhatsApp par message kar sakta hai. Aapki details sirf isi ke liye use hongi aur kehne par delete ho jayengi.",priv:"Hum aapki details kaise use karte hain",
ok1:"Aap list mein hain. Shukriya.",ok2:"Intezaar ke dauran aaj raat apne parents ko call kijiye aur ek baat poochiye: \"Kya kisi ne kabhi paise, OTP ya koi app install karne ke liye call kiya?\"",ok3:"Aur unhe batayiye: koi officer phone ya video call par kisi ko \"arrest\" nahi karta. Aisa ho to phone kaat dein aur aapko call karein.",share:"Kisi bhai-behen ko WhatsApp par bhejiye",
honest:"Robin abhi live nahi hai, aur ye emergency service nahi hai. Emergency mein 112 par call karein.",foot:"Robin ek AI assistant hai. Ye aapki, doctor ki ya police ki jagah nahi leta.",stk:"Waitlist mein judiye"}};
const EN={};document.querySelectorAll("[data-t]").forEach(e=>{EN[e.dataset.t]=e.textContent});T.en=EN;
let cur="en";function setLang(l){cur=l;document.documentElement.lang=l==="hi"?"hi-Latn":"en";document.querySelectorAll("[data-t]").forEach(e=>{const v=T[l][e.dataset.t];if(v)e.textContent=v});document.getElementById("lang").textContent=l==="hi"?"English":"हिंदी / Hinglish"}
document.getElementById("lang").onclick=()=>setLang(cur==="en"?"hi":"en");
const src=new URLSearchParams(location.search).get("src")||"";
const errs={en:{name:"Please enter your name.",phone:"Please enter a valid WhatsApp number.",busy:"Something went wrong. Please try again in a minute."},hi:{name:"Apna naam likhiye.",phone:"Sahi WhatsApp number likhiye.",busy:"Kuch gadbad hui. Ek minute baad dobara try karein."}};
const io=new IntersectionObserver(es=>{document.getElementById("sticky").style.visibility=es[0].isIntersecting?"hidden":"visible"});io.observe(document.getElementById("join"));
document.getElementById("f").addEventListener("submit",async ev=>{ev.preventDefault();const err=document.getElementById("err");err.textContent="";
const g=id=>document.getElementById(id).value.trim();const body={name:g("name"),phone:g("phone"),website:g("website"),src:src,consent:true};const E=errs[cur];
if(!body.name){err.textContent=E.name;return}if(body.phone.replace(/\D/g,"").length<8){err.textContent=E.phone;return}
const b=document.getElementById("go");b.disabled=true;
try{const r=await fetch("join",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});if(!r.ok){const j=await r.json().catch(()=>({}));err.textContent=(E[j.field]||E.busy);b.disabled=false;return}
document.getElementById("formwrap").style.display="none";document.getElementById("ok").style.display="block";document.getElementById("sticky").style.display="none";
const msg=cur==="hi"?"Robin: un parents ke liye jinhe aap har ghante call nahi kar sakte. Waitlist mein judiye: ":"Robin: for the parents you cannot call every hour. Join the waitlist: ";
document.getElementById("share").href="https://wa.me/?text="+encodeURIComponent(msg+location.origin+location.pathname+"?src=share");document.getElementById("join").scrollIntoView()}catch(e){err.textContent=E.busy;b.disabled=false}});
</script></body></html>
"""

PRIVACY = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>Robin waitlist: how we use your details</title>
<style>body{font:17px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;max-width:640px;margin:0 auto;padding:20px 16px 48px;background:#fbf7f1;color:#1d1b18}@media (prefers-color-scheme:dark){body{background:#14110e;color:#f3eee6}}h1{font-size:26px}a{color:inherit}</style></head><body>
<h1>How we use your details</h1>
<p><strong>What we ask for:</strong> your name and WhatsApp number. We also count page visits per day and per link, without saving your address or device.</p>
<p><strong>Why:</strong> only to message you on WhatsApp about the Robin waitlist and launch. We do not sell your details and do not share them for advertising.</p>
<p><strong>Where it is kept:</strong> on our own server, in a protected file. Only the Robin team can read it.</p>
<p><strong>How long:</strong> until Robin has launched and you have been invited, plus 90 days, or until you ask us to delete it.</p>
<p><strong>Delete or change it:</strong> {CONTACT}</p>
<p><strong>Not an emergency service:</strong> Robin is not live yet. In an emergency call 112.</p>
<p><a href=".">Back to the waitlist</a></p></body></html>
"""
