"""The per-call human-voice layer: one object the call session talks to.

Every element is gated by its own switch (``Settings.human_*``). With all of them off ``shape`` returns
the text unchanged and every other method is a cheap no-op, so production behaviour is the old one.
Safety: disclosure, stop and "are you AI?" lines are never shortened or reworded (``PROTECTED``), and
no element can say or imply that Friday is a person.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from friday.human import metrics as hm
from friday.human.backchannel import BackchannelEngine
from friday.human.listener import BASE_PACE, ListenerModel
from friday.human.mood import MoodAdapter
from friday.human.noise import NoiseGate, NoiseTracker
from friday.human.numbers import speak_numbers
from friday.human.pauses import PausePlanner
from friday.human.prosody import apply as apply_prosody
from friday.human.resume import is_acknowledgement, unfinished, with_connector
from friday.human.variants import VariantPicker

PROTECTED = re.compile(
    r"\b(virtual assistant|ai assistant|AI)\b|असिस्टेंट|do not call|call nahi karungi|no longer call", re.I
)
_ELDER = {"mother", "father", "mummy", "papa", "mom", "dad", "dada", "dadi", "nana", "nani", "elder",
          "grandmother", "grandfather", "maa", "baba", "uncle", "aunty"}
PACE_MIN_MULT = 0.85
PACE_MAX_MULT = 1.10


@dataclass
class Shaped:
    text: str
    pace_mult: float = 1.0
    pause_ms: int = 0
    kind: str = "plain"


def seed_for(call_id: str, task_id: str = "") -> str:
    return hashlib.sha256(f"{call_id}|{task_id}".encode()).hexdigest()[:16]


class HumanLayer:
    def __init__(self, settings: Any, seed: str, *, elder: bool = False, call_id: str = "") -> None:
        g = lambda n: bool(getattr(settings, n, False))  # noqa: E731
        self.on_numbers, self.on_prosody = g("human_numbers"), g("human_prosody")
        self.on_variants, self.on_mirror = g("human_variants"), g("human_mirror")
        self.on_mood, self.on_match = g("human_mood"), g("human_match_listener")
        self.on_pauses, self.on_bc = g("human_pauses"), g("human_backchannels")
        self.on_resume, self.on_noise = g("human_resume"), g("human_noise_adapt")
        self.on_metrics = g("human_metrics")
        self.seed = seed
        self.picker = VariantPicker(seed, mirror=self.on_mirror, enabled=self.on_variants)
        self.mood = MoodAdapter()
        self.listener = ListenerModel()
        self.pauses = PausePlanner(seed)
        self.backchannel = BackchannelEngine(seed, enabled=self.on_bc, allowed=not elder)
        self.noise = NoiseTracker()
        self.gate = NoiseGate()
        self.metrics = hm.CallHumanMetrics(call_id=call_id)
        self.metrics.switches_on = [n for n in (
            "human_numbers", "human_prosody", "human_variants", "human_mirror", "human_mood",
            "human_match_listener", "human_pauses", "human_backchannels", "human_resume",
            "human_noise_adapt") if g(n)]
        self.last_callee_text = ""
        self._paces: list[float] = []
        self.pending_resume: str | None = None

    @classmethod
    def from_settings(cls, settings: Any, *, call_id: str, task_id: str = "", relation: str | None = None) -> HumanLayer:
        elder = bool(relation) and any(w in (relation or "").lower() for w in _ELDER)
        return cls(settings, seed_for(call_id, task_id), elder=elder, call_id=call_id)

    @property
    def any_audible(self) -> bool:
        return any((self.on_numbers, self.on_prosody, self.on_variants, self.on_mirror, self.on_mood,
                    self.on_match, self.on_pauses, self.on_bc))

    # -------------------------------------------------------------------- hearing
    def observe_callee(self, text: str | None, duration_s: float | None = None) -> None:
        t = (text or "").strip()
        if not t:
            return
        self.last_callee_text = t
        self.picker.observe_callee(t)
        self.mood.observe(t)
        self.listener.observe(t, duration_s)
        if hm.asks_if_robot(t):
            self.metrics.robot_asked += 1

    # -------------------------------------------------------------------- speaking
    def shape(self, text: str, language: str = "hinglish", *, name: str = "", gap_ms: float = 0.0,
              first_turn: bool = False) -> Shaped:
        if not text or (not self.any_audible):
            return Shaped(text)
        protected = bool(PROTECTED.search(text))
        out = text
        if self.on_variants or self.on_mirror:
            rep = self.picker.replacement_for(out, name)
            if rep:
                out = rep
        if not protected:
            if self.on_mood and self.mood.active:
                if self.mood.needs_apology() and not first_turn:
                    self.mood.apologised = True
                    out = f"{self.picker.pick('mood.apology', language)} {self.mood.adapt(out)}"
                else:
                    out = self.mood.adapt(out)
            if self.on_match:
                out = self.listener.adapt(out)
        if self.on_numbers:
            out = speak_numbers(out, language)
        mult, kind = 1.0, "plain"
        if self.on_prosody:
            out, hint = apply_prosody(out)
            mult, kind = hint.rate_mult, hint.kind
        if self.on_match:
            mult *= self.listener.pace() / BASE_PACE
        mult = max(PACE_MIN_MULT, min(PACE_MAX_MULT, round(mult, 3)))
        self._paces.append(mult)
        pause = 0
        if self.on_pauses and not protected and not first_turn:
            pause = self.pauses.plan(our_line=out, callee_text=self.last_callee_text, gap_so_far_ms=gap_ms)
        return Shaped(out, mult, pause, kind)

    # -------------------------------------------------------------------- interruption resume
    def note_interrupted(self, full_text: str, sent_parts: int) -> None:
        if self.on_resume:
            self.pending_resume = unfinished(full_text, sent_parts)

    def take_resume(self, callee_text: str | None, language: str = "hinglish") -> str | None:
        """The text to speak instead of a new policy turn, only if the other side merely said 'go on'."""
        rest, self.pending_resume = self.pending_resume, None
        if not rest or not is_acknowledgement(callee_text):
            return None
        connector = self.picker.pick("resume.connector", language) if self.on_variants else None
        self.metrics.resumes += 1
        return with_connector(rest, connector)

    # -------------------------------------------------------------------- wrap up
    def finish(self, *, hung_up_by_callee: bool, length_s: float, answered: bool = True) -> hm.CallHumanMetrics:
        m = self.metrics
        m.answered = answered
        m.backchannels = self.backchannel.count
        m.mood_events = self.mood.events
        m.pauses_used = len(self.pauses.log)
        m.noise_repeat_asks = self.gate.asked
        summ = self.noise.summary()
        m.noise_class, m.snr_db, m.noise_rms = str(summ["noise_class"]), summ["snr_db"], summ["noise_rms"]  # type: ignore[assignment]
        m.listener_style = self.listener.style()
        m.pace_avg = round(sum(self._paces) / len(self._paces) * BASE_PACE, 3) if self._paces else None
        return hm.finish(m, hung_up_by_callee=hung_up_by_callee, length_s=length_s)
