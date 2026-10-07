"""Exotel telephony - stub (Phase 1 uses Twilio). Configured but not implemented yet:
every call raises ``ProviderError`` so the runner reports FAILED instead of crashing."""

from __future__ import annotations

from friday.core.container import Container
from friday.core.interfaces import ProviderError
from friday.core.models import OutboundCallRequest


class ExotelTelephony:
    name = "exotel"

    async def place_call(self, request: OutboundCallRequest):
        raise ProviderError("exotel", "Exotel telephony is not implemented yet; use Twilio")

    def take_inbound(self, provider_call_id: str):
        return None


def build_exotel(c: Container) -> ExotelTelephony:
    return ExotelTelephony()
