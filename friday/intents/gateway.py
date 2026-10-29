# ruff: noqa: E501
"""Proactive intents in the live message path (docs/PROACTIVE_INTENTS.md).

Runs in ``InboundPipeline._active`` after the chatbot / features and BEFORE the query-understanding
team and the approach planner. Off unless ``FRIDAY_PROACTIVE_INTENTS_ENABLED``.

* a request that needs a connection Friday does not have (Gmail, Calendar, Drive, an ordering app)
  gets an HONEST reply: what it needs, what happens next (a real connect link only when the Google
  connector is configured on this server), and the nearest thing Friday can do now. Never a bare refusal.
* a common personal intent (interview, birthday, trip, bill, exam, meeting) gets a concrete proposal
  from a data table (``playbooks.yaml``) with at most ONE question and 2-3 buttons.
* a fragment ('Kal', 'interview hainkal') is read against the previous turn: the open intent is kept
  and the date word fills the date slot (optionally via the query-understanding agent).

Nothing here calls anybody, pays, or invents facts; the reminder is a date fact in memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from friday.chatbot.composer import Composer, detect_language
from friday.core.clock import IST
from friday.core.logging import get_logger
from friday.core.models import Fact, FactKind, InboundMessage, MessageKind, ReplyButton, User
from friday.replywriter.schema import Button, Facts, ReplyInput
from friday.replywriter.service import context_from
from friday.replywriter.templates import greeting_text
from friday.style import StyleLayer

log = get_logger(__name__)

PREFIX = "pi:"
TTL = timedelta(minutes=15)
MAX_TEXT = 300  # a longer message is pasted content, not a request
_DATA: dict[str, Any] = yaml.safe_load(
    (Path(__file__).parent / "playbooks.yaml").read_text(encoding="utf-8")
)

_GLUE = re.compile(
    r"\b(hai|hain|hoga|he|h|hy)("
    + "|".join(w for ws in _DATA["dates"].values() for w in ws)
    + r")\b",
    re.I,
)
_GLUE_AFTER = re.compile(
    r"\b(" + "|".join(w for ws in _DATA["dates"].values() for w in ws) + r")(hai|hain|hoga)\b", re.I
)
_ASKING = re.compile(
    r"\?|\b(how|kaise|kaisa|tips|batao|bata\s*do|explain|what|kya|why|kyun|help)\b", re.I
)
_BILL_DUE = re.compile(r"\b(due|bharna|bharni|jama|pay|deadline|baaki|baki)\b", re.I)
# the consumer router (friday/integration) owns connect / disconnect / status wording for Google
_GOOGLE_ADMIN = re.compile(
    r"\b(connect|link|jodo|jod|disconnect|unlink|remove|hatao|hata|status|connected|juda)\b", re.I
)


def _words(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[\w'-]+", text)]


def unglue(text: str) -> str:
    """'interview hainkal' -> 'interview hain kal' (a merged typo), nothing else changes."""
    text = _GLUE.sub(r"\1 \2", text)
    return _GLUE_AFTER.sub(r"\1 \2", text)


def date_slot(text: str) -> str | None:
    for w in _words(text):
        for slot, names in _DATA["dates"].items():
            if w in names:
                return slot
    return None


def _line(row: dict[str, str], lang: str, **kw: str) -> str:
    text = row["en"] if lang == "en" else row["hinglish"]
    return text.format(**kw) if kw else text


def _when(slot: str, lang: str) -> str:
    return _line(_DATA["when"][slot], lang)


def pick_lang(text: str, current: str) -> str:
    """'en' or 'hinglish' (Devanagari users get the Roman Hinglish lines, pending approval)."""
    got = detect_language(text) or current
    return "en" if got == "en" else "hinglish"


@dataclass
class Open:
    kind: str  # playbook | capability
    key: str
    stage: str  # ask_date | offered | await_prep | done
    at: datetime
    slot: str | None = None
    own: bool = False


class IntentGateway:
    def __init__(self, pipeline: Any) -> None:
        self.p = pipeline
        self._open: dict[str, Open] = {}
        self._composer = Composer()
        self._style = StyleLayer.from_pipeline(pipeline)  # FRIDAY_STYLE_LAYER_ENABLED (off: no change)

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        return self.p.clock.now()

    def _fresh(self, user: User) -> Open | None:
        o = self._open.get(user.id)
        if o is not None and self._now() - o.at > TTL:
            self._open.pop(user.id, None)
            return None
        return o

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

    async def _say(self, user: User, text: str, buttons: list[ReplyButton] | None = None) -> None:
        comp = self._composer.compose(text, buttons=buttons or [], kind="assist")
        if comp is not None:
            body, chosen = comp.text, comp.buttons
            rs = getattr(self.p, "reply_service", None)  # reply writer / tester log (off: body is sent exactly as composed)
            if rs is not None:
                inp = ReplyInput(
                    intent="playbook", draft=[comp.text], buttons=[Button(id=b.id, title=b.title[:24]) for b in comp.buttons],
                    **context_from(None, await self.p._reply_lang(user)),  # type: ignore[arg-type]
                )
                out = await rs.respond(user.id, inp, [comp.text])
                if out.writer != "legacy":
                    body = "\n\n".join(out.messages)
                    keep = {b.id for b in out.buttons}
                    chosen = [b for b in comp.buttons if b.id in keep] if keep else comp.buttons
            parts = self._style.fit(body, source="intents", has_buttons=bool(chosen))
            for i, part in enumerate(parts):  # buttons ride on the last part
                await self.p.reply(user, part, chosen if i == len(parts) - 1 else [])

    async def _greet(self, user: User, text: str) -> bool:
        """A bare 'Hi' from an active user: the reply writer's greeting (name, example buckets, one question).
        Only while the reply writer or its log is on; otherwise the brain answers as before."""
        from friday.quotes.parse import GREETING_RE

        rs = getattr(self.p, "reply_service", None)
        if rs is None or not GREETING_RE.match(text):
            return False
        lang = await self.p._reply_lang(user)
        name = await rs.first_name(self.p, user)
        inp = ReplyInput(intent="greeting", facts=Facts(name=name), pending="answer", **context_from(text, lang))  # type: ignore[arg-type]
        out = await rs.respond(user.id, inp, greeting_text(name, "en" if lang == "en" else "hinglish"))
        for part in out.messages:
            await self.p.reply(user, part)
        return True

    def _qu(self) -> Any:
        return getattr(getattr(self.p, "team", None), "qu", None)

    # ------------------------------------------------------------------ entry
    async def route(self, user: User, msg: InboundMessage, rest: Any) -> None:
        if msg.kind == MessageKind.BUTTON_REPLY and (msg.button_id or "").startswith(PREFIX):
            await self._button(user, msg, rest)
            return
        text = (msg.text or "").strip()
        if (
            msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE)
            or not text
            or msg.button_id
            or len(text) > MAX_TEXT
        ):
            await rest(user, msg)
            return
        if await self._busy(user):
            await rest(user, msg)
            return
        if await self._greet(user, text):
            return
        lang = pick_lang(text, await self.p._reply_lang(user))
        if await self._handle(user, msg, text, lang, rest):
            return
        qu = self._qu()
        if qu is not None:  # the query-understanding agent may read a typo / lingo the rules missed
            try:
                res = await qu.understand(user.id, text)
                alt = (getattr(res, "instruction", "") or "").strip()
            except Exception:  # noqa: BLE001
                alt = ""
            if alt and alt != text and await self._handle(user, msg, alt, lang, rest):
                return
        await rest(user, msg)

    async def _handle(
        self, user: User, msg: InboundMessage, raw: str, lang: str, rest: Any
    ) -> bool:
        text = unglue(raw)
        words = _words(text)
        slot = date_slot(text)
        o = self._fresh(user)
        # 1. an answer to the one question we asked
        if (
            o is not None
            and o.stage == "await_prep"
            and not (self._capability(text) or self._playbook(text))
        ):
            self._open.pop(user.id, None)
            prompt = _DATA["playbooks"][o.key]["handoff"].format(answer=raw)
            await rest(
                user,
                msg.model_copy(
                    update={"text": prompt, "raw": {**(msg.raw or {}), "original_text": raw}}
                ),
            )
            return True
        # 2. a fragment ('Kal', 'parso') against the open intent
        if (
            o is not None
            and slot
            and len(words) <= 3
            and not (self._playbook(text) and o.kind != "playbook")
        ):
            if o.kind == "capability":
                row = _DATA["capabilities"][o.key]["fragment"]
                await self._say(user, _line(row, lang, when=_when(slot, lang)))
                o.at = self._now()
                return True
            if o.stage == "ask_date":
                await self._offer(user, o.key, slot, lang, own=o.own)
                return True
        if (
            o is not None
            and o.kind == "playbook"
            and o.key == "bill"
            and o.stage == "ask_date"
            and slot
        ):
            await self._offer(user, "bill", slot, lang)
            return True
        # 3. a new intent
        cap = self._capability(text)
        if cap is not None:
            await self._capability_reply(user, cap, lang)
            return True
        pb = self._playbook(text)
        if pb is not None:
            own = bool(set(words) & set(_DATA["playbooks"][pb].get("own_words", [])))
            if slot:
                await self._offer(user, pb, slot, lang, own=own)
            else:
                await self._ask_date(user, pb, lang, own=own)
            return True
        return False

    # ------------------------------------------------------------------ matching
    def _capability(self, text: str) -> str | None:
        words = set(_words(text))
        if _GOOGLE_ADMIN.search(text):
            return None
        for key, row in _DATA["capabilities"].items():
            if not words & set(row["triggers"]):
                continue
            if key == "app_order" and (
                not words & set(row["order_words"]) or words & set(row["skip_words"])
            ):
                continue
            if key == "drive" and "google" not in words and "drive" not in words:
                continue
            return key
        return None

    def _playbook(self, text: str) -> str | None:
        if _ASKING.search(text):
            return None
        words = set(_words(text))
        for key, row in _DATA["playbooks"].items():
            if words & set(row["triggers"]):
                if row.get("needs_due_word") and not _BILL_DUE.search(text):
                    continue
                return key
        return None

    # ------------------------------------------------------------------ playbooks
    async def _ask_date(self, user: User, key: str, lang: str, *, own: bool = False) -> None:
        row = _DATA["playbooks"][key]
        self._open[user.id] = Open("playbook", key, "ask_date", self._now(), own=own)
        if "ask_date_free" in row:
            await self._say(user, _line(row["ask_date_free"], lang))
            return
        text = _line(_DATA["common"]["ask_date"], lang, label=_line(row["label"], lang))
        titles = _DATA["date_buttons"]["en" if lang == "en" else "hinglish"]
        await self._say(
            user,
            text,
            [
                ReplyButton(id=f"{PREFIX}d:{s}", title=t)
                for s, t in zip(("today", "tomorrow", "dayafter"), titles, strict=True)
            ],
        )

    async def _offer(
        self, user: User, key: str, slot: str, lang: str, *, own: bool = False
    ) -> None:
        row = _DATA["playbooks"][key]
        c = _DATA["common"]["buttons"]
        when = _when(slot, lang)
        self._open[user.id] = Open("playbook", key, "offered", self._now(), slot=slot, own=own)
        if own and "offer_own" in row:
            text = _line(row["offer_own"], lang, when=when)
            btns = [
                ReplyButton(id=f"{PREFIX}a:handoff", title=_line(row["own_button"], lang)),
                ReplyButton(id=f"{PREFIX}a:no", title=_line(c["not_now"], lang)),
            ]
        else:
            text = _line(row["offer"], lang, when=when)
            btns = [ReplyButton(id=f"{PREFIX}a:remind", title=_line(c["remind_me"], lang))]
            if "prep_button" in row:
                btns.append(
                    ReplyButton(id=f"{PREFIX}a:prep", title=_line(row["prep_button"], lang))
                )
            btns.append(ReplyButton(id=f"{PREFIX}a:no", title=_line(c["not_now"], lang)))
        await self._say(user, text, btns)

    async def _button(self, user: User, msg: InboundMessage, rest: Any) -> None:
        parts = (msg.button_id or "").split(":")
        kind, value = (parts[1], parts[2]) if len(parts) > 2 else ("", "")
        lang = pick_lang(msg.text or "", await self.p._reply_lang(user))
        # the button title tells the language the user is reading
        if msg.text:
            lang = (
                "hinglish"
                if msg.text
                in {
                    *_DATA["date_buttons"]["hinglish"],
                    _DATA["common"]["buttons"]["remind_me"]["hinglish"],
                    _DATA["common"]["buttons"]["not_now"]["hinglish"],
                }
                else lang
            )
        o = self._fresh(user)
        if o is None or o.kind != "playbook":
            await self._say(user, _line(_DATA["common"]["stale"], lang))
            return
        if kind == "d" and value in _DATA["when"]:
            await self._offer(user, o.key, value, lang, own=o.own)
            return
        row = _DATA["playbooks"][o.key]
        if kind == "a" and value == "remind" and o.slot:
            await self._remind(user, o)
            await self._say(
                user, _line(_DATA["common"]["remind_done"], lang, when=_when(o.slot, lang))
            )
            o.stage = "done"
        elif kind == "a" and value == "prep" and "prep_ask" in row:
            o.stage, o.at = "await_prep", self._now()
            await self._say(user, _line(row["prep_ask"], lang))
        elif kind == "a" and value == "handoff" and o.slot and "own_handoff" in row:
            self._open.pop(user.id, None)
            prompt = row["own_handoff"].format(when=_when(o.slot, "en"))
            await rest(
                user,
                msg.model_copy(
                    update={"kind": MessageKind.TEXT, "text": prompt, "button_id": None}
                ),
            )
        else:
            self._open.pop(user.id, None)
            await self._say(user, _line(_DATA["common"]["dismiss"], lang))

    async def _remind(self, user: User, o: Open) -> None:
        """A date fact in memory (the existing date-based nudges pick it up): no exact time is invented."""
        today = self._now().astimezone(IST).date()
        due = today + timedelta(days={"today": 0, "tomorrow": 1, "dayafter": 2}[o.slot or "today"])
        label = _DATA["playbooks"][o.key]["label"]["en"]
        await self.p.repos.facts.upsert(
            Fact(
                user_id=user.id,
                kind=FactKind.DATE,
                key=f"{o.key}_{due.isoformat()}",
                value=label,
                due_on=due,
            )
        )

    # ------------------------------------------------------------------ capabilities
    async def _google_state(self, user: User) -> tuple[str, str | None]:
        """('not_configured' | 'connect' | 'connected', link). Never raises; never a link that cannot work."""
        try:
            consumer = self.p.consumer()
            parts = getattr(consumer, "google", None) if consumer is not None else None
            if parts is None:
                return "not_configured", None
            oauth = parts.oauth()
            if not oauth.configured:
                return "not_configured", None
            st = await oauth.status(user.id)
            if st.connected:
                return "connected", None
            start = await oauth.start(user.id)
            return "connect", start.link
        except Exception:  # noqa: BLE001 - NotConfigured or anything else: say it is not set up
            log.info("proactive intents: google state unavailable")
            return "not_configured", None

    async def _capability_reply(self, user: User, key: str, lang: str) -> None:
        row = _DATA["capabilities"][key]
        self._open[user.id] = Open("capability", key, "offered", self._now())
        if "static" in row:
            await self._say(user, _line(row["static"], lang))
            return
        paste = _line(row["paste"], lang)
        state, link = await self._google_state(user)
        if (
            state == "connect"
            and key == "gmail"
            and not getattr(self.p.settings, "google_gmail_enabled", False)
        ):
            state = "scope_off"
        if state == "connected":
            await self._say(user, _line(row["connected"], lang, paste=paste))
        elif state == "connect":
            await self._say(user, _line(row["connect"], lang, link=link or "", paste=paste))
        else:
            await self._say(
                user,
                _line(
                    row["scope_off" if state == "scope_off" else "not_configured"],
                    lang,
                    paste=paste,
                ),
            )
