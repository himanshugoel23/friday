"""``friday playbook preview``: hear EXACTLY what a call will say, before any live call.

The real playbook engine and the real call runner play one scripted salon (a branch you pick);
every line Friday speaks is then run through the names pipeline (Devanagari names, glossary),
the pronunciation dictionary and the real Sarvam voice at the chosen pace, 8 kHz, and joined
into ONE wav with a pause (default 1.8 s) wherever the salon would speak.
"""

from __future__ import annotations

import asyncio
import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from friday.core.clock import FakeClock
from friday.core.models import Language
from friday.playbooks.dryrun import PersonaDef, PersonaFile, run_persona
from friday.playbooks.model import PlaybookError, get_playbook
from friday.playbooks.select import playbook_test_brief

BRANCHES = {
    "book": ("free", "busy_then_fallback"),
    "quote_only": ("quote",),
}


@dataclass
class PreviewResult:
    wav_path: Path
    lines: list[str]
    outcome: str
    seconds: float


def _persona(mode: str, branch: str) -> PersonaDef:
    replies: dict[str, Any] = {"s3_ask": "Haircut 400 rupaye lagega"}
    if mode == "book":
        if branch == "busy_then_fallback":
            replies["s2_ask"] = "Aaj to full hai"
            replies["s2f_ask"] = "Haan ji, ho jayega"
        else:
            replies["s2_ask"] = "Haan ji, ho jayega"
    return PersonaDef(id=f"preview_{mode}_{branch}", greeting="Hello?", replies=replies)


def _silence(sample_rate: int, seconds: float) -> bytes:
    return b"\x00\x00" * int(sample_rate * seconds)


def join_pcm_wav(clips: list[bytes], silence_s: float) -> tuple[bytes, int]:
    """WAV clips -> one mono 16-bit WAV with ``silence_s`` between them."""
    pcms: list[bytes] = []
    rate = 8000
    for data in clips:
        with wave.open(io.BytesIO(data)) as w:
            rate = w.getframerate()
            pcms.append(w.readframes(w.getnframes()))
    gap = _silence(rate, silence_s)
    body = gap.join(pcms)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(body)
    return buf.getvalue(), rate


async def friday_lines(
    *,
    mode: str,
    branch: str | None,
    business: str,
    user: str,
    services: str,
    when: str | None,
    fallback_when: str | None,
    budget: int,
    honorific: str,
    speller: Any,
    playbook: str = "salon_booking",
    directory: Path | None = None,
    persona: str | None = None,
    extra: dict[str, str] | None = None,
) -> tuple[list[str], str]:
    """(what Friday says, in order; the playbook outcome) for the chosen branch."""
    pb0 = get_playbook(playbook, directory)
    if pb0.archetype:  # a vendor archetype: the branch is a persona of its own personas file
        return await _archetype_lines(
            pb0, directory=directory, persona=persona or branch, mode=mode, business=business,
            user=user, services=services, when=when, fallback_when=fallback_when, budget=budget,
            honorific=honorific, speller=speller, extra=extra or {},
        )
    services = services or "haircut"
    mode = mode.replace("-", "_")
    if mode not in BRANCHES:
        raise PlaybookError([f"--mode must be book or quote_only (got '{mode}')"], playbook)
    branch = branch or BRANCHES[mode][0]
    if branch not in BRANCHES[mode]:
        raise PlaybookError([f"--branch for {mode} must be one of {BRANCHES[mode]}"], playbook)
    if branch == "busy_then_fallback" and not fallback_when:
        raise PlaybookError(["--branch busy_then_fallback needs --fallback-when"], playbook)
    pb = pb0
    brief = playbook_test_brief(
        playbook,
        to="+918040000001",
        user_first_name=user,
        max_seconds=180,
        from_number=None,
        service=None,
        services=services,
        date_window=when,
        budget_inr=budget,
        salon_name=business,
        honorific=honorific,
        book_now=(mode == "book"),
        fallback_when=fallback_when if mode == "book" else None,
        name_speller=speller,
        now=FakeClock().now(),
    )
    persona = _persona(mode, branch)
    pf = PersonaFile(version=1, playbook=pb.id, personas=[persona])
    score = await run_persona(pb, pf, persona, brief=brief)
    lines = [t for sp, t in score.transcript if sp == "friday" and t]
    return lines, score.outcome


async def _archetype_lines(
    pb: Any,
    *,
    directory: Path | None,
    persona: str | None,
    mode: str,
    business: str,
    user: str,
    services: str | None,
    when: str | None,
    fallback_when: str | None,
    budget: int,
    honorific: str,
    speller: Any,
    extra: dict[str, str],
) -> tuple[list[str], str]:
    """Vendor archetype preview: play the chosen preview persona (default preview_quote /
    preview_book) with the founder's own names, services and category inputs."""
    from friday.playbooks.dryrun import build_brief, load_personas

    mode = mode.replace("-", "_")
    pf = load_personas(pb.id, directory)
    wanted = persona or ("preview_book" if mode == "book" else "preview_quote")
    base = next((p for p in pf.personas if p.id == wanted), None)
    if base is None:
        ids = [p.id for p in pf.personas if p.id.startswith("preview_")]
        raise PlaybookError([f"no preview persona '{wanted}' (have: {ids})"], pb.id)
    cfg: dict[str, Any] = {**pf.brief, **base.brief}
    cfg.update(
        user_first_name=user, business_name=business, honorific=honorific,
        user_spoken=speller.spoken(user), business_name_spoken=speller.spoken(business),
    )
    if services:
        cfg["services"] = services
    if when:
        cfg["date_window"] = when
    if fallback_when:
        cfg["fallback_when"] = fallback_when
    if mode == "book" or cfg.get("delegation_max_price"):
        cfg["delegation_max_price"] = cfg.get("delegation_max_price") or budget
    cfg.update(extra)
    persona_def = base.model_copy(update={"brief": cfg, "id": f"preview_{wanted}"})
    pf2 = pf.model_copy(update={"brief": {}})
    brief = build_brief(pb, pf2, persona_def)
    score = await run_persona(pb, pf2, persona_def, brief=brief)
    lines = [t for sp, t in score.transcript if sp == "friday" and t]
    return lines, score.outcome


async def render_preview(
    *,
    tts: Any,
    voice: Any,
    out_dir: Path,
    silence_s: float = 1.8,
    **kw: Any,
) -> PreviewResult:
    lines, outcome = await friday_lines(**kw)
    clips = []
    for text in lines:
        clip = await tts.synthesize(text, Language.HINGLISH, voice=voice)
        clips.append(clip.data)
    wav, rate = join_pcm_wav(clips, silence_s)
    mode = kw["mode"].replace("-", "_")
    branch = kw.get("persona") or kw.get("branch") or BRANCHES[mode][0]
    path = out_dir / f"preview_{mode}_{branch}.wav"

    def write() -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wav)
        path.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    await asyncio.to_thread(write)
    seconds = len(wav) / (2 * rate)
    return PreviewResult(path, lines, outcome, seconds)
