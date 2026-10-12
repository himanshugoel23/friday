"""``friday whatsapp-sim``: chat through the whole quotes flow in the terminal, offline.

Everything is simulated (fake WhatsApp, the simworld directory with Gurgaon and Bangalore
salons, simulated telephony and salons, the fake LLM); no keys, no network, no real call.
Type as the user. Numbers tap the buttons of Friday's last message.

  1, 2, 3            tap the numbered button        /pin 28.42,77.10   share a location pin
  /voice <words>     send a voice note              /tick              run the timers now
  /skip <minutes>    nothing (real time is used)    /quit              exit

Try:  kal shaam parlour mein haircut karwana hai, quotes chahiye   ->   Sector 56 Gurgaon  ->  1
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from friday.core.config import Settings
from friday.core.container import Container
from friday.core.logging import setup_logging
from friday.core.models import (
    Language,
    OnboardingStep,
    OutboundMessage,
    Profile,
    User,
    UserStatus,
    normalize_phone,
)


async def _amain(args: Any) -> int:
    from friday.api.runtime import Runtime
    from friday.channels.simulator import SimulatorChannel

    over: dict[str, Any] = dict(
        _env_file=None,  # offline: never reads .env, never uses a real key
        directory_provider="simulator",
        geocoder_provider="simulator",
        whatsapp_provider="simulator",
        database_url="sqlite+aiosqlite:///:memory:",
        mode="simulator", quotes_flow_enabled=True, playbooks_enabled=True, invite_only=False,
        quotes_retry_after_min=1,
    )
    if not args.real_hours:
        over.update(quotes_call_window_start="00:00", quotes_call_window_end="23:59")
    if args.redirect:
        over["vendor_call_redirect_to"] = args.redirect
    settings = Settings(**over)
    c = Container(settings)
    await c.db.create_all()
    channel = c.messaging
    if not isinstance(channel, SimulatorChannel):
        print("whatsapp-sim needs the simulator channel.")
        return 1
    phone = normalize_phone(args.phone, settings.default_country_code)
    users = c.repos.users
    user = await users.get_by_phone(phone)
    if user is None:
        user = await users.add(User(phone=phone, status=UserStatus.ACTIVE, invites_remaining=0))
        user.onboarding_step = OnboardingStep.DONE
        await users.save(user)
        await c.repos.profiles.save(
            Profile(user_id=user.id, name=args.name, city="Gurgaon", language=Language(args.lang))
        )
    runtime = Runtime(c)
    await runtime.start()

    def show(msg: OutboundMessage) -> None:
        body = channel.render(msg).replace("\n", "\n         ")
        print(f"\nFriday: {body}\n", flush=True)

    channel.subscribe(show)

    async def ticker() -> None:
        while True:
            await asyncio.sleep(2)
            await runtime.pipeline.quotes.tick()

    tick_task = asyncio.create_task(ticker())
    print(__doc__)
    if args.redirect:
        print(f"[TEST REDIRECT] vendor calls dial {settings.vendor_call_redirect_to} (simulated)\n")
    try:
        while True:
            try:
                line = await asyncio.to_thread(input, f"[{phone}] > ")
            except (EOFError, KeyboardInterrupt):
                break
            line = line.strip()
            if not line:
                continue
            if line in ("/quit", "/exit"):
                break
            if line == "/tick":
                await runtime.pipeline.quotes.tick()
                continue
            msg = channel.make_inbound(phone, line, default_cc=settings.default_country_code)
            await runtime.handle(msg)
            await asyncio.sleep(0)
    finally:
        tick_task.cancel()
        channel.unsubscribe(show)
        await runtime.stop()
        await c.aclose()
    return 0


def run(args: Any) -> int:
    setup_logging(os.environ.get("FRIDAY_CHAT_LOG_LEVEL", "WARNING"), False)
    if Settings().is_live:
        print("friday whatsapp-sim runs in simulator mode only (unset FRIDAY_MODE=live).")
        return 1
    return asyncio.run(_amain(args))
