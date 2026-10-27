"""``friday doctor``: one read-only command that proves the foundation works.

It places no call, sends no message and spends no money. Every line is ``[ OK ]``, ``[WARN]``,
``[FAIL]`` or ``[SKIP]``; the exit code is 1 when anything FAILED. Output never contains a secret:
only variable NAMES and ok/missing/unsafe, and a final scrub removes any configured secret value
that might have slipped into a message (defence in depth). What each line means:
``docs/DOCTOR.md``.

    friday doctor [--offline] [--json] [--section NAME]
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from friday.core.config import Settings

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIPPED"
TAGS = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]", SKIP: "[SKIP]"}
SECTIONS = (
    "settings", "database", "services", "public_url", "providers", "switches", "off_switch",
    "systemd", "receptionist", "browser",
)
TITLES = {
    "settings": "1. settings",
    "database": "2. database",
    "services": "3. redis and object store",
    "public_url": "4. public URL and WhatsApp handshake",
    "providers": "5. providers (read-only)",
    "switches": "6. switches",
    "off_switch": "7. off switch (kill switch)",
    "systemd": "8. service (systemd)",
    "receptionist": "9. receptionist (missed-call forwarding)",
    "browser": "10. private browser",
}
# chain 0006 -> 0007_consumer_calls -> 0008_savings_engine -> 0009_life_state -> 0010_chatbot
# -> 0011_receptionist -> 0012_receptionist_spam -> 0013_evidence -> 0014_documents
# -> (0015_urgent_escalation, built in parallel; not in this branch) -> 0016_family_drive
# must be in the code
EXPECTED_HEAD_CHAIN = "0016_family_drive"
DEV_VERIFY_TOKEN = "friday-dev-verify"  # noqa: S105 - the public development default
RLS_SQL = Path(__file__).resolve().parents[2] / "deploy" / "supabase" / "rls.sql"
GRAPH_BASE = "https://graph.facebook.com"
HTTP_TIMEOUT_S = 15.0


@dataclass
class Check:
    status: str
    message: str


@dataclass
class Section:
    name: str
    checks: list[Check] = field(default_factory=list)

    def add(self, status: str, message: str) -> None:
        self.checks.append(Check(status, message))


@dataclass
class Probes:
    """Everything that touches the outside world, replaceable in tests."""

    transport: httpx.AsyncBaseTransport | None = None
    redis_ping: Callable[[str], Awaitable[None]] | None = None
    object_store_check: Callable[[str], Awaitable[None]] | None = None
    run_command: Callable[[list[str]], tuple[int, str]] | None = None
    systemctl_present: Callable[[], bool] | None = None
    graph_base: str = GRAPH_BASE
    vobiz_transport: httpx.AsyncBaseTransport | None = None


# ----------------------------------------------------------------------------- helpers
def _secret_values(settings: Settings) -> list[str]:
    from pydantic import SecretStr

    values: list[str] = []
    for name in type(settings).model_fields:
        v = getattr(settings, name, None)
        if isinstance(v, SecretStr) and len(v.get_secret_value()) >= 4:
            values.append(v.get_secret_value())
    for name in ("database_url", "redis_url"):
        url = getattr(settings, name, None) or ""
        m = re.match(r"^[a-z+0-9]+://[^:/@]+:([^@]+)@", url)
        if m and len(m.group(1)) >= 4:
            values.append(m.group(1))
    return sorted(set(values), key=len, reverse=True)


def scrub(text: str, secret_values: list[str]) -> str:
    for s in secret_values:
        text = text.replace(s, "***")
    return text


def _exc(e: BaseException) -> str:
    return type(e).__name__  # never str(e): HTTP errors can carry the request URL


def _client(probes: Probes) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_S, transport=probes.transport, follow_redirects=False
    )


def _script_directory() -> Any:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from friday.db.migrate import SCRIPT_LOCATION

    cfg = Config()
    cfg.set_main_option("script_location", SCRIPT_LOCATION)
    return ScriptDirectory.from_config(cfg)


# ----------------------------------------------------------------------------- 1 settings
def check_settings(settings: Settings) -> Section:
    from friday.core.container import Container

    s = Section("settings")
    s.add(OK if settings.is_live else WARN, f"FRIDAY_MODE={settings.mode}"
          + ("" if settings.is_live else " (not live: real calls and WhatsApp stay simulated)"))
    try:
        missing_components = Container(settings).missing_role_components()
    except Exception as e:  # noqa: BLE001
        missing_components = []
        s.add(FAIL, f"could not wire the components ({_exc(e)}); run `friday check`")
    if missing_components:
        s.add(FAIL, "components needed by the roles but not implemented: "
              + ", ".join(missing_components))
    if not settings.is_live:
        s.add(SKIP, "live configuration is only checked in live mode (FRIDAY_MODE=live)")
        return s
    problems = settings.live_problems()
    if not problems:
        s.add(OK, "all required live settings are present and safe")
    for p in problems:
        if p.startswith("missing "):
            s.add(FAIL, f"missing: {p.removeprefix('missing ')}")
        else:
            s.add(FAIL, f"unsafe or invalid: {p}")
    for note in settings.optional_feature_notes():
        s.add(WARN, f"disabled or simulated: {note}")
    return s


# ----------------------------------------------------------------------------- 2 database
def rls_table_names(path: Path = RLS_SQL) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"ALTER TABLE public\.(\w+) ENABLE ROW LEVEL SECURITY", text)))


def evaluate_rls(expected: list[str], flags: dict[str, bool]) -> tuple[list[str], list[str]]:
    """(tables whose RLS is OFF, tables that do not exist). Pure, for tests."""
    absent = [t for t in expected if t not in flags]
    off = [t for t in expected if t in flags and not flags[t]]
    return off, absent


def code_head() -> str:
    return _script_directory().get_current_head() or ""


def known_revisions() -> set[str]:
    return {r.revision for r in _script_directory().walk_revisions()}


async def check_database(settings: Settings) -> Section:
    from sqlalchemy import inspect, text

    import friday.db.tables  # noqa: F401  (register tables)
    from friday.db.base import Base
    from friday.db.session import Database

    s = Section("database")
    url = settings.database_url
    is_pg = url.startswith(("postgresql", "postgres://"))
    s.add(OK, f"database kind: {'PostgreSQL' if is_pg else 'SQLite (single file, dev only)'}")
    db = Database(url)
    flags: dict[str, bool] = {}
    try:
        try:
            async with db.engine.connect() as conn:
                await conn.execute(text("select 1"))
                s.add(OK, "connected and ran a trivial query")
                try:
                    rows = (await conn.execute(text("select version_num from alembic_version"))
                            ).all()
                    current = rows[0][0] if rows else None
                except Exception:  # noqa: BLE001 - table absent: migrations never ran
                    await conn.rollback()
                    current = None
                tables = set(await conn.run_sync(lambda c: set(inspect(c).get_table_names())))
                if is_pg:
                    res = await conn.execute(text(
                        "select c.relname, c.relrowsecurity from pg_class c "
                        "join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname = 'public' and c.relkind in ('r', 'p')"
                    ))
                    flags = {r[0]: bool(r[1]) for r in res.all()}
        except Exception as e:  # noqa: BLE001
            s.add(FAIL, f"cannot connect with FRIDAY_DATABASE_URL ({_exc(e)}): check the URL, "
                  "password and that the database is reachable from this machine")
            return s
    finally:
        await db.dispose()
    head = code_head()
    if EXPECTED_HEAD_CHAIN not in known_revisions():
        s.add(WARN, f"this code does not contain migration {EXPECTED_HEAD_CHAIN}: "
              "the server has an older version of Friday than expected")
    if current is None:
        s.add(FAIL, f"migrations have never been applied (code head is {head}); "
              "run: uv run python -m friday.db.migrate up")
    elif current == head:
        s.add(OK, f"migration level is at head ({head})")
    else:
        s.add(FAIL, f"migration mismatch: database at {current}, code expects {head}; "
              "run: uv run python -m friday.db.migrate up")
    expected = sorted(Base.metadata.tables)
    missing = [t for t in expected if t not in tables]
    if missing:
        s.add(FAIL, f"{len(missing)} expected table(s) missing: " + ", ".join(missing))
    else:
        s.add(OK, f"all {len(expected)} expected tables exist")
    if not is_pg:
        s.add(SKIP, "row level security applies to PostgreSQL only; this database is SQLite")
        return s
    off, absent = evaluate_rls(rls_table_names(), flags)
    absent = [t for t in absent if t not in missing]  # already reported above
    if off:
        s.add(FAIL, "row level security is OFF on: " + ", ".join(off)
              + "; run: uv run python -m friday.db.migrate rls")
    else:
        s.add(OK, "row level security is ON for every table listed in deploy/supabase/rls.sql")
    if absent:
        s.add(WARN, "tables in deploy/supabase/rls.sql not present in the database: "
              + ", ".join(absent))
    return s


# ----------------------------------------------------------------------------- 3 services
async def _default_redis_ping(url: str) -> None:
    import redis.asyncio as aioredis

    client = aioredis.from_url(url, socket_connect_timeout=5, socket_timeout=5)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _default_object_store_check(url: str) -> None:
    from urllib.parse import urlparse

    u = urlparse(url)
    if u.scheme != "s3":
        raise ValueError("not an s3:// URL")

    def head() -> None:
        import boto3

        boto3.client("s3").head_bucket(Bucket=u.netloc)

    await asyncio.to_thread(head)


async def check_services(settings: Settings, offline: bool, probes: Probes) -> Section:
    s = Section("services")
    for label, name, value, fn in (
        ("redis", "FRIDAY_REDIS_URL", settings.redis_url,
         probes.redis_ping or _default_redis_ping),
        ("object store", "FRIDAY_OBJECT_STORE_URL", settings.object_store_url,
         probes.object_store_check or _default_object_store_check),
    ):
        if not value:
            s.add(SKIP, f"{label}: {name} not configured")
        elif offline:
            s.add(SKIP, f"{label}: configured ({name}); reachability skipped (--offline)")
        else:
            try:
                await fn(value)
                s.add(OK, f"{label}: reachable")
            except Exception as e:  # noqa: BLE001
                s.add(FAIL, f"{label}: {name} is set but not reachable ({_exc(e)})")
    return s


# ----------------------------------------------------------------------------- 4 public URL
async def check_public_url(settings: Settings, offline: bool, probes: Probes) -> Section:
    s = Section("public_url")
    base = settings.public_base_url.rstrip("/")
    bad_status = FAIL if settings.is_live else WARN
    problem = settings.public_url_problem()
    if problem:
        s.add(bad_status, problem)
    if offline:
        s.add(SKIP, "public URL requests skipped (--offline)")
        return s
    if problem:
        s.add(SKIP, "not requesting an address that cannot receive provider webhooks")
        return s
    async with _client(probes) as http:
        try:
            r = await http.get(f"{base}/health")
        except httpx.HTTPError as e:
            s.add(FAIL, f"GET /health could not be reached ({_exc(e)}): is Friday running, and "
                  "does the domain point at this server?")
            return s
        body_ok = False
        with contextlib.suppress(ValueError):
            body_ok = r.status_code == 200 and r.json().get("status") == "ok"
        s.add(OK if body_ok else FAIL,
              "GET /health answered ok over https" if body_ok
              else f"GET /health answered HTTP {r.status_code} without status ok")
        hsts = "strict-transport-security" in {k.lower() for k in r.headers}
        s.add(OK if hsts else WARN,
              "HSTS header present" if hsts
              else "HSTS header missing (https works; add it in the web server config)")
        if settings.resolve_whatsapp() != "cloud" and not settings.is_live:
            s.add(SKIP, "WhatsApp handshake: WhatsApp is simulated in this mode")
            return s
        token = settings.whatsapp_verify_token.get_secret_value()
        if token == DEV_VERIFY_TOKEN:
            s.add(FAIL, "WHATSAPP_VERIFY_TOKEN is still the development default (unsafe); "
                  "the handshake was not attempted")
            return s
        challenge = secrets.token_hex(8)
        try:  # the token goes to Friday's own URL only
            r = await http.get(f"{base}/webhooks/whatsapp", params={
                "hub.mode": "subscribe", "hub.verify_token": token, "hub.challenge": challenge})
        except httpx.HTTPError as e:
            s.add(FAIL, f"WhatsApp handshake request failed ({_exc(e)})")
            return s
        if r.status_code == 200 and r.text.strip() == challenge:
            s.add(OK, "WhatsApp webhook handshake answered the challenge")
        elif r.status_code == 403:
            s.add(FAIL, "WhatsApp handshake refused (HTTP 403): the verify token on the server "
                  "differs from WHATSAPP_VERIFY_TOKEN here, or the server runs old settings")
        else:
            s.add(FAIL, f"WhatsApp handshake gave HTTP {r.status_code} and did not echo the "
                  "challenge")
    return s


# ----------------------------------------------------------------------------- 5 providers
async def check_providers(settings: Settings, offline: bool, probes: Probes) -> Section:
    s = Section("providers")
    s.add(OK if settings.anthropic_api_key else WARN,
          "ANTHROPIC_API_KEY is " + ("set (presence only, no paid call)"
                                     if settings.anthropic_api_key else "missing"))
    s.add(OK if settings.sarvam_api_key else WARN,
          "SARVAM_API_KEY is " + ("set (presence only, no paid call)"
                                  if settings.sarvam_api_key else "missing"))
    token = settings.whatsapp_access_token
    pid = settings.whatsapp_phone_number_id
    if not (token and pid):
        s.add(WARN, "Meta: WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID not both set")
    elif offline:
        s.add(SKIP, "Meta token check skipped (--offline)")
    else:
        url = f"{probes.graph_base}/{settings.whatsapp_api_version}/{pid}"
        try:
            async with _client(probes) as http:
                r = await http.get(url, params={"fields": "id"},
                                   headers={"Authorization": f"Bearer {token.get_secret_value()}"})
            if r.status_code == 200 and r.json().get("id"):
                s.add(OK, "Meta token is valid and can read the phone number object")
            elif r.status_code in (400, 401, 403):
                code = (r.json().get("error") or {}).get("code") if r.content else None
                s.add(FAIL, f"Meta refused the token or phone number id (HTTP {r.status_code}"
                      + (f", error code {code}" if isinstance(code, int) else "")
                      + "): the token expired or lacks access; create a new system-user token")
            else:
                s.add(WARN, f"Meta answered HTTP {r.status_code}; try again later")
        except (httpx.HTTPError, ValueError) as e:
            s.add(WARN, f"Meta could not be reached ({_exc(e)})")
    auth_id, auth_tok = settings.sarvam_telephony_auth_id, settings.sarvam_telephony_auth_token
    if not (auth_id and auth_tok):
        s.add(WARN, "Vobiz: SARVAM_TELEPHONY_AUTH_ID / _AUTH_TOKEN not set")
    elif offline:
        s.add(SKIP, "Vobiz account read skipped (--offline)")
    else:
        from friday.voice.telephony.vobiz_probe import DEFAULT_BASE_URL, fetch_probe

        try:
            p = await fetch_probe(
                auth_id, auth_tok.get_secret_value(),
                base_url=settings.sarvam_telephony_base_url or DEFAULT_BASE_URL,
                transport=probes.vobiz_transport,
                caller_ids=list(settings.sarvam_caller_ids or settings.friday_numbers or []),
            )
            s.add(OK, f"Vobiz account readable: balance {p['balance']} {p['currency']}, "
                  f"{len(p['numbers'])} number(s)")
            for issue in p["issues"]:
                s.add(WARN, f"Vobiz: {issue}")
        except Exception as e:  # noqa: BLE001
            s.add(FAIL, f"Vobiz account could not be read ({_exc(e)}): check the Auth ID/token")
    return s


# ----------------------------------------------------------------------------- 6 switches
def check_switches(settings: Settings) -> Section:
    s = Section("switches")
    s.add(OK, f"FRIDAY_MODE={settings.mode}")
    for name, on in (
        ("FRIDAY_CONSUMER_CALLS_ENABLED", settings.consumer_calls_enabled),
        ("FRIDAY_SAVINGS_ENABLED", settings.savings_enabled),
        ("FRIDAY_LIFESTATE_ENABLED", settings.lifestate_enabled),
        ("FRIDAY_GOOGLE_ENABLED", settings.google_enabled),
        ("FRIDAY_PROOF_ENABLED", settings.proof_enabled),
        ("FRIDAY_DOCS_ENABLED", settings.docs_enabled),
        ("FRIDAY_FAMILY_DRIVE_ENABLED", settings.family_drive_enabled),
        ("FRIDAY_VOICE_NOTE_REPLIES", settings.voice_note_replies),
        ("FRIDAY_DEVANAGARI_INPUT", settings.devanagari_input),
    ):
        s.add(OK, f"{name}={'on' if on else 'off'}")
    if settings.family_drive_enabled:
        s.add(
            WARN,
            "FRIDAY_FAMILY_DRIVE_ENABLED is on: it adds the Google drive.file scope to new "
            "consents. The Drive consent paragraph and every line in friday/familydrive/copy.py "
            "(including the folder names created in the user's Drive) are PENDING founder "
            "approval, and the Drive facts are UNVERIFIED until the real-account spike in "
            "docs/FAMILY_DRIVE.md",
        )
        if settings.family_drive_sharing_enabled:
            s.add(
                WARN,
                "FRIDAY_FAMILY_DRIVE_SHARING_ENABLED is on: sharing the folder needs the "
                "owner's approval each time",
            )
        if not settings.google_oauth_client_id:
            s.add(WARN, "family Drive is on but GOOGLE_OAUTH_CLIENT_ID is not set")
    # ffmpeg makes the spoken reply WhatsApp-ready (Ogg/Opus) and decodes incoming voice notes
    if shutil.which("ffmpeg"):
        s.add(OK, "ffmpeg is installed (voice notes in and out)")
    else:
        s.add(
            WARN if settings.voice_note_replies else OK,
            "ffmpeg is MISSING: install it with 'apt-get install -y ffmpeg' (the installer does); "
            + (
                "voice-note replies will fall back to text"
                if settings.voice_note_replies
                else "it is needed once FRIDAY_VOICE_NOTE_REPLIES is turned on"
            ),
        )
    # human-like voice switches (docs/HUMAN_VOICE.md): every one reported ON or OFF, by name
    from friday.human.profile import switch_report, vad_effective

    s.add(OK, f"voice profile: {settings.voice_profile}")
    for env, kind, on, note in switch_report(settings):
        s.add(OK, f"{env}={'on' if on else 'off'} ({kind}){' - ' + note if note else ''}")
    if settings.voice_vad_backend == "silero" and vad_effective(settings) != "silero":
        s.add(WARN, "silero VAD requested but the 'vad' extra is not installed: running on the "
                    "energy rule (automatic fallback). Install with: uv sync --extra vad")
    n = len(settings.pilot_allowed_numbers)
    s.add(OK, f"pilot allow-list: {n} number(s)")
    if settings.is_live and settings.consumer_calls_enabled and n == 0:
        s.add(WARN, "consumer calls are on but the allow-list is empty")
    redirect = bool(settings.vendor_call_redirect_to)
    s.add(OK, "vendor-call redirect: " + (
        "SET (vendor calls ring the test number instead)" if redirect else "not set"))
    return s


# ----------------------------------------------------------------------------- 7 off switch
class _StubContainer:
    """Just enough of a Container for ``install_pause_guard``: one fake telephony."""

    def __init__(self, settings: Settings, telephony: Any) -> None:
        self.settings = settings
        self._tel = telephony

    def role_components(self) -> list[str]:
        return ["telephony"]

    def get(self, name: str) -> Any:
        return self._tel


async def check_off_switch(settings: Settings) -> Section:
    from friday.pause import (
        PausedError,
        install_pause_guard,
        is_paused,
        pause_status,
        set_paused,
    )

    s = Section("off_switch")
    live_state = pause_status(settings)
    paused_now = is_paused(settings)
    s.add(WARN if paused_now else OK,
          "kill switch right now: " + ("PAUSED (Friday is not placing calls)" if paused_now
                                       else "RUNNING"))
    with tempfile.TemporaryDirectory(prefix="friday-doctor-") as tmp:
        scoped = settings.model_copy(update={"pause_file": str(Path(tmp) / "PAUSED"),
                                             "paused": False})
        placed: list[str] = []

        class FakeTelephony:
            async def place_call(self, request: Any, *a: Any, **k: Any) -> str:
                placed.append("x")
                return "fake-call"

        tel = FakeTelephony()
        guarded = install_pause_guard(_StubContainer(scoped, tel))
        if "telephony.place_call" not in guarded:
            s.add(FAIL, "the pause guard did not wrap the dial path")
            return s
        try:
            await tel.place_call(None)
            s.add(OK, "temp scope: calls are allowed while running (fake line, nothing dialled)")
            set_paused(scoped, True)
            read_back = is_paused(scoped)
            refused = False
            try:
                await tel.place_call(None)
            except PausedError:
                refused = True
            set_paused(scoped, False)
            cleared = not is_paused(scoped)
            if read_back and refused and cleared and len(placed) == 1:
                s.add(OK, "flag set, read back, call refused while paused, then cleared")
            else:
                s.add(FAIL, "the kill switch did not round-trip "
                      f"(read={read_back}, refused={refused}, cleared={cleared})")
        except Exception as e:  # noqa: BLE001
            s.add(FAIL, f"kill switch test errored ({_exc(e)})")
    if pause_status(settings) != live_state:
        s.add(FAIL, "the real kill switch changed during the test")  # must never happen
    return s


# ----------------------------------------------------------------------------- 8 systemd
def _default_run(cmd: list[str]) -> tuple[int, str]:
    import subprocess

    p = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)  # noqa: S603
    return p.returncode, (p.stdout or "").strip()


def check_systemd(probes: Probes, unit: str = "friday") -> Section:
    s = Section("systemd")
    present = (probes.systemctl_present or (lambda: shutil.which("systemctl") is not None))()
    if not present:
        s.add(SKIP, "systemd not available here (not a server, or not Linux)")
        return s
    run = probes.run_command or _default_run
    try:
        rc, out = run(["systemctl", "is-active", unit])
    except Exception as e:  # noqa: BLE001
        s.add(SKIP, f"could not ask systemd ({_exc(e)})")
        return s
    if out == "active":
        s.add(OK, f"unit '{unit}' is active")
    elif out in ("", "unknown") or rc == 4:
        s.add(SKIP, f"no systemd unit named '{unit}' on this machine")
        return s
    else:
        s.add(FAIL, f"unit '{unit}' is {out}; run: sudo systemctl status {unit}")
    try:
        _, line = run(["journalctl", "-u", unit, "-n", "1", "--no-pager", "-o", "short-iso"])
        stamp = line.split()[0] if line.split() else ""  # the timestamp only, never the message
        if re.match(r"^\d{4}-\d\d-\d\dT[\d:+.\-]+$", stamp):
            s.add(OK, f"last log line at {stamp}")
        else:
            s.add(WARN, "no readable log line (run with sudo, or the unit has not logged yet)")
    except Exception as e:  # noqa: BLE001
        s.add(WARN, f"could not read the log ({_exc(e)})")
    return s


# ----------------------------------------------------------------------------- 9 receptionist
async def check_receptionist(settings: Settings) -> Section:
    """Read-only: the switch, how many users opted in, and what the forwarding probe found."""
    from friday.receptionist import probe as probe_mod

    s = Section("receptionist")
    on = bool(settings.receptionist_enabled)
    s.add(OK, f"FRIDAY_RECEPTIONIST_ENABLED={'on' if on else 'off (default)'}")
    if settings.receptionist_only_number:
        s.add(
            OK if settings.receptionist_inbound_number else WARN,
            "receptionist-only shared number: on"
            + ("" if settings.receptionist_inbound_number else
               " but FRIDAY_RECEPTIONIST_INBOUND_NUMBER is not set (the setting does nothing)"),
        )
    if on and not (settings.receptionist_inbound_number or settings.friday_numbers):
        s.add(WARN, "no inbound number: set FRIDAY_RECEPTIONIST_INBOUND_NUMBER (or FRIDAY_NUMBERS)")
    # opted-in users (a count only; no number, name or message is read)
    opted: int | None = None
    from friday.db.session import Database
    from friday.receptionist.store import SqlReceptionistStore

    db = Database(settings.database_url)
    try:
        opted = len(await SqlReceptionistStore(db).enabled_user_ids())
    except Exception:  # noqa: BLE001 - table absent / database unreachable
        opted = None
    finally:
        await db.dispose()
    if opted is None:
        s.add(WARN if on else SKIP, "opted-in users: not counted (database unreachable or "
              "migration 0011_receptionist not applied)")
    else:
        s.add(OK, f"opted-in users: {opted}")
        if on and opted == 0:
            s.add(WARN, "the switch is on but no user has opted in")
    # the forwarding probe: does the provider's webhook carry the redirecting number?
    path = Path(settings.receptionist_store_dir) / probe_mod.PROBE_FILE
    state, text = probe_mod.verdict(probe_mod.load(path))
    if state == "delivered":
        s.add(OK, "forwarding probe: " + text)
    elif state == "not_delivered":
        s.add(WARN if on else OK, "forwarding probe: " + text +
              "; forwarded calls take the generic message-taker path (docs/RECEPTIONIST.md 3)")
    else:
        s.add(WARN if on else OK, "forwarding probe: " + text + " (docs/RECEPTIONIST.md 3: set "
              "FRIDAY_RECEPTIONIST_PROBE=true and forward your own phone)")
    return s
def _check_browser(settings: Settings) -> Section:
    """Private browser (friday/connectors/doctor_checks.py): read-only, names and ok/warn only."""
    from friday.connectors.doctor_checks import check_browser, env_from_settings

    env = {**os.environ, **env_from_settings(settings)}
    return check_browser(env)


# ----------------------------------------------------------------------------- driver
async def run_sections(
    settings: Settings, *, offline: bool = False, only: str | None = None,
    probes: Probes | None = None,
) -> list[Section]:
    probes = probes or Probes()
    runners: dict[str, Callable[[], Any]] = {
        "settings": lambda: check_settings(settings),
        "database": lambda: check_database(settings),
        "services": lambda: check_services(settings, offline, probes),
        "public_url": lambda: check_public_url(settings, offline, probes),
        "providers": lambda: check_providers(settings, offline, probes),
        "switches": lambda: check_switches(settings),
        "off_switch": lambda: check_off_switch(settings),
        "systemd": lambda: check_systemd(probes),
        "receptionist": lambda: check_receptionist(settings),
        "browser": lambda: _check_browser(settings),
    }
    out: list[Section] = []
    for name in [only] if only else SECTIONS:
        try:
            r = runners[name]()
            out.append(await r if asyncio.iscoroutine(r) else r)
        except Exception as e:  # noqa: BLE001 - one broken section must not hide the others
            sec = Section(name)
            sec.add(FAIL, f"section crashed ({_exc(e)})")
            out.append(sec)
    return out


def render(
    sections: list[Section], *, offline: bool, as_json: bool, secret_values: list[str]
) -> tuple[str, bool]:
    counts = {OK: 0, WARN: 0, FAIL: 0, SKIP: 0}
    for sec in sections:
        for c in sec.checks:
            counts[c.status] += 1
    passed = counts[FAIL] == 0
    if as_json:
        doc = {
            "passed": passed, "offline": offline,
            "counts": {k.lower(): v for k, v in counts.items()},
            "sections": [
                {"name": sec.name, "title": TITLES[sec.name],
                 "checks": [{"status": c.status, "message": c.message} for c in sec.checks]}
                for sec in sections
            ],
        }
        return scrub(json.dumps(doc, indent=2), secret_values), passed
    lines = ["Friday doctor: read-only; no call, no message, no spend."
             + (" (--offline: no external calls)" if offline else ""), ""]
    for sec in sections:
        lines.append(TITLES[sec.name])
        lines += [f"  {TAGS[c.status]} {c.message}" for c in sec.checks]
        lines.append("")
    lines.append(f"{counts[OK]} ok, {counts[WARN]} warning(s), {counts[FAIL]} failure(s), "
                 f"{counts[SKIP]} skipped")
    lines.append("DOCTOR PASS" if passed
                 else f"DOCTOR FAIL: {counts[FAIL]} check(s) (see docs/DOCTOR.md)")
    return scrub("\n".join(lines), secret_values), passed


def run_doctor(
    settings: Settings, *, offline: bool = False, as_json: bool = False,
    section: str | None = None, probes: Probes | None = None,
    out: Callable[[str], None] = print,
) -> int:
    if section is not None and section not in SECTIONS:
        out(f"unknown section '{section}'; choose from: {', '.join(SECTIONS)}")
        return 2
    logging.disable(logging.CRITICAL)  # library log lines must not mix into the report / JSON
    try:
        sections = asyncio.run(
            run_sections(settings, offline=offline, only=section, probes=probes)
        )
    finally:
        logging.disable(logging.NOTSET)
    text, passed = render(sections, offline=offline, as_json=as_json,
                          secret_values=_secret_values(settings))
    out(text)
    return 0 if passed else 1
