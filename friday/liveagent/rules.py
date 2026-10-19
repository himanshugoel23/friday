# ruff: noqa: E501
"""The deterministic default policy: which move comes next, given what the callee just said.

``mandatory_decision`` covers everything that must NOT be left to a model (hard stops, the
truthful AI answer, secrets, money, commitments, "who is this", questions about the user,
waiting). ``RuleBasedPolicy.default_decision`` drives the agenda (purpose -> must_say messages ->
asks) and handles the ordinary replies. Policies only return decisions (move, variant, slots,
effects); the engine speaks the fixed line, runs the guards and applies the effects.
"""

from __future__ import annotations

import re

from friday.liveagent.contracts import CallBrief, OutcomeStatus
from friday.liveagent.moves import CallState, Effect, Move, MoveDecision, PolicyContext
from friday.liveagent.slotguard import judge_commitment, norm
from friday.liveagent.understand_callee import CalleeIntent, Understanding

_BOT_WORDS = re.compile(
    r"bot|robot|machine|ai\b|computer|recording|insaan|insan|human|aadmi|admi|इंसान|बॉट|रोबोट|मशीन",
    re.I,
)


def D(
    move: Move,
    variant: str,
    *,
    slots: dict[str, str] | None = None,
    reason: str = "",
    effects: list[Effect] | None = None,
    cont: bool = False,
    terminal: OutcomeStatus | None = None,
    **kw: object,
) -> MoveDecision:
    return MoveDecision(
        move=move,
        variant=variant,
        slots=slots or {},
        reason=reason,
        effects=effects or [],
        continue_turn=cont,
        terminal_status=terminal,
        **kw,  # type: ignore[arg-type]
    )


def E(name: str, /, **data: object) -> Effect:
    return Effect(kind=name, data=dict(data))


# ------------------------------------------------------------------ the agenda


def build_agenda(brief: CallBrief) -> list[tuple[str, int]]:
    items: list[tuple[str, int]] = [("purpose", 0)]
    items += [("message", i) for i in range(len(brief.must_say))]
    items += [("ask", i) for i in range(len(brief.ask_list))]
    return items


def _item_decision(
    brief: CallBrief, st: CallState, idx: int, *, again: bool = False
) -> MoveDecision:
    kind, n = st.agenda[idx]
    user = brief.user_name
    deliver = E("delivered", idx=idx)
    if kind == "purpose":
        return D(
            Move.STATE_PURPOSE,
            "purpose",
            slots={"user": user, "purpose": brief.goal_spoken or brief.goal},
            effects=[deliver],
            reason="state the purpose",
        )
    if kind == "message":
        return D(
            Move.STATE_PURPOSE,
            "message",
            slots={"message": brief.must_say[n]},
            effects=[deliver],
            reason="deliver a must_say item",
        )
    return D(
        Move.ASK,
        "followup" if again else "question",
        slots={"question": brief.ask_list[n]},
        effects=[deliver],
        reason="ask the next question" if not again else "ask again",
    )


def deliver_next(ctx: PolicyContext, *, cont_after: bool = False) -> MoveDecision:
    st: CallState = ctx.state
    if st.agenda_idx >= len(st.agenda):
        return closing_decision(ctx)
    d = _item_decision(ctx.brief, st, st.agenda_idx)
    # purpose is chained with the first following item in the same breath (first-seconds rule)
    if st.agenda[st.agenda_idx][0] == "purpose" and st.agenda_idx + 1 < len(st.agenda):
        d = d.model_copy(
            update={"continue_turn": True, "effects": d.effects + [E("resume", mode="next")]}
        )
    elif cont_after:
        d = d.model_copy(update={"continue_turn": True})
    return d


def redeliver(ctx: PolicyContext) -> MoveDecision | None:
    """Say the last item again: a question gets the "followup" wording, anything else is re-said
    with another candidate line (the repeat guard never lets the identical line out twice)."""
    st: CallState = ctx.state
    if st.last_item is None:
        return None
    return _item_decision(ctx.brief, st, st.last_item, again=True)


def _current_question(ctx: PolicyContext) -> str:
    st: CallState = ctx.state
    if st.last_item is not None and st.agenda[st.last_item][0] == "ask":
        return ctx.brief.ask_list[st.agenda[st.last_item][1]]
    return ""


def closing_decision(ctx: PolicyContext) -> MoveDecision:
    st: CallState = ctx.state
    user = ctx.brief.user_name
    if "declined" in st.flags:
        return D(Move.CLOSE, "declined", terminal=OutcomeStatus.DECLINED, reason="callee declined")
    if st.approvals:
        return D(
            Move.CLOSE,
            "need_approval",
            slots={"user": user},
            terminal=OutcomeStatus.NEEDS_USER_APPROVAL,
            reason="something needs the user's approval",
        )
    if st.callback_time is not None or "busy" in st.flags:
        return D(
            Move.CLOSE,
            "busy_later",
            terminal=OutcomeStatus.CALL_BACK_LATER,
            reason="callee asked for a call back",
        )
    finished = st.agenda_idx >= len(st.agenda)  # every item was delivered
    done = finished and not st.unanswered
    return D(
        Move.CLOSE,
        "done",
        slots={"user": user},
        terminal=OutcomeStatus.COMPLETED if done else OutcomeStatus.PARTIAL,
        reason="agenda finished",
    )


def forced_close(
    ctx: PolicyContext, variant: str, status: OutcomeStatus, reason: str
) -> MoveDecision:
    return D(
        Move.CLOSE, variant, slots={"user": ctx.brief.user_name}, terminal=status, reason=reason
    )


# ------------------------------------------------------------------ facts about the user

_ALIASES: dict[str, set[str]] = {
    "location": {
        "location",
        "city",
        "place",
        "where",
        "address",
        "kahan",
        "shehar",
        "area",
        "locality",
    },
    "phone": {"phone", "number", "mobile", "contact", "whatsapp", "email", "mail"},
    "address": {"address", "home", "ghar", "pata", "location", "residence"},
    "time": {
        "time",
        "timing",
        "timings",
        "when",
        "schedule",
        "availability",
        "kab",
        "slot",
        "visit",
        "arrival",
        "eta",
    },
    "health": {"health", "medicine", "doctor", "sehat"},
    "money": {"salary", "budget", "money", "price"},
    "job": {"job", "work", "office", "company", "profession", "occupation"},
    "family": {"family", "kids", "children"},
    "identity": {"name", "naam", "age"},
    "availability": {"availability", "free", "schedule", "time", "available"},
}


def match_shareable_fact(brief: CallBrief, u: Understanding) -> tuple[str, str] | None:
    """The shareable fact (key, value) that answers the callee's question, or None. Private facts
    are never consulted; a topic with no shareable key gets the fixed deflection."""
    text = norm(u.text)
    topic = u.topic or "other"
    aliases = _ALIASES.get(topic, set())
    for key, val in brief.shareable_facts.items():
        k = norm(key)
        ktoks = set(k.split())
        if (k and k in text) or (ktoks & aliases):
            return key, val
    return None


# ------------------------------------------------------------------ mandatory responses


def _closing_flag() -> list[Effect]:
    return [E("flag", name="closing")]


def mandatory_decision(ctx: PolicyContext) -> MoveDecision | None:
    st: CallState = ctx.state
    u: Understanding | None = ctx.understanding
    brief = ctx.brief
    user = brief.user_name
    if u is None:
        if not st.disclosed:  # the call is not open yet: greet, then disclose, in that order
            if st.last_move == Move.GREET:
                return D(
                    Move.DISCLOSE,
                    "intro",
                    slots={"user": user},
                    reason="disclosure is always the move right after the greet",
                    effects=[E("awaiting", value="go_ahead")],
                )
            return D(
                Move.GREET,
                "named" if brief.callee_name else "plain",
                slots={"callee": brief.callee_name} if brief.callee_name else {},
                cont=True,
                reason="open the call: greet, then disclose",
                effects=[E("awaiting", value="none")],
            )
        return None
    i = u.intent
    heard = u.text[:80]

    # --- hard stops
    if i == CalleeIntent.STOP_CALLING:
        bots = bool(_BOT_WORDS.search(norm(u.text)))
        return D(
            Move.STOP,
            "no_bots" if bots else "stop_calling",
            slots={"user": user},
            terminal=OutcomeStatus.DO_NOT_CALL,
            reason="callee asked us to stop" + (" / not to talk to a bot" if bots else ""),
            effects=[
                E("do_not_call"),
                E(
                    "next_action",
                    text="Do not call this number again"
                    + (
                        " (the callee does not want to talk to an AI / wants a human)"
                        if bots
                        else ""
                    )
                    + ". Tell the user.",
                ),
            ],
        )
    if i == CalleeIntent.WRONG_NUMBER:
        return D(
            Move.STOP,
            "wrong_number",
            terminal=OutcomeStatus.WRONG_NUMBER,
            reason="wrong person reached",
            effects=[
                E("do_not_call"),
                E(
                    "next_action",
                    text="Wrong person reached: check the number with the user before any retry.",
                ),
            ],
        )
    if i == CalleeIntent.DISTRESS:
        return D(
            Move.STOP,
            "distress",
            slots={"user": user},
            terminal=OutcomeStatus.DISTRESS,
            reason="callee sounded distressed",
            effects=[
                E(
                    "next_action",
                    text=f"URGENT: tell the user now, the person who answered sounded distressed (said: '{heard}').",
                )
            ],
        )
    if i == CalleeIntent.HOSTILE:
        return D(
            Move.STOP,
            "hostile",
            terminal=OutcomeStatus.HOSTILE,
            reason="abuse: end politely",
            effects=[
                E(
                    "next_action",
                    text="The callee was abusive; do not retry without the user's say-so.",
                )
            ],
        )

    # --- honesty first
    if i == CalleeIntent.ARE_YOU_AI:
        return D(
            Move.DISCLOSE,
            "are_you_ai",
            slots={"user": user},
            allow_repeat=True,
            reason="truthful fixed answer to are-you-an-AI",
            effects=[E("flag", name="asked_ai")],
        )
    if i == CalleeIntent.WHO_IS_THIS:
        more = st.agenda_idx == 0
        eff = (
            [E("resume", mode="next")]
            if more
            else ([E("resume", mode="again")] if st.awaiting == "answer" else [])
        )
        return D(
            Move.DISCLOSE,
            "who",
            slots={"user": user},
            cont=bool(eff),
            effects=eff,
            reason="callee asked who this is",
        )

    # --- secrets and personal details
    if i == CalleeIntent.ASKS_PERSONAL_DETAILS:
        if u.detail == "secret":
            if "secret_asked" in st.flags:
                return forced_close(
                    ctx,
                    "unresolved",
                    OutcomeStatus.UNRESOLVED,
                    "asked for OTP/PIN/card twice: end politely",
                )
            return D(
                Move.ANSWER_FROM_BRIEF,
                "secret",
                cont=True,
                reason="never give OTP/PIN/card",
                effects=[
                    E("flag", name="secret_asked"),
                    E(
                        "next_action",
                        text="The callee asked for an OTP/PIN/card/Aadhaar detail. It was refused. Possible scam or a check you should know about.",
                    ),
                    E("resume", mode="again" if st.awaiting == "answer" else "wait"),
                ],
            )
        hit = match_shareable_fact(brief, u)
        if hit:
            return D(
                Move.ANSWER_FROM_BRIEF,
                "fact",
                slots={"fact": hit[1]},
                reason=f"shareable fact '{hit[0]}'",
                cont=st.awaiting == "answer",
                effects=[E("resume", mode="again")] if st.awaiting == "answer" else [],
            )
        return D(
            Move.HANDLE_OBJECTION,
            "asks_personal",
            slots={"user": user},
            reason="personal detail not in the brief",
            cont=False,
            effects=[
                E(
                    "approval",
                    kind="personal_detail",
                    text=heard,
                    reason="the callee asked for a personal detail that is not marked shareable",
                ),
                E("ask_user", question=heard),
                E("flag", name="closing"),
            ],
        )

    # --- money
    if i == CalleeIntent.ASKS_MONEY:
        appr = E(
            "approval",
            kind="payment",
            text=heard,
            reason="the callee asked for money; Friday never pays or promises payment",
        )
        if "money_asked" in st.flags:
            return D(
                Move.HANDLE_OBJECTION,
                "asks_money",
                slots={"user": user},
                cont=True,
                effects=[appr, E("flag", name="closing")],
                reason="money asked again: close",
            )
        return D(
            Move.HANDLE_OBJECTION,
            "asks_money",
            slots={"user": user},
            cont=True,
            effects=[
                appr,
                E("flag", name="money_asked"),
                E("resume", mode="again" if st.awaiting == "answer" else "wait"),
            ],
            reason="money asked: cannot pay or promise",
        )

    # --- availability
    if i == CalleeIntent.BUSY_CALL_BACK_LATER and st.awaiting != "busy_time":
        eff = [E("flag", name="busy")]
        if u.entities.times:
            return D(
                Move.HANDLE_OBJECTION,
                "busy_noted",
                slots={"value": u.entities.times[0]},
                cont=True,
                effects=eff
                + [E("callback_time", value=u.entities.times[0]), E("flag", name="closing")],
                reason="busy and gave a time",
            )
        return D(
            Move.HANDLE_OBJECTION,
            "busy",
            effects=eff + [E("awaiting", value="busy_time")],
            reason="busy: ask when to call back",
        )

    if i == CalleeIntent.ASKS_TO_WAIT:
        return D(Move.HOLD_WAIT, "wait", effects=[E("hold")], reason="callee asked us to wait")

    # --- commitments
    if i == CalleeIntent.PROPOSES_COMMITMENT:
        v = judge_commitment(u, brief.limits)
        if v.allowed:
            value = u.entities.times[0] if u.entities.times else (v.text if v.text else "ye")
            eff = [E("commitment", kind=v.kinds[0], text=v.text)]
            if st.awaiting == "answer":
                eff += [
                    E("answer", question=_current_question(ctx), text=u.text),
                    E("resume", mode="next"),
                ]
            return D(
                Move.CONFIRM,
                "commit_ok",
                slots={"value": value},
                authorizes_commitment=True,
                reason="inside the brief limits",
                cont=st.awaiting == "answer",
                effects=eff,
            )
        eff = [
            E(
                "approval",
                kind=v.kinds[0] if v.kinds[0] != "amount" else "payment",
                text=v.text,
                reason=v.reason,
            ),
            E("flag", name="closing"),
        ]
        if st.awaiting == "answer":
            eff.append(E("answer", question=_current_question(ctx), text=u.text))
        return D(
            Move.CONFIRM,
            "need_user",
            slots={"user": user},
            cont=True,
            reason="commitment outside the limits: " + v.reason,
            effects=eff,
        )

    # --- questions about the user
    if i == CalleeIntent.ASKS_ABOUT_USER:
        resume = [E("resume", mode="again")] if st.awaiting == "answer" else []
        if u.topic == "purpose":
            return D(
                Move.STATE_PURPOSE,
                "purpose",
                slots={"user": user, "purpose": brief.goal_spoken or brief.goal},
                reason="callee asked why we called",
                cont=bool(resume),
                effects=resume,
            )
        hit = match_shareable_fact(brief, u)
        if hit:
            return D(
                Move.ANSWER_FROM_BRIEF,
                "fact",
                slots={"fact": hit[1]},
                reason=f"shareable fact '{hit[0]}'",
                cont=bool(resume),
                effects=resume,
            )
        return D(
            Move.ANSWER_FROM_BRIEF,
            "defer",
            slots={"user": user},
            reason="not marked shareable: fixed deflection",
            cont=bool(resume),
            effects=resume
            + [
                E(
                    "approval",
                    kind="question",
                    text=heard,
                    reason="the callee asked about the user and nothing in the brief is marked shareable for it",
                )
            ],
        )
    return None


# ------------------------------------------------------------------ the default policy


class RuleBasedPolicy:
    async def choose(self, ctx: PolicyContext) -> MoveDecision:
        return self.decide(ctx)

    def decide(self, ctx: PolicyContext) -> MoveDecision:
        md = mandatory_decision(ctx)
        if md is not None:
            return md
        return self.default_decision(ctx)

    # ---------------------------------------------------------
    def default_decision(self, ctx: PolicyContext) -> MoveDecision:
        st: CallState = ctx.state
        u: Understanding | None = ctx.understanding
        brief = ctx.brief
        user = brief.user_name

        if "closing" in st.flags:
            return closing_decision(ctx)

        if u is None:  # a chained step: the engine asked again without a new utterance
            if st.resume_mode == "again":
                d = redeliver(ctx)
                return d if d is not None else deliver_next(ctx)
            if st.resume_mode == "wait":
                return D(
                    Move.HOLD_WAIT,
                    "still_here",
                    silent=True,
                    reason="nothing more to say; wait for the callee",
                )
            return deliver_next(ctx)

        i = u.intent
        aw = st.awaiting

        if i == CalleeIntent.SILENCE:
            if st.silences >= 3:
                return forced_close(
                    ctx,
                    "unresolved",
                    OutcomeStatus.UNRESOLVED,
                    "nobody speaking after three prompts",
                )
            return D(Move.HANDLE_OBJECTION, "silence", reason=f"silence #{st.silences}")

        if i == CalleeIntent.ASKS_TO_REPEAT:
            if aw == "go_ahead" or st.last_item is None:
                return D(
                    Move.DISCLOSE,
                    "who",
                    slots={"user": user},
                    reason="callee did not hear the opening",
                    effects=[E("resume", mode="next")],
                    cont=True,
                )
            return D(
                Move.HANDLE_OBJECTION,
                "repeat_prefix",
                cont=True,
                reason="callee asked to repeat",
                effects=[E("resume", mode="again")],
            )

        if i == CalleeIntent.REFUSES and u.detail == "bare_no" and aw == "answer":
            return self._record_answer(ctx, u)

        if i == CalleeIntent.REFUSES:
            return D(
                Move.HANDLE_OBJECTION,
                "refuses",
                slots={"user": user},
                cont=True,
                reason="callee declined",
                effects=[E("flag", name="declined"), E("flag", name="closing")],
            )

        if i == CalleeIntent.OFF_TOPIC:
            if st.off_topic > 2:
                return forced_close(
                    ctx, "unresolved", OutcomeStatus.UNRESOLVED, "callee keeps going off topic"
                )
            eff = [E("resume", mode="again" if aw == "answer" else "wait")]
            return D(
                Move.HANDLE_OBJECTION,
                "off_topic",
                cont=True,
                effects=eff,
                reason="off topic: one polite redirect",
            )

        stt_bad = u.stt_confidence is not None and u.stt_confidence < 0.4
        if (
            stt_bad
            or i == CalleeIntent.UNKNOWN
            or (u.confidence < 0.5 and i != CalleeIntent.GIVES_ANSWER)
            or (
                i == CalleeIntent.GIVES_ANSWER
                and u.confidence < 0.5
                and aw not in ("answer", "go_ahead")
            )
        ):
            if st.unknown_streak > 2:
                return forced_close(
                    ctx,
                    "unresolved",
                    OutcomeStatus.UNRESOLVED,
                    "could not understand the callee after clarifying",
                )
            return D(
                Move.HANDLE_OBJECTION,
                "clarify",
                reason=f"did not understand (confidence {u.confidence:.2f}): safe clarifying move",
            )

        # ---- replies: agrees / gives_answer / plain no
        if aw == "busy_time":
            val = (
                u.entities.times[0]
                if u.entities.times
                else (norm(u.text) if len(u.text.split()) <= 6 else "")
            )
            if val:
                return D(
                    Move.HANDLE_OBJECTION,
                    "busy_noted",
                    slots={"value": val},
                    cont=True,
                    effects=[E("callback_time", value=val), E("flag", name="closing")],
                    reason="callback time heard",
                )
            return forced_close(
                ctx, "busy_later", OutcomeStatus.CALL_BACK_LATER, "no usable callback time"
            )

        if aw == "readback":
            if i in (CalleeIntent.AGREES,) or (
                i == CalleeIntent.GIVES_ANSWER and bool(u.matched) and not u.entities.times
            ):
                st_val = st.pending_value
                eff = [E("confirmed_readback", value=st_val or "")]
                return self._next_after_answer(ctx, lead=None, extra=eff)
            d = redeliver(ctx)
            if d is not None and st.ask_attempts < 2:
                return d.model_copy(update={"reason": "readback not confirmed: ask again"})
            return self._next_after_answer(ctx, lead=None, extra=[E("unanswered_current")])

        if aw == "returned":  # the callee came back from "ek minute"
            if st.awaiting_before_hold == "answer" and (
                u.entities.times or u.entities.amounts or i == CalleeIntent.GIVES_ANSWER
            ):
                return self._record_answer(ctx, u)
            d = redeliver(ctx)
            if d is not None and st.awaiting_before_hold == "answer":
                return d
            if st.agenda_idx == 0:
                return deliver_next(ctx)
            return (
                deliver_next(ctx)
                if st.awaiting_before_hold in ("ack", "go_ahead")
                else closing_decision(ctx)
            )

        if aw == "go_ahead":
            return deliver_next(ctx)

        if aw == "answer":
            return self._record_answer(ctx, u)

        # aw == "ack" / "none": the callee reacted to a message: move on
        return deliver_next(ctx)

    # ---------------------------------------------------------
    def _record_answer(self, ctx: PolicyContext, u: Understanding) -> MoveDecision:
        st: CallState = ctx.state
        brief = ctx.brief
        q = ""
        if st.last_item is not None and st.agenda[st.last_item][0] == "ask":
            q = brief.ask_list[st.agenda[st.last_item][1]]
        rec = E("answer", question=q, text=u.text)
        ent = u.entities
        value = ent.times[0] if ent.times else (f"{ent.amounts[0]} rupay" if ent.amounts else "")
        if value:
            low = (u.stt_confidence is not None and u.stt_confidence < 0.6) or u.confidence < 0.6
            if low:
                return D(
                    Move.CONFIRM,
                    "readback_check",
                    slots={"value": value},
                    effects=[rec, E("awaiting", value="readback"), E("pending", value=value)],
                    reason="low confidence on a time/amount: read it back as a question",
                )
            return self._next_after_answer(
                ctx,
                lead=D(
                    Move.CONFIRM,
                    "readback_note",
                    slots={"value": value},
                    reason="read back the heard value",
                ),
                extra=[rec],
            )
        return self._next_after_answer(ctx, lead=None, extra=[rec], thanks=True)

    def _next_after_answer(
        self,
        ctx: PolicyContext,
        *,
        lead: MoveDecision | None,
        extra: list[Effect],
        thanks: bool = False,
    ) -> MoveDecision:
        """Emit the lead line (readback / thanks) chained with the next item, or the close."""
        st: CallState = ctx.state
        has_more = st.agenda_idx < len(st.agenda)
        if lead is None and not thanks:
            d = deliver_next(ctx)
            return d.model_copy(update={"effects": extra + d.effects})
        if not has_more:
            if lead is not None:  # speak the readback, then close in the same breath
                return lead.model_copy(
                    update={"continue_turn": True, "effects": extra + [E("resume", mode="next")]}
                )
            d = closing_decision(ctx)
            return d.model_copy(update={"effects": extra + d.effects})
        if lead is None:
            lead = D(Move.CONFIRM, "thanks", reason="thank for the answer")
        return lead.model_copy(
            update={"continue_turn": True, "effects": extra + [E("resume", mode="next")]}
        )
