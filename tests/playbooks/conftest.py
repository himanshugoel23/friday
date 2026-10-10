"""Playbook test helpers: a tiny driver that plays scripted salon replies straight into the
playbook policy (no telephony), exactly the way the call runner would."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from friday.core.models import (
    AudioClass,
    Budget,
    CallAction,
    CallActionType,
    CallBrief,
    ContactTarget,
    Delegation,
    NegotiationPolicy,
    Speaker,
    TargetKind,
    TaskType,
    Transcript,
)
from friday.playbooks.engine import CallState, PlaybookPolicy
from friday.playbooks.model import DATA_DIR, Playbook, get_playbook, validate_data

START = datetime(2026, 10, 7, 4, 30)  # 10:00 IST, a Wednesday


def _raw() -> dict[str, Any]:
    from friday.playbooks.model import _Loader

    return yaml.load((DATA_DIR / "salon_booking.yaml").read_text(encoding="utf-8"), Loader=_Loader)


@pytest.fixture
def salon() -> Playbook:
    return get_playbook("salon_booking")


@pytest.fixture
def raw() -> dict[str, Any]:
    return _raw()


def make_brief(pb: Playbook | None = None, **kw: Any) -> CallBrief:
    """A salon brief. ``book=True``: the owner delegated (up to Rs 800) and asked for a booking
    of one specific time ("aaj shaam 5 baje"); the default is a price check (no delegation)."""
    from friday.playbooks.engine import resolve_inputs

    pb = pb or get_playbook("salon_booking")
    book = kw.pop("book", False)
    inputs = {
        "user_first_name": "Rahul", "service": "haircut", "services": "haircut",
        "date_window": "aaj shaam 5 baje" if book else "kal shaam",
        **({"playbook_mode": "book"} if book else {}),
        **kw.pop("inputs", {}),
    }
    if kw.pop("budget_input", True) and "budget" not in inputs and kw.get("budget") is None:
        inputs["budget"] = "600"
    if book and "delegation" not in kw:
        from datetime import UTC

        from friday.playbooks import slots as sl
        from friday.playbooks.select import book_now_delegation

        if sl.requested_time(inputs.get("date_window")):  # exactly that time (+ the fallback)
            kw["delegation"], _fb = book_now_delegation(
                inputs["date_window"], inputs.get("fallback_when"), 800, START.replace(tzinfo=UTC)
            )
        else:
            kw["delegation"] = Delegation(granted=True, scope=["slot", "price"], max_price_inr=800)
    data: dict[str, Any] = dict(
        task_id="t-" + kw.pop("tid", "1"),
        requester_user_id="u1",
        task_type=TaskType.BOOKING,
        goal="Book a haircut kal shaam",
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks Salon", phone="+918040000001"),
        on_behalf_of="Rahul",
        playbook=pb.id,
        playbook_inputs=inputs,
        ai_disclosure=pb.ai_disclosure,
        max_duration_s=180,
        negotiation=NegotiationPolicy(enabled=kw.pop("negotiation", False)),
    )
    if inputs.get("budget"):
        data["budget"] = Budget(max_inr=int(inputs["budget"]))
    data.update(kw)
    probe = CallBrief(**data)
    resolved = resolve_inputs(pb, probe)

    def fill(t: str) -> str:
        return re.sub(r"\{([a-z_]+)\}", lambda m: resolved.get(m.group(1), ""), t)

    upd = {}
    if "disclosure_text" not in kw:
        upd["disclosure_text"] = fill(pb.text("disclosure"))
    if pb.reintro and "redisclosure_text" not in kw:
        upd["redisclosure_text"] = fill(pb.text(pb.reintro))
    return probe.model_copy(update=upd)


@dataclass
class Run:
    actions: list[CallAction] = field(default_factory=list)
    transcript: Transcript = field(default_factory=Transcript)
    state: CallState | None = None
    policy: PlaybookPolicy | None = None

    @property
    def final(self) -> CallAction:
        return self.actions[-1]

    @property
    def said(self) -> list[str]:
        return [a.text for a in self.actions if a.text]

    @property
    def outcome(self) -> str | None:
        if self.final.type != CallActionType.HANGUP:
            return None
        return self.final.collected.get("outcome")

    @property
    def keys(self) -> set[str]:
        return set(self.state.uses) if self.state else set()

    @property
    def path(self) -> list[str]:
        return list(self.state.path) if self.state else []

    def all_text(self) -> str:
        return " ".join(self.said)


async def drive(
    replies: list[str],
    *,
    brief: CallBrief | None = None,
    policy: PlaybookPolicy | None = None,
    pb: Playbook | None = None,
    greeting: str = "Hello, salon.",
    block_commit: bool = False,
    step_s: float = 6.0,
    max_actions: int = 40,
    ident: bool = True,
) -> Run:
    """Play ``replies`` (what the salon says, in order) into the policy.

    Special replies: "<silence>" (nothing heard), "<hangup>" (she put the phone down),
    "<music>" (hold music). A WAIT_ON_HOLD action consumes no reply: the next reply is the
    person coming back."""
    pb = pb or get_playbook("salon_booking")
    brief = brief or make_brief(pb)
    policy = policy or PlaybookPolicy(llm_mode="never")
    policy.keep_finished = True
    run = Run(policy=policy)
    tr = run.transcript
    clock = [START]

    def now() -> datetime:
        return clock[0]

    def add(speaker: Speaker, text: str, **kw: Any) -> None:
        tr.add(speaker, text, at=now(), **kw)

    # the disclosure ends in the identity question ("Kya meri baat X se ho rahi hai?"); unless a
    # test drives that step itself (ident=False), the salon first answers it with a plain yes
    queue = (["Haan ji"] if ident else []) + list(replies)
    add(Speaker.CALLEE, greeting, audio_class=AudioClass.HUMAN)
    add(Speaker.FRIDAY, brief.disclosure())
    for _ in range(max_actions):
        action = await policy.next_call_action(brief, tr, [])
        run.actions.append(action)
        run.state = policy.state_of(tr)
        clock[0] += timedelta(seconds=step_s)
        if action.type == CallActionType.HANGUP:
            if block_commit and action.commits_booking:
                add(Speaker.SYSTEM, "BLOCKED: commitment not allowed on this call (test)")
                block_commit = False
                continue  # the runner asks the policy again
            if action.text:
                add(Speaker.FRIDAY, action.text)
            break
        if action.type == CallActionType.SAY:
            add(Speaker.FRIDAY, action.text or "")
        elif action.type == CallActionType.WAIT_ON_HOLD:
            add(Speaker.SYSTEM, "ON HOLD (listening mode, no LLM)")
            add(Speaker.SYSTEM, "HUMAN AGENT JOINED AFTER 20s HOLD")
            clock[0] += timedelta(seconds=20)
        if not queue:
            break
        nxt = queue.pop(0)
        if nxt == "<silence>":
            add(Speaker.SYSTEM, "SILENCE")
        elif nxt == "<hangup>":
            add(Speaker.SYSTEM, "CALLEE HUNG UP")
        elif nxt == "<music>":
            add(Speaker.CALLEE, "", audio_class=AudioClass.HOLD_MUSIC)
        else:
            add(Speaker.CALLEE, nxt, audio_class=AudioClass.HUMAN)
    return run


def delegation(max_price: int | None = 800, **kw: Any) -> Delegation:
    return Delegation(granted=True, scope=["slot", "price"], max_price_inr=max_price, **kw)


__all__ = ["Run", "delegation", "drive", "make_brief", "validate_data", "Path"]
