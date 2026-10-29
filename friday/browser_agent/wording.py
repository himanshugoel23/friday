# ruff: noqa: E501
"""Chat lines of the browser agent. ALL PENDING founder approval (en / hinglish); listed in docs/BROWSER_AGENT_DESIGN.md.
Chat text only: no spoken (voice) line is touched."""

from __future__ import annotations

LINES: dict[str, dict[str, str]] = {
    "ack": {
        "en": "On it. I'll work on {host} and ask you only if I need something.",
        "hinglish": "Kar rahi hoon. {host} par kaam karti hoon, kuch chahiye hoga toh aapse poochhungi.",
    },
    "ask_head": {
        "en": "To go on with this I need a few details ({host}):",
        "hinglish": "Aage badhne ke liye kuch details chahiye ({host}):",
    },
    "ask_foot": {
        "en": "Reply with the answers, one per line. Write 'ok' to accept my suggestions where I gave one.",
        "hinglish": "Jawab ek line mein ek likhiye. Jahan maine suggestion di hai wahan 'ok' likh dein toh wahi le lungi.",
    },
    "ask_suggest": {"en": "(suggested: {value})", "hinglish": "(suggestion: {value})"},
    "ask_options": {"en": "(choose: {value})", "hinglish": "(chuniye: {value})"},
    "attest_head": {
        "en": "The site asks you to confirm this. Only you can answer. Reply YES or NO for each:",
        "hinglish": "Site aapse yeh confirm karwa rahi hai. Sirf aap jawab de sakte hain. Har ek ke liye YES ya NO likhiye:",
    },
    "confirm": {
        "en": "I'm at the last step on {host}:\n{summary}\nThis cannot be undone. Reply YES to go ahead, or NO to stop.",
        "hinglish": "{host} par aakhri step par hoon:\n{summary}\nYeh wapas nahi ho sakta. Aage badhna hai toh YES likhiye, rokna hai toh NO.",
    },
    "confirm_again": {
        "en": "I need a clear YES or NO for this step: {summary}",
        "hinglish": "Is step ke liye saaf YES ya NO chahiye: {summary}",
    },
    "login": {
        "en": "{host} needs you to be logged in. Save your login on this secure page (never type a password in chat): {link}\nThen reply 'done'.",
        "hinglish": "{host} par login chahiye. Apna login is secure page par save kijiye (password chat mein kabhi na likhein): {link}\nPhir 'done' likhiye.",
    },
    "otp": {
        "en": "{host} sent you a code. Enter it on this secure page: {link}\nThen reply 'done'.",
        "hinglish": "{host} ne aapko code bheja hai. Is secure page par daaliye: {link}\nPhir 'done' likhiye.",
    },
    "allow_domain": {
        "en": "This continues on {host}. Is it okay for me to open it for this task? Reply YES or NO.",
        "hinglish": "Yeh aage {host} par jaata hai. Is kaam ke liye kholun? YES ya NO likhiye.",
    },
    "allow_account": {
        "en": "To continue, {host} wants a new account. Should I create one for you there? Reply YES or NO. (I never create government or ID accounts.)",
        "hinglish": "Aage badhne ke liye {host} par naya account banana padega. Kya main banaun? YES ya NO likhiye. (Sarkari ya ID account main kabhi nahi banati.)",
    },
    "secret_refused": {
        "en": "Please do not send passwords, card numbers, PINs or one-time codes here. I did not save that. Passwords go on the secure page I send; codes too.",
        "hinglish": "Password, card number, PIN ya OTP yahan mat bhejiye. Maine yeh save nahi kiya. Password aur code sirf mere bheje secure page par daalein.",
    },
    "not_understood": {
        "en": "I could not match that to my questions. Please answer the missing ones: {labels}",
        "hinglish": "Yeh mere sawaalon se match nahi hua. Baaki ke jawab dijiye: {labels}",
    },
    "done": {"en": "Done: {result}", "hinglish": "Ho gaya: {result}"},
    "proof": {"en": "Proof saved ({what}, {where}, {when}).", "hinglish": "Proof save kiya ({what}, {where}, {when})."},
    "blocked": {
        "en": "{host} is blocking automatic browsing ({reason}). I stopped and I do not bypass checks or captchas.\n{manual}",
        "hinglish": "{host} automatic browsing rok raha hai ({reason}). Maine ruk kar kaam band kiya; check ya captcha main bypass nahi karti.\n{manual}",
    },
    "payment": {
        "en": "I stopped at the payment step. I never pay or enter card, UPI or bank details; you pay yourself.{link}",
        "hinglish": "Payment ke step par ruk gayi. Main kabhi pay nahi karti aur card, UPI ya bank details nahi daalti; aap khud pay kijiye.{link}",
    },
    "payment_link": {"en": "\nPayment page (open it yourself): {url}", "hinglish": "\nPayment page (aap khud kholiye): {url}"},
    "budget": {
        "en": "I ran out of {what} for this task, so I stopped. Nothing was submitted.\n{manual}",
        "hinglish": "Is kaam ke liye {what} khatam ho gaya, isliye ruk gayi. Kuch submit nahi hua.\n{manual}",
    },
    "gave_up": {
        "en": "I could not finish this: {reason}\n{manual}",
        "hinglish": "Yeh poora nahi ho paya: {reason}\n{manual}",
    },
    "busy": {
        "en": "My browser is busy right now. I saved your task and will continue shortly.",
        "hinglish": "Mera browser abhi busy hai. Aapka kaam save hai, thodi der mein aage badhaungi.",
    },
    "expired": {
        "en": "I did not hear back, so I stopped. Nothing was submitted. Ask me again whenever you like.",
        "hinglish": "Jawab nahi aaya, isliye ruk gayi. Kuch submit nahi hua. Jab chahein dobara bol dijiye.",
    },
    "cancelled": {"en": "Okay, stopped. Nothing was submitted.", "hinglish": "Theek hai, ruk gayi. Kuch submit nahi hua."},
    "declined": {"en": "Okay, I stopped here.", "hinglish": "Theek hai, yahin ruk gayi."},
    "already_running": {
        "en": "I'm already working on a website task for you. Say 'stop' to cancel it first.",
        "hinglish": "Main aapke ek website kaam par pehle se lagi hoon. Pehle 'stop' likh kar usse rokiye.",
    },
    "no_site": {
        "en": "Which website should I use? Send me its address (for example example.com).",
        "hinglish": "Kaun si website par karna hai? Uska address bhejiye (jaise example.com).",
    },
    "error": {
        "en": "Something went wrong and I stopped safely. Nothing was submitted.\n{manual}",
        "hinglish": "Kuch gadbad hui, main surakshit tareeke se ruk gayi. Kuch submit nahi hua.\n{manual}",
    },
    "manual_open": {"en": "To do it yourself, open {where}.", "hinglish": "Khud karne ke liye {where} kholiye."},
    "manual_fields": {"en": " Fields I would have filled: {fields}.", "hinglish": " Jo fields main bharti: {fields}."},
    "manual_left": {"en": " Please fill yourself: {fields}.", "hinglish": " Yeh aap khud bharein: {fields}."},
}


def line(key: str, lang: str, **kw: object) -> str:
    row = LINES[key]
    text = row.get(lang) or row.get("hinglish") or row["en"]
    return text.format(**kw) if kw else text
