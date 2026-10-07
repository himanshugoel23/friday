"""Voice-specific bus events (subclasses of core ``Event``; no core change needed).

Inbound (BRIEF E30-35):
  * ``InboundCallReceived`` - someone called a Friday number and the call is ANSWERED
    and parked. The backend matches ``from_phone`` (+ ``to_number``, the Friday number
    dialled) to call memory, builds a CallBrief and runs::

        leg = c.telephony.take_inbound(event.provider_call_id)
        result = await c.call_runner.run_inbound(leg, brief, ask_user, notify_user,
                                                 context="We called you earlier about ...")

    If nobody claims the leg within ``inbound_claim_timeout_s`` the provider plays the
    fixed P1 message ("This is Friday, an AI assistant ... I'll call you back") and
    hangs up (US-16).
  * ``MissedCallReceived`` - a call to a Friday number that rang and was dropped before it was
    answered (short ring / missed call). Backend logs it and schedules a call-back.

Call quality:
  * ``CallLanguageSwitched`` - callee language changed mid-call (US-13.2 logging).
  * ``CallLatencyReport``   - per-call STT -> policy -> TTS turn latency (V-9).
"""

from __future__ import annotations

from friday.core.events import Event
from friday.core.models import Language


class InboundCallReceived(Event):
    """Contract shared with Backend A (docs/CORE_CHANGES.md): matched by class name."""

    from_phone: str  # caller ID (E.164; may be "anonymous")
    to_number: str | None = None  # the Friday number that was dialled
    provider_call_id: str | None = None  # key for TelephonyProvider.take_inbound()
    provider: str = "unknown"
    business_id: str | None = None  # simulator only: the simworld business calling

    @property
    def friday_number(self) -> str | None:
        return self.to_number


class MissedCallReceived(Event):
    """A call to a Friday number that was never answered (short ring / missed call)."""

    from_phone: str
    to_number: str | None = None
    provider_call_id: str | None = None
    provider: str = "unknown"
    ring_seconds: float = 0.0
    reason: str = "caller_hung_up"  # caller_hung_up | no_answer | short_ring

    @property
    def friday_number(self) -> str | None:
        return self.to_number


class CallLanguageSwitched(Event):
    task_id: str
    call_id: str
    old: Language | None
    new: Language


class CallLatencyReport(Event):
    task_id: str
    call_id: str
    turns: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    policy_p95_ms: float
    stt_p95_ms: float
    tts_p95_ms: float
