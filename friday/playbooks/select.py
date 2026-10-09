"""Which tasks use a playbook, and the values their fixed lines are filled with.

``playbook_fields`` is called when a call brief is built. It returns ``{}`` (use the normal
LLM-driven policy) unless the task clearly matches a playbook AND every required input is
known, so a playbook never starts a call it cannot finish.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from friday.core.clock import to_ist
from friday.playbooks import slots as sl
from friday.playbooks.engine import clean_input, first_name
from friday.playbooks.model import Playbook, PlaybookError, get_playbook, playbook_files

_SERVICE_WORDS = re.compile(
    r"(hair\s*cut|haircut|hair\s*spa|hair\s*colou?r|facial|beard(\s*trim)?|shave|trim|manicure|"
    r"pedicure|waxing|threading|keratin|massage|head\s*massage|spa)",
    re.I,
)


def matching_playbook(
    task_type: str, category: str | None, goal: str | None, directory: Any = None
) -> Playbook | None:
    text = f"{category or ''} {goal or ''}".lower()
    for name in playbook_files(directory):
        try:
            pb = get_playbook(name, directory)
        except PlaybookError:
            continue  # an invalid file never gets a call
        sel = pb.select
        if sel.task_types and str(getattr(task_type, "value", task_type)) not in sel.task_types:
            continue
        cat = (category or "").lower()
        if any(c in cat for c in sel.categories if c) or any(
            k in text for k in sel.keywords if k
        ):
            return pb
    return None


_EN_TO_HINGLISH = {
    "tomorrow": "kal", "today": "aaj", "tonight": "aaj raat", "evening": "shaam",
    "morning": "subah", "afternoon": "dopahar", "night": "raat", "the": "", "in": "", "at": "",
    "after": "", "day": "", "sham": "shaam",
}
_WHEN_OK = {"aaj", "kal", "parso", "subah", "dopahar", "shaam", "raat", "baje", "se", "ke", "beech",
            "tak", "ko", "aur", "ya"}
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def when_phrase(
    when_text: str | None,
    preferred_times: list[str],
    window_start: datetime | None,
    window_end: datetime | None,
    now: datetime | None,
) -> str:
    """How Friday says "when" ("kal shaam", "kal shaam 5 se 8 baje ke beech"): the user's own
    words when they are simple, else built from the resolved window. "" if neither works."""
    for raw in [when_text or "", *preferred_times[:1]]:
        t = sl.normalise(raw)
        words = [_EN_TO_HINGLISH.get(w, w) for w in re.findall(r"[a-z0-9']+", t)]
        words = [w for w in " ".join(words).split() if w]
        has_day = any(w in ("aaj", "kal", "parso") for w in words)
        has_period = any(w in ("subah", "dopahar", "shaam", "raat") for w in words)
        if words and (has_day or has_period) and all(
            w in _WHEN_OK or w.isdigit() for w in words
        ) and len(words) <= 8:
            return " ".join(words)
    if window_start is None:
        return ""
    ref = to_ist(now or datetime.now(UTC))
    start = to_ist(window_start)
    days = (start.date() - ref.date()).days
    if days < 0:
        return ""
    day = {0: "aaj", 1: "kal", 2: "parso"}.get(days, _WEEKDAYS[start.weekday()])
    period = "subah" if start.hour < 12 else "dopahar" if start.hour < 16 else (
        "shaam" if start.hour < 20 else "raat"
    )
    out = f"{day} {period}"
    if window_end is not None:
        end = to_ist(window_end)
        if end > start and (end - start).total_seconds() <= 4 * 3600:
            h1, h2 = start.hour % 12 or 12, end.hour % 12 or 12
            if start.minute == 0 and end.minute == 0:
                out += f" {h1} se {h2} baje ke beech"
    return out


def _service(item: str | None, goal: str | None, default: str | None) -> str:
    for text in (item, goal):
        m = _SERVICE_WORDS.search(text or "")
        if m:
            w = re.sub(r"\s+", " ", m.group(1).lower())
            return {"hair cut": "haircut"}.get(w, w)
    return default or ""


def playbook_fields(
    *,
    task_type: Any,
    category: str | None,
    goal: str | None,
    item: str | None,
    when_text: str | None,
    preferred_times: list[str],
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    now: datetime | None = None,
    requester_name: str | None = None,
    beneficiary_name: str | None,
    constraints: list[str],
    budget_max_inr: int | None,
    enabled: bool = True,
    directory: Any = None,
) -> dict[str, Any]:
    """CallBrief fields for a scripted call, or ``{}``."""
    if not enabled:
        return {}
    pb = matching_playbook(task_type, category, goal, directory)
    if pb is None:
        return {}
    inputs: dict[str, str] = {
        "user_first_name": first_name(requester_name),
        "service": _service(
            item, goal, pb.inputs["service"].default if "service" in pb.inputs else None
        ),
        "date_window": clean_input(
            when_phrase(when_text, preferred_times, window_start, window_end, now)
        ),
    }
    if beneficiary_name:
        inputs["for_whom"] = first_name(beneficiary_name)
    if budget_max_inr:
        inputs["budget"] = str(int(budget_max_inr))
    for cons in constraints:
        m = re.match(r"\s*stylist\s*[:=]?\s*([A-Za-z]{3,15})\s*$", cons, re.I)
        if m:
            inputs["stylist_pref"] = m.group(1).title()
    if any(spec.required and not inputs.get(n) for n, spec in pb.inputs.items()):
        return {}  # a required input is unknown: the normal policy handles this call

    shown = {n: spec.default for n, spec in pb.inputs.items() if spec.default} | {
        k: v for k, v in inputs.items() if v
    }
    disclosure = re.sub(
        r"\{([a-z_]+)\}", lambda m: shown.get(m.group(1), ""), pb.text(pb.disclosure)
    )
    return {"playbook": pb.id, "playbook_inputs": inputs, "disclosure_text": disclosure}


def playbook_test_brief(
    name: str,
    *,
    to: str,
    user_first_name: str,
    max_seconds: int,
    from_number: str | None,
    service: str | None = None,
    date_window: str | None = None,
    budget_inr: int | None = None,
    stylist_pref: str | None = None,
    target_name: str = "Test business (the founder)",
    salon_name: str | None = None,
    honorific: str | None = None,
) -> Any:
    """A CallBrief for ``friday livecall --playbook``: a normal outbound BOOKING brief with NO
    delegation and no approval, so the call can only end with "I will call back after approval"."""
    import secrets

    from friday.core.models import (
        Budget,
        CallBrief,
        ContactTarget,
        TargetKind,
        TaskType,
    )

    pb = get_playbook(name)
    inputs = {
        "user_first_name": first_name(user_first_name),
        "service": clean_input(service or "") or (
            pb.inputs["service"].default if "service" in pb.inputs else ""
        ) or "",
        "date_window": clean_input(date_window or ""),
    }
    if budget_inr:
        inputs["budget"] = str(int(budget_inr))
    if stylist_pref:
        inputs["stylist_pref"] = clean_input(stylist_pref, 20)
    if salon_name:
        inputs["business_name"] = clean_input(salon_name, 40)
    if honorific:
        inputs["honorific"] = clean_input(honorific, 10)
    missing = [n for n, spec in pb.inputs.items() if spec.required and not inputs.get(n)]
    if missing:
        raise PlaybookError([f"missing required input(s): {', '.join(missing)}"], name)
    shown = {n: spec.default for n, spec in pb.inputs.items() if spec.default} | {
        k: v for k, v in inputs.items() if v
    }
    disclosure = re.sub(
        r"\{([a-z_]+)\}", lambda m: shown.get(m.group(1), ""), pb.text(pb.disclosure)
    )
    return CallBrief(
        task_id=f"livecall-{secrets.token_hex(4)}",
        requester_user_id="pilot",
        task_type=TaskType.BOOKING,
        goal=f"Ask a salon about {inputs['service']} {inputs['date_window']} (scripted test call)",
        target=ContactTarget(kind=TargetKind.BUSINESS, name=target_name, phone=to),
        on_behalf_of=inputs["user_first_name"],
        budget=Budget(max_inr=int(budget_inr)) if budget_inr else None,
        constraints=[f"Test call: wrap up politely within {max_seconds} seconds."],
        from_number=from_number,
        max_duration_s=max_seconds,
        max_hold_s=min(60, max_seconds),
        playbook=pb.id,
        playbook_inputs=inputs,
        disclosure_text=disclosure,
    )


__all__ = ["matching_playbook", "playbook_fields", "playbook_test_brief"]
