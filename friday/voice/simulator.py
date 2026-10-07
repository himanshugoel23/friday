"""Telephony simulator (V-1): deterministic simulated businesses & people on the phone.

Every number in ``friday/simworld/world.json`` answers with that entry's persona:

* dial behaviour - ``answer``: answers | busy | no_answer | voicemail | callback_later;
  ``Settings.sim_business_answer_rate`` < 1 makes answers flaky (seeded)
* conversation - greeting, language + mid-call switch (``switches_to``), prices,
  negotiation room (``max_discount_pct``), slots, stock, room holds, "are you an AI?",
  hang-up after N turns, facts from ``notes``
* customer care - IVR trees driven by DTMF (or spoken option names), identifier prompts,
  OTP prompts, hold queue (hold music + queue announcements, then a human agent),
  tickets with promised dates, supervisor escalation
* conference - ``add_participant`` dials a third party (the user, a circle member) into
  the call; ``leave`` drops Friday; the remaining parties keep talking
* recording - a transcript file under ``<media_dir>/recordings`` (``file://`` URL)

Unknown numbers do not answer (NO_ANSWER) - except the Friday user being patched in
(``add_participant``) or dialled for translator mode (``metadata["role"] == "user"``),
who is played by a default ``SimParty`` unless one is registered.

Simulator directives live in ``persona.notes`` as ``"sim:<key>[=<value>]"`` (no schema
change needed); other notes are facts the persona tells when asked:
  sim:hostile_to_ai            refuses to talk to an AI and hangs up
  sim:switch_after=N           switch language after N replies (default 2)
  sim:asks_advance=500         asks for an advance before confirming
  sim:agent_asks_otp           care agent demands an OTP (-> patch the user in)
  sim:voicemail_greeting       answers, but it's an answering machine
  sim:person                   behaves like a circle member (wellbeing check-in)
  sim:wellbeing_alert          (person) mentions dizziness when asked how they feel
  sim:medicine=..., sim:feeling=..., sim:sleep=..., sim:food=..., sim:needs=...
                               (person) custom answers
  sim:no_answer_attempts=N     first N dial attempts ring out (NO_ANSWER), then it answers
  sim:alt_phones=+91..,+91..   extra numbers for the same business (BRIEF E36); the primary
                               keeps ``answer``, alternates answer (``sim:alt_answer=busy``...)
  sim:calls_back_after=S       S seconds after an outbound call ends, the business calls the
                               Friday number back (answered inbound call, BRIEF E31/E37)
  sim:missed_call_after=S      ... or gives a missed call (rings ~5 s, hangs up; E32)
  sim:callback_says=<text>     what the business says when Friday answers its call-back

Inbound (BRIEF E30-37): outbound legs carry a sticky Friday caller ID (``from_number``);
``simulate_inbound_call`` / scheduled call-backs publish ``InboundCallReceived`` or
``MissedCall`` on the bus and park the answered leg for ``take_inbound(call_id)``.
Scheduled call-backs are delivered by ``deliver_due_inbound()`` (deterministic: call it
after advancing the clock) or by the optional ``run_inbound_loop()`` background task.

Time: legs sleep on the container Clock. With ``FakeClock`` hold queues advance virtual
time instantly; with the system clock the default ``time_scale`` is 0 (instant) so the
local CLI never waits 7 real minutes on hold.
"""

from __future__ import annotations

import asyncio
import math
import random
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from friday.core.clock import Clock, FakeClock, format_ist
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.events import EventBus
from friday.core.interfaces import CallEnded
from friday.core.logging import get_logger, mask_phone
from friday.core.models import (
    AudioClass,
    DialStatus,
    Language,
    OutboundCallRequest,
    Transcription,
)
from friday.simworld import SimBusiness, SimIVRNode, SimWorld, load_world
from friday.voice.callerid import SIM_FRIDAY_NUMBERS, CallerIdSelector, choose_from_number
from friday.voice.events import InboundCallReceived, MissedCall
from friday.voice.sim_data import phrases as P
from friday.voice.text import contains_any, redact_secrets

log = get_logger(__name__)

HOLD_CHUNK_S = 30
RING_S = 4


class SimTranscription(Transcription):
    """Transcription + nominal chunk length (used for hold-time accounting)."""

    duration_s: float | None = None


class SimParty(BaseModel):
    """A non-business party: the Friday user (patched in / translator) or a person."""

    name: str = "User"
    language: Language = Language.HINGLISH
    answer: str = "answers"  # answers | busy | no_answer
    greeting: str | None = None
    script: list[str] = Field(default_factory=list)  # lines spoken in turn
    gives_otp: bool = True  # reads their own OTP to an agent on a bridged call
    replies: dict[str, str] = Field(default_factory=dict)  # medicine/feeling/... -> text


# =============================================================================== agents


class _Agent:
    """Something on the far end that hears text and produces utterances."""

    answer_mode: str = "answers"
    name: str = "party"

    def __init__(self, sim: SimulatedTelephony, language: Language) -> None:
        self.sim = sim
        self.lang = language
        self.outbox: deque[SimTranscription] = deque()
        self.ended = False
        self.ending = False  # hang up once the outbox is drained
        self.replies = 0
        self.silent_listens = 0
        self.legs: list[SimCallLeg] = []

    # -- output
    def say(
        self, parts: list[tuple[str, dict]], audio_class: AudioClass = AudioClass.HUMAN
    ) -> None:
        texts: list[str] = []
        lang = self.lang
        for key, params in parts:
            text, lang = P.phrase(self.lang, key, **params)
            texts.append(text)
        if texts:
            self.emit(" ".join(texts), lang, audio_class)

    def emit(
        self,
        text: str,
        language: Language | None,
        audio_class: AudioClass = AudioClass.HUMAN,
        duration_s: float | None = None,
    ) -> None:
        self.outbox.append(
            SimTranscription(
                text=text,
                language=language,
                confidence=0.95,
                audio_class=audio_class,
                duration_s=duration_s,
            )
        )
        if audio_class == AudioClass.HUMAN:
            self.replies += 1
            self.after_reply()

    def after_reply(self) -> None:  # language switch hook
        pass

    # -- input
    def start(self) -> None:  # called when the call is answered
        pass

    def hear(self, text: str, *, from_friday: bool = True) -> None:
        pass

    def on_dtmf(self, digits: str) -> None:
        pass

    async def idle(self, leg: SimCallLeg, timeout_s: float) -> SimTranscription | None:
        """Nothing queued: the far end is silent (or says hello / hangs up)."""
        self.silent_listens += 1
        if self.silent_listens == 2:
            self.say([("hello", {})])
            return self.outbox.popleft()
        if self.silent_listens >= 4:
            self.ended = True
            raise CallEnded()
        await self.sim.sleep(timeout_s)
        return None


def _directives(notes: list[str]) -> tuple[dict[str, str], list[str]]:
    d: dict[str, str] = {}
    facts: list[str] = []
    for n in notes:
        if n.startswith("sim:"):
            key, _, val = n[4:].partition("=")
            d[key.strip()] = val.strip()
        else:
            facts.append(n)
    return d, facts


_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)|(\d[\d,]*)\s*(?:rupees|rupaye|rs\b|/-)", re.I)
_DIGITS4 = re.compile(r"\d(?:[ \-]?\d){3,}")


def _amounts(text: str) -> list[int]:
    out = []
    for m in _AMOUNT.finditer(text):
        raw = (m.group(1) or m.group(2) or "").replace(",", "")
        if raw.isdigit():
            out.append(int(raw))
    return out


def _inr(n: int) -> str:
    return f"₹{n:,}"


class BusinessAgent(_Agent):
    """A simworld business persona."""

    def __init__(
        self, sim: SimulatedTelephony, biz: SimBusiness, call_no: int, *, via_alt: bool = False
    ) -> None:
        super().__init__(sim, biz.persona.language)
        self.biz = biz
        self.p = biz.persona
        self.name = biz.name
        self.rng = random.Random(f"{sim.seed}:{biz.id}:{call_no}")
        self.directives, self.facts = _directives(self.p.notes)
        self.answer_mode = self.p.answer
        if via_alt:
            self.answer_mode = self.directives.get("alt_answer") or "answers"
        self.switch_after = int(self.directives.get("switch_after") or 2)
        self.state = "human"
        self.node_id = "root"
        self.dtmf_buffer = ""
        self.invalid = 0
        self.no_input = 0
        self.held_s = 0.0
        self.hold_target_s = float(self.p.hold_seconds)
        self.queue_chunks = 0
        self.rep = self.p.rep_name or "Anita"
        self.entered: list[str] = []  # identifiers keyed into the IVR (for tests)
        self.ai_asked = False
        self.ai_acked = False
        self.hostile_done = False
        self.discount_round = 0
        self.price_now: dict[str, int] = {}
        self.otp_requests = 0
        self.verified = False
        self.ticket: str | None = None
        self.booking: str | None = None
        self.holdline_acked = False
        self.heard_friday = 0
        self.advance_said = False
        self.escalated = False
        self.ending_after_next = False

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if "voicemail_greeting" in self.directives:
            self.emit(
                self.p.greeting
                if self.p.greeting != "Hello?"
                else "The person you are calling is not available. Please leave a message after the beep.",
                Language.EN,
                AudioClass.VOICEMAIL,
            )
            self.ending = True
            return
        if self.p.ivr:
            self.state = "ivr"
            self._prompt()
            return
        if self.hold_target_s > 0:
            self.state = "queue"
            return
        self.emit(self.p.greeting, self.p.language)
        if self.answer_mode == "callback_later":
            self.ending_after_next = True

    def start_inbound(self) -> None:
        """The business is calling Friday back; Friday answered."""
        self.answer_mode = "answers"
        self.state = "human"
        says = self.directives.get("callback_says")
        if says:
            self.emit(says, self.p.language)
        else:
            self.say([("callback_greeting", {"name": self.biz.name})])

    def after_reply(self) -> None:
        if self.p.switches_to and self.replies >= self.switch_after:
            self.lang = self.p.switches_to
        if self.p.hangs_up_after_turns and self.replies >= self.p.hangs_up_after_turns:
            self.ending = True

    # ------------------------------------------------------------------ IVR
    @property
    def node(self) -> SimIVRNode:
        return self.p.ivr[self.node_id]

    def _prompt(self) -> None:
        self.emit(self.node.prompt, self.p.language, AudioClass.IVR_PROMPT)

    def _goto(self, target: str) -> None:
        if target == "agent":
            self.state = "queue"
            return
        if target == "hangup":
            self.say([("ivr_bye", {})], AudioClass.IVR_PROMPT)
            self.ending = True
            return
        if target in self.p.ivr:
            self.node_id = target
            self.dtmf_buffer = ""
            self._prompt()

    def on_dtmf(self, digits: str) -> None:
        if self.state != "ivr":
            return
        self.outbox.clear()
        self.no_input = 0
        for ch in digits:
            if ch.lower() == "w" or ch == " ":
                continue
            node = self.node
            if node.asks_for or node.asks_otp:
                if ch == "#":
                    entered, self.dtmf_buffer = self.dtmf_buffer, ""
                    self.entered.append(entered)
                    nxt = node.options.get("#")
                    if nxt and len(entered) >= 4:
                        self._goto(nxt)
                    else:
                        self.say([("ivr_invalid", {})], AudioClass.IVR_PROMPT)
                        self._prompt()
                elif ch in node.options and not self.dtmf_buffer:
                    self._goto(node.options[ch])
                else:
                    self.dtmf_buffer += ch
                continue
            target = node.options.get(ch)
            if target is None:
                self.invalid += 1
                if self.invalid >= 3:
                    self.say([("ivr_no_input", {})], AudioClass.IVR_PROMPT)
                    self.ending = True
                    return
                self.say([("ivr_invalid", {})], AudioClass.IVR_PROMPT)
                self._prompt()
                continue
            self._goto(target)

    def _spoken_option(self, low: str) -> str | None:
        """'broadband' spoken at 'For broadband press 3' -> '3'."""
        words = {w for w in re.findall(r"[a-zऀ-ॿ]{4,}", low)}
        for clause in re.split(r"[.,;]", self.node.prompt.lower()):
            m = re.search(r"(?:press|dial)\s+(\d|star|hash)|(\d)\s*dabaye", clause)
            if not m:
                continue
            key = m.group(1) or m.group(2)
            key = {"star": "*", "hash": "#"}.get(key, key)
            if any(w in clause for w in words if w not in ("press", "dial")):
                return key
        return None

    # ------------------------------------------------------------------ idle
    async def idle(self, leg: SimCallLeg, timeout_s: float) -> SimTranscription | None:
        if self.state == "queue":
            remaining = self.hold_target_s - self.held_s
            if remaining <= 0:
                self.state = "human"
                company = self.biz.company or self.biz.name
                self.say([("agent_greeting", {"rep": self.rep, "company": company})])
                return self.outbox.popleft()
            chunk = min(HOLD_CHUNK_S, remaining)
            await self.sim.sleep(chunk)
            self.held_s += chunk
            self.queue_chunks += 1
            if self.queue_chunks % 2 == 1:
                minutes = max(1, math.ceil((self.hold_target_s - self.held_s) / 60))
                text, lang = P.phrase(
                    Language.EN if self.p.language == Language.EN else self.p.language,
                    "queue",
                    minutes=minutes,
                )
                return SimTranscription(
                    text=text,
                    language=lang,
                    audio_class=AudioClass.QUEUE_ANNOUNCEMENT,
                    duration_s=chunk,
                    confidence=0.9,
                )
            return SimTranscription(
                text="", language=None, audio_class=AudioClass.HOLD_MUSIC, duration_s=chunk
            )
        if self.state == "ivr":
            self.no_input += 1
            await self.sim.sleep(min(timeout_s, 5))
            if self.no_input >= 3:
                self.say([("ivr_no_input", {})], AudioClass.IVR_PROMPT)
                self.ending = True
            else:
                self._prompt()
            return self.outbox.popleft()
        return await super().idle(leg, timeout_s)

    # ------------------------------------------------------------------ conversation
    def hear(self, text: str, *, from_friday: bool = True) -> None:
        if self.ended:
            return
        low = text.lower()
        if self.state == "ivr":
            key = self._spoken_option(low)
            if key:
                self.on_dtmf(key)
            return
        if self.state == "queue":
            return
        self.outbox.clear()  # anything unread was talked over
        self.silent_listens = 0
        if from_friday:
            self.heard_friday += 1
        parts = self._respond(low, text, from_friday=from_friday)
        if parts:
            self.say(parts)

    def _respond(self, low: str, text: str, *, from_friday: bool) -> list[tuple[str, dict]]:
        d = self.directives
        is_bye = contains_any(low, P.KW_BYE)

        if self.ending_after_next:
            self.ending = True
            return [("callback_ok" if contains_any(low, P.KW_CALLBACK) else "bye", {})]

        if "hostile_to_ai" in d and not self.hostile_done:
            self.hostile_done = True
            self.ending = True
            return [("hostile", {})]

        parts: list[tuple[str, dict]] = []
        if self.p.asks_if_ai and from_friday and not self.ai_asked:
            self.ai_asked = True
            return [("ask_ai", {})]
        if self.ai_asked and not self.ai_acked and from_friday:
            self.ai_acked = True
            if contains_any(low, P.KW_AI_ANSWER):
                parts.append(("ai_ack", {}))
            else:  # dodged the question -> suspicious, ends the call
                self.ending = True
                return [("hostile", {})]

        if contains_any(low, P.KW_CONNECT):
            return parts  # "connecting the account holder now" - just wait
        if self.biz.is_customer_care:
            if from_friday and self.heard_friday == 1 and contains_any(low, P.KW_HOSTILE_TRIGGER) and not (
                contains_any(low, P.KW_COMPLAINT)
            ):
                return parts + [("ok", {})]  # just the disclosure
            return parts + self._care(low, text, is_bye)

        if contains_any(low, P.KW_CALLBACK):
            if contains_any(low, P.KW_HOLD_REQ) or self.p.slots:
                parts.append(("hold_ok", {}))
            parts.append(("callback_ok", {}))
            if is_bye:
                parts.append(("bye", {}))
                self.ending = True
            return parts
        if contains_any(low, P.KW_HOLD_REQ):
            hours = self.p.holds_room_hours
            if self.biz.hotel is not None:
                parts.append(("room_hold", {"hours": hours}) if hours else ("room_no_hold", {}))
            else:
                parts.append(("hold_ok", {}))
            return parts
        if contains_any(low, P.KW_CONFIRM):
            if d.get("asks_advance") and not self.advance_said:
                self.advance_said = True
                return parts + [("advance", {"amount": _inr(int(d["asks_advance"] or 500))})]
            self.booking = self.booking or self._ref(self.biz.id[4:6].upper() or "BK")
            parts.append(("confirmed", {"slot": self._slot_in(low), "booking": self.booking}))
            if is_bye:
                parts.append(("bye", {}))
                self.ending = True
            return parts
        if contains_any(low, P.KW_HOLDLINE) or contains_any(low, P.KW_CONNECT):
            if not self.holdline_acked and contains_any(low, P.KW_HOLDLINE):
                self.holdline_acked = True
                return parts + [("hold_ack", {})]
            return parts
        if is_bye and not contains_any(low, P.KW_PRICE + P.KW_SLOT):
            self.ending = True
            return parts + [("bye", {})]

        answered = False
        if contains_any(low, P.KW_DISCOUNT) and self._catalogue():
            parts.append(self._negotiate(low))
            answered = True
        else:
            stock = self._stock(low)
            if stock:
                parts.append(stock)
                answered = True
            if contains_any(low, P.KW_PRICE) or (self.biz.hotel and contains_any(low, P.KW_ROOM)):
                cat = self._catalogue()
                if cat:
                    key = "rooms" if self.biz.hotel else "prices"
                    parts.append((key, {"prices": self._price_list(low)}))
                    answered = True
            if contains_any(low, P.KW_SLOT) and not stock and not (self.biz.hotel and answered):
                parts.append(
                    ("slots", {"slots": ", ".join(self.p.slots)})
                    if self.p.slots
                    else ("no_slots", {})
                )
                answered = True
        for fact in self.facts:
            words = [w for w in re.findall(r"[a-z]{4,}", fact.lower())]
            if words and any(w in low for w in words):
                parts.append(("note", {"note": fact}))
                answered = True
        if not answered and not parts:
            parts.append(("ok", {}) if self.heard_friday <= 1 else ("unknown", {}))
        return parts

    # ------------------------------------------------------------------ helpers
    def _ref(self, prefix: str) -> str:
        return f"{prefix}{self.rng.randint(10**5, 10**6 - 1)}"

    def _catalogue(self) -> dict[str, int]:
        if self.biz.hotel and isinstance(self.biz.hotel.get("rooms"), dict):
            return {k: int(v) for k, v in self.biz.hotel["rooms"].items()}
        return dict(self.p.prices)

    def _matched(self, low: str) -> list[str]:
        cat = self._catalogue()
        hits = [k for k in cat if all(t in low for t in k.lower().split())]
        if not hits:
            hits = [k for k in cat if any(len(t) > 3 and t in low for t in k.lower().split())]
        return hits or list(cat)

    def _price_list(self, low: str) -> str:
        cat = self._catalogue()
        return ", ".join(f"{k} {_inr(self.price_now.get(k, cat[k]))}" for k in self._matched(low))

    def _negotiate(self, low: str) -> tuple[str, dict]:
        cat = self._catalogue()
        item = self._matched(low)[0]
        base = cat[item]
        current = self.price_now.get(item, base)
        pct = self.p.max_discount_pct
        if pct <= 0:
            return ("no_discount", {})
        floor = int(math.ceil(base * (1 - pct / 100) / 10) * 10)
        self.discount_round += 1
        cited = [a for a in _amounts(low) if a < current]
        if self.discount_round == 1:
            new = int(math.floor(base * (1 - pct / 200) / 10) * 10)
        else:
            new = floor
        if cited:
            new = max(
                floor, min(min(cited), new) if self.discount_round > 1 else max(floor, min(cited))
            )
        new = max(floor, min(new, current))
        if new >= current:
            return ("final_price", {"price": f"{item} {_inr(current)}"})
        self.price_now[item] = new
        return ("discount", {"price": f"{item} {_inr(new)}"})

    def _stock(self, low: str) -> tuple[str, dict] | None:
        for item, ok in self.p.stock.items():
            tokens = item.lower().split()
            if all(t in low for t in tokens) or (
                tokens and tokens[0] in low and len(tokens[0]) > 3
            ):
                return ("stock_yes" if ok else "stock_no", {"item": item})
        return None

    def _slot_in(self, low: str) -> str:
        for s in self.p.slots:
            if s.lower() in low:
                return s
        for s in self.p.slots:  # "6pm" in "6 pm wala"
            if s.lower().replace(" ", "") in low.replace(" ", ""):
                return s
        return self.p.slots[0] if self.p.slots else "the requested time"

    def _care(self, low: str, text: str, is_bye: bool) -> list[tuple[str, dict]]:
        d = self.directives
        if contains_any(low, P.KW_ESCALATE) and not self.escalated:
            self.escalated = True
            self.state = "queue"
            self.hold_target_s = self.held_s + 60
            self.rep = "Supervisor " + (self.p.rep_name or "Meera")
            return [("escalate", {})]
        if "agent_asks_otp" in d and not self.verified:
            if (
                self.otp_requests
                and _DIGITS4.search(text)
                and not self._looks_like_identifier(text)
            ):
                self.verified = True
                return [("verified", {})] + self._issue_ticket()
            self.otp_requests += 1
            return [("otp_ask", {}) if self.otp_requests == 1 else ("otp_insist", {})]
        if self.ticket and is_bye:
            self.ending = True
            return [("bye", {})]
        if (
            contains_any(low, P.KW_COMPLAINT + ("ticket", "status", "reference"))
            or self.heard_friday >= 2
        ):
            if self.ticket:
                return [("ticket", self._ticket_params())]
            return self._issue_ticket()
        if is_bye:
            self.ending = True
            return [("bye", {})]
        return [("ok", {})]

    def _looks_like_identifier(self, text: str) -> bool:
        return "number" in text.lower() and "otp" not in text.lower()

    def _ticket_params(self) -> dict:
        when = self.sim.clock.now() + timedelta(days=2)
        return {"ticket": self.ticket, "date": format_ist(when, "%d %B")}

    def _issue_ticket(self) -> list[tuple[str, dict]]:
        self.ticket = self._ref(self.p.ticket_prefix or "TKT") + str(self.rng.randint(10, 99))
        return [("ticket", self._ticket_params())]


class PersonAgent(_Agent):
    """A circle member (wellbeing check-in) - simworld entry or registered SimParty."""

    def __init__(
        self,
        sim: SimulatedTelephony,
        *,
        name: str,
        language: Language,
        greeting: str,
        replies: dict[str, str],
        asks_if_ai: bool = False,
        answer: str = "answers",
    ) -> None:
        super().__init__(sim, language)
        self.name = name
        self.greeting = greeting
        self.custom = replies
        self.asks_if_ai = asks_if_ai
        self.ai_asked = False
        self.answer_mode = answer

    @classmethod
    def from_business(cls, sim: SimulatedTelephony, biz: SimBusiness) -> PersonAgent:
        d, facts = _directives(biz.persona.notes)
        replies = {
            k: v for k, v in d.items() if k in ("medicine", "feeling", "sleep", "food", "needs")
        }
        if "wellbeing_alert" in d and "feeling" not in replies:
            replies["feeling"] = (
                "Thoda chakkar aa raha hai subah se, aur seene mein halka dard hai."
            )
        return cls(
            sim,
            name=biz.name,
            language=biz.persona.language,
            greeting=biz.persona.greeting,
            replies=replies,
            asks_if_ai=biz.persona.asks_if_ai,
            answer=biz.persona.answer,
        )

    def start(self) -> None:
        self.emit(self.greeting, self.lang)

    def hear(self, text: str, *, from_friday: bool = True) -> None:
        if self.ended:
            return
        low = text.lower()
        self.outbox.clear()
        self.silent_listens = 0
        if self.asks_if_ai and not self.ai_asked:
            self.ai_asked = True
            self.say([("ask_ai", {})])
            return
        texts: list[str] = []
        lang = self.lang
        for key, kws in (
            ("medicine", P.KW_MEDICINE),
            ("feeling", P.KW_FEELING),
            ("sleep", P.KW_SLEEP),
            ("food", P.KW_FOOD),
            ("needs", P.KW_NEEDS),
        ):
            if contains_any(low, kws):
                if key in self.custom:
                    texts.append(self.custom[key])
                else:
                    t, lang = P.phrase(self.lang, key)
                    texts.append(t)
        if contains_any(low, P.KW_BYE):
            t, lang = P.phrase(self.lang, "bye")
            texts.append(t)
            self.ending = True
        if not texts:
            t, lang = P.phrase(self.lang, "person_ok")
            texts.append(t)
        self.emit(" ".join(texts), lang)


class UserAgent(_Agent):
    """The Friday user (or anyone patched in) - speaks ``script`` lines in turn."""

    def __init__(self, sim: SimulatedTelephony, party: SimParty) -> None:
        super().__init__(sim, party.language)
        self.party = party
        self.name = party.name
        self.answer_mode = party.answer
        self.script = deque(party.script)
        self.otp_given = False

    def start(self) -> None:
        if self.party.greeting:
            self.emit(self.party.greeting, self.lang)
        else:
            self.say([("user_join", {})])

    def hear(self, text: str, *, from_friday: bool = True) -> None:
        if self.ended:
            return
        low = text.lower()
        self.outbox.clear()
        if (
            self.party.gives_otp
            and not self.otp_given
            and contains_any(low, ("otp", "verif", "ओटीपी"))
        ):
            self.otp_given = True
            self.say([("user_otp", {})])
            return
        if contains_any(low, P.KW_CONNECT) or contains_any(low, P.KW_HOLDLINE):
            return
        if self.script:
            self.emit(self.script.popleft(), self.lang)
            return
        self.say([("user_bye", {})])
        self.ending = True


# =============================================================================== legs


@dataclass
class ScheduledInbound:
    at_s: float  # epoch seconds on the simulator clock
    from_phone: str
    to_phone: str
    kind: str  # "answered" | "missed"
    business_id: str | None = None


@dataclass
class _Conference:
    agents: list[_Agent] = field(default_factory=list)
    friday_present: bool = True


class SimCallLeg:
    """``CallLeg`` over a simulated agent (utterance level, text in/out)."""

    provider = "simulator"

    def __init__(
        self,
        sim: SimulatedTelephony,
        request: OutboundCallRequest,
        agent: _Agent | None,
        *,
        call_no: int,
        conference: _Conference | None = None,
    ) -> None:
        self.sim = sim
        self.request = request
        self.agent = agent
        self.provider_call_id: str | None = f"SIM{call_no:05d}-{request.task_id[:8]}"
        self.conference = conference or _Conference(agents=[agent] if agent else [])
        self.status: DialStatus | None = None
        self.ended = False
        self.left = False
        self.events: list[str] = []  # human-readable log (recording + tests)
        self.spoken: list[tuple[str, Language]] = []
        self.dtmf: list[str] = []
        self.children: list[SimCallLeg] = []
        self._recording: Path | None = None
        self.from_number: str | None = request.metadata.get("from_number")
        self.inbound = request.metadata.get("direction") == "inbound"

    # ------------------------------------------------------------------ dial
    async def wait_for_answer(self, timeout_s: float) -> DialStatus:
        if self.status is not None:
            return self.status
        agent = self.agent
        mode = agent.answer_mode if agent else "no_answer"
        if agent is not None and self.sim.forced_no_answer(self.request.to_phone, agent):
            mode = "no_answer"
        if (
            agent is not None
            and mode in ("answers", "callback_later")
            and not self.sim.answers_now(self.request)
        ):
            mode = "no_answer"
        if mode == "busy":
            await self.sim.sleep(3)
            self.status = DialStatus.BUSY
        elif mode == "voicemail":
            await self.sim.sleep(min(timeout_s, 12))
            self.status = DialStatus.VOICEMAIL
        elif mode == "no_answer" or agent is None:
            await self.sim.sleep(timeout_s)
            self.status = DialStatus.NO_ANSWER
        else:
            await self.sim.sleep(min(RING_S, timeout_s))
            self.status = DialStatus.ANSWERED
            agent.legs.append(self)
            agent.start()
        self.events.append(f"DIAL {self.status.value}")
        if self.status != DialStatus.ANSWERED:
            self.ended = True
        return self.status

    def _check_live(self) -> None:
        if self.status != DialStatus.ANSWERED:
            raise CallEnded()
        if self.ended or self.left or (self.agent and self.agent.ended and not self.agent.outbox):
            self.ended = True
            raise CallEnded()

    # ------------------------------------------------------------------ media
    async def speak(self, text: str, language: Language) -> None:
        self._check_live()
        self.spoken.append((text, language))
        self.events.append(f"FRIDAY[{language.value}]: {text}")
        assert self.agent is not None
        self.agent.hear(text, from_friday=True)
        await self.sim.sleep(max(1.0, len(text.split()) * 0.4))

    async def listen(self, timeout_s: float) -> Transcription | None:
        self._check_live()
        agent = self.agent
        assert agent is not None
        if agent.outbox:
            item: SimTranscription | None = agent.outbox.popleft()
        else:
            try:
                item = await agent.idle(self, timeout_s)
            except CallEnded:
                self.ended = True
                self.events.append("HUNG UP")
                raise
        if agent.ending and not agent.outbox:
            agent.ended = True
        if item is None:
            return None
        if item.text:
            self.events.append(
                f"{agent.name}[{item.audio_class.value}/{(item.language or Language.EN).value}]: "
                f"{redact_secrets(item.text)}"
            )
            # conference: the other parties hear it too
            for other in self.conference.agents:
                if other is not agent and not other.ended and item.audio_class == AudioClass.HUMAN:
                    other.hear(item.text, from_friday=False)
        elif item.audio_class == AudioClass.HOLD_MUSIC and (
            not self.events or not self.events[-1].endswith("[hold music]")
        ):
            self.events.append(f"{agent.name}: [hold music]")
        return item

    async def send_dtmf(self, digits: str) -> None:
        self._check_live()
        self.dtmf.append(digits)
        self.events.append(f"DTMF {len(digits)} keys")
        assert self.agent is not None
        self.agent.on_dtmf(digits)
        await self.sim.sleep(0.2 * len(digits))

    # ------------------------------------------------------------------ conference
    async def add_participant(self, phone: str, *, announce: str | None = None) -> SimCallLeg:
        self._check_live()
        agent = self.sim.agent_for(phone, role="user")
        req = OutboundCallRequest(
            to_phone=phone,
            task_id=self.request.task_id,
            record=False,
            metadata={"role": "user", "parent": self.provider_call_id or ""},
        )
        leg = SimCallLeg(
            self.sim, req, agent, call_no=self.sim.next_call_no(), conference=self.conference
        )
        self.sim.legs.append(leg)
        self.children.append(leg)
        if agent is not None:
            self.conference.agents.append(agent)
        self.events.append(f"CONFERENCE add {mask_phone(phone)}")
        if announce:
            leg.events.append(f"WHISPER: {announce}")
        return leg

    async def leave(self) -> None:
        if self.left:
            return
        self.left = True
        self.conference.friday_present = False
        self.events.append("FRIDAY LEFT (parties remain bridged)")
        self._write_recording()

    async def hangup(self) -> None:
        if not self.ended:
            self.events.append("FRIDAY HUNG UP")
        already = self.ended and self._recording is not None
        self.ended = True
        for agent in self.conference.agents:
            agent.ended = True
        for child in self.children:
            child.ended = True
        self._write_recording()
        if not already and not self.inbound and self.status == DialStatus.ANSWERED:
            self.sim.after_outbound(self)

    async def recording_url(self) -> str | None:
        if self._recording is None:
            return None
        return self._recording.resolve().as_uri()

    def _write_recording(self) -> None:
        if not self.request.record or self.status != DialStatus.ANSWERED:
            return
        try:
            folder = Path(self.sim.media_dir) / "recordings"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{self.provider_call_id}.txt"
            path.write_text("\n".join(self.events) + "\n", encoding="utf-8")
            self._recording = path
        except OSError:  # pragma: no cover - read-only FS
            log.warning("simulator could not write recording")


# =============================================================================== provider


class SimulatedTelephony:
    """``TelephonyProvider`` backed by ``simworld``. Deterministic given ``seed``."""

    name = "simulator"

    def __init__(
        self,
        *,
        world: SimWorld,
        clock: Clock,
        seed: int = 7,
        answer_rate: float = 1.0,
        media_dir: str = "./var/media",
        time_scale: float | None = None,
        default_user: SimParty | None = None,
        bus: EventBus | None = None,
        friday_numbers: list[str] | None = None,
    ) -> None:
        self.world = world
        self.clock = clock
        self.seed = seed
        self.answer_rate = answer_rate
        self.media_dir = media_dir
        self.time_scale = (
            time_scale if time_scale is not None else (1.0 if isinstance(clock, FakeClock) else 0.0)
        )
        self.default_user = default_user or SimParty()
        self.parties: dict[str, SimParty] = {}
        self.legs: list[SimCallLeg] = []
        self.bus = bus
        self.friday_numbers: list[str] = list(friday_numbers or SIM_FRIDAY_NUMBERS)
        self.caller_id_selector: CallerIdSelector | None = None
        self.inbound_legs: dict[str, SimCallLeg] = {}
        self.pending_inbound: list[ScheduledInbound] = []
        self.inbound_log: list[ScheduledInbound] = []  # delivered (tests / QA)
        self._dial_attempts: dict[str, int] = {}
        self._alt_index: dict[str, SimBusiness] = {}
        for biz in world.businesses:
            d, _ = _directives(biz.persona.notes)
            for alt in filter(None, (x.strip() for x in d.get("alt_phones", "").split(","))):
                self._alt_index[alt] = biz
        self._call_no = 0
        self._per_number: dict[str, int] = {}
        self._rng = random.Random(f"answer:{seed}")

    # ------------------------------------------------------------------ setup
    def register_party(self, phone: str, party: SimParty) -> None:
        """Script a user / person (tests, QA e2e, translator mode)."""
        self.parties[phone] = party

    def next_call_no(self) -> int:
        self._call_no += 1
        return self._call_no

    async def sleep(self, seconds: float) -> None:
        if self.time_scale > 0 and seconds > 0:
            await self.clock.sleep(seconds * self.time_scale)
        else:
            await asyncio.sleep(0)

    def answers_now(self, request: OutboundCallRequest) -> bool:
        if self.answer_rate >= 1.0 or request.metadata.get("role") == "user":
            return True
        return self._rng.random() < self.answer_rate

    def agent_for(self, phone: str, *, role: str | None = None) -> _Agent | None:
        if phone in self.parties:
            party = self.parties[phone]
            if party.replies:
                return PersonAgent(
                    self,
                    name=party.name,
                    language=party.language,
                    greeting=party.greeting or "Hello?",
                    replies=party.replies,
                    answer=party.answer,
                )
            return UserAgent(self, party)
        biz = self.world.by_phone(phone)
        via_alt = False
        if biz is None and phone in self._alt_index:
            biz, via_alt = self._alt_index[phone], True
        if biz is not None:
            n = self._per_number.get(biz.id, 0) + 1
            self._per_number[biz.id] = n
            d, _ = _directives(biz.persona.notes)
            if "person" in d or biz.category.lower() in ("person", "circle member", "family"):
                return PersonAgent.from_business(self, biz)
            return BusinessAgent(self, biz, n, via_alt=via_alt)
        if role == "user":
            return UserAgent(self, self.default_user)
        return None

    def business_for(self, phone: str) -> SimBusiness | None:
        return self.world.by_phone(phone) or self._alt_index.get(phone)

    def forced_no_answer(self, phone: str, agent: _Agent) -> bool:
        """``sim:no_answer_attempts=N``: the first N dials (per number) ring out."""
        n = self._dial_attempts.get(phone, 0) + 1
        self._dial_attempts[phone] = n
        if not isinstance(agent, BusinessAgent):
            return False
        limit = int(agent.directives.get("no_answer_attempts") or 0)
        return n <= limit

    # ------------------------------------------------------------------ inbound
    def after_outbound(self, leg: SimCallLeg) -> None:
        """Schedule a scripted call-back / missed call after an outbound call ends."""
        biz = self.business_for(leg.request.to_phone)
        if biz is None:
            return
        d, _ = _directives(biz.persona.notes)
        to = leg.from_number or self.friday_numbers[0]
        for key, kind in (("calls_back_after", "answered"), ("missed_call_after", "missed")):
            if d.get(key):
                self.pending_inbound.append(
                    ScheduledInbound(
                        at_s=self.clock.now().timestamp() + float(d[key]),
                        from_phone=leg.request.to_phone,
                        to_phone=to,
                        kind=kind,
                        business_id=biz.id,
                    )
                )

    async def deliver_due_inbound(self) -> list[str]:
        """Deliver every scheduled call-back / missed call that is due. Returns call ids
        of ANSWERED inbound calls (parked for ``take_inbound``)."""
        now = self.clock.now().timestamp()
        due = [p for p in self.pending_inbound if p.at_s <= now]
        self.pending_inbound = [p for p in self.pending_inbound if p.at_s > now]
        ids: list[str] = []
        for item in sorted(due, key=lambda p: p.at_s):
            cid = await self.simulate_inbound_call(
                item.from_phone, item.to_phone, answered=item.kind == "answered"
            )
            if cid:
                ids.append(cid)
        return ids

    async def run_inbound_loop(self, poll_s: float = 1.0) -> None:  # pragma: no cover
        """Background delivery for the interactive simulator (real clock)."""
        while True:
            await self.deliver_due_inbound()
            await asyncio.sleep(poll_s)

    async def simulate_inbound_call(
        self,
        from_phone: str,
        to_phone: str | None = None,
        *,
        answered: bool = True,
        ring_s: float = 5.0,
    ) -> str | None:
        """A business/person calls a Friday number. ``answered=False`` -> missed call
        (``MissedCall`` event, returns None). Else the answered leg is parked and
        ``InboundCallReceived`` published; returns the call id."""
        to_phone = to_phone or self.friday_numbers[0]
        no = self.next_call_no()
        item = ScheduledInbound(
            at_s=self.clock.now().timestamp(),
            from_phone=from_phone,
            to_phone=to_phone,
            kind="answered" if answered else "missed",
        )
        biz = self.business_for(from_phone)
        item.business_id = biz.id if biz else None
        self.inbound_log.append(item)
        provider_id = f"SIMIN{no:05d}"
        if not answered:
            await self.sleep(ring_s)
            if self.bus:
                await self.bus.publish(
                    MissedCall(
                        provider=self.name,
                        provider_call_id=provider_id,
                        from_phone=from_phone,
                        to_phone=to_phone,
                        ring_seconds=ring_s,
                        reason="short_ring" if ring_s < 10 else "caller_hung_up",
                    )
                )
            return None
        agent: _Agent | None
        if biz is not None:
            agent = BusinessAgent(self, biz, no)
        else:
            agent = self.agent_for(from_phone, role="user") or UserAgent(self, self.default_user)
        req = OutboundCallRequest(
            to_phone=from_phone,
            task_id=f"inbound-{no}",
            metadata={"direction": "inbound", "from_number": to_phone},
        )
        leg = SimCallLeg(self, req, agent, call_no=no)
        leg.provider_call_id = provider_id
        leg.status = DialStatus.ANSWERED
        assert agent is not None
        agent.legs.append(leg)
        if isinstance(agent, BusinessAgent):
            agent.start_inbound()
        else:
            agent.start()
        self.legs.append(leg)
        call_id = provider_id
        self.inbound_legs[call_id] = leg
        if self.bus:
            await self.bus.publish(
                InboundCallReceived(
                    call_id=call_id,
                    provider=self.name,
                    provider_call_id=provider_id,
                    from_phone=from_phone,
                    to_phone=to_phone,
                    business_id=biz.id if biz else None,
                )
            )
        return call_id

    def take_inbound(self, call_id: str) -> SimCallLeg | None:
        return self.inbound_legs.pop(call_id, None)

    # ------------------------------------------------------------------ protocol
    async def place_call(self, request: OutboundCallRequest) -> SimCallLeg:
        agent = self.agent_for(request.to_phone, role=request.metadata.get("role"))
        if request.metadata.get("role") != "user":
            from_number = choose_from_number(request, self.friday_numbers, self.caller_id_selector)
            if from_number:
                request = request.model_copy(
                    update={"metadata": {**request.metadata, "from_number": from_number}}
                )
        leg = SimCallLeg(self, request, agent, call_no=self.next_call_no())
        self.legs.append(leg)
        log.info(
            "sim call %s -> %s (%s)",
            leg.provider_call_id,
            mask_phone(request.to_phone),
            agent.name if agent else "unknown number",
        )
        return leg


def build_simulated_telephony(c: Container) -> SimulatedTelephony:
    s: Settings = c.settings
    return SimulatedTelephony(
        world=load_world(),
        clock=c.clock,
        seed=s.sim_seed,
        answer_rate=s.sim_business_answer_rate,
        media_dir=s.media_dir,
        time_scale=getattr(s, "sim_time_scale", None),
        bus=c.bus,
        friday_numbers=getattr(s, "friday_numbers", None) or None,
    )
