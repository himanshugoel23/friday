# ruff: noqa: E501
"""Move state machine, the policy interface and the pending lines catalog."""

from __future__ import annotations

import re

import pytest

from friday.liveagent import lines as L
from friday.liveagent.contracts import CalleeKind, CallLanguage
from friday.liveagent.moves import (
    KIND_MOVES,
    TERMINAL_MOVES,
    TRANSITIONS,
    CallState,
    LLMMovePolicy,
    Move,
    PolicyContext,
    allowed_next,
    transition_ok,
)
from friday.liveagent.ports import HeardUtterance
from friday.liveagent.rules import RuleBasedPolicy, build_agenda
from friday.liveagent.simulation.briefs import make_brief
from friday.liveagent.understand_callee import understand

ALL_PREV = [None, *Move]


@pytest.mark.parametrize("prev", ALL_PREV)
@pytest.mark.parametrize("nxt", list(Move))
@pytest.mark.parametrize("kind", list(CalleeKind))
def test_every_transition_matches_the_table(prev: Move | None, nxt: Move, kind: CalleeKind) -> None:
    expected = nxt in TRANSITIONS[prev] and nxt in KIND_MOVES[kind]
    assert transition_ok(prev, nxt, kind) is expected


def test_disclosure_is_always_right_after_greet() -> None:
    nxt = TRANSITIONS[Move.GREET]
    assert Move.DISCLOSE in nxt
    for content in (Move.STATE_PURPOSE, Move.ASK, Move.ANSWER_FROM_BRIEF, Move.CONFIRM):
        assert content not in nxt
    assert Move.GREET in TRANSITIONS[None] and Move.ASK not in TRANSITIONS[None]


def test_terminal_moves_have_no_successor() -> None:
    for m in TERMINAL_MOVES:
        assert TRANSITIONS[m] == frozenset()


def test_stop_is_reachable_from_every_non_terminal_move() -> None:
    for prev in (None, *[m for m in Move if m not in TERMINAL_MOVES and m != Move.VOICEMAIL]):
        assert Move.STOP in TRANSITIONS[prev]


def test_voicemail_only_for_personal_callees() -> None:
    for kind in (CalleeKind.CUSTOMER_CARE, CalleeKind.OFFICIAL, CalleeKind.BUSINESS):
        assert Move.VOICEMAIL not in allowed_next(None, kind)
    for kind in (CalleeKind.FAMILY_ELDER, CalleeKind.FRIEND, CalleeKind.UNKNOWN):
        assert Move.VOICEMAIL in allowed_next(None, kind)


def _ctx(text: str, awaiting: str = "none") -> PolicyContext:
    brief = make_brief(CalleeKind.FAMILY_ELDER, CallLanguage.HINGLISH)
    st = CallState(kind=brief.relationship, language=brief.language)
    st.agenda = build_agenda(brief)
    st.disclosed = True
    st.last_move = Move.DISCLOSE
    st.awaiting = awaiting
    u = understand(HeardUtterance(text=text))
    return PolicyContext(
        brief=brief,
        kind=st.kind,
        state=st,
        understanding=u,
        allowed=allowed_next(st.last_move, st.kind),
    )


class FakeModel:
    def __init__(self, out: dict | Exception) -> None:
        self.out = out

    async def propose(self, payload: dict) -> dict:
        assert "private_facts" not in str(payload) and "Metformin" not in str(payload)
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


async def test_llm_policy_accepts_a_valid_grounded_move() -> None:
    ctx = _ctx("haan boliye", "go_ahead")
    q = ctx.brief.ask_list[0]
    pol = LLMMovePolicy(FakeModel({"move": "ask", "variant": "question", "slots": {"question": q}}))
    d = await pol.choose(ctx)
    assert d.source == "llm" and d.move == Move.ASK and not pol.rejected


@pytest.mark.parametrize(
    "out",
    [
        {
            "move": "ask",
            "variant": "question",
            "slots": {"question": "Aapka salary kitna hai?"},
        },  # ungrounded slot
        {"move": "close", "variant": "done", "slots": {}},  # the model may not end the call
        {"move": "nonsense", "variant": "x"},
        {"move": "ask", "variant": "no_such_variant", "slots": {}},
        {"move": "ask", "variant": "question", "slots": {}},  # missing slot
        {"move": "greet", "variant": "plain", "slots": {}},  # illegal after disclose
        {
            "move": "answer_from_brief",
            "variant": "fact",
            "slots": {"fact": "Rs 85000 per month"},
        },  # a private fact
        RuntimeError("boom"),
    ],
)
async def test_llm_policy_rejects_invalid_output_and_falls_back(out: dict | Exception) -> None:
    ctx = _ctx("haan boliye", "go_ahead")
    pol = LLMMovePolicy(FakeModel(out))
    d = await pol.choose(ctx)
    assert pol.rejected and d.source == "rules"


async def test_llm_policy_cannot_override_mandatory_rules() -> None:
    ctx = _ctx("dobara call mat karna")
    pol = LLMMovePolicy(
        FakeModel(
            {"move": "ask", "variant": "question", "slots": {"question": ctx.brief.ask_list[0]}}
        )
    )
    d = await pol.choose(ctx)
    assert d.move == Move.STOP and d.source == "rules"


async def test_rule_policy_is_deterministic() -> None:
    a = await RuleBasedPolicy().choose(_ctx("haan boliye", "go_ahead"))
    b = await RuleBasedPolicy().choose(_ctx("haan boliye", "go_ahead"))
    assert a == b


# ------------------------------------------------------------------ lines


def test_all_lines_pending_and_ids_unique() -> None:
    lines = L.all_lines()
    assert len(lines) > 250
    assert len({pl.id for pl in lines}) == len(lines)
    assert all(pl.status == "PENDING_FOUNDER_APPROVAL" for pl in lines)
    assert L.LINE_STATUS == "PENDING_FOUNDER_APPROVAL"


def test_every_variant_has_all_three_languages_and_same_slots() -> None:
    for (move, variant), by_rel in L._CATALOG.items():
        assert "*" in by_rel, (move, variant)
        slot_sets = set()
        for rel, by_lang in by_rel.items():
            assert set(by_lang) == set(L.LANGS), (move, variant, rel)
            for lang, texts in by_lang.items():
                assert texts, (move, variant, rel, lang)
                for t in texts:
                    slot_sets.add(frozenset(re.findall(r"{(\w+)}", t)) - {"ack"})
        assert len(slot_sets) <= 2, (move, variant, slot_sets)


SLOT_SAMPLES = {
    "user": "Rohan", "callee": "Mummy ji", "purpose": "kal doctor", "message": "dawai lena",
    "question": "kya aap theek hain?", "fact": "wo shaam tak aa jayenge", "value": "kal shaam 5 baje",
}  # fmt: skip


@pytest.mark.parametrize("kind", list(CalleeKind))
@pytest.mark.parametrize("lang", list(CallLanguage))
def test_every_line_renders_for_every_kind_and_language(
    kind: CalleeKind, lang: CallLanguage
) -> None:
    for move_name, variant in L._CATALOG:
        move = Move(move_name)
        r = L.render(move, variant, kind, lang, SLOT_SAMPLES)
        assert r and "{" not in r.text and r.text.strip()


def test_lines_never_claim_to_be_the_user() -> None:
    bad = [
        r"\b(main|mai)\s+\{user\}\s+(bol|hoon|hu)",
        r"\b(this is|i am|i'm)\s+\{user\}\b(?!'s)",
        r"मैं\s+\{user\}\s+(बोल|हूँ)",
    ]
    for pl in L.all_lines():
        for pat in bad:
            assert not re.search(pat, pl.text, re.I), pl.id


def test_no_digits_except_the_emergency_number() -> None:
    for pl in L.all_lines():
        digits = re.findall(r"\d+", pl.text)
        assert digits in ([], ["112"]), pl.id
        if digits:
            assert pl.move == "stop" and pl.variant == "distress"


def test_are_you_ai_answers_are_truthful_in_every_language() -> None:
    for pl in L.all_lines():
        if (pl.move, pl.variant) == ("disclose", "are_you_ai"):
            assert re.search(r"\bAI\b|ए आई", pl.text), pl.id
            assert not re.search(r"not an? (ai|robot)|nahi hoon|insaan hoon|human", pl.text, re.I)


def test_disclosure_lines_name_an_assistant() -> None:
    for pl in L.all_lines():
        if (pl.move, pl.variant) in {
            ("disclose", "intro"),
            ("disclose", "who"),
            ("voicemail", "message"),
        }:
            assert re.search(r"assistant|असिस्टेंट", pl.text, re.I), pl.id
            assert "{user}" in pl.text


def test_hindi_lines_are_devanagari_and_hinglish_lines_are_roman() -> None:
    for pl in L.all_lines():
        has_dev = bool(re.search(r"[ऀ-ॿ]", pl.text))
        if pl.language == "hi":
            assert has_dev, pl.id
        else:
            assert not has_dev, pl.id


def test_same_line_never_twice_in_a_row() -> None:
    first = L.render(Move.HANDLE_OBJECTION, "silence", CalleeKind.FRIEND, CallLanguage.EN, {})
    second = L.render(
        Move.HANDLE_OBJECTION, "silence", CalleeKind.FRIEND, CallLanguage.EN, {}, avoid=[first.text]
    )
    assert second and second.text != first.text
    third = L.render(
        Move.HANDLE_OBJECTION,
        "silence",
        CalleeKind.FRIEND,
        CallLanguage.EN,
        {},
        avoid=[first.text, second.text],
    )
    assert third is None  # both wordings were just said
    only = L.render(
        Move.STOP,
        "hostile",
        CalleeKind.FRIEND,
        CallLanguage.EN,
        {},
        avoid=[L.render(Move.STOP, "hostile", CalleeKind.FRIEND, CallLanguage.EN, {}).text],
    )
    assert only is None  # a single wording repeated would trip the repeat guard


def test_ack_never_repeats_the_last_two() -> None:
    seen: list[str] = []
    for _ in range(8):
        a = L.pick_ack(CallLanguage.HINGLISH, seen)
        assert a not in seen[-2:]
        seen.append(a)


def test_missing_slot_raises() -> None:
    with pytest.raises(L.MissingSlot):
        L.render(Move.ASK, "question", CalleeKind.FRIEND, CallLanguage.EN, {})
