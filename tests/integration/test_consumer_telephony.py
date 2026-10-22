"""ConsumerTelephonyFactory: refusals, the approval requirement, outcome mapping, the real leg.

Everything is offline: scripted callees, fake provider legs, invented numbers, no network.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from friday.calls.interfaces import Callee
from friday.calls.models import CalleeKind, CallStatus, Limits, PurposeKind
from friday.calls.models import OutcomeStatus as W1Status
from friday.calls.understand import Draft
from friday.core.config import Settings
from friday.core.interfaces import ProviderError
from friday.core.models import DialStatus
from friday.integration.bridge import DialNotConnected
from friday.integration.sim import PersonaTelephony
from friday.integration.telephony import (
    ConsumerTelephonyFactory,
    DialRefused,
    MeteredPort,
    OpenedLine,
    PersonaLineOpener,
    VobizLineOpener,
    mask2,
    scrub_text,
)
from friday.integration.wiring import build_stack
from friday.liveagent.contracts import CallLanguage
from friday.liveagent.ports import CallDropped, HeardUtterance
from friday.liveagent.simulation.callee import DROP, SimClock, SimTelephony, U
from friday.tasks.number_pool import Pool
from tests.integration.conftest import close_world, make_world

NUM = "+919000000001"
OTHER = "+919000000002"
STRANGER = "+919876500077"


def _read(path: str) -> str:
    return Path(path).read_text()


# ------------------------------------------------------------------------------- the rig
@dataclass
class Rig:
    w: Any
    orch: Any
    factory: ConsumerTelephonyFactory
    opener: Any
    settings: Settings
    tmp: Path

    async def approved(
        self,
        *,
        number: str = NUM,
        goal: str = "main late hoon",
        approve: bool = True,
        scheduled: bool = True,
    ) -> tuple[Any, Any]:
        """A request with a brief, approved as shown (when ``approve``), scheduled by the gate."""
        o = self.orch
        draft = Draft(
            callee_ref="Mummy", callee_kind=CalleeKind.FAMILY_FRIEND, kind_confident=True,
            purpose=goal, purpose_kind=PurposeKind.INFORM, language="hinglish",
            limits=Limits(max_duration_s=150), raw_text=goal,
        )  # fmt: skip
        req, brief, _ = await o.create_from_draft(
            draft, user=self.w.user, message_id=f"m-{number}-{goal}", callee_name="Mummy",
            callee_number=number, number_confirmed=True, kind=CalleeKind.FAMILY_FRIEND,
            relationship="mother", user_display_name="Rahul",
        )  # fmt: skip
        fresh, _ = await o.approval.prepare(req, brief)
        if approve:
            fresh = o.approval.approve(fresh, fresh.content_hash()[:8], self.w.clock.now())
        await o.store.save_brief(fresh)
        if approve:
            res = await o.submit(req.id)
            assert (res.status == CallStatus.SCHEDULED) == scheduled
        return req, fresh

    async def run(self, **kw: Any) -> Any:
        req, _ = await self.approved(**kw)
        return await self.orch.execute(req.id), req

    def callee(self, number: str = NUM) -> Callee:
        return Callee(
            name="Mummy", number=number, kind=CalleeKind.FAMILY_FRIEND, max_duration_s=150
        )


async def make_rig(
    tmp_path: Path,
    *,
    persona: str | None = "friendly_elder",
    dial_status: W1Status | None = None,
    opener: Any = None,
    allow: list[str] | None = None,
    redirect: str | None = None,
    pool: Any = None,
    simulated: bool = False,
    **overrides: Any,
) -> Rig:
    w = await make_world(calls=True, savings=False, lifestate=False)
    update: dict[str, Any] = dict(
        mode="live", profile="pilot", consumer_calls_enabled=True, pilot_block_business_calls=True,
        pilot_allowed_numbers=[NUM] if allow is None else allow, call_record=False,
        vendor_call_redirect_to=redirect, pause_file=str(tmp_path / "PAUSED"),
    )  # fmt: skip
    update.update(overrides)
    s = w.c.settings.model_copy(update=update)
    orch = w.consumer.calls.orchestrator
    sim = PersonaTelephony({(redirect or NUM): persona} if persona else {})
    op = opener or PersonaLineOpener(sim, dial_status=dial_status)
    op.sim = getattr(op, "sim", sim)
    factory = ConsumerTelephonyFactory(
        settings=s, opener=op, gate=orch.gate, store=orch.store, users=orch.users,
        hasher=orch.hasher, calls_settings=orch.settings, pool=pool, clock=w.clock,
        log_dir=tmp_path / "calls", simulated=simulated,
    )  # fmt: skip
    orch.engine.factory, orch.engine.core, orch.gate.core = factory, s, s
    return Rig(w, orch, factory, op, s, tmp_path)


@pytest.fixture
async def rig(tmp_path: Path):  # noqa: ANN201
    r = await make_rig(tmp_path)
    try:
        yield r
    finally:
        await close_world(r.w)


# ------------------------------------------------------------------------------- the happy path
async def test_an_approved_brief_dials_once_and_writes_a_masked_log(rig: Rig, caplog):  # noqa: ANN001
    outcome, req = await rig.run()
    assert outcome.status == W1Status.COMPLETED
    assert rig.opener.dialled == [NUM]  # the one dial, to the allow-listed number
    log = rig.factory.logs[-1]
    assert log.dial_status == "answered" and log.turns >= 2 and log.languages
    assert log.to == mask2(NUM) and log.to.endswith("01") and NUM[4:10] not in log.to
    # transcript and call log exist and carry no full number
    text = _read(log.transcript_path) + _read(log.log_path)
    assert NUM not in text and NUM[3:] not in text
    assert json.loads(_read(log.log_path))["dial_status"] == "answered"
    assert NUM not in caplog.text and NUM[3:] not in caplog.text
    assert (await rig.orch.store.get_request(req.id)).status == CallStatus.COMPLETED


async def test_no_recording_notice_is_ever_spoken(tmp_path: Path):
    r = await make_rig(tmp_path, call_record=True)
    try:
        outcome, _ = await r.run()
        assert outcome.status == W1Status.COMPLETED
        said = " ".join(t for line in r.opener.sim.lines for (t, _l, _t) in line.spoken).lower()
        assert said and "record" not in said and "रिकॉर्ड" not in said
    finally:
        await close_world(r.w)


# ------------------------------------------------------------------------------- refusals
@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        pytest.param({"mode": "simulator"}, "not_live", id="not-live"),
        pytest.param({"profile": "default"}, "profile_not_pilot", id="profile-not-pilot"),
        pytest.param({"consumer_calls_enabled": False}, "switch_off", id="switch-off"),
        pytest.param({"paused": True}, "kill_switch", id="kill-switch-env"),
        pytest.param({"pilot_allowed_numbers": []}, "no_allow_list", id="empty-allow-list"),
    ],
)
async def test_the_factory_refuses_when_the_settings_are_not_live(
    rig: Rig, overrides: dict, code: str
):
    req, brief = await rig.approved()  # approved and scheduled while everything was fine
    rig.factory.settings = rig.factory.settings.model_copy(update=overrides)  # then it changes
    with pytest.raises(DialRefused) as e:
        await rig.factory.authorize(brief, rig.callee())
    assert e.value.code == code
    assert rig.opener.dialled == []


async def test_the_pause_flag_file_is_a_kill_switch_too(rig: Rig, tmp_path: Path):
    req, brief = await rig.approved()
    (tmp_path / "PAUSED").write_text("1")
    with pytest.raises(DialRefused) as e:
        await rig.factory.authorize(brief, rig.callee())
    assert e.value.code == "kill_switch"


async def test_the_w1_kill_switch_setting_refuses(tmp_path: Path):
    from friday.calls.settings import CallsSettings

    r = await make_rig(tmp_path)
    try:
        req, brief = await r.approved()
        r.factory.cs = CallsSettings(enabled=False)
        with pytest.raises(DialRefused) as e:
            await r.factory.authorize(brief, r.callee())
        assert e.value.code == "kill_switch"
    finally:
        await close_world(r.w)


async def test_a_number_that_is_not_allow_listed_is_never_dialled(tmp_path: Path):
    r = await make_rig(tmp_path, allow=[OTHER])  # NUM is not on the list
    try:
        req, brief = await r.approved(scheduled=False)  # the gate denies it at once
        assert (await r.orch.store.get_request(req.id)).status == CallStatus.DENIED
        assert await r.orch.execute(req.id) is None and r.opener.dialled == []
        with pytest.raises(DialRefused):  # and the factory would refuse it too
            await r.factory.authorize(brief, r.callee())
    finally:
        await close_world(r.w)


async def test_the_allow_list_applies_to_the_number_actually_dialled(tmp_path: Path):
    """Redirect to a number that is NOT allow-listed: nothing is dialled. Redirect to another
    allow-listed number: that number (and only that one) is dialled."""
    bad = await make_rig(tmp_path / "a", allow=[NUM], redirect=STRANGER)
    try:
        out, _ = await bad.run()
        assert out is not None and out.status == W1Status.FAILED
        assert bad.opener.dialled == []
    finally:
        await close_world(bad.w)
    good = await make_rig(tmp_path / "b", allow=[NUM, OTHER], redirect=OTHER)
    try:
        out, _ = await good.run()
        assert out is not None and out.status == W1Status.COMPLETED
        assert good.opener.dialled == [OTHER]
    finally:
        await close_world(good.w)


async def test_open_itself_checks_the_dialled_number(rig: Rig):
    req, brief = await rig.approved()
    await rig.factory.authorize(brief, rig.callee())
    with pytest.raises(DialRefused) as e:
        await rig.factory.open(
            brief=SimpleNamespace(limits=SimpleNamespace(max_call_seconds=150)),  # type: ignore[arg-type]
            callee=None,  # type: ignore[arg-type]
            dial_number=STRANGER, from_number=None,
        )  # fmt: skip
    assert e.value.code == "not_allow_listed" and rig.opener.dialled == []


async def test_the_gate_is_asked_again_at_the_last_moment(rig: Rig):
    req, brief = await rig.approved()
    await rig.orch.dnc.add(NUM, "opt_out_call", source="test")  # opted out after scheduling
    with pytest.raises(DialRefused) as e:
        await rig.factory.authorize(brief, rig.callee())
    assert e.value.code.startswith("gate_deny") and "dnc" in e.value.code
    assert rig.opener.dialled == []


async def test_outside_the_calling_window_the_gate_says_no(tmp_path: Path):
    r = await make_rig(tmp_path)
    try:
        req, brief = await r.approved()
        r.w.clock.set(r.w.at(23, 30))  # family/friend window ends 21:30 IST
        with pytest.raises(DialRefused) as e:
            await r.factory.authorize(brief, r.callee())
        assert "outside_window" in e.value.code and r.opener.dialled == []
    finally:
        await close_world(r.w)


async def test_per_number_limits_still_apply(tmp_path: Path):
    from friday.calls.settings import CallsSettings

    r = await make_rig(tmp_path)
    try:
        req, brief = await r.approved()
        r.orch.gate.settings = CallsSettings(number_day_cap=0)
        with pytest.raises(DialRefused) as e:
            await r.factory.authorize(brief, r.callee())
        assert "number_day_cap" in e.value.code
    finally:
        await close_world(r.w)


# ------------------------------------------------------------------------------- the approval
async def test_it_never_dials_without_a_recorded_approval(rig: Rig):
    req, brief = await rig.approved(approve=False)
    assert not brief.approved
    with pytest.raises(DialRefused) as e:
        await rig.factory.authorize(brief, rig.callee())
    assert e.value.code == "no_approved_brief"
    assert rig.opener.dialled == []


async def test_a_brief_edited_after_approval_is_refused(rig: Rig):
    req, brief = await rig.approved()
    edited = brief.model_copy(update={"goal": "kuch aur bolna hai"})  # same hash field, new content
    assert edited.approval_hash and not edited.is_approved_as_is()
    with pytest.raises(DialRefused) as e:
        await rig.factory.authorize(edited, rig.callee())
    assert e.value.code == "no_approved_brief"


async def test_an_approval_for_another_number_is_refused(rig: Rig):
    req, brief = await rig.approved()
    with pytest.raises(DialRefused) as e:
        await rig.factory.authorize(brief, rig.callee(OTHER))
    assert e.value.code == "approval_number_mismatch"


async def test_open_without_authorisation_and_a_second_open_are_refused(rig: Rig):
    req, brief = await rig.approved()
    live = SimpleNamespace(limits=SimpleNamespace(max_call_seconds=150))
    kw: dict[str, Any] = dict(brief=live, callee=None, dial_number=NUM, from_number=None)
    with pytest.raises(DialRefused) as e:
        await rig.factory.open(**kw)
    assert e.value.code == "no_approved_brief"
    await rig.factory.authorize(brief, rig.callee())
    await rig.factory.open(**{**kw, "brief": live_brief_for(brief), "callee": live_callee()})
    with pytest.raises(DialRefused):  # the permit was used up by the first open
        await rig.factory.open(**kw)
    assert rig.opener.dialled == [NUM]


def live_brief_for(brief: Any) -> Any:
    from friday.integration.bridge import to_live_brief

    return to_live_brief(brief, max_call_seconds=150)


def live_callee() -> Any:
    from friday.liveagent.contracts import Callee as LiveCallee
    from friday.liveagent.contracts import CalleeKind as LiveKind

    return LiveCallee(kind=LiveKind.FRIEND, name=None, number=None)


# ------------------------------------------------------------------------------- outcome mapping
@pytest.mark.parametrize(
    ("dial_status", "expect"),
    [
        (W1Status.BUSY, W1Status.BUSY),
        (W1Status.NO_ANSWER, W1Status.NO_ANSWER),
        (W1Status.VOICEMAIL, W1Status.VOICEMAIL),
        (W1Status.FAILED, W1Status.FAILED),
    ],
)
async def test_a_dial_that_reaches_nobody_maps_to_the_matching_outcome(
    tmp_path: Path, dial_status: W1Status, expect: W1Status
):
    r = await make_rig(tmp_path, dial_status=dial_status)
    try:
        outcome, req = await r.run()
        assert outcome.status == expect and outcome.duration_s == 0
        log = r.factory.logs[-1]
        assert log.dial_status == dial_status.value
        # a retry is scheduled by the normal W1 rules (+1 h), and nothing was said
        assert (await r.orch.store.get_request(req.id)).status == CallStatus.SCHEDULED
    finally:
        await close_world(r.w)


@pytest.mark.parametrize(
    ("persona", "expect"),
    [
        ("voicemail_not_allowed", W1Status.VOICEMAIL),  # a mailbox picked up: no message left
        ("line_drops", W1Status.FAILED),  # the line dropped mid-call
        ("carrier_unreachable", W1Status.NO_ANSWER),  # "switched off / not reachable"
        ("stop_calling", W1Status.OPTED_OUT),  # the callee hangs up on us after opting out
        ("long_talker", W1Status.PARTIAL),  # the maximum duration cut the call
        ("friendly_elder", W1Status.COMPLETED),  # Friday finishes and hangs up
    ],
)
async def test_what_happens_on_the_line_maps_to_a_w1_outcome(
    tmp_path: Path, persona: str, expect: W1Status
):
    r = await make_rig(tmp_path, persona=persona)
    try:
        outcome, _ = await r.run()
        assert outcome is not None and outcome.status == expect
        assert r.opener.sim.lines[-1].hung_up  # the line is always hung up
    finally:
        await close_world(r.w)


class _Hangs(SimTelephony):
    """The callee hangs up before saying anything."""


async def test_the_callee_hanging_up_is_a_dropped_call_and_the_line_is_released(tmp_path: Path):
    clock = SimClock()
    line = SimTelephony([DROP], CallLanguage.HINGLISH, clock)

    class Opener:
        dialled: list[str] = []

        async def dial(self, **kw: Any) -> OpenedLine:
            self.dialled.append(kw["to"])
            return OpenedLine(line, clock.now)

    r = await make_rig(tmp_path, opener=Opener())
    try:
        outcome, _ = await r.run()
        assert outcome.status == W1Status.FAILED and line.hung_up
        assert r.factory.logs[-1].ended_by == "line_ended"
    finally:
        await close_world(r.w)


async def test_a_backstop_stop_turns_a_dropped_result_into_cut_off(rig: Rig):
    """If the port had to end the call (the engine's own limit did not), the result says cut-off."""
    from friday.liveagent.contracts import CallOutcome as LiveOutcome
    from friday.liveagent.contracts import LiveCallResult
    from friday.liveagent.contracts import OutcomeStatus as LiveStatus

    req, brief = await rig.approved()
    await rig.factory.authorize(brief, rig.callee())
    lease = await rig.factory.open(
        brief=live_brief_for(brief), callee=live_callee(), dial_number=NUM, from_number=None
    )
    port = lease.port
    port.ended_by = "max_duration"  # type: ignore[attr-defined]
    dropped = LiveCallResult(outcome=LiveOutcome(status=LiveStatus.DROPPED, summary="x"))
    facts = await lease.finish(dropped)  # type: ignore[misc]
    assert facts.status_override == LiveStatus.CUT_OFF
    done = LiveCallResult(outcome=LiveOutcome(status=LiveStatus.COMPLETED, summary="x"))
    port.ended_by = "kill_switch"  # type: ignore[attr-defined]
    assert (await lease.finish(done)).status_override is None  # a finished call stays finished


async def test_the_kill_switch_stops_a_call_in_progress(tmp_path: Path):
    clock = SimClock()
    pause_file = tmp_path / "PAUSED"

    class PausingLine(SimTelephony):
        async def listen(self, timeout_s: float) -> HeardUtterance | None:
            heard = await super().listen(timeout_s)
            if len(self.spoken) >= 1:
                pause_file.write_text("1")  # the founder runs `friday pause` mid-call
            return heard

    line = PausingLine(
        [U("Hello", duration_s=2.0) for _ in range(30)], CallLanguage.HINGLISH, clock, tail="repeat"
    )

    class Opener:
        dialled: list[str] = []

        async def dial(self, **kw: Any) -> OpenedLine:
            self.dialled.append(kw["to"])
            return OpenedLine(line, clock.now)

    r = await make_rig(tmp_path, opener=Opener())
    try:
        outcome, _ = await r.run()
        assert outcome.status == W1Status.PARTIAL  # cut off, not retried
        assert r.factory.logs[-1].ended_by == "kill_switch" and line.hung_up
    finally:
        await close_world(r.w)


# ------------------------------------------------------------------------------- caller id + pool
async def test_the_caller_id_comes_from_the_number_pool_and_is_released(tmp_path: Path):
    seen: dict[str, Any] = {}

    class Spy(PersonaLineOpener):
        async def dial(self, **kw: Any) -> OpenedLine:
            seen["from"] = kw["from_number"]
            return await super().dial(**kw)

    sim = PersonaTelephony({NUM: "friendly_elder"})
    r = await make_rig(
        tmp_path, opener=Spy(sim), friday_numbers=["+918069110001"], number_min_gap_s=600
    )
    try:
        pool = Pool(r.settings, clock=r.w.clock)
        r.factory.pool = pool
        outcome, _ = await r.run()
        assert outcome.status == W1Status.COMPLETED
        assert seen["from"] == "+918069110001"
        assert pool._usage_for("+918069110001").inflight == {}  # the slot was released
        # pacing: an immediate second call on the same number is refused, nothing dialled
        sim.lines.clear()
        out2, _ = await r.run(goal="doosri baar test")
        assert out2.status == W1Status.FAILED and sim.lines == []
    finally:
        await close_world(r.w)


async def test_without_a_pool_the_first_configured_caller_id_is_used(tmp_path: Path):
    seen: dict[str, Any] = {}

    class Spy(PersonaLineOpener):
        async def dial(self, **kw: Any) -> OpenedLine:
            seen["from"] = kw["from_number"]
            return await super().dial(**kw)

    r = await make_rig(
        tmp_path, opener=Spy(PersonaTelephony({NUM: "friendly_elder"})),
        sarvam_caller_ids=["+918069110009"],
    )  # fmt: skip
    try:
        await r.run()
        assert seen["from"] == "+918069110009"
    finally:
        await close_world(r.w)


# ------------------------------------------------------------------------------- recordings
async def test_the_recording_reference_is_stored_with_the_outcome_when_recording_is_on(
    tmp_path: Path,
):
    sim = PersonaTelephony({NUM: "friendly_elder"})
    inner = PersonaLineOpener(sim)

    class Rec:
        sim = inner.sim
        dialled = inner.dialled

        async def dial(self, **kw: Any) -> OpenedLine:
            line = await inner.dial(**kw)

            async def ref() -> str:
                return "https://rec.example.invalid/abc.mp3"

            return OpenedLine(line.port, line.clock, line.user_channel, recording=ref)

    r = await make_rig(tmp_path, opener=Rec(), call_record=True)
    try:
        outcome, req = await r.run()
        assert outcome.recording_ref == "https://rec.example.invalid/abc.mp3"
        stored = await r.orch.store.recordings(r.w.user.id)
        assert [x.ref for x in stored] == [outcome.recording_ref]  # the retention sweep owns it now
    finally:
        await close_world(r.w)


async def test_no_recording_reference_when_recording_is_off(rig: Rig):
    outcome, _ = await rig.run()
    assert outcome.recording_ref is None


# ------------------------------------------------------------------------------- the metered port
class _Inner:
    def __init__(self) -> None:
        self.hangups = 0
        self.said: list[str] = []

    async def speak(self, text: str, language: CallLanguage) -> None:
        self.said.append(text)

    async def listen(self, timeout_s: float) -> HeardUtterance | None:
        return HeardUtterance(text="mera number 9876543210 hai", language="hi")

    async def send_dtmf(self, digits: str) -> None: ...

    async def hangup(self) -> None:
        self.hangups += 1


async def test_the_metered_port_ends_the_call_at_the_hard_limit():
    t = [0.0]
    inner = _Inner()
    port = MeteredPort(inner, clock=lambda: t[0], hard_limit_s=10.0)
    await port.speak("namaste", CallLanguage.HINGLISH)
    t[0] = 10.5
    with pytest.raises(CallDropped):
        await port.listen(5.0)
    assert port.ended_by == "max_duration" and inner.hangups == 1
    await port.hangup()  # idempotent
    assert inner.hangups == 1


async def test_the_metered_port_masks_numbers_the_callee_reads_out_and_times_replies():
    t = [0.0]
    port = MeteredPort(_Inner(), clock=lambda: t[0], hard_limit_s=100.0)
    await port.listen(5.0)
    t[0] = 0.4
    await port.speak("theek hai", CallLanguage.HINGLISH)
    assert "9876543210" not in str(port.turns) and "10" in port.turns[0]["text"]
    assert port.languages == ["hi"] and port.gaps_ms == [pytest.approx(400.0)]


def test_masking_shows_only_the_last_two_digits():
    assert mask2("+919876543210") == "+**********10"
    assert mask2(None) == "<none>"
    assert scrub_text("call 98765 43210 now, room 12") == "call ********10 now, room 12"


# ------------------------------------------------------------------------------- the real leg
class CallEnded(Exception):  # noqa: N818 - the voice stack's own name, matched by class name
    pass


class FakeLeg:
    """Stands in for ``SarvamCallLeg``: no audio, no network."""

    provider = "sarvam"

    def __init__(self, status: DialStatus, script: list[Any], block: str | None = None) -> None:
        self.status_to_give, self.script, self.block_signal = status, list(script), block
        self.from_number = "+918069110001"
        self.spoken: list[str] = []
        self.hangups = 0
        self.reply_gaps = [420.0, 510.0, 980.0]

    async def wait_for_answer(self, timeout_s: float) -> DialStatus:
        return self.status_to_give

    async def speak(self, text: str, language: Any) -> None:
        self.spoken.append(text)

    async def listen(self, timeout_s: float) -> Any:
        if not self.script:
            raise CallEnded()
        item = self.script.pop(0)
        if item == "HANGUP":
            raise CallEnded()
        return SimpleNamespace(
            text=item, language=SimpleNamespace(value="hi"), confidence=0.9,
            audio_class=SimpleNamespace(value="human"), duration_s=2.0,
        )  # fmt: skip

    async def send_dtmf(self, digits: str) -> None: ...

    async def hangup(self) -> None:
        self.hangups += 1

    async def recording_url(self) -> str | None:
        return None


class FakeProvider:
    name = "sarvam"

    def __init__(self, leg: FakeLeg | None = None, error: Exception | None = None) -> None:
        self.leg, self.error = leg, error
        self.requests: list[Any] = []

    async def place_call(self, request: Any) -> FakeLeg:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.leg  # type: ignore[return-value]


def _opener(provider: FakeProvider, **kw: Any) -> VobizLineOpener:
    return VobizLineOpener(lambda: provider, Settings(_env_file=None, **kw))


async def _dial(op: VobizLineOpener, **kw: Any) -> OpenedLine:
    args: dict[str, Any] = dict(
        brief=SimpleNamespace(language=CallLanguage.HINGLISH), callee=None, to=NUM,
        from_number="+918069110001", max_seconds=150, ring_timeout_s=30, call_id="c1", record=False,
    )  # fmt: skip
    return await op.dial(**{**args, **kw})


@pytest.mark.parametrize(
    ("status", "expect"),
    [
        (DialStatus.BUSY, W1Status.BUSY),
        (DialStatus.NO_ANSWER, W1Status.NO_ANSWER),
        (DialStatus.VOICEMAIL, W1Status.VOICEMAIL),
        (DialStatus.FAILED, W1Status.FAILED),
    ],
)
async def test_the_vobiz_opener_maps_dial_statuses_and_hangs_up_a_machine(
    status: DialStatus, expect: W1Status
):
    leg = FakeLeg(status, [])
    with pytest.raises(DialNotConnected) as e:
        await _dial(_opener(FakeProvider(leg)))
    assert e.value.status == expect and leg.hangups == 1


async def test_a_blocked_call_and_a_provider_error_are_failures():
    leg = FakeLeg(DialStatus.FAILED, [], block="blocked")
    with pytest.raises(DialNotConnected) as e:
        await _dial(_opener(FakeProvider(leg)))
    assert e.value.status == W1Status.FAILED
    with pytest.raises(DialNotConnected) as e2:
        await _dial(_opener(FakeProvider(error=ProviderError("sarvam", "boom"))))
    assert e2.value.status == W1Status.FAILED


async def test_the_vobiz_opener_builds_the_provider_request():
    prov = FakeProvider(FakeLeg(DialStatus.ANSWERED, []))
    opened = await _dial(_opener(prov), record=True, max_seconds=120, ring_timeout_s=25)
    req = prov.requests[0]
    assert (req.to_phone, req.from_number, req.max_duration_s, req.ring_timeout_s, req.record) == (
        NUM, "+918069110001", 120, 25, True,
    )  # fmt: skip
    assert opened.from_number == "+918069110001" and opened.recording is not None


async def test_a_whole_call_over_the_vobiz_leg_with_the_production_factory(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    leg = FakeLeg(
        DialStatus.ANSWERED, ["Hello", "Haan bolo beta", "Achha theek hai, bye", "HANGUP"]
    )
    prov = FakeProvider(leg)
    r = await make_rig(tmp_path, opener=_opener(prov), friday_numbers=[], persona=None)
    try:
        outcome, _ = await r.run()
        assert outcome is not None and outcome.status in (W1Status.COMPLETED, W1Status.PARTIAL)
        assert len(prov.requests) == 1 and prov.requests[0].to_phone == NUM
        assert leg.spoken and "Mummy" in leg.spoken[0]  # the approved opening, spoken first
        log = r.factory.logs[-1]
        assert log.reply_gaps_ms == [420, 510, 980]  # from the leg, not re-measured
        assert (log.gap_p50_ms, log.gap_p95_ms) == (510.0, 980.0)
        assert leg.hangups >= 1
        assert NUM not in caplog.text and NUM[3:] not in caplog.text
    finally:
        await close_world(r.w)


# ---------------------------------------------------------------- switch off / wiring
async def test_with_the_switch_off_the_production_line_is_never_built():
    from friday.integration.wiring import Switches

    hook_calls: list[int] = []

    def hook(**parts: Any) -> Any:
        hook_calls.append(1)

    w = await make_world(calls=False, savings=False, lifestate=False)
    try:
        router = build_stack(
            settings=w.c.settings, clock=w.clock, repos=w.c.repos, send=lambda *a: None,  # type: ignore[arg-type,return-value]
            queue=w.c.get("job_queue"), consumer_line=hook,
            switches=Switches(False, False, False, False),
        )  # fmt: skip
        assert router is None and hook_calls == []
        assert w.consumer is None
    finally:
        await close_world(w)


async def test_the_production_line_is_wired_only_when_live_pilot_and_the_switch_is_on(
    tmp_path: Path,
):
    from friday.integration.bridge import RefusingTelephonyFactory
    from friday.integration.wiring import build_consumer

    async def wired(**s: Any) -> Any:
        w = await make_world(calls=True, savings=False, lifestate=False)
        try:
            w.c.settings = w.c.settings.model_copy(update=s)  # the container reads its settings
            router = build_consumer(w.c)
            return router.calls.orchestrator.engine.factory if router and router.calls else None
        finally:
            await close_world(w)

    assert isinstance(await wired(), RefusingTelephonyFactory)  # simulator: refuses, as before
    assert isinstance(
        await wired(mode="live", profile="default"), RefusingTelephonyFactory
    )  # live but not pilot
    live = await wired(mode="live", profile="pilot")
    assert isinstance(live, ConsumerTelephonyFactory) and not live.simulated


def test_no_log_line_in_the_new_modules_formats_a_raw_number():
    """A cheap sweep: the new modules log only masked numbers."""
    root = Path(__file__).resolve().parents[2] / "friday" / "integration"
    for name in ("telephony.py", "call_test.py"):
        for ln, line in enumerate((root / name).read_text().splitlines(), 1):
            if re.search(r"log(?:ger)?\.(?:info|warning|error|debug)\(", line):
                assert "dial_number" not in line and "callee.number" not in line, f"{name}:{ln}"


@pytest.fixture(autouse=True)
def _debug_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="friday")
