"""Check, fix and learn the founder's script style. Offline, deterministic, no network."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

STYLE_PATH = Path(__file__).with_name("style.yaml")
LEARNED_PATH = Path(__file__).with_name("learned.yaml")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_WORD = re.compile(r"[\w']+", re.UNICODE)


@dataclass
class Issue:
    line_id: str
    kind: str  # swap | avoid | filler | ending | structure
    message: str
    suggestion: str | None = None
    severity: str = "warn"

    def __str__(self) -> str:
        tail = f"  -> {self.suggestion}" if self.suggestion else ""
        return f"[{self.kind}] {self.line_id}: {self.message}{tail}"


@dataclass
class StyleBook:
    swap: dict[str, str] = field(default_factory=dict)
    avoid: list[dict[str, Any]] = field(default_factory=list)
    fillers: list[str] = field(default_factory=list)
    filler_exempt_ids: set[str] = field(default_factory=set)
    filler_min_words: int = 5
    endings: list[dict[str, str]] = field(default_factory=list)
    structure: dict[str, Any] = field(default_factory=dict)
    golden: list[str] = field(default_factory=list)

    def prompt_block(self) -> str:
        """The style rules and approved examples, as text for a drafting prompt."""
        rules = [
            "Write natural spoken Hinglish, like a real person on the phone.",
            "Always include a natural filler ("
            + ", ".join(self.fillers)
            + ") in each sentence of 5+ words.",
            "Order: confirm the business name, then the purpose in one short line, then detail.",
            "Natural endings (rahega, rahegi, kar dun, ho jayega na), never stiff or formal.",
        ]
        rules += [f'Say "{b}" not "{a}".' for a, b in self.swap.items()]
        return "\n".join(rules + ["Approved examples:"] + [f"- {g}" for g in self.golden])


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_style(style_path: Path = STYLE_PATH, learned_path: Path = LEARNED_PATH) -> StyleBook:
    base, learned = _read(style_path), _read(learned_path)
    swap = {str(k).lower(): str(v) for k, v in (base.get("swap") or {}).items()}
    swap.update({str(k).lower(): str(v) for k, v in (learned.get("swap") or {}).items()})
    golden = list(base.get("golden") or []) + [str(g) for g in learned.get("golden") or []]
    return StyleBook(
        swap=swap,
        avoid=list(base.get("avoid") or []),
        fillers=[str(f).lower() for f in base.get("fillers") or []],
        filler_exempt_ids=set(base.get("filler_exempt_ids") or []),
        filler_min_words=int(base.get("filler_min_words", 5)),
        endings=list(base.get("endings") or []),
        structure=dict(base.get("structure") or {}),
        golden=golden,
    )


def _spoken(text: str) -> str:
    return _PLACEHOLDER.sub(" ", text)


def _has_word(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![\w']){re.escape(phrase)}(?![\w'])", text, re.I) is not None


def lint_line(line_id: str, text: str, style: StyleBook) -> list[Issue]:
    out: list[Issue] = []
    low = _spoken(text).lower()
    for bad, good in sorted(style.swap.items(), key=lambda kv: -len(kv[0])):
        if _has_word(low, bad):
            out.append(Issue(line_id, "swap", f'say "{good}" instead of "{bad}"', good, "error"))
    for a in style.avoid:
        if _has_word(low, a["word"]):
            out.append(
                Issue(line_id, "avoid", a.get("why", "avoid"), None, a.get("severity", "warn"))
            )
    stripped = text.strip().lower()
    for e in style.endings:
        if re.search(e["pattern"], stripped):
            out.append(Issue(line_id, "ending", e.get("why", "stiff ending"), e.get("suggest")))
    words = _WORD.findall(low)
    if (
        len(words) >= style.filler_min_words
        and line_id not in style.filler_exempt_ids
        and not any(_has_word(low, f) for f in style.fillers)
    ):
        out.append(
            Issue(line_id, "filler", "no natural filler word", "add Ji / Achha / Toh / actually")
        )
    return out


def autofix(text: str, style: StyleBook) -> str:
    """Apply the word swaps only (safe). Fillers and endings need a human choice."""
    parts = re.split(f"({_PLACEHOLDER.pattern})", text)
    for i, part in enumerate(parts):
        if _PLACEHOLDER.fullmatch(part):
            continue
        for bad, good in sorted(style.swap.items(), key=lambda kv: -len(kv[0])):
            part = re.sub(
                rf"(?<![\w']){re.escape(bad)}(?![\w'])",
                lambda m, g=good: g.capitalize() if m.group(0)[:1].isupper() else g,
                part,
                flags=re.I,
            )
        parts[i] = part
    return "".join(parts)


def lint_playbook(pb: Any, style: StyleBook) -> list[Issue]:
    """Every spoken line of a loaded playbook, plus the call-order rules."""
    issues: list[Issue] = []
    texts = {
        lid: (v if isinstance(v, str) else getattr(v, "text", "")) for lid, v in pb.lines.items()
    }
    for lid, text in texts.items():
        issues += lint_line(lid, text, style)
    st = style.structure
    opening = texts.get(getattr(pb, "disclosure", ""), "")
    if st.get("opening_must_ask_name") and opening and "kya meri baat" not in opening.lower():
        issues.append(
            Issue(
                getattr(pb, "disclosure", "disclosure"),
                "structure",
                "the opening must confirm the business name first",
                "Hello, kya meri baat {business_name_spoken} se ho rahi hai?",
            )
        )
    markers = [m.lower() for m in st.get("purpose_markers", [])]
    purpose = [(lid, t) for lid, t in texts.items() if lid.startswith("intro")]
    if markers and purpose and not any(any(m in t.lower() for m in markers) for _l, t in purpose):
        issues.append(
            Issue(
                purpose[0][0],
                "structure",
                "no purpose-of-call line (the hook) after the name check",
            )
        )
    maxw = int(st.get("purpose_max_words", 22))
    for lid, t in purpose:
        n = len(_WORD.findall(_spoken(t)))
        if n > maxw:
            issues.append(
                Issue(
                    lid, "structure", f"purpose line is {n} words; keep the hook short (<= {maxw})"
                )
            )
    return issues


def _tokens(s: str) -> list[str]:
    return _WORD.findall(s.lower())


def learn(
    before: str, after: str, *, learned_path: Path = LEARNED_PATH, note: str = ""
) -> dict[str, Any]:
    """Record one correction: new word swaps from the diff (<= 3 words each side) and the corrected
    line as a golden example. Returns what was learned."""
    a, b = _tokens(before), _tokens(after)
    swaps: dict[str, str] = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if tag == "replace" and 0 < i2 - i1 <= 3 and 0 < j2 - j1 <= 3:
            swaps[" ".join(a[i1:i2])] = " ".join(b[j1:j2])
    data = _read(learned_path)
    data.setdefault("swap", {}).update(swaps)
    data.setdefault("golden", [])
    if after.strip() and after.strip() not in data["golden"]:
        data["golden"].append(after.strip())
    data.setdefault("log", []).append(
        {
            "date": date.today().isoformat(),
            "before": before.strip(),
            "after": after.strip(),
            "note": note,
        }
    )
    learned_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return {"swaps": swaps, "golden_added": after.strip()}
