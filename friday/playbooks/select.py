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


def _services(item: str | None, goal: str | None, default: str | None) -> list[str]:
    """Every known service word in the owner's text, in order ("haircut and beard trim")."""
    found: list[str] = []
    for text in (item, goal):
        for m in _SERVICE_WORDS.finditer(text or ""):
            w = re.sub(r"\s+", " ", m.group(1).lower())
            w = {"hair cut": "haircut"}.get(w, w)
            if w not in found and not (w == "trim" and any("trim" in f for f in found)):
                found.append(w)
        if found:
            break
    return found or ([default] if default else [])


def _service(item: str | None, goal: str | None, default: str | None) -> str:
    for text in (item, goal):
        m = _SERVICE_WORDS.search(text or "")
        if m:
            w = re.sub(r"\s+", " ", m.group(1).lower())
            return {"hair cut": "haircut"}.get(w, w)
    return default or ""


def book_now_delegation(
    date_window: str,
    fallback_when: str | None,
    max_price_inr: int,
    now: datetime,
    *,
    name: str = "salon_booking",
    label: str = "delegation",
) -> tuple[Any, str]:
    """A delegation for EXACTLY the requested time (and, if given, ONE fallback time, same price
    ceiling): each time gets a +-5 minute window, and ``slot_windows`` keeps every time in between
    out. Returns (Delegation, cleaned fallback text). Raises PlaybookError without a specific time."""  # noqa: E501
    from datetime import timedelta

    from friday.core.models import Delegation

    asked = sl.requested_time(date_window)
    if not asked:
        raise PlaybookError(
            ["--book-now needs --when with ONE specific time, e.g. 'aaj shaam 5 baje' "
             f"(got '{date_window}')"], name)
    phrase = sl.with_day(asked, sl.find_day(date_window))
    slot_at = sl.resolve_slot_at(phrase, now=now)
    if slot_at is None:
        raise PlaybookError([f"cannot work out the time '{phrase}'"], name)
    windows = [(slot_at - timedelta(minutes=5), slot_at + timedelta(minutes=5))]
    said = f"book {phrase} if free"
    fb = ""
    if fallback_when:
        fb = clean_input(fallback_when)
        fb_t = sl.requested_time(fb)
        if not fb_t:
            raise PlaybookError(
                ["--fallback-when needs ONE specific time with a day, e.g. 'kal shaam 5 baje' "
                 f"(got '{fb}')"], name)
        fb_phrase = sl.with_day(fb_t, sl.find_day(fb) or "kal")
        fb_at = sl.resolve_slot_at(fb_phrase, now=now)
        if fb_at is None:
            raise PlaybookError([f"cannot work out the time '{fb_phrase}'"], name)
        windows.append((fb_at - timedelta(minutes=5), fb_at + timedelta(minutes=5)))
        said += f", or {fb_phrase}"
    return Delegation(
        granted=True,
        scope=["slot", "price"],
        window_start=min(w[0] for w in windows),
        window_end=max(w[1] for w in windows),
        slot_windows=windows if len(windows) > 1 else [],
        max_price_inr=int(max_price_inr),
        user_words=f"{said}, up to Rs {int(max_price_inr)} ({label})",
    ), fb


def _name_inputs(inputs: dict[str, str], speller: Any) -> None:
    """Worked out ONCE, when the task/call is set up: how the voice reads the names."""
    from friday.voice.names import default_speller

    sp = speller or default_speller()
    if inputs.get("user_first_name"):
        inputs["user_spoken"] = sp.spoken(inputs["user_first_name"])
    if inputs.get("business_name"):
        inputs["business_name_spoken"] = sp.spoken(inputs["business_name"])


def _opening_texts(pb: Playbook, inputs: dict[str, str]) -> dict[str, Any]:
    """The runner's opening and (on_request) the short re-intro after a hold, names filled in."""
    shown = {n: spec.default for n, spec in pb.inputs.items() if spec.default} | {
        k: v for k, v in inputs.items() if v
    }
    from friday.voice.names import default_speller

    for src, dst in (("business_name", "business_name_spoken"), ("user_first_name", "user_spoken")):
        if not shown.get(dst):
            shown[dst] = default_speller().spoken(shown.get(src, "")) or shown.get(src, "")

    def fill_(text: str) -> str:
        return re.sub(r"\{([a-z_]+)\}", lambda m: shown.get(m.group(1), ""), text)

    out: dict[str, Any] = {"disclosure_text": fill_(pb.text(pb.disclosure))}
    if pb.ai_disclosure == "on_request" and pb.reintro:
        out["redisclosure_text"] = fill_(pb.text(pb.reintro))
    return out


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
    business_name: str | None = None,
    delegation_granted: bool = False,
    name_speller: Any = None,
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
        "services": ", ".join(
            _services(item, goal, pb.inputs["service"].default if "service" in pb.inputs else None)
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
        # both are OFF unless the owner's instruction says so in so many words
        if re.match(r"\s*(negotiate|bargain)\b", cons, re.I):
            inputs["negotiate"] = "yes"
        if re.match(r"\s*(explore|compare)[ _-]*(multiple[ _-]*)?options\b", cons, re.I):
            inputs["explore_options"] = "yes"
        m = re.match(r"\s*(?:fallback|fallback[ _-]*when)\s*[:=]\s*(.+)$", cons, re.I)
        if m:
            inputs["fallback_when"] = clean_input(m.group(1))
        m = re.match(r"\s*(?:mode|playbook[ _-]*mode)\s*[:=]\s*(book|quote[ _-]*only)\s*$", cons, re.I)  # noqa: E501
        if m:
            inputs["playbook_mode"] = m.group(1).lower().replace("-", "_").replace(" ", "_")
        if re.match(r"\s*(price|quote)[ _-]*(check|only)\b", cons, re.I):
            inputs["playbook_mode"] = "quote_only"
    # the mode comes from the owner's instruction; "book" exists only with a delegation
    if inputs.get("playbook_mode") != "quote_only":
        inputs["playbook_mode"] = "book" if (delegation_granted and inputs["date_window"]) else (
            "quote_only"
        )
    if business_name and "test business" not in business_name.lower():
        inputs["business_name"] = clean_input(business_name, 40)
    _name_inputs(inputs, name_speller)
    if any(spec.required and not inputs.get(n) for n, spec in pb.inputs.items()):
        return {}  # a required input is unknown: the normal policy handles this call
    if inputs["playbook_mode"] == "book" and not inputs["date_window"]:
        inputs["playbook_mode"] = "quote_only"
    return {
        "playbook": pb.id,
        "playbook_inputs": inputs,
        "ai_disclosure": pb.ai_disclosure,
        **_opening_texts(pb, inputs),
    }


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
    book_now: bool = False,
    explore_options: bool = False,
    negotiate: bool = False,
    services: str | None = None,
    fallback_when: str | None = None,
    mode: str | None = None,
    name_speller: Any = None,
    now: datetime | None = None,
) -> Any:
    """A CallBrief for ``friday livecall --playbook``: a normal outbound BOOKING brief with NO
    delegation and no approval, so the call can only end with "I will call back after approval".

    ``book_now`` is the one exception, and an explicit one: it gives the brief a delegation for
    exactly the requested time (needs a specific time in ``date_window``) and the ``budget_inr``
    ceiling (required), so Friday may say the single booking line if, and only if, the salon
    confirms THAT time at a price within the ceiling. The code-level commit check still decides."""
    import secrets
    from datetime import UTC, datetime

    from friday.core.models import (
        Budget,
        CallBrief,
        ContactTarget,
        Delegation,
        TargetKind,
        TaskType,
    )

    pb = get_playbook(name)
    from friday.voice.names import parse_services

    inputs = {
        "user_first_name": first_name(user_first_name),
        "service": clean_input(service or "") or (
            pb.inputs["service"].default if "service" in pb.inputs else ""
        ) or "",
        "services": ", ".join(parse_services(services or service)),
        "date_window": clean_input(date_window or ""),
    }
    if services and not service:
        inputs["service"] = inputs["services"].split(", ")[0] or inputs["service"]
    if not inputs["services"]:
        inputs["services"] = inputs["service"]
    if budget_inr:
        inputs["budget"] = str(int(budget_inr))
    if stylist_pref:
        inputs["stylist_pref"] = clean_input(stylist_pref, 20)
    if salon_name:
        inputs["business_name"] = clean_input(salon_name, 40)
    if honorific:
        inputs["honorific"] = clean_input(honorific, 10)
    if explore_options:
        inputs["explore_options"] = "yes"
    if negotiate:
        inputs["negotiate"] = "yes"
    if mode not in (None, "book", "quote_only"):
        raise PlaybookError([f"mode must be book or quote_only (got '{mode}')"], name)
    if mode == "book" and not book_now:
        raise PlaybookError(
            ["--mode book needs --book-now (a delegation: one specific --when time and --budget)"],
            name)
    inputs["playbook_mode"] = "book" if book_now else "quote_only"
    if mode == "quote_only" and book_now:
        raise PlaybookError(["--mode quote-only cannot be combined with --book-now"], name)
    missing = [n for n, spec in pb.inputs.items() if spec.required and not inputs.get(n)]
    if missing:
        raise PlaybookError([f"missing required input(s): {', '.join(missing)}"], name)
    delegation = Delegation()
    if book_now:
        if not budget_inr:
            raise PlaybookError(
                ["--book-now needs --budget (the most Friday may agree to, in rupees)"], name)
        delegation, fb_clean = book_now_delegation(
            inputs["date_window"], fallback_when, int(budget_inr), now or datetime.now(UTC),
            name=name, label="book-now test call, --book-now",
        )
        if fb_clean:
            inputs["fallback_when"] = fb_clean
    elif fallback_when:
        raise PlaybookError(["--fallback-when only makes sense with --book-now"], name)
    _name_inputs(inputs, name_speller)
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
        ai_disclosure=pb.ai_disclosure,
        delegation=delegation,
        **_opening_texts(pb, inputs),
    )


__all__ = ["matching_playbook", "playbook_fields", "playbook_test_brief"]
