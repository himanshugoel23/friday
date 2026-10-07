"""ConversationContext builder - the snapshot the brain sees (brain does no DB I/O).

Minimum data: only the requesting user's own records. ``Person.notes`` are
included because the brain needs them for the owner's own conversation; the
brain's brief builder is responsible for never forwarding them.
"""

from __future__ import annotations

from friday.core.clock import Clock
from friday.core.models import ConversationContext, MidCallQuestion, User
from friday.db.repositories import Repositories

RECENT_TURNS = 20


async def build_context(
    repos: Repositories,
    clock: Clock,
    user: User,
    *,
    pending_question: MidCallQuestion | None = None,
    recent_limit: int = RECENT_TURNS,
) -> ConversationContext:
    profile = await repos.profiles.get_or_default(user.id)
    if pending_question is None:
        pending_question = await repos.tasks.open_question_for_user(user.id)
    return ConversationContext(
        user=user,
        profile=profile,
        now=clock.now(),
        recent=await repos.messages.recent_turns(user.id, limit=recent_limit),
        facts=await repos.facts.list_for_user(user.id),
        open_tasks=await repos.tasks.list_for_user(user.id, open_only=True),
        pending_question=pending_question,
        known_businesses=await repos.businesses.known_for_user(user.id),
        vendor_history=await repos.businesses.interactions(user.id, limit=30),
        people=await repos.people.list_for_owner(user.id),
        places=await repos.places.list_for_owner(user.id),
        autonomy=await repos.autonomy.list_for_user(user.id),
    )
