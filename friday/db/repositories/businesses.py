"""Businesses (shared across users) + per-user vendor memory (B20)."""

from __future__ import annotations

from sqlalchemy import select

from friday.core.models import Business, BusinessHours, GeoPoint, InteractionKind, VendorInteraction
from friday.db.repositories._base import Repo, copy_simple, dump_json, row_dict
from friday.db.tables import BusinessRow, VendorInteractionRow


def _business(row: BusinessRow) -> Business:
    d = row_dict(row, skip={"lat", "lng", "hours"})
    if row.lat is not None and row.lng is not None:
        d["location"] = GeoPoint(lat=row.lat, lng=row.lng)
    d["hours"] = BusinessHours.model_validate(row.hours) if row.hours else None
    return Business.model_validate(d)


def _interaction(row: VendorInteractionRow) -> VendorInteraction:
    return VendorInteraction.model_validate(row_dict(row))


class BusinessRepo(Repo):
    """Implements ``BusinessRepository``."""

    async def get(self, business_id: str) -> Business | None:
        async with self.db.session() as s:
            row = await s.get(BusinessRow, business_id)
            return _business(row) if row else None

    async def get_by_phone(self, phone: str) -> Business | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(BusinessRow)
                    .where((BusinessRow.phone == phone) | (BusinessRow.whatsapp_phone == phone))
                    .order_by(BusinessRow.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return _business(row) if row else None

    async def get_by_directory_id(self, provider: str, place_id: str) -> Business | None:
        async with self.db.session() as s:
            row = (
                await s.execute(
                    select(BusinessRow).where(
                        BusinessRow.directory_provider == provider,
                        BusinessRow.directory_place_id == place_id,
                    )
                )
            ).scalar_one_or_none()
            return _business(row) if row else None

    async def upsert(self, business: Business) -> Business:
        values = copy_simple(business, BusinessRow, skip={"hours"})
        values["hours"] = dump_json(business.hours)
        values["lat"] = business.location.lat if business.location else None
        values["lng"] = business.location.lng if business.location else None
        async with self.db.session() as s:
            await s.merge(BusinessRow(**values))
        return business

    async def add_interaction(self, interaction: VendorInteraction) -> VendorInteraction:
        async with self.db.session() as s:
            s.add(VendorInteractionRow(**copy_simple(interaction, VendorInteractionRow)))
        return interaction

    async def interactions(
        self,
        user_id: str,
        *,
        business_id: str | None = None,
        limit: int = 50,
        kind: InteractionKind | None = None,
    ) -> list[VendorInteraction]:
        """Newest first."""
        async with self.db.session() as s:
            q = select(VendorInteractionRow).where(VendorInteractionRow.user_id == user_id)
            if business_id:
                q = q.where(VendorInteractionRow.business_id == business_id)
            if kind:
                q = q.where(VendorInteractionRow.kind == kind.value)
            rows = (
                await s.execute(q.order_by(VendorInteractionRow.at.desc()).limit(limit))
            ).scalars()
            return [_interaction(r) for r in rows]

    async def known_for_user(self, user_id: str, *, limit: int = 30) -> list[Business]:
        """Businesses this user has history with, most recent first."""
        async with self.db.session() as s:
            sub = (
                select(
                    VendorInteractionRow.business_id,
                    VendorInteractionRow.at,
                )
                .where(VendorInteractionRow.user_id == user_id)
                .order_by(VendorInteractionRow.at.desc())
            )
            seen: list[str] = []
            for bid, _at in (await s.execute(sub)).all():
                if bid not in seen:
                    seen.append(bid)
                if len(seen) >= limit:
                    break
            if not seen:
                return []
            rows = (await s.execute(select(BusinessRow).where(BusinessRow.id.in_(seen)))).scalars()
            by_id = {r.id: _business(r) for r in rows}
            return [by_id[b] for b in seen if b in by_id]
