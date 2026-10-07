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

from dataclasses import dataclass
from typing import TYPE_CHECKING

from friday.core.clock import Clock
from friday.db.repositories._base import SecretBox
from friday.db.repositories.businesses import BusinessRepo
from friday.db.repositories.memory import AuditRepo, CostRepo, FactRepo, IdentifierRepo
from friday.db.repositories.messages import MessageRepo, StoredMessage
from friday.db.repositories.nudges import NudgeRepo
from friday.db.repositories.people import PersonRepo, PlaceRepo
from friday.db.repositories.purge import DataPurger
from friday.db.repositories.tasks import TaskRepo
from friday.db.repositories.users import (
    AutonomyRepo,
    ConsentRepo,
    InviteRepo,
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
    "ConsentRepo",
    "CostRepo",
    "DataPurger",
    "FactRepo",
    "IdentifierRepo",
    "InviteRepo",
    "MessageRepo",
    "NudgeRepo",
    "PersonRepo",
    "PlaceRepo",
    "ProfileRepo",
    "Repositories",
    "StoredMessage",
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
    purger: DataPurger


def make_repositories(db: Database, clock: Clock | None, secret_key: str) -> Repositories:
    box = SecretBox(secret_key)
    return Repositories(
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
        purger=DataPurger(db, clock),
    )


def build_repositories(c: Container) -> Repositories:
    return make_repositories(c.db, c.clock, c.settings.secret_key.get_secret_value())
