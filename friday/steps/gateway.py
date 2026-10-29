# ruff: noqa: E501
"""The step runner in the live message path.

* ``handle`` (early in ``InboundPipeline._active``, before the browser-agent gateway): the user's answer while a plan is open
  (area, 'yes', a form field ...), 'stop'. A bare login code is left to the guarded OTP flow.
* ``start`` (called by the approach planner for 'price of X on <store>' and the other playbooks): plans first, then runs ONE step.
* ``tick`` (runtime loop): codes that arrived, OTP timeout and its single resend, busy retries, unanswered questions, restarts.
"""

from __future__ import annotations

from typing import Any

from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, User
from friday.steps import wording as w
from friday.steps.runner import StepRunner

log = get_logger(__name__)


class StepGateway:
    def __init__(self, pipeline: Any, runner: StepRunner) -> None:
        self.p, self.runner = pipeline, runner

    async def _lang(self, user: User) -> str:
        try:
            return str(await self.p._reply_lang(user))
        except Exception:  # noqa: BLE001
            return "hinglish"

    async def handle(self, user: User, msg: InboundMessage) -> bool:
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE) or not (msg.text or "").strip():
            return False
        if not self.runner.has_open(user.id):
            return False
        return await self.runner.handle_reply(user.id, msg.text or "")

    async def start(self, user: User, text: str, lang: str) -> bool:
        if self.runner.has_open(user.id):
            await self.runner.say(user.id, w.line("already", lang))
            return True
        try:
            return await self.runner.start(user.id, text, lang)
        except Exception:  # noqa: BLE001 - never lose the user: the old flow takes the request
            log.exception("step runner failed to start; using the old flow")
            return False

    async def tick(self) -> int:
        n = await self.runner.tick()
        purge = getattr(self.runner.store, "purge_finished", None)
        if purge is not None:
            purge(self.p.clock.now())
        return n

    async def forget_user(self, user_id: str) -> None:
        await self.runner.forget_user(user_id)
