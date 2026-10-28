# ruff: noqa: E501
"""The chain in the live message path (InboundPipeline._active, after chatbot/features, before the planner):

    text -> dictionary commands -> pending answers (yes/no, area) -> QUERY UNDERSTANDING (rewrite, ask if unsure)
         -> TEAM (decompose; PM or lead PM + sub-PMs over A2A) -> one merged reply
         -> anything the team does not handle goes on to the planner / old chain with the CLEAN instruction.

Two independent switches: ``FRIDAY_QUERY_UNDERSTANDING_ENABLED`` (rewrite only) and ``FRIDAY_AGENT_TEAM_ENABLED``.
Never touches buttons, commands, a task waiting for this user's answer, or an active PM task.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, User
from friday.planner import signals as sg
from friday.planner.slow import ACK_AFTER_S, run_with_ack
from friday.speech import dict_chat
from friday.speech.query_agent import AskBack, QueryUnderstandingAgent
from friday.speech.userdict import home_area
from friday.team import wording
from friday.team.pm import Goal, ProjectManager, TeamOutcome, merge_reply

log = get_logger(__name__)
Rest = Callable[[User, InboundMessage], Awaitable[None]]
TTL = timedelta(minutes=10)
YES = re.compile(r"^\W*(yes|yeah|yep|y|ok|okay|haan|han|ha|haa|sahi|correct|right|theek|ji)\W*$", re.I)
NO = re.compile(r"^\W*(no|nope|n|nahi|nahin|na|galat|wrong)\W*$", re.I)
SEARCH_WORDS = re.compile(r"\b(options?|best|near\s*me|nearby|under|below|restaurants?|menu|price|rating|compare)\b", re.I)


@dataclass
class PendingFix:
    msg: InboundMessage
    ask: AskBack
    at: datetime


@dataclass
class PendingInput:
    goal: Goal
    pending: list[tuple[str, str]]
    root: str
    at: datetime


class TeamGateway:
    def __init__(self, pipeline: Any, *, qu: QueryUnderstandingAgent | None, pm: ProjectManager | None,
                 web_render: Callable[[dict[str, Any], str], str] | None = None, ack_after_s: float = ACK_AFTER_S) -> None:
        self.p, self.qu, self.pm, self.web_render, self.ack_after_s = pipeline, qu, pm, web_render, ack_after_s
        self._fix: dict[str, PendingFix] = {}
        self._input: dict[str, PendingInput] = {}

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        return self.p.clock.now()

    async def _say(self, user: User, text: str) -> None:
        await self.p.reply(user, text)

    async def _busy(self, user: User) -> bool:
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

    async def _audit(self, user: User, event: str, **kw: Any) -> None:
        with contextlib.suppress(Exception):
            await self.p.audit(event, user, **kw)

    # ------------------------------------------------------------------ entry
    async def route(self, user: User, msg: InboundMessage, rest: Rest) -> None:
        text = (msg.text or "").strip()
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE) or not text or msg.button_id:
            await rest(user, msg)
            return
        lang = await self.p._reply_lang(user)
        # 1. the user's own dictionary: view / add / remove / delete all
        if msg.kind == MessageKind.TEXT:
            reply = await dict_chat.handle(self.p.repos, user.id, text, lang)
            if reply is not None:
                await self._say(user, reply)
                return
        # 2. answers to what we asked last
        handled, msg = await self._pending(user, msg, text, lang)
        if handled:
            return
        if await self._busy(user):
            await rest(user, msg)
            return
        # 3. query understanding: one clear instruction
        skip: set[str] = set(msg.raw.get("_skip_forms", [])) if msg.raw else set()
        if self.qu is not None:
            msg, asked = await self._understand(user, msg, lang, skip)
            if asked:
                return
        # 4. the team
        if self.pm is not None and await self._team(user, msg, lang, rest):
            return
        await rest(user, msg)

    # ------------------------------------------------------------------ pending answers
    async def _pending(self, user: User, msg: InboundMessage, text: str, lang: str) -> tuple[bool, InboundMessage]:
        fix = self._fix.get(user.id)
        if fix is not None:
            if self._now() - fix.at > TTL:
                self._fix.pop(user.id, None)
            elif YES.match(text) or NO.match(text):
                self._fix.pop(user.id, None)
                if YES.match(text):
                    await self.qu.learn(user.id, self.p.repos, self.p.clock,  # type: ignore[union-attr]
                                        [(fix.ask.heard, fix.ask.candidate, fix.ask.kind, fix.ask.source)], confirmed=True)
                    text2 = fix.ask.candidate_text
                    return False, fix.msg.model_copy(update={"text": text2, "raw": {**fix.msg.raw, "original_text": fix.msg.text,
                                                                                      "query_confirmed": True}})
                return False, fix.msg.model_copy(update={"raw": {**fix.msg.raw, "_skip_forms": [fix.ask.heard]}})
            else:
                self._fix.pop(user.id, None)  # a new message: the old question is dropped
        pin = self._input.get(user.id)
        if pin is not None:
            if self._now() - pin.at > TTL:
                self._input.pop(user.id, None)
            elif self.pm is not None and not sg.explicit_call_request(text) and len(text.split()) <= 6:
                self._input.pop(user.id, None)
                res = await self.pm.resume(pin.pending, text, pin.goal, pin.root, lang=lang)
                out = TeamOutcome(pin.root, [pin.goal], [res], False)
                if res.status == "input_required":
                    self._input[user.id] = PendingInput(pin.goal, res.pending, pin.root, self._now())
                await self._say(user, merge_reply(out, lang, web_render=self.web_render))
                return True, msg
            else:
                self._input.pop(user.id, None)
        return False, msg

    # ------------------------------------------------------------------ step 3
    async def _understand(self, user: User, msg: InboundMessage, lang: str, skip: set[str]) -> tuple[InboundMessage, bool]:
        try:
            ctx = await self.p.context(user)
            out = await self.qu.understand(user.id, msg.text or "", ctx, skip_forms=skip)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            log.exception("query understanding failed; using the words as typed")
            return msg, False
        await self._audit(user, "query.understood", **out.audit())
        if out.ask is not None:
            self._fix[user.id] = PendingFix(msg.model_copy(update={"text": out.instruction}), out.ask, self._now())
            await self._say(user, wording.line("confirm_fix", lang, candidate=out.ask.candidate, heard=out.ask.heard))
            return msg, True
        if out.entity_fixes:
            await self.qu.learn(user.id, self.p.repos, self.p.clock, out.entity_fixes)  # type: ignore[union-attr]
        if out.changed:
            raw = {**msg.raw, "query": out.audit()}
            raw.setdefault("original_text", out.original_text)
            msg = msg.model_copy(update={"text": out.instruction, "raw": raw})
        return msg, False

    # ------------------------------------------------------------------ step 4
    async def _team(self, user: User, msg: InboundMessage, lang: str, rest: Rest) -> bool:
        assert self.pm is not None
        text = msg.text or ""
        goals = self.pm.plan(text)
        food = [g for g in goals if g.domain == "food"]
        team_goals = [g for g in goals if g.team_supported]
        # single web-price goals stay with the approach planner (pincode follow-ups, cache); the team takes food
        # goals and multi-goal requests
        if not food and len(team_goals) < 2:
            return False
        # a plain "order pizza" with the browser connector on is the connector's job (stop-at-payment rule)
        if getattr(self.p, "browser", None) is not None and len(goals) == 1 and sg.ORDER_RE.search(text) and not SEARCH_WORDS.search(text):
            return False
        ctx = await self.p.context(user)
        area = home_area(ctx)
        big = len(team_goals) >= self.pm.big_threshold

        async def ack() -> None:
            if big:
                await self._say(user, wording.line("ack_team_big", lang))
            else:
                where = "Zomato / Swiggy" if food else "the web"
                await self._say(user, wording.line("ack_team", lang, where=where))

        out = await run_with_ack(self.pm.run(text, default_area=area, lang=lang, goals=goals), ack, after_s=self.ack_after_s)
        await self._audit(user, "team.run", goals=len(goals), big=out.big, sub_pms=out.sub_pms,
                          steps=out.budget.get("steps"), cost_inr=out.budget.get("cost_inr"),
                          exhausted=out.budget_exhausted, partial=out.partial)
        for r in out.results:
            if r.status == "input_required" and r.pending:
                self._input[user.id] = PendingInput(r.goal, r.pending, out.root_task_id, self._now())
                break
        await self._say(user, merge_reply(out, lang, web_render=self.web_render))
        if out.remaining_text:  # the parts the team does not do continue in the old chain
            self._fix.pop(user.id, None)
            rest_msg = msg.model_copy(update={"text": out.remaining_text})
            await rest(user, rest_msg)
        return True
