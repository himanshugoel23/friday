# ruff: noqa: E501
"""T13: scam check by forwarding. A text, link, forwarded message or screenshot from a Robin PARENT (WhatsApp) is judged here.

    ParentInbound (channel.py) -> ScamForward.handle
      no ``scam_check`` consent -> the parent is told Robin cannot help (show it to the child); the child is told once a day
      text / link  -> ``scamcheck.check`` (rules first; the optional LLM second opinion can only RAISE, switch
                      FRIDAY_ROBIN_DEVICE_SCAM_LLM_ENABLED, default OFF)
      screenshot   -> bytes fetched in memory -> the existing vision port reads the text -> bytes dropped -> same check
      -> the parent gets a short line (the caller sends it as a voice note + text, in the parent's language)
      -> SCAM_LIKELY (HIGH) tells the child when the parent agreed to ``share_summary_with_child``; a money moment adds the first-hour
         playbook text for the child; the same sender seen again (hashed) is flagged and also tells the child.

Privacy: the forwarded content is analysed in memory and dropped. What is kept is one audit row: verdict, category, time, and (only when a
phone number or a link host was found) a keyed hash of the sender for repeat detection. Never the text, the image, a number or a link.
Logs carry member ids and verdict words only. Real vision/LLM providers are not exercised here (tested with fakes).

The verdict never says "safe": the best answer is "no warning signs found" followed by a reminder that this is not a promise. Every line
is in friday/robin/lines.py (PENDING founder approval).
"""

from __future__ import annotations

import contextlib
import re
from datetime import timedelta
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import MessageKind
from friday.robin.models import Family, Member
from friday.robindevice import copy as scam_copy
from friday.robindevice import scamcheck

log = get_logger(__name__)

MAX_IMAGE_BYTES = 8_000_000
REPEAT_WINDOW = timedelta(days=30)  # the audit log itself is kept 30 days
CHILD_DEDUPE_MIN = 10  # the same category for the same parent within 10 minutes tells the child once
MONEY_CATEGORIES = frozenset({
    "otp_pin", "collect_refund", "safe_account", "investment", "job_fee", "relative_trouble", "prize", "kyc_block", "utility", "pension",
    "digital_arrest", "link_lookalike", "apk_file", "remote_access",
})  # the scam wants money, a code or an install: the child gets the first-hour playbook text
_RANK = {"NO_SIGNS_FOUND": 0, "UNSURE": 1, "RISKY": 2, "SCAM_LIKELY": 3}
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?([6-9]\d{4}[\s-]?\d{5})(?!\d)")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)([^\s/?#<>\"']+)")
_ONLY_URL = re.compile(r"(?i)^\s*(?:https?://\S+|www\.\S+)\s*$")


class ScamForward:
    """``channel.ScamIntake`` for real. ``messaging`` / ``vision`` / ``llm`` are getters (components are built lazily; None = not configured)."""

    def __init__(self, hub: Any, *, messaging: Any = None, vision: Any = None, llm: Any = None) -> None:
        self.hub, self._messaging, self._vision, self._llm = hub, messaging, vision, llm

    @staticmethod
    def _get(getter: Any) -> Any:
        try:
            return getter() if getter is not None else None
        except Exception:  # noqa: BLE001 - component not configured
            return None

    # ------------------------------------------------------------------ entry
    async def handle(self, *, family: Family, parent: Member, msg: Any, text: str | None) -> str | None:
        c = self.hub.ctx
        lang = parent.language if parent.language in scam_copy.LANGS else "hinglish"
        kind = msg.kind
        has_content = kind in (MessageKind.IMAGE, MessageKind.DOCUMENT) and bool(msg.media_url) or bool(text)
        if not has_content:
            return None  # a location pin, a contact card, an empty message: the short hello
        if kind not in (MessageKind.IMAGE, MessageKind.DOCUMENT) and len((text or "").split()) <= 3 and not re.search(r"\d|(?i:https?:|www\.|\.com|\.in\b|\.apk)", text or ""):
            return None  # 'hi', 'namaste', 'thank you': a greeting, not something to judge; the short hello answers it
        slots = await c.slots(family)
        if not await c.has_consent(parent, "scam_check"):
            await self._refuse(family, parent, kind, msg)
            return c.say("scam.no_consent", parent.language, **slots)
        if kind in (MessageKind.IMAGE, MessageKind.DOCUMENT):
            read = await self._read_picture(msg)
            value = "\n".join(x for x in (text or "", read or "") if x).strip()
            if not read and not text:
                return await self._unreadable(family, parent, slots)
        else:
            value = text or ""
        sender_hash = self._sender_hash(value)
        res = await self._judge(value, lang)
        del value  # the content is gone from here on
        return await self._answer(family, parent, res, sender_hash, slots)

    # ------------------------------------------------------------------ the judgement
    async def _judge(self, value: str, lang: str) -> scamcheck.ScamResult:
        k = "url" if _ONLY_URL.match(value) else "text"
        llm = self._get(self._llm)  # None unless FRIDAY_ROBIN_DEVICE_SCAM_LLM_ENABLED
        try:
            return await scamcheck.check(k, value.strip(), lang=lang, llm=llm)
        except Exception as e:  # noqa: BLE001 - an engine bug must not give false reassurance
            log.warning("robin: scam check failed (%s)", type(e).__name__)
            return scamcheck.check_rules("screenshot_ref", "", lang)  # UNSURE: 'do not click, show it to the child'

    async def _read_picture(self, msg: Any) -> str | None:
        """fetch -> vision -> forget. The bytes live only in this frame. None = unreadable (no provider, failure, too large, empty)."""
        messaging, vision = self._get(self._messaging), self._get(self._vision)
        if messaging is None or vision is None or not msg.media_url:
            return None
        blob = None
        try:
            from friday.docunderstand.ports import VisionInput, sniff_mime

            blob = await messaging.fetch_media(msg.media_url)
            data = blob.data
            if not data or len(data) > MAX_IMAGE_BYTES:
                return None
            mime = sniff_mime(data) or msg.media_mime or blob.mime
            if not (mime or "").startswith("image/") and mime != "application/pdf":
                return None
            out = await vision.read(VisionInput(data=data, mime=mime))
            return (out.text or "").strip() or None
        except Exception as e:  # noqa: BLE001
            log.info("robin: forwarded picture could not be read (%s)", type(e).__name__)
            return None
        finally:
            blob = None  # drop the picture
            delete = getattr(messaging, "delete_media", None)
            if callable(delete):
                with contextlib.suppress(Exception):
                    await delete(msg.media_url)  # the provider's copy too (best effort)

    # ------------------------------------------------------------------ the answer
    async def _unreadable(self, family: Family, parent: Member, slots: dict[str, str]) -> str:
        c = self.hub.ctx
        await self._record(family, parent, "UNSURE", "screenshot", None, 1)
        return c.say("scam.unreadable", parent.language, **slots)

    async def _answer(self, family: Family, parent: Member, res: scamcheck.ScamResult, sender_hash: str | None, slots: dict[str, str]) -> str:
        c = self.hub.ctx
        lang = parent.language
        category = (res.categories[0] if res.categories else ("none" if res.verdict == "NO_SIGNS_FOUND" else "unsure"))
        prior = await self._prior_count(family, sender_hash) if sender_hash and _RANK[res.verdict] >= _RANK["RISKY"] else 0
        times = prior + 1
        key = {"SCAM_LIKELY": "scam.high", "RISKY": "scam.risky", "UNSURE": "scam.unsure", "NO_SIGNS_FOUND": "scam.nosigns"}[res.verdict]
        say = c.say(key, lang, verdict=res.headline, why=res.reason, **slots)
        if times >= 2:
            say = f"{say} {c.say('scam.repeat', lang)}"
        await self._record(family, parent, res.verdict, category, sender_hash, times)
        high = res.verdict == "SCAM_LIKELY"
        if (high or (times >= 2 and _RANK[res.verdict] >= _RANK["RISKY"])) and await c.has_consent(parent, "share_summary_with_child"):
            await self._tell_child(family, parent, res, category, times)
        return say

    async def _tell_child(self, family: Family, parent: Member, res: scamcheck.ScamResult, category: str, times: int) -> None:
        c = self.hub.ctx
        bucket = int(c.clock.now().timestamp() // (CHILD_DEDUPE_MIN * 60))
        rec = await c.audit(family, "scam_child_told", f"{family.parent_label}'s scam check was passed to you ({category}).", key=f"scam_child:{parent.id}:{category}:{bucket}", category=category)
        if rec.data.get("told"):
            return
        chat = await c.chat_lang(family)
        what = scam_copy.pick(scam_copy.REASONS, category if category in scam_copy.REASONS else "unsure", chat if chat in scam_copy.LANGS else "en")
        line = "scam.child_repeat" if times >= 2 else "scam.child_high"
        text = c.say(line, chat, parent=family.parent_label, what=what, n=times)
        if MONEY_CATEGORIES & {category, *res.categories}:
            text = f"{text}\n\n{c.say('scam.child_playbook', chat, parent=family.parent_label)}"  # money moment: the first-hour playbook text
        await c.tell_child(family, text)
        rec.data["told"] = True
        with contextlib.suppress(Exception):
            await c.store.set_data(rec.id, rec.data)

    async def _refuse(self, family: Family, parent: Member, kind: Any, msg: Any) -> None:  # noqa: ARG002
        """No ``scam_check`` consent: nothing is looked at. The child is informed once a day."""
        c = self.hub.ctx
        day = c.local_day_bounds(parent)[0].date().isoformat()
        rec = await c.audit(family, "scam_no_consent", f"{family.parent_label} sent something for a scam check but scam check is off; nothing was looked at.", key=f"scam_noc:{parent.id}:{day}")
        if rec.data.get("told"):
            return
        await c.tell_child(family, c.say("scam.child_no_consent", await c.chat_lang(family), parent=family.parent_label))
        rec.data["told"] = True
        with contextlib.suppress(Exception):
            await c.store.set_data(rec.id, rec.data)

    # ------------------------------------------------------------------ what is kept
    async def _record(self, family: Family, parent: Member, verdict: str, category: str, sender_hash: str | None, times: int) -> None:
        """Verdict, category and time. No content, no number, no link. ``sender_hash`` is a keyed hash, only for repeat detection."""
        c = self.hub.ctx
        data: dict[str, Any] = {"verdict": verdict, "category": category, "member_id": parent.id, "times": times}
        if sender_hash:
            data["sender_hash"] = sender_hash
        await c.audit(family, "scam_check", f"{family.parent_label} sent something for a scam check: {verdict.replace('_', ' ').lower()} ({category}).", **data)
        log.info("robin: scam check for member %s: %s", parent.id, verdict)

    async def _prior_count(self, family: Family, sender_hash: str) -> int:
        c = self.hub.ctx
        rows = await c.store.list(family.id, "audit", since=c.clock.now() - REPEAT_WINDOW, limit=500)
        return sum(1 for r in rows if r.data.get("event") == "scam_check" and r.data.get("sender_hash") == sender_hash and _RANK.get(str(r.data.get("verdict")), 0) >= _RANK["RISKY"])

    def _sender_hash(self, value: str) -> str | None:
        """A keyed hash of the first phone number, else the first link host, found in the content. The identifier itself is dropped at once."""
        ident: str | None = None
        m = _PHONE.search(value)
        if m:
            ident = "p:" + re.sub(r"\D", "", m.group(1))
        else:
            u = _URL.search(value)
            if u:
                ident = "h:" + u.group(1).lower().rstrip(".,;:)")
        if ident is None:
            return None
        try:
            return self.hub.ctx.store.hasher.cipher.blind_index(ident, label="scam_sender")
        except Exception as e:  # noqa: BLE001 - no key configured: repeat detection is simply off
            log.info("robin: sender hash unavailable (%s)", type(e).__name__)
            return None
