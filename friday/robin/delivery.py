# ruff: noqa: E501
"""Delivery (T08): what happens when a message cannot reach its person.

``ChildInbox``  the LAST rung of the child's chain WhatsApp -> SMS (the Notifier does both) -> the chat inbox. A message the child's phone
                could not receive waits here (a ``pending`` record, status ``held``) and is shown at the child's next message in the chat
                (web chat or WhatsApp), oldest first, once. Holding never hides the failure: ``Ctx.tell_child`` still returns False, so the
                alert engine flags ``delivery_failed`` and escalates one rung earlier.
``OutboxDrain`` the parent's app outbox (``pending`` records, status ``queued``, written when there was no parent channel or a send failed).
                With a ``ctx.parent_channel`` it sends them, once: a line is claimed (``queued`` -> ``sending``) before it is sent, so two
                ticks, or the tick and the parent's own message, can never send it twice; a failed send puts it back. Identical lines
                (same parent, same words) are sent once; a line the parent already got in the last two hours is not repeated. When the 24 h window
                is closed ``channel.reopen`` goes first (at most once per ``REOPEN_EVERY``), then the lines follow (the channel falls to the
                pre-approved template). The parent's pause holds the outbox; stale non-essential lines expire instead of arriving a day late.

Nothing here logs words or numbers; counts and ids only.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from friday.core.logging import get_logger
from friday.robin.context import Ctx
from friday.robin.models import Family, FamilyStatus, Member
from friday.robin.store import Record

log = get_logger(__name__)

HELD_MAX = 20  # lines held per family
DEDUPE_WINDOW = timedelta(hours=2)  # the same words sent to the same parent within this time are not repeated
REOPEN_EVERY = timedelta(hours=12)
STALE_AFTER = timedelta(hours=48)  # a queued good-morning or reminder from two days ago is dropped; the consent notice never expires
NEVER_STALE = ("notify",)


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


class ChildInbox:
    """The chat inbox of the child: lines their phone could not receive."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx, self.store = ctx, ctx.store

    async def hold(self, family: Family, text: str) -> bool:
        """Keep ``text`` for the child's next message. The same words within five minutes are held once."""
        c = self.ctx
        try:
            held = await self.store.list(family.id, "pending", status="held")
            if len(held) >= HELD_MAX:
                return False
            bucket = int(c.clock.now().timestamp() // 300)
            _, created = await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="pending", key=f"held:{_digest(text, str(bucket))}", status="held", at=c.clock.now(), data={"text": text, "purpose": "child_inbox"}))
            return created
        except Exception as e:  # noqa: BLE001 - holding is best effort and must never raise into a safety path
            log.warning("robin: could not hold a message for the child (%s)", type(e).__name__)
            return False

    async def count(self, family: Family) -> int:
        return len(await self.store.list(family.id, "pending", status="held"))

    async def deliver(self, family: Family, send: Any) -> int:
        """Show the held lines now (the child just wrote, so their phone is reachable). ``send`` is the raw ``Ctx.send``. Returns how many were
        delivered; a line that fails again stays held and ends the run."""
        c = self.ctx
        rows = await self.store.list(family.id, "pending", status="held")
        if not rows:
            return 0
        lang = await c.chat_lang(family)
        sent = 0
        for r in rows:
            if not await self.store.cas(r.id, "held", status="sending"):
                continue  # another run took it
            try:
                if sent == 0:
                    await send(family.owner_user_id, c.say("inbox.head", lang), [])
                await send(family.owner_user_id, str(r.data.get("text", "")), [])
            except Exception as e:  # noqa: BLE001
                await self.store.cas(r.id, "sending", status="held")
                log.warning("robin: held message still not delivered (%s)", type(e).__name__)
                break
            await self.store.cas(r.id, "sending", status="sent", data={"purpose": "child_inbox"})  # the words are not kept after delivery
            sent += 1
        if sent:
            await c.audit(family, "inbox", f"Showed you {sent} message(s) your phone could not receive earlier.")
        return sent


class OutboxDrain:
    """Drains the parent's ``queued`` app-outbox records through ``ctx.parent_channel``."""

    def __init__(self, ctx: Ctx) -> None:
        self.ctx, self.store = ctx, ctx.store

    async def tick(self) -> int:
        if self.ctx.parent_channel is None:
            return 0
        n = 0
        for fam in await self.store.all_families(("active", "onboarding")):
            n += await self.drain_family(fam)
        return n

    async def drain_family(self, family: Family) -> int:
        c = self.ctx
        if c.parent_channel is None or family.status not in (FamilyStatus.ACTIVE, FamilyStatus.ONBOARDING):
            return 0
        parent = await c.parent(family)
        if parent is None or parent.paused or not parent.phone:
            return 0
        return await self.drain_member(family, parent)

    async def drain_member(self, family: Family, parent: Member) -> int:
        """Send what waits for ``parent``. Returns the number of lines delivered."""
        c, ch = self.ctx, self.ctx.parent_channel
        if ch is None or parent.paused or not parent.phone:
            return 0
        queued = [r for r in await self.store.list(family.id, "pending", status="queued") if r.data.get("member_id") == parent.id and r.data.get("text")]
        if not queued:
            return 0
        now = c.clock.now()
        recent = {_digest(parent.id, str(r.data.get("text", ""))) for r in await self.store.list(family.id, "pending", status="sent", since=now - DEDUPE_WINDOW) if r.data.get("member_id") == parent.id}
        todo: list[Record] = []
        seen: set[str] = set()
        for r in queued:  # oldest first
            d = _digest(parent.id, str(r.data["text"]))
            if r.data.get("purpose") not in NEVER_STALE and now - r.at > STALE_AFTER:
                await self.store.cas(r.id, "queued", status="expired", data={"member_id": parent.id, "purpose": r.data.get("purpose")})
                continue
            if d in recent or d in seen:  # already delivered, or the same words twice in this batch: once is enough
                await self.store.cas(r.id, "queued", status="deduped", data={"member_id": parent.id, "purpose": r.data.get("purpose")})
                continue
            seen.add(d)
            todo.append(r)
        if not todo:
            return 0
        if not await self._window_open(ch, parent):
            await self._reopen(family, parent)
        sent = 0
        for r in todo:
            text = str(r.data["text"])
            if not await self.store.cas(r.id, "queued", status="sending"):
                continue  # claimed by another tick or by the device (take_app_notifications)
            ok = False
            try:
                voice = bool(await ch.send_voice_note(parent, text, parent.language))
                txt = bool(await ch.send_text(parent, text))
                ok = voice or txt
            except Exception as e:  # noqa: BLE001
                log.warning("robin: outbox line to member %s failed (%s)", parent.id, type(e).__name__)
            if not ok:
                await self.store.cas(r.id, "sending", status="queued")
                break  # keep the order: later lines wait behind this one
            await self.store.cas(r.id, "sending", status="sent", data={**r.data})
            sent += 1
        if sent:
            await c.audit(family, "outbox", f"Delivered {sent} waiting message(s) to {family.parent_label}.", purpose="outbox")
        return sent

    @staticmethod
    async def _window_open(ch: Any, parent: Member) -> bool:
        probe = getattr(ch, "in_window", None)
        if probe is None:
            return True  # a channel that does not know its window (it will use a template itself)
        try:
            return bool(await probe(parent.phone))
        except Exception:  # noqa: BLE001
            return True

    async def _reopen(self, family: Family, parent: Member) -> bool:
        """The 24 h window is closed: ask the parent (template, one per ``REOPEN_EVERY``) to say anything so the lines can follow."""
        c, ch = self.ctx, self.ctx.parent_channel
        reopen = getattr(ch, "reopen", None)
        if reopen is None:
            return False
        now = c.clock.now()
        key = f"reopen:{parent.id}"
        old = await self.store.by_key(family.id, "pending", key)
        if old is not None and now - old.at < REOPEN_EVERY:
            return False
        if old is not None:
            await self.store.delete_record(old.id)
        slots = await c.slots(family)
        try:
            ok = bool(await reopen(parent, family.parent_label, slots["child"]))
        except Exception as e:  # noqa: BLE001
            log.warning("robin: reopen for member %s failed (%s)", parent.id, type(e).__name__)
            return False
        if ok:
            await self.store.put(Record(family_id=family.id, user_id=family.owner_user_id, kind="pending", key=key, status="done", at=now, data={}))
        return ok
