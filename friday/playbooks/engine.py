"""The playbook engine: a ``CallPolicy`` that walks a playbook state machine.

The call runner (friday/voice/session.py) calls ``next_call_action`` after every reply, exactly
as it does for the LLM-driven brain. This policy:

* speaks ONLY lines from the playbook file (rendered with sanitised slots) - never model text;
* understands each reply with ``friday.playbooks.understand`` (heuristic first, one small
  structured model call only when the heuristic is not sure) into a CLOSED intent;
* looks the intent up in the current step's branches (then the defaults); anything unknown goes
  to the confusion branch ("Sorry, ek baar phir?", max 2 per step, then a polite UNCLEAR close);
* never confirms/books unless the brief delegates AND ``check_commit`` passes for the offer
  (the runner re-checks); otherwise the closing line says she will call back after approval;
* stops on do-not-call wording (checked in code, before and after any model), keeps to the
  duration/turn/repeat limits, and never speaks OTP/PIN/card words (the loader rejects them).
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import (
    AudioClass,
    CallAction,
    CallActionType,
    CallBrief,
    CallOutcome,
    Language,
    Quote,
    Speaker,
    Transcript,
    UserAnswer,
)
from friday.latency.speculative import Speculator
from friday.playbooks import classifier as clf
from friday.playbooks import slots as sl
from friday.playbooks.intents import ANY, FACT_INPUTS, QUESTION_INPUTS, RESUME_INPUTS, Intent
from friday.playbooks.model import (
    Action,
    LineRef,
    Playbook,
    get_playbook,
)
from friday.playbooks.understand import (
    HeuristicUnderstander,
    Understander,
    Understanding,
    asks_if_ai,
    ground,
    heuristic,
    is_stop_request,
)

log = get_logger(__name__)

_MAX_HOPS = 12
_SAFE_INPUT = re.compile(r"[^\w\s'.\-]", re.U)


def fill(template: str, value: Any) -> str:
    """Fill ``{slots}`` of a line; a line that starts with a slot starts with a capital."""
    out = re.sub(r"\{([a-z0-9_]+)\}", lambda m: value(m.group(1)), template)
    return out[:1].upper() + out[1:] if template.startswith("{") else out


_HINT_WORDS = {
    "men": ("men", "mens", "men's", "gents", "gent", "male", "boys", "boy", "man"),
    "women": ("women", "womens", "women's", "ladies", "lady", "female", "girls", "girl", "woman"),
    "kids": ("kids", "kid", "child", "children", "baby"),
}


def hints_of(c: Any) -> list[str]:
    """Words naming who the service is for ("men", "women", "kids"), from the task's own words;
    they pick the right price out of a price list."""
    text = " ".join(
        [c.brief.goal or "", c.inputs.get("service", ""), *c.brief.constraints]
    ).lower()
    out = []
    for canon, words in _HINT_WORDS.items():
        if any(re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", text) for w in words):
            out.append(canon)
    return out


class MissingSlot(KeyError):
    """A line needs a value the call has not collected."""


_YES_WORDS = frozenset({"yes", "true", "1", "haan", "y"})


def truthy(value: object) -> bool:
    """An input switched on ("yes"/"true"/"1"); anything else, or nothing, is off."""
    return str(value or "").strip().lower() in _YES_WORDS


def clean_input(value: object, limit: int = 40) -> str:
    """User-provided input values (name, service, date words) -> safe spoken text."""
    s = _SAFE_INPUT.sub("", str(value or "")).strip()
    s = re.sub(r"\s+", " ", s)[:limit]
    return s


def clean_spoken(value: object, limit: int = 60) -> str:
    """A spoken-form name (may be Devanagari): letters, marks, space, & - . only."""
    from friday.voice.names import sanitise

    return sanitise(str(value or ""), limit)


def first_name(name: str | None) -> str:
    n = clean_input(name or "", 30)
    return n.split(" ")[0] if n else ""


@dataclass
class CallState:
    step: str
    seen: int = 0
    started: bool = False
    finished: bool = False
    times: list[str] = field(default_factory=list)
    price_inr: int | None = None
    duration_min: int | None = None
    stylist: str | None = None
    advance_needed: str | None = None
    slot_free: str | None = None
    is_range: bool = False
    # vendor archetypes (all stay empty on a salon call)
    price_low: int | None = None  # lower end of a price range
    price_unit: str | None = None  # plate / kg / head / hour / ... (None = flat)
    deposit_inr: int | None = None  # information only, never agreed to
    estimate_inr: int | None = None  # rough job estimate (upper end)
    estimate_low: int | None = None
    suspects: list[int] = field(default_factory=list)  # prices outside the sane range
    notes: dict[str, str] = field(default_factory=dict)  # step.note: the vendor's own words
    flags: dict[str, str] = field(default_factory=dict)
    asked: Counter = field(default_factory=Counter)
    unclear: Counter = field(default_factory=Counter)
    visits: Counter = field(default_factory=Counter)
    uses: Counter = field(default_factory=Counter)
    path: list[str] = field(default_factory=list)
    turns: int = 0
    first_at: datetime | None = None
    after_hold: bool = False
    last_friday: str = ""
    said_norm: list[str] = field(default_factory=list)  # her recent lines (repeat guard)
    captured: str | None = None  # a number the business gave ("same" = the one we called)
    seeded: bool = False  # the carried-in answers of a retry call were applied
    prior_done: set[str] = field(default_factory=set)  # steps an earlier call completed
    entering: str = ""  # the step being entered (for the step_answered condition)
    acks: list[str] = field(default_factory=list)  # acknowledgements used so far (never repeat 2)
    last_was_commit: bool = False
    commit_blocked: bool = False
    commit_slot: str | None = None
    unhandled: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    llm_calls: int = 0
    repeats: int = 0
    outcome: str | None = None
    blocked: int = 0
    transcript: Any = None  # strong ref: keeps id(transcript) unique while the state lives
    speculator: Any = None  # friday.latency.speculative.Speculator (only with the switch on)


@dataclass
class Ctx:
    """What conditions and line rendering see on this turn."""

    pb: Playbook
    brief: CallBrief
    st: CallState
    inputs: dict[str, str]
    recording: bool
    now: datetime
    answers: list[UserAnswer]
    commit_ok: bool | None = None
    dyn_answer: str | None = None  # a grounded reply to an open question (playbooks/answerer.py)

    @property
    def slot_text(self) -> str:
        return sl.join_slots(self.st.times)

    def value(self, name: str) -> str:
        st = self.st
        if name in self.inputs and self.inputs[name]:
            return self.inputs[name]
        if name == "slot" and st.times:
            return self.slot_text
        if name == "vendor_price" and st.price_inr is not None:
            return str(st.price_inr)
        if name == "push2_price":
            t, m = _digits(self.inputs.get("target_price")), _digits(self.inputs.get("max_price"))
            if t and m:  # slightly higher than the first push, never above the user's maximum
                return str(min(m, max(t, int((t + m) / 2 / 100.0 + 0.5) * 100)))
            if t or m:
                return str(t or m)
        if name == "captured_number" and st.captured and st.captured != "same":
            return st.captured
        if name == "captured_spoken" and st.captured and st.captured != "same":
            d = st.captured
            return f"{' '.join(d[:5])}, {' '.join(d[5:])}"  # "9 8 1 1 1, 2 2 3 3 4"
        if name == "ack":
            from friday.playbooks.intents import ACK_POOL

            fresh = [a for a in ACK_POOL if a not in st.acks[-2:]]
            pick = random.choice(fresh or list(ACK_POOL))
            st.acks.append(pick)
            return pick
        if name == "slot_time" and st.times:  # the time without the day: "shaam 5 baje"
            return re.sub(r"^(aaj|kal|parso) ", "", st.times[0])
        if name == "price_inr" and st.price_inr is not None:
            return str(st.price_inr)
        if name == "duration_min" and st.duration_min is not None:
            return str(st.duration_min)
        if name == "stylist" and st.stylist:
            return st.stylist
        raise MissingSlot(name)


def resolve_inputs(pb: Playbook, brief: CallBrief) -> dict[str, str]:
    """Playbook inputs for this call: the brief's ``playbook_inputs`` (task data), defaults from
    the playbook, then facts the brief already has. Everything sanitised."""
    raw = dict(brief.playbook_inputs)
    out: dict[str, str] = {}
    for name, spec in pb.inputs.items():
        v = raw.get(name)
        if not v and spec.default:
            v = spec.default
        if name == "user_first_name" and not v:
            v = first_name(brief.on_behalf_of)
        if name == "budget" and not v and brief.budget and brief.budget.max_inr:
            v = str(brief.budget.max_inr)
        if name == "date_window" and not v and brief.preferred_times:
            v = brief.preferred_times[0]
        if name == "business_name" and (not v or v == spec.default):
            tn = (brief.target.name or "").strip()
            if tn and "test business" not in tn.lower():
                v = tn
        if name == "user_full_name" and not v:
            v = (brief.on_behalf_of or "").strip()
        if name == "for_whom" and not v and brief.beneficiary_name:
            v = first_name(brief.beneficiary_name)
        if name in ("services_spoken", "user_spoken", "business_name_spoken", "user_full_spoken"):
            continue  # derived below
        if name == "services":
            continue
        if name in RESUME_INPUTS:  # carried-in answers keep their ">" and JSON punctuation
            out[name] = "".join(ch for ch in str(v or "") if ch.isprintable())[:400]
            continue
        out[name] = first_name(v) if name == "user_first_name" else clean_input(v)
    if name := out.get("budget"):
        digits = re.sub(r"\D", "", name)
        out["budget"] = digits if digits else ""
    for key in (
        "price_min", "price_max", "estimate_max", "party_size", "target_price", "max_price",
    ):
        if key in out:
            out[key] = re.sub(r"\D", "", out[key])[:7]
    _derive_spoken(pb, brief, raw, out)
    return out


def _derive_spoken(pb: Playbook, brief: CallBrief, raw: dict[str, str], out: dict[str, str]) -> None:  # noqa: E501
    """Spoken forms (names in Devanagari, services joined), the effective mode and the fallback.
    Roman inputs stay as they are for logs; the ``*_spoken`` ones are what the voice reads. They
    come from the brief (worked out at task creation) or, failing that, from the offline speller
    (overrides + glossary): never from the network, never mid-call."""
    from friday.voice.names import default_speller, join_services, parse_services

    sp = default_speller()
    for src, dst in (
        ("user_first_name", "user_spoken"),
        ("business_name", "business_name_spoken"),
        ("user_full_name", "user_full_spoken"),
    ):
        if dst not in pb.inputs:
            continue
        given = clean_spoken(raw.get(dst))
        out[dst] = given or sp.spoken(out.get(src, "")) or out.get(src, "")
    if "services" in pb.inputs:
        items = parse_services(raw.get("services")) or parse_services(out.get("service"))
        items = [sp.spoken_service(x) for x in items]
        out["services"] = ", ".join(items)
        out["services_spoken"] = re.sub(r"[^\w\s,'.\-]", "", join_services(items))[:90].strip()
        if not out.get("service"):
            out["service"] = out["services_spoken"]
    # mode: "book" only with a delegation and a time to ask for; everything else is a price check
    want = (raw.get("playbook_mode") or "").strip().lower().replace("-", "_")
    book = want == "book" and brief.delegation.granted and bool(out.get("date_window"))
    out["playbook_mode"] = "book" if book else "quote_only"
    if want in ("negotiate", "confirm"):  # callbacks started by the user's decision (task layer)
        out["playbook_mode"] = want
    fb = clean_input(raw.get("fallback_when") or "")
    if fb and sl.requested_time(fb) and book:
        day = sl.find_day(fb) or "kal"
        out["fallback_when"] = fb
        out["fallback_day"] = day
    else:
        out["fallback_when"] = ""
        out["fallback_day"] = ""


def missing_inputs(pb: Playbook, inputs: dict[str, str]) -> list[str]:
    return [n for n, spec in pb.inputs.items() if spec.required and not inputs.get(n)]


def _digits(v: Any) -> int | None:
    d = re.sub(r"\D", "", str(v or ""))
    return int(d) if d else None


def _within(price: int | None, limit: Any) -> bool:
    """The price heard is at or below ``limit`` (False when either is unknown)."""
    lim = _digits(limit)
    return price is not None and lim is not None and price <= lim


def _seed_from_prior(st: CallState, inputs: dict[str, str]) -> None:
    """A retry call starts with what the earlier call already learned, so answered steps are
    skipped (``skip_when: [price_known]``) and never asked again."""
    if not truthy(inputs.get("resume")):
        return
    steps = [s for s in (inputs.get("prior_steps") or "").split(">") if s]
    st.prior_done = set(steps[:-1])  # the last one is where the call was cut: ask it again
    if (v := _digits(inputs.get("prior_price_inr"))) is not None:
        st.price_inr = v
    if (v := _digits(inputs.get("prior_estimate_inr"))) is not None:
        st.estimate_inr = v
    if inputs.get("prior_slot_free") in ("yes", "no", "other_time"):
        st.slot_free = inputs["prior_slot_free"]
    if inputs.get("prior_slot"):
        st.times = [t.strip() for t in inputs["prior_slot"].split(",") if t.strip()][:2]
    for field_name, target in (("prior_notes", st.notes), ("prior_flags", st.flags)):
        try:
            data = json.loads(inputs.get(field_name) or "{}")
        except ValueError:
            data = {}
        if isinstance(data, dict):
            target.update({str(k)[:30]: str(x)[:80] for k, x in data.items()})


def _learn(c: Ctx, u: Understanding | None, text: str, *, unhandled: bool = False) -> None:
    """Log what the business said for the founder's review queue (docs/LEARNING_AND_BUILD_PLAN.md).
    Never raises, never blocks a call. On by default (the founder records everything); off with
    FRIDAY_LEARNING=0 and during tests."""
    try:
        import os

        if os.environ.get("FRIDAY_LEARNING") == "0" or (
            "PYTEST_CURRENT_TEST" in os.environ and not os.environ.get("FRIDAY_LEARNING_LOG")
        ):
            return
        from friday.learning.log import record_turn

        if unhandled:  # the script had no branch for the last understood intent
            record_turn(
                call_id=c.brief.task_id, playbook_id=c.pb.id, step=c.st.step,
                text="", intent=c.st.intents[-1] if c.st.intents else "UNCLEAR",
                confident=False, unhandled=True,
            )
            return
        assert u is not None
        record_turn(
            call_id=c.brief.task_id, playbook_id=c.pb.id, step=c.st.step, text=text,
            intent=u.intent, confident=u.confident, repeat_count=c.st.repeats,
        )
    except Exception:  # noqa: BLE001 - learning must never break a call
        return


class PlaybookPolicy:
    """``CallPolicy`` for scripted calls. One instance serves any number of calls."""

    def __init__(
        self,
        *,
        understander: Understander | None = None,
        llm_mode: str = "auto",  # auto: model only when the heuristic is unsure | always | never
        recording: bool = False,
        clock: Any = None,
        playbooks: dict[str, Playbook] | None = None,
        answerer: Any = None,
        open_questions: bool = False,
        classifier: clf.IntentClassifier | None = None,
        classifier_threshold: float = clf.DEFAULT_THRESHOLD,
        speculative: bool = False,
    ) -> None:
        # latency switches (docs/LATENCY.md 2026-10-21), all OFF unless the caller passes them
        self.classifier = classifier
        self.classifier_threshold = classifier_threshold
        self.speculative = speculative
        self.stats: Counter[str] = Counter()
        self.answerer = answerer
        self.open_questions = open_questions  # founder switch: model-written open answers
        self.understander = understander or HeuristicUnderstander()
        self.llm_mode = llm_mode
        self.recording = recording
        self.clock = clock
        self._playbooks = playbooks or {}
        self.keep_finished = False  # dry runs read the finished state for scoring
        self._states: dict[int, CallState] = {}

    # ------------------------------------------------------------------ plumbing
    def playbook(self, brief: CallBrief) -> Playbook:
        name = brief.playbook or ""
        if name not in self._playbooks:
            self._playbooks[name] = get_playbook(name)
        return self._playbooks[name]

    def state_of(self, transcript: Transcript) -> CallState | None:
        return self._states.get(id(transcript))

    def _state(self, pb: Playbook, transcript: Transcript) -> CallState:
        key = id(transcript)
        st = self._states.get(key)
        if st is None:
            for k in [k for k, v in self._states.items() if v.finished and not self.keep_finished]:
                del self._states[k]  # tidy: finished calls are not needed any more
            st = CallState(step=pb.start, transcript=transcript)
            self._states[key] = st
        return st

    def fixed_lines(self, brief: CallBrief) -> dict[Language, list[str]]:
        """Fixed lines to pre-render through the TTS cache while the phone rings."""
        if not brief.playbook:
            return {}
        pb = self.playbook(brief)
        return {Language.HINGLISH: static_utterances(pb, resolve_inputs(pb, brief))}

    # ------------------------------------------------------------------ conditions
    def _cond(self, name: str, c: Ctx) -> bool:
        neg = name.startswith("!")
        key = name.lstrip("!")
        st = c.st
        price, budget = st.price_inr, c.inputs.get("budget")
        if key.startswith("has_") and key[4:] in FACT_INPUTS:
            return (not bool(c.inputs.get(key[4:]))) if neg else bool(c.inputs.get(key[4:]))
        val = {
            # founder 13 Oct: calls are recorded but it is never announced on the call
            "recording": False,
            "has_budget": bool(budget),
            "over_budget": bool(price is not None and budget and price > int(budget)),
            # asking for a discount needs an EXPLICIT owner instruction (input negotiate: yes);
            # the brief's NegotiationPolicy alone (its default is "enabled") is not enough
            "may_negotiate": bool(
                truthy(c.inputs.get("negotiate"))
                and budget
                and c.brief.negotiation.enabled
                and c.brief.negotiation.may_ask_discount
            ),
            "explore_options": truthy(c.inputs.get("explore_options")),
            "has_requested_time": self._requested(c) is not None,
            "has_stylist_pref": bool(c.inputs.get("stylist_pref")),
            "time_known": len(st.times) == 1,
            "slot_known": len(st.times) >= 1,
            "price_known": price is not None or st.flags.get("price_free") == "yes",
            "duration_known": st.duration_min is not None,
            "is_range": st.is_range,
            "has_offered": len(st.times) >= 2,
            "can_commit": self._can_commit(c) if key == "can_commit" else False,
            "first_ask": st.asked[st.step] == 0,
            "mode_book": c.inputs.get("playbook_mode") == "book",
            "mode_quote": c.inputs.get("playbook_mode") not in ("book", "negotiate", "confirm"),
            "mode_negotiate": c.inputs.get("playbook_mode") == "negotiate",
            "mode_confirm": c.inputs.get("playbook_mode") == "confirm",
            "has_fallback": self._fallback(c) is not None,
            "price_le_target": _within(price, c.inputs.get("target_price")),
            "price_le_max": _within(price, c.inputs.get("max_price")),
            "is_resume": truthy(c.inputs.get("resume")),
            "step_answered": bool(st.entering) and st.entering in st.prior_done,
            "used_fallback": st.flags.get("fallback_used") == "yes",
            "alt_offered": st.flags.get("alt_offered") == "yes",
            "has_date_window": bool(c.inputs.get("date_window")),
            "has_duration": bool(c.inputs.get("duration_text")),
            "available": st.slot_free in ("yes", "other_time")
            or st.flags.get("slot_free") == "yes",
            "estimate_known": st.estimate_inr is not None,
            "price_suspect": bool(st.suspects),
            "price_free": st.flags.get("price_free") == "yes",
            **{q: truthy(c.inputs.get(q)) for q in QUESTION_INPUTS},
        }[key]
        return (not val) if neg else bool(val)

    def _requested(self, c: Ctx) -> str | None:
        """The one specific time the task already names (None if it only names a part of day)."""
        t = sl.requested_time(c.inputs.get("date_window"))
        return sl.with_day(t, sl.find_day(c.inputs.get("date_window", ""))) if t else None

    def _fallback(self, c: Ctx) -> str | None:
        """The second specific time the task names ("kal shaam 5 baje"), if any."""
        fb = c.inputs.get("fallback_when")
        t = sl.requested_time(fb) if fb else None
        return sl.with_day(t, sl.find_day(fb) or "kal") if t else None

    def _all(self, conds: list[str], c: Ctx) -> bool:
        return all(self._cond(x, c) for x in conds)

    def _can_commit(self, c: Ctx) -> bool:
        """Delegated booking: the user's delegation, the offer and the code-level commit check."""
        if c.commit_ok is not None:
            return c.commit_ok
        c.commit_ok = False
        st, b = c.st, c.brief
        if st.commit_blocked or not b.delegation.granted or not st.times:
            return False
        # a restaurant table has no price to agree: only the slot (and, via the delegation, no
        # price ceiling) is checked; every other archetype needs a known price
        needs_price = c.pb.archetype != "table_booking" or truthy(c.inputs.get("q_price"))
        if (
            (needs_price and st.price_inr is None)
            or st.advance_needed == "yes"
            or st.flags.get("price_unknown")
        ):
            return False
        budget = c.inputs.get("budget")
        if budget and st.price_inr is not None and st.price_inr > int(budget):
            return False
        from friday.voice.commit import commit_reasons

        for t in st.times[:2]:
            slot_at = sl.resolve_slot_at(t, now=c.now, window_start=b.window_start)
            probe = CallAction(
                type=CallActionType.HANGUP,
                commits_booking=True,
                slot_at=slot_at,
                collected={} if st.price_inr is not None else {"decision": "slot"},
                quote=Quote(
                    business_name=b.target.name,
                    amount_inr=st.price_inr,
                    price_text=f"Rs {st.price_inr}",
                ),
            )
            if not commit_reasons(b, c.answers, probe):
                st.commit_slot = t
                st.times = [t]
                c.commit_ok = True
                return True
        return False

    # ------------------------------------------------------------------ rendering
    def _render(self, pb: Playbook, line_id: str, c: Ctx) -> str:
        if line_id == "offscript" and c.dyn_answer:  # grounded, validated reply
            return c.dyn_answer
        return fill(pb.text(line_id), c.value)

    def _lines(self, pb: Playbook, items: list[str | LineRef], c: Ctx) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for it in items:
            lid, when = (it, []) if isinstance(it, str) else (it.line, it.when)
            if when and not self._all(when, c):
                continue
            try:
                out.append((lid, self._render(pb, lid, c)))
            except MissingSlot as e:
                log.warning("playbook line %s skipped: missing %s", lid, e)
        return out

    # ------------------------------------------------------------------ main entry
    async def next_call_action(
        self, brief: CallBrief, transcript: Transcript, answers: list[UserAnswer] | Any
    ) -> CallAction:
        try:
            return await self._next_call_action(brief, transcript, answers)
        finally:  # a leftover guess from this turn must not leak into the next
            st = self._states.get(id(transcript))
            if st is not None and st.speculator is not None:
                st.speculator.end_turn()

    async def _next_call_action(
        self, brief: CallBrief, transcript: Transcript, answers: list[UserAnswer] | Any
    ) -> CallAction:
        pb = self.playbook(brief)
        st = self._state(pb, transcript)
        turns = transcript.turns
        new = turns[st.seen :]
        st.seen = len(turns)
        now = (
            turns[-1].at
            if turns
            else (self.clock.now() if self.clock else datetime.now().astimezone())
        )
        if st.first_at is None and turns:
            st.first_at = turns[0].at
        inputs = resolve_inputs(pb, brief)
        c = Ctx(pb, brief, st, inputs, self.recording, now, list(answers))
        if not st.seeded:
            st.seeded = True
            _seed_from_prior(st, inputs)

        # ---- system events since the last turn
        for t in new:
            if t.speaker == Speaker.SYSTEM and t.text.startswith("CALLEE HUNG UP"):
                return self._hung_up(c)
        blocked = [t for t in new if t.speaker == Speaker.SYSTEM and t.text.startswith("BLOCKED")]
        if blocked:
            st.blocked += len(blocked)
            return self._after_block(c)
        if st.finished:  # the runner asked again after we ended: just hang up
            od = pb.outcomes.get(st.outcome or "", pb.outcomes[pb.confusion.outcome])
            return CallAction(
                type=CallActionType.HANGUP,
                outcome=CallOutcome(od.call_outcome),
                collected=self._collected(c),
            )

        # ---- AI disclosure must already have been spoken (the runner does it, in code)
        if not any(t.speaker == Speaker.FRIDAY for t in turns):
            return CallAction(type=CallActionType.WAIT)

        reply_turn = next(
            (t for t in reversed(new) if t.speaker == Speaker.CALLEE), None
        )
        silent = reply_turn is None and any(
            t.speaker == Speaker.SYSTEM and t.text.startswith("SILENCE") for t in new
        )
        if reply_turn is not None and reply_turn.audio_class not in (None, AudioClass.HUMAN):
            return self._hold_action(pb, hold_s=pb.limits.hold_max_s, st=st)

        # ---- limits
        limit = self._limit_hit(c, turns)
        if limit:
            return self._finish_now(c)

        # ---- first turn: the step after the runner's disclosure
        if not st.started:
            st.started = True
            st.last_friday = next(
                (t.text for t in reversed(turns) if t.speaker == Speaker.FRIDAY), ""
            )
            return self._enter(c, pb.start, say=[])

        if reply_turn is None and not silent:
            return CallAction(type=CallActionType.WAIT)

        st.turns += 1
        if silent or not (reply_turn and reply_turn.text.strip()):
            u = Understanding(intent=Intent.UNCLEAR.value, confident=True)
        else:
            u = await self._understand(c, reply_turn.text)
        st.intents.append(u.intent)
        if reply_turn is not None and reply_turn.text.strip():
            _learn(c, u, reply_turn.text)
        if (
            self.open_questions
            and self.answerer is not None
            and u.intent == Intent.ASKS_OFFTOPIC.value
            and reply_turn is not None
        ):
            c.dyn_answer = await self._open_answer(c, reply_turn.text)
        return self._apply(c, u, reply_turn.text if reply_turn else "")

    def _facts(self, c: Ctx) -> dict[str, Any]:
        """What Friday may say about this request (and nothing else)."""
        i = c.inputs
        spoken = lambda k, fb: i.get(k + "_spoken") or i.get(fb) or ""  # noqa: E731
        facts: dict[str, Any] = {
            "I_am": "Friday, a virtual assistant calling on behalf of the user",
            "user": spoken("user", "user_first_name"),
            "honorific": i.get("honorific") or "sir",
            "business_called": spoken("business_name", "business_name"),
            "user_wants": i.get("services") or i.get("service") or "",
            "mode": i.get("playbook_mode") or "quote_only",
            "why_calling": "to ask the charges"
            + (" and a slot" if (i.get("playbook_mode") == "book") else "")
            + " for the user",
        }
        for key, label in (("date_window", "wanted_when"), ("for_whom", "for_whom"),
                           ("party_size", "party_size"), ("duration_text", "for_how_long")):
            if i.get(key):
                facts[label] = i[key]
        st = c.st
        if st.price_inr is not None:
            facts["price_already_heard_rs"] = st.price_inr
        if st.times:
            facts["slot_already_heard"] = sl.join_slots(st.times)
        return facts

    async def _open_answer(self, c: Ctx, reply: str) -> str | None:
        try:
            return await self.answerer.answer(
                question=reply, friday_said=c.st.last_friday, facts=self._facts(c),
                task_id=c.brief.task_id,
            )
        except Exception as e:  # noqa: BLE001 - the canned line is always there
            log.warning("open-question answer failed (%s); using the canned line", type(e).__name__)
            return None

    # ------------------------------------------------------------------ understanding
    def _allowed(self, pb: Playbook, step_id: str) -> list[str]:
        s = pb.steps[step_id]
        keys = {k for k in s.branches if k != ANY} | set(pb.defaults)
        return sorted(keys | {Intent.UNCLEAR.value})

    async def _understand(self, c: Ctx, reply: str) -> Understanding:
        u = await self._understand_raw(c, reply)
        if (
            c.pb.ai_disclosure == "on_request"
            and u.intent not in (Intent.STOP_CALLING.value, Intent.RUDE.value)
            and asks_if_ai(reply)
        ):  # hard rule: anything that looks like "are you an AI?" is answered, whatever the model said  # noqa: E501
            return Understanding(intent=Intent.ARE_YOU_BOT.value, confident=True)
        return u

    def _ai_line(self, c: Ctx) -> str:
        """The truthful answer to 'are you an AI?' (the first line of defaults.ARE_YOU_BOT)."""
        for a in c.pb.actions(c.pb.defaults.get("ARE_YOU_BOT", [])):
            for it in a.say:
                lid = it if isinstance(it, str) else it.line
                if lid not in c.pb.lines or not re.search(r"\bAI\b", c.pb.text(lid)):
                    continue
                try:
                    return self._render(c.pb, lid, c)
                except MissingSlot:
                    continue
        return "Haan ji, main AI assistant hoon."

    def _ensure_ai(self, c: Ctx, action: CallAction) -> CallAction:
        """on_request guarantee, in code: the reply to an 'are you an AI?' question says AI."""
        if action.text and re.search(r"\bAI\b", action.text):
            return action
        ai = self._ai_line(c)
        if action.type in (CallActionType.SAY, CallActionType.HANGUP):
            text = f"{ai} {action.text}".strip() if action.text else ai
            c.st.last_friday = text
            return action.model_copy(update={"text": text, "language": Language.HINGLISH})
        c.st.last_friday = ai
        return self._say(c, ai)

    async def _understand_raw(self, c: Ctx, reply: str) -> Understanding:
        st, pb = c.st, c.pb
        if is_stop_request(reply):  # hard rule: no model needed, none trusted
            self._end_speculation(c)
            return Understanding(intent=Intent.STOP_CALLING.value, confident=True)
        ext = self._ext_known(pb, st.step)
        h = heuristic(reply, step=st.step, known={"hints": hints_of(c), **ext})
        use_llm = self.llm_mode == "always" or (self.llm_mode == "auto" and not h.confident)
        if self.llm_mode == "never" or not use_llm:
            self._end_speculation(c)
            return h
        said = self._classify(c, reply, h)
        if said is not None:  # the small trained classifier is sure: no model call
            self._end_speculation(c)
            return said
        try:
            u = await self._model_understanding(c, reply, ext)
            st.llm_calls += 1
        except Exception as e:  # noqa: BLE001 - never stall a call on a model failure
            log.warning("playbook understand failed (%s); using the heuristic", type(e).__name__)
            return h
        if is_stop_request(reply):
            return Understanding(intent=Intent.STOP_CALLING.value, confident=True)
        u = ground(u.normalised(), reply)  # nothing the vendor did not say survives
        if u.intent == Intent.UNCLEAR.value and h.intent != Intent.UNCLEAR.value and h.confident:
            return h
        return u

    # ------------------------------------------------------------------ model call (+ speculation)
    def _model_args(self, c: Ctx, reply: str, ext: dict[str, Any]) -> dict[str, Any]:
        """Everything the understander is asked, captured NOW (a speculative call must not read
        call state later)."""
        st = c.st
        return {
            "reply": reply,
            "friday_said": st.last_friday,
            "step": st.step,
            "allowed": self._allowed(c.pb, st.step),
            "known": {"slot": c.slot_text, "price_inr": st.price_inr, "hints": hints_of(c), **ext},
            "task_id": c.brief.task_id,
        }

    async def _model_understanding(
        self, c: Ctx, reply: str, ext: dict[str, Any]
    ) -> Understanding:
        sp = c.st.speculator
        if sp is not None:
            got, _how = await sp.take(self._spec_key(c), reply)
            if got is not None:  # the guess made while she was still talking is for these words
                self.stats["speculative_hit"] += 1
                return got  # type: ignore[no-any-return]
            self.stats["speculative_miss" if _how == "miss" else "speculative_none"] += 1
        return await self.understander.understand(**self._model_args(c, reply, ext))

    @staticmethod
    def _spec_key(c: Ctx) -> tuple[str, str]:
        return (c.st.step, c.st.last_friday)

    def _classify(
        self, c: Ctx, reply: str, h: Understanding, *, record: bool = True
    ) -> Understanding | None:
        """The trained classifier's answer, or None (take the model path). Only when the rules are
        not confident; the hard rules (stop, secrets, rude, AI question) already ran."""
        if self.classifier is None or h.confident:
            return None
        d = clf.decide(
            reply, self.classifier, self.classifier_threshold, self._allowed(c.pb, c.st.step)
        )
        if record:
            self.stats["classifier_hit" if d.used else "classifier_miss"] += 1
            if d.used:
                log.info("classifier hit %s conf=%.3f (no model call)", d.intent, d.confidence)
            else:
                log.info("classifier miss %s conf=%.3f (%s); rules + model path",
                         d.intent, d.confidence, d.reason)
        if not d.used:
            return None
        return Understanding(intent=d.intent, confident=True)

    def speculate(self, brief: CallBrief, transcript: Transcript, text: str) -> bool:
        """Start understanding ``text`` (an early / stable transcript) while the caller's pause is
        still being timed out. Pure: it changes no call state and speaks nothing; the result is
        used only if the committed words are the same (``_model_understanding``). False when the
        switch is off, the rules / classifier already know, or this turn already guessed once."""
        if not self.speculative or self.llm_mode == "never":
            return False
        st = self._states.get(id(transcript))
        text = (text or "").strip()
        if st is None or not (st.started and st.seeded) or st.finished or not text:
            return False
        pb = self.playbook(brief)
        if st.step not in pb.steps or is_stop_request(text):
            return False
        now = self.clock.now() if self.clock else datetime.now().astimezone()
        c = Ctx(pb, brief, st, resolve_inputs(pb, brief), self.recording, now, [])
        ext = self._ext_known(pb, st.step)
        h = heuristic(text, step=st.step, known={"hints": hints_of(c), **ext})
        if h.confident and self.llm_mode != "always":
            return False  # rules are sure: there is nothing to start
        if self._classify(c, text, h, record=False) is not None:
            return False  # the classifier will answer: no model call to start
        if st.speculator is None:
            st.speculator = Speculator()
        args = self._model_args(c, text, ext)
        started = st.speculator.start(
            self._spec_key(c), text, lambda: self.understander.understand(**args)
        )
        if started:
            self.stats["speculative_started"] += 1
        return started

    def cancel_speculation(
        self, transcript: Transcript, reason: str = "caller kept talking"
    ) -> bool:
        st = self._states.get(id(transcript))
        sp = st.speculator if st is not None else None
        return bool(sp is not None and sp.cancel(reason))

    @staticmethod
    def _end_speculation(c: Ctx) -> None:
        sp = c.st.speculator
        if sp is not None:
            sp.end_turn()

    @staticmethod
    def _price_step(pb: Playbook, step_id: str) -> bool:
        """Does this step take a price? (An archetype never stores a price heard elsewhere:
        a delivery charge is not the product's price.)"""
        return bool(
            set(pb.steps[step_id].branches) & {Intent.GIVES_PRICE.value, Intent.PRICE_RANGE.value}
        )

    @staticmethod
    def _ext_known(pb: Playbook, step_id: str) -> dict[str, Any]:
        """What the extended (archetype) understanding needs to know about this step."""
        if not pb.archetype:
            return {}
        s = pb.steps[step_id]
        allowed = {k for k in s.branches if k != ANY} | set(pb.defaults)
        return {
            "extended": True,
            "archetype": pb.archetype,
            "allowed": sorted(allowed),
            "price_step": bool(allowed & {Intent.GIVES_PRICE.value, Intent.PRICE_RANGE.value}),
        }

    # ------------------------------------------------------------------ applying an intent
    def _sane(self, c: Ctx | None, price: int, *, estimate: bool) -> bool:
        """Is this price inside the category's sane range? Without a range it always is. The same
        out-of-range price heard twice is believed (a pricey place is not an absurd parse)."""
        if c is None:
            return True
        st = c.st
        lo_raw = "" if estimate else c.inputs.get("price_min", "")
        hi_raw = c.inputs.get("estimate_max" if estimate else "price_max", "")
        lo = int(lo_raw) if lo_raw.isdigit() else 0
        hi = int(hi_raw) if hi_raw.isdigit() else 0
        if price >= lo and (not hi or price <= hi):
            return True
        if price in st.suspects:
            st.flags["price_unusual"] = "yes"
            return True
        st.suspects.append(price)
        return False

    def _merge_slots(
        self, st: CallState, u: Understanding, day: str | None = None, c: Ctx | None = None
    ) -> None:
        intent = u.intent
        if intent in (Intent.SLOT_FREE, Intent.GIVES_TIME, Intent.OFFERS_SLOTS) or (
            intent == Intent.NEEDS_ADVANCE and u.time
        ):
            times = [t for t in [u.time, *u.alt_times] if t][:2]
            if times:
                st.times = [sl.with_day(t, day) for t in times]
            if intent == Intent.SLOT_FREE:
                st.slot_free = "yes"
            elif intent == Intent.OFFERS_SLOTS:
                st.slot_free = "other_time"
        elif intent == Intent.SLOT_BUSY:
            st.slot_free = "no"
        elif intent == Intent.GIVES_NUMBER and u.phone:
            st.captured = u.phone
            from friday.core.safety import allow_spoken_number

            allow_spoken_number(u.phone)  # she may read back the number they just gave
        elif intent == Intent.SAME_NUMBER:
            st.captured = "same"
        if intent in (Intent.GIVES_PRICE, Intent.PRICE_RANGE) and (
            c is None or not c.pb.archetype or self._price_step(c.pb, st.step)
        ):
            estimate = c is not None and c.pb.steps[st.step].captures == "estimate"
            if u.price_inr is not None and estimate:
                if self._sane(c, u.price_inr, estimate=True):
                    st.estimate_inr = u.price_inr
                    st.estimate_low = u.price_low_inr if intent == Intent.PRICE_RANGE else None
            elif u.price_inr is not None and self._sane(c, u.price_inr, estimate=False):
                st.price_inr = u.price_inr
                st.is_range = intent == Intent.PRICE_RANGE
                if c is not None and c.pb.archetype:
                    st.price_low = u.price_low_inr if intent == Intent.PRICE_RANGE else None
                    st.price_unit = u.price_unit
                    st.suspects.clear()
            if u.duration_min is not None:
                st.duration_min = u.duration_min
            if c is not None and c.pb.archetype:  # a deposit next to the rate: information only
                if u.advance_needed:
                    st.advance_needed = "yes"
                if u.deposit_inr is not None:
                    st.deposit_inr = u.deposit_inr
        if intent == Intent.GIVES_STYLIST and u.stylist:
            st.stylist = u.stylist
        if intent == Intent.NEEDS_ADVANCE:
            st.advance_needed = "yes"
            if c is not None and c.pb.archetype and u.deposit_inr is not None:
                st.deposit_inr = u.deposit_inr
        elif intent == Intent.NO_ADVANCE:
            st.advance_needed = "no"

    def _pick(self, pb: Playbook, step_id: str, intent: str, c: Ctx) -> tuple[Action | None, str]:
        """The action for (step, intent): step branch, then defaults, then ANY. Returns
        (action, key) with ``key`` identifying the branch for ``max_uses``."""
        step = pb.steps[step_id]
        candidates: list[tuple[str, Any]] = []
        if intent in step.branches:
            candidates.append((f"{step_id}.{intent}", step.branches[intent]))
        if intent in pb.defaults:
            candidates.append((f"defaults.{intent}", pb.defaults[intent]))
        if intent != Intent.UNCLEAR.value and ANY in step.branches:
            candidates.append((f"{step_id}.{ANY}", step.branches[ANY]))
        for key, acts in candidates:
            options = pb.actions(acts)
            for i, a in enumerate(options):
                if a.when and not self._all(a.when, c):
                    continue
                # each option of a list counts on its own, but only for options that ask for it
                akey = key if i == 0 or not a.when else f"{key}#{i}"
                if a.max_uses is not None and c.st.uses[akey] >= a.max_uses:
                    continue  # this option is used up: the next option, then the next candidate
                return a, akey
        return None, ""

    def _apply(self, c: Ctx, u: Understanding, reply: str) -> CallAction:
        action = self._apply_intent(c, u, reply)
        if c.pb.ai_disclosure == "on_request" and u.intent == Intent.ARE_YOU_BOT.value:
            action = self._ensure_ai(c, action)
        return action

    def _apply_intent(self, c: Ctx, u: Understanding, reply: str) -> CallAction:
        pb, st = c.pb, c.st
        day_key = pb.steps[st.step].day_input or "date_window"
        self._merge_slots(st, u, day=sl.find_day(c.inputs.get(day_key, "")), c=c)
        intent = u.intent
        self._note(c, intent, reply)
        if (intent == Intent.SLOT_FREE or (intent == Intent.NEEDS_ADVANCE and u.slot_free)) and (
            not st.times
        ):
            self._take_requested(c)  # "ho jayega" to a question that named the time
        if st.after_hold:
            st.after_hold = False
            if intent in (  # she is back ("haan boliye", "kya poochh rahi thi?"): ask again
                Intent.CONTINUE, Intent.YES, Intent.ACK, Intent.ASKS_OFFTOPIC,
                Intent.WHO_IS_THIS, Intent.UNCLEAR,
            ):
                return self._reask(c, say=[])
        action, key = self._pick(pb, st.step, intent, c)
        if action is None:
            if intent != Intent.UNCLEAR.value:
                st.unhandled.append(f"{st.step}:{intent}")
                _learn(c, None, "", unhandled=True)
            return self._confusion(c)
        st.uses[key] += 1
        return self._run(c, action)

    _NOT_INFORMATIVE = frozenset(
        {
            Intent.ASKS_REPEAT, Intent.HOLD_ON, Intent.WHO_IS_THIS,
            Intent.ARE_YOU_BOT, Intent.ACK, Intent.CONTINUE, Intent.RUDE, Intent.STOP_CALLING,
            Intent.WRONG_NUMBER, Intent.BUSY_LATER, Intent.ASKS_OFFTOPIC, Intent.ASKS_SECRET,
            Intent.ASKS_CUSTOMER_PHONE, Intent.YES, Intent.NO,
        }
    )

    def _note(self, c: Ctx, intent: str, reply: str) -> None:
        """A step with ``note:`` keeps the vendor's own words (never spoken, only reported)."""
        key = c.pb.steps[c.st.step].note
        if not key or intent in self._NOT_INFORMATIVE or not reply.strip():
            return
        text = re.sub(r"\d{7,}", "", clean_input(reply, 80))
        if re.search(r"[A-Za-z]{3}|\d", text):
            c.st.notes[key] = re.sub(r"\s+", " ", text).strip()

    def _take_requested(self, c: Ctx) -> None:
        """She said yes to the time we asked for: that time is the slot (never invented)."""
        fallback_step = c.pb.steps[c.st.step].day_input == "fallback_when"
        req = self._fallback(c) if fallback_step else self._requested(c)
        if req and not c.st.times:
            c.st.times = [req]
            c.st.slot_free = "yes"
            if fallback_step:
                c.st.flags["fallback_used"] = "yes"

    def _run(self, c: Ctx, a: Action) -> CallAction:
        pb, st = c.pb, c.st
        st.flags.update({k: v for k, v in a.set.items()})
        if a.use_requested_time:
            self._take_requested(c)
        if a.use_fallback_time:
            fb = self._fallback(c)
            if fb:
                st.times = [fb]
                st.slot_free = "yes"
                st.flags["fallback_used"] = "yes"
        say = self._lines(pb, a.say, c)
        if a.hold_s is not None:
            st.after_hold = True
            return self._hold_action(pb, hold_s=a.hold_s, st=st)
        if a.outcome:
            return self._end(c, a.outcome, say, commit=a.commit)
        if a.stay:
            return self._speak(c, say, step=st.step, count_ask=True)
        if a.repeat:
            return self._reask(c, say=say)
        if a.goto:
            return self._goto(c, a.goto, say)
        return self._confusion(c)

    def _goto(self, c: Ctx, target: str, say: list[tuple[str, str]]) -> CallAction:
        pb = c.pb
        for _ in range(_MAX_HOPS):
            if target.startswith("@"):
                route = pb.routes[target[1:]]
                act = next((x for x in route if not x.when or self._all(x.when, c)), None)
                if act is None:
                    return self._confusion(c)
                say = say + self._lines(pb, act.say, c)
                c.st.flags.update(act.set)
                if act.outcome:
                    return self._end(c, act.outcome, say, commit=act.commit)
                if not act.goto:
                    return self._confusion(c)
                target = act.goto
                continue
            return self._enter(c, target, say)
        return self._confusion(c)

    def _enter(self, c: Ctx, step_id: str, say: list[tuple[str, str]]) -> CallAction:
        pb, st = c.pb, c.st
        for _ in range(_MAX_HOPS):
            step = pb.steps[step_id]
            st.entering = step_id
            st.visits[step_id] += 1
            over = step.max_visits is not None and st.visits[step_id] > step.max_visits
            if over or (step.skip_when and self._all(step.skip_when, c)):
                act, _key = self._pick_any(pb, step_id, c)
                if act is None:
                    return self._confusion(c)
                say = say + self._lines(pb, act.say, c)
                st.flags.update(act.set)
                if act.outcome:
                    return self._end(c, act.outcome, say, commit=act.commit)
                if act.goto:
                    if act.goto.startswith("@"):
                        return self._goto(c, act.goto, say)
                    step_id = act.goto
                    continue
                return self._confusion(c)
            if step.final:
                act, _key = self._pick_any(pb, step_id, c)
                if act is None:
                    return self._confusion(c)
                say = say + self._lines(pb, act.say, c)
                st.step = step_id
                st.path.append(step_id)
                st.flags.update(act.set)
                return self._end(c, act.outcome or pb.confusion.outcome, say, commit=act.commit)
            st.step = step_id
            st.path.append(step_id)
            return self._speak(c, say, step=step_id, ask=True)
        return self._confusion(c)

    def _pick_any(self, pb: Playbook, step_id: str, c: Ctx) -> tuple[Action | None, str]:
        for a in pb.actions(pb.steps[step_id].branches[ANY]):
            if not a.when or self._all(a.when, c):
                c.st.uses[f"{step_id}.{ANY}"] += 1
                return a, f"{step_id}.{ANY}"
        return None, ""

    def _reask(self, c: Ctx, say: list[tuple[str, str]]) -> CallAction:
        c.st.repeats += 1
        return self._speak(c, say, step=c.st.step, ask=True)

    def _speak(
        self,
        c: Ctx,
        say: list[tuple[str, str]],
        *,
        step: str,
        ask: bool = False,
        count_ask: bool = False,
    ) -> CallAction:
        pb, st = c.pb, c.st
        parts = [t for _l, t in say]
        if ask and not parts and not pb.steps[step].ask:
            return CallAction(type=CallActionType.WAIT)  # nothing to ask here: wait for her answer
        if ask:
            parts += [t for _l, t in self._lines(pb, pb.steps[step].ask, c)]
        if ask or count_ask:
            st.asked[step] += 1
            if st.asked[step] > pb.limits.max_repeats:
                return self._end(c, pb.confusion.outcome, [], gave_up=True)
        text = " ".join(p for p in parts if p).strip()
        if not text:
            return self._confusion(c)
        st.last_friday = text
        st.last_was_commit = False
        return self._say(c, text)

    def _confusion(self, c: Ctx) -> CallAction:
        pb, st = c.pb, c.st
        st.unclear[st.step] += 1
        if st.unclear[st.step] > pb.limits.max_unclear_per_step:
            return self._end(c, pb.confusion.outcome, [], gave_up=True)
        line = self._lines(pb, [pb.confusion.line], c)
        text = line[0][1] if line else ""
        st.last_friday = text
        return self._say(c, text)

    # ------------------------------------------------------------------ results
    @staticmethod
    def _norm_line(text: str) -> str:
        return re.sub(r"\W+", " ", (text or "").lower()).strip()

    def _say(self, c: Ctx, text: str) -> CallAction:
        """Every spoken line goes through here: Friday never says the same line over and over.
        The same line twice in a row is allowed once (the vendor asked her to repeat or did not
        hear); a third time (or the same line 3 times in the last 6) ends the call politely."""
        st, pb = c.st, c.pb
        n = self._norm_line(text)
        recent = st.said_norm[-6:]
        run = 0
        for prev in reversed(st.said_norm):
            if prev != n:
                break
            run += 1
        # "are you a bot?" is a fresh question, so asking again afterwards is fair
        asked_ai = bool(st.intents) and st.intents[-1] == "ARE_YOU_BOT"
        if n and (run >= 2 or recent.count(n) >= 3) and not st.finished and not asked_ai:
            log.info("repeat guard: ending instead of saying the same line again (%s)", n[:40])
            st.flags["repeat_guard"] = "yes"
            return self._end(c, pb.confusion.outcome, [], gave_up=True)
        st.said_norm.append(n)
        return CallAction(
            type=CallActionType.SAY,
            text=text,
            language=Language.HINGLISH,
            collected=self._collected(c),
            quote=self._quote(c),
        )

    def _hold_action(self, pb: Playbook, *, hold_s: int, st: CallState) -> CallAction:
        st.after_hold = True
        return CallAction(
            type=CallActionType.WAIT_ON_HOLD,
            max_hold_s=hold_s,
            language=Language.HINGLISH,
        )

    def _end(
        self,
        c: Ctx,
        outcome_id: str,
        say: list[tuple[str, str]],
        *,
        commit: bool = False,
        gave_up: bool = False,
    ) -> CallAction:
        pb, st = c.pb, c.st
        if gave_up and pb.confusion.close:
            say = self._lines(pb, [pb.confusion.close], c)
        if commit and not self._can_commit(c):  # the code gate says no: close as a call-back
            st.commit_blocked = True
            return self._enter(c, pb.commit_step or pb.start, [])
        if outcome_id == "SLOT_OFFERED" and not st.times:
            outcome_id = pb.confusion.outcome
        od = pb.outcomes[outcome_id]
        st.finished = True
        st.outcome = outcome_id
        text = " ".join(t for _l, t in say).strip() or None
        st.last_friday = text or ""
        st.last_was_commit = commit
        collected = self._collected(c)
        collected["outcome"] = outcome_id
        collected.update(od.collected)
        quote = self._quote(c) if od.needs_quote else None
        slot_at = None
        if commit and st.times:
            slot_at = sl.resolve_slot_at(st.times[0], now=c.now, window_start=c.brief.window_start)
            collected["slot_at"] = slot_at.isoformat() if slot_at else ""
            collected["decision"] = "slot,price" if st.price_inr is not None else "slot"
        return CallAction(
            type=CallActionType.HANGUP,
            text=text,
            language=Language.HINGLISH,
            outcome=CallOutcome(od.call_outcome),
            collected=collected,
            quote=quote,
            commits_booking=commit,
            slot_at=slot_at,
        )

    def _collected(self, c: Ctx) -> dict[str, str]:
        st = c.st
        out: dict[str, str] = {"playbook": c.pb.id, "steps": ">".join(st.path)}
        if st.slot_free:
            out["slot_free"] = st.slot_free
        if st.times:
            out["slot"] = sl.join_slots(st.times)
            out["offered_slots"] = ",".join(st.times)
        if st.price_inr is not None:
            out["price_inr"] = str(st.price_inr)
        if st.duration_min is not None:
            out["duration_min"] = str(st.duration_min)
        if st.stylist:
            out["stylist"] = st.stylist
        if st.advance_needed:
            out["advance_needed"] = st.advance_needed
        if st.price_low is not None:
            out["price_low_inr"] = str(st.price_low)
        if st.price_unit:
            out["price_unit"] = st.price_unit
        if st.deposit_inr is not None:
            out["deposit_inr"] = str(st.deposit_inr)
        if st.estimate_inr is not None:
            out["estimate_inr"] = str(st.estimate_inr)
        if st.estimate_low is not None:
            out["estimate_low_inr"] = str(st.estimate_low)
        if st.captured:
            out["captured_number"] = "same" if st.captured == "same" else st.captured
        out.update(st.notes)
        out.update(st.flags)
        return out

    def _quote(self, c: Ctx) -> Quote | None:
        st = c.st
        if st.price_inr is None and not st.times:
            return None
        budget = c.inputs.get("budget")
        price_text = (
            f"Rs {st.price_inr}{' (upper end of a range)' if st.is_range else ''}"
            if st.price_inr is not None
            else "price not given on the phone"
        )
        notes = f"duration about {st.duration_min} min" if st.duration_min is not None else None
        if c.pb.archetype:  # unit, range, estimate and deposit travel with the quote
            price_text, notes = self._archetype_texts(c, price_text)
        return Quote(
            business_name=c.brief.target.name,
            amount_inr=st.price_inr,
            price_text=price_text,
            available_slots=[
                sl.slot_label(t, asked_day=sl.find_day(c.inputs.get("date_window", "")))
                for t in st.times
            ],
            within_budget=(st.price_inr <= int(budget))
            if (st.price_inr is not None and budget)
            else None,
            notes=notes,
        )

    @staticmethod
    def _archetype_texts(c: Ctx, base: str) -> tuple[str, str | None]:
        st = c.st
        text = base
        if st.price_inr is not None and st.price_low is not None:
            text = f"Rs {st.price_low} to {st.price_inr}"
        elif st.price_inr is None and st.flags.get("price_free") == "yes":
            text = "free (no charge)"
        if st.price_unit:
            text += f" per {st.price_unit}"
        notes: list[str] = []
        if st.estimate_inr is not None:
            rng = f"{st.estimate_inr}"
            if st.estimate_low:
                rng = f"{st.estimate_low} to {st.estimate_inr}"
            notes.append(f"rough estimate Rs {rng}")
        if st.deposit_inr is not None:
            notes.append(f"deposit mentioned: Rs {st.deposit_inr} (information only)")
        if st.duration_min is not None:
            notes.append(f"duration about {st.duration_min} min")
        return text, "; ".join(notes) or None

    # ------------------------------------------------------------------ special cases
    def _hung_up(self, c: Ctx) -> CallAction:
        pb, st = c.pb, c.st
        st.finished = True
        if st.flags.get("rude") or st.flags.get("do_not_call"):
            oid = "REFUSED"
        elif st.times and st.price_inr is not None and "SLOT_OFFERED" in pb.outcomes:
            oid = "SLOT_OFFERED"  # she gave slot and price, then hung up: still worth approval
        elif (
            st.price_inr is not None or st.flags.get("price_free") == "yes"
        ) and "QUOTE_COLLECTED" in pb.outcomes:
            oid = "QUOTE_COLLECTED"  # a price check: the price is all we came for
        else:
            oid = None
        st.outcome = oid or "HUNG_UP"
        collected = self._collected(c)
        collected["outcome"] = st.outcome
        if oid:
            od = pb.outcomes[oid]
            collected.update(od.collected)
            return CallAction(
                type=CallActionType.HANGUP,
                outcome=CallOutcome(od.call_outcome),
                collected=collected,
                quote=self._quote(c) if od.needs_quote else None,
            )
        return CallAction(
            type=CallActionType.HANGUP,
            outcome=CallOutcome.HUNG_UP,
            collected=collected,
            quote=self._quote(c),
        )

    def _after_block(self, c: Ctx) -> CallAction:
        """The runner refused something we tried to say. Never repeat it."""
        st, pb = c.st, c.pb
        if st.last_was_commit:  # the commit gate said no: fall back to a call-back close
            st.commit_blocked = True
            st.finished = False
            return self._goto(c, pb.commit_step or pb.start, [])
        st.finished = True
        st.outcome = pb.confusion.outcome
        collected = self._collected(c)
        collected["outcome"] = st.outcome
        return CallAction(
            type=CallActionType.HANGUP,
            outcome=CallOutcome.PENDING_APPROVAL
            if (st.times and st.price_inr is not None)
            else CallOutcome.PARTIAL,
            collected=collected,
            quote=self._quote(c),
        )

    def _limit_hit(self, c: Ctx, turns: list) -> bool:
        pb, st = c.pb, c.st
        if st.first_at is not None and turns:
            elapsed = (turns[-1].at - st.first_at).total_seconds()
            if elapsed > min(pb.limits.max_duration_s, max(30, c.brief.max_duration_s - 5)):
                return True
        return st.turns >= pb.limits.max_turns

    def _finish_now(self, c: Ctx) -> CallAction:
        """Out of time/turns: close from the commit step's non-commit path, or give up."""
        pb, st = c.pb, c.st
        st.commit_blocked = True  # never commit in a hurry
        if st.times:
            return self._enter(c, pb.commit_step or pb.start, [])
        return self._end(c, pb.confusion.outcome, [], gave_up=True)


# --------------------------------------------------------------------------- pre-render
def static_utterances(pb: Playbook, inputs: dict[str, str]) -> list[str]:
    """Every text that depends only on the task's inputs, as Friday would speak it: each line,
    each line's sentences (the leg may speak sentence by sentence) and the joined
    "say + next question" combinations. Used to warm the TTS cache while the phone rings."""
    from friday.voice.telephony.sarvam import split_sentences

    def render(lid: str) -> str | None:
        if not pb.placeholders_in(lid) <= set(inputs):
            return None
        if any(not inputs.get(n) for n in pb.placeholders_in(lid)):
            return None
        return fill(pb.text(lid), lambda n: inputs[n])

    texts: list[str] = []

    def add(t: str | None) -> None:
        if t and t not in texts:
            texts.append(t)
            for part in split_sentences(t):
                if part not in texts:
                    texts.append(part)

    def ids(items: list[str | LineRef]) -> list[str]:
        return [
            x if isinstance(x, str) else x.line
            for x in items
            if isinstance(x, str) or not x.when
        ]

    for lid in pb.lines:
        if not pb.line_def(lid).commit:
            add(render(lid))
    mode = inputs.get("playbook_mode")
    known_conds = {"first_ask": True, "mode_book": mode == "book",
                   "mode_quote": mode not in ("book", "negotiate", "confirm"),
                   "mode_negotiate": mode == "negotiate", "mode_confirm": mode == "confirm",
                   "is_resume": truthy(inputs.get("resume")),
                   "has_date_window": bool(inputs.get("date_window")),
                   "has_duration": bool(inputs.get("duration_text")),
                   **{q: truthy(inputs.get(q)) for q in QUESTION_INPUTS}}

    def first_ask_ids(items: list[str | LineRef]) -> list[str]:
        # first entry into a step: lines needing only `first_ask` (and the call's mode, known from
        # the inputs) are spoken, `!first_ask` ones are not
        return [
            x if isinstance(x, str) else x.line
            for x in items
            if isinstance(x, str)
            or (set(x.when) <= set(known_conds) and all(known_conds[c] for c in x.when))
        ]

    for step in pb.steps.values():
        asks = [render(i) for i in first_ask_ids(step.ask)]
        if asks and all(asks):
            add(" ".join(a for a in asks if a))
    for _where, _intent, a in pb.all_actions():
        said = [render(i) for i in ids(a.say)]
        if not said or not all(said):
            continue
        base = " ".join(s for s in said if s)
        add(base)
        if a.goto and not a.goto.startswith("@") and a.goto in pb.steps:
            asks = [render(i) for i in first_ask_ids(pb.steps[a.goto].ask)]
            if asks and all(asks):
                add(base + " " + " ".join(a2 for a2 in asks if a2))
    return texts[:160]


class RoutingCallPolicy:
    """The runner's single ``CallPolicy``: scripted briefs (``brief.playbook``) go to the
    playbook engine, everything else to the LLM-driven brain, untouched."""

    def __init__(self, get_base: Any, playbook_policy: PlaybookPolicy) -> None:
        self._get_base = get_base  # callable returning the brain (resolved lazily)
        self.playbook_policy = playbook_policy

    async def next_call_action(
        self, brief: CallBrief, transcript: Transcript, answers: Any
    ) -> CallAction:
        if brief.playbook:
            return await self.playbook_policy.next_call_action(brief, transcript, answers)
        return await self._get_base().next_call_action(brief, transcript, answers)

    def fixed_lines(self, brief: CallBrief) -> dict[Language, list[str]]:
        return self.playbook_policy.fixed_lines(brief) if brief.playbook else {}

    async def next_call_action_streamed(
        self, brief: CallBrief, transcript: Any, answers: Any, **kw: Any
    ) -> Any:
        """Latency switch FRIDAY_LLM_STREAM_TO_TTS: only the model-written free-form turns stream;
        a scripted (playbook) call speaks fixed lines, so it returns None (= the ordinary call)."""
        base = self._get_base()
        fn = getattr(base, "next_call_action_streamed", None)
        if brief.playbook or fn is None:
            return None
        return await fn(brief, transcript, answers, **kw)

    def speculate(self, brief: CallBrief, transcript: Any, text: str) -> bool:
        """Latency switch: start understanding an early transcript (scripted calls only)."""
        return bool(brief.playbook and self.playbook_policy.speculate(brief, transcript, text))

    def cancel_speculation(self, transcript: Any, reason: str = "caller kept talking") -> bool:
        return self.playbook_policy.cancel_speculation(transcript, reason)
