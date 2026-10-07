""""Delete everything" (DPDP right to erasure): hard-delete every user-keyed row,
keep a PII-free user tombstone and scrubbed audit entries."""

from __future__ import annotations

from sqlalchemy import delete, update

from friday.core.models import OnboardingStep, UserStatus
from friday.db.repositories._base import Repo
from friday.db.tables import (
    AccountIdentifierRow,
    AuditRow,
    AutonomySettingRow,
    BusinessRow,
    ConsentRow,
    FactRow,
    HotelBookingRow,
    InviteRow,
    MessageRow,
    NudgeFeedbackRow,
    NudgeRow,
    PersonRow,
    PlaceRow,
    ProfileRow,
    TaskRow,
    UserRow,
    VendorInteractionRow,
)


def tombstone_phone(user_id: str) -> str:
    return f"del:{user_id[:16]}"


class DataPurger(Repo):
    async def purge_user(self, user_id: str) -> dict[str, int]:
        """Returns per-table deleted-row counts (no PII). Cost ledger rows (amounts
        only) are kept for ops accounting."""
        counts: dict[str, int] = {}
        async with self.db.session() as s:

            async def wipe(table: type, *conds: object) -> None:
                res = await s.execute(delete(table).where(*conds))
                counts[table.__tablename__] = int(res.rowcount or 0)  # type: ignore[attr-defined]

            await wipe(NudgeFeedbackRow, NudgeFeedbackRow.user_id == user_id)
            await wipe(NudgeRow, NudgeRow.user_id == user_id)
            await wipe(HotelBookingRow, HotelBookingRow.user_id == user_id)
            await wipe(TaskRow, TaskRow.requester_user_id == user_id)  # cascades calls/quotes/...
            await wipe(MessageRow, MessageRow.user_id == user_id)
            await wipe(FactRow, FactRow.user_id == user_id)
            await wipe(AccountIdentifierRow, AccountIdentifierRow.user_id == user_id)
            await wipe(VendorInteractionRow, VendorInteractionRow.user_id == user_id)
            await wipe(PlaceRow, PlaceRow.owner_user_id == user_id)
            await wipe(ConsentRow, ConsentRow.user_id == user_id)
            await wipe(PersonRow, PersonRow.owner_user_id == user_id)
            await wipe(AutonomySettingRow, AutonomySettingRow.user_id == user_id)
            await wipe(ProfileRow, ProfileRow.user_id == user_id)
            await wipe(
                InviteRow,
                InviteRow.created_by_user_id == user_id,
                InviteRow.redeemed_by_user_id.is_(None),
            )
            await s.execute(
                update(BusinessRow)
                .where(BusinessRow.created_by_user_id == user_id)
                .values(created_by_user_id=None)
            )
            await s.execute(
                update(PersonRow)
                .where(PersonRow.linked_user_id == user_id)
                .values(linked_user_id=None)
            )
            await s.execute(
                update(AuditRow)
                .where(AuditRow.user_id == user_id)
                .values(detail={}, subject_id=None)
            )
            await s.execute(
                update(UserRow)
                .where(UserRow.id == user_id)
                .values(
                    phone=tombstone_phone(user_id),
                    status=UserStatus.DELETED.value,
                    onboarding_step=OnboardingStep.DONE.value,
                    pin_hash=None,
                    pin_failed_attempts=0,
                    invited_by_user_id=None,
                    invites_remaining=0,
                    last_inbound_at=None,
                    updated_at=self.now(),
                )
            )
        return counts
