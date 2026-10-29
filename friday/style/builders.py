# ruff: noqa: E501
"""Message builders for the Instinct-style reply shapes (docs/STYLE_GUIDE.md). Pure functions that
return chat text; the lines live in ``friday.style.wording`` (PENDING founder approval).

Each builder is one message with one idea. Callers send a second message for a second idea.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from friday.style.wording import t

MAX_OPTIONS = 4


def ack(what: str, lang: str = "hinglish") -> str:
    """First reply, within seconds, naming the concrete action."""
    return t("ack", lang, what=what)


def status(what: str, lang: str = "hinglish", *, step: str | None = None) -> str:
    """A second short status, only if the work is slow; ``step`` answers 'status?' with the current step."""
    return t("status_step", lang, step=step) if step else t("status_slow", lang, what=what)


def result(
    headline: str,
    options: Sequence[str],
    *,
    pick: tuple[str, str] | None = None,
    question: str | None = None,
    lang: str = "hinglish",
) -> str:
    """Headline fact first, 3-4 option lines, 'My pick', then exactly ONE closing question or next step."""
    lines = [headline.strip()]
    lines += [f"{i}. {o.strip()}" for i, o in enumerate(list(options)[:MAX_OPTIONS], 1)]
    if pick is not None:
        lines.append(t("pick", lang, name=pick[0], reason=pick[1]))
    if question:
        lines.append(question.strip())
    return "\n".join(lines)


def grouped_questions(items: Sequence[tuple[str, str]], lang: str = "hinglish") -> str:
    """Many form answers in ONE message, each with its default ('Salary: 55L?')."""
    rows = [t("grouped_row", lang, label=label, default=default) for label, default in items]
    return "\n".join([t("grouped_head", lang), *rows])


def assumption(thing: str, lang: str = "hinglish") -> str:
    """Say the assumption out loud ('Taking this as Gazebo Inn, Sector 39. Right?')."""
    return t("assume", lang, thing=thing)


def confirm_irreversible(
    *,
    item: str,
    place: str | None = None,
    address: str | None = None,
    fees: str | None = None,
    total: str,
    next_step: str,
    lang: str = "hinglish",
) -> str:
    """Restate item, place, address, fees, TOTAL and what happens next, then ask for approval."""
    rows = [t("confirm_head", lang), t("confirm_item", lang, item=item)]
    if place:
        rows.append(t("confirm_place", lang, place=place))
    if address:
        rows.append(t("confirm_address", lang, address=address))
    if fees:
        rows.append(t("confirm_fees", lang, fees=fees))
    rows += [t("confirm_total", lang, total=total), t("confirm_next", lang, next_step=next_step), t("confirm_ask", lang)]
    return "\n".join(rows)


def cancelled(lang: str = "hinglish", *, ordered: bool = False) -> str:
    """After 'no' or 'cancel': always say what was NOT done."""
    return t("cancelled_order" if ordered else "cancelled", lang)


def correction(fix: str, lang: str = "hinglish") -> str:
    return t("correction", lang, fix=fix)


def honest_limit(cant: str, alt: str, lang: str = "hinglish", *, question: str | None = None) -> str:
    """'I can't X; here is what I can do instead.' Never a bare refusal."""
    text = t("limit", lang, cant=cant, alt=alt)
    return f"{text}\n{question.strip()}" if question else text


# --------------------------------------------------------------------------- proof card
OUTCOMES = ("done", "attempted", "checkout", "failed")


@dataclass
class ProofCard:
    """What a proof message says. All fields are plain, already-scrubbed strings."""

    outcome: str  # done | attempted | checkout (stopped at payment) | failed
    what: str
    where: str = ""
    when: str = ""
    amount: str = ""
    reference: str = ""
    link: str = ""
    seen: str = ""  # failed or stopped attempts: what the page or call showed
    has_screenshot: bool = False
    keep_days: int | None = None
    plain: str = ""  # failed / attempted: what happened in plain words (replaces the generic head and the 'Saw:' line)
    next_step: str = ""  # failed / attempted: what Friday can do next
    extra: list[str] = field(default_factory=list)


def proof_card(card: ProofCard, lang: str = "hinglish") -> str:
    """Head, what / where / when / amount / reference / link, screenshot note, expiry line."""
    outcome = card.outcome if card.outcome in OUTCOMES else "attempted"
    plain = card.plain if outcome in ("attempted", "failed") else ""
    head = t("proof_plain", lang, v=plain) if plain else t(f"proof_head_{outcome}", lang)
    rows = [head, t("proof_what", lang, v=card.what)]
    for key, value in (
        ("proof_where", card.where),
        ("proof_when", card.when),
        ("proof_amount", card.amount),
        ("proof_ref", card.reference),
        ("proof_link", card.link),
    ):
        if value:
            rows.append(t(key, lang, v=value))
    if card.seen and outcome in ("attempted", "failed", "checkout"):
        rows.append(t("proof_seen", lang, v=card.seen))
    if card.next_step and plain:
        rows.append(t("proof_next", lang, v=card.next_step))
    if card.has_screenshot:
        rows.append(t("proof_shot", lang))
    if card.keep_days:
        rows.append(t("proof_keep", lang, days=str(card.keep_days)))
    return "\n".join(rows)
