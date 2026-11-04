# ruff: noqa: E501
"""The public page (English + Roman Hinglish toggle). Copy is PENDING founder approval (docs/ROBIN_WAITLIST.md)."""

from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><title>Robin: a calm helper for your parents' safety</title>
<meta name="description" content="Daily check-ins, medicine reminders and scam alerts for the parents you cannot be with every day. Join the Robin waitlist.">
<style>
:root{--bg:#fbf8f3;--ink:#1c1b19;--mut:#5f5a52;--card:#fff;--line:#e6dfd3;--acc:#1f6f5c;--accink:#fff;--warn:#8a4b00}
@media (prefers-color-scheme:dark){:root{--bg:#14110e;--ink:#f3eee6;--mut:#b4ab9d;--card:#1d1915;--line:#332c24;--acc:#49b79a;--accink:#08201a;--warn:#e0a85b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:640px;margin:0 auto;padding:20px 16px 56px}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}
.brand{font-weight:700;font-size:22px;letter-spacing:.2px}.tag{font-size:13px;background:var(--card);border:1px solid var(--line);border-radius:999px;padding:4px 10px;color:var(--mut)}
button.lang{background:none;border:1px solid var(--line);border-radius:999px;color:var(--ink);padding:6px 12px;font-size:14px;cursor:pointer}
h1{font-size:32px;line-height:1.15;margin:0 0 12px}p.lead{font-size:19px;color:var(--mut);margin:0 0 20px}
ul.pts{padding-left:0;list-style:none;margin:0 0 24px}ul.pts li{padding:10px 0 10px 28px;position:relative;border-bottom:1px solid var(--line)}
ul.pts li:before{content:"";position:absolute;left:4px;top:18px;width:10px;height:10px;border-radius:50%;background:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px}
label{display:block;font-weight:600;margin:14px 0 6px;font-size:15px}
input[type=text],input[type=tel],select{width:100%;padding:13px 12px;font-size:17px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}
.chk{display:flex;gap:10px;align-items:flex-start;font-weight:400;margin:8px 0}.chk input{margin-top:5px;width:20px;height:20px}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chips label{margin:0;font-weight:400;border:1px solid var(--line);border-radius:999px;padding:8px 12px;cursor:pointer;display:flex;gap:8px;align-items:center}
.chips input{width:18px;height:18px}
button.go{margin-top:18px;width:100%;padding:15px;font-size:18px;font-weight:700;border:0;border-radius:12px;background:var(--acc);color:var(--accink);cursor:pointer}
button.go[disabled]{opacity:.6}.fine{font-size:14px;color:var(--mut);margin-top:12px}.err{color:#b3261e;font-size:15px;margin-top:10px;min-height:20px}
.honest{margin-top:22px;font-size:14px;color:var(--warn);border-left:3px solid var(--warn);padding-left:12px}
.hp{position:absolute;left:-9999px;height:0;overflow:hidden}.ok{display:none;text-align:center}.ok h2{margin:6px 0}
a.share{display:inline-block;margin-top:12px;padding:12px 18px;border-radius:12px;background:var(--acc);color:var(--accink);text-decoration:none;font-weight:700}
footer{margin-top:28px;font-size:13px;color:var(--mut)}footer a{color:var(--mut)}
</style></head><body><div class="wrap">
<div class="top"><div><span class="brand">Robin</span> <span class="tag" data-t="tag">Launching soon</span></div><button class="lang" id="lang" type="button">हिंदी / Hinglish</button></div>
<h1 data-t="h1">A calm helper for your parents' safety.</h1>
<p class="lead" data-t="lead">Robin checks in on your parents every day, reminds them about medicines, and warns you when something looks wrong. You set it up and stay in charge. They talk to Robin on WhatsApp.</p>
<ul class="pts">
<li data-t="p1">A friendly daily check-in, in their language.</li>
<li data-t="p2">Medicine reminders, and a heads-up to you when a refill is due.</li>
<li data-t="p3">Scam help: they forward a message or call details to Robin and get a plain answer.</li>
<li data-t="p4">An alert to you when something looks risky, so you can call them in time.</li>
</ul>
<div class="card" id="formcard"><strong data-t="join">Join the waitlist</strong>
<p class="fine" data-t="sub">Robin is about to launch. We will message you on WhatsApp when your spot opens. No payment now.</p>
<form id="f" autocomplete="on" novalidate>
<label for="name" data-t="l_name">Your first name</label><input id="name" name="name" type="text" maxlength="40" autocomplete="given-name" required>
<label for="phone" data-t="l_phone">Your WhatsApp number (with country code if outside India)</label><input id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="98765 43210  or  +1 415 555 0100" required>
<label for="whom" data-t="l_whom">Who is it for?</label><select id="whom" name="whom"><option value="mother" data-t="o_mother">My mother</option><option value="father" data-t="o_father">My father</option><option value="both" data-t="o_both">Both parents</option><option value="other" data-t="o_other">Someone else</option></select>
<label for="city" data-t="l_city">Where do they live? (city)</label><input id="city" name="city" type="text" maxlength="60" autocomplete="off" required>
<label for="lang2" data-t="l_lang">Their main language</label><select id="lang2" name="lang"><option value="hindi">Hindi</option><option value="english">English</option><option value="punjabi">Punjabi</option><option value="marathi">Marathi</option><option value="gujarati">Gujarati</option><option value="bengali">Bengali</option><option value="tamil">Tamil</option><option value="telugu">Telugu</option><option value="kannada">Kannada</option><option value="other">Other</option></select>
<label data-t="l_worry">What worries you most? (optional)</label>
<div class="chips" id="worries">
<label><input type="checkbox" value="scam_calls"><span data-t="w1">Scam calls</span></label>
<label><input type="checkbox" value="medicines"><span data-t="w2">Medicines</span></label>
<label><input type="checkbox" value="living_alone"><span data-t="w3">Living alone</span></label>
<label><input type="checkbox" value="emergencies"><span data-t="w4">Emergencies</span></label>
<label><input type="checkbox" value="loneliness"><span data-t="w5">Loneliness</span></label>
<label><input type="checkbox" value="bills"><span data-t="w6">Bills and paperwork</span></label></div>
<div class="hp"><label for="website">Website</label><input id="website" name="website" type="text" tabindex="-1" autocomplete="off"></div>
<label class="chk"><input id="consent" type="checkbox"><span data-t="consent">I agree that Robin may message me on WhatsApp about the waitlist and the launch. My details are used only for this, and I can ask for them to be deleted at any time.</span></label>
<div class="err" id="err" role="alert"></div>
<button class="go" id="go" type="submit" data-t="btn">Join the waitlist</button>
<p class="fine"><a href="privacy" data-t="priv">How we use your details</a></p>
</form></div>
<div class="card ok" id="ok"><h2 data-t="ok1">You are on the list.</h2><p data-t="ok2">We will message you on WhatsApp when your spot opens. If a sibling helps with your parents, send them this page too.</p>
<a class="share" id="share" href="#" data-t="share">Share on WhatsApp</a></div>
<p class="honest" data-t="honest">Robin is not live yet, and it is not an emergency service. In an emergency call 112.</p>
<footer data-t="foot">Robin is an AI assistant. It does not replace you, a doctor or the police.</footer>
</div>
<script>
const T={en:{},hi:{
tag:"Jald aa raha hai",h1:"Aapke parents ki safety ke liye ek shaant saathi.",lead:"Robin roz aapke parents ka haal poochta hai, dawai yaad dilata hai, aur kuch galat lage to aapko bata deta hai. Setup aap karte hain aur control aapke paas rehta hai. Parents Robin se WhatsApp par baat karte hain.",
p1:"Roz ek dostana check-in, unki apni bhasha mein.",p2:"Dawai ke reminder, aur refill ka waqt aaye to aapko khabar.",p3:"Scam ki madad: wo koi message ya call ki detail Robin ko forward karein aur saaf jawab payein.",p4:"Kuch risky lage to aapko alert, taaki aap time par call kar sakein.",
join:"Waitlist mein judiye",sub:"Robin jald launch ho raha hai. Aapki jagah khulte hi hum WhatsApp par message karenge. Abhi koi payment nahi.",
l_name:"Aapka pehla naam",l_phone:"Aapka WhatsApp number (India ke bahar ho to country code ke saath)",l_whom:"Kiske liye?",o_mother:"Meri maa",o_father:"Mere papa",o_both:"Dono parents",o_other:"Koi aur",
l_city:"Wo kahan rehte hain? (sheher)",l_lang:"Unki mukhya bhasha",l_worry:"Sabse zyada chinta kis baat ki hai? (zaroori nahi)",w1:"Scam calls",w2:"Dawaiyan",w3:"Akele rehna",w4:"Emergency",w5:"Akelapan",w6:"Bills aur paperwork",
consent:"Main maanta/maanti hoon ki Robin mujhe waitlist aur launch ke baare mein WhatsApp par message kar sakta hai. Meri details sirf isi ke liye use hongi, aur main kabhi bhi unhe delete karwa sakta/sakti hoon.",
btn:"Waitlist mein judiye",priv:"Hum aapki details kaise use karte hain",ok1:"Aap list mein hain.",ok2:"Aapki jagah khulte hi hum WhatsApp par message karenge. Agar koi bhai-behen parents ka dhyan rakhta hai to unhe bhi ye page bhejiye.",share:"WhatsApp par share karein",
honest:"Robin abhi live nahi hai, aur ye emergency service nahi hai. Emergency mein 112 par call karein.",foot:"Robin ek AI assistant hai. Ye aapki, doctor ki ya police ki jagah nahi leta."}};
const EN={};document.querySelectorAll("[data-t]").forEach(e=>{EN[e.dataset.t]=e.textContent});T.en=EN;
let cur="en";function setLang(l){cur=l;document.documentElement.lang=l==="hi"?"hi-Latn":"en";document.querySelectorAll("[data-t]").forEach(e=>{const v=T[l][e.dataset.t];if(v)e.textContent=v});document.getElementById("lang").textContent=l==="hi"?"English":"हिंदी / Hinglish"}
document.getElementById("lang").onclick=()=>setLang(cur==="en"?"hi":"en");
const src=new URLSearchParams(location.search).get("src")||"";
const errs={en:{consent:"Please tick the box so we can message you.",name:"Please enter your first name.",phone:"Please enter a valid WhatsApp number.",city:"Please enter your parents' city.",busy:"Something went wrong. Please try again in a minute."},
hi:{consent:"Message bhejne ki ijazat ke liye box tick karein.",name:"Apna pehla naam likhiye.",phone:"Sahi WhatsApp number likhiye.",city:"Parents ka sheher likhiye.",busy:"Kuch gadbad hui. Ek minute baad dobara try karein."}};
document.getElementById("f").addEventListener("submit",async ev=>{ev.preventDefault();const err=document.getElementById("err");err.textContent="";
const g=id=>document.getElementById(id).value.trim();const body={name:g("name"),phone:g("phone"),whom:g("whom"),city:g("city"),lang:g("lang2"),website:g("website"),src:src,
worries:[...document.querySelectorAll("#worries input:checked")].map(x=>x.value),consent:document.getElementById("consent").checked};
const E=errs[cur];if(!body.name){err.textContent=E.name;return}if(body.phone.replace(/\D/g,"").length<8){err.textContent=E.phone;return}if(!body.city){err.textContent=E.city;return}if(!body.consent){err.textContent=E.consent;return}
const b=document.getElementById("go");b.disabled=true;
try{const r=await fetch("join",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});if(!r.ok){const j=await r.json().catch(()=>({}));err.textContent=(E[j.field]||E.busy);b.disabled=false;return}
document.getElementById("formcard").style.display="none";document.getElementById("ok").style.display="block";
const msg=cur==="hi"?"Robin: parents ki safety ke liye ek shaant saathi. Waitlist mein judiye: ":"Robin: a calm helper for your parents' safety. Join the waitlist: ";
document.getElementById("share").href="https://wa.me/?text="+encodeURIComponent(msg+location.origin+location.pathname+"?src=share");window.scrollTo(0,0)}catch(e){err.textContent=E.busy;b.disabled=false}});
</script></body></html>
"""

PRIVACY = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>Robin waitlist: how we use your details</title>
<style>body{font:17px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;max-width:640px;margin:0 auto;padding:20px 16px 48px;background:#fbf8f3;color:#1c1b19}@media (prefers-color-scheme:dark){body{background:#14110e;color:#f3eee6}}h1{font-size:26px}a{color:inherit}</style></head><body>
<h1>How we use your details</h1>
<p><strong>What we ask for:</strong> your first name, WhatsApp number, your parents' city and main language, who the service is for, and (optional) what worries you. We also count page visits per day and per link, without saving your address or device.</p>
<p><strong>Why:</strong> only to message you on WhatsApp about the Robin waitlist and launch, and to understand who needs Robin. We do not sell your details and do not share them for advertising.</p>
<p><strong>Where it is kept:</strong> on our own server, in a protected file. Only the Robin team can read it.</p>
<p><strong>How long:</strong> until Robin has launched and you have been invited, plus 90 days, or until you ask us to delete it.</p>
<p><strong>Delete or change it:</strong> {CONTACT}</p>
<p><strong>Not an emergency service:</strong> Robin is not live yet. In an emergency call 112.</p>
<p><a href=".">Back to the waitlist</a></p></body></html>
"""
