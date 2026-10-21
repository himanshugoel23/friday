# ruff: noqa: E501
"""Stream the model's reply into the voice: speak the first sentence while the rest is written.

Today a model-written reply is requested as one JSON object and spoken only when it is complete
(plus ~0.7-2 s of model time). With ``FRIDAY_LLM_STREAM_TO_TTS`` on, the reply is streamed:

    model tokens -> JsonFieldStream ("text" field) -> SentenceSplitter -> per-sentence guards
                 -> speak(sentence)            (the voice starts on sentence 1 while 2.. are written)

Rules that keep the safety of the whole-reply path:

* every sentence passes the same guards BEFORE it reaches the voice (the caller supplies ``check``;
  the brain uses ``guards.to_call_action`` on that one sentence: money promises, commitment
  wording, ungrounded prices / times, secrets / long numbers, "no repeated line"),
* the first failing sentence STOPS the stream (the model is cancelled), nothing after it is spoken,
  and the caller falls back to the safe fixed line the guard produced,
* a sentence equal to one of Friday's recent sentences, or to an earlier sentence of this reply,
  is a repeat and fails the same way,
* any stream error before the first sentence = the caller runs the old non-streaming path; after
  the first sentence the reply simply ends where it was cut (words are never replayed),
* speech starts only once ``type`` is known to be ``say`` (the schema writes ``type`` first); any
  other action type is not streamed at all.

Log lines (INFO), in the style of the ``reply gap`` lines::

    stream-to-tts first sentence 590 ms after the request (48 chars)
    stream-to-tts done: 2 sentences spoken, first at 590 ms, stream ended at 1480 ms
    stream-to-tts sentence blocked by guard (ungrounded number(s) ['450']); stopping
    stream-to-tts failed (ReadTimeout) after 0 sentences; falling back to the normal path
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from friday.core.logging import get_logger
from friday.latency.speculative import normalise_utterance

log = get_logger(__name__)

TERMINATORS = ".!?।"
_OPENERS = "\"'”’)]"


# --------------------------------------------------------------------------- the interface
class StreamingLLM(Protocol):
    """A chat model that can stream. ``stream`` yields text deltas as they are produced; the
    streams are the raw JSON text when ``json_schema`` is given. Raises on any failure."""

    def stream(
        self, *, system: str, messages: Sequence[Any], purpose: str = "call_turn",
        model: str | None = None, max_tokens: int = 1024, effort: Any = None,
        json_schema: dict | None = None,
    ) -> AsyncIterator[str]: ...


# --------------------------------------------------------------------------- sentences
class SentenceSplitter:
    """Incremental sentence / clause splitter for spoken Hinglish, Hindi and English.

    A sentence ends at ``. ! ? ।`` followed by white space (so ``10.30`` and ``Rs.400`` stay
    whole); ``? ! ।`` also end a sentence at the very end of the text so far. Fragments shorter
    than ``min_chars`` are merged into the next one ("Ji. Haan." is one piece). A piece that grows
    past ``clause_chars`` without a terminator is cut at its last comma / semicolon (0 = never).
    """

    def __init__(self, min_chars: int = 14, clause_chars: int = 90) -> None:
        self.min_chars = min_chars
        self.clause_chars = clause_chars
        self._buf = ""

    def feed(self, text: str) -> list[str]:
        self._buf += text
        return self._drain(final=False)

    def flush(self) -> list[str]:
        out = self._drain(final=True)
        rest = " ".join(self._buf.split())
        self._buf = ""
        if rest:
            out.append(rest)
        return out

    def _drain(self, *, final: bool) -> list[str]:
        out: list[str] = []
        while True:
            cut = self._find_cut(final)
            if cut is None:
                break
            piece, self._buf = self._buf[:cut], self._buf[cut:]
            piece = " ".join(piece.split())
            if piece:
                out.append(piece)
        return out

    def _find_cut(self, final: bool) -> int | None:
        buf = self._buf
        for i, ch in enumerate(buf):
            if ch not in TERMINATORS:
                continue
            j = i + 1
            while j < len(buf) and buf[j] in _OPENERS:  # a closing quote belongs to the sentence
                j += 1
            if j >= len(buf):
                if ch != "." and not final and len(buf[:j].strip()) >= self.min_chars:
                    return j  # "?", "!" and the danda are unambiguous even at the end
                if not final:
                    return None  # a "." at the very end: wait for the next character
                return None
            if not buf[j].isspace():
                continue  # "10.30", "rs.400", "a.m"
            if len(buf[:j].strip()) < self.min_chars:
                continue  # too short on its own: merge with what follows
            return j
        if self.clause_chars and len(buf) >= self.clause_chars:
            comma = max(buf.rfind(", "), buf.rfind("; "))
            if comma >= self.min_chars and not (comma > 0 and buf[comma - 1].isdigit()
                                                and buf[comma + 2 : comma + 3].isdigit()):
                return comma + 1
        return None


# --------------------------------------------------------------------------- JSON text field
class JsonFieldStream:
    """Pulls the decoded text of ONE top-level string field out of a JSON object that arrives in
    arbitrary chunks, and collects the other top-level string fields (``type``) as they complete.

    ``feed`` returns the NEW decoded characters of the target field. It never raises: malformed
    JSON just stops producing text (``broken``) and the caller's fallback handles it."""

    def __init__(self, key: str = "text") -> None:
        self.key = key
        self.strings: dict[str, str] = {}  # completed top-level string values
        self.target_done = False
        self.broken = False
        self._depth = 0
        self._state = "out"  # out | key | colon | value | str_value | skip
        self._cur_key = ""
        self._buf: list[str] = []
        self._esc = False
        self._uni = ""
        self._skip_depth = 0
        self._skip_str = False

    def feed(self, chunk: str) -> str:
        out: list[str] = []
        for ch in chunk:
            if self.broken:
                break
            self._step(ch, out)
        return "".join(out)

    # one character at a time keeps the machine small and obviously correct
    def _step(self, ch: str, out: list[str]) -> None:  # noqa: C901
        st = self._state
        if st == "out":
            if ch == "{":
                self._depth += 1
            elif ch == "}":
                self._depth = max(0, self._depth - 1)
            elif ch == '"' and self._depth == 1:
                self._state, self._buf = "key", []
            return
        if st in ("key", "str_value"):
            piece = self._string_char(ch)
            if piece is None:  # string closed
                text = "".join(self._buf)
                if st == "key":
                    self._cur_key, self._state = text, "colon"
                else:
                    if self._cur_key == self.key:
                        self.target_done = True
                    else:
                        self.strings[self._cur_key] = text
                    self._state = "out"
                self._buf = []
            elif piece:
                if st == "str_value" and self._cur_key == self.key:
                    out.append(piece)
                else:
                    self._buf.append(piece)
            return
        if st == "colon":
            if ch == ":":
                self._state = "value"
            elif not ch.isspace():
                self.broken = True
            return
        if st == "value":
            if ch.isspace():
                return
            if ch == '"':
                self._state, self._buf, self._esc, self._uni = "str_value", [], False, ""
            else:  # number / true / null / object / array: skip it
                self._state, self._skip_depth, self._skip_str = "skip", 0, False
                self._skip_char(ch)
            return
        if st == "skip":
            self._skip_char(ch)

    def _skip_char(self, ch: str) -> None:
        if self._skip_str:
            if self._esc:
                self._esc = False
            elif ch == "\\":
                self._esc = True
            elif ch == '"':
                self._skip_str = False
            return
        if ch == '"':
            self._skip_str = True
        elif ch in "{[":
            self._skip_depth += 1
        elif ch in "}]":
            if self._skip_depth == 0:  # the object itself closes
                self._state, self._depth = "out", max(0, self._depth - 1)
            else:
                self._skip_depth -= 1
        elif ch == "," and self._skip_depth == 0:
            self._state = "out"

    def _string_char(self, ch: str) -> str | None:
        """Decoded character(s) of a JSON string, "" while inside an escape, None at the end quote."""
        if self._uni:
            self._uni += ch
            if len(self._uni) == 5:  # "u" + 4 hex digits
                with contextlib.suppress(ValueError):
                    code = chr(int(self._uni[1:], 16))
                    self._uni = ""
                    return code
                self._uni = ""
                self.broken = True
            return ""
        if self._esc:
            self._esc = False
            if ch == "u":
                self._uni = "u"
                return ""
            return {"n": "\n", "t": "\t", "r": "\r", "b": "", "f": "", "/": "/"}.get(ch, ch)
        if ch == "\\":
            self._esc = True
            return ""
        if ch == '"':
            return None
        return ch


# --------------------------------------------------------------------------- guards
class RepeatGuard:
    """The 'no repeated line' rule, per sentence. The whole-reply rule is "the same line as her last
    two turns = repeating herself" (``guards.repeats_last_line`` >= 2); per sentence that is: the
    sentence occurs in each of her last ``need`` turns (counting back from the latest), or it
    already occurred earlier in THIS reply."""

    def __init__(self, recent_friday_texts: Sequence[str] = (), need: int = 2) -> None:
        self.need = need
        self._turns = [
            {normalise_utterance(x) for x in SentenceSplitterFull(t)} for t in recent_friday_texts
        ]
        self._now: set[str] = set()

    def __call__(self, sentence: str, _accepted: Sequence[str] = ()) -> str | None:
        key = normalise_utterance(sentence)
        if not key:
            return None
        if key in self._now:
            return "repeats a sentence of this reply"
        run = 0
        for turn in reversed(self._turns):
            if key not in turn:
                break
            run += 1
        if run >= self.need:
            return "repeating herself"
        self._now.add(key)
        return None


def SentenceSplitterFull(text: str) -> list[str]:  # noqa: N802 - tiny helper, reads like a class
    sp = SentenceSplitter(min_chars=1, clause_chars=0)
    return sp.feed(text + " ") + sp.flush()


# --------------------------------------------------------------------------- the runner
@dataclass
class StreamedTurn:
    """What ``FridayBrain.next_call_action_streamed`` returns: the action for the session to
    execute, and the sentences ALREADY spoken while the reply was still being written."""

    action: Any  # friday.core.models.CallAction
    spoken: list[str] = field(default_factory=list)
    result: StreamResult | None = None
    language: Any = None  # the language those sentences were spoken in
    fell_back: bool = False  # the old non-streaming path produced this action

    @property
    def streamed(self) -> bool:
        return bool(self.spoken)


@dataclass
class StreamResult:
    spoken: list[str] = field(default_factory=list)  # sentences actually sent to the voice
    accepted: list[str] = field(default_factory=list)  # sentences that passed the guards
    raw: str = ""  # the model's whole output so far (the JSON text)
    text: str = ""  # the decoded reply text
    reason: str | None = None  # None = the stream completed and every sentence was spoken
    failed_sentence: str | None = None
    type_value: str | None = None
    first_sentence_ms: float | None = None  # request -> first sentence passed the guards
    total_ms: float = 0.0
    complete: bool = False  # the model finished writing
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def streamed(self) -> bool:
        return bool(self.spoken)


async def stream_to_voice(  # noqa: C901
    chunks: AsyncIterator[str],
    *,
    speak: Callable[[str], Awaitable[None]],
    check: Callable[[str, Sequence[str]], str | None],
    text_field: str | None = "text",
    gate: tuple[str, frozenset[str]] | None = ("type", frozenset({"say"})),
    should_stop: Callable[[], bool] | None = None,
    splitter: SentenceSplitter | None = None,
    clock: Callable[[], float] | None = None,
) -> StreamResult:
    """Read ``chunks`` (text deltas), speak each sentence once it has passed ``check``.

    ``text_field`` None = the deltas are the reply text itself (no JSON). ``gate=(key, allowed)``:
    speak only once that top-level string field is one of ``allowed`` (a reply whose ``type`` is not
    ``say`` is never streamed: ``reason="gate:<type>"``, nothing spoken). Speak errors (the call
    ended) propagate after the stream is closed."""
    now = clock or asyncio.get_running_loop().time
    t0 = now()
    res = StreamResult()
    field_stream = JsonFieldStream(text_field) if text_field else None
    sp = splitter or SentenceSplitter()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    stop = should_stop or (lambda: False)
    held: list[str] = []  # sentences waiting for the gate field (type) to arrive
    gate_ok = gate is None or text_field is None

    async def speaker() -> None:
        while True:
            s = await queue.get()
            if s is None:
                return
            if stop():
                continue  # the caller spoke over her: drain without speaking
            await speak(s)
            res.spoken.append(s)

    speaker_task = asyncio.ensure_future(speaker())

    def accept(sentence: str) -> bool:
        reason = check(sentence, res.accepted)
        if reason:
            res.reason, res.failed_sentence = f"guard: {reason}", sentence
            log.warning("stream-to-tts sentence blocked by guard (%s); stopping", reason)
            return False
        res.accepted.append(sentence)
        if res.first_sentence_ms is None:
            res.first_sentence_ms = (now() - t0) * 1000
            log.info("stream-to-tts first sentence %.0f ms after the request (%d chars)",
                     res.first_sentence_ms, len(sentence))
        queue.put_nowait(sentence)
        return True

    def sentences_from(text: str) -> list[str]:
        return sp.feed(text) if text else []

    try:
        try:
            async for chunk in chunks:
                res.raw += chunk
                if speaker_task.done():  # the voice failed (the call ended): stop writing
                    break
                if stop():
                    res.reason = "barge_in"
                    break
                new = field_stream.feed(chunk) if field_stream else chunk
                if field_stream is not None and field_stream.broken:
                    res.reason = "malformed_json"
                    break
                res.text += new
                if res.reason is not None:  # muted (not a "say" reply): just collect the rest
                    continue
                if gate is not None and field_stream is not None and not gate_ok:
                    got = field_stream.strings.get(gate[0])
                    if got is not None:
                        if got not in gate[1]:
                            res.type_value, res.reason = got, f"gate:{got}"
                            continue  # keep reading: the caller needs the whole reply, not a 2nd call
                        res.type_value, gate_ok = got, True
                found = sentences_from(new)
                if not gate_ok:
                    held += found  # the type has not arrived yet: do not speak
                    continue
                batch, held = held + found, []
                failed = False
                for s in batch:
                    if not accept(s):
                        failed = True
                        break
                if failed:
                    break
            else:
                res.complete = True
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - any stream failure: the caller falls back
            res.reason = f"error: {type(e).__name__}"
            log.warning("stream-to-tts failed (%s) after %d sentences; falling back",
                        type(e).__name__, len(res.accepted))
        if res.reason is None and res.complete:
            if field_stream is not None:
                res.type_value = field_stream.strings.get(gate[0]) if gate else None
                if gate is not None and not gate_ok:
                    if res.type_value is not None and res.type_value not in gate[1]:
                        res.reason = f"gate:{res.type_value}"
                    elif res.type_value is None:
                        res.reason = "gate:unknown"
                    else:
                        gate_ok = True
            if res.reason is None:
                tail = held + sp.flush() if gate_ok else []
                for s in tail:
                    if not accept(s):
                        break
        elif res.reason is not None and res.reason.startswith("error") and res.accepted:
            pass  # words already spoken are never replayed; the caller decides what follows
    finally:
        aclose = getattr(chunks, "aclose", None)
        if aclose is not None:  # cancels the HTTP stream if it is still open
            with contextlib.suppress(Exception):
                await aclose()
        queue.put_nowait(None)
        try:
            await speaker_task
        finally:
            res.total_ms = (now() - t0) * 1000
    if res.reason is None:
        log.info("stream-to-tts done: %d sentences spoken, first at %.0f ms, stream ended at %.0f ms",
                 len(res.spoken), res.first_sentence_ms or 0.0, res.total_ms)
    return res

