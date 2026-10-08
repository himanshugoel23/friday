"""Circle (people) and saved places."""

from __future__ import annotations

from sqlalchemy import select

from friday.core.models import GeoPoint, Person, PersonConsent, Place
from friday.db.repositories._base import Repo, copy_simple, phone_index, row_dict
from friday.db.tables import PersonRow, PlaceRow, SuppressionRow


def _person(row: PersonRow) -> Person:
    return Person.model_validate(row_dict(row))


def _place(row: PlaceRow) -> Place:
    d = row_dict(row, skip={"lat", "lng"})
    if row.lat is not None and row.lng is not None:
        d["location"] = GeoPoint(lat=float(row.lat), lng=float(row.lng))
    return Place.model_validate(d)


class PersonRepo(Repo):
    """Implements ``PersonRepository``. ``notes`` stay private to the owner: callers
    must never pass them to businesses or other circle members."""

    async def get(self, person_id: str) -> Person | None:
        async with self.db.session() as s:
            row = await s.get(PersonRow, person_id)
            return _person(row) if row else None

    async def list_for_owner(self, owner_user_id: str) -> list[Person]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(PersonRow)
                    .where(PersonRow.owner_user_id == owner_user_id)
                    .order_by(PersonRow.created_at)
                )
            ).scalars()
            return [_person(r) for r in rows]

    async def find_by_phone(self, phone: str) -> list[Person]:
        """All circle entries with this phone (across owners) - inbound from a
        circle member (opt-in replies)."""
        async with self.db.session() as s:
            rows = (await s.execute(select(PersonRow).where(PersonRow.phone_hmac == phone_index(phone)))).scalars()
            return [_person(r) for r in rows]

    async def upsert(self, person: Person) -> Person:
        """SECURITY-16: saving OPTED_OUT suppresses the phone for every owner; a new row
        for a suppressed phone starts OPTED_OUT (delete + re-add can't reset it)."""
        person.updated_at = self.now()
        async with self.db.session() as s:
            if person.phone:
                h = phone_index(person.phone)
                if person.contact_consent == PersonConsent.OPTED_OUT:
                    await _suppress(s, h, "contact", "opted_out", self.now())
                elif await _is_suppressed(s, h, "contact"):
                    person.contact_consent = PersonConsent.OPTED_OUT
                if person.checkin_consent == PersonConsent.OPTED_OUT:
                    await _suppress(s, h, "checkin", "opted_out", self.now())
                elif await _is_suppressed(s, h, "checkin"):
                    person.checkin_consent = PersonConsent.OPTED_OUT
            await s.merge(
                PersonRow(
                    **copy_simple(person, PersonRow),
                    phone_hmac=phone_index(person.phone) if person.phone else None,
                )
            )
        return person

    async def delete(self, person_id: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(PersonRow, person_id)
            if row is None:
                return False
            await s.delete(row)
            return True


async def _is_suppressed(s, phone_hmac: str, scope: str) -> bool:  # noqa: ANN001
    row = (
        await s.execute(
            select(SuppressionRow.id).where(
                SuppressionRow.phone_hmac == phone_hmac, SuppressionRow.scope == scope
            )
        )
    ).first()
    return row is not None


async def _suppress(s, phone_hmac: str, scope: str, reason: str, at) -> None:  # noqa: ANN001
    if not await _is_suppressed(s, phone_hmac, scope):
        s.add(SuppressionRow(phone_hmac=phone_hmac, scope=scope, reason=reason, at=at))
        await s.flush()


class SuppressionRepo(Repo):
    """Per-phone suppression (STOP / opt-out), across all owners (SECURITY-16)."""

    async def add(self, phone: str, *, scope: str = "contact", reason: str = "stop") -> None:
        async with self.db.session() as s:
            await _suppress(s, phone_index(phone), scope, reason, self.now())

    async def is_suppressed(self, phone: str, *, scope: str = "contact") -> bool:
        async with self.db.session() as s:
            return await _is_suppressed(s, phone_index(phone), scope)


class PlaceRepo(Repo):
    """Implements ``PlaceRepository``."""

    async def get(self, place_id: str) -> Place | None:
        async with self.db.session() as s:
            row = await s.get(PlaceRow, place_id)
            return _place(row) if row else None

    async def list_for_owner(
        self, owner_user_id: str, *, include_ephemeral: bool = False
    ) -> list[Place]:
        async with self.db.session() as s:
            q = select(PlaceRow).where(PlaceRow.owner_user_id == owner_user_id)
            if not include_ephemeral:
                q = q.where(PlaceRow.ephemeral.is_(False))
            rows = (await s.execute(q.order_by(PlaceRow.created_at))).scalars()
            return [_place(r) for r in rows]

    async def upsert(self, place: Place) -> Place:
        place.updated_at = self.now()
        values = copy_simple(place, PlaceRow)
        values["lat"] = repr(place.location.lat) if place.location else None
        values["lng"] = repr(place.location.lng) if place.location else None
        async with self.db.session() as s:
            await s.merge(PlaceRow(**values))
        return place

    async def delete(self, place_id: str) -> bool:
        async with self.db.session() as s:
            row = await s.get(PlaceRow, place_id)
            if row is None:
                return False
            await s.delete(row)
            return True
