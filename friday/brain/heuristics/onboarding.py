"""Conversational onboarding, one ``OnboardingStep`` at a time (deterministic: it
handles consent and the PIN, so it must be predictable). The brain proposes
``next_step``; the backend validates and persists.

* Consent only on EXPLICIT agreement ("I agree", "agree", "मैं सहमत हूँ", the button).
* PIN: exactly 4 digits, weak PINs refused, never echoed back.
"""

from __future__ import annotations

import re

from friday.core.models import (
    ConversationContext,
    InboundMessage,
    Language,
    OnboardingStep,
    OnboardingTurn,
    Person,
    Place,
    PlaceSource,
    ReplyButton,
    Tone,
)

from ..copy import say
from ..lang import detect_language
from ..schemas import TaskDraft
from ..textutil import extract_phones, has_any, norm
from .interpret import _Ctx, draft_task
from .references import relation_word_in

S = OnboardingStep
INVITE_RE = re.compile(r"\bfri[\s-]*([a-z0-9]{6})\b", re.I)
WEAK_PINS = {
    "1234",
    "4321",
    "1212",
    "2580",
    "0852",
    "0000",
    "1111",
    "2222",
    "3333",
    "4444",
    "5555",
    "6666",
    "7777",
    "8888",
    "9999",
    "1122",
    "6969",
    "1004",
    "2000",
}
SKIP = (
    "skip",
    "later",
    "not now",
    "baad mein",
    "baad me",
    "no",
    "nahi",
    "na",
    "none",
    "nobody",
    "koi nahi",
    "no one",
    "abhi nahi",
)
CITY_MAP = {
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "blr": "Bengaluru",
    "bengalooru": "Bengaluru",
    "delhi": "Delhi NCR",
    "new delhi": "Delhi NCR",
    "ncr": "Delhi NCR",
    "gurgaon": "Delhi NCR",
    "gurugram": "Delhi NCR",
    "noida": "Delhi NCR",
    "mumbai": "Mumbai",
    "bombay": "Mumbai",
    "bom": "Mumbai",
    "navi mumbai": "Mumbai",
    "thane": "Mumbai",
}
CONSENT_YES = (
    "i agree",
    "agree",
    "i accept",
    "मैं सहमत हूँ",
    "सहमत",
    "haan agree",
    "haan, agree",
    "agreed",
    "main agree karta hoon",
    "main agree karti hoon",
)
_STEP_ORDER = [
    S.INVITE_CODE,
    S.NAME,
    S.CITY,
    S.LANGUAGE,
    S.TONE,
    S.CONSENT,
    S.PIN,
    S.CIRCLE,
    S.PLACES,
    S.FIRST_TASK,
    S.DONE,
]


def _next(step: OnboardingStep) -> OnboardingStep:
    i = _STEP_ORDER.index(step)
    return _STEP_ORDER[min(i + 1, len(_STEP_ORDER) - 1)]


def _b(id_: str, title: str) -> ReplyButton:
    return ReplyButton(id=id_, title=title)


def prompt_for(c: _Ctx, step: OnboardingStep) -> tuple[str, list[ReplyButton]]:
    name = c.name
    if step == S.INVITE_CODE:
        return (
            c.say(
                en="I'm Friday. I make calls so you don't have to. Access is by invite only. "
                "Do you have a code?",
                hinglish="Main Friday hoon. Aapke liye calls karti hoon. Abhi sirf invite se "
                "access hai. Code hai?",
            ),
            [],
        )
    if step == S.NAME:
        return c.say(en="What should I call you?", hinglish="Aapko kya bulaun?"), []
    if step == S.CITY:
        return c.say(
            en=f"Nice to meet you{', ' + name if name else ''}. Which city are you in?",
            hinglish=f"Milke achha laga{', ' + name if name else ''}. Kaunsa city?",
        ), [_b("ob:skip", "Skip")]
    if step == S.LANGUAGE:
        return c.say(
            en="Which language do you prefer?", hinglish="Kaunsi language prefer karoge?"
        ), [
            _b("ob:lang:en", "English"),
            _b("ob:lang:hi", "हिंदी"),
            _b("ob:lang:hinglish", "Hinglish"),
        ]
    if step == S.TONE:
        return c.say(
            en='Tone? Playful: "Done. Saturday, 11." Formal: "Your appointment is confirmed '
            'for Saturday, 11 AM."',
            hinglish='Mera style? Playful: "Ho gaya. Saturday 11 baje." Formal: "Your '
            'appointment is confirmed for Saturday, 11 AM."',
        ), [_b("ob:tone:playful", "Playful"), _b("ob:tone:formal", "Formal")]
    if step == S.CONSENT:
        return c.say(
            en="I store your details (name, city, tasks, call recordings) in India, only to do "
            'your tasks. Say "delete everything" anytime to erase them. On every call I '
            "say I'm an AI. Terms: https://friday.example/terms\nAre you 18+ and do you "
            "agree?",
            hinglish="Main aapki details (naam, city, tasks, call recordings) India mein "
            'store karti hoon, sirf aapke kaam ke liye. "delete everything" bolke kabhi bhi '
            "mita sakte ho. Har call pe main batati hoon ki main AI hoon. Terms: "
            "https://friday.example/terms\nKya aap 18+ ho aur agree karte ho?",
        ), [_b("ob:consent:yes", "I agree"), _b("ob:consent:no", "Not now")]
    if step == S.PIN:
        return c.say(
            en="Set a 4-digit Friday PIN. I ask for it before sensitive actions.",
            hinglish="Ek 4-digit Friday PIN set kijiye. Sensitive kaam se pehle main yahi "
            "poochungi.",
        ), []
    if step == S.CIRCLE:
        nri = not c.ctx.user.phone.startswith("+91")
        lead = "Since you're abroad: " if nri else ""
        return c.say(
            en=f"{lead}Do you look after anyone else - parents, spouse, kids? I can book "
            f'for them too. e.g. "my dad Ramesh, +91 98…, Hindi, Jaipur"',
            hinglish=f"{lead}Kya aap kisi aur ka bhi dhyan rakhte ho - parents, spouse, "
            f'bachche? Unke liye bhi book kar sakti hoon. e.g. "mere papa '
            f'Ramesh, +91 98…, Hindi, Jaipur"',
        ), [_b("ob:circle:add", "Add someone"), _b("ob:skip", "Skip")]
    if step == S.PLACES:
        return c.say(
            en="Save your home and office? Share a location pin or type the area "
            '("home: Indiranagar, office: Bellandur").',
            hinglish="Ghar aur office save karun? Location pin bhejo ya area type karo "
            '("home: Indiranagar, office: Bellandur").',
        ), [_b("ob:skip", "Skip")]
    if step == S.FIRST_TASK:
        return c.say(
            en="Last one: what call have you been putting off? I'll make it now. "
            'e.g. "Dentist, Saturday"',
            hinglish="Last: kaunsi call taal rahe ho? Main abhi kar deti hoon. "
            'e.g. "Dentist, Saturday"',
        ), [_b("ob:skip", "Later")]
    return (
        c.say(
            en="You're set. I handle bookings, enquiries, orders, customer care, hotels and "
            "family check-ins. To let me decide on the call, say e.g. \"any slot 5-7pm "
            "under ₹800, you decide\". 'help' lists more.",
            hinglish="Sab set hai. Bookings, enquiries, orders, customer care, hotels aur "
            "family check-ins - sab main karti hoon. Call pe mujhe decide karne dena ho toh "
            'bolo "5-7 ke beech koi bhi slot, ₹800 tak, aap decide karo". Aur jaanne ke '
            "liye 'help'.",
        ),
        [],
    )


def _extract_name(text: str) -> str | None:
    t = text.strip()
    m = re.search(
        r"(?:my name is|i am|i'm|im|this is|call me|mera naam|main|naam)\s+"
        r"([A-Za-zऀ-ॿ][\wऀ-ॿ.' ]{0,40}?)(?:\s+(?:hai|hoon|hu|here))?"
        r"[.!]*$",
        t,
        re.I,
    )
    name = m.group(1) if m else t
    name = re.sub(r"[^\wऀ-ॿ .'-]", "", name).strip()
    words = name.split()
    if not words or len(words) > 4 or any(ch.isdigit() for ch in name):
        return None
    if norm(name) in {"hi", "hello", "hey", "yes", "no", "ok", "skip"}:
        return None
    return " ".join(w[:1].upper() + w[1:] for w in words)


def _city(text: str) -> str | None:
    t = norm(text)
    t = re.sub(r"^(i live in|i'm in|i am in|in|main|city is|my city is)\s+", "", t)
    t = re.sub(r"\s+(mein|me|hoon|hu|se)$", "", t).strip(" .")
    if not t or len(t) > 40:
        return None
    for k, v in CITY_MAP.items():
        if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", t):
            return v
    return " ".join(w.capitalize() for w in t.split())


def _language(text: str, button: str | None) -> Language | None:
    if button and button.startswith("ob:lang:"):
        return Language(button.split(":", 2)[2])
    t = norm(text)
    if "hinglish" in t:
        return Language.HINGLISH
    if "hindi" in t or "हिंदी" in t or "हिन्दी" in t:
        return Language.HI
    if "english" in t:
        return Language.EN
    if not t:
        return None
    return detect_language(text)


def _tone(text: str, button: str | None) -> Tone | None:
    if button and button.startswith("ob:tone:"):
        return Tone(button.split(":", 2)[2])
    t = norm(text)
    if "formal" in t:
        return Tone.FORMAL
    if has_any(t, ("playful", "fun", "casual", "masti")):
        return Tone.PLAYFUL
    if has_any(t, ("friendly", "normal", "default")):
        return Tone.FRIENDLY
    return None


def _people(ctx: ConversationContext, text: str) -> list[Person]:
    out: list[Person] = []
    for chunk in re.split(r";|\n| and also | aur ", text):
        if not chunk.strip():
            continue
        rel = relation_word_in(norm(chunk))
        phones = extract_phones(chunk)
        m = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", chunk)
        name = m.group(1) if m and m.group(1).lower() not in {"my", "add", "mere", "meri"} else None
        if not rel and not name:
            continue
        lang = None
        for word, value in (
            ("marathi", Language.MR),
            ("hindi", Language.HI),
            ("english", Language.EN),
            ("tamil", Language.TA),
            ("telugu", Language.TE),
            ("kannada", Language.KN),
            ("bengali", Language.BN),
            ("gujarati", Language.GU),
        ):
            if word in chunk.lower():
                lang = value
        out.append(
            Person(
                owner_user_id=ctx.user.id,
                name=name or rel[1].title(),
                relation=rel[0] if rel else None,
                aliases=[rel[1]] if rel else [],
                phone=phones[0] if phones else None,
                language=lang,
            )
        )
    return out


def _places(ctx: ConversationContext, msg: InboundMessage) -> list[Place]:
    if msg.location is not None:
        return [
            Place(
                owner_user_id=ctx.user.id,
                label="Home",
                address_text=msg.location.address,
                source=PlaceSource.WA_LOCATION,
            )
        ]
    out: list[Place] = []
    for m in re.finditer(
        r"(home|ghar|office|work|pg)\s*(?:is|:|-|=)?\s*(?:at|in)?\s*"
        r"([^,;\n]+?)(?=$|[,;\n]|\s+(?:and|aur)\s+(?:home|ghar|office|work))",
        msg.text or "",
        re.I,
    ):
        label = {"ghar": "Home", "work": "Office", "pg": "PG"}.get(
            m.group(1).lower(), m.group(1).title()
        )
        out.append(
            Place(
                owner_user_id=ctx.user.id,
                label=label,
                address_text=m.group(2).strip(),
                city=ctx.profile.city,
            )
        )
    return out


def onboarding_turn(
    ctx: ConversationContext, step: OnboardingStep, message: InboundMessage | None
) -> tuple[OnboardingTurn, TaskDraft | None]:
    c = _Ctx(ctx)
    if message is None:
        reply, buttons = prompt_for(c, step)
        return OnboardingTurn(reply=reply, buttons=buttons, next_step=step), None
    text = (message.text or "").strip()
    t = norm(text)
    button = message.button_id
    skip = button == "ob:skip" or (has_any(t, SKIP) and len(t.split()) <= 3)

    def advance(to: OnboardingStep, prefix: str = "", **kw) -> OnboardingTurn:
        reply, buttons = prompt_for(c, to)
        return OnboardingTurn(
            reply=(prefix + " " + reply).strip(), buttons=buttons, next_step=to, **kw
        )

    def again(reply: str, **kw) -> OnboardingTurn:
        _r, buttons = prompt_for(c, step)
        return OnboardingTurn(reply=reply, buttons=buttons, next_step=step, **kw)

    if step == S.INVITE_CODE:
        m = INVITE_RE.search(text)
        if not m:
            return again(
                c.say(
                    en="I'm invite-only right now. Have an invite code? It looks like FRI-XXXXXX.",
                    hinglish="Abhi invite-only hoon. Invite code hai? Aisa dikhta hai: FRI-XXXXXX.",
                )
            ), None
        code = f"FRI-{m.group(1).upper()}"
        return advance(
            S.NAME, c.say(en="You're in.", hinglish="Aap andar ho.", playful_tail=" 🎉"), invite_code=code
        ), None
    if step == S.NAME:
        name = _extract_name(text)
        if not name:
            return again(
                c.say(
                    en="Sorry, what name should I use for you?",
                    hinglish="Sorry, aapka naam kya likhun?",
                )
            ), None
        c.name = name.split()[0]
        return advance(S.CITY, profile_updates={"name": name}), None
    if step == S.CITY:
        if skip:
            return advance(S.LANGUAGE), None
        city = _city(text)
        if not city:
            return again(
                c.say(
                    en="Which city? e.g. Bengaluru, Delhi, Mumbai.",
                    hinglish="Kaunsa city? e.g. Bengaluru, Delhi, Mumbai.",
                )
            ), None
        note = ""
        if city not in ("Bengaluru", "Delhi NCR", "Mumbai"):
            note = c.say(
                en=f"{city}, got it - I work best in Bengaluru, Delhi NCR and Mumbai for now.",
                hinglish=f"{city}, theek hai - abhi main Bengaluru, Delhi NCR aur Mumbai "
                f"mein best kaam karti hoon.",
            )
        else:
            note = c.say(en=f"{city}, got it.", hinglish=f"{city}, got it.")
        return advance(S.LANGUAGE, note, profile_updates={"city": city}), None
    if step == S.LANGUAGE:
        lang = _language(text, button)
        if lang is None or lang not in (Language.EN, Language.HI, Language.HINGLISH):
            lang = Language.HINGLISH if skip or lang is None else lang
        c.lang = lang
        return advance(
            S.TONE,
            say(lang, c.tone, en="Done.", hinglish="Done.", hi="ठीक है।"),
            profile_updates={"language": lang},
        ), None
    if step == S.TONE:
        tone = _tone(text, button) or (Tone.PLAYFUL if skip else None)
        if tone is None:
            return again(c.say(en="Playful or formal?", hinglish="Playful ya formal?")), None
        c.tone = tone
        return advance(S.CONSENT, profile_updates={"tone": tone}), None
    if step == S.CONSENT:
        if button == "ob:consent:yes" or has_any(t, CONSENT_YES):
            return advance(S.PIN, c.say(en="Thanks!", hinglish="Thanks!"), consent_given=True), None
        if button == "ob:consent:no" or has_any(
            t, ("not now", "no", "nahi", "disagree", "don't agree", "dont agree")
        ):
            return OnboardingTurn(
                reply=c.say(
                    en="No problem. Say 'start' whenever you're ready.",
                    hinglish="Koi baat nahi. Jab ready ho, 'start' bol dena.",
                ),
                consent_given=False,
                next_step=S.CONSENT,
            ), None
        return again(
            c.say(
                en='To continue I need your explicit OK - tap "I agree" or type "I agree".',
                hinglish='Aage badhne ke liye clear haan chahiye - "I agree" tap karo ya likho.',
            )
        ), None
    if step == S.PIN:
        digits = re.sub(r"\D", "", text)
        if not re.fullmatch(r"\D*\d{4}\D*", text) or len(digits) != 4:
            return again(
                c.say(
                    en="The PIN has to be exactly 4 digits. Try again?",
                    hinglish="PIN exactly 4 digits ka hona chahiye. Phir se bhejo?",
                )
            ), None
        if digits in WEAK_PINS or len(set(digits)) == 1:
            return again(
                c.say(
                    en="That PIN is easy to guess. Pick another 4 digits.",
                    hinglish="Yeh guess karna aasaan hai. Koi aur 4 digits?",
                )
            ), None
        return advance(
            S.CIRCLE,
            c.say(
                en="PIN set. (Tip: delete that message from the chat.)",
                hinglish="PIN set. (Tip: woh message chat se delete kar do.)",
            ),
            pin=digits,
        ), None
    if step == S.CIRCLE:
        if skip:
            return advance(S.PLACES), None
        if button == "ob:circle:add":
            return again(
                c.say(
                    en="Tell me about them: name, relation, phone, language.",
                    hinglish="Unke baare mein batao: naam, relation, phone, language.",
                )
            ), None
        people = _people(ctx, text)
        if not people:
            return again(
                c.say(
                    en='Who should I add? e.g. "my mom Sunita, +91 98…, Marathi"',
                    hinglish='Kisko add karun? e.g. "meri mummy Sunita, +91 98…, Marathi"',
                )
            ), None
        names = ", ".join(p.name for p in people)
        return advance(
            S.PLACES,
            c.say(
                en=f"Added {names}. You can add more anytime.",
                hinglish=f"{names} add kar liya. Baad mein aur add kar sakte ho.",
            ),
            people=people,
        ), None
    if step == S.PLACES:
        if skip:
            return advance(S.FIRST_TASK), None
        places = _places(ctx, message)
        if not places:
            return again(
                c.say(
                    en='Share a location pin, or type e.g. "home: Indiranagar".',
                    hinglish='Location pin bhejo, ya likho e.g. "home: Indiranagar".',
                )
            ), None
        labels = ", ".join(p.label for p in places)
        return advance(
            S.FIRST_TASK,
            c.say(en=f"Saved {labels}.", hinglish=f"{labels} save kar liya."),
            places=places,
        ), None
    if step == S.FIRST_TASK:
        if skip:
            return advance(S.DONE), None
        draft = draft_task(c, text, message)
        if draft is None:
            return again(
                c.say(
                    en='Tell me the call, e.g. "Book a haircut at Looks tomorrow 6pm".',
                    hinglish='Call batao, e.g. "Looks mein kal 6 baje haircut book karo".',
                )
            ), None
        from .interpret import _task_reply

        reply, _buttons = prompt_for(c, S.DONE)
        return OnboardingTurn(reply=_task_reply(c, draft) + "\n\n" + reply, next_step=S.DONE), draft
    reply, buttons = prompt_for(c, S.DONE)
    return OnboardingTurn(reply=reply, buttons=buttons, next_step=S.DONE), None
