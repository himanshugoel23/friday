"""Dependency wiring. Picks real vs simulator implementations from Settings.

Every component is built lazily, once, by a *factory* found by import path:

    "friday.brain.service:build_brain"   ->   def build_brain(c: Container) -> Brain

Factories receive the container and pull their own dependencies from it
(``c.settings``, ``c.clock``, ``c.bus``, ``c.db``, ``c.llm``, ...). This keeps the
core free of imports from engineer-owned packages, so everything imports and the
test-suite runs even before a module exists. Asking for a component whose factory
module isn't written yet raises ``ComponentNotAvailable`` with the expected path.

THE FACTORY PATHS BELOW ARE THE CONTRACT: each engineer must provide exactly these
callables (see docs/TASKS.md). Tests can bypass factories with ``override``:

    c = Container(settings, clock=FakeClock())
    c.override("llm", MyFakeLLM())

Owner: Engineering Manager (core).
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from typing import Any

from friday.core.clock import Clock, SystemClock
from friday.core.config import Settings
from friday.core.events import EventBus
from friday.core.logging import get_logger

log = get_logger(__name__)

Factory = Callable[["Container"], Any]

# component -> {provider name -> "module:callable"}.  "*" = single implementation.
FACTORIES: dict[str, dict[str, str]] = {
    # --- AI Engineer (friday/brain/)
    "llm": {
        "anthropic": "friday.brain.llm:build_anthropic_llm",
        "fake": "friday.brain.fake_llm:build_fake_llm",
    },
    "brain": {"*": "friday.brain.service:build_brain"},
    "document_extractor": {"*": "friday.brain.extraction:build_document_extractor"},
    # --- Voice Engineer (friday/voice/)
    "telephony": {
        "simulator": "friday.voice.simulator:build_simulated_telephony",
        "twilio": "friday.voice.telephony.twilio:build_twilio",
        "exotel": "friday.voice.telephony.exotel:build_exotel",
        "plivo": "friday.voice.telephony.plivo:build_plivo",
    },
    "stt": {
        "fake": "friday.voice.stt.fake:build_fake_stt",
        "sarvam": "friday.voice.stt.sarvam:build_sarvam_stt",
        "deepgram": "friday.voice.stt.deepgram:build_deepgram_stt",
    },
    "tts": {
        "fake": "friday.voice.tts.fake:build_fake_tts",
        "sarvam": "friday.voice.tts.sarvam:build_sarvam_tts",
        "elevenlabs": "friday.voice.tts.elevenlabs:build_elevenlabs_tts",
    },
    "audio_classifier": {"*": "friday.voice.classifier:build_audio_classifier"},
    "call_runner": {"*": "friday.voice.session:build_call_runner"},
    "voice_router": {"*": "friday.voice.http:build_router"},  # FastAPI APIRouter (webhooks/WS)
    # --- Backend Engineer (friday/channels/, friday/discovery/, friday/tasks/, ...)
    "messaging": {
        "simulator": "friday.channels.simulator:build_simulator_channel",
        "cloud": "friday.channels.whatsapp:build_whatsapp_channel",
    },
    "sms": {
        "fake": "friday.channels.sms:build_fake_sms",
        "msg91": "friday.channels.sms:build_msg91_sms",
    },
    "directory": {
        "simulator": "friday.discovery.simulator:build_simulated_directory",
        "google_places": "friday.discovery.google_places:build_google_places_directory",
    },
    "geocoder": {
        "simulator": "friday.discovery.simulator:build_simulated_geocoder",
        "google": "friday.discovery.google_geocoder:build_google_geocoder",
    },
    "official_numbers": {"*": "friday.discovery.official_numbers:build_official_numbers"},
    "number_verifier": {"*": "friday.discovery.verify:build_number_verifier"},
    "repos": {"*": "friday.db.repositories:build_repositories"},
    "notifier": {"*": "friday.channels.notifier:build_notifier"},
    "task_engine": {"*": "friday.tasks.engine:build_task_engine"},
    "proactive": {"*": "friday.proactive.engine:build_proactive_engine"},
}


class ComponentNotAvailable(RuntimeError):
    """The factory module for a component has not been implemented (yet)."""


class Container:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        clock: Clock | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.clock: Clock = clock or SystemClock()
        self.bus = bus or EventBus()
        self._instances: dict[str, Any] = {}
        self._db: Any = None

    # ------------------------------------------------------------------ resolution
    def provider_for(self, component: str) -> str:
        s = self.settings
        resolvers: dict[str, Callable[[], str]] = {
            "llm": s.resolve_llm,
            "telephony": s.resolve_telephony,
            "stt": s.resolve_stt,
            "tts": s.resolve_tts,
            "messaging": s.resolve_whatsapp,
            "sms": s.resolve_sms,
            "directory": s.resolve_directory,
            "geocoder": s.resolve_geocoder,
        }
        return resolvers[component]() if component in resolvers else "*"

    def factory_path(self, component: str) -> str:
        try:
            options = FACTORIES[component]
        except KeyError:
            raise KeyError(f"unknown component {component!r}") from None
        provider = self.provider_for(component)
        try:
            return options[provider]
        except KeyError:
            raise ComponentNotAvailable(
                f"no factory for {component} provider {provider!r}"
            ) from None

    def get(self, component: str) -> Any:
        if component not in self._instances:
            self._instances[component] = self._build(component)
        return self._instances[component]

    def override(self, component: str, instance: Any) -> None:
        """Inject an instance (tests, simulator CLI)."""
        self._instances[component] = instance

    def is_available(self, component: str) -> bool:
        try:
            _load(self.factory_path(component))
        except (ComponentNotAvailable, KeyError):
            return False
        return True

    def _build(self, component: str) -> Any:
        path = self.factory_path(component)
        factory = _load(path)
        log.debug("building %s via %s", component, path)
        return factory(self)

    # ------------------------------------------------------------------ typed accessors
    @property
    def db(self):  # -> friday.db.Database
        if self._db is None:
            from friday.db.session import Database

            self._db = Database(self.settings.database_url, echo=self.settings.db_echo)
        return self._db

    def override_db(self, db: Any) -> None:
        self._db = db

    llm = property(lambda self: self.get("llm"))
    brain = property(lambda self: self.get("brain"))
    document_extractor = property(lambda self: self.get("document_extractor"))
    telephony = property(lambda self: self.get("telephony"))
    stt = property(lambda self: self.get("stt"))
    tts = property(lambda self: self.get("tts"))
    audio_classifier = property(lambda self: self.get("audio_classifier"))
    call_runner = property(lambda self: self.get("call_runner"))
    messaging = property(lambda self: self.get("messaging"))
    sms = property(lambda self: self.get("sms"))
    directory = property(lambda self: self.get("directory"))
    geocoder = property(lambda self: self.get("geocoder"))
    official_numbers = property(lambda self: self.get("official_numbers"))
    number_verifier = property(lambda self: self.get("number_verifier"))
    repos = property(lambda self: self.get("repos"))
    notifier = property(lambda self: self.get("notifier"))
    task_engine = property(lambda self: self.get("task_engine"))
    proactive = property(lambda self: self.get("proactive"))

    # ------------------------------------------------------------------ lifecycle
    def check_live_config(self) -> None:
        if self.settings.is_live and (problems := self.settings.live_problems()):
            raise RuntimeError("live mode misconfigured: " + "; ".join(problems))

    async def startup(self) -> None:
        self.check_live_config()
        await self.db.create_all()

    async def aclose(self) -> None:
        for name, inst in list(self._instances.items()):
            closer = getattr(inst, "aclose", None)
            if closer is None:
                continue
            try:
                result = closer()
                if inspect.isawaitable(result):
                    await result
            except Exception:  # pragma: no cover - best effort
                log.exception("error closing %s", name)
        self._instances.clear()
        if self._db is not None:
            await self._db.dispose()


def _load(path: str) -> Factory:
    module_name, _, attr = path.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name and module_name.startswith(e.name):
            raise ComponentNotAvailable(f"{path} not implemented yet") from e
        raise
    try:
        return getattr(module, attr)
    except AttributeError:
        raise ComponentNotAvailable(f"{path} not implemented yet") from None
