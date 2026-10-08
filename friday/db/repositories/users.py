"""Users, profiles, consents, invites, autonomy settings."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select

from friday.core.models import (
    AutonomyCategory,
    AutonomySetting,
    Consent,
    ConsentKind,
    Invite,
    Profile,
    User,
    UserStatus,
)
from friday.db.repositories._base import Repo, copy_simple, phone_index, row_dict
from friday.db.tables import (
    AutonomySettingRow,
    ConsentRow,
    InviteRow,
    PinLockRow,
    ProfileRow,
    UserRow,
)


def _user(row: UserRow) -> User:
    return User.model_validate(row_dict(row))


class UserRepo(Repo):
    """Implements ``friday.core.interfaces.UserRepository`` (+ extras)."""

    async def get(self, user_id: str) -> User | None:
        async with self.db.session() as s:
            row = await s.get(UserRow, user_id)
            return _user(row) if row else None

    async def get_by_phone(self, phone: str) -> User | None:
        async with self.db.session() as s:
            row = (
                await s.execute(select(UserRow).where(UserRow.phone_hmac == phone_index(phone)))
            ).scalar_one_or_none()
            return _user(row) if row else None

    async def add(self, user: User) -> User:
        async with self.db.session() as s:
            s.add(UserRow(**copy_simple(user, UserRow), phone_hmac=phone_index(user.phone)))
        return user

    async def save(self, user: User) -> User:
        user.updated_at = self.now()
        async with self.db.session() as s:
            await s.merge(UserRow(**copy_simple(user, UserRow), phone_hmac=phone_index(user.phone)))
        return user

    async def list_by_status(self, *statuses: UserStatus) -> list[User]:
        async with self.db.session() as s:
            q = select(UserRow)
            if statuses:
                q = q.where(UserRow.status.in_([st.value for st in statuses]))
            rows = (await s.execute(q.order_by(UserRow.created_at))).scalars().all()
            return [_user(r) for r in rows]

    async def list_active(self) -> list[User]:
        return await self.list_by_status(UserStatus.ACTIVE)


class ProfileRepo(Repo):
    async def get(self, user_id: str) -> Profile | None:
        async with self.db.session() as s:
            row = await s.get(ProfileRow, user_id)
            return Profile.model_validate(row_dict(row)) if row else None

    async def get_or_default(self, user_id: str) -> Profile:
        return await self.get(user_id) or Profile(user_id=user_id)

    async def save(self, profile: Profile) -> Profile:
        profile.updated_at = self.now()
        async with self.db.session() as s:
            await s.merge(ProfileRow(**copy_simple(profile, ProfileRow)))
        return profile


class ConsentRepo(Repo):
    """DPDP consent records (append-only; the latest record per kind wins)."""

    async def add(self, consent: Consent) -> Consent:
        async with self.db.session() as s:
            s.add(ConsentRow(**copy_simple(consent, ConsentRow)))
        return consent

    async def list_for_user(self, user_id: str) -> list[Consent]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(ConsentRow)
                    .where(ConsentRow.user_id == user_id)
                    .order_by(ConsentRow.recorded_at)
                )
            ).scalars()
            return [Consent.model_validate(row_dict(r)) for r in rows]

    async def latest(
        self, user_id: str, kind: ConsentKind, *, person_id: str | None = None
    ) -> Consent | None:
        async with self.db.session() as s:
            q = select(ConsentRow).where(
                ConsentRow.user_id == user_id, ConsentRow.kind == kind.value
            )
            q = q.where(
                ConsentRow.person_id == person_id if person_id else ConsentRow.person_id.is_(None)
            )
            row = (
                await s.execute(q.order_by(ConsentRow.recorded_at.desc()).limit(1))
            ).scalar_one_or_none()
            return Consent.model_validate(row_dict(row)) if row else None

    async def has(self, user_id: str, kind: ConsentKind, *, person_id: str | None = None) -> bool:
        c = await self.latest(user_id, kind, person_id=person_id)
        return bool(c and c.granted)


class InviteRepo(Repo):
    async def add(self, invite: Invite) -> Invite:
        async with self.db.session() as s:
            s.add(InviteRow(**copy_simple(invite, InviteRow)))
        return invite

    async def get(self, code: str) -> Invite | None:
        async with self.db.session() as s:
            row = await s.get(InviteRow, code)
            return Invite.model_validate(row_dict(row)) if row else None

    async def redeem(self, code: str, user_id: str) -> Invite | None:
        """Atomically mark ``code`` redeemed. None if unknown / used / expired."""
        async with self.db.session() as s:
            row = await s.get(InviteRow, code)
            now = self.now()
            if row is None or row.redeemed_by_user_id is not None:
                return None
            if row.expires_at is not None and row.expires_at <= now:
                return None
            row.redeemed_by_user_id = user_id
            row.redeemed_at = now
            return Invite.model_validate(row_dict(row))

    async def list_by_creator(self, user_id: str) -> list[Invite]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(InviteRow)
                    .where(InviteRow.created_by_user_id == user_id)
                    .order_by(InviteRow.created_at)
                )
            ).scalars()
            return [Invite.model_validate(row_dict(r)) for r in rows]

    async def count_by_creator(self, user_id: str) -> int:
        async with self.db.session() as s:
            return int(
                (
                    await s.execute(
                        select(func.count())
                        .select_from(InviteRow)
                        .where(InviteRow.created_by_user_id == user_id)
                    )
                ).scalar_one()
            )

    async def delete_unused_by_creator(self, user_id: str) -> int:
        async with self.db.session() as s:
            rows = (
                (
                    await s.execute(
                        select(InviteRow).where(
                            InviteRow.created_by_user_id == user_id,
                            InviteRow.redeemed_by_user_id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for r in rows:
                await s.delete(r)
            return len(rows)


class AutonomyRepo(Repo):
    async def list_for_user(self, user_id: str) -> list[AutonomySetting]:
        async with self.db.session() as s:
            rows = (
                await s.execute(
                    select(AutonomySettingRow).where(AutonomySettingRow.user_id == user_id)
                )
            ).scalars()
            return [AutonomySetting.model_validate(row_dict(r)) for r in rows]

    async def get(self, user_id: str, category: AutonomyCategory) -> AutonomySetting:
        """Stored setting or the default (SUGGEST, enabled)."""
        async with self.db.session() as s:
            row = await s.get(AutonomySettingRow, (user_id, category.value))
            if row:
                return AutonomySetting.model_validate(row_dict(row))
        return AutonomySetting(user_id=user_id, category=category)

    async def upsert(self, setting: AutonomySetting) -> AutonomySetting:
        setting.updated_at = self.now()
        async with self.db.session() as s:
            await s.merge(AutonomySettingRow(**copy_simple(setting, AutonomySettingRow)))
        return setting

    async def upsert_many(self, settings: Sequence[AutonomySetting]) -> None:
        for st in settings:
            await self.upsert(st)


class PinLock(BaseModel):
    user_id: str
    strikes: int = 0
    locked_until: datetime | None = None
    support_required: bool = False
    reason: str | None = None
    updated_at: datetime | None = None

    def active(self, now: datetime) -> bool:
        return self.support_required or (self.locked_until is not None and self.locked_until > now)


class PinLockRepo(Repo):
    """SECURITY-23 lock state (strike count, lock expiry, support-only unlock)."""

    async def get(self, user_id: str) -> PinLock:
        async with self.db.session() as s:
            row = await s.get(PinLockRow, user_id)
            return PinLock.model_validate(row_dict(row)) if row else PinLock(user_id=user_id)

    async def save(self, lock: PinLock) -> PinLock:
        lock.updated_at = self.now()
        async with self.db.session() as s:
            await s.merge(PinLockRow(**lock.model_dump()))
        return lock

    async def clear(self, user_id: str) -> None:
        """Support-verified unlock."""
        async with self.db.session() as s:
            row = await s.get(PinLockRow, user_id)
            if row is not None:
                await s.delete(row)
