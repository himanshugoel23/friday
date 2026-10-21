# ruff: noqa: E501
"""Deterministic synthetic training data for the end-of-turn model. No model calls, no network.

Complete utterances come from hand-written Hinglish / Hindi / English templates per expected answer
type; INCOMPLETE ones are built the way real speakers get cut off: a finished core followed by a
connector or filler ("500 rupaye lekin", "haan ji umm"), a day-part with no hour ("kal shaam ko"),
a number with its unit still to come ("400 se", "500 ke liye"), a name or number announced but not
said, half a phone number, a noun phrase waiting for its postposition ("mere bhai ka").

Same seed -> same sentences in the same order. This is SYNTHETIC: it teaches the shapes, it is not
phone speech. The held-out hand-written list (``data/eot_examples.txt``, split=test) is never used
here: the templates were written before that list was scored and are not changed after its errors.

``uv run python -m friday.learning.eot_synth`` prints the counts and a sample.
"""

from __future__ import annotations

import random
import sys

Row = tuple[str, str, str]  # (text, label, answer_type)

NUMBERS = (100, 120, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800, 900,
           1000, 1200, 1500, 2000, 2500, 3000)
WORD_PRICES = ("chaar sau", "paanch sau", "dedh sau", "do sau", "teen sau", "saat sau", "dhai sau",
               "hazaar", "aath sau", "nau sau", "do hazaar", "teen hazaar")
SMALL_WORDS = ("do", "teen", "chaar", "paanch", "chhe", "saat", "aath", "nau", "das")
HOURS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
HOUR_WORDS = ("ek", "do", "teen", "chaar", "paanch", "chhe", "saat", "aath", "nau", "das")
DAYS = ("kal", "aaj", "parso", "tomorrow", "today", "monday", "friday", "somvar", "shanivar")
PARTS = ("subah", "shaam", "dopahar", "raat", "morning", "evening", "afternoon")
NAMES = ("Rohan", "Aman", "Priya", "Sunita", "Imran", "Neha", "Rakesh", "Anjali", "Deepak",
         "Pooja", "Vikram", "Kavita", "Salman", "Meena", "Karan", "Divya", "Farhan", "Geeta")
NOUNS = ("bhai", "dost", "manager", "stylist", "owner", "customer", "gaadi", "dukaan", "parcel",
         "order", "booking", "kaam", "samaan", "payment", "bill", "kamre", "room")
CONNECTORS = ("lekin", "aur", "toh", "matlab", "par", "magar", "kyunki", "ya", "ki", "umm", "hmm",
              "so", "but", "and", "because", "wo", "acha", "dekhiye", "actually", "agar")
POST = ("ka", "ke", "ki", "ko", "se", "mein", "ke liye", "jo")
PRE = ("", "", "haan ", "ji ", "haan ji ", "achha ", "dekhiye ", "sir ", "toh ")
SUF = ("", "", "", " ji", " sir", " madam")
DEV_COMPLETE = {
    "yesno": ("हाँ जी", "जी नहीं", "बिल्कुल", "ठीक है जी", "नहीं सर", "हाँ बिल्कुल", "जी हाँ"),
    "price": ("पाँच सौ रुपये", "तीन सौ लगेंगे", "सात सौ", "एक हज़ार रुपये", "छह सौ पचास", "आठ सौ रुपये हैं"),
    "time": ("शाम को छह बजे", "कल सुबह दस बजे", "आज शाम पाँच बजे", "दोपहर दो बजे", "परसों सुबह 9 बजे"),
    "name": ("मेरा नाम रोहन है", "मैं पूजा बोल रही हूँ", "मेरा नाम अमन है"),
    "": ("आप कल आ जाइए", "वो उपलब्ध है", "अभी स्टॉक नहीं है", "मैं बाद में फोन करता हूँ", "कोई बात नहीं",
         "आप शाम को आइए", "यह फ्री है", "जी बताइए", "मैं मैनेजर से पूछता हूँ"),
}
DEV_INCOMPLETE = {
    "time": ("कल शाम को", "आज सुबह", "परसों दोपहर को", "शाम 6", "कल सुबह तक या"),
    "price": ("पाँच सौ के", "तीन सौ से", "क़ीमत तो", "सात सौ और", "लगभग"),
    "name": ("मेरा नाम", "मैं रोहन और"),
    "": ("वो मेरे भाई का", "लेकिन", "और फिर", "मतलब", "क्योंकि", "अगर आप", "देखिए", "उम्म", "हम्म", "वो मैनेजर जो",
         "हम लोग कल", "आपके यहाँ से", "मैं कल आऊँगा लेकिन", "सर वो क्या है कि"),
}
GENERAL_COMPLETE = (
    "wo kal aa jayega", "abhi nahi hai", "parking available hai", "main baad mein call karta hoon",
    "aap kal subah aa jaiye", "ye toh free hai", "delivery mil jayegi", "main abhi busy hoon",
    "discount nahi milega", "ek minute ruko", "hold kijiye", "aap ghar aake dekh lijiye",
    "theek hai main bata dunga", "stylist abhi nahi hai", "manager se pooch ke batati hoon",
    "yes we are open till eight", "I am not interested", "it is out of stock", "I will call you back",
    "thank you so much", "no problem at all", "that works for me", "please call tomorrow",
    "we do not do that", "it is possible", "I cannot say right now", "let me check and tell you",
    "kal band hai", "service ho jayegi", "number yahi hai", "main hi bol raha hoon",
    "aapko kal call karenge", "aaj nahi ho payega", "sab theek hai", "ho jayega ji",
    "kaam ho gaya hai", "payment ho chuka hai", "booking confirm hai", "wahan jaana padega",
    "bahut time lagega", "abhi dukaan band hai", "aap WhatsApp kar dijiye", "mujhe pata nahi",
)
GENERAL_INCOMPLETE = (
    "I was thinking that", "we can do it but", "so basically", "the thing is that the", "let me think about",
    "please send it to", "it depends on", "I will let you know if", "the problem is", "and also the",
    "as soon as", "because of", "well I think", "okay so", "I wanted to say that",
    "woh stylist jo hai na", "aap jab bhi", "agar aap kal", "ek minute main", "mujhe lagta hai ki hum",
    "isme kuch", "ye toh", "aap ka naam", "hum aapko bata denge jab", "main manager se pooch ke",
    "mere paas ek problem hai aur", "wo kal ka", "aapke yahan ka", "dekhiye sir wo", "haan toh main keh raha tha ki",
)


def _price(rng: random.Random) -> str:
    return str(rng.choice(NUMBERS)) if rng.random() < 0.6 else rng.choice(WORD_PRICES)


def _hour(rng: random.Random) -> str:
    return str(rng.choice(HOURS)) if rng.random() < 0.7 else rng.choice(HOUR_WORDS)


def _day_part(rng: random.Random) -> str:
    return f"{rng.choice(DAYS)} {rng.choice(PARTS)}"


def _phone(rng: random.Random) -> str:
    return rng.choice("6789") + "".join(rng.choice("0123456789") for _ in range(9))


def _decor(rng: random.Random, core: str) -> str:
    return rng.choice(PRE) + core + rng.choice(SUF)


def _complete(rng: random.Random, kind: str) -> Row:
    if kind == "yesno":
        core = rng.choice(("haan", "haan ji", "ji haan", "nahi", "nahi ji", "bilkul", "theek hai", "yes", "no", "yes sir",
                           "no sir", "okay", "sure", "ji bilkul", "haan bilkul", "nahin", "nahi sir", "sahi hai", "correct"))
        return core, "complete", "yesno"
    if kind == "price":
        p = _price(rng)
        core = rng.choice((f"{p} rupaye", f"{p}", f"{p} lagega", f"{p} mein ho jayega", f"around {p} rupees",
                           f"it is {p}", f"{p} rupaye hai", f"lagbhag {p} rupaye", f"{p} ji", f"rate toh {p} hai",
                           f"{p} per head", f"bas {p} rupaye", f"{p} rupees only"))
        return _decor(rng, core).strip(), "complete", "price"
    if kind == "time":
        d, h = _day_part(rng), _hour(rng)
        core = rng.choice((f"{d} {h} baje", f"{h} baje", f"{d} {h} baje aa jaiye", f"{d} {h} baje free hai",
                           f"{rng.choice(PARTS)} ko {h} baje", f"{d} {h}:30 baje", f"tomorrow at {h} pm",
                           f"{h}:30 pm", f"{d} {h} baje ke baad", "abhi free hai aap aa sakte hain",
                           f"{rng.choice(DAYS)} tak ho jayega", "aaj hi aa jaiye"))
        return _decor(rng, core).strip(), "complete", "time"
    if kind == "name":
        n = rng.choice(NAMES)
        core = rng.choice((f"mera naam {n} hai", f"{n}", f"main {n} bol raha hoon", f"main {n} bol rahi hoon",
                           f"this is {n}", f"my name is {n}", f"{n} speaking", f"naam {n} hai", f"{n} ji"))
        return core, "complete", "name"
    if kind == "phone":
        ph = _phone(rng)
        core = rng.choice((ph, f"{ph[:5]} {ph[5:]}", f"mera number {ph} hai", f"my number is {ph}", f"{ph} hai ji",
                           f"number {ph}"))
        return core, "complete", "phone"
    core = rng.choice(GENERAL_COMPLETE)
    return _decor(rng, core).strip(), "complete", rng.choice(("", "", "yesno"))


def _incomplete(rng: random.Random, kind: str) -> Row:
    pre = rng.choice(PRE)
    if kind == "time":
        d, part = rng.choice(DAYS), rng.choice(PARTS)
        core = rng.choice((f"{d} {part} ko", f"{d} {part}", f"{d} {part} {_hour(rng)}", f"{part} ko", f"{d} ko",
                           f"around {_hour(rng)}", "lagbhag", f"{d} {part} mein", f"{d} {part} {_hour(rng)} ya",
                           f"{d} {part} tak ya phir", f"{d} {part} ke baad", "tomorrow at", "about", f"{d} ke"))
        return (pre + core).strip(), "incomplete", "time"
    if kind == "price":
        p, q = _price(rng), _price(rng)
        core = rng.choice((f"{p} se", f"{p} ke liye", f"{p} se {q} ke", f"{p} aur", f"{p} lekin", f"{p} ya",
                           f"{rng.choice(SMALL_WORDS)}", f"{rng.choice(SMALL_WORDS)} sau aur", "price toh around",
                           "lagbhag", "roughly", "approximately", f"around {p} but", f"{p} ke", "rate ye hai ki",
                           f"{p} lagega par", f"{p} toh"))
        return (pre + core).strip(), "incomplete", "price"
    if kind == "name":
        n = rng.choice(NAMES)
        core = rng.choice(("mera naam", "my name is", "naam hai", "this is", "mera naam hai", f"main {n} aur",
                           f"main {n} bol raha hoon ki", "main", f"{n} ka"))
        return core, "incomplete", "name"
    if kind == "phone":
        ph = _phone(rng)
        k = rng.randint(1, 9)
        shown = ph[:k] if rng.random() < 0.5 else (ph[:5] + " " + ph[5:k] if k > 5 else ph[:k])
        core = rng.choice((shown, f"mera number {shown}", f"number hai {shown}", f"my number is {shown}",
                           f"{shown} aur", "mera number", "number hai"))
        return core, "incomplete", "phone"
    if kind == "yesno":
        core = rng.choice(("haan", "nahi", "yes", "no", "haan ji", "ji haan", "bilkul", "theek hai", "okay")) + " " + rng.choice(CONNECTORS)
        return core, "incomplete", "yesno"
    if kind == "connector":
        base = _complete(rng, rng.choice(("price", "time", "name", "", "yesno")))
        return f"{base[0]} {rng.choice(CONNECTORS)}", "incomplete", base[2]
    if kind == "np":
        core = f"{rng.choice(('wo', 'mere', 'aapke', 'hamare', 'us', 'ye', 'woh'))} {rng.choice(NOUNS)} {rng.choice(POST)}"
        return (pre + core).strip(), "incomplete", ""
    return rng.choice(GENERAL_INCOMPLETE), "incomplete", rng.choice(("", "", "yesno"))


def generate(seed: int = 7, per_kind: int = 90) -> list[Row]:
    """About 1,500 deterministic rows (text, label, answer_type), duplicates removed."""
    rng = random.Random(seed)
    rows: list[Row] = []
    for kind in ("yesno", "price", "time", "name", "phone", "general"):
        for _ in range(per_kind):
            rows.append(_complete(rng, kind))
    for kind in ("time", "price", "name", "phone", "yesno", "connector", "np", "general"):
        for _ in range(per_kind):
            rows.append(_incomplete(rng, kind))
    for at, items in DEV_COMPLETE.items():
        for t in items:
            rows.append((t, "complete", at))
    for at, items in DEV_INCOMPLETE.items():
        for t in items:
            rows.append((t, "incomplete", at))
    for t in GENERAL_INCOMPLETE:
        rows.append((t, "incomplete", ""))
    for t in GENERAL_COMPLETE:
        rows.append((t, "complete", ""))
    seen: set[Row] = set()
    out: list[Row] = []
    for r in rows:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


if __name__ == "__main__":  # pragma: no cover
    data = generate(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
    comp = sum(1 for r in data if r[1] == "complete")
    print(f"{len(data)} rows: {comp} complete, {len(data) - comp} incomplete")
    for r in data[:: max(1, len(data) // 25)]:
        print(r)
