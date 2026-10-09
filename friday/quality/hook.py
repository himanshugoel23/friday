"""The ONE connection between the front door and the quality loop.

``install_quality_hook(container)`` subscribes a handler to ``FrontDoorCallFinished`` on the
container's bus (called once from ``create_app``). The handler hands the call to
``TranscriptStore.capture`` which stores it only for a consenting caller. It never raises
into the call path (the bus already isolates handler failures; we also log without content).
"""

from __future__ import annotations

from typing import Any

from friday.core.logging import get_logger

log = get_logger(__name__)
_FLAG = "_friday_quality_hook"


def install_quality_hook(c: Any) -> bool:
    """Idempotent per container. Returns True when the subscription was added."""
    if getattr(c, _FLAG, False):
        return False
    from friday.voice.frontdoor import FrontDoorCallFinished

    async def on_finished(ev: FrontDoorCallFinished) -> None:
        from friday.quality.store import TranscriptStore

        try:
            res = await TranscriptStore.from_container(c).capture(ev.summary, ev.result)
            log.info("quality capture: %s", res.reason)
        except Exception as e:  # noqa: BLE001 - quality must never affect a call
            log.warning("quality capture failed: %s", type(e).__name__)

    c.bus.subscribe(FrontDoorCallFinished, on_finished)
    setattr(c, _FLAG, True)
    return True
