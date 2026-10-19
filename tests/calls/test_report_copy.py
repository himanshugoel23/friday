"""Reports, privacy scrubbing and the rules on the user-facing text module."""

from __future__ import annotations

import logging
import re

import pytest

from friday.calls import copy
from friday.calls.models import (
    CallBrief,
    CalleeKind,
    CallOutcome,
    CallRequest,
    Commitment,
    NextAction,
    OutcomeStatus,
)
from friday.calls.privacy import scrub
from friday.calls.report import ReportBuilder, parse_action
from tests.calls.conftest import MUMMY, World

B = ReportBuilder()


def pair(**kw):
    req = CallRequest(
        user_id="u1", callee_kind=CalleeKind.FAMILY_FRIEND, purpose="late", callee_name="Mummy",
        callee_number=MUMMY,
    )  # fmt: skip
    brief = CallBrief(
        request_id=req.id, user_id="u1", callee_kind=CalleeKind.FAMILY_FRIEND, goal="late",
        private_facts=["meri FD 5 lakh ki hai"], **kw,
    )  # fmt: skip
    return req, brief


def out(req, status, **kw):
    return CallOutcome(request_id=req.id, status=status, **kw)


def test_completed_report_has_answers_and_next_buttons():
    req, brief = pair()
    r = B.single(
        req, brief, out(req, OutcomeStatus.COMPLETED, summary="Wo ghar par hain.",
                        answers={"kab aayenge": "shaam 6 baje"}),
    )  # fmt: skip
    assert "Mummy se baat ho gayi" in r.text and "shaam 6 baje" in r.text
    assert len(r.buttons) <= 3 and r.actions[0] == NextAction.DONE
    assert not r.urgent


def test_commitments_needing_approval_are_listed_separately():
    req, brief = pair()
    o = out(
        req, OutcomeStatus.COMPLETED, summary="Theek hai.",
        commitments=[Commitment(text="Rs 600 dena hoga", needs_user_approval=True),
                     Commitment(text="shaam ko milenge")],
        needs_user_approval=["visit Sunday 10am"],
    )  # fmt: skip
    r = B.single(req, brief, o)
    assert "Tay hua: shaam ko milenge" in r.text
    assert "Rs 600 dena hoga" in r.text and "visit Sunday 10am" in r.text
    assert r.actions[:2] == [NextAction.APPROVE_COMMITMENT, NextAction.DECLINE_COMMITMENT]


@pytest.mark.parametrize(
    "status,needle",
    [
        (OutcomeStatus.NO_ANSWER, "phone nahi uthaya"),
        (OutcomeStatus.BUSY, "busy"),
        (OutcomeStatus.VOICEMAIL, "voicemail"),
        (OutcomeStatus.DECLINED, "mana kar diya"),
        (OutcomeStatus.CALLBACK_LATER, "baad mein call"),
        (OutcomeStatus.FAILED, "technical"),
        (OutcomeStatus.SAFETY_STOP, "rok di"),
        (OutcomeStatus.PARTIAL, "poora nahi"),
    ],
)
def test_every_status_has_a_plain_report(status, needle):
    req, brief = pair()
    r = B.single(req, brief, out(req, status, summary="x"), attempts_used=3)
    assert needle in r.text and r.buttons


def test_wrong_person_is_an_urgent_apology():
    req, brief = pair()
    r = B.single(req, brief, out(req, OutcomeStatus.WRONG_PERSON))
    assert r.urgent and "Maaf" in r.text and "kabhi call nahi" in r.text


def test_opt_out_is_acknowledged_even_on_a_completed_call():
    req, brief = pair()
    r = B.single(req, brief, out(req, OutcomeStatus.COMPLETED, do_not_call_again=True))
    assert "dobara call na karein" in r.text


def test_english_report():
    req, brief = pair(language="en")
    r = B.single(req, brief, out(req, OutcomeStatus.NO_ANSWER), attempts_used=3)
    assert "didn't pick up after 3 tries" in r.text


def test_reports_scrub_numbers_and_private_facts():
    req, brief = pair()
    o = out(
        req, OutcomeStatus.COMPLETED,
        summary=f"Unhone {MUMMY} diya aur bola meri FD 5 lakh ki hai, 98100 11223 par call karo",
        answers={"number": "+91 90000 00001"},
    )  # fmt: skip
    r = B.single(req, brief, o)
    assert "9000000001" not in r.text and "90000 00001" not in r.text
    assert "98100 11223" not in r.text and "FD" not in r.text
    assert "[private]" in r.text and "number ending" in r.text


def test_retry_notice_is_short_and_has_no_number():
    from datetime import datetime

    from friday.core.clock import IST

    req, brief = pair()
    t = B.retry_notice(req, brief, OutcomeStatus.NO_ANSWER, datetime(2026, 1, 5, 12, 0, tzinfo=IST))
    assert "12:00 PM" in t and "9000" not in t


def test_group_report_collects_all_members_and_commitments():
    parent, brief = pair()
    rows = []
    for name, st in (
        ("Raj", OutcomeStatus.COMPLETED),
        ("Amit", OutcomeStatus.NO_ANSWER),
        ("Neha", None),
    ):
        c = CallRequest(user_id="u1", callee_kind=CalleeKind.FAMILY_FRIEND, purpose="p",
                        callee_name=name, parent_id=parent.id)  # fmt: skip
        o = None
        if st:
            o = out(c, st, summary="aa raha hoon" if st == OutcomeStatus.COMPLETED else "",
                    commitments=[Commitment(text="5 log aayenge", needs_user_approval=True)]
                    if name == "Raj" else [])  # fmt: skip
        rows.append((c, o))
    r = B.group(parent, brief, rows)
    assert "1 ne bataya" in r.text and "3 me se" in r.text
    assert "Raj: aa raha hoon" in r.text and "Amit: phone nahi uthaya" in r.text
    assert "Neha: abhi baaki hai" in r.text and "Raj: 5 log aayenge" in r.text


def test_button_ids_round_trip():
    req, brief = pair()
    r = B.single(req, brief, out(req, OutcomeStatus.NO_ANSWER))
    parsed = {parse_action(b.id) for b in r.buttons}
    assert (req.id, NextAction.CALL_AGAIN) in parsed
    assert parse_action("callact:x:launch_missiles") is None and parse_action("nope") is None


def test_scrub_masks_all_number_spellings():
    req, brief = pair()
    for spelling in (MUMMY, "9000000001", "090000 00001", "+91 90000-00001", "91-9000000001"):
        assert "9000000001" not in re.sub(r"\D", "", scrub(f"call {spelling} now", request=req))


# ---------------------------------------------------------------- copy module rules


def test_copy_is_marked_pending_and_covers_both_languages():
    assert copy.PENDING_FOUNDER_APPROVAL is True
    for key, variants in copy.LINES.items():
        assert "hinglish" in variants, key


def test_button_titles_fit_whatsapp():
    for key, variants in copy.LINES.items():
        if key.startswith("btn_"):
            for text in variants.values():
                assert len(text) <= 20, (key, text)


def test_no_line_makes_friday_speak_as_the_user():
    """A5.2: nothing says 'main <name> bol raha hoon' or claims to be the user."""
    pat = re.compile(
        r"main\s+\w+\s+bol\s+(raha|rahi)\s+h(oon|u)|i am the user|this is the user speaking", re.I
    )
    for key, variants in copy.LINES.items():
        for text in variants.values():
            assert not pat.search(text), (key, text)


def test_copy_placeholders_are_all_formattable():
    import string

    for key, variants in copy.LINES.items():
        for text in variants.values():
            fields = {f for _, f, _, _ in string.Formatter().parse(text) if f}
            copy.line(key, "en", **{f: "x" for f in fields})


def test_all_new_user_text_lives_in_copy_only():
    """Other modules only reference copy keys; they do not hold their own Hinglish sentences."""
    import pathlib

    root = pathlib.Path(copy.__file__).parent
    marker = re.compile(r"\b(aap|kijiye|bataiye|karungi|hoon|nahi)\b", re.I)
    allowed = {
        "copy.py",
        "classify.py",
        "dnc.py",
        "understand.py",
        "contacts.py",
        "flow.py",
        "brief.py",
        "fakes.py",
    }
    for path in root.glob("*.py"):
        if path.name in allowed:
            continue
        for lineno, text in enumerate(path.read_text().splitlines(), 1):
            if text.lstrip().startswith(("#", '"""')):
                continue
            assert not marker.search(re.sub(r"#.*", "", text)), (path.name, lineno, text)


def test_logs_carry_no_private_text(world: World, caplog):
    caplog.set_level(logging.DEBUG)
    import asyncio

    async def go():
        await world.contacts.add(
            world.user.id, "Mummy", MUMMY, relationship="mother", confirmed=True
        )
        reply = await world.intake.handle(
            world.user,
            "mummy ko phone karke bata do ki main late hoon, mat batana meri FD 5 lakh ki hai",
            message_id="m1",
        )
        assert "5 lakh" not in reply.text and "[private]" in reply.text
        btn = next(b.id for b in reply.buttons if b.title == "Approve")
        await world.orch.handle_button(world.user.id, btn)
        await world.orch.run_due()

    asyncio.run(go())
    assert "9000000001" not in caplog.text and "5 lakh" not in caplog.text
    assert not any("5 lakh" in t for t in world.notifier.texts())
