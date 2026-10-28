# ruff: noqa: E501
"""Chat lines of the query-understanding step and the agent team. ALL PENDING founder approval
(listed in docs/AGENT_TEAM_DESIGN.md). Text only: no spoken (voice) line is touched."""

from __future__ import annotations

LINES: dict[str, dict[str, str]] = {
    "confirm_fix": {
        "en": "Did you mean {candidate} (you wrote \"{heard}\")? Reply yes or no.",
        "hinglish": "Kya aapka matlab {candidate} hai (aapne \"{heard}\" likha)? Haan ya nahi bata dein.",
    },
    "ask_area": {
        "en": "Which area should I search in? Tell me the town or locality.",
        "hinglish": "Kis area mein dekhun? Shehar ya locality bata dein.",
    },
    "ask_dish": {
        "en": "What would you like to eat?",
        "hinglish": "Kya khana hai?",
    },
    "ack_team": {
        "en": "On it, checking {where} now. I'll send the options in a moment.",
        "hinglish": "{where} check kar rahi hoon. Options abhi bhejti hoon.",
    },
    "ack_team_big": {
        "en": "This has a few parts, so I'm splitting it up and checking each one. I'll send everything together.",
        "hinglish": "Isme kai hisse hain, isliye alag alag dekh rahi hoon. Sab ek saath bhejti hoon.",
    },
    "food_header": {"en": "Options on {site} (as of {time} IST):", "hinglish": "{site} par options ({time} IST ke hisaab se):"},
    "food_none": {
        "en": "I could not find reliable {site} options for that.",
        "hinglish": "{site} par iske liye pakke options nahi mile.",
    },
    "food_unverified": {
        "en": "Note: my notes on {site} are not verified yet, so check the details in the app.",
        "hinglish": "Dhyan dein: {site} ke baare mein meri jaankari abhi verify nahi hui, app mein details dekh lein.",
    },
    "price_unknown": {"en": "price not shown", "hinglish": "daam nahi dikha"},
    "over_cap": {"en": "{n} more were above Rs {cap}.", "hinglish": "{n} aur options Rs {cap} se upar the."},
    "food_footer": {
        "en": "I can't place orders or pay for you. Open a link and order in your own app.",
        "hinglish": "Order aur payment main nahi karti. Link kholkar apne app mein order kar lijiye.",
    },
    "part_failed": {"en": "I could not finish this part: {what}.", "hinglish": "Yeh hissa pura nahi ho paya: {what}."},
    "budget_stop": {
        "en": "I stopped early to keep this quick. Here is what I have.",
        "hinglish": "Jaldi dene ke liye yahin ruk gayi. Jo mila woh yeh hai.",
    },
    "rest_note": {"en": "I'll look at the rest ({what}) separately.", "hinglish": "Baaki ({what}) alag se dekhti hoon."},
    "all_failed": {
        "en": "I could not get a reliable answer for that right now. Please try again in a bit.",
        "hinglish": "Abhi iska pakka jawab nahi mil paya. Thodi der baad dobara try karein.",
    },
    "part_title": {"en": "Part {n}: {what}", "hinglish": "Hissa {n}: {what}"},
    "sources": {"en": "Source:", "hinglish": "Source:"},
}


def line(key: str, lang: str | None = "hinglish", **kw: object) -> str:
    row = LINES[key]
    text = row["en"] if lang == "en" else row["hinglish"]
    return text.format(**kw) if kw else text
