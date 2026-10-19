"""One registry for button ids across calls, savings and life state.

Every consumer button id starts with a prefix that names its owner:

  callap:<request>:<approve|edit|cancel>:<hash8>   W1 approval of the call plan
  callact:<request>:<next-action>                  W1 report buttons (call again, stop calling...)
  led:<entry>:<used|other|skip>                    W3 "which card did you use"
  bill:<bill>:<ok|paid|snooze|notmine>             W3 bill reminders
  life:<action>[:<ref>]                            W4 life state (``undo``)

``dispatch`` returns None for an id that is not ours (the pipeline then carries on exactly as it
did before), and a ``Handled`` for ours, even when the button is stale or belongs to someone else:
such a tap is swallowed without a reply and never reaches another handler. A handler that raises
is logged by type only and swallowed too: a button must never take the conversation down.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from friday.core.logging import get_logger
from friday.core.models import ReplyButton

log = get_logger(__name__)

PREFIXES = ("callap", "callact", "led", "bill", "life")


@dataclass
class Handled:
    """What to send back (may be nothing: the call orchestrator replies by its own notifier)."""

    text: str | None = None
    buttons: list[ReplyButton] = field(default_factory=list)


Handler = Callable[[str, str], Awaitable[Handled | None]]  # (user_id, button_id)


def prefix_of(button_id: str | None) -> str | None:
    head = (button_id or "").split(":", 1)[0]
    return head if head in PREFIXES else None


class ButtonRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, prefix: str, handler: Handler) -> None:
        if prefix not in PREFIXES:
            raise ValueError(f"unknown button prefix {prefix!r}")
        self._handlers[prefix] = handler

    def owns(self, button_id: str | None) -> bool:
        return prefix_of(button_id) in self._handlers

    async def dispatch(self, user_id: str, button_id: str | None) -> Handled | None:
        prefix = prefix_of(button_id)
        handler = self._handlers.get(prefix or "")
        if handler is None or not button_id:
            return None
        try:
            return await handler(user_id, button_id) or Handled()
        except Exception as e:  # noqa: BLE001 - one bad button never breaks the chat
            log.warning("button handler %s failed (%s)", prefix, type(e).__name__)
            return Handled()
