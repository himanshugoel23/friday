"""Accuracy of the existing rule banks on Devanagari and mixed-script messages.

``friday chatbot devanagari-eval`` runs every labelled message through the SAME parsers the router
uses (never a copy of their logic), once with the normaliser in front and, with ``--baseline``,
once without it, and prints accuracy per intent and the failures.

Intents (the first that matches wins, in the router's own order):

    call          "mummy ko phone karke ..."             calls/understand.py (+ router verb regex)
    stop_delete   "sab delete karo", "mat poocho", "SBI card hata do"   memory + mute + wallet
    memory        "tumhe kya yaad hai", "mera data export karo"          lifestate/memory.py
    bill          a forwarded bill / statement           savings/bills.py
    add_card      "mere paas HDFC Regalia hai"           savings/wallet.py
    card_question "kaun sa card Zomato pe 640"           savings/categories.py + commands
    event         "kal 2 baje interview hai"             lifestate/capture.py
    menu          "help", "menu"                         brain/heuristics/interpret.py
    none          chit-chat the rules must NOT take

A case is right on ``intent`` when the predicted intent matches, and ``strict`` when its labelled
slots (hour, day, amount, bank ...) match too. Data: ``data/dev.tsv`` (used while building the
normaliser) and ``data/heldout.tsv`` (written after the lexicon was frozen and never tuned on).
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from friday.core.clock import to_ist
from friday.lang_dev.normalise import normalise_text

DATA_DIR = Path(__file__).parent / "data"
# 22 Oct 2026, 10:00 IST (a Thursday): every relative date in the labels is against this instant
NOW = datetime(2026, 10, 22, 4, 30, tzinfo=UTC)
INTENTS = (
    "call", "stop_delete", "memory", "bill", "add_card", "card_question", "event", "menu", "none",
)  # fmt: skip


@dataclass
class Case:
    id: str
    split: str
    intent: str
    slots: dict[str, str]
    text: str


@dataclass
class Outcome:
    case: Case
    predicted: str
    got: dict[str, str]
    intent_ok: bool
    slots_ok: bool
    normalised: str


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)

    def per_intent(self) -> dict[str, dict[str, float]]:
        agg: dict[str, list[Outcome]] = defaultdict(list)
        for o in self.outcomes:
            agg[o.case.intent].append(o)
        out: dict[str, dict[str, float]] = {}
        for intent in INTENTS:
            rows = agg.get(intent)
            if not rows:
                continue
            out[intent] = {
                "n": len(rows),
                "intent_acc": sum(r.intent_ok for r in rows) / len(rows),
                "strict_acc": sum(r.intent_ok and r.slots_ok for r in rows) / len(rows),
            }
        return out

    @property
    def intent_acc(self) -> float:
        return sum(o.intent_ok for o in self.outcomes) / max(1, len(self.outcomes))

    @property
    def strict_acc(self) -> float:
        return sum(o.intent_ok and o.slots_ok for o in self.outcomes) / max(1, len(self.outcomes))

    def failures(self) -> list[Outcome]:
        return [o for o in self.outcomes if not (o.intent_ok and o.slots_ok)]


# ------------------------------------------------------------------ data


def _slots(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in filter(None, (p.strip() for p in raw.split(";"))):
        k, _, v = part.partition("=")
        out[k.strip()] = v.strip()
    return out


def load_cases(split: str = "all") -> list[Case]:
    """Rows are ``intent<TAB>slots<TAB>text``; ``#`` starts a comment."""
    cases: list[Case] = []
    for name in ("dev", "heldout"):
        if split not in ("all", name):
            continue
        path = DATA_DIR / f"{name}.tsv"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip() or line.startswith("#"):
                continue
            intent, slots, text = line.split("\t", 2)
            cases.append(Case(f"{name}-{n}", name, intent.strip(), _slots(slots), text.strip()))
    return cases


# ------------------------------------------------------------------ the real parsers


def _help_ctx() -> Any:
    from friday.core.models import (
        ConversationContext,
        Language,
        OnboardingStep,
        Profile,
        User,
        UserStatus,
    )

    user = User(
        id="eval", phone="+919800000001", status=UserStatus.ACTIVE,
        onboarding_step=OnboardingStep.DONE,
    )  # fmt: skip
    profile = Profile(user_id="eval", name="Eval", language=Language.HINGLISH)
    return ConversationContext(user=user, profile=profile, now=NOW)


def _is_menu(text: str) -> bool:
    from friday.brain.heuristics.interpret import interpret
    from friday.core.models import InboundMessage, Intent

    msg = InboundMessage(channel="whatsapp", from_phone="+919800000001", text=text)  # type: ignore[arg-type]
    try:
        return interpret(_help_ctx(), msg).intent == Intent.HELP
    except Exception:  # noqa: BLE001 - an eval row must never stop the run
        return False


def _day_offset(dt: datetime) -> int:
    return (to_ist(dt).date() - to_ist(NOW).date()).days


def classify(text: str) -> tuple[str, dict[str, str]]:
    """Intent + slots the router's parsers find in ``text`` (already normalised or not)."""
    from friday.calls.understand import RequestUnderstander
    from friday.integration.router import _CALL_VERB
    from friday.lifestate import memory as mem
    from friday.lifestate.capture import parse_message
    from friday.lifestate.followups import parse_mute_command
    from friday.savings import commands as sc
    from friday.savings.bills import parse_bill_text
    from friday.savings.categories import parse_purchase
    from friday.savings.wallet import parse_wallet_message

    t = text.strip()
    today = to_ist(NOW).date()
    if _CALL_VERB.search(t):
        und = asyncio.run(RequestUnderstander().understand(t, now=NOW))
        return "call", {"callee": (und.draft.callee_ref or "").lower()}
    if mem._CONFIRM_DELETE.match(t) or mem._DELETE_ALL.search(t):
        return "stop_delete", {"action": "delete_all"}
    if mem._EXPORT.search(t):
        return "memory", {"action": "export"}
    if mem._REMEMBER.search(t):
        return "memory", {"action": "remember"}
    if mem._EDIT.match(t):
        return "memory", {"action": "edit"}
    forget = mem._FORGET.match(t) or mem._FORGET_AFTER.match(t)
    if forget and not parse_wallet_message(t).cards:  # a card to remove goes to the wallet
        return "stop_delete", {"action": "forget"}
    if sc._ASK_CARD.search(t):
        p = parse_purchase(t)
        return "card_question", {
            "amount": str((p.amount_paise or 0) // 100) if p.amount_paise else "",
            "category": p.category or "",
        }
    if sc._BILL_HINT.search(t):
        b = parse_bill_text(t, today)
        if b.due_date is not None or (b.amount_paise is not None and b.kind.value != "other"):
            return "bill", {
                "amount": str((b.amount_paise or 0) // 100) if b.amount_paise else "",
                "day": str(b.due_date.day) if b.due_date else "",
            }
    w = parse_wallet_message(t)
    if w.kind == "add" and (w.cards or w.unclear):
        return "add_card", {"banks": ",".join(sorted(c.bank for c in w.cards))}
    if w.kind == "remove" and w.cards:
        return "stop_delete", {"action": "remove_card"}
    if sc._SUMMARY.search(t) or sc._BILLS_LIST.search(t):
        return "memory", {"action": "savings"}
    if parse_mute_command(t) is not None:
        return "stop_delete", {"action": "mute"}
    p = parse_purchase(t)
    if len(t.split()) <= 8 and re.search(r"\b(?:pe|par|on)\b", t, re.I) and p.complete:
        return "card_question", {
            "amount": str((p.amount_paise or 0) // 100),
            "category": p.category or "",
        }
    parsed = parse_message(t, NOW)
    if parsed.status in ("event", "commitment") and parsed.start is not None:
        local = to_ist(parsed.start)
        return "event", {
            "hour": str(local.hour),
            "minute": str(local.minute),
            "day": str(_day_offset(parsed.start)),
            "dom": str(local.day),
            "kind": parsed.kind.value,
        }
    if parsed.status in ("bill",):
        return "bill", {}
    if _is_menu(t):
        return "menu", {}
    return "none", {}


def _slots_ok(want: dict[str, str], got: dict[str, str]) -> bool:
    for key, value in want.items():
        have = got.get(key, "")
        if key == "callee":
            if value.lower() not in have:
                return False
        elif key == "banks":
            if sorted(value.split(",")) != sorted(h for h in have.split(",") if h):
                return False
        elif have != value:
            return False
    return True


def evaluate(cases: list[Case], *, normalise: bool = True) -> Report:
    report = Report()
    for case in cases:
        text = normalise_text(case.text).text if normalise else case.text
        try:
            predicted, got = classify(text)
        except Exception:  # noqa: BLE001
            predicted, got = "error", {}
        ok = predicted == case.intent
        report.outcomes.append(
            Outcome(case, predicted, got, ok, ok and _slots_ok(case.slots, got), text)
        )
    return report


# ------------------------------------------------------------------ printing / CLI


def format_report(report: Report, *, title: str, show_failures: bool = True) -> str:
    lines = [title, "-" * len(title)]
    lines.append(f"{'intent':<14}{'n':>5}{'intent acc':>12}{'strict acc':>12}")
    for intent, row in report.per_intent().items():
        lines.append(
            f"{intent:<14}{int(row['n']):>5}{row['intent_acc']:>11.1%}{row['strict_acc']:>12.1%}"
        )
    lines.append(
        f"{'ALL':<14}{len(report.outcomes):>5}{report.intent_acc:>11.1%}{report.strict_acc:>12.1%}"
    )
    fails = report.failures()
    if show_failures and fails:
        lines += ["", f"failures ({len(fails)}):"]
        for o in fails:
            why = f"got {o.predicted} {o.got}" if not o.intent_ok else f"slots {o.got}"
            lines.append(f"  [{o.case.id}] want {o.case.intent} {o.case.slots}")
            lines.append(f"      text: {o.case.text}")
            lines.append(f"      read: {o.normalised}")
            lines.append(f"      {why}")
    return "\n".join(lines)


def run_cli(split: str = "all", *, baseline: bool = False, failures: bool = True) -> int:
    cases = load_cases(split)
    if not cases:
        print("no cases")
        return 1
    print(f"{len(cases)} labelled messages ({split}); today = {to_ist(NOW).date()}\n")
    title = f"with the normaliser ({split})"
    print(format_report(evaluate(cases), title=title, show_failures=failures))
    if baseline:
        print()
        print(
            format_report(
                evaluate(cases, normalise=False), title=f"without it ({split})", show_failures=False
            )
        )
    return 0


def today_ist() -> date:
    return to_ist(NOW).date() + timedelta(days=0)
