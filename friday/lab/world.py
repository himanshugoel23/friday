"""The lab's world: the real pipeline over a fake WhatsApp, a fake clock and simulated callees.

Built like ``friday consumer demo``/the integration tests (simulator container, in-memory SQLite,
the consumer stack with a ``PersonaTelephony`` line), plus invented saved users, a turn tracer and
a per-user chat log with message ids for the page.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from friday.api.runtime import Runtime
from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.core.clock import IST, FakeClock, ist_date, to_ist
from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import (
    Consent,
    ConsentKind,
    InboundMessage,
    Language,
    LocationPin,
    MessageKind,
    OutboundMessage,
    Profile,
    User,
    UserStatus,
    normalize_phone,
)
from friday.db import Database
from friday.integration.sim import PersonaTelephony, demo_card_rules
from friday.integration.wiring import attach, build_stack
from friday.lab.safety import (
    assert_no_live_channel,
    environment_settings,
    is_fake_number,
    lab_settings,
)
from friday.lab.trace import Tracer
from friday.savings.config import SavingsConfig

# callee personas offered in the page: label -> W2 persona id (friday/liveagent/simulation)
PERSONAS: dict[str, tuple[str, str]] = {
    "friendly_elder": ("Friendly elder", "friendly_elder"),
    "busy": ("Busy (gives a time to call back)", "busy_gives_time"),
    "hostile": ("Hostile (abuses, says shut up)", "hostile_abuser"),
    "wrong_number": ("Wrong number", "wrong_number"),
    "voicemail": ("Voicemail (greeting, beep)", "voicemail_with_beep"),
    "are_you_a_bot": ("Asks 'are you a bot?'", "are_you_a_bot_then_ok"),
}
DEFAULT_PERSONA = "friendly_elder"

# invented contact cards offered by the attach menu (callee range +919000......)
CONTACT_PRESETS: list[dict[str, str]] = [
    {"name": "Neha (invented)", "number": "+919000000010"},
    {"name": "Kabir (invented)", "number": "+919000000011"},
    {"name": "Meena Aunty (invented)", "number": "+919000000012"},
]
LOCATION_PRESETS: dict[str, tuple[float, float]] = {
    "Gurgaon": (28.4595, 77.0266),
    "Bangalore": (12.9716, 77.5946),
    "Mumbai": (19.0760, 72.8777),
}
SAMPLE_FILES: dict[str, tuple[str, str]] = {
    "electricity-bill.pdf": ("doc", "application/pdf"),
    "restaurant-receipt.jpg": ("image", "image/jpeg"),
    "visiting-card.jpg": ("image", "image/jpeg"),
}
LATENCY_SWITCHES = (
    "voice_speculative_understanding",
    "llm_stream_to_tts",
    "intent_classifier",
    "voice_semantic_eot",
)
CONSUMER_SWITCHES = {
    "calls": "consumer_calls_enabled",
    "savings": "savings_enabled",
    "lifestate": "lifestate_enabled",
    "google": "google_enabled",
}
MAX_UPLOAD = 5 * 1024 * 1024


@dataclass
class SavedUser:
    key: str
    label: str
    phone: str
    name: str
    language: Language
    morning: bool
    contacts: list[tuple[str, str, str, list[str]]]  # name, number, relationship, nicknames


SAVED_USERS = [
    SavedUser(
        "rahul",
        "Rahul (Hinglish, has contacts)",
        "+919800000001",
        "Rahul",
        Language.HINGLISH,
        True,
        [
            ("Mummy", "+919000000001", "mother", ["mummy", "maa"]),
            ("Papa", "+919000000002", "father", ["papa"]),
            ("Didi", "+919000000003", "sister", ["didi"]),
        ],
    ),
    SavedUser(
        "priya",
        "Priya (English, no morning brief)",
        "+919800000002",
        "Priya",
        Language.EN,
        False,
        [("Mom", "+919000000004", "mother", ["mom", "mummy"])],
    ),
    SavedUser(
        "sunita",
        "Sunita (Hindi, Devanagari)",
        "+919800000003",
        "Sunita",
        Language.HI,
        True,
        [("बेटा", "+919000000005", "son", ["beta", "बेटा"])],
    ),
]


def mask_name(name: str | None) -> str | None:
    if not name:
        return name
    return name[0] + "*" * (len(name) - 1)


def mask_number(phone: str) -> str:
    return phone[:3] + "*" * max(0, len(phone) - 7) + phone[-4:] if len(phone) > 6 else "***"


def _ist_label(dt: datetime) -> str:
    return to_ist(dt).strftime("%d %b %H:%M")


@dataclass
class LabUser:
    key: str
    label: str
    phone: str
    saved: bool
    user_id: str | None = None


class LabError(ValueError):
    """A request the lab refuses (bad number, unknown message, ...). Maps to HTTP 4xx."""


@dataclass
class LabWorld:
    settings: Settings
    c: Container
    channel: SimulatorChannel
    clock: FakeClock
    runtime: Runtime
    router: Any
    telephony: PersonaTelephony
    tracer: Tracer
    env: Settings
    notes_path: Path
    users: list[LabUser] = field(default_factory=list)
    entries: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    turns: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    other_out: list[dict[str, Any]] = field(default_factory=list)
    persona: str = DEFAULT_PERSONA
    llm_mode: str = "fake"
    _seq: int = 0
    _fresh: int = 100_000
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _parts: dict[str, Any] = field(default_factory=dict)
    _fake_llm: Any = None
    _calls_seen: int = 0
    _text_media: dict[str, bytes] = field(default_factory=dict)

    # ------------------------------------------------------------------ building
    @classmethod
    async def create(
        cls,
        *,
        env: Settings | None = None,
        notes_path: Path | str = "var/lab/notes.jsonl",
        start: datetime | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> LabWorld:
        env = env or environment_settings()
        settings = lab_settings(**(overrides or {}))
        today = datetime.now(IST).date()
        clock = FakeClock(start or datetime(today.year, today.month, today.day, 10, 0, tzinfo=IST))
        db = Database(settings.database_url)
        await db.create_all()
        c = Container(settings, clock=clock)
        c.override_db(db)
        c.install_field_cipher()
        channel = SimulatorChannel(clock, dict(settings.whatsapp_templates))
        c.override("messaging", channel)
        c.override("sms", FakeSMS(dict(settings.sms_dlt_templates), clock))
        telephony = PersonaTelephony(default=PERSONAS[DEFAULT_PERSONA][1])

        async def send(user_id: str, text: str, buttons: Sequence[Any]) -> None:
            await c.get("notifier").notify_user(user_id, text, buttons=list(buttons))

        router = build_stack(
            settings=settings, clock=clock, repos=c.repos, send=send, queue=c.get("job_queue"),
            locks=None, telephony=telephony,
            savings_config=SavingsConfig(allow_example_rules=True),
        )  # fmt: skip
        assert router is not None
        c.override("consumer", router)
        runtime = Runtime(c, fast_pin_hash=True)
        attach(router, task_engine=c.get("task_engine"), proactive=c.get("proactive"))
        await runtime.start(background=False)
        assert_no_live_channel(settings, c)
        w = cls(
            settings=settings,
            c=c,
            channel=channel,
            clock=clock,
            runtime=runtime,
            router=router,
            telephony=telephony,
            tracer=Tracer(),
            env=env,
            notes_path=Path(notes_path),
        )
        w._parts = {
            "calls": router.calls,
            "savings": router.savings,
            "lifestate": router.life,
            "google": router.google,
        }
        brain = runtime.pipeline.brain()
        w._fake_llm = getattr(brain, "llm", None)
        w.tracer.install(
            pipeline=runtime.pipeline,
            router=router,
            brain=brain,
            llm_owner=w._fake_llm,
            proactive=c.get("proactive"),
            task_engine=c.get("task_engine"),
        )
        channel.subscribe(w._on_out)
        for rule in demo_card_rules(ist_date(clock.now())):
            await router.savings.rules.upsert(rule)  # INVENTED example rows
        for su in SAVED_USERS:
            await w._seed(su)
        return w

    async def _seed(self, su: SavedUser) -> None:
        repos = self.c.repos
        user = await repos.users.add(User(phone=su.phone, status=UserStatus.ACTIVE))
        await repos.profiles.save(
            Profile(
                user_id=user.id, name=su.name, language=su.language, morning_briefing=su.morning
            )
        )
        await repos.consents.add(
            Consent(
                user_id=user.id,
                kind=ConsentKind.TERMS_PRIVACY,
                granted=True,
                evidence_text="seeded by the Chat Lab",
            )
        )
        for name, number, rel, nicks in su.contacts:
            await self.router.calls.contacts.add(
                user.id, name, number, nicknames=nicks, relationship=rel, confirmed=True
            )
        self.users.append(LabUser(su.key, su.label, su.phone, True, user.id))
        self.entries.setdefault(su.phone, [])
        self.turns.setdefault(su.phone, [])

    async def close(self) -> None:
        self.channel.unsubscribe(self._on_out)
        self.tracer.uninstall()
        await self.runtime.stop()
        await self.c.aclose()
        from friday.core.crypto import set_field_cipher

        set_field_cipher(None)

    # ------------------------------------------------------------------ outbound capture
    def _next(self) -> int:
        self._seq += 1
        return self._seq

    def _on_out(self, msg: OutboundMessage) -> None:
        entry = self._out_entry(msg)
        if any(u.phone == msg.to_phone for u in self.users):
            self.entries.setdefault(msg.to_phone, []).append(entry)
        else:  # a circle member / business / callee: not the tester's chat
            entry["to"] = mask_number(msg.to_phone)
            self.other_out.append(entry)

    def _out_entry(self, msg: OutboundMessage) -> dict[str, Any]:
        lst = getattr(msg, "list_message", None)
        return {
            "seq": self._next(),
            "dir": "out",
            "id": msg.id,
            "at": self.clock.now().isoformat(),
            "time": _ist_label(self.clock.now()),
            "text": msg.text,
            "buttons": [{"id": b.id, "title": b.title} for b in msg.buttons],
            "list": lst,
            "template": msg.template.model_dump() if msg.template else None,
            "media": {"url": msg.media_url, "mime": msg.media_mime} if msg.media_url else None,
            "rendered": self.channel.render(msg),
            "mark": None,
        }

    # ------------------------------------------------------------------ users
    def user_for(self, phone: str) -> LabUser:
        for u in self.users:
            if u.phone == phone:
                return u
        raise LabError("unknown lab user")

    def clean_phone(self, phone: str) -> str:
        phone = phone.strip().replace(" ", "+") if phone.startswith(" ") else phone.strip()
        try:
            p = normalize_phone(phone, self.settings.default_country_code)
        except ValueError:
            raise LabError("invalid phone") from None
        if not is_fake_number(p):
            raise LabError("the lab only accepts its own invented test numbers")
        return p

    async def new_user(self) -> LabUser:
        async with self._lock:
            self._fresh += 1
            phone = f"+919800{self._fresh:06d}"
            u = LabUser(
                f"new{len(self.users) - len(SAVED_USERS) + 1}",
                f"New user {len(self.users) - len(SAVED_USERS) + 1}",
                phone,
                False,
            )
            self.users.append(u)
            self.entries[phone] = []
            self.turns[phone] = []
            return u

    async def reset(self, phone: str) -> None:
        async with self._lock:
            u = self.user_for(phone)
            self.entries[phone] = []
            self.turns[phone] = []
            self.channel._by_phone.pop(phone, None)  # noqa: SLF001 - numbered replies start over
            user = await self.c.repos.users.get_by_phone(phone)
            if user is not None:
                await self.runtime.pipeline.state.clear_pending(user.id)
                for name in ("_intake", "_capture", "_edit"):
                    getattr(self.router, name)._d.pop(user.id, None)  # noqa: SLF001
            u.user_id = user.id if user else None

    # ------------------------------------------------------------------ inbound
    def inbound_text(self, phone: str, text: str) -> InboundMessage:
        return self.channel.make_inbound(phone, text, default_cc=self.settings.default_country_code)

    def inbound_location(self, phone: str, lat: float, lng: float) -> InboundMessage:
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise LabError("latitude/longitude out of range")
        msg = self.inbound_text(phone, "/pin 0,0")
        msg.location = LocationPin(lat=lat, lng=lng)
        return msg

    def inbound_voice(self, phone: str, says: str) -> InboundMessage:
        says = says.strip()
        if not says:
            raise LabError("type what the voice note says")
        return self.inbound_text(phone, f"/voice {says}")

    def inbound_contact(self, phone: str, name: str, number: str) -> InboundMessage:
        number = self.clean_phone(number)
        msg = self.inbound_text(phone, f"/contact {number}")
        msg.text = name.strip() or None  # the WhatsApp adapter puts the card's name here
        return msg

    def inbound_sample(self, phone: str, name: str) -> InboundMessage:
        if name not in SAMPLE_FILES:
            raise LabError("unknown sample file")
        kind, _ = SAMPLE_FILES[name]
        return self.inbound_text(phone, f"/{kind} {name}")

    def inbound_file(self, phone: str, filename: str, mime: str, data: bytes) -> InboundMessage:
        if len(data) > MAX_UPLOAD:
            raise LabError("file too large for the lab (5 MB)")
        kind = MessageKind.DOCUMENT if mime == "application/pdf" else MessageKind.IMAGE
        if mime != "application/pdf" and not mime.startswith("image/"):
            raise LabError("only images and PDFs")
        msg = self.inbound_text(phone, "/image x")
        media = self.channel.put_media(data, mime, filename)
        return msg.model_copy(update={"kind": kind, "media_url": media, "media_mime": mime})

    def inbound_button(self, phone: str, out_id: str, button_id: str) -> InboundMessage:
        for e in reversed(self.entries.get(phone, [])):
            if e["dir"] == "out" and e["id"] == out_id:
                choices = list(e["buttons"])
                if e.get("list"):
                    for sec in e["list"].get("sections", []):
                        choices += sec.get("items", [])
                for b in choices:
                    if b["id"] == button_id:
                        msg = self.inbound_text(phone, "x")
                        return msg.model_copy(
                            update={
                                "kind": MessageKind.BUTTON_REPLY,
                                "text": b["title"],
                                "button_id": b["id"],
                            }
                        )
                raise LabError("that button is not on that message")
        raise LabError("unknown message")

    def _in_entry(self, msg: InboundMessage, label: str) -> dict[str, Any]:
        return {
            "seq": self._next(),
            "dir": "in",
            "id": msg.id,
            "kind": msg.kind.value,
            "at": self.clock.now().isoformat(),
            "time": _ist_label(self.clock.now()),
            "text": msg.text or (label if msg.kind == MessageKind.VOICE_NOTE else None),
            "label": label,
            "button_id": msg.button_id,
            "location": msg.location.model_dump() if msg.location else None,
            "contact_phone": mask_number(msg.contact_phone) if msg.contact_phone else None,
            "status": "sent",
            "mark": None,
        }

    async def send_inbound(self, phone: str, msg: InboundMessage, label: str) -> dict[str, Any]:
        """Run one inbound message through the REAL pipeline; returns the turn."""
        phone = self.clean_phone(phone)
        self.user_for(phone)
        async with self._lock:
            entry = self._in_entry(msg, label)
            self.entries[phone].append(entry)
            first_out = len(self.entries[phone])
            calls_before = len(self._call_results())
            async with self.tracer.turn(f"{msg.kind.value}: {label[:60]}") as t:
                entry["status"] = "delivered"
                await self.runtime.handle(msg)
                await self._settle()
            entry["status"] = "read"
            turn = self._finish_turn(phone, t, entry, first_out, calls_before)
            return turn

    def _call_results(self) -> list[Any]:
        calls = self.router.calls
        return list(calls.orchestrator.engine.results) if calls is not None else []

    async def _settle(self) -> None:
        """Run the jobs the message created (an approved call runs now, on the fake line)."""
        await self.c.get("task_engine").drain()

    def _finish_turn(
        self,
        phone: str,
        t: dict[str, Any],
        entry: dict[str, Any],
        first_out: int,
        calls_before: int,
    ) -> dict[str, Any]:
        outs = [e for e in self.entries[phone][first_out:] if e["dir"] == "out"]
        t["input_seq"] = entry["seq"]
        t["output_seqs"] = [e["seq"] for e in outs]
        t["outputs"] = [
            {"text": e["text"], "buttons": [b["title"] for b in e["buttons"]]} for e in outs
        ]
        results = self._call_results()
        t["calls"] = []
        for r in results[calls_before:] if len(results) >= calls_before else results:
            t["calls"].append(
                {
                    "persona": self.persona,
                    "status": r.outcome.status.value,
                    "summary": r.outcome.summary,
                    "duration_s": r.duration_s,
                    "transcript": [
                        {"speaker": x.speaker, "text": x.text, "move": x.move} for x in r.transcript
                    ],
                    "guards": [
                        {"kind": ev.kind, "detail": ev.detail}
                        for ev in r.events
                        if ev.kind in ("guard", "hard_stop", "policy_rejected")
                    ],
                }
            )
        t["clock"] = self.clock.now().isoformat()
        t["llm_mode"] = self.llm_mode
        self.turns[phone].append(t)
        return t

    # ------------------------------------------------------------------ clock
    async def advance(self, phone: str, how: str) -> dict[str, Any]:
        """Move the fake clock, then run what a server would have run by then: the proactive
        engine, the consumer periodic pass and the job queue."""
        phone = self.clean_phone(phone)
        self.user_for(phone)
        async with self._lock:
            now = self.clock.now()
            if how == "hour":
                self.clock.advance(hours=1)
                label = "clock +1 hour"
            elif how == "morning":
                ist = to_ist(now)
                target = ist.replace(hour=8, minute=10, second=0, microsecond=0)
                if target <= ist:
                    target += timedelta(days=1)
                self.clock.set(target)
                label = "clock to next morning 08:10"
            else:
                raise LabError("how must be 'hour' or 'morning'")
            first_out = len(self.entries[phone])
            calls_before = len(self._call_results())
            entry = {
                "seq": self._next(),
                "dir": "sys",
                "at": self.clock.now().isoformat(),
                "time": _ist_label(self.clock.now()),
                "text": f"{label} -> {_ist_label(self.clock.now())}",
                "mark": None,
            }
            self.entries[phone].append(entry)
            first_out = len(self.entries[phone])
            async with self.tracer.turn(label) as t:
                await self.c.get("proactive").tick()
                await self.router.periodic()
                await self.c.get("task_engine").drain()
            return self._finish_turn(phone, t, entry, first_out, calls_before)

    # ------------------------------------------------------------------ controls
    def set_persona(self, key: str) -> None:
        if key not in PERSONAS:
            raise LabError("unknown persona")
        self.persona = key
        self.telephony.default = PERSONAS[key][1]

    def set_switch(self, name: str, on: bool) -> None:
        if name in CONSUMER_SWITCHES:
            if name == "google":
                raise LabError("Google needs a Google Cloud project: not available in the lab")
            setattr(
                self.router,
                {"lifestate": "life"}.get(name, name),
                self._parts[name] if on else None,
            )
            setattr(self.settings, CONSUMER_SWITCHES[name], on)
        elif name in LATENCY_SWITCHES:
            setattr(self.settings, name, on)
        else:
            raise LabError("unknown switch")

    def switches(self) -> dict[str, Any]:
        s = self.settings
        return {
            "consumer": {
                k: {
                    "on": bool(getattr(self.router, {"lifestate": "life"}.get(k, k))),
                    "env": f"FRIDAY_{CONSUMER_SWITCHES[k].upper()}",
                    "available": k != "google",
                }
                for k in CONSUMER_SWITCHES
            },
            "latency": {
                k: {"on": bool(getattr(s, k)), "env": f"FRIDAY_{k.upper()}"}
                for k in LATENCY_SWITCHES
            },
            "latency_note": "These change the voice-call path only; chat replies are not affected.",
        }

    def real_llm_available(self) -> bool:
        return bool(self.env.llm_key_configured())

    def set_llm(self, mode: str) -> None:
        brain = self.runtime.pipeline.brain()
        if mode == "fake":
            brain.llm = self._fake_llm
            self.llm_mode = "fake"
            return
        if mode != "real":
            raise LabError("llm must be 'fake' or 'real'")
        if not self.real_llm_available():
            raise LabError("no language-model key in the environment")
        real_settings = self.env.model_copy(update={"mode": "simulator"})
        real_c = Container(real_settings, clock=self.clock)
        real = real_c.llm
        brain.llm = real
        self.tracer._wrap_llm(real)  # noqa: SLF001
        self.llm_mode = "real"

    # ------------------------------------------------------------------ panel state
    async def user_state(self, phone: str) -> dict[str, Any]:
        lu = self.user_for(phone)
        repos = self.c.repos
        user = await repos.users.get_by_phone(phone)
        out: dict[str, Any] = {
            "key": lu.key,
            "label": lu.label,
            "saved": lu.saved,
            "phone": mask_number(phone),
            "exists": user is not None,
        }
        if user is None:
            out["note"] = "No account yet: the first message starts onboarding."
            return out
        prof = await repos.profiles.get_or_default(user.id)
        consent = await repos.consents.latest(user.id, ConsentKind.TERMS_PRIVACY)
        out.update(
            {
                "status": user.status.value,
                "onboarding_step": user.onboarding_step.value,
                "pin_set": bool(user.pin_hash),
                "consent_terms": bool(consent and consent.granted),
                "language": prof.language.value,
                "tone": prof.tone.value,
                "name": mask_name(prof.name),
                "city": prof.city,
                "morning_briefing": prof.morning_briefing,
            }
        )
        life = self.router.life
        if life is not None:
            events = await life.store.list_events(user.id, include_inactive=False)
            out["life_events"] = [
                {
                    "kind": getattr(e.kind, "value", str(e.kind)),
                    "title": e.title,
                    "start": _ist_label(e.start) if getattr(e, "start", None) else None,
                }
                for e in events[:10]
            ]
        calls = self.router.calls
        if calls is not None:
            contacts = await calls.contacts.list(user.id) if hasattr(calls.contacts, "list") else []
            out["contacts"] = [getattr(c, "name", "?") for c in contacts][:10]
        out["window_24h_open"] = bool(
            user.last_inbound_at and self.clock.now() - user.last_inbound_at < timedelta(hours=24)
        )
        return out

    def clock_info(self) -> dict[str, str]:
        now = self.clock.now()
        return {"iso": now.isoformat(), "label": _ist_label(now)}

    def config(self) -> dict[str, Any]:
        return {
            "users": [
                {
                    "key": u.key,
                    "label": u.label,
                    "phone": u.phone,
                    "masked": mask_number(u.phone),
                    "saved": u.saved,
                }
                for u in self.users
            ],
            "personas": {k: v[0] for k, v in PERSONAS.items()},
            "persona": self.persona,
            "contact_presets": CONTACT_PRESETS,
            "location_presets": {
                k: {"lat": v[0], "lng": v[1]} for k, v in LOCATION_PRESETS.items()
            },
            "sample_files": list(SAMPLE_FILES),
            "chips": CHIPS,
            "llm": {"mode": self.llm_mode, "real_available": self.real_llm_available()},
            "clock": self.clock_info(),
            "mode": "simulator",
        }

    # ------------------------------------------------------------------ notes and export
    def mark_wrong(self, phone: str, seq: int, note: str) -> dict[str, Any]:
        self.user_for(phone)
        target = next((e for e in self.entries[phone] if e["seq"] == seq), None)
        if target is None:
            raise LabError("unknown message")
        target["mark"] = "wrong"
        turn = next((t for t in self.turns[phone] if seq in t.get("output_seqs", [])), None)
        record = {
            "at": self.clock.now().isoformat(),
            "user": self.user_for(phone).key,
            "reply": {
                "text": target.get("text"),
                "buttons": [b["title"] for b in target.get("buttons", [])],
            },
            "input": next(
                (
                    e.get("text")
                    for e in self.entries[phone]
                    if turn and e["seq"] == turn.get("input_seq")
                ),
                None,
            ),
            "route": (turn or {}).get("route"),
            "intent": ((turn or {}).get("interpretation") or {}).get("intent"),
            "note": note.strip()[:1000],
        }
        self.notes_path.parent.mkdir(parents=True, exist_ok=True)
        with self.notes_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def export(self, phone: str) -> dict[str, Any]:
        self.user_for(phone)
        return {
            "lab": "Friday Chat Lab export (simulator; fake clock, fake calls)",
            "exported_at_fake_clock": self.clock.now().isoformat(),
            "user": self.user_for(phone).label,
            "llm_mode": self.llm_mode,
            "persona": self.persona,
            "switches": self.switches(),
            "messages": [
                {k: v for k, v in e.items() if k != "rendered"} for e in self.entries[phone]
            ],
            "turns": self.turns[phone],
        }

    def export_markdown(self, phone: str) -> str:
        data = self.export(phone)
        lines = [
            "# Friday Chat Lab transcript",
            "",
            f"- user: {data['user']}",
            f"- fake clock at export: {data['exported_at_fake_clock']}",
            f"- language model: {data['llm_mode']}; callee persona: {data['persona']}",
            "- everything here is simulated: no WhatsApp message, call or real number was involved",
            "",
            "## Chat",
            "",
        ]
        for e in data["messages"]:
            who = {"in": "You", "out": "Friday", "sys": "Lab"}[e["dir"]]
            body = e.get("text") or e.get("label") or ""
            if e.get("kind") and e["kind"] != "text":
                body = f"[{e['kind']}] {body}"
            flag = "  **[marked wrong]**" if e.get("mark") == "wrong" else ""
            lines.append(f"- {e['time']} **{who}**: {body}{flag}")
            for b in e.get("buttons") or []:
                lines.append(f"    - button `{b['id']}`: {b['title']}")
        lines += ["", "## Inside each turn", ""]
        for i, t in enumerate(data["turns"], start=1):
            lines.append(f"### Turn {i}: {t['label']}")
            lines.append(f"- route: {t['route']['label']} ({t['answered_by']})")
            ip = t.get("interpretation")
            if ip:
                lines.append(f"- intent: {ip['intent']} (confidence {ip['confidence']})")
            if t.get("slots"):
                lines.append(f"- slots: `{json.dumps(t['slots'], ensure_ascii=False)}`")
            for g in t["guards"]:
                lines.append(f"- guard {g['gate']}: {g['verdict']} {g['reasons']}")
            lines.append(f"- latency ms: {t['latency_ms']}")
            if t["copy_keys"]:
                lines.append(f"- wording still pending approval: {', '.join(t['copy_keys'])}")
            for call in t.get("calls", []):
                lines.append(
                    f"- simulated call ({call['persona']}): {call['status']}: {call['summary']}"
                )
            lines.append("")
        return "\n".join(lines)


CHIPS: list[dict[str, str]] = [
    {"label": "hi (first run)", "text": "hi", "note": "use with New user"},
    {"label": "mummy ko call", "text": "mummy ko call karke bata do ki main late hoon"},
    {"label": "cards", "text": "HDFC Regalia aur SBI Cashback hai"},
    {"label": "Zomato pe 640", "text": "Zomato pe 640"},
    {"label": "interview kal", "text": "kal 2 baje interview hai"},
    {"label": "mera din", "text": "mera din"},
    {"label": "menu", "text": "menu"},
    {"label": "delete everything", "text": "delete everything"},
    # Devanagari example row (shown on its own line)
    {"label": "कल 2 बजे interview है", "text": "कल 2 बजे interview है", "row": "2"},
    {"label": "मम्मी को कॉल करके बता दो", "text": "मम्मी को कॉल करके बता दो कि मैं लेट हूँ", "row": "2"},
    {"label": "मेरा दिन", "text": "मेरा दिन", "row": "2"},
]
