# ruff: noqa: E501
"""Deterministic latency simulator: reply gap before / after the three latency features.

No network, no sleeping: a VIRTUAL-TIME event loop (time jumps to the next timer), fake STT / model
/ TTS with configurable delays, and the REAL components under test: ``PlaybookPolicy`` (rules,
classifier, ``Speculator``) for scripted turns and ``FridayBrain.next_call_action_streamed`` /
``stream_to_voice`` for free-form turns. The same inputs always give the same numbers.

"Reply gap" = caller stopped speaking -> first audio of Friday's reply is queued (the number the
live ``reply gap`` log line reports). Two speech-to-text sources are modelled for a scripted turn:

  rest    (today's default)  t=0 the caller stops; t=340 ms the early REST transcription starts and
          its text is ready ``stt_ms`` later (the speculation may start there); the utterance is
          committed at max(end-silence wait, that), the early text being reused as the final text.
  stream  (FRIDAY_VOICE_STREAM_STT)  the last partial exists at ``partial_ms``; a partial unchanged
          for ``spec_stable_ms`` starts the speculation; a SHORT answer (<= 6 words) is committed
          ``stable_ms`` after the partial, a longer one waits for the server's final (``stream_final_ms``).

After the commit: understanding = rules (~0) | classifier (~0) | one model call (``model_ms``),
then ``tts_first_ms`` (0 = pre-rendered / cached line).

The mix of turn kinds below is an ASSUMPTION for illustration, not a measurement of real calls; the
per-kind numbers are what the code does given the delays you configure. Real vendor delays, real STT
partial quality and real Vobiz audio are NOT measured here (docs/LATENCY.md says so).

Run: ``uv run python -m friday.latency.simulator``
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from friday.core.models import AudioClass, Speaker, Transcript
from friday.latency.stream_adapters import FakeStreamingLLM, json_chunks


# --------------------------------------------------------------------------- virtual time
class VirtualTimeLoop(asyncio.SelectorEventLoop):
    """An event loop whose clock jumps to the next scheduled timer instead of waiting."""

    def __init__(self) -> None:
        super().__init__()
        self._vt = 0.0

    def time(self) -> float:
        return self._vt

    def _run_once(self) -> None:
        sched = self._scheduled  # type: ignore[attr-defined]
        if not self._ready and sched:  # type: ignore[attr-defined]
            self._vt = max(self._vt, sched[0]._when)
        super()._run_once()  # type: ignore[misc]


def run_virtual(coro: Awaitable[Any]) -> Any:
    loop = VirtualTimeLoop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --------------------------------------------------------------------------- configuration
@dataclass(frozen=True)
class Timing:
    """All in milliseconds (the defaults are the numbers in docs/LATENCY.md; change them to taste)."""

    end_silence_ms: int = 650  # short answers (FRIDAY_VOICE_SHORT_END_SILENCE_MS)
    early_stt_at_ms: int = 340  # SarvamCallLeg.EARLY_STT_SILENCE_MS
    stt_ms: int = 500  # Sarvam REST on the early snapshot
    model_ms: int = 650  # the tiny call-turn understanding request
    tts_first_ms: int = 0  # 0 = cached / pre-rendered scripted line
    long_end_silence_ms: int = 900  # end-of-speech wait for answers longer than ~1.5 s
    short_max_words: int = 6  # FRIDAY_VOICE_EARLY_COMMIT_WORDS
    partial_ms: int = 350  # streaming STT: the final partial text exists this long after the stop
    stable_ms: int = 220  # FRIDAY_VOICE_STREAM_STT_STABLE_MS
    spec_stable_ms: int = 150  # SarvamCallLeg.SPECULATE_STABLE_MS
    stream_final_ms: int = 850  # streaming STT: the server's final transcript
    # free-form (model-written) turns
    ttft_ms: int = 450  # time to first token
    tokens_per_s: int = 100
    chars_per_token: int = 4
    freeform_tts_first_ms: int = 260  # uncached line through Sarvam streaming TTS


@dataclass(frozen=True)
class ScriptedCase:
    name: str
    early_text: str  # what the early transcription (and a stable partial) says
    final_text: str  # what the committed utterance says
    weight: float = 1.0  # share of turns of this kind in the ASSUMED mix
    caller_continues: bool = False  # the caller speaks again after the early text: guess cancelled


@dataclass
class TurnOutcome:
    gap_ms: float
    path: str  # rules | model | speculative_hit | speculative_miss | classifier
    model_calls: int


@dataclass
class ScriptedRow:
    case: ScriptedCase
    baseline: TurnOutcome
    speculative: TurnOutcome
    classifier: TurnOutcome
    both: TurnOutcome


@dataclass
class FreeFormRow:
    name: str
    sentences: int
    baseline_gap_ms: float
    streamed_gap_ms: float
    first_sentence_ms: float
    fell_back: bool = False


@dataclass
class Report:
    timing: Timing
    scripted_by_mode: dict[str, list[ScriptedRow]] = field(default_factory=dict)
    freeform: list[FreeFormRow] = field(default_factory=list)

    @property
    def scripted(self) -> list[ScriptedRow]:  # the default (REST) source
        return self.scripted_by_mode.get("rest") or next(iter(self.scripted_by_mode.values()), [])

    # ---- aggregates over the assumed mix
    def mean(self, which: str, mode: str = "rest") -> float:
        rows = self.scripted_by_mode[mode]
        tot = sum(r.case.weight for r in rows) or 1.0
        return sum(getattr(r, which).gap_ms * r.case.weight for r in rows) / tot

    def hit_rate(self, mode: str = "rest") -> float:
        """Of the turns where a speculative model call was started: the share that was reused."""
        rows = self.scripted_by_mode[mode]
        started = [r for r in rows if r.speculative.path in ("speculative_hit", "speculative_miss")]
        hits = [r for r in started if r.speculative.path == "speculative_hit"]
        return len(hits) / len(started) if started else 0.0

    def extra_model_calls_per_100(self, mode: str = "rest") -> float:
        """Model calls the speculation added (wasted guesses) per 100 turns of the assumed mix."""
        rows = self.scripted_by_mode[mode]
        tot = sum(r.case.weight for r in rows) or 1.0
        return 100 * sum(r.case.weight * (r.speculative.model_calls - r.baseline.model_calls)
                         for r in rows) / tot

    def hit_rate_of_all_turns(self, mode: str = "rest") -> float:
        rows = self.scripted_by_mode[mode]
        tot = sum(r.case.weight for r in rows) or 1.0
        return sum(r.case.weight for r in rows if r.speculative.path == "speculative_hit") / tot

    def format(self) -> str:
        t = self.timing
        lines = [
            "Reply gap = caller stopped speaking -> first audio queued (virtual clock, fake STT/model/TTS)",
            f"timing: end-silence {t.end_silence_ms}/{t.long_end_silence_ms} ms, early STT at {t.early_stt_at_ms} ms + {t.stt_ms} ms, "
            f"stream partial at {t.partial_ms} ms (+{t.spec_stable_ms} ms stable), model {t.model_ms} ms, tts first audio {t.tts_first_ms} ms",
        ]
        for mode, rows in self.scripted_by_mode.items():
            lines += [
                "",
                f"SCRIPTED TURNS, speech-to-text source: {mode.upper()} (playbook: rules, then classifier, then one model call)",
                f"{'case':<34}{'weight':>7}{'baseline':>10}{'specul.':>9}{'saved':>7}{'classif.':>10}{'both':>7}  path(specul./classif.)",
            ]
            for r in rows:
                lines.append(
                    f"{r.case.name:<34}{r.case.weight:>7.2f}{r.baseline.gap_ms:>9.0f} {r.speculative.gap_ms:>8.0f} "
                    f"{r.baseline.gap_ms - r.speculative.gap_ms:>6.0f} {r.classifier.gap_ms:>9.0f} {r.both.gap_ms:>6.0f}  "
                    f"{r.speculative.path}/{r.classifier.path}"
                )
            lines += [
                f"{'mean over the ASSUMED mix':<34}{'':>7}{self.mean('baseline', mode):>9.0f} {self.mean('speculative', mode):>8.0f} "
                f"{self.mean('baseline', mode) - self.mean('speculative', mode):>6.0f} {self.mean('classifier', mode):>9.0f} "
                f"{self.mean('both', mode):>6.0f}",
                f"speculative: guess reused on {self.hit_rate(mode) * 100:.0f}% of the turns where one was started, "
                f"{self.hit_rate_of_all_turns(mode) * 100:.0f}% of all turns; "
                f"extra (wasted) model calls: {self.extra_model_calls_per_100(mode):.0f} per 100 turns",
            ]
        lines += [
            "(the mix of turn kinds is an assumption; real calls will differ)",
            "",
            "FREE-FORM TURNS (model writes the reply; streamed into the voice vs whole reply)",
            f"{'case':<34}{'sent.':>6}{'baseline':>10}{'streamed':>10}{'saved':>7}{'1st sentence at':>17}",
        ]
        for f in self.freeform:
            lines.append(
                f"{f.name:<34}{f.sentences:>6}{f.baseline_gap_ms:>9.0f} {f.streamed_gap_ms:>9.0f} "
                f"{f.baseline_gap_ms - f.streamed_gap_ms:>6.0f} {f.first_sentence_ms:>16.0f}"
                + ("  (fell back to the normal path)" if f.fell_back else "")
            )
        return "\n".join(lines)


# --------------------------------------------------------------------------- scripted turns
class SimModel:
    """Fake ``Understander``: answers after ``delay_ms`` of (virtual) time; counts calls."""

    def __init__(self, delay_ms: float, intent: str = "YES") -> None:
        self.delay_ms, self.intent, self.calls = delay_ms, intent, 0
        self.llm_calls = 0

    async def understand(self, **kw: Any) -> Any:
        from friday.playbooks.understand import Understanding

        self.calls += 1
        self.llm_calls += 1
        await asyncio.sleep(self.delay_ms / 1000)
        return Understanding(intent=self.intent, confident=True)


_T0 = datetime(2026, 10, 7, 4, 30)


async def _waiting_policy(policy: Any) -> tuple[Any, Transcript]:
    """A salon price-check call that has just asked its first question and waits for the reply."""
    from friday.playbooks.dryrun import build_brief, load_personas
    from friday.playbooks.model import get_playbook

    pb = get_playbook("salon_booking")
    pf = load_personas("salon_booking")
    brief = build_brief(pb, pf, pf.personas[0])
    tr = Transcript()
    tr.add(Speaker.CALLEE, "Hello, salon.", at=_T0, audio_class=AudioClass.HUMAN)
    tr.add(Speaker.FRIDAY, brief.disclosure(), at=_T0)
    act = await policy.next_call_action(brief, tr, [])
    if act.text:
        tr.add(Speaker.FRIDAY, act.text, at=_T0)
    tr.add(Speaker.CALLEE, "Haan boliye", at=_T0, audio_class=AudioClass.HUMAN)
    act = await policy.next_call_action(brief, tr, [])
    if act.text:
        tr.add(Speaker.FRIDAY, act.text, at=_T0)
    return brief, tr


def timeline_ms(case: ScriptedCase, t: Timing, mode: str) -> tuple[float | None, float]:
    """(when the speculation can start or None, when the utterance is committed), ms after the stop."""
    short = len(case.final_text.split()) <= t.short_max_words
    if mode == "stream":
        spec = float(t.partial_ms + t.spec_stable_ms)
        commit = float(t.partial_ms + t.stable_ms if short else t.stream_final_ms)
        return (spec if spec < commit else None), commit
    spec = float(t.early_stt_at_ms + t.stt_ms)
    commit = float(max(t.end_silence_ms if short else t.long_end_silence_ms, spec))
    return (spec if spec < commit else None), commit


async def _scripted_turn(
    case: ScriptedCase, t: Timing, mode: str, *, speculative: bool, classifier: Any | None
) -> TurnOutcome:
    from friday.playbooks.engine import PlaybookPolicy

    model = SimModel(t.model_ms)
    policy = PlaybookPolicy(
        understander=model, llm_mode="auto", speculative=speculative, classifier=classifier,
        classifier_threshold=0.9,
    )
    brief, tr = await _waiting_policy(policy)
    loop = asyncio.get_running_loop()
    t0 = loop.time()  # the caller stops speaking
    spec_at, commit_at = timeline_ms(case, t, mode)

    if spec_at is not None:
        await asyncio.sleep(spec_at / 1000)
        if speculative:
            policy.speculate(brief, tr, case.early_text)
        if case.caller_continues:  # more speech arrives before the pause ends: the guess is dropped
            await asyncio.sleep(0.05)
            policy.cancel_speculation(tr, "caller kept talking")
    await asyncio.sleep(max(0.0, commit_at / 1000 - (loop.time() - t0)))
    tr.add(Speaker.CALLEE, case.final_text, at=_T0, audio_class=AudioClass.HUMAN)
    await policy.next_call_action(brief, tr, [])
    gap = round((loop.time() - t0) * 1000 + t.tts_first_ms, 3)
    s = policy.stats
    state = policy.state_of(tr)
    cancelled = bool(state is not None and state.speculator is not None
                     and state.speculator.stats.cancelled)
    if s["classifier_hit"]:
        path = "classifier"
    elif s["speculative_hit"]:
        path = "speculative_hit"
    elif cancelled:
        path = "speculative_cancelled"
    elif model.calls == 0:
        path = "rules"
    elif s["speculative_miss"] or (speculative and model.calls > 1):
        path = "speculative_miss"
    else:
        path = "model"
    return TurnOutcome(gap, path, model.calls)


def default_scripted_cases() -> list[ScriptedCase]:
    """Texts chosen from the real rules / classifier: one the rules are sure of, unsure ones the
    classifier can and cannot answer, and the speculative miss / cancel situations."""
    return [
        ScriptedCase("rules sure (haan ji bataiye)", "haan ji bataiye", "haan ji bataiye", 0.45),
        ScriptedCase("rules unsure, early text = final", "haan toh phir", "haan toh phir", 0.20),
        ScriptedCase("rules unsure, classifier knows", "parking hai kya aapke paas",
                     "parking hai kya aapke paas", 0.10),
        ScriptedCase("text drifted (guess wasted)", "haan toh phir", "haan toh phir kal dekhte hain", 0.10),
        ScriptedCase("caller kept talking (cancelled)", "haan toh phir", "haan toh phir kal dekhte hain", 0.05, True),
        ScriptedCase("rules unsure, long answer", "achha toh phir kya karna hai aapko",
                     "achha toh phir kya karna hai aapko", 0.10),
    ]


async def _scripted_row(case: ScriptedCase, t: Timing, mode: str, clf: Any | None) -> ScriptedRow:
    return ScriptedRow(
        case,
        await _scripted_turn(case, t, mode, speculative=False, classifier=None),
        await _scripted_turn(case, t, mode, speculative=True, classifier=None),
        await _scripted_turn(case, t, mode, speculative=False, classifier=clf),
        await _scripted_turn(case, t, mode, speculative=True, classifier=clf),
    )


# --------------------------------------------------------------------------- free-form turns
FREEFORM_REPLIES: dict[str, list[str]] = {
    "1 short sentence": ["Ji, main Rahul ji ke liye haircut ka rate poochh rahi hoon."],
    "2 sentences": [
        "Ji, main Rahul ji ke liye haircut ka rate poochh rahi hoon.",
        "Kya aap kal shaam ka slot bata sakte hain?",
    ],
    "3 sentences": [
        "Ji, main Rahul ji ke liye haircut ka rate poochh rahi hoon.",
        "Kya aap kal shaam ka slot bata sakte hain?",
        "Pakka time main unse poochh kar bataungi.",
    ],
}


async def _freeform_row(name: str, sentences: list[str], t: Timing) -> FreeFormRow:
    from friday.brain.service import FridayBrain
    from friday.core.config import Settings
    from friday.core.models import CallBrief, ContactTarget, TargetKind, TaskType

    raw = json.dumps({"type": "say", "text": " ".join(sentences), "language": "hinglish",
                      "commits_booking": False})
    per_char_s = 1.0 / (t.tokens_per_s * t.chars_per_token)
    chunk = 5
    stream = FakeStreamingLLM(json_chunks(raw, chunk), delay_s=chunk * per_char_s,
                              first_delay_s=t.ttft_ms / 1000)
    settings = Settings(_env_file=None, mode="simulator", env="test", llm_stream_to_tts=True)
    brain = FridayBrain(_NoCompleteLLM(), settings)
    brain.streaming_llm = stream
    brief = CallBrief(
        task_id="sim", requester_user_id="u", task_type=TaskType.ENQUIRY, goal="Ask a haircut price",
        on_behalf_of="Rahul",
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Looks Salon", phone="+918040000001"),
    )
    tr = Transcript()
    tr.add(Speaker.FRIDAY, "Hello, main Friday.", at=_T0)
    tr.add(Speaker.CALLEE, "haan ji boliye", at=_T0)
    loop = asyncio.get_running_loop()
    commit_at = max(t.end_silence_ms, t.early_stt_at_ms + t.stt_ms)
    first_audio: list[float] = []

    async def speak(_s: str) -> None:
        if not first_audio:
            first_audio.append(loop.time())
        await asyncio.sleep(0.01)

    await asyncio.sleep(commit_at / 1000)  # the utterance is committed
    t_commit = loop.time()
    turn = await brain.next_call_action_streamed(brief, tr, [], speak=speak)
    streamed_gap = commit_at + ((first_audio[0] - t_commit) * 1000 if first_audio else 0.0) + t.freeform_tts_first_ms
    first_sentence = turn.result.first_sentence_ms if turn.result and turn.result.first_sentence_ms else 0.0
    # whole-reply path: wait for the last token (same stream, no early speech), then speak
    total_model_s = t.ttft_ms / 1000 + (len(raw) - 1) // chunk * chunk * per_char_s
    baseline_gap = commit_at + total_model_s * 1000 + t.freeform_tts_first_ms
    return FreeFormRow(name, len(sentences), round(baseline_gap, 3), round(streamed_gap, 3),
                       round(first_sentence, 3), turn.fell_back)


class _NoCompleteLLM:
    """The simulator never uses the non-streaming client (a call would mean the fallback ran)."""

    provider = "sim"

    async def complete(self, **kw: Any) -> Any:  # pragma: no cover - only if the stream failed
        raise RuntimeError("non-streaming call in the simulator")


# --------------------------------------------------------------------------- entry points
def run_benchmark(
    timing: Timing | None = None,
    cases: list[ScriptedCase] | None = None,
    classifier: Any | None = "active",
    modes: tuple[str, ...] = ("rest", "stream"),
) -> Report:
    """Run every scripted case four ways (baseline / speculative / classifier / both) and the
    free-form replies streamed vs whole. ``classifier="active"`` = the repo's gate-passed model."""
    t = timing or Timing()
    if classifier == "active":
        from friday.playbooks.classifier import load_active

        classifier = load_active()

    async def main() -> Report:
        rep = Report(t)
        for mode in modes:
            rep.scripted_by_mode[mode] = [
                await _scripted_row(c, t, mode, classifier) for c in cases or default_scripted_cases()
            ]
        for name, sents in FREEFORM_REPLIES.items():
            rep.freeform.append(await _freeform_row(name, sents, t))
        return rep

    return run_virtual(main())  # type: ignore[no-any-return]


def main(argv: list[str] | None = None) -> int:
    import argparse
    import logging

    ap = argparse.ArgumentParser(description="Reply-gap simulator (virtual clock, no network)")
    for f in ("end_silence_ms", "stt_ms", "model_ms", "tts_first_ms", "ttft_ms", "tokens_per_s"):
        ap.add_argument("--" + f.replace("_", "-"), type=int, default=getattr(Timing, f))
    ap.add_argument("--verbose", action="store_true", help="show the speculative / classifier log lines")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    t = Timing(**{k: v for k, v in vars(a).items() if k != "verbose"})
    print(run_benchmark(t).format())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
