"""The receptionist's conversation: fixed lines, deterministic understanding, a hard time limit.

The conversation reuses the live engine's ideas (a closed set of moves with fixed approved lines,
the TelephonyPort, "are you AI" answered truthfully) but is its own small state machine because the
live engine is built for calls Friday MAKES. The moves here are:

    greet+disclose -> ask (name / reason) -> read back briefly -> close
    side moves: AI answer, who, deflect (user info / connect me), promise refusal, secret refusal
    stops: abuse, wrong number, silence, "do not note this down", hang-up, 90 s limit

Hard rules (kept in code, not in a prompt):
* every spoken line is a fixed line from ``lines.py`` (dynamic parts: the caller's own name and a
  short excerpt of their own reason, both sanitised);
* nothing is promised or committed for the user: Friday only says she will pass the message on;
* nothing about the user (location, number, schedule, private facts) is ever said;
* a call-back number is only taken when the caller volunteers it (never asked for);
* stops the moment the caller hangs up (CallDropped); never longer than ``max_call_s`` (90 s).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from friday.liveagent.contracts import CallLanguage
from friday.liveagent.ports import CallDropped, TelephonyPort
from friday.receptionist import lines
from friday.receptionist.hear import Heard, Said, hear
from friday.receptionist.models import CallCapture, CallOutcomeKind, ReceptionistConfig
from friday.voice.text import redact_secrets

MAX_TURNS = 12
LISTEN_S = 7.0
WRAP_MARGIN_S = 30.0  # an utterance is <= 20 s (segmenter cap) + the closing line stays <= 90 s
EXCERPT_WORDS = 12
SNIPPET_CHARS = 240
REASON_CHARS = 300
UNNAMED = {"hinglish": "mere user", "hi": "मेरे यूज़र", "en": "my user"}
_SECRETISH = re.compile(r"\b(?:otp|pin|cvv|cvc|password|passcode|card)\b|\d{10,}", re.I)
_NAME_OK = re.compile(r"^[A-Za-zऀ-ॿ][A-Za-zऀ-ॿ .'-]{0,29}$")


class ReceptionistFlow:
    def __init__(
        self,
        port: TelephonyPort,
        cfg: ReceptionistConfig,
        *,
        generic: bool = False,
        now: Callable[[], float] = time.monotonic,
        max_call_s: float = 90.0,
        listen_s: float = LISTEN_S,
    ) -> None:
        self.port, self.cfg, self.generic = port, cfg, generic
        self.now, self.max_call_s, self.listen_s = now, float(max_call_s), listen_s
        self.lang = cfg.language if cfg.language in lines.LANGS else "hinglish"
        self.cap = CallCapture(language=self.lang)
        self.name: str | None = None
        self.reason: str = ""
        self.snippet: str = ""
        self.stage = "gather"  # gather | confirm
        self.expect: str | None = None  # name | reason
        self.silences = self.unclear = self.retakes = self.deflects = self.secrets = 0
        self.asked_name = self.asked_reason = 0
        self.spoken: list[tuple[str, str]] = []  # (line key, text) for tests and the simulator
        self._t0 = 0.0
        self.ended = False

    # ------------------------------------------------------------------ speaking
    def _user(self) -> str:
        return self.cfg.user_name.strip() or UNNAMED[self.lang]

    async def _say(self, key: str, **slots: str) -> None:
        if self.spoken and self.spoken[-1][0] == key and key not in {"unclear"}:
            return  # never the same line twice in a row
        if "user" in lines.required_slots(key):
            slots.setdefault("user", self._user())
        text = lines.say(key, self.lang, **slots)
        self.spoken.append((key, text))
        self.cap.transcript.append(("friday", text))
        await self.port.speak(text, CallLanguage(self.lang))

    def _leaks(self, text: str) -> bool:
        low = text.lower()
        return any(f.strip().lower() in low for f in self.cfg.private_facts if f.strip())

    def _excerpt(self) -> str | None:
        words = self.reason.split()[:EXCERPT_WORDS]
        text = " ".join(words)
        if not text or _SECRETISH.search(text) or self._leaks(text):
            return None
        return text

    # ------------------------------------------------------------------ main loop
    async def run(self) -> CallCapture:
        self._t0 = self.now()
        try:
            await self._say("greet.generic" if self.generic else "greet.intro")
            while self.cap.turns < MAX_TURNS and not self.ended:
                elapsed = self.now() - self._t0
                if elapsed >= self.max_call_s - WRAP_MARGIN_S:
                    await self._wrap_up()
                    break
                utt = await self.port.listen(self.listen_s)
                self.cap.turns += 1
                h = hear(utt, awaiting_confirm=self.stage == "confirm")
                self._mirror(h)
                if h.text:
                    self.cap.transcript.append(("caller", redact_secrets(h.text)))
                await self._handle(h)
            if not self.ended:  # turn cap reached
                await self._close()
        except CallDropped:
            self.ended = True
        finally:
            self.cap.duration_s = max(0.0, self.now() - self._t0)
        return self._finalize()

    def _mirror(self, h: Heard) -> None:
        if h.language == "en" and self.lang != "en":
            self.lang = "en"
        elif h.language in {"hi", "hinglish"} and self.lang == "en":
            self.lang = "hinglish"
        self.cap.language = self.lang

    # ------------------------------------------------------------------ one caller turn
    async def _handle(self, h: Heard) -> None:  # noqa: PLR0912
        if h.said != Said.SILENCE:
            self.silences = 0
        if h.said == Said.SILENCE:
            self.silences += 1
            if self.name or self.reason:
                await self._close()
            elif self.silences == 1:
                await self._say("silence.prompt")
            else:
                await self._say("silence.end")
                self._stop(CallOutcomeKind.NO_MESSAGE)
            return
        if h.said == Said.ABUSE:
            await self._say("abuse.end")
            self.reason = ""
            self.snippet = ""
            self._stop(CallOutcomeKind.ABUSE_ENDED)
            return
        if h.said == Said.WRONG_NUMBER:
            await self._say("wrong_number")
            self._stop(CallOutcomeKind.WRONG_NUMBER)
            return
        if h.said == Said.SECRET:
            self.secrets += 1
            self.cap.asked_secret = True
            self._add_snippet(h.text)
            await self._say("secret.refuse")
            if self.secrets >= 2:
                await self._close()
            else:
                await self._prompt_next()
            return
        self._absorb_identity(h)
        if h.said == Said.AI_QUESTION:
            self.cap.asked_if_ai = True
            await self._say("ai.answer.generic" if self.generic else "ai.answer")
            await self._prompt_next()
        elif h.said == Said.WHO:
            await self._say("greet.generic" if self.generic else "who")
            await self._prompt_next()
        elif h.said == Said.DECLINES_NOTES:
            self.cap.declined_notes = True
            self.reason = self.snippet = ""
            await self._say("close.declined_notes")
            self._stop(CallOutcomeKind.MESSAGE)
        elif h.said in {Said.WANTS_CONNECT, Said.WANTS_PROMISE, Said.ASKS_USER_INFO}:
            self.deflects += 1
            key = {
                Said.WANTS_CONNECT: "deflect.connect",
                Said.WANTS_PROMISE: "promise.refuse",
                Said.ASKS_USER_INFO: "deflect.user_info",
            }[h.said]
            await self._say(key)
            if self.deflects >= 3:
                await self._close()
            elif self.reason:
                await self._readback()
            else:
                await self._prompt_next()
        elif h.said == Said.YES:
            await self._close()
        elif h.said == Said.NO:
            if self.retakes < 1:
                self.retakes += 1
                self.reason = ""
                self.snippet = ""
                self.stage, self.expect = "gather", "reason"
                await self._say("retake")
            else:
                await self._close()
        else:
            await self._content(h)

    def _absorb_identity(self, h: Heard) -> None:
        if h.name and not self.name:
            self.name = self._safe_name(h.name)
        if h.callback_number and not self.cap.callback_number:
            self.cap.callback_number = h.callback_number

    @staticmethod
    def _safe_name(raw: str | None) -> str | None:
        if not raw:
            return None
        raw = raw.strip()
        return raw if _NAME_OK.match(raw) and not _SECRETISH.search(raw) else None

    async def _content(self, h: Heard) -> None:
        if self.stage == "confirm":  # something else instead of yes/no: it is more of the message
            self._add_reason(h.reason or h.text)
            self._add_snippet(h.text)
            await self._close()
            return
        words = h.text.split()
        if self.expect == "name" and not self.name and len(words) <= 3:
            self.name = self._safe_name(h.name or " ".join(words)) or self.name
            if not h.reason or h.reason == h.text:
                h = Heard(Said.CONTENT, h.text, name=self.name, reason=None, callback_number=h.callback_number)
        if self.expect == "reason" and not h.reason and h.text:
            h = Heard(Said.CONTENT, h.text, name=h.name, reason=h.text, callback_number=h.callback_number)
        if h.reason and not (self.name and h.reason.strip().lower() == self.name.lower()):
            self._add_reason(h.reason)
        self._add_snippet(h.text)
        if self.cap.callback_number and not (self.reason or self.name):
            await self._say("callback.noted")
        if self.reason:
            if not self.name and self.asked_name < 1 and not self.generic:
                self.asked_name += 1
                self.expect = "name"
                await self._say("ask.name")
            else:
                await self._readback()
        elif self.name:
            if self.asked_reason < 2:
                self.asked_reason += 1
                self.expect = "reason"
                await self._say("ask.reason_named", name=self.name)
            else:
                await self._close()
        else:
            self.unclear += 1
            if self.unclear > 2:
                await self._close()
            else:
                await self._say("unclear")

    def _add_reason(self, text: str) -> None:
        text = redact_secrets(text.strip())
        if text:
            self.reason = (self.reason + " " + text).strip()[:REASON_CHARS]

    def _add_snippet(self, text: str) -> None:
        if self.cap.declined_notes or not text:
            return
        self.snippet = (self.snippet + " " + redact_secrets(text.strip())).strip()[:SNIPPET_CHARS]

    async def _prompt_next(self) -> None:
        if not self.reason:
            if self.name and self.asked_reason < 2:
                self.asked_reason += 1
                self.expect = "reason"
                await self._say("ask.reason_named", name=self.name)
            elif self.asked_reason < 2:
                self.asked_reason += 1
                self.expect = "reason"
                await self._say("ask.reason")
            else:
                await self._close()
        elif not self.name and self.asked_name < 1 and not self.generic:
            self.asked_name += 1
            self.expect = "name"
            await self._say("ask.name")
        else:
            await self._readback()

    async def _readback(self) -> None:
        self.stage = "confirm"
        self.expect = None
        ex = self._excerpt()
        if ex and self.name and not self._leaks(self.name):
            await self._say("readback", name=self.name, reason=ex)
        else:
            await self._say("readback.generic")

    # ------------------------------------------------------------------ endings
    async def _wrap_up(self) -> None:
        if self.reason or self.name:
            await self._close()
        else:
            await self._say("timeout.wrapup")
            self._stop(CallOutcomeKind.NO_MESSAGE)

    async def _close(self) -> None:
        if self.generic:
            await self._say("unrouted.close" if (self.reason or self.name) else "close.no_details")
        elif self.reason:
            await self._say("close.message")
        else:
            await self._say("close.no_details")
        self._stop(CallOutcomeKind.UNROUTED if self.generic else CallOutcomeKind.MESSAGE)

    def _stop(self, outcome: CallOutcomeKind) -> None:
        self.ended = True
        self.cap.outcome = outcome

    def _finalize(self) -> CallCapture:
        cap = self.cap
        cap.caller_name = self.name
        cap.reason = self.reason or None
        cap.snippet = None if cap.declined_notes else (self.snippet or None)
        if cap.outcome not in {CallOutcomeKind.ABUSE_ENDED, CallOutcomeKind.WRONG_NUMBER}:
            had = bool(self.reason or self.name or cap.declined_notes or cap.callback_number or self.snippet)
            if not had:
                cap.outcome = CallOutcomeKind.NO_MESSAGE
            elif self.generic:
                cap.outcome = CallOutcomeKind.UNROUTED
            else:
                cap.outcome = CallOutcomeKind.MESSAGE
        return cap
