# ruff: noqa: E501
"""T16: the call-bridge PORT (Robin joins a call on Robin's own line) with a FAKE and a Vobiz adapter that is written but NEVER exercised.

The bridge only moves words: it gives the family code the call's turns as TEXT (caller / parent) and speaks the fixed lines. It stores nothing:
no audio, no transcript. Rules the port enforces so the callers cannot forget them:

* ``join`` and ``answer`` take the disclosure / screening line as a REQUIRED argument and speak it FIRST, to both sides of the call, before the
  first turn is delivered. An empty line is refused (``BridgeRefused``).
* A session can only be created through the port; whether the family has consented and the switches are on is decided BEFORE (screening.py).

``FakeCallBridge`` replays a scripted dialogue and records every event in order (tests). ``VobizCallBridge`` is written against the documented Vobiz
REST + WebSocket stream API (skills ``vobiz-audio-streams``, ``vobiz-voice-calls``, ``vobiz-voice-xml``) and every endpoint use is marked [U]:
unverified on a real account. Nothing in this module dials a number.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Speaker = Literal["caller", "parent"]


class BridgeRefused(Exception):
    """The bridge will not join: no disclosure line, no such call, or the provider said no."""


@dataclass(frozen=True)
class Turn:
    speaker: Speaker
    text: str  # held in memory for one scoring step, never persisted by Robin
    t: float = 0.0


@runtime_checkable
class BridgeSession(Protocol):
    async def speak(self, text: str, *, to: Literal["both", "parent"] = "both") -> None: ...
    def turns(self) -> AsyncIterator[Turn]: ...
    async def connect_parent(self) -> None: ...  # screen-first only: ring/attach the parent's phone (never before the screening line was spoken)
    async def leave(self) -> None: ...  # Robin drops out; the two people stay connected (listen-in) or the caller is hung up (screen-first decline)


@runtime_checkable
class CallBridge(Protocol):
    async def join(self, call_ref: str, *, disclosure: str) -> BridgeSession:
        """Listen-in: add Robin to the live call. ``disclosure`` is spoken to BOTH sides before any turn is delivered."""
        ...

    async def answer(self, call_ref: str, *, screening_line: str) -> BridgeSession:
        """Screen-first: answer the unknown caller on Robin's line. The parent's phone is NOT rung until ``connect_parent``."""
        ...


# ---------------------------------------------------------------------------------------------------- fake
@dataclass
class FakeSession:
    script: list[Turn]
    events: list[tuple[str, str]]  # (kind, detail) in order: 'speak:both', 'speak:parent', 'turn', 'ring_parent', 'leave'
    delivered: int = 0

    async def speak(self, text: str, *, to: Literal["both", "parent"] = "both") -> None:
        self.events.append((f"speak:{to}", text))

    async def turns(self) -> AsyncIterator[Turn]:  # type: ignore[override]
        for turn in self.script:
            self.delivered += 1
            self.events.append(("turn", turn.speaker))  # the kind of turn, never its text
            yield turn

    async def connect_parent(self) -> None:
        self.events.append(("ring_parent", ""))

    async def leave(self) -> None:
        self.events.append(("leave", ""))


@dataclass
class FakeCallBridge:
    """Replays ``scripts[call_ref]`` (a list of ``Turn``). ``events`` is the order in which things happened across all sessions."""

    scripts: dict[str, list[Turn]] = field(default_factory=dict)
    events: list[tuple[str, str]] = field(default_factory=list)

    async def join(self, call_ref: str, *, disclosure: str) -> BridgeSession:
        if not disclosure.strip():
            raise BridgeRefused("no_disclosure")
        if call_ref not in self.scripts:
            raise BridgeRefused("no_such_call")
        self.events.append(("join", call_ref))
        s = FakeSession(list(self.scripts[call_ref]), self.events)
        await s.speak(disclosure, to="both")  # FIRST, to both sides
        return s

    async def answer(self, call_ref: str, *, screening_line: str) -> BridgeSession:
        if not screening_line.strip():
            raise BridgeRefused("no_screening_line")
        if call_ref not in self.scripts:
            raise BridgeRefused("no_such_call")
        self.events.append(("answer", call_ref))
        s = FakeSession(list(self.scripts[call_ref]), self.events)
        await s.speak(screening_line, to="both")
        return s


# ---------------------------------------------------------------------------------------------------- Vobiz (written, never run) [U]
Request = Callable[..., Awaitable[Any]]  # request(method, path, json=...) under /Account/{auth_id}; same shape as friday/voice/telephony/sarvam.py


class VobizSession:
    """One call. Transcript turns arrive from OUR WebSocket server (the ``wss://`` URL given to Vobiz) after speech-to-text, via ``push``.
    The WebSocket server and the STT are not part of this module [U]."""

    def __init__(self, bridge: VobizCallBridge, caller_leg: str, parent_leg: str | None) -> None:
        self.bridge, self.caller_leg, self.parent_leg = bridge, caller_leg, parent_leg
        self._q: asyncio.Queue[Turn | None] = asyncio.Queue()
        self.stream_ids: list[str] = []

    def push(self, turn: Turn) -> None:
        self._q.put_nowait(turn)

    def end(self) -> None:  # the WebSocket closed: Vobiz sends no 'stop' event, the close is the end of the stream [U]
        self._q.put_nowait(None)

    async def speak(self, text: str, *, to: Literal["both", "parent"] = "both") -> None:
        legs = [self.parent_leg] if to == "parent" else [self.caller_leg, self.parent_leg]
        for leg in (x for x in legs if x):
            # POST /Account/{id}/Call/{call_uuid}/Speak/ [U]: plays TTS into that leg. Which legs a conference member hears from a leg-level Speak is unverified.
            await self.bridge.request("POST", f"/Call/{leg}/Speak/", json={"text": text, "language": self.bridge.language})

    async def turns(self) -> AsyncIterator[Turn]:  # type: ignore[override]
        while (turn := await self._q.get()) is not None:
            yield turn

    async def connect_parent(self) -> None:
        # Screen-first: move the caller leg into a room and add the parent [U]. Documented pieces: VobizXML <Conference> and <Dial>, REST transfer.
        await self.bridge.request("POST", f"/Call/{self.caller_leg}/", json={"legs": "aleg", "aleg_url": self.bridge.conference_xml_url(self.caller_leg), "aleg_method": "GET"})

    async def leave(self) -> None:
        for sid in self.stream_ids:
            await self.bridge.request("DELETE", f"/Call/{self.caller_leg}/Stream/{sid}/")  # 204; stops one fork, other fork/legs stay [U]
        self.end()


class VobizCallBridge:
    """CallBridge over Vobiz. Written from the documentation only; NOT EXERCISED (no account call was made). Needs, before anything real: Vobiz
    confirms in writing that calls can be routed through Robin's line into a conference with two one-way streams; the founder approves the
    disclosure wording; legal sign-off (two-party consent). ``resolve_legs(call_ref) -> (caller_leg_uuid, parent_leg_uuid | None)`` comes from the
    telephony wiring (the parked inbound leg / the conference member list)."""

    def __init__(self, request: Request, *, ws_url: str, resolve_legs: Callable[[str], Awaitable[tuple[str, str | None]]], conference_xml_url: Callable[[str], str], language: str = "hi-IN") -> None:
        self.request, self.ws_url, self.resolve_legs, self.conference_xml_url, self.language = request, ws_url, resolve_legs, conference_xml_url, language
        self.sessions: dict[str, VobizSession] = {}

    async def _streams(self, s: VobizSession) -> None:
        # Two ONE-WAY streams, one per leg ('audio_track=both' + 'bidirectional' does not work; mixed audio would hide who speaks) [U].
        # service_url carries a per-call secret path (extra_headers do not reach the socket) [U]. Inbound format 16 kHz L16 or 8 kHz mu-law, never 24 kHz.
        for leg, who in ((s.caller_leg, "caller"), (s.parent_leg, "parent")):
            if not leg:
                continue
            r = await self.request("POST", f"/Call/{leg}/Stream/", json={"service_url": f"{self.ws_url}/{who}", "audio_track": "inbound", "bidirectional": "false", "content_type": "audio/x-l16;rate=16000", "stream_timeout": 3600})
            sid = (r or {}).get("stream_id") if isinstance(r, dict) else None
            if sid:
                s.stream_ids.append(str(sid))

    async def join(self, call_ref: str, *, disclosure: str) -> BridgeSession:
        if not disclosure.strip():
            raise BridgeRefused("no_disclosure")
        try:
            caller, parent = await self.resolve_legs(call_ref)
        except Exception as e:  # noqa: BLE001
            raise BridgeRefused("no_such_call") from e
        s = self.sessions[call_ref] = VobizSession(self, caller, parent)
        await s.speak(disclosure, to="both")  # disclosure BEFORE the streams start, so no word is analysed before both sides were told
        await self._streams(s)
        return s

    async def answer(self, call_ref: str, *, screening_line: str) -> BridgeSession:
        if not screening_line.strip():
            raise BridgeRefused("no_screening_line")
        try:
            caller, _ = await self.resolve_legs(call_ref)
        except Exception as e:  # noqa: BLE001
            raise BridgeRefused("no_such_call") from e
        s = self.sessions[call_ref] = VobizSession(self, caller, None)
        await s.speak(screening_line, to="both")
        await self._streams(s)
        return s
