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
from friday.playbooks import slots as sl
from friday.playbooks.intents import ANY, Intent
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
    heuristic,
    is_stop_request,
)

log = get_logger(__name__)

_MAX_HOPS = 12
_SAFE_INPUT = re.compile(r"[^\w\s'.\-]", re.U)


def fill(template: str, value: Any) -> str:
    """Fill ``{slots}`` of a line; a line that starts with a slot starts with a capital."""
    out = re.sub(r"\{([a-z_]+)\}", lambda m: value(m.group(1)), template)
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

    @property
    def slot_text(self) -> str:
        return sl.join_slots(self.st.times)

    def value(self, name: str) -> str:
        st = self.st
        if name in self.inputs and self.inputs[name]:
            return self.inputs[name]
        if name == "slot" and st.times:
            return self.slot_text
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
        if name == "for_whom" and not v and brief.beneficiary_name:
            v = first_name(brief.beneficiary_name)
        out[name] = first_name(v) if name == "user_first_name" else clean_input(v)
    if name := out.get("budget"):
        digits = re.sub(r"\D", "", name)
        out["budget"] = digits if digits else ""
    return out


def missing_inputs(pb: Playbook, inputs: dict[str, str]) -> list[str]:
    return [n for n, spec in pb.inputs.items() if spec.required and not inputs.get(n)]


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
    ) -> None:
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
        val = {
            "recording": c.recording,
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
            "price_known": price is not None,
            "duration_known": st.duration_min is not None,
            "is_range": st.is_range,
            "has_offered": len(st.times) >= 2,
            "can_commit": self._can_commit(c) if key == "can_commit" else False,
            "first_ask": st.asked[st.step] == 0,
        }[key]
        return (not val) if neg else bool(val)

    def _requested(self, c: Ctx) -> str | None:
        """The one specific time the task already names (None if it only names a part of day)."""
        t = sl.requested_time(c.inputs.get("date_window"))
        return sl.with_day(t, sl.find_day(c.inputs.get("date_window", ""))) if t else None

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
        if st.price_inr is None or st.advance_needed == "yes" or st.flags.get("price_unknown"):
            return False
        budget = c.inputs.get("budget")
        if budget and st.price_inr > int(budget):
            return False
        from friday.voice.commit import commit_reasons

        for t in st.times[:2]:
            slot_at = sl.resolve_slot_at(t, now=c.now, window_start=b.window_start)
            probe = CallAction(
                type=CallActionType.HANGUP,
                commits_booking=True,
                slot_at=slot_at,
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
        return self._apply(c, u, reply_turn.text if reply_turn else "")

    # ------------------------------------------------------------------ understanding
    def _allowed(self, pb: Playbook, step_id: str) -> list[str]:
        s = pb.steps[step_id]
        keys = {k for k in s.branches if k != ANY} | set(pb.defaults)
        return sorted(keys | {Intent.UNCLEAR.value})

    async def _understand(self, c: Ctx, reply: str) -> Understanding:
        st, pb = c.st, c.pb
        if is_stop_request(reply):  # hard rule: no model needed, none trusted
            return Understanding(intent=Intent.STOP_CALLING.value, confident=True)
        h = heuristic(reply, step=st.step, known={"hints": hints_of(c)})
        use_llm = self.llm_mode == "always" or (self.llm_mode == "auto" and not h.confident)
        if self.llm_mode == "never" or not use_llm:
            return h
        try:
            u = await self.understander.understand(
                reply=reply,
                friday_said=st.last_friday,
                step=st.step,
                allowed=self._allowed(pb, st.step),
                known={"slot": c.slot_text, "price_inr": st.price_inr, "hints": hints_of(c)},
                task_id=c.brief.task_id,
            )
            st.llm_calls += 1
        except Exception as e:  # noqa: BLE001 - never stall a call on a model failure
            log.warning("playbook understand failed (%s); using the heuristic", type(e).__name__)
            return h
        if is_stop_request(reply):
            return Understanding(intent=Intent.STOP_CALLING.value, confident=True)
        u = u.normalised()
        if u.intent == Intent.UNCLEAR.value and h.intent != Intent.UNCLEAR.value and h.confident:
            return h
        return u

    # ------------------------------------------------------------------ applying an intent
    def _merge_slots(self, st: CallState, u: Understanding, day: str | None = None) -> None:
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
        if intent in (Intent.GIVES_PRICE, Intent.PRICE_RANGE):
            if u.price_inr is not None:
                st.price_inr = u.price_inr
                st.is_range = intent == Intent.PRICE_RANGE
            if u.duration_min is not None:
                st.duration_min = u.duration_min
        if intent == Intent.GIVES_STYLIST and u.stylist:
            st.stylist = u.stylist
        if intent == Intent.NEEDS_ADVANCE:
            st.advance_needed = "yes"
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
            for a in pb.actions(acts):
                if a.when and not self._all(a.when, c):
                    continue
                if a.max_uses is not None and c.st.uses[key] >= a.max_uses:
                    break  # this branch is used up: try the next candidate
                return a, key
        return None, ""

    def _apply(self, c: Ctx, u: Understanding, reply: str) -> CallAction:
        pb, st = c.pb, c.st
        self._merge_slots(st, u, day=sl.find_day(c.inputs.get("date_window", "")))
        intent = u.intent
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
            return self._confusion(c)
        st.uses[key] += 1
        return self._run(c, action)

    def _take_requested(self, c: Ctx) -> None:
        """She said yes to the time we asked for: that time is the slot (never invented)."""
        req = self._requested(c)
        if req and not c.st.times:
            c.st.times = [req]
            c.st.slot_free = "yes"

    def _run(self, c: Ctx, a: Action) -> CallAction:
        pb, st = c.pb, c.st
        st.flags.update({k: v for k, v in a.set.items()})
        if a.use_requested_time:
            self._take_requested(c)
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
    def _say(self, c: Ctx, text: str) -> CallAction:
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
        out.update(st.flags)
        return out

    def _quote(self, c: Ctx) -> Quote | None:
        st = c.st
        if st.price_inr is None and not st.times:
            return None
        budget = c.inputs.get("budget")
        return Quote(
            business_name=c.brief.target.name,
            amount_inr=st.price_inr,
            price_text=(
                f"Rs {st.price_inr}{' (upper end of a range)' if st.is_range else ''}"
                if st.price_inr is not None
                else "price not given on the phone"
            ),
            available_slots=[
                sl.slot_label(t, asked_day=sl.find_day(c.inputs.get("date_window", "")))
                for t in st.times
            ],
            within_budget=(st.price_inr <= int(budget))
            if (st.price_inr is not None and budget)
            else None,
            notes=(
                f"duration about {st.duration_min} min" if st.duration_min is not None else None
            ),
        )

    # ------------------------------------------------------------------ special cases
    def _hung_up(self, c: Ctx) -> CallAction:
        pb, st = c.pb, c.st
        st.finished = True
        if st.flags.get("rude") or st.flags.get("do_not_call"):
            oid = "REFUSED"
        elif st.times and st.price_inr is not None:
            oid = "SLOT_OFFERED"  # she gave slot and price, then hung up: still worth approval
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

    def asks_of(step_id: str) -> None:
        """The question(s) a step opens with: with every conditional line, and without them."""
        step = pb.steps.get(step_id)
        if step is None:
            return
        allv = [render(x if isinstance(x, str) else x.line) for x in step.ask]
        if allv and all(allv):
            add(" ".join(a for a in allv if a))  # e.g. the intro AND the first question, one go
        base = [render(i) for i in ids(step.ask)]
        if base and all(base):
            add(" ".join(a for a in base if a))

    def action_texts(a: Action) -> None:
        said = [render(i) for i in ids(a.say)]
        if not said or not all(said):
            return
        base = " ".join(s for s in said if s)
        add(base)
        if a.goto and not a.goto.startswith("@") and a.goto in pb.steps:
            step = pb.steps[a.goto]
            allv = [render(x if isinstance(x, str) else x.line) for x in step.ask]
            if allv and all(allv):
                add(base + " " + " ".join(a2 for a2 in allv if a2))
            asks = [render(i) for i in ids(step.ask)]
            if asks and all(asks):
                add(base + " " + " ".join(a2 for a2 in asks if a2))

    # 1) the conversation in the order it happens: the disclosure, then each step breadth-first
    #    from the start (the first answers come at once, so these must be warm first)
    add(render(pb.disclosure))
    order: list[str] = []
    todo = [pb.start]
    while todo:
        sid = todo.pop(0)
        if sid in order or sid not in pb.steps:
            continue
        order.append(sid)
        step = pb.steps[sid]
        acts = [x for a in step.branches.values() for x in pb.actions(a)]
        for a in acts:
            if a.goto:
                targets = [a.goto]
                if a.goto.startswith("@"):
                    targets = [r.goto for r in pb.routes.get(a.goto[1:], []) if r.goto]
                todo.extend(t for t in targets if not t.startswith("@"))
    for sid in order:
        asks_of(sid)
        for a in (x for br in pb.steps[sid].branches.values() for x in pb.actions(br)):
            action_texts(a)
    # 2) the shared answers (are you a bot, who is this, repeat, hold ...)
    for a in (x for d in pb.defaults.values() for x in pb.actions(d)):
        action_texts(a)
    # 3) everything else, so nothing the old list covered is lost
    for lid in pb.lines:
        if not pb.line_def(lid).commit:
            add(render(lid))
    for step in pb.steps.values():
        asks = [render(i) for i in ids(step.ask)]
        if asks and all(asks):
            add(" ".join(a for a in asks if a))
    for _where, _intent, a in pb.all_actions():
        action_texts(a)
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
