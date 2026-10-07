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
  * ``CallCostReport``      - telephony seconds, STT seconds, TTS chars, LLM calls (cost ledger).
"""

from __future__ import annotations

# Merged into core (docs/CORE_CHANGES.md, Stage 3): re-exported here so existing
# imports keep working. Define new voice-only events below.
from friday.core.events import (  # noqa: F401
    CallCostReport,
    CallLanguageSwitched,
    CallLatencyReport,
    Event,
    InboundCallReceived,
    MissedCallReceived,
)

__all__ = [
    "CallCostReport",
    "CallLanguageSwitched",
    "CallLatencyReport",
    "InboundCallReceived",
    "MissedCallReceived",
]
