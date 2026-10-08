"""Learned IVR menu maps per company number (cost rule 4: replay without LLM).

After a call navigates an IVR and reaches a human, ``learn_ivr_map`` turns the
transcript into a map; ``IVRMap.to_note()`` renders it in the voice runner's replay
format, which the backend stores on ``Business.ivr_notes`` (shared across users -
it contains no personal data: identifier steps are stored as ``{label}``
placeholders, never digits). ``build_call_brief`` copies ``Business.ivr_notes`` into
the brief, the runner replays it with zero policy calls, and ``replay_step`` lets
the brain answer a known prompt without the LLM if the runner hands back control.

Replay note format (voice runner, ``friday.voice.session``):
    "replay: 2 | 3@broadband | {Registered mobile}# | 9@executive"
step = DTMF keys, optional ``@keyword`` the prompt must contain, ``{label}`` =
an approved identifier's value.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field

from friday.core.clock import utcnow
from friday.core.models import CallBrief, Speaker, Transcript

from .heuristics.callstate import (
    IDENTIFIER_PROMPT,
    is_hold,
    is_ivr,
    ivr_options,
    normalize_transcript,
    strip_tag,
)
from .textutil import norm

_DTMF = re.compile(r"^\s*dtmf:\s*([0-9*#w•x]+)", re.I)
_STOP = {
    "press",
    "please",
    "your",
    "dial",
    "enter",
    "followed",
    "number",
    "main",
    "menu",
    "repeat",
    "with",
    "this",
    "that",
    "for",
    "the",
    "and",
    "to",
}


class IVRStep(BaseModel):
    keys: str  # "3", "9", "{Registered mobile}#"
    expect: str | None = None  # keyword the prompt must contain
    prompt: str | None = None  # (trimmed) prompt heard, for humans debugging the map


class IVRMap(BaseModel):
    phone: str
    company: str | None = None
    steps: list[IVRStep] = Field(default_factory=list)
    reaches_agent: bool = True
    learned_at: datetime = Field(default_factory=utcnow)

    def to_note(self) -> str:
        parts = [s.keys + (f"@{s.expect}" if s.expect else "") for s in self.steps]
        return "replay: " + " | ".join(parts)

    @property
    def keys_only(self) -> list[str]:
        return [s.keys for s in self.steps]


def _keyword(prompt: str, key: str) -> str | None:
    for k, label in ivr_options(prompt):
        if k == key:
            words = [w for w in re.findall(r"[a-z]{4,}", norm(label)) if w not in _STOP]
            return max(words, key=len) if words else None
    return None


def learn_ivr_map(transcript: Transcript, brief: CallBrief) -> IVRMap | None:
    """Menu path from a transcript that reached a human agent (None otherwise)."""
    transcript = normalize_transcript(transcript)
    steps: list[IVRStep] = []
    last_prompt: str | None = None
    reached_human = False
    turns = transcript.turns
    for turn in turns:
        if turn.speaker == Speaker.CALLEE:
            if is_ivr(turn.text):
                last_prompt = strip_tag(turn.text)
            elif not is_hold(turn.text) and steps:
                reached_human = True
                break
            continue
        if turn.speaker == Speaker.SYSTEM and "human agent joined" in norm(turn.text) and steps:
            reached_human = True
            break
        m = _DTMF.match(turn.text) if turn.speaker in (Speaker.SYSTEM, Speaker.FRIDAY) else None
        if not m or last_prompt is None:
            continue
        pressed = m.group(1)
        p = norm(last_prompt)
        if re.search(IDENTIFIER_PROMPT, p) or len(re.sub(r"\D", "", pressed)) > 2 or "•" in pressed:
            ident = _identifier_label(brief, p)
            if ident is None:
                return None  # can't store a personal value; don't learn this path
            keys = "{" + ident + "}" + ("#" if pressed.endswith("#") else "")
            steps.append(IVRStep(keys=keys, prompt=last_prompt[:120]))
        else:
            steps.append(
                IVRStep(
                    keys=pressed, expect=_keyword(last_prompt, pressed), prompt=last_prompt[:120]
                )
            )
        last_prompt = None
    if not steps or not reached_human:
        return None
    return IVRMap(phone=brief.target.phone, company=brief.company or brief.target.name, steps=steps)


def _identifier_label(brief: CallBrief, prompt: str) -> str | None:
    wants_mobile = bool(re.search(r"mobile|phone|registered number", prompt))
    for ident in brief.approved_identifiers:
        lbl = norm(ident.label)
        is_mobile = bool(re.search(r"mobile|phone|registered", lbl))
        if is_mobile == wants_mobile:
            return ident.label
    return None


def map_from_notes(notes: list[str], phone: str) -> IVRMap | None:
    for note in notes:
        if note.lower().startswith("replay:"):
            steps = []
            for item in note.split(":", 1)[1].split("|"):
                keys, _, expect = item.strip().partition("@")
                if keys:
                    steps.append(IVRStep(keys=keys.strip(), expect=expect.strip() or None))
            return IVRMap(phone=phone, steps=steps) if steps else None
    return None


def replay_step(brief: CallBrief, transcript: Transcript) -> str | None:
    """Keys for the CURRENT IVR prompt from the brief's learned map, or None.
    The step index = number of DTMF presses so far. Identifier placeholders resolve
    only to APPROVED identifiers."""
    proposed = list(getattr(brief, "ivr_map", None) or [])  # proposed core field
    notes = ["replay: " + " | ".join(proposed)] if proposed else list(brief.ivr_notes)
    ivr_map = map_from_notes(notes, brief.target.phone)
    transcript = normalize_transcript(transcript)
    if ivr_map is None or not transcript.turns:
        return None
    last = transcript.turns[-1]
    if last.speaker != Speaker.CALLEE or not is_ivr(last.text):
        return None
    pressed = sum(
        1
        for t in transcript.turns
        if t.speaker in (Speaker.SYSTEM, Speaker.FRIDAY) and _DTMF.match(t.text)
    )
    if pressed >= len(ivr_map.steps):
        return None
    step = ivr_map.steps[pressed]
    if step.expect and step.expect.lower() not in norm(last.text):
        return None
    keys = step.keys
    m = re.match(r"\{([^}]+)\}(#?)", keys)
    if m:
        ref = m.group(1).lower()
        ident = next(
            (i for i in brief.approved_identifiers if ref in (i.id.lower(), i.label.lower())), None
        )
        if ident is None:
            return None
        return re.sub(r"\D", "", ident.value) + m.group(2)
    return keys
