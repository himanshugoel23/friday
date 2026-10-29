# ruff: noqa: E501
"""Chat lines of the step runner. ALL PENDING founder approval (en / hinglish); chat text only, no spoken line is touched.
Tests check structure (placeholders, no secret echoed), never the exact words."""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True

LINES: dict[str, dict[str, str]] = {
    "step": {"en": "Step {n} of {total}: {title}", "hinglish": "Step {n}/{total}: {title}"},
    # --- titles (the part after 'Step n of m:')
    "t_open_site": {"en": "opening {host}", "hinglish": "{host} khol rahi hoon"},
    "t_need_area": {"en": "I need your area for the price. Home or PG? (or send an area or pincode)", "hinglish": "Price ke liye aapka area chahiye. Home ya PG? (ya area / pincode bhej dijiye)"},
    "t_need_area_saved": {"en": "which place should I use: {saved}? (or send another area or pincode)", "hinglish": "Kaun si jagah lun: {saved}? (ya doosra area / pincode bhej dijiye)"},
    "t_need_area_again": {"en": "{site} did not accept \"{area}\". Please send a pincode or a nearby area.", "hinglish": "{site} ne \"{area}\" accept nahi kiya. Pincode ya paas ka area bhej dijiye."},
    "t_need_area_retry": {"en": "I could not read an area from that. Send an area name or a 6-digit pincode, or say Home / PG.", "hinglish": "Isse area samajh nahi aaya. Area ka naam ya 6 digit pincode bhejiye, ya Home / PG likhiye."},
    "t_need_login": {"en": "{site} needs a login. It will send an OTP to your number ending {tail}. Send it here and I will enter it. (Use it only for {site}; I use it once and do not keep it.)",
                     "hinglish": "{site} par login chahiye. Woh aapke number ending {tail} par OTP bhejega. Yahin bhej dijiye, main daal dungi. (Sirf {site} ke liye; ek baar use karti hoon, rakhti nahi.)"},
    "t_need_info": {"en": "{question}", "hinglish": "{question}"},
    "t_search": {"en": "searching for {query}", "hinglish": "{query} dhoondh rahi hoon"},
    "t_read_results": {"en": "reading the prices", "hinglish": "daam padh rahi hoon"},
    "t_navigate": {"en": "opening the right section", "hinglish": "sahi section khol rahi hoon"},
    "t_fill_preview": {"en": "filling the form (I will not send it)", "hinglish": "form bhar rahi hoon (bhejungi nahi)"},
    "t_act_confirmed": {"en": "the final action (only after your yes)", "hinglish": "aakhri kaam (aapke yes ke baad hi)"},
    "t_read_status": {"en": "reading the status", "hinglish": "status padh rahi hoon"},
    "t_compare_and_suggest": {"en": "checking other popular brands to recommend one", "hinglish": "doosre popular brands dekh rahi hoon, ek recommend karungi"},
    # --- login
    "otp_wait": {"en": "I am waiting for the OTP. Send it here when it arrives.", "hinglish": "OTP ka intezaar hai. Aate hi yahin bhej dijiye."},
    "otp_taken": {"en": "Got it, entering it now.", "hinglish": "Mil gaya, abhi daal rahi hoon."},
    "otp_wrong": {"en": "That code did not work. Send the newest OTP from {site}.", "hinglish": "Woh code chala nahi. {site} ka sabse naya OTP bhejiye."},
    "otp_resend": {"en": "The OTP has not arrived yet. Should I ask {site} to send it again? Reply YES or NO.", "hinglish": "OTP abhi tak nahi aaya. {site} se dobara bhejne ko kahun? YES ya NO likhiye."},
    "otp_unavailable": {"en": "I cannot take a login code safely here. Please log in on {site} yourself and ask me again.", "hinglish": "Yahan main login code surakshit tareeke se nahi le sakti. {site} par khud login kijiye aur phir mujhe bataiye."},
    "otp_secret": {"en": "Please send only the login code for {site}. Never send bank, card or UPI details.", "hinglish": "Sirf {site} ka login code bhejiye. Bank, card ya UPI ki details kabhi mat bhejiye."},
    # --- stop
    "stop": {"en": "I stopped at step {n} ({title}): {why}", "hinglish": "Step {n} ({title}) par ruk gayi: {why}"},
    "why_blocked": {"en": "the site is blocking automatic browsing, and I do not get around checks.", "hinglish": "site automatic browsing rok rahi hai, aur main checks bypass nahi karti."},
    "why_payment": {"en": "this needs a payment, and I never pay. You pay yourself in your own app.", "hinglish": "yahan payment chahiye, aur main kabhi pay nahi karti. Aap apne app mein khud pay kijiye."},
    "why_failed": {"en": "the page did not look the way I expected (the layout may have changed).", "hinglish": "page waisa nahi dikha jaisa socha tha (layout badal gaya ho sakta hai)."},
    "why_no_price": {"en": "I could not see a price on the page.", "hinglish": "Page par daam dikhai nahi diya."},
    "why_login": {"en": "the site wants a login that I could not complete.", "hinglish": "site login maang rahi hai jo main poora nahi kar payi."},
    "why_otp_late": {"en": "the OTP never arrived.", "hinglish": "OTP aaya hi nahi."},
    "why_other": {"en": "{reason}", "hinglish": "{reason}"},
    "offer_web": {"en": "Want me to compare public web prices for {item} instead? Reply YES or NO.", "hinglish": "Iske badle {item} ke public web prices compare kar dun? YES ya NO likhiye."},
    "offer_manual": {"en": "To do it yourself, open {where}.", "hinglish": "Khud karne ke liye {where} kholiye."},
    "nothing_changed": {"en": "Nothing was submitted or changed.", "hinglish": "Kuch submit ya change nahi hua."},
    "cancelled": {"en": "Okay, stopped. Nothing was submitted.", "hinglish": "Theek hai, ruk gayi. Kuch submit nahi hua."},
    "expired": {"en": "I did not hear back, so I stopped. Nothing was submitted. Ask me again whenever you like.", "hinglish": "Jawab nahi aaya, isliye ruk gayi. Kuch submit nahi hua. Jab chahein dobara bol dijiye."},
    "busy": {"en": "My browser is busy right now. I saved your task and will continue shortly.", "hinglish": "Mera browser abhi busy hai. Aapka kaam save hai, thodi der mein aage badhaungi."},
    "already": {"en": "I am already working on a step-by-step task for you. Say 'stop' to cancel it first.", "hinglish": "Main aapke ek step-by-step kaam par pehle se lagi hoon. Pehle 'stop' likh kar use rokiye."},
    "working": {"en": "I am still on it, one step at a time.", "hinglish": "Abhi bhi lagi hoon, ek ek step karke."},
    "yes_no": {"en": "Please reply YES or NO.", "hinglish": "Kripya YES ya NO likhiye."},
    "secret": {"en": "Please do not send passwords, card numbers or PINs here. I did not save that.", "hinglish": "Password, card number ya PIN yahan mat bhejiye. Maine yeh save nahi kiya."},
    # --- report
    "r_head": {"en": "{item} on {store}{where}:", "hinglish": "{store} par {item}{where}:"},
    "r_area": {"en": " ({area})", "hinglish": " ({area})"},
    "r_variant_missing": {"en": "I could not see {variant} there. These are the main ones:", "hinglish": "{variant} wahan nahi dikha. Mukhya variants yeh hain:"},
    "r_variant": {"en": "Your variant ({variant}):", "hinglish": "Aapka variant ({variant}):"},
    "r_main": {"en": "Main variants:", "hinglish": "Mukhya variants:"},
    "r_others": {"en": "Other popular {cat} brands:", "hinglish": "Doosre popular {cat} brands:"},
    "r_pick": {"en": "My pick: {name}, {reason}.", "hinglish": "Meri pasand: {name}, {reason}."},
    "r_no_pick": {"en": "I could not pick one with confidence from the prices I saw.", "hinglish": "Jo daam dikhe unse ek pakka pick nahi kar payi."},
    "r_proof": {"en": "Proof: {n} screenshot(s) saved; the page said: \"{snippet}\"", "hinglish": "Proof: {n} screenshot save hue; page par likha tha: \"{snippet}\""},
    "r_proof_text": {"en": "Proof: the page said \"{snippet}\"", "hinglish": "Proof: page par likha tha \"{snippet}\""},
    "r_done": {"en": "Done on {store}. {result}", "hinglish": "{store} par ho gaya. {result}"},
    "r_unsure": {"en": "Prices change often: this is what the page showed just now.", "hinglish": "Daam badalte rehte hain: yeh abhi page par dikha tha."},
}


def line(key: str, lang: str, **kw: object) -> str:
    row = LINES[key]
    text = row.get(lang) or row.get("hinglish") or row["en"]
    return text.format(**kw) if kw else text
