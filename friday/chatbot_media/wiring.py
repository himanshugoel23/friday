"""Build the hooks from the container. Only called while a switch is on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from friday.chatbot_media import copy as _copy  # noqa: F401  (registers the Devanagari variants)
from friday.chatbot_media.convert import FfmpegConverter
from friday.chatbot_media.inbound import SttTranscriber, VoiceInbound
from friday.chatbot_media.ledger import VoiceLedger
from friday.chatbot_media.outbound import OutboundHooks
from friday.chatbot_media.prefs import VoiceState
from friday.chatbot_media.speech import VoiceSynthesizer
from friday.core.container import ComponentNotAvailable
from friday.core.logging import get_logger
from friday.core.scale import Cache, MemoryCache

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)


def _opt(c: Container, name: str) -> Any:
    try:
        return c.get(name)
    except ComponentNotAvailable:
        return None
    except Exception as e:  # noqa: BLE001 - a missing key must not stop the chatbot
        log.warning("chatbot_media: %s could not be built (%s)", name, type(e).__name__)
        return None


def shared_state(c: Container) -> VoiceState:
    """One VoiceState per container (the notifier and the inbound pipeline share the cache)."""
    state = getattr(c, "_voice_state", None)
    if state is None:
        cache: Cache = _opt(c, "cache") or MemoryCache(c.clock)
        state = VoiceState(cache)
        c._voice_state = state  # type: ignore[attr-defined]
    return state


def attach_outbound(c: Container, notifier: Any) -> OutboundHooks:
    s = c.settings
    state = shared_state(c)
    synth = ledger = None
    if s.voice_note_replies:
        converter = FfmpegConverter()
        if not converter.available:
            log.warning("FRIDAY_VOICE_NOTE_REPLIES is on but ffmpeg is missing: replies stay text")
        tts = _opt(c, "tts")
        if tts is not None:
            synth = VoiceSynthesizer(tts, converter)
        ledger = VoiceLedger(
            state.cache,
            c.clock,
            daily_cap=s.voice_note_daily_cap,
            cost_per_1k_chars_inr=s.voice_note_cost_per_1k_chars_inr,
        )
    hooks = OutboundHooks(
        settings=s, clock=c.clock, state=state, ledger=ledger, synth=synth,
        channel=notifier.messaging,
    )  # fmt: skip
    notifier.outbound_hook = hooks
    return hooks


def build_inbound(c: Container, pipeline: Any) -> VoiceInbound:
    """The voice-note side of the inbound pipeline (only built while the voice switch is on)."""
    s = c.settings

    def transcriber() -> SttTranscriber | None:
        stt = _opt(c, "stt")
        return SttTranscriber(stt) if stt is not None else None

    messaging = _opt(c, "messaging")
    return VoiceInbound(
        state=shared_state(c),
        transcriber=transcriber,
        fetch_media=messaging.fetch_media if messaging is not None else None,
        reply=lambda user, text, buttons: pipeline.reply(user, text, buttons),
        now=c.clock.now,
        confirm_below=s.voice_note_confirm_below,
        voice_enabled=s.voice_note_replies,
    )


def build_docs(c: Container, pipeline: Any, *, vision: Any = None) -> Any:
    """Photos and documents (FRIDAY_DOCS_ENABLED). ``vision`` is for tests; production uses the
    provider named by FRIDAY_DOCS_VISION_PROVIDER (default ``none``: "cannot read files now")."""
    from friday.chatbot_media.docs import DocsInbound
    from friday.docunderstand.pipeline import DocLimits, DocumentPipeline
    from friday.docunderstand.ports import build_vision
    from friday.docunderstand.service import DocumentService
    from friday.docunderstand.store import MemoryDocStore

    s = c.settings
    repos = c.repos
    store = getattr(repos, "documents", None) or MemoryDocStore()
    cache: Cache = _opt(c, "cache") or MemoryCache(c.clock)
    limits = DocLimits(
        max_bytes=s.docs_max_bytes, max_pages=s.docs_max_pages, daily_cap=s.docs_daily_cap,
        confirm_below=s.docs_confirm_below, pending_days=s.docs_pending_days,
    )  # fmt: skip
    service = DocumentService(
        DocumentPipeline(vision or build_vision(s.docs_vision_provider), c.clock, cache, limits),
        store,
        c.clock,
        retention_days=s.docs_retention_days,
        bill_sink=_bill_sink(c) if s.savings_enabled else None,
        doc_sink=getattr(getattr(pipeline, "features", None), "on_document_confirmed", None),
    )
    allowed = {x.strip() for x in s.docs_enabled_users if x.strip()}
    messaging = _opt(c, "messaging")

    async def language_of(user: Any) -> str:
        profile = await repos.profiles.get_or_default(user.id)
        return profile.language.value

    return DocsInbound(
        service=service,
        fetch_media=messaging.fetch_media if messaging is not None else None,
        reply=lambda user, text, buttons: pipeline.reply(user, text, buttons),
        enabled_for=lambda user: not allowed or user.id in allowed or user.phone in allowed,
        language_of=language_of,
    )


def _bill_sink(c: Container) -> Any:
    """A confirmed bill document becomes a tracked bill (savings engine; reminders come from it).
    The existing parser already read the text; this only maps the confirmed fields."""
    from datetime import date

    from friday.savings.bills import BillKind, BillParse, BillSource, bill_from_parse
    from friday.savings.store import SavingsRepos

    bills = SavingsRepos(c.repos.db, c.clock).bills

    async def sink(user_id: str, v: dict[str, str]) -> bool:
        if not v.get("due_date") or not v.get("biller"):
            return False
        try:
            kind = BillKind(v.get("kind", "other"))
        except ValueError:
            kind = BillKind.OTHER
        parse = BillParse(
            kind=kind,
            biller=v["biller"],
            amount_paise=int(v["amount_paise"]) if v.get("amount_paise") else None,
            min_due_paise=int(v["min_due_paise"]) if v.get("min_due_paise") else None,
            due_date=date.fromisoformat(v["due_date"]),
        )
        bill = bill_from_parse(user_id, parse, BillSource.FORWARDED)
        bill.confirmed = True  # the user just said "sahi hai"
        await bills.save(bill)
        return True

    return sink
