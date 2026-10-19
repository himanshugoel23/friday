"""The one interface the front door and the live call engine call to know the user's context.

    provider = LifeContextProvider(store, settings)
    summary = await provider.context_for(user_id, now)      # "now: in event (interview) until ..."
    status  = await provider.status_for(user_id, now)       # NowStatus

The summary holds only kinds, times and counts (no titles, notes, places or names), so it is safe
to put in a model prompt on any channel. ``register_context_provider`` is the registration point:
the front door asks ``get_context_provider()`` and injects the text if one is registered. Nothing
else about the front door changes.

During a protected event: a user who calls or writes is NEVER refused or delayed (they started it);
the summary only lets Friday answer in context ("aapka interview 2 se 3 hai"). Friday does not
start contact during it; that is the scheduler's job (followups.py).
"""

from __future__ import annotations

from datetime import datetime

from friday.core.config import Settings
from friday.lifestate.models import NowStatus, UserContext
from friday.lifestate.now import build_user_context, context_summary, now_status
from friday.lifestate.ports import BillsPort
from friday.lifestate.store import LifeStore


class LifeContextProvider:
    def __init__(
        self, store: LifeStore, settings: Settings | None = None, bills: BillsPort | None = None
    ) -> None:
        self.store, self.settings, self.bills = store, settings, bills

    async def context_for(self, user_id: str, at: datetime) -> str:
        return await context_summary(self.store, user_id, at, self.settings, self.bills)

    async def status_for(self, user_id: str, at: datetime) -> NowStatus:
        return await now_status(self.store, user_id, at, self.settings)

    async def snapshot_for(self, user_id: str, at: datetime) -> UserContext:
        return await build_user_context(self.store, user_id, at, self.settings, self.bills)


_provider: LifeContextProvider | None = None


def register_context_provider(provider: LifeContextProvider | None) -> None:
    """Called once at startup (container wiring). ``None`` unregisters."""
    global _provider
    _provider = provider


def get_context_provider() -> LifeContextProvider | None:
    return _provider
