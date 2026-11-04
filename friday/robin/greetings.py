# ruff: noqa: E501
"""Good-morning digest and festival graphics for the parent (per-family on/off, default OFF).

* The festival calendar is a data file (``data/festivals.json``). A festival whose date is not marked
  ``verified`` is NEVER sent. Regions filter regional festivals.
* Graphics are ORIGINAL and template-based, drawn server-side as SVG from plain geometry and the greeting text
  (no scraped or religious imagery). PNG conversion needs an optional library and is best effort
  (``to_png`` returns None without it); WhatsApp needs PNG/JPEG, so a PNG converter must be chosen before launch.
  Devanagari text needs a font on the converter: UNVERIFIED.
* Sent through the ``ParentChannel`` (WhatsApp; template + media outside the 24 h window); the parent can forward
  the image to family groups. Respects quiet hours, the parent's pause, and the care protocol. All wording PENDING.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.robin.context import Ctx
from friday.robin.family import FamilyService
from friday.robin.medicine import MedicineService
from friday.robin.models import Family, FamilyStatus, Member
from friday.robin.store import Record

log = get_logger(__name__)
DATA = Path(__file__).parent / "data" / "festivals.json"


def load_festivals(path: Path = DATA) -> list[dict[str, Any]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["festivals"])


def festivals_on(day: date, regions: list[str] | None = None, *, festivals: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Verified festivals on ``day``; with ``regions`` set only those tagged 'all' or matching."""
    out = []
    for f in festivals if festivals is not None else load_festivals():
        if not f.get("verified"):
            continue
        hit = f.get("date") == day.isoformat() or f.get("month_day") == day.strftime("%m-%d")
        if not hit:
            continue
        tags = set(f.get("regions") or ["all"])
        if regions and not (tags & ({"all"} | set(regions))) or (not regions and "all" not in tags):
            continue
        out.append(f)
    return out


def render_svg(festival_id: str, text: str, *, size: int = 1080) -> str:
    """An original graphic: a gradient from the festival id, a ring of petals made of circles, the greeting text."""
    h = hashlib.sha256(festival_id.encode()).digest()
    c1, c2 = f"#{h[0]:02x}{h[1]:02x}{h[2]:02x}", f"#{h[3]:02x}{h[4]:02x}{h[5]:02x}"
    cx = cy = size // 2
    petals = "".join(
        f'<circle cx="{cx + int(300 * math.cos(k * 6.2832 / 12))}" cy="{cy - 140 + int(300 * math.sin(k * 6.2832 / 12))}" r="70" fill="#ffffff" fill-opacity="0.18"/>' for k in range(12)
    )
    words, lines, cur = escape(text).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 26:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    tspans = "".join(f'<tspan x="{cx}" dy="{64 if i else 0}">{ln}</tspan>' for i, ln in enumerate(lines))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient></defs>'
        f'<rect width="{size}" height="{size}" fill="url(#g)"/>{petals}<circle cx="{cx}" cy="{cy - 140}" r="120" fill="#ffffff" fill-opacity="0.35"/>'
        f'<text x="{cx}" y="{size - 330}" font-size="56" fill="#ffffff" text-anchor="middle" font-family="sans-serif">{tspans}</text></svg>'
    )


def to_png(svg: str) -> bytes | None:
    try:
        import cairosvg  # type: ignore[import-not-found]

        return cairosvg.svg2png(bytestring=svg.encode("utf-8"))
    except Exception:  # noqa: BLE001 - optional converter not installed
        return None


class GreetingService:
    def __init__(self, ctx: Ctx, family_svc: FamilyService, meds: MedicineService) -> None:
        self.ctx, self.fam, self.meds, self.store = ctx, family_svc, meds, ctx.store

    async def tick(self) -> int:
        n = 0
        for fam in await self.store.all_families(("active",)):
            parent = await self.ctx.parent(fam)
            if parent is not None and (fam.settings.good_morning or fam.settings.festival_graphics):
                n += int(await self.send_today(fam, parent))
        return n

    async def compose(self, fam: Family, parent: Member, day: date) -> tuple[str, dict[str, Any] | None]:
        c = self.ctx
        lang = parent.language
        slots = await c.slots(fam)
        parts = []
        if fam.settings.good_morning:
            parts.append(c.say("gm.greet", lang, date=day.strftime("%d %b %Y"), **slots))
            items = [f"{m.name} {', '.join(m.times)}" for _, m in await self.meds.meds(fam)]
            if items:
                parts.append(c.say("gm.meds", lang, meds="; ".join(items), **slots))
        fest = None
        if fam.settings.festival_graphics:
            hits = festivals_on(day)
            if hits:
                fest = hits[0]
                parts.append(c.say("fest.greeting", lang, festival=fest["name"].get(lang, fest["name"]["en"]), **slots))
                parts.append(c.say("gm.share", lang, **slots))
        return "\n".join(parts), fest

    async def send_today(self, fam: Family, parent: Member) -> bool:
        c = self.ctx
        now = c.clock.now()
        loc = c.local(parent, now)
        h, m = (int(x) for x in fam.settings.good_morning_time.split(":"))
        if parent.paused or fam.status != FamilyStatus.ACTIVE or loc < loc.replace(hour=h, minute=m, second=0, microsecond=0):
            return False
        if c.in_quiet(parent, fam, now) or await c.care_active(fam.owner_user_id):
            return False
        key = f"gm:{loc.date().isoformat()}"
        if await self.store.by_key(fam.id, "digest", key) is not None:
            return False
        text, fest = await self.compose(fam, parent, loc.date())
        if not text:
            return False
        _, created = await self.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="digest", key=key, status="sent", at=now, data={"festival": fest["id"] if fest else None}))
        if not created:
            return False
        ch = c.parent_channel
        if ch is None:  # no WhatsApp adapter yet: the widget/app picks it up from the outbox
            await self.store.put(Record(family_id=fam.id, user_id=fam.owner_user_id, kind="pending", status="queued", at=now, data={"member_id": parent.id, "line": "gm", "purpose": "good_morning", "text": text, "incident_id": None}))
        elif fest is not None:
            svg = render_svg(fest["id"], fest["name"].get(parent.language, fest["name"]["en"]))
            png = to_png(svg)
            await ch.send_template(parent, "good_morning_festival", {"text": text}, png or svg.encode(), "image/png" if png else "image/svg+xml")
        else:
            await ch.send_text(parent, text)
            await ch.send_voice_note(parent, text, parent.language)
        await c.audit(fam, "greeting", f"Sent {fam.parent_label} a good-morning message" + (f" with a {fest['name']['en']} greeting." if fest else "."))
        return True
