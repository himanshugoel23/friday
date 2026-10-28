# ruff: noqa: E501
"""Fuzzy matching of what the user typed against the USER'S OWN entities (places, people, shops, words).

Edit distance plus a phonetic skeleton tuned for Indian-name transliteration ("Soneepat", "Sonepat",
"sonipath" -> Sonipat). Deterministic, no model, no network. Three outcomes per candidate:

* ``auto``  - the heard form is a saved alias, or it is a very close sound/spelling match to a place, shop or
              dictionary word and nothing else is close: fix it (the original text is always kept).
* ``ask``   - plausible but not sure (or a person's name, or two entities are about equally close): the
              caller must ASK the user; nothing is changed silently.
* nothing   - too far, too short, an ordinary word, or already exactly right.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

_TOKEN = re.compile(r"[\wऀ-ॿ']+", re.U)
_DATA = Path(__file__).parent / "data" / "lingo.json"

AUTO_MIN = 0.84  # score for a silent fix (plus an identical phonetic skeleton)
ASK_MIN = 0.70  # below this nothing is suggested
ASK_SKELETON_MIN = 0.75
MIN_LEN = 4  # shorter words are never fuzzy-matched
MARGIN = 0.04  # two entities closer than this -> ask
MAX_WINDOW = 3  # "sone pat" (two typed words) can match "Sonipat"

_DIGRAPHS = (("ph", "f"), ("kh", "k"), ("gh", "g"), ("bh", "b"), ("dh", "d"), ("th", "t"), ("jh", "j"),
             ("sh", "s"), ("ch", "c"), ("ck", "k"), ("qu", "k"), ("w", "v"), ("z", "j"), ("q", "k"), ("x", "ks"))


@dataclass(frozen=True)
class Entity:
    written: str  # the form the user's memory holds ("Sonipat")
    kind: str  # place | person | shop | word
    source: str  # profile | place | person | shop | dictionary
    aliases: tuple[str, ...] = ()  # active heard forms: exact, case-insensitive, always trusted


@dataclass
class Match:
    start: int  # character span in the text
    end: int
    heard: str
    entity: Entity
    score: float
    decision: str  # auto | ask
    reason: str = ""
    runner_up: float = 0.0


@dataclass
class Resolution:
    matches: list[Match] = field(default_factory=list)

    @property
    def auto(self) -> list[Match]:
        return [m for m in self.matches if m.decision == "auto"]

    @property
    def ask(self) -> list[Match]:
        return [m for m in self.matches if m.decision == "ask"]


def _load() -> dict:
    try:
        return json.loads(_DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_COMMON: frozenset[str] = frozenset(w.lower() for w in _load().get("common_words", []))


def norm(s: str) -> str:
    return re.sub(r"[^\wऀ-ॿ]", "", (s or "").lower())


def edit_distance(a: str, b: str) -> int:
    """Damerau-Levenshtein (adjacent swaps count 1)."""
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def skeleton(word: str) -> str:
    """Consonant skeleton after Indian-English transliteration folding (th->t, ph->f, w->v, ee/i/e merge)."""
    w = norm(word)
    for a, b in _DIGRAPHS:
        w = w.replace(a, b)
    w = re.sub(r"c(?=[ei])", "s", w).replace("c", "k")
    w = w.replace("y", "i")
    out = []
    for i, ch in enumerate(w):
        if ch in "aeiou" and i > 0:
            continue
        if ch == "h":
            continue
        if out and out[-1] == ch:
            continue
        out.append("a" if ch in "aeiou" else ch)  # any initial vowel folds to one symbol
    return "".join(out)


def similarity(a: str, b: str) -> tuple[float, float]:
    """(score, skeleton ratio) between two already-normalised words."""
    if a == b:
        return 1.0, 1.0
    edit = 1.0 - edit_distance(a, b) / max(len(a), len(b))
    sa, sb = skeleton(a), skeleton(b)
    skel = 1.0 if sa == sb else SequenceMatcher(None, sa, sb).ratio()
    return max(edit * 0.5 + skel * 0.5, 0.0), skel


def _tokens(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in _TOKEN.finditer(text or "")]


def find_matches(text: str, entities: list[Entity], *, skip: set[str] | None = None) -> Resolution:
    """All suggested fixes in ``text``, non-overlapping, best first. ``skip`` holds heard forms the user
    already said are right ("no, I meant it as written") so they are never asked about again."""
    skip = {norm(s) for s in (skip or set())}
    toks = _tokens(text)
    res = Resolution()
    if not toks or not entities:
        return res
    exact_forms: dict[str, Entity] = {}
    written_forms: set[str] = set()
    for e in entities:
        written_forms.add(norm(e.written))
        for al in e.aliases:
            exact_forms[norm(al)] = e
    used: set[int] = set()
    candidates: list[Match] = []
    for i in range(len(toks)):
        for n in range(1, MAX_WINDOW + 1):
            if i + n > len(toks):
                break
            window = toks[i:i + n]
            if n > 1 and any(text[window[k][1]:window[k + 1][0]].strip() for k in range(n - 1)):
                break  # punctuation between the words: not one name
            heard = text[window[0][0]:window[-1][1]]
            h = norm(heard)
            if not h or h.isdigit() or any(len(k) >= MIN_LEN and (h in k or k in h) for k in skip):
                continue
            if h in written_forms:
                if n > 1 and len(h) >= MIN_LEN:  # "soni pat" typed as two words
                    e = next(x for x in entities if norm(x.written) == h)
                    if " ".join(heard.lower().split()) != " ".join(e.written.lower().split()):
                        candidates.append(Match(window[0][0], window[-1][1], heard, e, 1.0, "auto", "same letters"))
                continue  # already exactly right
            if n > 1 and any(
                norm(" ".join(t[2] for t in window[a:b])) in written_forms
                for a in range(n) for b in range(a + 1, n + 1) if (b - a) < n
            ):
                continue  # the window already contains a correctly written entity plus a neighbouring word
            if h in exact_forms:
                e = exact_forms[h]
                candidates.append(Match(window[0][0], window[-1][1], heard, e, 1.0, "auto", "saved alias"))
                continue
            if len(h) < MIN_LEN or h in _COMMON or (n == 1 and h in {x for x in _COMMON}):
                continue
            scored = []
            for e in entities:
                w = norm(e.written)
                if h[0] != w[0] and skeleton(h)[:1] != skeleton(w)[:1]:
                    continue
                score, skel = similarity(h, w)
                scored.append((score, skel, e))
            if not scored:
                continue
            scored.sort(key=lambda x: -x[0])
            score, skel, best = scored[0]
            second = max((s for s, _k, e in scored[1:] if e.written != best.written), default=0.0)
            if score < ASK_MIN or skel < ASK_SKELETON_MIN:
                continue
            clear = score >= AUTO_MIN and skel >= 0.99 and best.kind != "person" and score - second >= MARGIN
            candidates.append(Match(
                window[0][0], window[-1][1], heard, best, round(score, 3), "auto" if clear else "ask",
                "close spelling and sound" if clear else ("a person's name" if best.kind == "person" else "not sure"),
                round(second, 3),
            ))
    candidates.sort(key=lambda m: (-m.score, m.start))
    for m in candidates:
        idx = {k for k, (s, e, _t) in enumerate(toks) if s >= m.start and e <= m.end}
        if idx & used:
            continue
        used |= idx
        res.matches.append(m)
    res.matches.sort(key=lambda m: m.start)
    return res


def apply(text: str, matches: list[Match]) -> str:
    """Replace the given matches (right to left so spans stay valid)."""
    out = text
    for m in sorted(matches, key=lambda m: -m.start):
        out = out[:m.start] + m.entity.written + out[m.end:]
    return out
