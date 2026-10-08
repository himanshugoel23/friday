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
        "routed": "friday.voice.telephony.routing:build_routed_telephony",
        "sarvam": "friday.voice.telephony.sarvam:build_sarvam_telephony",
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
    "hotels": {
        "simulator": "friday.discovery.hotels.simulator:build_simulated_hotels",
        "expedia_rapid": "friday.discovery.hotels.expedia:build_expedia_rapid",
    },
    "official_numbers": {"*": "friday.discovery.official_numbers:build_official_numbers"},
    "number_verifier": {"*": "friday.discovery.verify:build_number_verifier"},
    "repos": {"*": "friday.db.repositories:build_repositories"},
    "notifier": {"*": "friday.channels.notifier:build_notifier"},
    "task_engine": {"*": "friday.tasks.engine:build_task_engine"},
    "proactive": {"*": "friday.proactive.engine:build_proactive_engine"},
    # --- caller-ID reputation & rotation (Backend B)
    "number_pool": {"*": "friday.tasks.number_pool:build_number_pool"},
    # --- scale-out (core memory impls; durable impls by Backend A in friday/db/)
    "job_queue": {
        "memory": "friday.core.scale:build_memory_job_queue",
        "postgres": "friday.db.queue:build_pg_job_queue",
    },
    "outbox": {"*": "friday.core.scale:build_queue_outbox"},
    "lock": {
        "memory": "friday.core.scale:build_memory_lock",
        "postgres": "friday.db.locks:build_pg_lock",
        "redis": "friday.db.redis_backends:build_redis_lock",
    },
    "cache": {
        "memory": "friday.core.scale:build_memory_cache",
        "redis": "friday.db.redis_backends:build_redis_cache",
    },
    "rate_limiter": {
        "memory": "friday.core.scale:build_memory_rate_limiter",
        "redis": "friday.db.redis_backends:build_redis_rate_limiter",
    },
    "idempotency": {
        "memory": "friday.core.scale:build_memory_idempotency",
        "postgres": "friday.db.idempotency:build_pg_idempotency",
    },
    # --- field encryption keys (SECURITY-12): local in dev, KMS envelope in live
    # --- recordings / media object storage (Backend A): S3 in live, local dir in dev
    "object_store": {"*": "friday.db.objectstore:build_object_store_component"},
    "key_provider": {
        "local": "friday.core.crypto:build_local_key_provider",
        "kms": "friday.db.kms:build_kms_key_provider",
    },
}

# Which components each process role needs (one codebase, several deployments).
# ``Container.role_components()`` -> union for Settings.roles. Startup only wires these.
ROLE_COMPONENTS: dict[str, tuple[str, ...]] = {
    "api": (
        "repos", "messaging", "sms", "notifier", "brain", "stt", "job_queue", "outbox",
        "idempotency", "lock", "rate_limiter", "voice_router",
    ),
    "task": (
        "repos", "brain", "task_engine", "notifier", "directory", "geocoder", "hotels",
        "official_numbers", "number_verifier", "number_pool", "job_queue", "outbox", "lock",
        "cache", "rate_limiter",
    ),
    "voice": (
        "repos", "brain", "telephony", "stt", "tts", "audio_classifier", "call_runner",
        "voice_router", "number_pool", "job_queue", "cache", "rate_limiter", "notifier",
        "object_store", "task_engine",
    ),
    "proactive": (
        "repos", "brain", "proactive", "notifier", "job_queue", "outbox", "lock", "idempotency",
        "object_store",
    ),
    "batch": ("repos", "brain", "llm", "document_extractor", "job_queue", "cache"),
}  # fmt: skip

# Durable job kinds and the role whose workers consume them (see ARCHITECTURE §10).
JOB_ROUTES: dict[str, str] = {
    "inbound.message": "task",  # webhook stored + acked by api, processed by task workers
    "task.step": "task",
    "task.scheduled": "task",  # retries, call-backs, recurring instances, reconfirms
    "call.place": "voice",  # pinned to the voice worker that claims it
    "call.inbound": "voice",
    "message.send": "task",  # outbox -> notifier
    "nudge.evaluate": "proactive",
    "nudge.send": "proactive",
    "batch.extract_facts": "batch",
    "batch.vendor_memory": "batch",
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
            "hotels": s.resolve_hotels,
            "job_queue": s.resolve_queue,
            "idempotency": s.resolve_queue,
            "lock": s.resolve_lock,
            "cache": s.resolve_cache,
            "rate_limiter": s.resolve_rate_limiter,
            "key_provider": lambda: "kms" if (s.is_live and s.field_key_id) else "local",
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

            s = self.settings
            self._db = Database(
                s.database_url,
                echo=s.db_echo,
                pool_size=s.db_pool_size,
                max_overflow=s.db_max_overflow,
                pool_timeout_s=s.db_pool_timeout_s,
            )
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
    hotels = property(lambda self: self.get("hotels"))
    number_pool = property(lambda self: self.get("number_pool"))
    job_queue = property(lambda self: self.get("job_queue"))
    outbox = property(lambda self: self.get("outbox"))
    lock = property(lambda self: self.get("lock"))
    cache = property(lambda self: self.get("cache"))
    rate_limiter = property(lambda self: self.get("rate_limiter"))
    idempotency = property(lambda self: self.get("idempotency"))
    key_provider = property(lambda self: self.get("key_provider"))
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

    @property
    def roles(self) -> list[str]:
        return list(self.settings.roles)

    def role_components(self, roles: list[str] | None = None) -> list[str]:
        """Components this process needs for ``roles`` (default Settings.roles)."""
        out: list[str] = []
        for role in roles or self.roles:
            for comp in ROLE_COMPONENTS.get(role, ()):
                if comp not in out:
                    out.append(comp)
        return out

    def missing_role_components(self, roles: list[str] | None = None) -> list[str]:
        """Components the roles need whose factory module isn't importable (startup check)."""
        return [comp for comp in self.role_components(roles) if not self.is_available(comp)]

    def install_field_cipher(self) -> None:
        """Install the process-wide FieldCipher for EncryptedText/EncryptedJSON columns."""
        from friday.core.crypto import FieldCipher, set_field_cipher

        if self.is_available("key_provider"):
            set_field_cipher(FieldCipher(self.key_provider))

    async def startup(self) -> None:
        self.check_live_config()
        self.install_field_cipher()
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
