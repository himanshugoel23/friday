"""Deterministic people/place reference resolution ("papa", "mummy ke ghar ke paas",
"near my office", "his place"). Used by the fake LLM and as the real path's
fallback, and inside ``interpret`` to resolve the refs the draft names.
"""

from __future__ import annotations

import re

from friday.core.models import ConversationContext, Direction, Person, Place

from ..schemas import AliasOut, ButtonOut, ResolutionOut
from ..textutil import has_any, norm, truncate_title

# canonical relation -> words users say for it (EN / Hindi / Hinglish / Marathi...)
RELATION_WORDS: dict[str, tuple[str, ...]] = {
    "father": (
        "papa",
        "papa ji",
        "pappa",
        "dad",
        "daddy",
        "father",
        "pitaji",
        "pita ji",
        "abba",
        "baba",
        "bauji",
        "pops",
        "पापा",
        "पिताजी",
    ),
    "mother": (
        "mummy",
        "mumma",
        "mom",
        "mommy",
        "mum",
        "maa",
        "ma",
        "mother",
        "amma",
        "aai",
        "mataji",
        "माँ",
        "मम्मी",
    ),
    "wife": ("wife", "biwi", "patni", "missus", "better half"),
    "husband": ("husband", "pati", "hubby"),
    "son": ("son", "beta", "bete"),
    "daughter": ("daughter", "beti", "bitiya"),
    "grandmother": ("nani", "dadi", "grandma", "granny", "grandmother", "ajji", "aaji"),
    "grandfather": ("nana", "dada", "grandpa", "grandfather", "ajoba"),
    "brother": ("brother", "bhai", "bhaiya", "bro"),
    "sister": ("sister", "didi", "behen", "sis"),
    "friend": ("friend", "dost"),
    "uncle": ("uncle", "chacha", "mama", "tauji"),
    "aunt": ("aunt", "aunty", "chachi", "mami", "bua", "mausi"),
}
_RELATION_ALIASES = {"dad": "father", "mom": "mother", "mum": "mother"}
PARENTS_WORDS = (
    "parents",
    "mom-dad",
    "mom dad",
    "mom and dad",
    "mummy papa",
    "mummy-papa",
    "mom & dad",
    "maa papa",
    "mummy aur papa",
    "papa mummy",
)

HOME_WORDS = ("home", "ghar", "house", "flat", "apartment", "place", "ghar pe", "residence")
OFFICE_WORDS = ("office", "work", "workplace", "daftar", "dafter")
PRONOUN_WORDS = (
    "his",
    "her",
    "their",
    "unke",
    "unka",
    "unki",
    "uske",
    "uska",
    "uski",
    "inke",
    "inka",
    "him",
    "them",
)


def canonical_relation(rel: str | None) -> str | None:
    if not rel:
        return None
    r = norm(rel)
    r = _RELATION_ALIASES.get(r, r)
    for canon, words in RELATION_WORDS.items():
        if r == canon or r in words:
            return canon
    return r


def relation_word_in(text: str) -> tuple[str, str] | None:
    """(canonical relation, word used) for the first relation word in ``text``."""
    t = norm(text)
    best: tuple[int, str, str] | None = None
    for canon, words in RELATION_WORDS.items():
        for w in words:
            m = re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), canon, w)
    return (best[1], best[2]) if best else None


def _person_matches(p: Person, t: str) -> str | None:
    """Return the word in ``t`` that refers to ``p`` (alias / name / relation)."""
    for alias in p.aliases:
        if alias and re.search(rf"(?<!\w){re.escape(norm(alias))}(?!\w)", t):
            return alias
    first = norm(p.name).split()[0] if p.name.strip() else ""
    if first and len(first) > 2 and re.search(rf"(?<!\w){re.escape(first)}(?!\w)", t):
        return p.name.split()[0]
    canon = canonical_relation(p.relation)
    if canon and canon in RELATION_WORDS:
        for w in RELATION_WORDS[canon]:
            if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t):
                return w
    return None


def find_people(ctx: ConversationContext, text: str) -> list[tuple[Person, str]]:
    t = norm(text)
    out: list[tuple[Person, str]] = []
    for p in ctx.people:
        word = _person_matches(p, t)
        if word:
            out.append((p, word))
    if not out and has_any(t, PARENTS_WORDS):
        for p in ctx.people:
            if canonical_relation(p.relation) in ("father", "mother"):
                out.append((p, "parents"))
    return out


def _last_person_mentioned(ctx: ConversationContext) -> Person | None:
    for turn in reversed(ctx.recent):
        hits = find_people(ctx, turn.text)
        if len(hits) == 1:
            return hits[0][0]
        if hits and turn.direction == Direction.INBOUND:
            return hits[0][0]
    return None


def _place_matches(pl: Place, t: str) -> bool:
    for alias in [pl.label, *pl.aliases]:
        a = norm(alias)
        if a and len(a) > 1 and re.search(rf"(?<!\w){re.escape(a)}(?!\w)", t):
            return True
    return False


def _is_home(pl: Place) -> bool:
    return has_any(norm(pl.label), HOME_WORDS) or any(
        has_any(norm(a), HOME_WORDS) for a in pl.aliases
    )


def _is_office(pl: Place) -> bool:
    return has_any(norm(pl.label), OFFICE_WORDS) or any(
        has_any(norm(a), OFFICE_WORDS) for a in pl.aliases
    )


_NEAR = re.compile(
    r"\b(?:near|nearby|around|close to)\s+([a-z0-9][\w .,'-]{2,40}?)(?=$|[,.?!]| for | ke | "
    r"tomorrow| today| on | at | under | by | ideally)"
    r"|\b([a-z][\w'-]{2,20}(?: [a-z][\w'-]{2,20})?)\s+(?:ke paas|ke pass|ke nazdeek|ke aas paas)\b",
    re.I,
)
_STOP_LOCATIONS = {
    "the",
    "my",
    "a",
    "an",
    "it",
    "them",
    "morning",
    "evening",
    "time",
    "budget",
    "kal",
    "aaj",
    "subah",
    "shaam",
    "ghar",
    "office",
    "home",
    "next week",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "january",
    "february",
}


def location_text_of(text: str) -> str | None:
    t = norm(text)
    for m in _NEAR.finditer(t):
        loc = (m.group(1) or m.group(2) or "").strip(" ,.")
        words = loc.split()
        if (
            not loc
            or loc in _STOP_LOCATIONS
            or (words and words[0] in _STOP_LOCATIONS)
            or (words and words[0] in {"kis", "kaun", "kaunse", "which", "any", "koi"})
        ):
            continue
        if re.search(r"\d+\s*(am|pm)|\bbaje\b|₹|rs\b", loc):
            continue
        if any(
            w in RELATION_WORDS.get("father", ()) + RELATION_WORDS.get("mother", ()) for w in words
        ):
            continue
        return loc
    return None


def resolve(ctx: ConversationContext, text: str) -> ResolutionOut:
    t = norm(text)
    out = ResolutionOut()
    if not t:
        return out

    # ---- people
    hits = find_people(ctx, t)
    person: Person | None = None
    if len(hits) == 1 or (hits and all(w == "parents" for _, w in hits)):
        person = hits[0][0]
    elif len(hits) > 1:
        # same word matching several people (e.g. two "mama"s) -> ambiguous
        distinct = {p.id for p, _ in hits}
        exact = [
            p
            for p, w in hits
            if norm(w) in [norm(a) for a in p.aliases] or norm(w) == norm(p.name.split()[0])
        ]
        if len(exact) == 1:
            person = exact[0]
        elif len(distinct) > 1:
            out.ambiguous = True
            out.clarification = "Who is this for? " + " or ".join(p.name for p, _ in hits[:3]) + "?"
            out.buttons = [
                ButtonOut(id=f"r:person:{p.id}", title=truncate_title(p.name)) for p, _ in hits[:3]
            ]
            return out
    pronoun = has_any(t, PRONOUN_WORDS)
    if person is None and pronoun:
        person = _last_person_mentioned(ctx)
    if person is not None:
        out.person_id = person.id
        used = next((w for p, w in hits if p.id == person.id), None)
        if (
            used
            and used != "parents"
            and norm(used) not in [norm(a) for a in person.aliases]
            and norm(used) != norm(person.name.split()[0])
        ):
            out.new_aliases.append(AliasOut(target="person", target_id=person.id, alias=used))

    # ---- places
    place_hits = [pl for pl in ctx.places if not pl.ephemeral and _place_matches(pl, t)]
    wants_home = has_any(t, HOME_WORDS) or "'s place" in t or "s place" in t
    wants_office = has_any(t, OFFICE_WORDS)
    candidates: list[Place] = []
    if person is not None and (wants_home or pronoun):
        candidates = [pl for pl in ctx.places if pl.person_id == person.id and not pl.ephemeral]
        if not candidates and canonical_relation(person.relation) in ("father", "mother"):
            # "Mom & Dad's home" is often linked to only one parent
            parents = {
                p.id for p in ctx.people if canonical_relation(p.relation) in ("father", "mother")
            }
            candidates = [pl for pl in ctx.places if pl.person_id in parents]
    elif wants_office:
        candidates = [pl for pl in ctx.places if _is_office(pl) and pl.person_id is None]
    elif place_hits:
        candidates = place_hits
    elif wants_home and person is None:
        candidates = [pl for pl in ctx.places if _is_home(pl) and pl.person_id is None]
    if place_hits and len(candidates) > 1:
        narrowed = [pl for pl in candidates if pl in place_hits]
        candidates = narrowed or candidates
    if len(candidates) == 1:
        out.place_id = candidates[0].id
    elif len(candidates) > 1:
        out.ambiguous = True
        labels = [pl.label for pl in candidates[:3]]
        out.clarification = " or ".join(labels) + "?"
        out.buttons = [
            ButtonOut(id=f"r:place:{pl.id}", title=truncate_title(pl.label))
            for pl in candidates[:3]
        ]
    if out.place_id is None and not out.ambiguous:
        out.location_text = location_text_of(text)
    return out
