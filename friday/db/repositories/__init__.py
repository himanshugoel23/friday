"""Repositories: ORM rows <-> ``friday.core.models`` domain objects.

``build_repositories(c)`` (FACTORIES["repos"]) returns a :class:`Repositories`
bundle. Every repository implements the matching Protocol in
``friday.core.interfaces`` (TaskRepository, UserRepository, PersonRepository,
PlaceRepository, BusinessRepository, IdentifierRepository, FactRepository,
NudgeRepository) and adds extra query helpers documented on each class.

Each method runs in its own short transaction (``db.session()``) and returns
domain models - callers never see ORM rows.

    repos = c.repos
    user = await repos.users.get_by_phone("+919800000001")
    await repos.tasks.save(task)

Owner: Backend Engineer A.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from friday.core.clock import Clock
from friday.db.repositories._base import SecretBox
from friday.db.repositories.businesses import BusinessRepo
from friday.db.repositories.calls import (
    CallbackMatch,
    CallMemory,
    CallMemoryRepo,
    InboundContact,
    InboundKind,
    MatchStatus,
)
from friday.db.repositories.chatbot import ChatbotRepo
from friday.db.repositories.consumer_calls import (
    CallDncRepo,
    ConsumerCallsRepo,
    ConsumerContactsRepo,
)
from friday.db.repositories.documents import DocumentRepo
from friday.db.repositories.evidence import EvidenceRepo
from friday.db.repositories.family_drive import FamilyDriveRepo
from friday.db.repositories.google import GoogleRepo
from friday.db.repositories.lifestate import LifeRepo
from friday.db.repositories.memory import AuditRepo, CostRepo, FactRepo, IdentifierRepo
from friday.db.repositories.messages import MessageRepo, StoredMessage
from friday.db.repositories.nudges import NudgeRepo
from friday.db.repositories.numbers import DncEntry, NumberAssignment, NumberRepo, OutcomeRecord
from friday.db.repositories.people import PersonRepo, PlaceRepo, SuppressionRepo
from friday.db.repositories.purge import DataPurger
from friday.db.repositories.refunds import RefundRepo
from friday.db.repositories.tasks import TaskRepo
from friday.db.repositories.trips import PerkRepo, TripRepo
from friday.db.repositories.users import (
    AutonomyRepo,
    ConsentRepo,
    InviteRepo,
    PinLock,
    PinLockRepo,
    ProfileRepo,
    UserRepo,
)
from friday.db.session import Database

if TYPE_CHECKING:
    from friday.core.container import Container

__all__ = [
    "AuditRepo",
    "AutonomyRepo",
    "BusinessRepo",
    "ChatbotRepo",
    "CallMemory",
    "CallMemoryRepo",
    "CallbackMatch",
    "InboundContact",
    "InboundKind",
    "MatchStatus",
    "ConsentRepo",
    "CostRepo",
    "CallDncRepo",
    "ConsumerCallsRepo",
    "ConsumerContactsRepo",
    "DataPurger",
    "DocumentRepo",
    "EvidenceRepo",
    "FactRepo",
    "FamilyDriveRepo",
    "GoogleRepo",
    "IdentifierRepo",
    "LifeRepo",
    "PerkRepo",
    "RefundRepo",
    "TripRepo",
    "InviteRepo",
    "MessageRepo",
    "NudgeRepo",
    "NumberRepo",
    "NumberAssignment",
    "OutcomeRecord",
    "DncEntry",
    "PersonRepo",
    "PinLock",
    "PinLockRepo",
    "PlaceRepo",
    "ProfileRepo",
    "Repositories",
    "StoredMessage",
    "SuppressionRepo",
    "TaskRepo",
    "UserRepo",
    "build_repositories",
    "make_repositories",
]


@dataclass
class Repositories:
    db: Database
    users: UserRepo
    profiles: ProfileRepo
    consents: ConsentRepo
    invites: InviteRepo
    autonomy: AutonomyRepo
    people: PersonRepo
    places: PlaceRepo
    businesses: BusinessRepo
    identifiers: IdentifierRepo
    facts: FactRepo
    messages: MessageRepo
    tasks: TaskRepo  # + calls, quotes, mid-call questions, hotel bookings
    nudges: NudgeRepo
    audit: AuditRepo
    costs: CostRepo
    calls: CallMemoryRepo  # call memory + inbound calls/missed calls/business messages
    suppressions: SuppressionRepo
    pin_locks: PinLockRepo
    numbers: NumberRepo  # caller-ID pool state (NP-1)
    google: GoogleRepo  # per-user Google OAuth connection (friday/google)
    life: LifeRepo  # per-user life state (friday/lifestate)
    consumer_calls: ConsumerCallsRepo  # call requests, briefs, outcomes (friday/calls)
    consumer_contacts: ConsumerContactsRepo  # the user's own contact book (friday/calls)
    call_dnc: CallDncRepo  # global do-not-call registry, keyed hash only (friday/calls)
    purger: DataPurger
    evidence: EvidenceRepo | None = None  # proof items + done claims (friday/evidence)
    documents: DocumentRepo | None = None  # understood photos/documents (friday/docunderstand)
    family_drive: FamilyDriveRepo | None = None  # Drive links, folders, shares (friday/familydrive)
    trips: TripRepo | None = None  # trips, legs, tasks, nudges (friday/trips)
    card_perks: PerkRepo | None = None  # shared verified lounge perks (friday/trips/perks)
    refunds: RefundRepo | None = None  # refund cases, events, evidence (friday/refunds)
    chatbot: ChatbotRepo | None = None  # first-run state, waitlist, wishlist (friday/chatbot)
    retention: Any = None  # RetentionService: .run(now, recording_days, preconsent_days)


def make_repositories(
    db: Database,
    clock: Clock | None,
    secret_key: str,
    *,
    previous_keys: Sequence[str] = (),
    store_factory: Callable[[], Any] | None = None,
    telephony_factory: Callable[[], Any] | None = None,
) -> Repositories:
    """``secret_key`` keys the identifier SecretBox (HKDF, purpose-labelled);
    ``previous_keys`` stay readable after a rotation (SECURITY-13)."""
    box = SecretBox(secret_key, previous=previous_keys)
    repos = Repositories(
        db=db,
        users=UserRepo(db, clock),
        profiles=ProfileRepo(db, clock),
        consents=ConsentRepo(db, clock),
        invites=InviteRepo(db, clock),
        autonomy=AutonomyRepo(db, clock),
        people=PersonRepo(db, clock),
        places=PlaceRepo(db, clock),
        businesses=BusinessRepo(db, clock),
        identifiers=IdentifierRepo(db, clock, box),
        facts=FactRepo(db, clock),
        messages=MessageRepo(db, clock),
        tasks=TaskRepo(db, clock),
        nudges=NudgeRepo(db, clock),
        audit=AuditRepo(db, clock),
        costs=CostRepo(db, clock),
        calls=CallMemoryRepo(db, clock),
        suppressions=SuppressionRepo(db, clock),
        pin_locks=PinLockRepo(db, clock),
        numbers=NumberRepo(db, clock),
        google=GoogleRepo(db, clock),
        life=LifeRepo(db, clock),
        consumer_calls=ConsumerCallsRepo(db, clock),
        consumer_contacts=ConsumerContactsRepo(db, clock),
        call_dnc=CallDncRepo(db, clock),
        purger=DataPurger(db, clock),
        chatbot=ChatbotRepo(db, clock),
        evidence=EvidenceRepo(db, clock),
        documents=DocumentRepo(db, clock),
        family_drive=FamilyDriveRepo(db, clock),
        trips=TripRepo(db, clock),
        card_perks=PerkRepo(db, clock),
        refunds=RefundRepo(db, clock),
    )
    from friday.db.retention import RetentionService

    if store_factory is None:
        from friday.core.config import Settings
        from friday.db.objectstore import build_object_store

        def store_factory() -> Any:  # dev/test default: local media dir
            return build_object_store(Settings())

    repos.retention = RetentionService(repos, store_factory, telephony_factory)
    return repos


def build_repositories(c: Container) -> Repositories:
    s = c.settings
    # SECURITY-30: a dedicated field key when configured; the dev fallback is the app
    # secret, which SecretBox separates from the PIN pepper / index key by HKDF label.
    key = s.field_key.get_secret_value() if s.field_key else s.secret_key.get_secret_value()
    from friday.core.container import ComponentNotAvailable
    from friday.db.objectstore import build_object_store

    def telephony() -> Any:
        try:
            return c.get("telephony")
        except ComponentNotAvailable:
            return None

    return make_repositories(
        c.db,
        c.clock,
        key,
        store_factory=lambda: build_object_store(s),
        telephony_factory=telephony,
    )
