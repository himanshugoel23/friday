# ruff: noqa: E501
"""T03: every consent grant / withdrawal / pause / resume is audited with ACTOR, TIME and SOURCE; the admin can never resume
a parent-paused family; a paused parent's device signals are dropped server-side (through the HTTP API). Fakes only."""

from __future__ import annotations

from friday.core.models import Channel, InboundMessage, MessageKind
from friday.robin.models import ConsentSource, FamilyStatus
from tests.robin.conftest import CHILD_PHONE
from tests.robin.test_erase_all import B, Phone
from tests.robindevice.conftest import ev

ACTORS = {"admin_on_behalf", "user", "guardian"}


async def trail(w, fam, *events):
    return [r for r in await w.store.list(fam.id, "audit") if r.data.get("event") in events]


def complete(rec) -> bool:
    d = rec.data
    return d.get("actor") in ACTORS and bool(d.get("source")) and bool(d.get("at")) and rec.at is not None


async def test_admin_grant_is_audited_with_actor_source_and_time(w):
    fam, parent = await w.family(consent=False)
    assert await w.hub.fam.admin_consent(fam, "daily_checkin_calls") == "given"
    (rec,) = await trail(w, fam, "consent")
    assert rec.data["actor"] == "admin_on_behalf" and rec.data["source"] == "admin_chat" and rec.data["given_by"] == "admin_on_behalf" and complete(rec)


async def test_guardian_mode_is_the_actor_when_it_is_on(w):
    fam, parent = await w.family(consent=False)
    assert await w.hub.fam.set_guardian(fam, "power of attorney, 2026")
    fam = await w.store.get_family(fam.id)
    await w.hub.fam.admin_consent(fam, "medicine_reminders")
    assert (await trail(w, fam, "consent"))[-1].data["actor"] == "guardian"


async def test_parents_own_yes_and_every_withdrawal_carry_actor_and_source(w):
    fam, parent = await w.family(consent=False)
    await w.hub.fam.give_consent(parent.id, "scam_check", ConsentSource.VOICE_YES, given_by="user")
    assert await w.hub.fam.withdraw_consent(parent.id, "scam_check", tell_child=False, actor="user", source="parent_device")
    await w.hub.fam.give_consent(parent.id, "medicine_reminders", ConsentSource.ADMIN_CHAT, given_by="admin_on_behalf")
    assert await w.hub.fam.withdraw_consent(parent.id, "medicine_reminders", tell_child=False, actor="admin_on_behalf", source="admin_chat")
    rows = await trail(w, fam, "consent")
    assert [(r.data["actor"], r.data["source"]) for r in rows] == [("user", "voice_yes"), ("user", "parent_device"), ("admin_on_behalf", "admin_chat"), ("admin_on_behalf", "admin_chat")]
    assert all(complete(r) for r in rows)


async def test_the_chat_disable_command_and_the_phone_withdrawal_are_attributed(w):
    fam, parent = await w.family()
    msg = InboundMessage(channel=Channel.SIMULATOR, from_phone=CHILD_PHONE, text="disable medicine reminders", kind=MessageKind.TEXT)
    await w.hub.handle(w.child_user, msg)
    from friday.robin.wiring import _DeviceConsent

    await w.hub.fam.admin_consent(fam, "device_signals")
    await _DeviceConsent(w.hub).set(parent.id, "calls", False, "app")
    withdrawals = [r for r in await trail(w, fam, "consent") if "withdrew" in r.data["text"]]
    assert {(r.data["actor"], r.data["source"]) for r in withdrawals} == {("admin_on_behalf", "admin_chat"), ("user", "parent_device")}


async def test_pause_and_resume_are_audited_and_the_whole_trail_is_complete(w):
    fam, parent = await w.family()
    await w.hub.fam.admin_consent(fam, "scam_check")
    await w.hub.fam.request_consent(fam, "payment_alerts")
    await w.hub.fam.pause(parent.id, "voice")
    await w.hub.fam.resume(parent.id, "voice")
    await w.hub.fam.pause(parent.id, "widget")
    rows = await trail(w, fam, "consent", "consent_request", "pause", "resume")
    assert {r.data["event"] for r in rows} == {"consent", "consent_request", "pause", "resume"}
    assert all(complete(r) for r in rows), [(r.data["event"], r.data.get("actor"), r.data.get("source")) for r in rows if not complete(r)]
    assert [r.data["source"] for r in rows if r.data["event"] in ("pause", "resume")] == ["voice", "voice", "widget"]


async def test_the_admin_cannot_resume_a_parent_paused_family(w):
    fam, parent = await w.family()
    await w.hub.fam.pause(parent.id, "voice")
    assert (await w.store.get_family(fam.id)).status == FamilyStatus.PAUSED
    assert not await w.hub.fam.resume(parent.id, "admin_chat", actor="admin_on_behalf")
    assert not await w.hub.fam.resume(parent.id, "admin_chat", actor="guardian")
    assert (await w.store.get_member(parent.id)).paused and (await w.store.get_family(fam.id)).status == FamilyStatus.PAUSED
    refused = await trail(w, fam, "resume_refused")
    assert [r.data["actor"] for r in refused] == ["admin_on_behalf", "guardian"] and all(complete(r) for r in refused)
    assert await w.hub.fam.admin_consent(fam, "device_signals") == "parent_paused"  # sensitive items wait for the parent
    assert await w.hub.fam.resume(parent.id, "voice")  # only the parent
    assert (await w.store.get_family(fam.id)).status == FamilyStatus.ACTIVE


async def test_a_parent_who_paused_during_setup_is_not_activated_by_the_admins_consent(w):
    fam, parent = await w.family(consent=False, notified=False)
    assert fam.status == FamilyStatus.ONBOARDING
    parent.paused = True
    await w.store.save_member(parent, fam.owner_user_id)
    assert await w.hub.fam.admin_consent(fam, "daily_checkin_calls") == "given"  # not sensitive: recorded
    assert (await w.store.get_family(fam.id)).status == FamilyStatus.PAUSED  # but the admin did not undo the parent's stop


async def test_paused_parent_device_signals_are_dropped_server_side_until_the_parent_resumes(w, db):
    fam, parent = await w.family()
    await w.hub.fam.admin_consent(fam, "device_signals")
    phone = Phone(w, db)
    await phone.pair(parent.id)
    ms = int(w.clock.now().timestamp() * 1000)

    async def send():
        r = await phone.client.post(f"{B}/signals", headers=phone.h(), json={"events": [ev("camera_in_use_start", ms)]})
        assert r.status_code == 200
        return r.json()

    assert (await send())["accepted"] == 1
    await w.hub.fam.pause(parent.id, "voice")
    out = await send()
    assert out["accepted"] == 0 and out["dropped_no_consent"] == 1
    await w.hub.fam.resume(parent.id, "admin_chat", actor="admin_on_behalf")  # refused
    assert (await send())["accepted"] == 0
    await w.hub.fam.resume(parent.id, "voice")
    assert (await send())["accepted"] == 1
    await phone.client.aclose()
