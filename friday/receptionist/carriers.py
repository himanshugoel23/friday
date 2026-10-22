"""Conditional call-forwarding codes for the four big Indian carriers.

EVERYTHING HERE IS GENERAL KNOWLEDGE ABOUT THE GSM STANDARD (3GPP TS 22.030 supplementary-service
codes), NOT VERIFIED ON A REAL SIM. The probe in ``probe.py`` and the steps in docs/RECEPTIONIST.md
exist to verify each carrier before any user is told to rely on it. ``UNVERIFIED`` lists what must
be checked.

Codes (standard GSM, ``<n>`` = the forwarding target, ``<s>`` = seconds):

    no answer      register+activate  **61*<n>**<s>#      cancel ##61#     status *#61#
    busy           register+activate  **67*<n>#           cancel ##67#     status *#67#
    unreachable    register+activate  **62*<n>#           cancel ##62#     status *#62#
    cancel ALL forwarding (all conditions) ##002#

``<s>`` is the no-reply timer: 5 to 30 seconds in steps of 5 (about 5 seconds per ring).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

from friday.receptionist.models import MAX_RINGS, MIN_RINGS, ReceptionistConfig

SECONDS_PER_RING = 5
STEP_SECONDS = 5
DEFAULT_MAX_NO_REPLY_S = 30  # the GSM maximum; a carrier may allow less (verify)

CANCEL_ALL = "##002#"
STATUS_NO_ANSWER = "*#61#"
STATUS_BUSY = "*#67#"
STATUS_UNREACHABLE = "*#62#"

GENERAL_KNOWLEDGE_NOTICE = (
    "These codes are the standard GSM forwarding codes and are general knowledge. They have NOT "
    "been verified on a real Jio, Airtel, Vi or BSNL SIM. Check the result with the status code "
    "(*#61# etc.) and a test call before relying on it."
)

UNVERIFIED = (
    "Each code works on each carrier (Jio, Airtel, Vi, BSNL) and on prepaid AND postpaid plans.",
    "The **seconds** value is honoured; some carriers ignore it and use their own timer (often "
    "20-30 s) or cap it below 30.",
    "A declined call (iPhone Decline, Android reject) is treated as BUSY and therefore forwarded.",
    "Whether silenced unknown callers (iPhone Silence Unknown Callers, Android spam filters) take "
    "the forwarding path.",
    "That the carrier's own voicemail does not win (it may sit on one of the three conditions).",
    "That the number is accepted with +91 (otherwise try the 10-digit form).",
    "Whether the network passes the redirecting number to Vobiz, and in which webhook field.",
    "Forwarded-call charges to the user (differs by plan) and dual-SIM / eSIM behaviour.",
    "That the phone's own dialler accepts these codes (iPhone may refuse some tel: links).",
)


@dataclass(frozen=True)
class Carrier:
    key: str
    name: str
    max_no_reply_s: int = DEFAULT_MAX_NO_REPLY_S
    notes: tuple[str, ...] = ()
    verified: bool = False  # always False until a probe on a real SIM says otherwise


CARRIERS: dict[str, Carrier] = {
    "jio": Carrier(
        "jio",
        "Jio",
        notes=(
            "Jio is 4G/5G (VoLTE) only. The standard codes are believed to work; if the dialler "
            "rejects them, use the phone's own Call Forwarding setting (Android: Phone app > "
            "Settings > Calling accounts > Call forwarding).",
            "Jio may use a fixed no-reply timer.",
        ),
    ),
    "airtel": Carrier(
        "airtel",
        "Airtel",
        notes=(
            "Standard codes believed to work. Airtel offers its own voicemail on some plans: "
            "switch it off or it may answer before Friday.",
        ),
    ),
    "vi": Carrier(
        "vi",
        "Vi (Vodafone Idea)",
        notes=(
            "Standard codes believed to work. Vi may have a voicemail service active by default: "
            "switch it off or it may answer before Friday.",
        ),
    ),
    "bsnl": Carrier(
        "bsnl",
        "BSNL",
        notes=(
            "Standard codes believed to work, but some BSNL plans may need forwarding enabled by "
            "customer care first.",
        ),
    ),
}

CARRIER_ALIASES = {
    "reliance jio": "jio",
    "jio": "jio",
    "airtel": "airtel",
    "bharti airtel": "airtel",
    "vi": "vi",
    "vodafone": "vi",
    "idea": "vi",
    "vodafone idea": "vi",
    "bsnl": "bsnl",
}


def find_carrier(name: str) -> Carrier | None:
    key = CARRIER_ALIASES.get((name or "").strip().lower())
    return CARRIERS.get(key) if key else None


def no_reply_seconds(rings: int, *, max_seconds: int = DEFAULT_MAX_NO_REPLY_S) -> int:
    """5 seconds per ring, rounded to a multiple of 5, never above the carrier's maximum."""
    rings = max(MIN_RINGS, min(MAX_RINGS, int(rings)))
    secs = rings * SECONDS_PER_RING
    secs = int(round(secs / STEP_SECONDS)) * STEP_SECONDS
    cap = (max_seconds // STEP_SECONDS) * STEP_SECONDS
    return max(STEP_SECONDS, min(secs, cap))


def dial_number(number: str, *, style: str = "e164") -> str:
    """The forwarding target as typed in the code. ``e164``: +91XXXXXXXXXX. ``national``: the
    10-digit form, the fallback if a carrier rejects the plus sign."""
    digits = "".join(ch for ch in number if ch.isdigit())
    if not digits:
        raise ValueError("empty forwarding number")
    if style == "national":
        return digits[-10:]
    if number.strip().startswith("+"):
        return "+" + digits
    return "+91" + digits[-10:] if len(digits) >= 10 else "+" + digits


@dataclass(frozen=True)
class CodeLine:
    label: str  # "no_answer" | "busy" | "unreachable"
    code: str
    tel_link: str
    condition_text: str


@dataclass
class CodeSet:
    carrier: Carrier
    number: str
    seconds: int
    rings: int
    activate: list[CodeLine] = field(default_factory=list)
    cancel: list[tuple[str, str]] = field(default_factory=list)  # (label, code)
    status: list[tuple[str, str]] = field(default_factory=list)
    cancel_all: str = CANCEL_ALL
    notices: list[str] = field(default_factory=list)


def tel_link(code: str) -> str:
    """``tel:`` URI for a USSD-style code: ``#`` MUST be percent-encoded (%23), ``*`` kept."""
    return "tel:" + quote(code, safe="*+")


def codes_for(
    carrier: Carrier | str,
    config: ReceptionistConfig,
    friday_number: str,
    *,
    number_style: str = "e164",
) -> CodeSet:
    c = find_carrier(carrier) if isinstance(carrier, str) else carrier
    if c is None:
        raise ValueError(f"unknown carrier {carrier!r}; known: {', '.join(CARRIERS)}")
    n = dial_number(friday_number, style=number_style)
    secs = no_reply_seconds(config.rings, max_seconds=c.max_no_reply_s)
    cs = CodeSet(carrier=c, number=n, seconds=secs, rings=config.rings)
    if config.forward_no_answer:
        code = f"**61*{n}**{secs}#"
        cs.activate.append(
            CodeLine("no_answer", code, tel_link(code), f"you do not answer for ~{config.rings} rings")
        )
        cs.cancel.append(("no_answer", "##61#"))
        cs.status.append(("no_answer", STATUS_NO_ANSWER))
    if config.forward_busy:
        code = f"**67*{n}#"
        cs.activate.append(
            CodeLine("busy", code, tel_link(code), "you are busy or you decline the call")
        )
        cs.cancel.append(("busy", "##67#"))
        cs.status.append(("busy", STATUS_BUSY))
    if config.forward_unreachable:
        code = f"**62*{n}#"
        cs.activate.append(
            CodeLine("unreachable", code, tel_link(code), "your phone is off or has no network")
        )
        cs.cancel.append(("unreachable", "##62#"))
        cs.status.append(("unreachable", STATUS_UNREACHABLE))
    cs.notices.append(GENERAL_KNOWLEDGE_NOTICE)
    cs.notices.extend(c.notes)
    if secs < config.rings * SECONDS_PER_RING:
        cs.notices.append(
            f"{c.name} allows at most {secs} seconds here, so Friday answers after about "
            f"{secs // SECONDS_PER_RING} rings, not {config.rings}."
        )
    return cs
