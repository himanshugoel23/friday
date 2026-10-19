# ruff: noqa: E501
"""Simulated callee side: a scripted telephony port with a simulated clock. No network, no audio."""

from __future__ import annotations

from dataclasses import dataclass, field

from friday.liveagent.contracts import CallLanguage
from friday.liveagent.ports import CallDropped, HeardUtterance


class SimClock:
    """Simulated seconds. Speaking, listening and the user's reply time all advance it."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += max(0.0, s)


@dataclass
class Utter:
    """One thing the callee side produces. ``text`` maps language -> words (or a plain string)."""

    text: dict[str, str] | str = ""
    audio_class: str = "human"
    duration_s: float = 2.0  # how long it plays / how long the callee talks
    confidence: float | None = None
    drop: bool = False  # the line drops instead of this utterance

    def words(self, lang: CallLanguage) -> str:
        if isinstance(self.text, str):
            return self.text
        return self.text.get(lang.value) or self.text.get("hinglish") or ""


def U(hinglish: str, hi: str | None = None, en: str | None = None, **kw: object) -> Utter:
    """A human utterance in the three languages (missing ones fall back to Hinglish)."""
    return Utter(text={"hinglish": hinglish, "hi": hi or hinglish, "en": en or hinglish}, **kw)  # type: ignore[arg-type]


def MUSIC(seconds: float = 30.0) -> Utter:
    return Utter(text="", audio_class="hold_music", duration_s=seconds)


def SILENCE(seconds: float = 5.0) -> Utter:
    return Utter(text="", audio_class="silence", duration_s=seconds)


DROP = Utter(drop=True)


class SimTelephony:
    """Plays ``script`` to the engine. After the script ends: ``tail`` = silence | drop | repeat."""

    def __init__(
        self,
        script: list[Utter],
        lang: CallLanguage,
        clock: SimClock,
        *,
        tail: str = "silence",
        speech_chars_per_s: float = 14.0,
    ) -> None:
        self.script = list(script)
        self.lang = lang
        self.clock = clock
        self.tail = tail
        self.rate = speech_chars_per_s
        self.spoken: list[tuple[str, CallLanguage, float]] = []
        self.dtmf: list[str] = []
        self.hung_up = False
        self._i = 0
        self._last: Utter | None = None

    async def speak(self, text: str, language: CallLanguage) -> None:
        if self.hung_up:
            raise CallDropped("speak after hangup")
        self.clock.advance(len(text) / self.rate)
        self.spoken.append((text, language, self.clock.now()))

    async def listen(self, timeout_s: float) -> HeardUtterance | None:
        if self.hung_up:
            raise CallDropped("listen after hangup")
        if self._i < len(self.script):
            u = self.script[self._i]
            self._i += 1
        elif self.tail == "drop":
            raise CallDropped("line dropped")
        elif self.tail == "repeat" and self._last is not None:
            u = self._last
        else:
            self.clock.advance(timeout_s)
            return None
        if u.drop:
            raise CallDropped("line dropped")
        self._last = u
        self.clock.advance(u.duration_s)
        return HeardUtterance(
            text=u.words(self.lang),
            language=self.lang.value,
            confidence=u.confidence,
            audio_class=u.audio_class,
            duration_s=u.duration_s,
        )

    async def send_dtmf(self, digits: str) -> None:
        self.dtmf.append(digits)

    async def hangup(self) -> None:
        self.hung_up = True


@dataclass
class FakeUserChannel:
    """The 'ask the user' hook. ``answer=None`` means the user does not reply in time."""

    answer: str | None = None
    delay_s: float = 10.0
    clock: SimClock | None = None
    asked: list[str] = field(default_factory=list)

    async def ask_user(self, question: str, *, timeout_s: float) -> str | None:
        self.asked.append(question)
        if self.clock is not None:
            self.clock.advance(
                min(self.delay_s, timeout_s) if self.answer is not None else timeout_s
            )
        if self.answer is not None and self.delay_s <= timeout_s:
            return self.answer
        return None
