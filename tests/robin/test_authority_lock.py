# ruff: noqa: E501
"""T06 authority lock: with EVERY Robin switch on nothing in the graph can place a call to 112/100/101/102/108/1930 (the CallGate path and
TelephonyParentCaller refuse independently), and DRY_RUN=false without a live adapter refuses and alerts instead of silently working.
Tested with fakes; no real call is placed or simulated."""

from __future__ import annotations

import pytest

from friday.core.models import User, UserStatus
from friday.robin.authority import DryRunAuthorityCaller
from friday.robin.models import CallOutcome, CallResult, Family, Member, Role
from friday.robin.store import Record
from friday.robin.telephony import TelephonyParentCaller
from friday.robin.wiring import build_robin
from tests.robin.conftest import PARENT_PHONE

NUMBERS = ["112", "100", "101", "102", "108", "1930", "+91112", "+911930", "0112", "1-1-2", "00911930", "91 108"]
NO = CallOutcome(result=CallResult.NO_ANSWER)


class RecordingTelephony:
    def __init__(self) -> None:
        self.placed: list[object] = []

    async def place_call(self, req):  # noqa: ANN001, ANN201
        self.placed.append(req)
        raise AssertionError("a call was placed")


def switches_on(settings) -> None:
    settings.robin_enabled = True
    settings.robin_device_enabled = True
    settings.robin_authority_calls_enabled = True
    settings.robin_safe_word_enabled = True
    settings.robin_screen_unknown_enabled = True
    settings.robin_listen_in_enabled = True
    settings.robin_waitlist_enabled = True
    settings.robin_authority_dry_run = True


def member(number: str, role: Role = Role.PARENT) -> Member:
    return Member(family_id="f1", role=role, phone=number, language="hinglish", name="Test")


async def test_every_switch_on_no_object_in_the_graph_can_dial_an_emergency_number(container, settings):
    switches_on(settings)
    settings.pilot_allowed_numbers = [PARENT_PHONE, *NUMBERS]  # even an allow-list that names them must not help
    hub = build_robin(container)
    assert hub is not None
    tel = RecordingTelephony()
    caller = hub.ctx.caller
    assert isinstance(caller, TelephonyParentCaller)
    real = TelephonyParentCaller(tel, settings)
    fam = Family(owner_user_id="u1", parent_label="Papa")
    for num in NUMBERS:
        for c in (real, caller):
            out = await c.converse(member=member(num), family=fam, purpose="nudge", steps=[], dedupe_key="k", brand="Robin")
            assert out.result == CallResult.REFUSED and out.detail == "emergency_number", num
            out = await c.bridge(child=member(num, Role.CHILD), parent=member(PARENT_PHONE), family=fam, dedupe_key="k", brand="Robin")
            assert out.result == CallResult.REFUSED and out.detail == "emergency_number", num
        owner = User(phone="+919800000199", status=UserStatus.ACTIVE)
        gate = await hub.ctx.gate.check(owner, num, override_window=True, now=hub.ctx.clock.now())
        assert gate.allowed is False, num
    assert tel.placed == []
    assert isinstance(hub.authority.caller, DryRunAuthorityCaller) and hub.authority.caller.live is False
    assert hub.authority._dry() is True


async def test_emergency_refusal_comes_before_the_qa_override_and_the_pending_lines_check(settings):
    settings.pilot_allowed_numbers = ["+919800000102"]
    real = TelephonyParentCaller(RecordingTelephony(), settings)
    assert real._refusal("112", []).detail == "emergency_number"
    other = real._refusal(None, [])
    assert other is not None and other.detail != "emergency_number"


async def desk(w):
    fam, parent = await w.family(second=False, checkin="21:30")
    parent.name, parent.address = "Ramesh Kumar", "12 Park Road, Delhi"
    await w.store.save_member(parent, fam.owner_user_id)
    await w.hub.fam.admin_consent(fam, "device_signals")
    await w.hub.fam.admin_consent(fam, "authority_calls")
    w.settings.robin_authority_calls_enabled = True
    return fam, parent


async def test_dry_run_false_without_a_live_adapter_refuses_and_alerts_the_founder(w):
    fam, parent = await desk(w)
    w.settings.robin_authority_dry_run = False  # the dangerous setting
    w.hub.authority.caller = DryRunAuthorityCaller()  # there is NO live adapter in this repo
    ops: list[str] = []

    async def ops_sender(text: str) -> None:
        ops.append(text)

    w.ctx.extra_senders["ops"] = ops_sender
    w.caller.script(NO)
    await w.hub.sos.trigger(parent.id, "app")
    for _ in range(10):
        w.go(minutes=3)
        await w.hub.tick()
    assert w.hub.authority.caller.logged == []
    assert ops and "misconfigured" in ops[0] and "Ramesh" not in ops[0] and "Park Road" not in ops[0]
    assert not [r for r in await w.store.list(fam.id, "pending") if r.status in ("placed", "dry_run", "countdown")]
    audit = [r.data["text"] for r in await w.store.list(fam.id, "audit") if r.data["event"] == "authority"]
    assert any("no_live_adapter" in t for t in audit)
    assert not any("Contacted" in t for t in audit)


async def test_dry_run_false_refuses_even_when_a_countdown_was_somehow_started(w):
    fam, parent = await desk(w)
    now = w.clock.now()
    auth, _ = await w.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="pending", key="auth:x", status="countdown", at=now, due_at=now, data={"incident_id": "x", "category": "physical", "what": "medical"}))
    w.settings.robin_authority_dry_run = False
    w.hub.authority.caller = DryRunAuthorityCaller()
    out = await w.hub.authority._place(fam, parent, auth, "x")
    assert out.startswith("refused:") and w.hub.authority.caller.logged == []
    assert (await w.store.get(auth.id)).status == "refused"


@pytest.mark.parametrize("dry", [True, False])
async def test_switch_off_means_off_whatever_dry_run_says(w, dry):
    fam, parent = await desk(w)
    w.settings.robin_authority_calls_enabled = False
    w.settings.robin_authority_dry_run = dry
    w.caller.script(NO)
    await w.hub.sos.trigger(parent.id, "app")
    for _ in range(10):
        w.go(minutes=3)
        await w.hub.tick()
    assert w.hub.authority.caller.logged == []
    _ = fam
