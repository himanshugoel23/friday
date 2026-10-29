# ruff: noqa: E501
"""The planner in the live message path (InboundPipeline._active, after chatbot/features, before the
browser, quotes, PM and brain). Off unless ``FRIDAY_APPROACH_PLANNER_ENABLED``.

For each typed request it picks ONE approach and then:

* WEB_LOOKUP  -> runs the web lookup agent here and replies with sourced results;
* ASK / DECLINE -> sends the one question / the plain refusal here;
* CALL_VENDORS / APP_OR_CONNECTOR / ANSWER -> lets the existing chain handle it (``rest``): the calls
  keep their consent / allow-list / kill-switch guards, an app flow its browser rules, an answer the
  brain. If that takes longer than ~8 s the user gets ONE short 'on it' line naming the approach.

Never touches buttons, commands, answers to an open question, or an active PM task.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, User
from friday.planner import signals as sg
from friday.planner import wording
from friday.planner.agents.answer import AnswerAgent, AnswerInput
from friday.planner.agents.ask import AskAgent, AskInput
from friday.planner.agents.call import CallAgent, CallPlanInput
from friday.planner.agents.web_lookup import WebLookupAgent, WebLookupInput, WebLookupOutput
from friday.planner.planner import ApproachPlanner
from friday.planner.slow import ACK_AFTER_S, run_with_ack
from friday.planner.types import Approach, ApproachDecision, PlannerContext
from friday.style import StyleLayer
from friday.style import builders as style_say

log = get_logger(__name__)

RETRY_WINDOW = timedelta(minutes=10)
_YES = re.compile(r"^\W*(yes|yeah|yep|ok|okay|haan|han|ha|haa|kar\s*do|try\s*again|dobara|phir\s*se|retry)\W*$", re.I)
Rest = Callable[[User, InboundMessage], Awaitable[None]]


class PlannerGateway:
    def __init__(
        self,
        pipeline: Any,
        *,
        planner: ApproachPlanner,
        web: WebLookupAgent,
        ask: AskAgent | None = None,
        answer: AnswerAgent | None = None,
        call: CallAgent | None = None,
        ack_after_s: float = ACK_AFTER_S,
        shopping: Any = None,  # friday.shopping.ShoppingAssistant, or None while its switch is off
    ) -> None:
        self.p = pipeline
        self.planner, self.web = planner, web
        self.ask, self.answer, self.call = ask or AskAgent(), answer or AnswerAgent(), call or CallAgent()
        self.ack_after_s = ack_after_s
        self.shopping = shopping
        self._style = StyleLayer.from_pipeline(pipeline)  # FRIDAY_STYLE_LAYER_ENABLED (off: no change)
        self._last: dict[str, tuple[datetime, WebLookupInput, WebLookupOutput]] = {}

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        return self.p.clock.now()

    def connectors(self) -> frozenset[str]:
        return frozenset({"browser"}) if getattr(self.p, "browser", None) is not None else frozenset()

    async def _busy(self, user: User) -> bool:
        """A task is waiting for this user's answer: the message belongs to it, not to a new plan."""
        try:
            if await self.p.repos.tasks.open_question_for_user(user.id) is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
        store = getattr(getattr(self.p, "pm_gateway", None), "store", None)
        active_for = getattr(store, "active_for_user", None)
        try:
            return bool(active_for and active_for(user.id) is not None)
        except Exception:  # noqa: BLE001
            return False

    async def _lang(self, user: User) -> str:
        return await self.p._reply_lang(user)

    async def _say(self, user: User, text: str) -> None:
        for part in self._style.fit(text, source="planner", kind="result"):  # one part while the switch is off
            await self.p.reply(user, part)

    def _ack_text(self, approach: Approach, retailer: str | None, lang: str) -> str:
        if self._style.enabled and approach == Approach.WEB_LOOKUP:
            return style_say.ack(wording.where_label(retailer, lang), lang)
        return wording.ack_line(approach, retailer, lang)

    async def _audit(self, user: User, d: ApproachDecision) -> None:
        with contextlib.suppress(Exception):
            await self.p.audit(
                "planner.decision", user, approach=d.approach.value, reason=d.reason.code.value, source=d.source
            )

    # ------------------------------------------------------------------ entry
    async def route(self, user: User, msg: InboundMessage, rest: Rest) -> None:
        text = (msg.text or "").strip()
        if self.shopping is not None and not await self._busy(user) and await self.shopping.handle(user, msg, await self._lang(user)):
            return  # shopping: a product word, a Home / PG tap, or the one area answer
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE) or len(text) < 3 or await self._busy(user):
            await rest(user, msg)
            return
        lang = await self._lang(user)
        follow = self._follow_up(user, text)
        if follow is not None:
            await self._lookup(user, follow, lang)
            return
        ctx = PlannerContext(text=text, lang=lang, connectors=self.connectors(), pincode=sg.pincode_in(text))
        d = await self.planner.plan(ctx)
        await self._audit(user, d)
        shop_cat = self.shopping.matches(d.query or "") if self.shopping is not None and d.approach == Approach.WEB_LOOKUP else None
        if shop_cat is not None:  # the planner's own lookup query is a shopping one ("price of atta on zepto")
            await self.shopping.start(user, shop_cat, text, lang)
        elif d.approach == Approach.WEB_LOOKUP:
            await self._lookup(
                user,
                WebLookupInput(query=d.query or text, retailer=d.retailer, pincode=ctx.pincode, lang=lang),
                lang,
            )
        elif d.approach == Approach.ASK:
            q = self.ask.run(
                AskInput(reason_code=d.reason.code, proposed=d.question, lang=lang, call_in_plan=False)
            ).question
            await self._say(user, self._style.flag(q, source="planner.ask", user_text=text))
        elif d.approach == Approach.DECLINE:
            await self._say(user, wording.guard_text(d.question, call_in_plan=False, fallback=wording.line("decline", lang)))
        else:
            await self._pass_through(user, msg, d, lang, rest)

    def _follow_up(self, user: User, text: str) -> WebLookupInput | None:
        """'560001' after 'tell me your pincode', or 'yes' after a timeout: redo the last lookup."""
        last = self._last.get(user.id)
        if last is None or self._now() - last[0] > RETRY_WINDOW:
            return None
        _, inp, out = last
        pin = sg.pincode_in(text)
        if pin and re.fullmatch(r"\W*\d{6}\W*", text) and (out.ask_pincode or out.status != "ok"):
            return inp.model_copy(update={"pincode": pin, "query": f"{inp.query} (pincode {pin})"})
        if _YES.match(text) and out.status in ("timeout", "unavailable", "no_result"):
            return inp
        return None

    async def _lookup(self, user: User, inp: WebLookupInput, lang: str) -> None:
        async def ack() -> None:
            await self._say(user, self._ack_text(Approach.WEB_LOOKUP, inp.retailer, lang))

        out = await run_with_ack(self.web.run(inp), ack, after_s=self.ack_after_s)
        self._last[user.id] = (self._now(), inp, out)
        await self._say(user, self.web.render(out, lang))
        if out.ask_pincode:  # the reply ends with a question: nothing may bury it
            return
        from friday.evidence.action_proof import send_card

        first = next(iter(getattr(out, "sources", None) or []), None)
        res = {"status": out.status, "url": getattr(first, "url", None), "seen": "" if out.status == "ok" else f"lookup {out.status}"}
        await send_card(self.p, user, res, kind="lookup", what=inp.query[:80], lang=lang)

    async def _pass_through(
        self, user: User, msg: InboundMessage, d: ApproachDecision, lang: str, rest: Rest
    ) -> None:
        if d.approach == Approach.CALL_VENDORS:
            self.call.run(CallPlanInput(decision=d))  # marks the plan; the old flow places nothing without consent
        elif d.approach == Approach.ANSWER:
            out = await self.answer.run(AnswerInput(text=msg.text or "", lang=lang))
            if out.handled and out.text:
                await self._say(user, out.text)
                return

        async def ack() -> None:
            await self._say(user, self._ack_text(d.approach, d.retailer, lang))

        await run_with_ack(rest(user, msg), ack, after_s=self.ack_after_s)
