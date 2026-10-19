"""CallGate: one test per rule. The gate is plain code, so every rule is checked on its own."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from friday.calls.gate import CallGate, Verdict, in_window, next_window_start
from friday.calls.models import CallBrief, CalleeKind, CallRequest, Limits
from friday.calls.settings import CallsSettings
from friday.calls.stores import AttemptRecord
from friday.core.config import Settings
from friday.core.models import User, UserStatus
from tests.calls.conftest import MUMMY, PLUMBER, World, build_world


async def make(
    w: World, *, kind=CalleeKind.FAMILY_FRIEND, number=MUMMY, approved=True, confirmed=True,
    goal="bata do ki main late hoon", raw=None, limits=None,
):  # fmt: skip
    req = CallRequest(
        user_id=w.user.id, callee_kind=kind, purpose=goal, callee_name="Mummy",
        callee_number=number, number_confirmed=confirmed, raw_text=raw,
    )  # fmt: skip
    brief = CallBrief(
        request_id=req.id, user_id=w.user.id, callee_kind=kind, callee_name="Mummy", goal=goal,
        callee_number_hash=w.hasher.hash(number) if number else None, limits=limits or Limits(),
    )  # fmt: skip
    if approved:
        brief = w.approval.approve(brief, brief.content_hash()[:8], w.clock.now())
    return req, brief


async def decide(w: World, req, brief, now=None):
    return await w.gate.decide(req, brief, w.user, now or w.clock.now())


async def test_allow_when_everything_is_in_order(world: World):
    req, brief = await make(world)
    d = await decide(world, req, brief)
    assert d.verdict == Verdict.ALLOW and d.max_duration_s == 300


async def test_kill_switch_setting_and_pause_flag(tmp_path):
    w = build_world(settings=CallsSettings(enabled=False))
    req, brief = await make(w)
    d = await decide(w, req, brief)
    assert d.verdict == Verdict.DENY and d.reasons == ["kill_switch"]
    paused = Settings(_env_file=None, paused=True)
    w2 = build_world(core=paused)
    req, brief = await make(w2)
    assert (await decide(w2, req, brief)).reasons == ["kill_switch"]
    flag = tmp_path / "PAUSED"
    flag.write_text("x")
    w3 = build_world(core=Settings(_env_file=None, pause_file=str(flag)))
    req, brief = await make(w3)
    assert (await decide(w3, req, brief)).reasons == ["kill_switch"]


async def test_per_kind_switch():
    w = build_world(settings=CallsSettings(disabled_kinds="unknown, group"))
    req, brief = await make(w, kind=CalleeKind.UNKNOWN)
    assert (await decide(w, req, brief)).reasons == ["kind_disabled"]
    req, brief = await make(w, kind=CalleeKind.FAMILY_FRIEND)
    assert (await decide(w, req, brief)).allowed


async def test_user_must_be_active_and_not_banned(world: World):
    req, brief = await make(world)
    world.user.status = UserStatus.SUSPENDED
    assert (await decide(world, req, brief)).reasons == ["user_not_active"]
    world.user.status = UserStatus.ACTIVE
    for _ in range(3):
        await world.store.add_strike(world.user.id, "threat", world.clock.now())
    assert (await decide(world, req, brief)).reasons == ["user_blocked"]


async def test_brief_must_belong_to_the_request(world: World):
    req, brief = await make(world)
    other = brief.model_copy(update={"request_id": "someone-elses"})
    assert (await decide(world, req, other)).reasons == ["brief_mismatch"]


@pytest.mark.parametrize(
    "number",
    ["112", "100", "101", "102", "108", "1091", "1098", "+91112", "+91 112", "0112", "00 91 112",
     "1-1-2", "91100", "+911098", "tel:108", "181"],
)  # fmt: skip
async def test_emergency_numbers_are_never_dialled(world: World, number):
    req, brief = await make(world, number=number)
    d = await decide(world, req, brief)
    assert d.verdict == Verdict.DENY
    assert d.reasons == ["emergency_number"] and d.refusal_key == "refuse_emergency_number"


async def test_emergency_by_name_even_without_number(world: World):
    req, brief = await make(world, number=MUMMY)
    req.callee_ref = "112"
    assert (await decide(world, req, brief)).reasons == ["emergency_number"]


@pytest.mark.parametrize("number", ["12345", "+91 98", "abc", "+91 90000 0000"])
async def test_invalid_numbers_are_refused(world: World, number):
    req, brief = await make(world, number=number)
    d = await decide(world, req, brief)
    assert d.verdict == Verdict.DENY and d.reasons[0] in ("invalid_number", "emergency_number")


async def test_missing_number_is_denied(world: World):
    req, brief = await make(world, number=None)
    assert (await decide(world, req, brief)).reasons == ["no_number"]


async def test_test_mode_allow_list_is_preserved():
    core = Settings(
        _env_file=None, pilot_block_business_calls=True, pilot_allowed_numbers=[MUMMY]
    )  # fmt: skip
    w = build_world(core=core)
    req, brief = await make(w, number=MUMMY)
    assert (await decide(w, req, brief)).allowed
    req, brief = await make(w, number=PLUMBER)
    d = await decide(w, req, brief)
    assert d.verdict == Verdict.DENY and d.reasons == ["test_allowlist"]


async def test_do_not_call_registry_blocks(world: World):
    await world.dnc.add(MUMMY, "opt_out_call")
    req, brief = await make(world)
    d = await decide(world, req, brief)
    assert d.reasons == ["dnc"] and d.refusal_key == "deny_dnc"
    # the same number in another written form is the same entry
    req, brief = await make(world, number="090000 00001")
    assert (await decide(world, req, brief)).reasons == ["dnc"]


async def test_dnc_wins_over_a_valid_approval(world: World):
    req, brief = await make(world)
    assert brief.is_approved_as_is()
    await world.dnc.add(MUMMY, "wrong_person")
    assert not (await decide(world, req, brief)).allowed


@pytest.mark.parametrize(
    "text,category",
    [
        ("usko dhamki dene ke liye call karo", "threat"),
        ("bolo ki main bank se hoon aur OTP maango", "scam"),
        ("mere dost ko prank call karo", "prank"),
        ("unse bolo ki main Rahul bol raha hoon", "impersonation"),
        ("usko 50 baar call karke pareshan karo", "harassment"),
        ("dawai batao bukhar ke liye", "medical_advice"),
        ("I want to end my life", "self_harm"),
    ],
)
async def test_classifier_is_wired_into_the_gate(world: World, text, category):
    req, brief = await make(world, goal=text, raw=text)
    d = await decide(world, req, brief)
    assert d.verdict == Verdict.DENY and d.category == category and d.refusal_key


async def test_user_daily_call_cap(world: World):
    req, brief = await make(world)
    for _ in range(10):
        await world.store.record_attempt(
            AttemptRecord(world.user.id, "r", "h", world.clock.now(), 10)
        )
    d = await decide(world, req, brief)
    assert d.reasons == ["user_daily_calls"]
    tomorrow = world.clock.now() + timedelta(days=1)
    assert (await decide(world, req, brief, tomorrow)).reasons != ["user_daily_calls"]


async def test_user_daily_minute_cap(world: World):
    req, brief = await make(world)
    await world.store.record_attempt(
        AttemptRecord(world.user.id, "r", "h", world.clock.now(), 26 * 60)
    )
    # 26 min used + 5 min planned > 30
    assert (await decide(world, req, brief)).reasons == ["user_daily_minutes"]
    short = brief.model_copy(update={"limits": Limits(max_duration_s=120)})
    short = world.approval.approve(
        short.model_copy(update={"approved": False}), short.content_hash()[:8], world.clock.now()
    )
    assert (await decide(world, req, short)).allowed  # 26 + 2 <= 30


async def test_per_recipient_day_cap_counts_all_users(world: World):
    req, brief = await make(world)
    h = world.hasher.hash(MUMMY)
    for uid in ("other-1", "other-2", "other-3"):  # three DIFFERENT users already called today
        await world.store.record_attempt(AttemptRecord(uid, "r", h, world.clock.now(), 5))
    assert (await decide(world, req, brief)).reasons == ["number_day_cap"]


async def test_per_recipient_week_cap(world: World):
    req, brief = await make(world)
    h = world.hasher.hash(MUMMY)
    for i in range(2, 8):
        when = world.clock.now() - timedelta(days=i % 6 + 1)
        await world.store.record_attempt(AttemptRecord("someone", "r", h, when, 5))
    assert (await decide(world, req, brief)).reasons == ["number_week_cap"]


async def test_max_duration_is_clamped(world: World):
    req, brief = await make(world, limits=Limits(max_duration_s=9999))
    assert (await decide(world, req, brief)).max_duration_s == 300
    req, brief = await make(world, limits=Limits(max_duration_s=90))
    assert (await decide(world, req, brief)).max_duration_s == 90


async def test_approval_missing_stale_expired_and_number_swap(world: World):
    req, brief = await make(world, approved=False)
    assert (await decide(world, req, brief)).reasons == ["approval_missing"]
    req, brief = await make(world)
    edited = brief.model_copy(update={"goal": "bata do ki main kal aaunga"})  # edit after approval
    assert (await decide(world, req, edited)).reasons == ["approval_stale"]
    fake_flag = brief.model_copy(update={"approval_hash": "deadbeef"})
    assert (await decide(world, req, fake_flag)).reasons == ["approval_stale"]
    later = world.clock.now() + timedelta(hours=25)
    assert (await decide(world, req, brief, later)).reasons == ["approval_expired"]
    req.callee_number = PLUMBER  # someone changed the number after the user approved
    assert (await decide(world, req, brief)).reasons == ["approval_stale"]


async def test_number_must_be_confirmed_back(world: World):
    req, brief = await make(world, confirmed=False)
    d = await decide(world, req, brief)
    assert d.verdict == Verdict.ASK and d.reasons == ["number_unconfirmed"]


async def test_calling_window_by_kind(world: World):
    cases = {
        CalleeKind.BUSINESS: ((8, 59), (9, 0), (18, 59), (19, 0)),
        CalleeKind.CUSTOMER_CARE: ((8, 59), (9, 0), (18, 59), (19, 0)),
        CalleeKind.FAMILY_FRIEND: ((7, 59), (8, 0), (21, 29), (21, 30)),
    }
    for kind, (before, start, last, end) in cases.items():
        req, brief = await make(world, kind=kind)
        for hm, expect in ((before, False), (start, True), (last, True), (end, False)):
            d = await decide(world, req, brief, world.at(*hm))
            assert (d.verdict == Verdict.ALLOW) is expect, (kind, hm)
            if not expect:
                assert d.verdict == Verdict.ASK and "outside_window" in d.reasons
                assert d.defer_until and in_window(kind.value, d.defer_until, world.settings)


async def test_windows_are_configurable():
    s = CallsSettings(window_business="10:00-12:00", window_family_friend="06:00-23:00")
    w = build_world(settings=s)
    assert next_window_start("business", w.at(13), s) == w.at(10, day=6)
    assert in_window("family_friend", w.at(22, 30), s)


async def test_deny_beats_ask(world: World):
    """An unapproved brief for a do-not-call number is a refusal, not a question."""
    await world.dnc.add(MUMMY, "opt_out_call")
    req, brief = await make(world, approved=False, confirmed=False)
    assert (await decide(world, req, brief)).verdict == Verdict.DENY


async def test_group_parent_needs_size_and_approval(world: World):
    req = CallRequest(
        user_id=world.user.id, callee_kind=CalleeKind.GROUP, purpose="party",
        group_members=[f"m{i}" for i in range(11)],
    )  # fmt: skip
    brief = CallBrief(
        request_id=req.id, user_id=world.user.id, callee_kind=CalleeKind.GROUP, goal="party"
    )
    assert (await decide(world, req, brief)).reasons == ["group_too_big"]
    req.group_members = ["a", "b"]
    assert (await decide(world, req, brief)).reasons == ["approval_missing"]
    brief = world.approval.approve(brief, brief.content_hash()[:8], world.clock.now())
    assert (await decide(world, req, brief)).allowed


def test_gate_is_not_a_model_call():
    """The gate module imports no model client: the model only proposes."""
    import friday.calls.gate as g

    src = Path(g.__file__).read_text()
    assert "anthropic" not in src and "openai" not in src


def test_gate_class_signature():
    import inspect

    sig = inspect.signature(CallGate.decide)
    assert list(sig.parameters)[1:] == ["request", "brief", "user", "now"]
    assert User  # imported for the signature check above
