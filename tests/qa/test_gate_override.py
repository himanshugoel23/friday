"""The QA override inside the real W1 CallGate: caps and calling window lifted ONLY for the
allow-listed number and ONLY while a QA session is open. Uses the W1 in-memory fakes."""

from __future__ import annotations

from friday.calls.gate import Verdict
from friday.calls.models import CalleeKind
from friday.calls.settings import CallsSettings
from friday.calls.stores import AttemptRecord
from friday.qa import override
from friday.qa.override import QaSession
from tests.calls.conftest import MUMMY, PLUMBER, World, build_world
from tests.calls.test_gate import decide, make
from tests.qa.conftest import make_settings


def _world(allow: list[str]) -> World:
    return build_world(core=make_settings(pilot_allowed_numbers=allow))


async def _fill_caps(w: World, number: str) -> None:
    h = w.hasher.hash(number)
    for _ in range(10):  # per-user daily cap
        await w.store.record_attempt(AttemptRecord(w.user.id, "r", h, w.clock.now(), 10))


async def test_without_a_session_the_caps_still_apply() -> None:
    w = _world([MUMMY])
    await _fill_caps(w, MUMMY)
    req, brief = await make(w)
    d = await decide(w, req, brief)
    assert d.verdict == Verdict.DENY and d.reasons[0] in {"user_daily_calls", "number_day_cap"}


async def test_in_a_session_the_caps_are_lifted_for_the_number() -> None:
    w = _world([MUMMY])
    await _fill_caps(w, MUMMY)
    req, brief = await make(w)
    override.activate(QaSession("r1", "consumer_family", target=MUMMY))
    try:
        d = await decide(w, req, brief)
    finally:
        override.deactivate()
    assert d.verdict == Verdict.ALLOW


async def test_in_a_session_the_calling_window_is_lifted_for_the_number() -> None:
    w = _world([MUMMY])
    req, brief = await make(w, kind=CalleeKind.BUSINESS)
    at_night = w.at(23, 30)
    assert (await decide(w, req, brief, at_night)).verdict == Verdict.ASK  # normal: outside window
    override.activate(QaSession("r1", "salon_quote", target=MUMMY))
    try:
        assert (await decide(w, req, brief, at_night)).verdict == Verdict.ALLOW
    finally:
        override.deactivate()


async def test_override_does_not_lift_anything_for_another_number() -> None:
    # the session targets MUMMY but the request is for PLUMBER (and the list is not exactly [MUMMY])
    w = _world([MUMMY, PLUMBER])
    await _fill_caps(w, PLUMBER)
    req, brief = await make(w, number=PLUMBER)
    override.activate(QaSession("r1", "x", target=MUMMY))
    try:
        d = await decide(w, req, brief)
    finally:
        override.deactivate()
    assert d.verdict == Verdict.DENY


async def test_override_never_lifts_the_allow_list_dnc_or_kill_switch() -> None:
    w = _world([PLUMBER])  # MUMMY is NOT allow-listed
    req, brief = await make(w, number=MUMMY)
    override.activate(QaSession("r1", "x", target=PLUMBER))
    try:
        d = await decide(w, req, brief)
    finally:
        override.deactivate()
    assert d.verdict == Verdict.DENY and d.reasons == ["test_allowlist"]
    killed = build_world(
        settings=CallsSettings(enabled=False), core=make_settings(pilot_allowed_numbers=[MUMMY])
    )
    req, brief = await make(killed)
    override.activate(QaSession("r1", "x", target=MUMMY))
    try:
        assert (await decide(killed, req, brief)).reasons == ["kill_switch"]
    finally:
        override.deactivate()
