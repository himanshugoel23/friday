# ruff: noqa: E501
"""Chat wording of the shopping assistant (CHAT TEXT ONLY). Every line is listed in
docs/SHOPPING_ASSISTANT.md as PENDING the founder's approval. Rules: short, personal, proactive; one
question per message; never 'before I call'; never asks for a pincode while a saved place exists."""

from __future__ import annotations

LINES: dict[str, dict[str, str]] = {
    "pick": {
        "en": "Here are the {n} popular {cat} choices. I would take {name}: {reason}.",
        "hinglish": "Yeh rahe {n} popular {cat} options. Main {name} loongi: {reason}.",
    },
    "pick_none": {
        "en": "Here are the popular {cat} choices I found. I could not see enough prices to pick one yet.",
        "hinglish": "Yeh rahe popular {cat} options. Daam poore nahi dikhe, isliye abhi ek pick nahi kar paayi.",
    },
    "row": {"en": "{i}. {name}{store}: {price}{per}{rating}", "hinglish": "{i}. {name}{store}: {price}{per}{rating}"},
    "price_hidden": {"en": "price not visible", "hinglish": "daam nahi dikha"},
    "fresh": {
        "en": "Prices as of {time} IST from public pages. They may differ in the app.",
        "hinglish": "{time} IST ke daam, public pages se. App mein alag ho sakte hain.",
    },
    "store_hidden": {
        "en": "{store} does not show its own prices online, so these are other sellers' prices.",
        "hinglish": "{store} apne daam online nahi dikhata, isliye yeh doosre sellers ke daam hain.",
    },
    "sources": {"en": "Sources:", "hinglish": "Sources:"},
    "card_caption": {"en": "{name}\n{line}", "hinglish": "{name}\n{line}"},
    # --- the one delivery-place question
    "place_ask_saved": {
        "en": "Home or PG? I will check delivery and price for that place.",
        "hinglish": "Ghar ya PG? Us jagah ke liye delivery aur daam dekh leti hoon.",
    },
    "place_ask_new": {
        "en": "Ghar ya PG? Share the area or pincode once and I will remember it.",
        "hinglish": "Ghar ya PG? Area ya pincode ek baar bata dein, main yaad rakhungi.",
    },
    "place_saved": {
        "en": "Saved your {label} ({where}). It shows under 'what do you remember'.",
        "hinglish": "Aapka {label} ({where}) yaad kar liya. 'what do you remember' mein dikhega.",
    },
    "place_checking": {
        "en": "Checking again for {label} ({where}).",
        "hinglish": "{label} ({where}) ke liye dobara dekh rahi hoon.",
    },
    "place_no_area": {
        "en": "I could not read an area from that. Send the area name or a 6 digit pincode.",
        "hinglish": "Isse area samajh nahi aaya. Area ka naam ya 6 digit pincode bhej dein.",
    },
    "refined_same": {
        "en": "Same pick for {label}: {name}.",
        "hinglish": "{label} ke liye bhi wahi pick: {name}.",
    },
    "refined_new": {
        "en": "For {label} I would now take {name}: {reason}.",
        "hinglish": "{label} ke liye ab main {name} loongi: {reason}.",
    },
    # --- soft failures (proactive, never 'result not found' plus a demand for details)
    "soft_fail": {
        "en": "I could not read live prices just now. The popular {cat} picks are {names}. Want me to try again in a minute?",
        "hinglish": "Abhi live daam nahi padh paayi. Popular {cat} yeh hain: {names}. Ek minute baad dobara try karun?",
    },
    "soft_fail_down": {
        "en": "I can't look up prices right now. The popular {cat} picks are {names}.",
        "hinglish": "Abhi daam check nahi kar sakti. Popular {cat} yeh hain: {names}.",
    },
    "progress": {
        "en": "Checking {sites} for {cat}... one moment.",
        "hinglish": "{sites} par {cat} check kar rahi hoon... bas ek minute.",
    },
    "sites_read": {
        "en": "I could read prices on {ok} of {n} sites.",
        "hinglish": "{n} mein se {ok} sites par daam dikhe.",
    },
    "sites_unread": {
        "en": "Could not read: {names} (price not visible online).",
        "hinglish": "Yahan nahi padh paayi: {names} (daam online nahi dikhe).",
    },
    "also": {"en": "also", "hinglish": "aur"},
    "refine_fail": {
        "en": "I could not refresh the prices for that place just now, so the comparison above stands.",
        "hinglish": "Us jagah ke liye abhi daam refresh nahi ho paaye, upar wali comparison hi sahi maanein.",
    },
    "compare_no": {
        "en": "Okay, I will stay with {store}. Say 'compare' any time and I will check the others too.",
        "hinglish": "Theek hai, {store} par hi rehte hain. 'compare' likhiye to baaki par bhi dekh lungi.",
    },
    "btn_cmp_yes": {"en": "Compare", "hinglish": "Compare karo"},
    "btn_cmp_no": {"en": "No thanks", "hinglish": "Nahi, theek hai"},
    "btn_home": {"en": "Home", "hinglish": "Ghar"},
    "btn_pg": {"en": "PG", "hinglish": "PG"},
    "btn_office": {"en": "Office", "hinglish": "Office"},
    "label_home": {"en": "home", "hinglish": "ghar"},
    "label_pg": {"en": "PG", "hinglish": "PG"},
    "label_office": {"en": "office", "hinglish": "office"},
}  # fmt: skip


def line(key: str, lang: str | None = "hinglish", **kw: str) -> str:
    row = LINES[key]
    text = row["en"] if lang == "en" else row["hinglish"]
    return text.format(**kw) if kw else text
