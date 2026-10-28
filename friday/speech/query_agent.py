# ruff: noqa: E501
"""Query Understanding Agent: Wispr-style rewrite of the user's TEXT into one clear instruction.

A shared component, not a copy: it reuses ``SpeechUnderstander`` (fillers, self-corrections, grounding,
deadline, rules floor, raw-words fallback) for the language work, and adds what text needs:

1. deterministic lingo (pls, tmrw, resto ...) from ``data/lingo.json``;
2. the USER-SPECIFIC dictionary: fuzzy match (edit distance + Indian-name phonetics) against the user's own
   places, people, shops and words FIRST ("Soneepat" -> "Sonipat" for someone who lives in Sonipat);
   sure matches are fixed, unsure ones become ONE question (never a silent change);
3. the shared understander for the rest, then its code-enforced grounding (no invented number, day, name).

The original text is always kept. Never applied to a vendor's speech. Never raises. Secret talk (OTP/PIN)
is passed through untouched. The model step has a hard deadline; rules + fuzzy always run.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.core.models import ConversationContext
from friday.speech import fuzzy
from friday.speech.memory import MemoryView, build_memory
from friday.speech.schema import Repair
from friday.speech.userdict import UserDictionary, entities_from_context
from friday.voice.text import redact_secrets

log = get_logger(__name__)
_LINGO = json.loads((Path(__file__).parent / "data" / "lingo.json").read_text(encoding="utf-8"))
ABBREV: dict[str, str] = {k.lower(): v for k, v in _LINGO.get("abbreviations", {}).items()}
_WORD = re.compile(r"[\wऀ-ॿ']+", re.U)


@dataclass
class AskBack:
    """One question for the user: 'did you mean <entity>?'. Nothing was changed yet."""

    heard: str
    candidate: str
    kind: str
    candidate_text: str  # the instruction with the fix applied
    source: str  # dictionary | place | person | shop | profile
    score: float


@dataclass
class QueryUnderstanding:
    original_text: str
    instruction: str
    source: str = "raw"  # model | rules | fuzzy | raw
    repairs: list[Repair] = field(default_factory=list)
    entity_fixes: list[tuple[str, str, str, str]] = field(default_factory=list)  # heard, written, kind, source
    ask: AskBack | None = None
    reason: str | None = None
    latency_ms: float = 0.0

    @property
    def changed(self) -> bool:
        return self.instruction.strip() != self.original_text.strip()

    def audit(self) -> dict[str, Any]:
        """Counts and kinds only (no words): safe for logs and ``InboundMessage.raw``."""
        return {"source": self.source, "changed": self.changed, "repairs": len(self.repairs),
                "entity_fixes": len(self.entity_fixes), "asked": self.ask is not None, "reason": self.reason,
                "ms": round(self.latency_ms)}


def expand_lingo(text: str) -> tuple[str, list[Repair]]:
    """Whole-word abbreviation expansion. Never touches digits."""
    repairs: list[Repair] = []

    def sub(m: re.Match[str]) -> str:
        w = m.group()
        full = ABBREV.get(w.lower())
        if full is None or full.lower() == w.lower():
            return w
        repairs.append(Repair(old=w, new=full, kind="other"))
        return full

    return _WORD.sub(sub, text), repairs


class QueryUnderstandingAgent:
    def __init__(self, understander: Any, userdict: UserDictionary | None, settings: Any) -> None:
        self.und, self.userdict, self.s = understander, userdict, settings

    async def understand(self, user_id: str, text: str, ctx: ConversationContext | None = None, *,
                         skip_forms: set[str] | None = None, model: bool = True) -> QueryUnderstanding:
        t0 = time.perf_counter()
        original = (text or "").strip()
        out = QueryUnderstanding(original_text=original, instruction=original)

        def done(r: QueryUnderstanding) -> QueryUnderstanding:
            r.latency_ms = (time.perf_counter() - t0) * 1000
            log.info("query understanding %s", r.audit())
            return r

        try:
            if not original:
                out.reason = "empty"
                return done(out)
            if redact_secrets(original) != original:
                out.reason = "secret_context"  # OTP/PIN talk is never touched
                return done(out)
            work, repairs = expand_lingo(original)
            out.repairs.extend(repairs)

            entries = await self.userdict.list(user_id) if self.userdict is not None else []
            entities = entities_from_context(ctx, entries)
            res = fuzzy.find_matches(work, entities, skip=skip_forms)
            fixed = fuzzy.apply(work, res.auto)
            for m in res.auto:
                out.entity_fixes.append((m.heard, m.entity.written, m.entity.kind, m.entity.source))
                out.repairs.append(Repair(old=m.heard, new=m.entity.written, kind="mishearing"))
            work = fixed
            if res.ask:
                m = max(res.ask, key=lambda x: x.score)  # one question at a time
                out.ask = AskBack(m.heard, m.entity.written, m.entity.kind,
                                  _apply_one(work, m.heard, m.entity.written), m.entity.source, m.score)
                out.instruction = work
                out.source = "fuzzy" if out.entity_fixes else "raw"
                out.reason = "needs_confirmation"
                return done(out)

            mv = self._memory(ctx, entries)
            if model and self.und is not None:
                u = await self.und.understand(work, ctx, channel="text", force=True, memory=mv,
                                              deadline_s=float(getattr(self.s, "query_understanding_timeout_s", 2.5)))
                out.reason = u.reason
                if u.source in ("llm", "rules") and u.corrected_text.strip():
                    work = u.corrected_text
                    out.repairs.extend(u.repairs)
                    out.source = "model" if u.source == "llm" else "rules"
            if out.source == "raw" and work != original:
                out.source = "fuzzy" if out.entity_fixes else "rules"
            out.instruction = work
        except Exception:  # noqa: BLE001 - a rewrite problem must never block the user
            log.exception("query understanding failed; using the words as typed")
            out = QueryUnderstanding(original_text=original, instruction=original, reason="error")
        return done(out)

    async def learn(self, user_id: str, repos: Any, clock: Any, fixes: list[tuple[str, str, str, str]], *,
                    confirmed: bool = False) -> None:
        """Each fixed spelling is a sighting: after two (or one confirmation) it is a saved heard form, so the
        same slip is fixed even if the model is down. Person/Place rows use MemoryService; the rest the
        dictionary. Never raises."""
        try:
            from friday.memory import MemoryService

            svc = MemoryService(repos, clock)
            for heard, written, kind, _src in fixes:
                if kind in ("place", "person") and await svc.note_misheard(user_id, heard, written, confirmed=confirmed) != "ignored":
                    continue
                if self.userdict is not None:
                    await self.userdict.add(user_id, written, kind)  # seeds the entry from memory (profile city ...)
                    await self.userdict.note_heard(user_id, written, heard, confirmed=confirmed)
        except Exception:  # noqa: BLE001
            log.exception("query understanding: learning failed")

    @staticmethod
    def _memory(ctx: ConversationContext | None, entries: list[Any]) -> MemoryView:
        mv = build_memory(ctx)
        for e in entries:
            label = e.written
            (mv.people if e.kind == "person" else mv.businesses if e.kind == "shop" else mv.places).append(label)
            mv.vocab |= {t.lower() for t in _WORD.findall(label) if len(t) > 1}
            for h in e.heard:
                mv.aliases[h.lower()] = label
        return mv


def _apply_one(text: str, heard: str, written: str) -> str:
    """Replace the first case-insensitive occurrence of the heard form with the written form."""
    return re.sub(re.escape(heard), written, text, count=1, flags=re.IGNORECASE)
