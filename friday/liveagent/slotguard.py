# ruff: noqa: E501
"""Code that verifies everything Friday is about to say, whichever path produced it.

Reuses the existing guards (``friday.brain.guards.ungrounded_numbers`` for numbers and clock times
that appear nowhere in the brief or the conversation, ``friday.core.safety`` for OTP/PIN/card
wording and long unapproved numbers, ``looks_like_commitment`` for spoken promises) and adds the
consumer-call rules:

* every slot value comes from the brief (user name, goal, must_say, ask_list, shareable facts,
  allowed times) or from the callee's own words (or the user's mid-call answer);
* ``private_facts`` are never spoken (value, distinctive words, digits);
* ``must_not_say`` phrases never appear;
* a promise outside the brief limits becomes ``needs_user_approval`` (``judge_commitment``);
* the same line is never spoken twice in a row;
* Friday never claims to be the user and never denies being an AI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from friday.brain.guards import ungrounded_numbers
from friday.core.safety import check_speech, looks_like_commitment
from friday.liveagent.contracts import CallBrief, Limits
from friday.liveagent.understand_callee import Understanding

EMERGENCY_NUMBERS = ("112",)  # the only constant number a fixed line may speak (distress line)

_DEV = "ऀ-ॿ"


def norm(text: str | None) -> str:
    t = (text or "").lower().replace("’", "'")
    t = re.sub(rf"[^\w{_DEV}₹']+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ what is public


def public_text(brief: CallBrief) -> str:
    """Everything Friday MAY draw words and numbers from, out of the brief. Deliberately excludes
    private_facts and limits.max_amount_inr (the user's ceiling is never spoken)."""
    parts: list[str] = [
        brief.goal,
        brief.goal_spoken or "",
        brief.user_name,
        brief.callee_name or "",
    ]
    parts += brief.must_say + brief.ask_list
    for k, v in brief.shareable_facts.items():
        parts += [k, v]
    parts += brief.limits.allowed_times
    return " \n".join(p for p in parts if p)


def public_brief_view(brief: CallBrief) -> dict[str, Any]:
    """The brief as a model may see it: no private facts, no money ceiling."""
    return {
        "goal": brief.goal_spoken or brief.goal,
        "must_say": list(brief.must_say),
        "must_not_say": list(brief.must_not_say),
        "ask_list": list(brief.ask_list),
        "shareable_fact_keys": sorted(brief.shareable_facts),
        "relationship": brief.relationship.value,
        "tone": brief.tone,
        "language": brief.language.value,
    }


# ------------------------------------------------------------------ slot verification

_SLOT_NAMES = frozenset({"user", "callee", "purpose", "message", "question", "fact", "value"})


def _times_in(text: str) -> set[tuple[int, int]]:
    from friday.liveagent.understand_callee import dev_to_roman
    from friday.playbooks import slots as sl

    return {(p.hour24 % 12, p.minute) for p in sl.parse_times(dev_to_roman(text), limit=50)}


def _numbers_in(text: str) -> set[int]:
    from friday.playbooks import slots as sl

    return {v for v, _s, _e in sl.words_to_numbers(text)}


def value_grounded(value: str, allowed_text: str, heard_text: str) -> bool:
    """``value`` (a time, amount or short phrase) is the callee's own words, or in the brief."""
    v = norm(value)
    if not v:
        return False
    pool = norm(allowed_text) + " \n" + norm(heard_text)
    if v in pool:
        return True
    # normalised times/amounts ("kal shaam 5 baje" for "kal shaam paanch baje")
    vt, vn = _times_in(value), _numbers_in(value)
    if not vt and not vn:
        return False
    return vt <= _times_in(pool) and vn <= (_numbers_in(pool) | {0})


def verify_slots(
    slots: dict[str, str], brief: CallBrief, heard: str, extra_known: str = ""
) -> list[str]:
    """Problems with a decision's slots ([] = every slot is grounded)."""
    problems: list[str] = []
    for name, val in slots.items():
        if name not in _SLOT_NAMES:
            problems.append(f"unknown slot {name}")
            continue
        if name == "user":
            ok = val == brief.user_name
        elif name == "callee":
            ok = bool(val) and (val == brief.callee_name or norm(val) in norm(heard))
        elif name == "purpose":
            ok = val in (brief.goal_spoken, brief.goal)
        elif name == "message":
            ok = val in brief.must_say
        elif name == "question":
            ok = val in brief.ask_list
        elif name == "fact":
            ok = val in brief.shareable_facts.values()
        else:  # value
            ok = value_grounded(val, public_text(brief) + " " + extra_known, heard)
        if not ok:
            problems.append(f"slot {name}={val[:40]!r} is not from the brief or the callee's words")
    return problems


# ------------------------------------------------------------------ line checks


class Violation(SimpleNamespace):
    code: str
    detail: str


@dataclass
class GuardContext:
    brief: CallBrief
    heard_text: str = ""  # all the callee's words so far
    user_answers: list[str] = field(default_factory=list)  # the user's mid-call replies
    friday_lines: list[str] = field(default_factory=list)  # lines already spoken, oldest first
    callee_number: str = ""
    commit_authorized: bool = False  # the commitment guard allowed this line's agreement
    allow_repeat: bool = False  # the truthful AI answer may be repeated if asked again


@dataclass
class GuardResult:
    ok: bool
    violations: list[tuple[str, str]] = field(default_factory=list)

    def has(self, code: str) -> bool:
        return any(c == code for c, _d in self.violations)


def _shim_brief(brief: CallBrief, callee_number: str) -> Any:
    """The slice of the core CallBrief that ``check_speech`` reads."""
    ids = [
        SimpleNamespace(value=v)
        for v in brief.shareable_facts.values()
        if len(re.sub(r"\D", "", v)) >= 6 and not re.search(r"[a-z]{3,}", v.lower())
    ]
    return SimpleNamespace(
        approved_identifiers=ids, target=SimpleNamespace(phone=callee_number or ""), reference=None
    )


class _Known:
    """Duck-types the core brief for ``ungrounded_numbers`` (it only calls ``model_dump_json``)."""

    def __init__(self, text: str) -> None:
        self._t = text

    def model_dump_json(self) -> str:
        return self._t


def ungrounded(line: str, gctx: GuardContext) -> list[str]:
    known = _Known(public_text(gctx.brief) + " " + " ".join(gctx.user_answers))
    transcript = SimpleNamespace(turns=[SimpleNamespace(text=gctx.heard_text)])
    cleaned = line
    for n in EMERGENCY_NUMBERS:
        cleaned = re.sub(rf"(?<!\d){n}(?!\d)", " ", cleaned)
    return ungrounded_numbers(cleaned, known, transcript)  # type: ignore[arg-type]


_FIXED_VOCAB: set[str] | None = None


def _fixed_vocab() -> set[str]:
    global _FIXED_VOCAB
    if _FIXED_VOCAB is None:
        from friday.liveagent import lines as L

        _FIXED_VOCAB = {w for pl in L.all_lines() for w in norm(pl.text).split()}
    return _FIXED_VOCAB


def private_leaks(line: str, brief: CallBrief) -> list[str]:
    """Private fact values (or their distinctive words/digits) that the line would reveal."""
    ln = norm(line)
    words = set(ln.split())
    pub = norm(public_text(brief))
    pub_words = set(pub.split())
    pub_digits = set(re.findall(r"\d{3,}", re.sub(r"(?<=\d)[ ,.-](?=\d)", "", pub)))
    line_digits = set(re.findall(r"\d{3,}", re.sub(r"(?<=\d)[ ,.-](?=\d)", "", line)))
    shareable_vals = {norm(v) for v in brief.shareable_facts.values()}
    leaks: list[str] = []
    for key, val in brief.private_facts.items():
        v = norm(val)
        if not v:
            continue
        if len(v) >= 3 and v in ln and v not in shareable_vals:
            leaks.append(f"value of private fact '{key}'")
            continue
        for tok in set(re.findall(rf"[\w{_DEV}]{{5,}}", v)):
            if tok in words and tok not in pub_words and tok not in _fixed_vocab():
                leaks.append(f"word from private fact '{key}'")
                break
        else:
            for run in set(re.findall(r"\d{3,}", re.sub(r"(?<=\d)[ ,.-](?=\d)", "", val))):
                if run in line_digits and run not in pub_digits:
                    leaks.append(f"digits from private fact '{key}'")
                    break
    return leaks


def must_not_say_hits(line: str, brief: CallBrief) -> list[str]:
    ln = " " + norm(line) + " "
    return [p for p in brief.must_not_say if norm(p) and f" {norm(p)} " in ln]


def repeats(line: str, friday_lines: list[str], window: int = 2) -> bool:
    key = norm(line)
    return any(norm(prev) == key for prev in friday_lines[-window:])


def claims_to_be_user(line: str, brief: CallBrief) -> bool:
    u = re.escape(norm(brief.user_name))
    if not u or u == "user":
        u = r"\{user\}"
    pats = [
        rf"\b(main|mai|mein)\s+{u}\s+(bol|hoon|hu|hun|speaking)",
        rf"\b(this is|i am|i'm|it'?s)\s+{u}\b(?!'?s)(?!\s+(assistant|ki|ka))",
        rf"\b{u}\s+(bol raha|bol rahi|speaking here)",
    ]
    ln = norm(line)
    return any(re.search(p, ln) for p in pats)


_DENIES_AI = re.compile(
    r"(main|mai)\s+(robot|bot|machine|ai)\s+nahi|(main|mai)\s+(ek\s+)?(insaan|insan|human|real person)\s+(hoon|hu|hun)|"
    r"i\s*(am|'m)\s+not\s+(a\s+|an\s+)?(ai|bot|robot|machine|computer)|i\s*(am|'m)\s+(a\s+)?(human|real person)|"
    r"मैं\s+(रोबोट|बॉट|मशीन)\s+नहीं|मैं\s+(एक\s+)?इंसान\s+हूँ",
    re.I,
)


def denies_being_ai(line: str) -> bool:
    return bool(_DENIES_AI.search(norm(line)))


def check_line(line: str, gctx: GuardContext) -> GuardResult:
    """Every guard on one line. ``ok`` only when none fires."""
    v: list[tuple[str, str]] = []
    sc = check_speech(line, _shim_brief(gctx.brief, gctx.callee_number))  # type: ignore[arg-type]
    if not sc.allowed:
        v.append(("secret_or_number", "; ".join(sc.reasons)))
    bad = ungrounded(line, gctx)
    if bad:
        v.append(("ungrounded_number", ", ".join(bad)))
    for leak in private_leaks(line, gctx.brief):
        v.append(("private_leak", leak))
    for hit in must_not_say_hits(line, gctx.brief):
        v.append(("must_not_say", hit))
    if not gctx.allow_repeat and repeats(line, gctx.friday_lines):
        v.append(("repeat", line[:40]))
    if claims_to_be_user(line, gctx.brief):
        v.append(("claims_to_be_user", line[:40]))
    if denies_being_ai(line):
        v.append(("denies_ai", line[:40]))
    if not gctx.commit_authorized and looks_like_commitment(line):
        v.append(("commitment", line[:40]))
    return GuardResult(ok=not v, violations=v)


# ------------------------------------------------------------------ commitment guard


@dataclass
class CommitVerdict:
    allowed: bool
    kinds: list[str]
    reason: str
    text: str  # the callee's words that carry the commitment (times/amounts) for the record


def _amount_val(a: str) -> int:
    return int(re.sub(r"\D", "", a) or 0)


def judge_commitment(u: Understanding, limits: Limits) -> CommitVerdict:
    """May Friday say yes to what the callee just proposed? Only when EVERY part of it (time,
    visit, booking, amount) is inside the brief's limits. Friday never agrees to pay money."""
    ent = u.entities
    kinds: list[str] = []
    reasons: list[str] = []
    allowed_kinds = set(limits.allowed_commitments)
    if ent.times:
        kinds.append("time")
        ok_times = _times_in(" ".join(limits.allowed_times)) if limits.allowed_times else set()
        mine = _times_in(" ".join(ent.times))
        if (
            "time" not in allowed_kinds
            and "visit" not in allowed_kinds
            and "booking" not in allowed_kinds
        ):
            reasons.append("a time was proposed and the brief allows no time commitment")
        elif not mine <= ok_times:
            reasons.append("the proposed time is not one of the times the user allowed")
    if ent.visit:
        kinds.append("visit")
        if "visit" not in allowed_kinds:
            reasons.append("a visit is not allowed by the brief")
    if ent.booking:
        kinds.append("booking")
        if "booking" not in allowed_kinds:
            reasons.append("a booking is not allowed by the brief")
    if ent.amounts:
        kinds.append("amount")
        cap = limits.max_amount_inr
        if "booking" not in allowed_kinds or cap is None:
            reasons.append("agreeing to an amount is not allowed by the brief")
        elif any(_amount_val(a) > cap for a in ent.amounts):
            reasons.append("the amount is above the user's limit")
    if not kinds:
        kinds.append("other")
        reasons.append("an open-ended promise is not in the brief")
    text = ", ".join(ent.times + [f"{a} rupay" for a in ent.amounts]) or u.text[:60]
    return CommitVerdict(allowed=not reasons, kinds=kinds, reason="; ".join(reasons), text=text)
