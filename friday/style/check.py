# ruff: noqa: E501
"""Deterministic post-check of outgoing chat text (docs/STYLE_GUIDE.md section "Message budget").

Pure functions, no network, no LLM. Two uses:

* ``check`` returns violations for ANY text. For model free-text it is only used to log or to flag
  in the bench: free text is never rewritten.
* ``enforce`` is applied ONLY to templates we own (planner, shopping, intents, browser-agent lines).
  It never changes words: it strips markdown header markers and splits an over-long text into several
  short messages at paragraph or line borders ("a second message for a second idea").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from friday.core.logging import get_logger

log = get_logger(__name__)

# kind -> (max non-empty lines, max characters). Comparisons, confirmations and proof cards are "result".
BUDGETS: dict[str, tuple[int, int]] = {"text": (5, 450), "result": (8, 700), "proof": (10, 800)}

_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_LIST_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")
_Q = re.compile(r"[?？؟]+(?=\s|$|[)\"'])")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LETTER = re.compile(r"[^\W\d_]", re.U)

_REFUSAL = re.compile(
    r"\bcan'?t\b|\bcannot\b|unable to|not able to|\bsorry\b|\bnahi (kar|dekh|de|ho|bana|laga|sak)|\bnahi hua\b|"
    r"\bnahi hai\b|\bmanaa?\b|i don'?t (know|have)",
    re.I,
)
_CONFUSED = re.compile(r"samajh nahi pa|samajh nahi aa|didn'?t (?:quite )?(?:get|understand)|not sure what you mean", re.I)
_ALTERNATIVE = re.compile(
    r"\binstead\b|\bpaste\b|\bdraft\b|https?://|\blink\b|tab tak|you can|\bi can(?!'?t)\b|main (?:(?!nahi|na ).){0,25}(?:sakti|sakta)|"
    r"bata(?:o|iye|ao|ye)\b|\bconnect|set ?up|kar (?:dungi|dunga)|laga (?:dungi|dunga|dun)\b|\btry\b|\bshare\b|"
    r"bhej(?:iye|o|na)\b|\bopen\b|reminder|yaad dila|settings|\bapp\b|\bcall\b|likh (?:dungi|dunga|du)|"
    r"dekh (?:dungi|dunga|leti)|badle",
    re.I,
)
_CANCEL_OK = re.compile(
    r"nothing was (?:charged|booked|ordered|paid)|no charge|kuch charge (?:ya \w+ )?nahi|kuch (?:book|order|charge) nahi|"
    r"charge nahi hua",
    re.I,
)
_PROOF_MARK = re.compile(
    r"\bproof\b|\breference\b|\bref[:#]|screenshot|https?://|\bwhat:|\bkya:|\bsaw:|\bdikha\b", re.I
)


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str = ""

    def __str__(self) -> str:  # noqa: D105
        return f"{self.code}: {self.detail}" if self.detail else self.code


def lines_of(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def question_groups(text: str) -> int:
    """Number of separate question blocks. A run of consecutive question lines (a grouped-questions
    message) is ONE group; two question sentences in one prose line count as two."""
    groups = 0
    in_run = False
    for ln in text.splitlines():
        marks = len(_Q.findall(ln))
        if marks == 0:
            if ln.strip():
                in_run = False
            continue
        listlike = bool(_LIST_LINE.match(ln)) or (":" in ln and ln.index(":") < ln.find("?"))
        if not in_run:
            groups += 1
        groups += 0 if listlike else marks - 1
        in_run = True
    return groups


def script_violation(user_text: str, reply: str) -> str | None:
    """Reply in the user's script: Roman stays Roman; Devanagari gets mostly Devanagari."""
    if not user_text.strip() or not reply.strip():
        return None
    in_dev = len(_DEVANAGARI.findall(user_text))
    out_dev = len(_DEVANAGARI.findall(reply))
    if in_dev == 0:
        return "Devanagari reply to a Roman-script message" if out_dev > 2 else None
    letters = len(_LETTER.findall(reply)) or 1
    return "Roman reply to a Devanagari message" if out_dev / letters < 0.3 else None


def has_cancel_wording(text: str) -> bool:
    return bool(_CANCEL_OK.search(text))


def has_proof_marks(text: str) -> bool:
    return bool(_PROOF_MARK.search(text))


def headline_first(text: str) -> bool:
    """A comparison starts with the headline fact, not with its first option line."""
    ls = lines_of(text)
    if sum(1 for ln in ls if _LIST_LINE.match(ln)) < 2:
        return True
    return not _LIST_LINE.match(ls[0])


def check(text: str, *, kind: str = "text", user_text: str | None = None, has_buttons: bool = False) -> list[Violation]:
    """Violations of the style rules in ``text`` (empty list = clean)."""
    out: list[Violation] = []
    max_lines, max_chars = BUDGETS.get(kind, BUDGETS["text"])
    n_lines = len(lines_of(text))
    if n_lines > max_lines or len(text) > max_chars:
        out.append(Violation("too_long", f"{n_lines} lines, {len(text)} chars (budget {max_lines}/{max_chars})"))
    if question_groups(text) > 1:
        out.append(Violation("many_questions", f"{question_groups(text)} question groups"))
    if _HEADER.search(text):
        out.append(Violation("markdown_header"))
    if _CONFUSED.search(text):
        out.append(Violation("flat_refusal", "generic 'did not understand' reply"))
    elif kind != "proof" and _REFUSAL.search(text) and not (_ALTERNATIVE.search(text) or has_buttons or _CANCEL_OK.search(text)):
        out.append(Violation("flat_refusal", "refuses with no alternative"))
    if not headline_first(text):
        out.append(Violation("options_before_headline"))
    if user_text is not None:
        bad = script_violation(user_text, text)
        if bad:
            out.append(Violation("script_mismatch", bad))
    return out


def log_violations(source: str, violations: list[Violation]) -> None:
    """Codes only, never the text (the reply may hold personal data)."""
    if violations:
        log.info("style: %s violated %s", source, ",".join(v.code for v in violations))


def strip_headers(text: str) -> str:
    return _HEADER.sub("", text)


def split_messages(text: str, kind: str = "text") -> list[str]:
    """Greedy split at blank lines, then at line borders, so each part fits the budget. Words are
    never changed; a single line longer than the character budget stays whole."""
    max_lines, max_chars = BUDGETS.get(kind, BUDGETS["text"])
    if len(lines_of(text)) <= max_lines and len(text) <= max_chars:
        return [text]
    paras = [p.strip("\n") for p in re.split(r"\n\s*\n", text) if p.strip()]
    units: list[str] = []
    for p in paras:  # a paragraph that alone breaks the budget is cut at line borders
        if len(lines_of(p)) <= max_lines and len(p) <= max_chars:
            units.append(p)
            continue
        cur: list[str] = []
        for ln in lines_of(p):
            if cur and (len(cur) + 1 > max_lines or len("\n".join([*cur, ln])) > max_chars):
                units.append("\n".join(cur))
                cur = []
            cur.append(ln)
        if cur:
            units.append("\n".join(cur))
    parts: list[str] = []
    cur_s = ""
    for u in units:
        joined = f"{cur_s}\n\n{u}" if cur_s else u
        if cur_s and (len(lines_of(joined)) > max_lines or len(joined) > max_chars):
            parts.append(cur_s)
            cur_s = u
        else:
            cur_s = joined
    if cur_s:
        parts.append(cur_s)
    return parts


def enforce(text: str, *, kind: str = "text") -> list[str]:
    """For OWNED templates only: strip header markers and split to the budget. Everything else
    (questions, refusals, script) is only flagged by ``check``; we never guess a rewrite."""
    return split_messages(strip_headers(text), kind)
