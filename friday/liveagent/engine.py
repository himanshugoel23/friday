# ruff: noqa: E501
"""LiveCallEngine: drives one consumer call from pickup to a CallOutcome.

    engine = LiveCallEngine(policy=RuleBasedPolicy(), user_channel=...)
    result = await engine.run(brief, callee, telephony)

Per turn: listen -> understand (deterministic) -> policy picks a MOVE -> fixed line rendered with
verified slots -> guards (numbers, secrets, private facts, must_not_say, repeats, commitments) ->
speak. Hard stops, the truthful AI answer, secrets, money and commitments are decided by code
before any model is asked. Caps: max duration, max turns, hold, IVR steps, loop detector. The
telephony leg, the user channel (mid-call question) and the models are ports (ports.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Callable
from types import SimpleNamespace

from friday.core.safety import check_keys
from friday.liveagent import lines as L
from friday.liveagent.contracts import (
    ApprovalRequest,
    CallBrief,
    Callee,
    CallLanguage,
    Commitment,
    EngineEvent,
    LiveCallResult,
    OutcomeStatus,
    TranscriptTurn,
)
from friday.liveagent.ivr import choose_option, needs_identifier, parse_options
from friday.liveagent.moves import (
    KIND_MOVES,
    KINDS_WITH_IVR,
    TERMINAL_MOVES,
    CallState,
    Effect,
    Move,
    MoveDecision,
    MovePolicy,
    PolicyContext,
    allowed_next,
    transition_ok,
)
from friday.liveagent.ports import (
    CallDropped,
    HeardUtterance,
    LineModel,
    TelephonyPort,
    UserChannel,
)
from friday.liveagent.report import build_outcome, mask_numbers
from friday.liveagent.rules import RuleBasedPolicy, build_agenda, closing_decision
from friday.liveagent.slotguard import (
    GuardContext,
    check_line,
    norm,
    verify_slots,
)
from friday.liveagent.understand_callee import (
    HARD_STOP_INTENTS,
    CalleeIntent,
    Understanding,
    understand,
)

# moves whose line may come from the (OFF by default) fully generated mode. Disclosure, the AI
# answer, stop, close, voicemail and the refusals of secrets are ALWAYS the fixed lines.
GENERATABLE: frozenset[tuple[Move, str]] = frozenset(
    {
        (Move.ASK, "question"),
        (Move.ASK, "followup"),
        (Move.STATE_PURPOSE, "message"),
        (Move.CONFIRM, "thanks"),
        (Move.HANDLE_OBJECTION, "off_topic"),
        (Move.HANDLE_OBJECTION, "clarify"),
    }
)


class EngineConfig:
    """Caps and switches. Defaults are conservative; limits.max_* in the brief can only lower them."""

    def __init__(
        self,
        *,
        max_call_seconds: float = 300.0,
        max_turns: int = 40,
        max_hold_seconds: float = 120.0,
        listen_timeout_s: float = 7.0,
        first_listen_s: float = 4.0,
        ask_user_timeout_s: float = 45.0,
        max_user_questions: int = 2,
        max_ivr_steps: int = 6,
        loop_repeats: int = 3,
        voicemail_wait_s: float = 20.0,
        generated_lines: bool = False,
    ) -> None:
        self.max_call_seconds = max_call_seconds
        self.max_turns = max_turns
        self.max_hold_seconds = max_hold_seconds
        self.listen_timeout_s = listen_timeout_s
        self.first_listen_s = first_listen_s
        self.ask_user_timeout_s = ask_user_timeout_s
        self.max_user_questions = max_user_questions
        self.max_ivr_steps = max_ivr_steps
        self.loop_repeats = loop_repeats
        self.voicemail_wait_s = voicemail_wait_s
        self.generated_lines = generated_lines  # fully generated line mode: OFF by default


class _Done(Exception):
    """Internal: the call is over (status already set on the state)."""


class _Run:
    """Everything one call needs; the engine itself stays stateless between calls."""

    def __init__(
        self, brief: CallBrief, callee: Callee, tel: TelephonyPort, state: CallState, t0: float
    ) -> None:
        self.brief = brief
        self.callee = callee
        self.tel = tel
        self.st = state
        self.t0 = t0
        self.events: list[EngineEvent] = []
        self.transcript: list[TranscriptTurn] = []
        self.heard: list[str] = []  # the callee's words, raw
        self.user_answers: list[str] = []
        self.spoke_lines: list[str] = []  # unmasked Friday lines (guards, tests)
        self.line_ids: list[str] = []
        self.recent_acks: list[str] = []
        self.callee_norms: list[str] = []
        self.human_spoke = False
        self.pending_utt: HeardUtterance | None = None
        self.after_user_answer = False


class LiveCallEngine:
    def __init__(
        self,
        policy: MovePolicy | None = None,
        *,
        config: EngineConfig | None = None,
        user_channel: UserChannel | None = None,
        line_model: LineModel | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.policy: MovePolicy = policy or RuleBasedPolicy()
        self.cfg = config or EngineConfig()
        self.user_channel = user_channel
        self.line_model = line_model
        self.clock = clock or time.monotonic
        self._fallback = RuleBasedPolicy()

    # ------------------------------------------------------------------ public

    async def run(
        self, brief: CallBrief, callee: Callee, telephony: TelephonyPort
    ) -> LiveCallResult:
        kind = callee.kind
        st = CallState(kind=kind, language=brief.language)
        st.agenda = build_agenda(brief)
        r = _Run(brief, callee, telephony, st, self.clock())
        status: OutcomeStatus
        try:
            await self._drive(r)
            status = st.terminal or OutcomeStatus.UNRESOLVED
        except _Done:
            status = st.terminal or OutcomeStatus.UNRESOLVED
        except CallDropped:
            self._ev(r, "dropped", "the line dropped")
            status = OutcomeStatus.DROPPED
            st.next_actions.append("The line dropped mid-call: retry under the retry rules.")
        except Exception as exc:  # never leave the line open on a bug
            self._ev(r, "error", f"{type(exc).__name__}: {exc}")
            status = OutcomeStatus.UNRESOLVED
            st.next_actions.append("The call engine hit an internal error and ended the call.")
        finally:
            with contextlib.suppress(Exception):
                await telephony.hangup()
        if st.health_note:
            st.next_actions.append(st.health_note)
        for q in list(st.unanswered):
            st.next_actions.append(f"Still unanswered: {q}")
        outcome = build_outcome(
            brief,
            callee,
            status,
            answers=st.answers,
            commitments=st.commitments,
            approvals=st.approvals,
            next_actions=st.next_actions,
            unanswered=st.unanswered,
            callback_time=st.callback_time,
            ivr_path=st.ivr_path,
        )
        return LiveCallResult(
            outcome=outcome,
            transcript=r.transcript,
            events=r.events,
            duration_s=round(self.clock() - r.t0, 2),
            friday_lines=r.spoke_lines,
            pending_line_ids=list(dict.fromkeys(r.line_ids)),
        )

    # ------------------------------------------------------------------ helpers

    def _now(self, r: _Run) -> float:
        return round(self.clock() - r.t0, 2)

    def _ev(self, r: _Run, kind: str, detail: str, **data: str | float | int | bool | None) -> None:
        r.events.append(EngineEvent(t=self._now(r), kind=kind, detail=detail, data=dict(data)))

    def _budget_s(self, r: _Run) -> float:
        return float(min(self.cfg.max_call_seconds, r.brief.limits.max_call_seconds))

    def _hold_budget_s(self, r: _Run) -> float:
        return float(min(self.cfg.max_hold_seconds, r.brief.limits.max_hold_seconds))

    def _ctx(self, r: _Run, u: Understanding | None) -> PolicyContext:
        st = r.st
        return PolicyContext(
            brief=r.brief,
            kind=st.kind,
            state=st,
            understanding=u,
            allowed=allowed_next(st.last_move, st.kind),
        )

    def _finish(self, r: _Run, status: OutcomeStatus) -> None:
        r.st.terminal = status
        raise _Done

    # ------------------------------------------------------------------ main loop

    async def _drive(self, r: _Run) -> None:
        st = r.st
        r.pending_utt = await r.tel.listen(self.cfg.first_listen_s)
        first = True
        while True:
            if self.clock() - r.t0 >= self._budget_s(r):
                await self._time_up(r, "maximum call duration reached")
            if st.turns >= self.cfg.max_turns:
                await self._time_up(r, "maximum number of turns reached")
            utt = r.pending_utt
            r.pending_utt = None
            if utt is None and not first:
                utt = await r.tel.listen(self.cfg.listen_timeout_s)
            u = understand(utt)
            if first and utt is None:
                u = None  # pickup silence: just open the call
            first = False
            if u is not None:
                self._observe(r, u)
                if await self._line_events(r, u):
                    continue
            if not st.disclosed and (u is None or u.intent not in HARD_STOP_INTENTS):
                await self._opening(r)  # greet + disclose, then wait for the callee
                continue
            if u is None:
                continue
            await self._turn(r, u)

    def _observe(self, r: _Run, u: Understanding) -> None:
        st = r.st
        self._ev(
            r,
            "understood",
            f"{u.intent.value}",
            confidence=u.confidence,
            matched=u.matched[:40],
            stt=u.stt_confidence,
        )
        if u.intent == CalleeIntent.SILENCE:
            st.silences += 1
        else:
            st.silences = 0
            st.turns += 1
        if u.text:
            r.heard.append(u.text)
            r.transcript.append(
                TranscriptTurn(speaker="callee", text=mask_numbers(u.text), t=self._now(r))
            )
            if u.audio_class == "human":
                r.human_spoke = True
        st.unknown_streak = (
            st.unknown_streak + 1 if (u.intent == CalleeIntent.UNKNOWN or u.confidence < 0.5) else 0
        )
        if u.intent == CalleeIntent.OFF_TOPIC:
            st.off_topic += 1
        if "wants_english" in u.flags and st.language != CallLanguage.EN:
            st.language = CallLanguage.EN
            self._ev(r, "language", "switched to English at the callee's request")
        elif "wants_hindi" in u.flags and st.language == CallLanguage.EN:
            st.language = CallLanguage.HINGLISH
            self._ev(r, "language", "switched to Hinglish at the callee's request")
        if "health_mention" in u.flags and not st.health_note:
            st.health_note = f"The callee mentioned a health problem ('{mask_numbers(u.text)[:80]}'). You may want to check on them."
        # loop detector: the same words again and again
        key = norm(u.text)
        if key and u.intent != CalleeIntent.SILENCE:
            r.callee_norms.append(key)
        recent = r.callee_norms[-self.cfg.loop_repeats :]
        if len(recent) == self.cfg.loop_repeats and len(set(recent)) == 1:
            r.callee_norms.clear()
            self._ev(r, "loop", "the callee repeated the same words")
            st.flags.add("loop")

    # ------------------------------------------------------------------ line events

    async def _line_events(self, r: _Run, u: Understanding) -> bool:
        """Voicemail, carrier messages, IVR, hold queue. True when handled (loop continues)."""
        st = r.st
        i = u.intent
        if i == CalleeIntent.UNREACHABLE:
            self._ev(r, "unreachable", u.matched)
            st.next_actions.append("The number was switched off / not reachable: retry later.")
            self._finish(r, OutcomeStatus.UNREACHABLE)
        if i == CalleeIntent.VOICEMAIL_BEEP:
            await self._voicemail(r, u)
            return True
        if i == CalleeIntent.IVR_MENU:
            await self._ivr(r, u)
            return True
        if i == CalleeIntent.HOLD_MUSIC:
            await self._queue_hold(r)
            return True
        return False

    async def _voicemail(self, r: _Run, u: Understanding) -> None:
        st, brief = r.st, r.brief
        self._ev(r, "voicemail", f"detail={u.detail}")
        if Move.VOICEMAIL not in KIND_MOVES[st.kind] or not brief.voicemail_allowed:
            st.next_actions.append(
                "Reached a voicemail; no message was left (not allowed for this call). Retry later."
            )
            self._finish(r, OutcomeStatus.VOICEMAIL_NO_MESSAGE)
        # wait for the beep: the greeting may still be playing
        if u.detail != "beep":
            waited = 0.0
            t_start = self.clock()
            while waited < self.cfg.voicemail_wait_s:
                nxt = await r.tel.listen(5.0)
                waited = self.clock() - t_start
                if nxt is None:
                    break  # the greeting ended in silence: the recording is open
                nu = understand(nxt)
                if nu.intent == CalleeIntent.VOICEMAIL_BEEP and nu.detail == "beep":
                    break
        d = MoveDecision(
            move=Move.VOICEMAIL,
            variant="message",
            slots={"user": brief.user_name},
            terminal=OutcomeStatus.VOICEMAIL_LEFT,
            reason="fixed voicemail message",
        )
        spoken = await self._speak_chain(r, [d], None)
        if not spoken:
            st.next_actions.append("Voicemail message was blocked by a guard; nothing was left.")
            self._finish(r, OutcomeStatus.VOICEMAIL_NO_MESSAGE)
        st.next_actions.append("Voicemail left; the user may expect a call back from them.")
        self._finish(r, OutcomeStatus.VOICEMAIL_LEFT)

    async def _queue_hold(self, r: _Run) -> None:
        """Hold music / queue announcement: stay silent, up to the hold cap, until a person speaks."""
        st = r.st
        budget = self._hold_budget_s(r)
        t_start = self.clock()
        self._ev(r, "hold", "waiting in a queue", cap=budget)
        while True:
            used = st.hold_s + (self.clock() - t_start)
            if used >= budget or self.clock() - r.t0 >= self._budget_s(r):
                st.hold_s = used
                st.next_actions.append(
                    f"Held for about {int(used)} seconds with nobody picking up; the cap was reached. Retry later."
                )
                self._finish(r, OutcomeStatus.UNRESOLVED)
            utt = await r.tel.listen(min(10.0, max(1.0, budget - used)))
            if utt is None:
                continue
            nu = understand(utt)
            if nu.intent in (CalleeIntent.HOLD_MUSIC, CalleeIntent.SILENCE):
                continue
            st.hold_s += self.clock() - t_start
            self._ev(r, "hold", "a person picked up", held_s=round(st.hold_s, 1))
            r.pending_utt = utt
            return

    async def _ivr(self, r: _Run, u: Understanding) -> None:
        st, brief = r.st, r.brief
        if st.kind not in KINDS_WITH_IVR:
            st.next_actions.append(
                "An automated menu answered a personal call: check the number with the user."
            )
            self._ev(r, "ivr", "menu on a personal call: stop")
            self._finish(r, OutcomeStatus.UNRESOLVED)
        st.ivr_steps += 1
        if st.ivr_steps > self.cfg.max_ivr_steps:
            st.next_actions.append("The phone menu did not lead to a person within the step limit.")
            self._finish(r, OutcomeStatus.UNRESOLVED)
        options = parse_options(u.text)
        if not options and needs_identifier(u.text):
            st.next_actions.append(
                "The phone menu asks for an account/mobile number or PIN. Friday does not key identifiers; ask the user."
            )
            self._ev(r, "ivr", "menu asks for an identifier: stop")
            self._finish(r, OutcomeStatus.UNRESOLVED)
        pick, why = choose_option(options, brief, st.ivr_path)
        if pick is None:
            self._ev(r, "ivr", f"no safe key ({why})", options=len(options))
            if st.ivr_steps >= 2:
                st.next_actions.append(
                    "Could not match a menu option to the goal; no key was pressed."
                )
                self._finish(r, OutcomeStatus.UNRESOLVED)
            return  # listen again: the menu often repeats
        safe = check_keys(
            pick.digit,
            SimpleNamespace(
                approved_identifiers=[], target=SimpleNamespace(phone=""), reference=None
            ),
        )  # type: ignore[arg-type]
        if not safe.allowed or len(pick.digit) != 1:
            self._finish(r, OutcomeStatus.UNRESOLVED)
        await r.tel.send_dtmf(pick.digit)
        st.ivr_path.append(pick.digit)
        st.last_move = Move.HOLD_WAIT
        self._ev(r, "ivr", f"pressed {pick.digit} ({pick.label[:30]}): {why}", options=len(options))
        r.transcript.append(
            TranscriptTurn(
                speaker="system",
                text=f"[pressed {pick.digit} for {pick.label[:30]}]",
                move=Move.HOLD_WAIT.value,
                t=self._now(r),
            )
        )

    # ------------------------------------------------------------------ opening and turns

    async def _opening(self, r: _Run) -> None:
        """First seconds: greet -> disclose in ONE utterance; then wait for the callee."""
        st = r.st
        decisions = await self._decide_chain(r, None)
        spoken = await self._speak_chain(r, decisions, None)
        if not spoken or not st.disclosed:
            self._finish(r, OutcomeStatus.UNRESOLVED)

    async def _turn(self, r: _Run, u: Understanding) -> None:
        st = r.st
        if "loop" in st.flags:
            await self._say_forced(
                r,
                "unresolved",
                OutcomeStatus.UNRESOLVED,
                "stuck in a loop: escalating to a polite end",
            )
        decisions = await self._decide_chain(r, u)
        await self._speak_chain(r, decisions, u)
        if r.after_user_answer:  # the user answered a mid-call question: pick the thread up again
            r.after_user_answer = False
            decisions = await self._decide_chain(r, None)
            await self._speak_chain(r, decisions, None)

    async def _decide_chain(self, r: _Run, u: Understanding | None) -> list[MoveDecision]:
        """Ask the policy for the first move, then (while it says continue_turn) for the next ones,
        applying each decision's effects to a simulated state so the chain is coherent."""
        out: list[MoveDecision] = []
        # chain decisions need the state AFTER earlier effects: we apply effects at plan time
        cur_u = u
        for _ in range(5):
            ctx = self._ctx(r, cur_u)
            d = await self.policy.choose(ctx)
            if not transition_ok(r.st.last_move, d.move, r.st.kind):
                self._ev(
                    r, "policy_rejected", f"illegal move {d.move.value} after {r.st.last_move}"
                )
                d = self._fallback.decide(ctx)
                if not transition_ok(r.st.last_move, d.move, r.st.kind):
                    d = closing_decision(ctx)
            self._ev(
                r,
                "move",
                f"{d.move.value}.{d.variant}",
                source=d.source,
                reason=d.reason[:80],
                conf=d.confidence,
            )
            out.append(d)
            r.st.last_move = d.move
            r.st.last_variant = d.variant
            self._apply_plan_effects(r, d)
            if d.terminal_status is not None or not d.continue_turn:
                break
            cur_u = None
        return out

    def _apply_plan_effects(self, r: _Run, d: MoveDecision) -> None:
        st = r.st
        for e in d.effects:
            self._apply_effect(r, e)
        if d.move == Move.STATE_PURPOSE and d.variant == "purpose":
            st.purpose_said = True

    def _apply_effect(self, r: _Run, e: Effect) -> None:
        st, k, data = r.st, e.kind, e.data
        if k == "approval":
            kind_ = str(data["kind"])
            dup = any(
                a.kind == kind_
                and (
                    kind_ in ("payment", "time", "booking", "visit")
                    or a.text == mask_numbers(str(data["text"]))
                )
                for a in st.approvals
            )
            if dup:
                return
            st.approvals.append(
                ApprovalRequest(
                    kind=str(data["kind"]),
                    text=mask_numbers(str(data["text"])),
                    reason=str(data["reason"]),
                )
            )
        elif k == "commitment":
            st.commitments.append(
                Commitment(kind=str(data["kind"]), text=str(data["text"]), within_limits=True)
            )
        elif k == "next_action":
            st.next_actions.append(str(data["text"]))
        elif k == "do_not_call":
            st.do_not_call = True
        elif k == "answer":
            q = str(data.get("question") or "")
            st.answers[q or f"note {len(st.answers) + 1}"] = str(data["text"])
        elif k == "delivered":
            idx = int(data["idx"])
            kind = st.agenda[idx][0]
            st.ask_attempts = st.ask_attempts + 1 if st.last_item == idx else 0
            st.last_item = idx
            st.agenda_idx = max(st.agenda_idx, idx + 1)
            st.awaiting = "answer" if kind == "ask" else "ack"
        elif k == "resume":
            st.resume_pending = True
            st.resume_mode = str(data["mode"])
        elif k == "awaiting":
            st.awaiting = str(data["value"])
        elif k == "callback_time":
            st.callback_time = str(data["value"])
        elif k == "flag":
            st.flags.add(str(data["name"]))
        elif k == "pending":
            st.pending_value = str(data["value"])
        elif k == "confirmed_readback":
            st.pending_value = None
        elif k == "unanswered_current":
            if st.last_item is not None and st.agenda[st.last_item][0] == "ask":
                st.unanswered.append(r.brief.ask_list[st.agenda[st.last_item][1]])
        # "hold" and "ask_user" are executed at speak time (they need the line / the user)

    # ------------------------------------------------------------------ speaking

    def _guard_ctx(self, r: _Run, d: MoveDecision) -> GuardContext:
        return GuardContext(
            brief=r.brief,
            heard_text=" \n".join(r.heard),
            user_answers=r.user_answers,
            friday_lines=r.spoke_lines,
            callee_number=r.callee.number or "",
            commit_authorized=d.authorizes_commitment,
            allow_repeat=d.allow_repeat,
        )

    async def _render(
        self, r: _Run, d: MoveDecision, extra_lines: list[str]
    ) -> tuple[str, str] | None:
        """(line_id, text) that passes every guard, or None when nothing safe can be said."""
        st, brief = r.st, r.brief
        heard = " \n".join(r.heard)
        problems = verify_slots(d.slots, brief, heard, extra_known=" ".join(r.user_answers))
        if problems:
            self._ev(r, "guard", "ungrounded slot: " + "; ".join(problems))
            return None
        history = r.spoke_lines + extra_lines
        avoid = [] if d.allow_repeat else history[-2:]
        try:
            rendered = L.render(
                d.move,
                d.variant,
                st.kind,
                st.language,
                d.slots,
                avoid=avoid,
                recent_acks=r.recent_acks,
                seed=len(history),
            )
        except L.MissingSlot as exc:
            self._ev(r, "guard", f"missing slot {exc}")
            return None
        if rendered is None:
            self._ev(
                r,
                "guard",
                f"repeat guard: every wording of {d.move.value}.{d.variant} was just said",
            )
            st.flags.add("loop")
            return None
        text, line_id = rendered.text, rendered.line_id
        if (
            self.cfg.generated_lines
            and self.line_model is not None
            and (d.move, d.variant) in GENERATABLE
        ):
            gen = await self._generate(r, d, text)
            if gen:
                text, line_id = gen, "generated"
        gctx = self._guard_ctx(r, d)
        gctx.friday_lines = history
        # fixed catalog lines are commitment-safe by construction (every "yes" goes through the
        # commitment guard first); only generated text is scanned for spoken promises
        if line_id != "generated":
            gctx.commit_authorized = True
        res = check_line(text, gctx)
        if not res.ok:
            for code, detail in res.violations:
                self._ev(
                    r,
                    "guard",
                    f"{code}: {detail}",
                    move=f"{d.move.value}.{d.variant}",
                    line=line_id,
                )
            if line_id == "generated":  # fall back to the fixed line, re-check it
                text, line_id = rendered.text, rendered.line_id
                res = check_line(text, gctx)
            if not res.ok:
                if any(
                    c
                    in (
                        "secret_or_number",
                        "ungrounded_number",
                        "private_leak",
                        "must_not_say",
                        "claims_to_be_user",
                        "denies_ai",
                    )
                    for c, _ in res.violations
                ):
                    st.next_actions.append(
                        "A line was blocked by a safety guard: "
                        + ", ".join(sorted({c for c, _ in res.violations}))
                        + "."
                    )
                if res.has("repeat"):
                    st.flags.add("loop")
                return None
        if "{ack}" in text or any(a in text for a in L.ACK_POOL[st.language.value]):
            for a in L.ACK_POOL[st.language.value]:
                if text.startswith(a):
                    r.recent_acks.append(a)
        return line_id, text

    async def _generate(self, r: _Run, d: MoveDecision, fixed: str) -> str | None:
        assert self.line_model is not None
        from friday.liveagent.slotguard import public_brief_view

        try:
            text = await self.line_model.generate(
                {
                    "brief": public_brief_view(r.brief),
                    "move": d.move.value,
                    "variant": d.variant,
                    "slots": d.slots,
                    "language": r.st.language.value,
                    "fixed_line": fixed,
                    "callee_said": r.heard[-1] if r.heard else "",
                }
            )
        except Exception as exc:  # noqa: BLE001
            self._ev(r, "guard", f"line model failed: {exc!r}")
            return None
        text = re.sub(r"\s+", " ", (text or "")).strip()
        if not text or len(text) > 240:
            return None
        return text

    async def _safe_alternative(
        self, r: _Run, extra_lines: list[str]
    ) -> tuple[MoveDecision, str, str] | None:
        """When a line was blocked: the fixed deflection, then a polite end."""
        for d in (
            MoveDecision(
                move=Move.ANSWER_FROM_BRIEF,
                variant="defer",
                slots={"user": r.brief.user_name},
                reason="guard replaced the line",
            ),
            MoveDecision(
                move=Move.CLOSE,
                variant="unresolved",
                slots={"user": r.brief.user_name},
                terminal=OutcomeStatus.UNRESOLVED,
                reason="guard replaced the line",
            ),
        ):
            got = await self._render(r, d, extra_lines)
            if got:
                return d, got[0], got[1]
        return None

    async def _speak_chain(
        self, r: _Run, decisions: list[MoveDecision], u: Understanding | None
    ) -> bool:
        """Render every decision of a turn, speak them as one utterance, then run side steps
        (hold, ask the user) and finish the call if a decision was terminal."""
        st = r.st
        pieces: list[tuple[MoveDecision, str, str]] = []
        extra: list[str] = []
        terminal: OutcomeStatus | None = None
        for d in decisions:
            if d.silent:
                continue
            if any(e.kind == "ask_user" for e in d.effects) and await self._try_user(
                r, d, u, pieces, extra
            ):
                continue
            got = await self._render(r, d, extra)
            if got is None and d.move == Move.VOICEMAIL:
                break  # a blocked voicemail message is never replaced by another line
            if got is None and d.terminal_status is not None:
                terminal = (
                    d.terminal_status
                )  # a stop/close must happen even if its line was blocked
                self._ev(r, "guard", "terminal line blocked: ending the call silently")
                break
            if got is None:
                alt = await self._safe_alternative(r, extra)
                if alt is None:
                    terminal = OutcomeStatus.UNRESOLVED
                    break
                d, line_id, text = alt
            else:
                line_id, text = got
            pieces.append((d, line_id, text))
            extra.append(text)
            if d.terminal_status is not None:
                terminal = d.terminal_status
                break
        if pieces:
            joined = " ".join(t for _d, _i, t in pieces)
            await r.tel.speak(joined, r.st.language)
            now = self._now(r)
            for d, line_id, text in pieces:
                r.spoke_lines.append(text)
                r.line_ids.append(line_id)
                st.used_line_ids.append(line_id)
                st.friday_lines.append(text)
                r.transcript.append(
                    TranscriptTurn(
                        speaker="friday",
                        text=mask_numbers(text),
                        move=f"{d.move.value}.{d.variant}",
                        t=now,
                    )
                )
                if d.move == Move.DISCLOSE:
                    st.disclosed = True
        if (
            terminal is None
            and decisions
            and decisions[-1].terminal_status is not None
            and not pieces
        ):
            terminal = decisions[-1].terminal_status
        if terminal is not None:
            self._finish(r, terminal)
        # side steps after the line: hold for a person who said "ek minute"
        if pieces and any(e.kind == "hold" for d, _i, _t in pieces for e in d.effects):
            await self._hold_for_callee(r)
        return bool(pieces)

    # ------------------------------------------------------------------ ask the user (warm transfer)

    async def _try_user(
        self,
        r: _Run,
        d: MoveDecision,
        u: Understanding | None,
        pieces: list[tuple[MoveDecision, str, str]],
        extra: list[str],
    ) -> bool:
        """The callee asked for something not in the brief. If a user channel exists and the
        question budget allows, say "one minute, let me check with <user>", ask them with a time
        limit and relay the answer through the guards. True when the user's answer was queued."""
        st = r.st
        if self.user_channel is None or st.user_questions >= self.cfg.max_user_questions:
            return False
        hold = MoveDecision(
            move=Move.HOLD_WAIT,
            variant="asking_user",
            slots={"user": r.brief.user_name},
            reason="ask the user mid-call",
        )
        got = await self._render(r, hold, extra)
        if got is None:
            return False
        await r.tel.speak(got[1], st.language)
        r.spoke_lines.append(got[1])
        r.line_ids.append(got[0])
        st.friday_lines.append(got[1])
        r.transcript.append(
            TranscriptTurn(
                speaker="friday",
                text=mask_numbers(got[1]),
                move="hold_wait.asking_user",
                t=self._now(r),
            )
        )
        st.user_questions += 1
        asked = next(
            (str(e.data.get("question", "")) for e in d.effects if e.kind == "ask_user"), ""
        )
        q = f'The person on the call ({r.callee.kind.value.replace("_", " ")}) asked: "{mask_numbers(asked)}". What should I tell them? I cannot give OTPs, PINs or card details. Reply within {int(self.cfg.ask_user_timeout_s)} seconds.'
        self._ev(r, "ask_user", "asked the user mid-call", timeout=self.cfg.ask_user_timeout_s)
        try:
            answer = await asyncio.wait_for(
                self.user_channel.ask_user(q, timeout_s=self.cfg.ask_user_timeout_s),
                timeout=self.cfg.ask_user_timeout_s + 1,
            )
        except TimeoutError:
            answer = None
        if not answer or not answer.strip():
            self._ev(r, "ask_user", "no answer in time")
            return False
        answer = re.sub(r"\s+", " ", answer).strip()[:200]
        r.user_answers.append(answer)
        self._ev(r, "ask_user", "the user answered")
        fact = MoveDecision(
            move=Move.ANSWER_FROM_BRIEF,
            variant="fact",
            slots={"fact": answer},
            reason="the user's own answer",
        )
        # the user's words are a trusted source, but they still pass the secret/number/repeat guards
        try:
            rendered = L.render(
                fact.move,
                fact.variant,
                st.kind,
                st.language,
                fact.slots,
                avoid=(r.spoke_lines + extra)[-2:],
                recent_acks=r.recent_acks,
                seed=len(r.spoke_lines),
            )
        except L.MissingSlot:
            return False
        if rendered is None:
            return False
        gctx = self._guard_ctx(r, fact)
        gctx.friday_lines = r.spoke_lines + extra
        res = check_line(rendered.text, gctx)
        res.violations = [(c, dd) for c, dd in res.violations if c not in ("private_leak",)]
        if res.violations:
            for code, detail in res.violations:
                self._ev(r, "guard", f"user answer blocked, {code}: {detail}")
            return False
        # success: drop this decision's pending approval/closing, resume the flow afterwards
        st.approvals = [
            a
            for a in st.approvals
            if not (a.kind == "personal_detail" and a.text == mask_numbers(asked[:80]))
        ]
        st.flags.discard("closing")
        st.resume_pending = True
        st.resume_mode = "again" if st.awaiting == "answer" else "wait"
        r.after_user_answer = True
        pieces.append((fact, rendered.line_id, rendered.text))
        extra.append(rendered.text)
        return True

    # ------------------------------------------------------------------ hold, close, caps

    async def _hold_for_callee(self, r: _Run) -> None:
        """The callee said "ek minute": wait up to the hold cap for them to come back."""
        st = r.st
        budget = self._hold_budget_s(r)
        t_start = self.clock()
        st.awaiting_before_hold = st.awaiting
        self._ev(r, "hold", "callee asked us to wait", cap=budget)
        nudged = False
        while True:
            used = st.hold_s + (self.clock() - t_start)
            if used >= budget or self.clock() - r.t0 >= self._budget_s(r):
                st.hold_s = used
                await self._say_forced(
                    r,
                    "unresolved",
                    OutcomeStatus.UNRESOLVED,
                    "hold cap reached",
                    next_action="The person asked us to wait and did not come back within the hold cap.",
                )
            utt = await r.tel.listen(min(10.0, max(1.0, budget - used)))
            if (
                utt is None
                or not (utt.text or "").strip()
                or utt.audio_class in ("hold_music", "silence")
            ):
                if utt is None and not nudged and used > budget / 2:
                    nudged = True
                    await self._speak_simple(r, Move.HOLD_WAIT, "still_here")
                continue
            st.hold_s += self.clock() - t_start
            st.awaiting = "returned"
            r.pending_utt = utt
            return

    async def _speak_simple(self, r: _Run, move: Move, variant: str) -> bool:
        d = MoveDecision(move=move, variant=variant, slots={"user": r.brief.user_name})
        got = await self._render(r, d, [])
        if got is None:
            return False
        await r.tel.speak(got[1], r.st.language)
        r.spoke_lines.append(got[1])
        r.line_ids.append(got[0])
        r.st.friday_lines.append(got[1])
        r.transcript.append(
            TranscriptTurn(
                speaker="friday",
                text=mask_numbers(got[1]),
                move=f"{move.value}.{variant}",
                t=self._now(r),
            )
        )
        r.st.last_move = move
        return True

    async def _say_forced(
        self,
        r: _Run,
        variant: str,
        status: OutcomeStatus,
        reason: str,
        next_action: str | None = None,
    ) -> None:
        """Escalation: end politely with a fixed CLOSE line (if a person is there to hear it)."""
        st = r.st
        self._ev(r, "escalate", reason, status=status.value)
        if next_action:
            st.next_actions.append(next_action)
        if r.human_spoke and st.disclosed:
            d = MoveDecision(
                move=Move.CLOSE,
                variant=variant,
                slots={"user": r.brief.user_name},
                terminal=status,
                reason=reason,
            )
            got = await self._render(r, d, [])
            if got is not None:
                await r.tel.speak(got[1], st.language)
                r.spoke_lines.append(got[1])
                r.line_ids.append(got[0])
                st.friday_lines.append(got[1])
                r.transcript.append(
                    TranscriptTurn(
                        speaker="friday",
                        text=mask_numbers(got[1]),
                        move=f"close.{variant}",
                        t=self._now(r),
                    )
                )
        self._finish(r, status)

    async def _time_up(self, r: _Run, reason: str) -> None:
        if r.st.approvals:
            await self._say_forced(r, "need_approval", OutcomeStatus.CUT_OFF, reason)
        await self._say_forced(
            r,
            "time_up",
            OutcomeStatus.CUT_OFF,
            reason,
            next_action=f"The call was cut off: {reason}.",
        )


__all__ = ["TERMINAL_MOVES", "EngineConfig", "LiveCallEngine"]
