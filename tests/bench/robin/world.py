# ruff: noqa: E501
"""A throw-away Robin world for the evaluation flow cases: in-memory SQLite, fake clock, fake caller, recording sender. Nothing is dialled or sent."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.events import EventBus
from friday.core.models import User, UserStatus
from friday.db import Database
from friday.robin.alerts import RobinAlert
from friday.robin.context import Ctx
from friday.robin.gate import AllowAllGate
from friday.robin.models import ConsentSource, Tier
from friday.robin.ports import FakeParentCaller, FakeParentChannel, RecordingSender
from friday.robin.store import RobinStore
from friday.robin.wiring import RobinHub

CHILD_PHONE = "+919800000101"  # invented
PARENT_PHONE = "+919800000102"
SECOND_PHONE = "+919800000103"


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        anthropic_api_key=None,
        sarvam_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        google_places_api_key=None,
    )


async def run_flow(case: dict[str, Any]) -> dict[str, Any]:
    """Raise one alert in a fresh world and report what happened (counts and booleans only)."""
    settings = _settings()
    settings.brand_name = "Robin"
    clock = FakeClock(datetime(2026, 1, 5, 10, 0, tzinfo=IST))
    db = Database(settings.database_url)
    await db.create_all()
    container = Container(settings, clock=clock, bus=EventBus())
    container.override_db(db)
    try:
        child_user = await container.repos.users.add(
            User(phone=CHILD_PHONE, status=UserStatus.ACTIVE)
        )
        store = RobinStore(container.repos.db, clock)
        caller, sender, channel = FakeParentCaller(), RecordingSender(), FakeParentChannel()
        ctx = Ctx(
            store=store,
            clock=clock,
            send=sender,
            caller=caller,
            gate=AllowAllGate(),
            users=container.repos.users,
            settings=settings,
            parent_channel=channel,
        )
        hub = RobinHub(ctx)
        fam = await hub.fam.create_family(
            child_user, parent_label="Papa", child_name="Asha", child_language="en"
        )
        parent = await hub.fam.add_parent(fam, PARENT_PHONE, language="hinglish")
        child = await ctx.child(fam)
        child.call_ok = True
        await store.save_member(child, fam.owner_user_id)
        if case.get("second"):
            await hub.fam.set_second_contact(fam, SECOND_PHONE, "Uncle")
        if not case.get("not_active"):
            await hub.fam.update_settings(fam, checkin_time="09:00")
            for item in (
                "daily_checkin_calls",
                "medicine_reminders",
                "scam_check",
                "share_summary_with_child",
            ):
                await hub.fam.give_consent(parent.id, item, ConsentSource.ADMIN_CHAT)
            await hub.intro.notify_parent(fam)
            fam = await store.get_family(fam.id)
            await hub.fam.admin_consent(fam, "device_signals")
            await hub.fam.admin_consent(fam, "payment_alerts")
        if case.get("paused"):
            await hub.fam.pause(parent.id, "voice")
        clock.set(datetime(2026, 1, 5, int(case["hour"]), int(case.get("minute", 0)), tzinfo=IST))
        sent_before = len(sender.sent)
        calls_before = len(caller.calls)
        if case.get("unanswered"):
            from friday.robin.models import CallResult

            caller.script(CallResult.NO_ANSWER)
        alert = RobinAlert(
            parent_member_id=parent.id,
            tier=Tier[case["tier"]],
            scenario=case["scenario"],
            why="evaluation case",
            money=bool(case.get("money")),
            dedupe_key=f"eval:{case['id']}",
        )
        res = await hub.alerts.raise_alert(alert)
        for _ in range(8):
            clock.advance(minutes=3)
            await hub.alerts.tick()
        calls = caller.calls[calls_before:]
        return {
            "accepted": bool(res.accepted),
            "child_told": len(sender.sent) > sent_before,
            "child_rings": len([c for c in calls if c.role == "child"]),
            "parent_calls": len([c for c in calls if c.role == "parent"]),
        }
    finally:
        await container.aclose()
        await db.dispose()
