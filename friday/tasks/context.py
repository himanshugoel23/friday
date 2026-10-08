"""Builds the ``ConversationContext`` snapshot the brain needs (brain does no I/O).
Shared by the task and proactive engines; every source is optional."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from friday.core.models import ConversationContext, MidCallQuestion, Profile, User
from friday.tasks.ports import call_opt, repo


async def build_context(
    repos: Any,
    user_id: str,
    now: datetime,
    *,
    pending_question: MidCallQuestion | None = None,
    with_messages: bool = True,
) -> ConversationContext:
    users = repo(repos, "users")
    user = await call_opt(users, "get", user_id) or User(id=user_id, phone="")
    profiles = repo(repos, "profiles")
    profile = await call_opt(profiles, "get", user_id) or Profile(user_id=user_id)
    businesses = repo(repos, "businesses")
    recent = []
    if with_messages:
        recent = await call_opt(repo(repos, "messages"), "recent_turns", user_id, default=[]) or []
    return ConversationContext(
        user=user,
        profile=profile,
        now=now,
        recent=recent,
        facts=await call_opt(repo(repos, "facts"), "list_for_user", user_id, default=[]) or [],
        open_tasks=await call_opt(
            repo(repos, "tasks"), "list_for_user", user_id, open_only=True, default=[]
        )
        or [],
        pending_question=pending_question,
        known_businesses=await call_opt(businesses, "known_for_user", user_id, default=[]) or [],
        vendor_history=await call_opt(businesses, "interactions", user_id, default=[]) or [],
        people=await call_opt(repo(repos, "people"), "list_for_owner", user_id, default=[]) or [],
        places=await call_opt(repo(repos, "places"), "list_for_owner", user_id, default=[]) or [],
        autonomy=await call_opt(repo(repos, "autonomy"), "list_for_user", user_id, default=[])
        or [],
        # QA BUG-10(a): saved identifiers never reached build_call_brief, so a care call
        # could not share an approved account number at the IVR.
        identifiers=await call_opt(
            repo(repos, "identifiers"), "list_for_user", user_id, default=[]
        )
        or [],
    )
