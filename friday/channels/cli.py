"""``uv run friday chat`` - local WhatsApp simulator in the terminal (no keys needed).

Type as the user. Commands:
  1, 2, 3            tap the numbered button of Friday's last message
  /pin 12.97,77.64   share a location pin
  /voice <words>     send a voice note saying <words>
  /contact +91...    share a contact card
  /image <name>      send an image   /doc <name>  send a PDF
  /as <phone>        switch sender (another user, a circle member, a business)
  /call <phone>      a business calls Friday back   /missed <phone>  a missed call
  /who               show current sender            /quit  exit
"""

from __future__ import annotations

import asyncio
import os
import sys

from friday.core.config import Settings
from friday.core.container import Container
from friday.core.logging import setup_logging
from friday.core.models import OutboundMessage, normalize_phone

DEFAULT_PHONE = "+919900000001"


async def _amain(settings: Settings, phone: str) -> int:
    from friday.api.runtime import Runtime
    from friday.channels.simulator import SimulatorChannel

    c = Container(settings)
    channel = c.messaging
    if not isinstance(channel, SimulatorChannel):
        print("friday chat needs the simulator channel (FRIDAY_MODE=simulator).")
        return 1
    if not settings.admin_phones and settings.invite_only:
        # Local convenience: the default chat user skips the invite step.
        settings.admin_phones = [phone]
    runtime = Runtime(c)
    await runtime.start()
    state = {"phone": phone}

    def show(msg: OutboundMessage) -> None:
        who = "" if msg.to_phone == state["phone"] else f" -> {msg.to_phone}"
        body = channel.render(msg).replace("\n", "\n         ")
        print(f"\nFriday{who}: {body}\n", flush=True)

    channel.subscribe(show)
    print(__doc__)
    print(f"You are {state['phone']}. Say hi!\n")
    try:
        while True:
            try:
                line = await asyncio.to_thread(input, f"[{state['phone']}] > ")
            except (EOFError, KeyboardInterrupt):
                break
            line = line.strip()
            if not line:
                continue
            if line in ("/quit", "/exit"):
                break
            if line == "/who":
                print(state["phone"])
                continue
            if line.startswith(("/as ", "/call ", "/missed ")):
                cmd, _, arg = line.partition(" ")
                try:
                    p = normalize_phone(arg, settings.default_country_code)
                except ValueError:
                    print("invalid phone")
                    continue
                if cmd == "/as":
                    state["phone"] = p
                    continue
                match, _contact = await runtime.callbacks.on_inbound_call(
                    p, None, answered=cmd == "/call"
                )
                ctx = await runtime.callbacks.safe_context(match)
                print(f"[call from {p}: {match.status.value}] {runtime.callbacks.greeting(ctx)}")
                continue
            msg = channel.make_inbound(
                state["phone"], line, default_cc=settings.default_country_code
            )
            await runtime.handle(msg)
            await asyncio.sleep(0)
    finally:
        channel.unsubscribe(show)
        await runtime.stop()
        await c.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = Settings()
    if settings.is_live:
        print("friday chat runs in simulator mode only (unset FRIDAY_MODE=live).")
        return 1
    setup_logging(os.environ.get("FRIDAY_CHAT_LOG_LEVEL", "WARNING"), False)
    args = argv if argv is not None else sys.argv[2:]
    phone = DEFAULT_PHONE
    if args:
        phone = normalize_phone(args[0], settings.default_country_code)
    return asyncio.run(_amain(settings, phone))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
