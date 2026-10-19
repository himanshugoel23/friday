"""``friday consumer demo``: the consumer beta on a fake WhatsApp, entirely offline.

Runs two scenarios and prints the WhatsApp transcript:

  calls    "mummy ko phone karke bata do ki main late hoon" -> approval -> Approve -> the task
           engine's job -> the W2 live engine against a SIMULATED callee -> report with buttons
  savings  "HDFC Regalia aur SBI Cashback hai" -> "Zomato pe 640" -> ranked answer with a reason,
           then a forwarded electricity bill -> confirmation -> reminders on the right days

Nothing here touches a network, reads .env or dials anything: simulator messaging, an in-memory
SQLite database, a persona instead of a phone line, invented numbers, invented EXAMPLE card rows.
Every user-facing and spoken line shown is PENDING founder approval (hear-before-change).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from typing import Any

from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.core.clock import IST, FakeClock, ist_date
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import Language, Profile, User, UserStatus
from friday.db import Database
from friday.integration.sim import PersonaTelephony, demo_card_rules
from friday.integration.wiring import attach, build_stack
from friday.savings.config import SavingsConfig

USER_PHONE = "+919800000001"  # invented
MUMMY = "+919000000001"  # invented
BANNER = (
    "OFFLINE DEMO. Fake WhatsApp, a simulated callee (no phone line), no network, no real number.\n"
    "Card rules are INVENTED example rows. Every line below is PENDING founder approval."
)


class Demo:
    def __init__(self, c: Container, channel: SimulatorChannel, clock: FakeClock, user: User):
        self.c, self.channel, self.clock, self.user = c, channel, clock, user
        self.router = c.get("consumer")
        self.lines: list[str] = []

    def _show(self, msgs: list[Any]) -> None:
        for m in msgs:
            for ln in self.channel.render(m).splitlines():
                self.lines.append(f"  Friday: {ln}" if ln is not None else "")

    async def say(self, text: str) -> None:
        self.lines.append(f"You: {text}")
        before = len(self.channel.messages_to(USER_PHONE))
        from friday.api.runtime import Runtime

        rt = getattr(self, "_rt", None) or Runtime(self.c, fast_pin_hash=True)
        self._rt = rt
        await rt.handle(self.channel.make_inbound(USER_PHONE, text))
        self._show(self.channel.messages_to(USER_PHONE)[before:])

    async def tap(self, number: int, title: str) -> None:
        self.lines.append(f"You tap: {title}")
        before = len(self.channel.messages_to(USER_PHONE))
        await self._rt.handle(self.channel.make_inbound(USER_PHONE, str(number)))
        self._show(self.channel.messages_to(USER_PHONE)[before:])

    async def jobs(self, label: str) -> None:
        self.lines.append(f"-- {label} --")
        before = len(self.channel.messages_to(USER_PHONE))
        await self.c.get("task_engine").drain()
        self._show(self.channel.messages_to(USER_PHONE)[before:])

    async def tick(self, when: datetime, label: str) -> None:
        self.clock.set(when)
        self.lines.append(f"-- {label} --")
        before = len(self.channel.messages_to(USER_PHONE))
        await self.c.get("proactive").tick()
        self._show(self.channel.messages_to(USER_PHONE)[before:])


async def build_demo(*, start: datetime | None = None) -> Demo:
    settings = Settings(
        _env_file=None,
        mode="simulator",
        env="dev",
        database_url="sqlite+aiosqlite:///:memory:",
        anthropic_api_key=None,
        sarvam_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        google_places_api_key=None,
        consumer_calls_enabled=True,
        savings_enabled=True,
        lifestate_enabled=True,
        google_enabled=False,
    )
    clock = FakeClock(start or datetime(2026, 1, 5, 10, 0, tzinfo=IST))
    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=clock)
    c.override_db(db)
    c.install_field_cipher()  # the app's field encryption, from the local dev key of this run
    channel = SimulatorChannel(clock, dict(settings.whatsapp_templates))
    c.override("messaging", channel)
    c.override("sms", FakeSMS(dict(settings.sms_dlt_templates), clock))
    telephony = PersonaTelephony({MUMMY: "friendly_elder"})

    async def send(user_id: str, text: str, buttons: Any) -> None:
        await c.get("notifier").notify_user(user_id, text, buttons=list(buttons))

    router = build_stack(
        settings=settings, clock=clock, repos=c.repos, send=send, queue=c.get("job_queue"),
        telephony=telephony, savings_config=SavingsConfig(allow_example_rules=True),
    )  # fmt: skip
    assert router is not None
    c.override("consumer", router)
    attach(router, task_engine=c.get("task_engine"), proactive=c.get("proactive"))
    user = await c.repos.users.add(User(phone=USER_PHONE, status=UserStatus.ACTIVE))
    await c.repos.profiles.save(Profile(user_id=user.id, name="Rahul", language=Language.HINGLISH))
    assert router.calls is not None and router.savings is not None
    await router.calls.contacts.add(
        user.id, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother", confirmed=True
    )
    for rule in demo_card_rules(ist_date(clock.now())):
        await router.savings.rules.upsert(rule)
    return Demo(c, channel, clock, user)


async def scenario_calls(d: Demo) -> None:
    d.lines.append("=== Scenario: a call to Mummy ===")
    await d.say("mummy ko phone karke bata do ki main late hoon")
    await d.tap(1, "Approve")
    await d.jobs("the task engine runs the call job; the live engine talks to a simulated Mummy")
    line = d.router.calls.orchestrator.engine.results[-1]  # type: ignore[union-attr]
    d.lines.append("-- what Friday said on the (simulated) line --")
    for t in line.friday_lines:
        d.lines.append(f"  Friday (call): {t}")


async def scenario_savings(d: Demo) -> None:
    d.lines.append("=== Scenario: which card, and a bill ===")
    await d.say("mere paas HDFC Regalia aur SBI Cashback hai")
    await d.say("Zomato pe 640")
    await d.say(
        "Your electricity bill of Rs 1,240.50 for BSES is due on 25 Jan 2026. "
        "Pay online at bsesdelhi.com"
    )
    await d.tap(1, "Sahi hai")
    await d.tick(datetime(2026, 1, 22, 9, 30, tzinfo=IST), "22 Jan 09:30: one proactive tick")


SCENARIOS = {"calls": scenario_calls, "savings": scenario_savings}


async def run_demo(which: str = "all") -> list[str]:
    d = await build_demo()
    try:
        names = list(SCENARIOS) if which == "all" else [which]
        for n in names:
            await SCENARIOS[n](d)
        return [BANNER, "", *d.lines]
    finally:
        await d.c.aclose()
        from friday.core.crypto import set_field_cipher

        set_field_cipher(None)  # leave the process as we found it


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser("consumer", help="consumer beta tools (offline)")
    cs = p.add_subparsers(dest="consumer_cmd", required=True)
    demo = cs.add_parser("demo", help="print the WhatsApp transcript of the consumer scenarios")
    demo.add_argument("--scenario", choices=["all", *SCENARIOS], default="all")


def run_command(args: argparse.Namespace) -> int:
    if args.consumer_cmd == "demo":
        for line in asyncio.run(run_demo(args.scenario)):
            print(line)
        return 0
    return 2
