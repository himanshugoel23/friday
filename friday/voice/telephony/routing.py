"""Provider routing (founder priority 2026-10-07): Sarvam first for India, Exotel as
fallback, Twilio for international numbers. Per-call fallback on missing capability
or a dial-time ProviderError.

The runner puts what a call needs in ``OutboundCallRequest.metadata["needs"]``
(comma-separated: ``dtmf`` for IVR/customer care, ``bridge`` for warm transfer,
``media_stream`` for translator mode). ``RoutedTelephony.place_call`` picks the first
provider (in priority order) whose ``capabilities()`` cover the needs; providers
without ``capabilities()`` use the table below.

Live mode with ``telephony_provider=auto`` (or ``routed``) builds this from
``Settings.telephony_route`` (default sarvam,exotel,twilio); providers whose credentials
are missing are skipped.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from friday.core.container import Container
from friday.core.interfaces import ProviderError
from friday.core.logging import get_logger, mask_phone
from friday.core.models import OutboundCallRequest

log = get_logger(__name__)

ALL_CAPS = frozenset({
    "outbound", "inbound", "missed_call", "media_stream", "dtmf", "recording", "amd",
    "bridge_transfer", "bridge_conference",
})  # fmt: skip
KNOWN_CAPS: dict[str, frozenset[str]] = {
    "twilio": ALL_CAPS,
    "exotel": ALL_CAPS - {"amd", "bridge_conference"},
    "simulator": ALL_CAPS,
    "plivo": frozenset(),
}


def capabilities_of(provider: Any) -> frozenset[str]:
    fn = getattr(provider, "capabilities", None)
    if callable(fn):
        return frozenset(fn())
    return KNOWN_CAPS.get(getattr(provider, "name", ""), ALL_CAPS)


def satisfies(caps: frozenset[str], needs: set[str]) -> bool:
    for need in needs:
        if need == "bridge":
            if not caps & {"bridge_transfer", "bridge_conference"}:
                return False
        elif need not in caps:
            return False
    return True


class RoutedTelephony:
    name = "routed"

    def __init__(
        self,
        providers: list[Any],
        *,
        international: Any | None = None,
        domestic_prefix: str = "+91",
    ) -> None:
        if not providers:
            raise ProviderError("routing", "no telephony provider available")
        self.providers = providers
        self.international = international
        self.domestic_prefix = domestic_prefix
        self._selector: Callable | None = None

    @property
    def caller_id_selector(self) -> Callable | None:
        return self._selector

    @caller_id_selector.setter
    def caller_id_selector(self, fn: Callable | None) -> None:
        self._selector = fn
        for p in self.providers:
            if hasattr(p, "caller_id_selector"):
                p.caller_id_selector = fn

    def capabilities(self) -> frozenset[str]:
        out: frozenset[str] = frozenset()
        for p in self.providers:
            out |= capabilities_of(p)
        return out

    def order_for(self, request: OutboundCallRequest) -> list[Any]:
        needs = {n for n in request.metadata.get("needs", "").split(",") if n}
        ordered = list(self.providers)
        if self.international is not None and not request.to_phone.startswith(self.domestic_prefix):
            ordered = [self.international] + [p for p in ordered if p is not self.international]
        capable = [p for p in ordered if satisfies(capabilities_of(p), needs)]
        return capable or ordered

    async def place_call(self, request: OutboundCallRequest) -> Any:
        last: Exception | None = None
        for p in self.order_for(request):
            try:
                leg = await p.place_call(request)
            except ProviderError as e:
                log.warning(
                    "%s could not place call to %s (%s); trying next provider",
                    p.name,
                    mask_phone(request.to_phone),
                    e,
                )
                last = e
                continue
            return leg
        raise last or ProviderError("routing", "no provider could place the call")

    def take_inbound(self, provider_call_id: str) -> Any:
        for p in self.providers:
            fn = getattr(p, "take_inbound", None)
            leg = fn(provider_call_id) if fn else None
            if leg is not None:
                return leg
        return None

    async def delete_recording(self, url: str) -> None:
        """Erasure (SECURITY-14): the first provider that owns the URL deletes it."""
        last: Exception | None = None
        for p in self.providers:
            fn = getattr(p, "delete_recording", None)
            if fn is None:
                continue
            try:
                await fn(url)
                return
            except ProviderError as e:
                last = e
        raise last or ProviderError("routing", "no provider can delete this recording")

    def find(self, cls: type) -> Any | None:
        return next((p for p in self.providers if isinstance(p, cls)), None)

    async def aclose(self) -> None:
        for p in self.providers:
            closer = getattr(p, "aclose", None)
            if closer:
                await closer()


def build_routed_telephony(c: Container, order: list[str] | None = None) -> RoutedTelephony:
    from friday.voice.telephony.exotel import build_exotel
    from friday.voice.telephony.sarvam import build_sarvam_telephony
    from friday.voice.telephony.twilio import build_twilio

    builders = {
        "sarvam": build_sarvam_telephony,
        "exotel": build_exotel,
        "twilio": build_twilio,
    }
    built: dict[str, Any] = {}
    for name in order or c.settings.telephony_route or ["sarvam", "exotel", "twilio"]:
        if name not in builders:
            continue
        try:
            built[name] = builders[name](c)
        except ProviderError as e:
            log.info("telephony route: skipping %s (%s)", name, e)
    providers = list(built.values())
    return RoutedTelephony(providers, international=built.get("twilio"))
