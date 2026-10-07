"""Voice-specific bus events (subclasses of core ``Event``; no core change needed).

Inbound (BRIEF E30-35):
  * ``InboundCallReceived`` - someone called a Friday number and the call is ANSWERED
    and parked. The backend matches ``from_phone`` (+ ``to_phone``, the Friday number
    dialled) to call memory, builds a CallBrief and runs::

        leg = c.telephony.take_inbound(event.call_id)
        result = await c.call_runner.run_inbound(brief, leg, ask_user, notify_user,
                                                 context="We called you earlier about ...")

    If nobody claims the leg within ``inbound_claim_timeout_s`` the provider plays the
    fixed P1 message ("This is Friday, an AI assistant ... I'll call you back") and
    hangs up (US-16).
  * ``MissedCall`` - a call to a Friday number that rang and was dropped before it was
    answered (short ring / missed call). Backend logs it and schedules a call-back.

Call quality:
  * ``CallLanguageSwitched`` - callee language changed mid-call (US-13.2 logging).
  * ``CallLatencyReport``   - per-call STT -> policy -> TTS turn latency (V-9).
"""

from __future__ import annotations

from friday.core.events import Event
from friday.core.models import Language


class InboundCallReceived(Event):
    call_id: str  # key for TelephonyProvider.take_inbound()
    provider: str
    provider_call_id: str | None = None
    from_phone: str  # caller ID (E.164; may be "anonymous")
    to_phone: str  # the Friday number that was dialled
    business_id: str | None = None  # simulator only: the simworld business calling


class MissedCall(Event):
    provider: str
    provider_call_id: str | None = None
    from_phone: str
    to_phone: str
    ring_seconds: float = 0.0
    reason: str = "caller_hung_up"  # caller_hung_up | no_answer | short_ring


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
