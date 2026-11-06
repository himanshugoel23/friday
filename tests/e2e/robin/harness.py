# ruff: noqa: E501
"""Robin end-to-end harness: the REAL container + InboundPipeline + RobinHub (+ the device API) on in-memory SQLite and a fake clock.

Nothing real is reached: the parent's phone is a ``FakeParentCaller`` (swapped onto the hub's context after the container is built, so
production code has no test seam), the parent's WhatsApp is a ``FakeParentChannel``, the child's WhatsApp is the simulator channel behind
the container's notifier (what the child "reads"), the authority desk is the dry-run logger, every Robin switch is OFF unless a test turns
it on. Every phone number below is invented.

    w = await RobinWorld.start()
    await w.setup_family()                  # child chat: "set up Robin for my father" ... -> consent -> parent notified
    await w.parent_says("band karo")        # the parent's words arrive the way the (future) WhatsApp transport would deliver them
    await w.advance(minutes=30)             # fake clock + one scheduler tick (check-ins, ladder, missed-call rings)
    w.child_texts()                          # what the child's phone showed
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from friday.core.clock import IST
from friday.core.models import ReplyButton
from friday.robin.models import CallOutcome, CallResult, Family, Member, Role
from friday.robin.ports import FakeParentCaller, FakeParentChannel
from tests.e2e.harness import Friday, Party, plain

CHILD = "+919800000101"  # invented
PARENT = "+919800000102"
SECOND = "+919800000103"
PARENT_OTHER = "+919800000104"
START = datetime(2026, 1, 5, 8, 0, tzinfo=IST)  # Monday 08:00 IST: inside the call window, outside quiet hours


class LogCapture(logging.Handler):
    """Every log record the app emits, un-redacted (the production redacting filter is deliberately NOT applied: the code itself must be clean)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            msg = str(record.msg)
        extra = ""
        if record.exc_info and record.exc_info[1] is not None:
            extra = " | " + repr(record.exc_info[1])
        self.lines.append(f"{record.levelname} {record.name}: {msg}{extra}")

    def text(self) -> str:
        return "\n".join(self.lines)


def digits_of(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def phone_forms(phone: str) -> list[str]:
    """Every way a full invented number could appear in a log or audit line."""
    d = digits_of(phone)  # 919800000102
    local = d[-10:]  # 9800000102
    return [phone, d, local, f"+91 {local}", f"+91-{local}", f"91 {local}", f"{local[:5]} {local[5:]}", f"+91 {local[:5]} {local[5:]}"]


_LONG_RUN = re.compile(r"(?<![0-9A-Za-z])\d{10,}(?![0-9A-Za-z])")  # a standalone digit run (ids are hex, so digits inside them do not count)


def assert_no_pii(texts: list[str] | str, *, phones: tuple[str, ...] = (CHILD, PARENT, SECOND, PARENT_OTHER), secrets: tuple[str, ...] = (), what: str = "logs") -> None:
    """``texts`` (log lines, audit rows, ...) never contain a full phone number (any common spelling), a 10+ digit run, or any of ``secrets``
    (medicine names, transcripts, distress words the test fed in). Fails with the offending line (already free of the secret it shows: the line is cut)."""
    blob = texts if isinstance(texts, str) else "\n".join(texts)
    low = blob.lower()
    for ph in phones:
        for form in phone_forms(ph):
            assert form not in blob, f"full phone number found in {what}: ...{blob[max(0, blob.index(form) - 40) : blob.index(form)]}<NUMBER>"
    m = _LONG_RUN.search(blob)
    assert m is None, f"a 10+ digit run found in {what}: ...{blob[max(0, m.start() - 40) : m.start()]}<DIGITS>"
    for s in secrets:
        assert s.lower() not in low, f"sensitive text {s[:3]}... found in {what}: ...{low[max(0, low.index(s.lower()) - 40) : low.index(s.lower())]}<SECRET>"


_TEMPLATE: Path | None = None


async def _child_template() -> Path:
    """One SQLite file with the child (CHILD, 'Asha') onboarded as an ordinary Friday user, built once per process and copied per test."""
    global _TEMPLATE
    if _TEMPLATE is None:
        folder = Path(tempfile.mkdtemp(prefix="robin-e2e-template-"))
        f = await Friday.start(database_url=f"sqlite+aiosqlite:///{folder}/e2e.db", media_dir=str(folder / "media"))
        await f.onboard(CHILD, "Asha")
        await f.close()
        _TEMPLATE = folder / "e2e.db"
    return _TEMPLATE


@dataclass
class Device:
    """The Android device API (friday.robindevice) mounted on the container, driven over ASGI. Its clock follows the world's fake clock."""

    app: FastAPI
    service: Any
    client: httpx.AsyncClient
    token: str | None = None

    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def pair(self, parent_id: str, *, shadow_days: int = 0) -> str:
        code = await self.service.create_pairing_code(parent_id)
        r = await self.client.post("/robin/device/pair", json={"code": code, "app_version": "1.0.0", "os_sdk": 34})
        assert r.status_code == 200, r.text
        self.token = r.json()["device_token"]
        self.service.set_policy(parent_id, shadow_days=shadow_days)  # live from the first signal; the learning week has its own tests
        return self.token

    async def signal(self, w: RobinWorld, type_: str, **fields: Any) -> httpx.Response:
        ev = {"id": f"evt-{w.next_id():08d}", "type": type_, "ts_ms": int(w.clock.now().timestamp() * 1000), **fields}
        return await self.client.post("/robin/device/signals", headers=self.h(), json={"events": [ev]})

    async def sos(self) -> httpx.Response:
        return await self.client.post("/robin/device/sos", headers=self.h(), json={})

    async def heartbeat(self, w: RobinWorld) -> httpx.Response:
        return await self.client.post("/robin/device/heartbeat", headers=self.h(), json={"app_version": "1.0.0", "os_sdk": 34, "roles": {}, "ts_ms": int(w.clock.now().timestamp() * 1000)})


@dataclass
class RobinWorld:
    f: Friday
    child: Party
    caller: FakeParentCaller
    channel: FakeParentChannel
    logs: LogCapture
    device: Device | None = None
    _ids: int = 0
    mark: int = 0  # messages the child had before Robin (none: the child comes from the template)
    workdir: Path = field(default_factory=Path)
    closed: bool = False
    secrets: list[str] = field(default_factory=list)  # strings the test fed in that must never reach a log or an audit row

    # ------------------------------------------------------------------ building the world
    @classmethod
    async def start(cls, *, device: bool = False, now: datetime = START, **settings: Any) -> RobinWorld:
        """Robin ON (and the device API if asked), everything else at its default (authority calls OFF, dry-run ON, listen-in OFF)."""
        logs = LogCapture()
        root = logging.getLogger()
        root.addHandler(logs)
        root.setLevel(logging.INFO)
        logging.getLogger("friday").setLevel(logging.DEBUG)  # the app's own debug lines count too
        from friday.core.logging import QUIET_LOGGERS

        for noisy in QUIET_LOGGERS:  # same as production's setup_logging: SQL parameters and HTTP bodies are never logged
            logging.getLogger(noisy).setLevel(logging.WARNING)
        base: dict[str, Any] = dict(robin_enabled=True, robin_device_enabled=device, brand_name="Robin", robin_tick_s=30)
        base.update(settings)
        workdir = Path(tempfile.mkdtemp(prefix="robin-e2e-"))
        shutil.copy(await _child_template(), workdir / "e2e.db")  # Asha (the child) is already a Friday user: onboarding is covered by tests/e2e/test_onboarding.py
        f = await Friday.start(now=now, database_url=f"sqlite+aiosqlite:///{workdir}/e2e.db", media_dir=str(workdir / "media"), create_tables=False, first_message_id=10_000_000, **base)
        hub = f.rt.pipeline.robin
        assert hub is not None, "FRIDAY_ROBIN_ENABLED did not build the hub"
        caller, channel = FakeParentCaller(), FakeParentChannel()
        hub.ctx.caller = caller  # the parent's phone: never dialled
        hub.ctx.parent_channel = channel  # the parent's WhatsApp: a recording fake
        child = f.person(CHILD)
        w = cls(f, child, caller, channel, logs)
        w.workdir = workdir
        if device:
            w.device = await w._mount_device()
        return w

    async def _mount_device(self) -> Device:
        from friday.robindevice.wiring import maybe_mount

        app = FastAPI()
        service = maybe_mount(app, self.f.c)
        assert service is not None, "device API did not mount (Robin family core and device switch must both be on)"
        service.now_ms = lambda: int(self.clock.now().timestamp() * 1000)  # the device service defaults to the wall clock
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url="http://test")
        return Device(app, service, client)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        logging.getLogger().removeHandler(self.logs)
        if self.device is not None:
            await self.device.client.aclose()
        await self.f.close()
        shutil.rmtree(self.workdir, ignore_errors=True)

    # ------------------------------------------------------------------ handles
    @property
    def hub(self):  # noqa: ANN201
        return self.f.rt.pipeline.robin

    @property
    def store(self):  # noqa: ANN201
        return self.hub.ctx.store

    @property
    def clock(self):  # noqa: ANN201
        return self.f.clock

    @property
    def settings(self):  # noqa: ANN201
        return self.f.c.settings

    def next_id(self) -> int:
        self._ids += 1
        return self._ids

    async def family(self) -> Family:
        fam = await self.hub.family(await self._child_id())
        assert fam is not None, "no family yet"
        return fam

    async def _child_id(self) -> str:
        return (await self.child.user_row()).id

    async def parent(self) -> Member:
        p = await self.hub.parent(await self.family())
        assert p is not None
        return p

    # ------------------------------------------------------------------ the DSL
    async def child_says(self, text: str) -> list[str]:
        self.clock.advance(seconds=12)  # a person types; also keeps the pipeline's per-user message limiter calm
        return await self.child.say(text)

    async def child_taps(self, button_id: str, title: str = "") -> list[str]:
        """The child taps a reply button under an alert (the pipeline routes ``rb:<incident>:<action>`` to Robin)."""
        from friday.core.models import InboundMessage, MessageKind

        self.clock.advance(seconds=12)
        n = len(self.child.msgs())
        msg = InboundMessage(channel=self.f.channel.channel, from_phone=CHILD, kind=MessageKind.BUTTON_REPLY, button_id=button_id, text=title or None, provider_message_id=f"sim.btn.{self.next_id()}", received_at=self.clock.now())
        await self.f.rt.handle(msg, raise_errors=True)
        await self.f.settle()
        return [plain(m) for m in self.child.msgs()[n:]]

    async def tap(self, which: str) -> list[str]:
        """Tap the alert button whose action is ``which`` (call | join | safe) on the newest alert."""
        for b in self.child_buttons():
            if b.id.endswith(f":{which}"):
                return await self.child_taps(b.id, b.title)
        raise AssertionError(f"no '{which}' button on any message to the child")

    async def setup_family(self, *, second: str | None = None, checkin: str = "9am", sensitivity: str = "balanced", parent_language: str = "hinglish", child_call_ok: bool = True) -> Family:
        """The child's whole onboarding by chat. At the end the child's consent is on file, the parent has been NOTIFIED (voice note + text) and the family is ACTIVE."""
        await self.child_says("set up Robin for my father")
        await self.child_says(PARENT)
        await self.child_says(parent_language)
        await self.child_says(checkin)
        await self.child_says("ok")  # quiet hours as proposed
        await self.child_says(second or "no")
        await self.child_says(sensitivity)
        await self.child_says("yes" if child_call_ok else "no")  # may Robin ring you?
        return await self.family()

    async def parent_says(self, text: str, via: str = "text"):  # noqa: ANN201
        """What the parent said (voice note already transcribed, or text). The WhatsApp transport that will call ``RobinHub.parent_said`` is not built yet."""
        return await self.hub.parent_said(PARENT, text, via)

    async def advance(self, **delta: float) -> int:
        """Move the fake clock and run one scheduler pass (the same ``RobinHub.tick`` the runtime loop runs)."""
        self.clock.advance(**delta)
        n = await self.hub.tick()
        await self.f.settle()
        return n

    async def run_to(self, hour: int, minute: int = 0) -> None:
        self.clock.set(self.clock.now().replace(hour=hour, minute=minute, second=0, microsecond=0))

    # ------------------------------------------------------------------ what happened
    def child_msgs(self):  # noqa: ANN201
        return self.child.msgs()[self.mark :]

    def child_texts(self) -> list[str]:
        """What the child's phone showed since Robin started (Friday's own onboarding chat is left out)."""
        return [plain(m) for m in self.child_msgs()]

    def child_buttons(self) -> list[ReplyButton]:
        for m in reversed(self.child_msgs()):
            if m.buttons:
                return list(m.buttons)
        return []

    def calls(self, role: str | None = None, purpose: str | None = None):  # noqa: ANN201
        return [c for c in self.caller.calls if (role is None or c.role == role) and (purpose is None or c.purpose == purpose)]

    def script_calls(self, *outcomes: CallResult | CallOutcome) -> None:
        self.caller.script(*outcomes)

    async def audit_rows(self) -> list[Any]:
        fam = await self.hub.family(await self._child_id())
        return await self.store.list(fam.id, "audit") if fam else []

    async def audit_blob(self) -> str:
        """The family's 'what Robin did' log AND the core audit log, as one string."""
        parts: list[str] = []
        for r in await self.audit_rows():
            parts.append(json.dumps({"status": r.status, "data": r.data}, default=str, ensure_ascii=False))
        core = await self.f.c.repos.audit.list_for_user(await self._child_id()) if hasattr(self.f.c.repos.audit, "list_for_user") else []
        for e in core or []:
            parts.append(repr(e))
        return "\n".join(parts)

    async def incidents(self) -> list[Any]:
        fam = await self.hub.family(await self._child_id())
        return await self.store.list(fam.id, "incident") if fam else []

    async def authority_records(self) -> list[Any]:
        fam = await self.hub.family(await self._child_id())
        return [r for r in await self.store.list(fam.id, "pending") if (r.key or "").startswith("auth:")] if fam else []

    def assert_no_pii(self, extra_blob: str = "", **kw: Any) -> None:
        assert_no_pii(self.logs.text() + "\n" + extra_blob, secrets=tuple(self.secrets), **kw)

    async def consent_device(self) -> None:
        """The child (admin) switches the phone signals and payment alerts on, in chat; the parent's soft approval is the notification they already got."""
        await self.child_says("enable device signals")
        await self.child_says("enable payment alerts")


def line(key: str, lang: str = "en", **slots: str) -> str:
    """The fixed Robin line as the child (English chat) or the parent would read it. Tests compare against the line table, not copies of its words."""
    from friday.robin import lines

    slots.setdefault("parent", "Papa")
    slots.setdefault("child", "ji")
    return lines.say(key, lang, brand="Robin", **slots)


def index_of(texts: list[str], expected: str, start: int = 0) -> int:
    """Position of the first message at or after ``start`` that equals/contains ``expected`` (fails with a short list of what was there)."""
    for i in range(start, len(texts)):
        if expected in texts[i]:
            return i
    raise AssertionError(f"message not found: {expected[:70]!r}; got {[t[:50] for t in texts[start:]]}")


def parents_of(members: list[Member]) -> list[Member]:
    return [m for m in members if m.role == Role.PARENT]
