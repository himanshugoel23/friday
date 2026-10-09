"""Laptop live-call pilot helpers behind ``friday init-env | doctor | livecall``.

Everything here is additive: it uses the normal Container, voice router and CallRunner (the same
path the task engine uses). Plain-language output is deliberate: the user is not an engineer.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import secrets
import shutil
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from friday.core.config import Settings
from friday.core.container import Container
from friday.core.models import (
    CallBrief,
    CallResult,
    ContactTarget,
    TargetKind,
    TaskType,
    normalize_phone,
)

TRIAL_CALLER_ID = "+918065354620"  # Vobiz trial number used for the laptop pilot
HARD_MAX_SECONDS = 300  # no pilot call may ever be longer than this
MIN_SECONDS = 20
EST_INR_PER_MIN = 5.0  # generous: Vobiz ~0.44 + Sarvam STT/TTS + LLM turns
DEFAULT_GOAL = (
    "This is a short TEST call. Introduce yourself as Friday, an AI assistant calling on behalf "
    "of the founder to test call quality. The person on the phone is playing a business. Ask "
    "two or three simple questions (what are your opening hours? do you take bookings by "
    "phone? what is the best way to reach you?), thank them, and politely end the call."
)
DEFAULT_QUESTIONS = [
    "What are your opening hours?",
    "Do you take bookings by phone?",
    "What is the best way to reach you?",
]
SIM_BUSINESS = "+918040000001"  # simulator's fake salon
GENERATED_KEYS = ("FRIDAY_SECRET_KEY", "FRIDAY_PIN_PEPPER", "FRIDAY_FIELD_KEY", "FRIDAY_INDEX_KEY")
LOCK_NAME = "livecall.lock"


def estimate_cost_inr(seconds: float) -> float:
    return round(seconds / 60.0 * EST_INR_PER_MIN, 1)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------------------ init-env
def _set_line(text: str, key: str, value: str) -> str:
    line = f"{key}={value}"
    pat = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    if pat.search(text):
        return pat.sub(lambda _m: line, text, count=1)
    return text.rstrip("\n") + f"\n{line}\n"


def _blank_names(text: str, names: list[str]) -> list[str]:
    out = []
    for n in names:
        m = re.search(rf"^{re.escape(n)}=([^#\n]*)", text, re.M)
        if not m or not m.group(1).strip():
            out.append(n)
    return out


def init_env(root: Path | None = None, out: Callable[[str], None] = print) -> int:
    root = root or Path.cwd()
    target = root / ".env"
    if target.exists():
        out(f"A .env file already exists at {target}. I did not change it.")
        out("(Delete or rename it first if you want a fresh one.)")
        return 0
    example = root / ".env.example"
    if not example.exists():
        example = repo_root() / ".env.example"
    if not example.exists():
        out("Could not find .env.example. Are you inside the friday folder?")
        return 1
    text = example.read_text(encoding="utf-8")
    sets = {
        "FRIDAY_MODE": "live",
        "FRIDAY_PROFILE": "pilot",
        "FRIDAY_TELEPHONY_PROVIDER": "sarvam",
        "SARVAM_CALLER_IDS": TRIAL_CALLER_ID,
        "FRIDAY_PUBLIC_BASE_URL": "",
    }
    for k in GENERATED_KEYS:
        sets[k] = secrets.token_urlsafe(32)
    for k, v in sets.items():
        text = _set_line(text, k, v)
    target.write_text(text, encoding="utf-8")
    to_fill = ["SARVAM_TELEPHONY_AUTH_ID", "SARVAM_TELEPHONY_AUTH_TOKEN", "SARVAM_API_KEY",
               "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FRIDAY_PUBLIC_BASE_URL",
               "FRIDAY_PILOT_ALLOWED_NUMBERS"]
    to_fill = _blank_names(text, to_fill)
    llm_keys = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}
    if llm_keys - set(to_fill):  # one brain key is enough: do not ask for the other
        to_fill = [n for n in to_fill if n not in llm_keys]
    out(f"Created {target}")
    out("Strong random secrets were generated for you (not shown here).")
    out("Open .env in Notepad and fill in these values (the text after the = sign):")
    for n in to_fill:
        out(f"  - {n}")
    out("Brain key: fill ANTHROPIC_API_KEY or OPENAI_API_KEY (either one; leave the other blank).")
    out("Tip: no Anthropic credits? Fill OPENAI_API_KEY and add FRIDAY_LLM_PROVIDER=openai.")
    out("Tip: no LLM key at all? Add FRIDAY_LLM_PROVIDER=fake to test only the audio.")
    out(f"The caller ID is already set to the Vobiz trial number {TRIAL_CALLER_ID}.")
    return 0


# ------------------------------------------------------------------------------ doctor
async def _get(url: str, headers: dict[str, str] | None = None, wait_s: float = 10.0):  # noqa: ANN202
    async with httpx.AsyncClient(timeout=wait_s, follow_redirects=True) as http:
        return await http.get(url, headers=headers)


async def doctor(settings: Settings, env_path: Path | None = None,
                 out: Callable[[str], None] = print) -> int:
    problems = 0

    def ok(msg: str) -> None:
        out(f"  [OK]   {msg}")

    def bad(msg: str) -> None:
        nonlocal problems
        problems += 1
        out(f"  [FIX]  {msg}")

    out("Friday doctor: read-only checks, nothing here costs money or places a call.\n")
    v = sys.version_info
    (ok if v >= (3, 11) else bad)(f"Python {v.major}.{v.minor}.{v.micro}")
    uv = shutil.which("uv")
    (ok if uv else bad)("uv is installed" if uv else "uv not found (winget install astral-sh.uv)")
    env_path = env_path or Path(".env")
    if env_path.exists():
        ok(".env file found")
    else:
        bad(".env not found. Run: uv run friday init-env")
    out(f"\nSettings: mode={settings.mode}, profile={settings.profile}")
    llm = settings.resolve_llm()
    if llm == "fake":
        out("  LLM brain: fake (scripted replies; set OPENAI_API_KEY or ANTHROPIC_API_KEY)")
    elif settings.llm_key_configured():
        ok(f"LLM brain: {llm} ({settings.llm_key_name()} is set; "
           f"call turns use {settings.model_for('call_turn')})")
    else:
        bad(f"LLM brain: {llm} but {settings.llm_key_name()} is empty. Fill ANTHROPIC_API_KEY or "
            "OPENAI_API_KEY in .env (and FRIDAY_LLM_PROVIDER=openai for GPT)")
    if not settings.is_live:
        bad("FRIDAY_MODE is not 'live' (init-env sets it). Real calls need live mode.")
    live = settings.live_problems() if settings.is_live else []
    names = [p.removeprefix("missing ") for p in live]
    if live:
        for n in names:
            bad(f"needs attention: {n}")
    elif settings.is_live:
        ok("all required settings are filled in")
    if not settings.pilot_allowed_numbers:
        bad("FRIDAY_PILOT_ALLOWED_NUMBERS is empty: add your own phone, e.g. +919812345678")
    else:
        ok(f"{len(settings.pilot_allowed_numbers)} phone number(s) allowed for test calls")

    out("\nInternet checks:")
    base = settings.public_base_url.rstrip("/")
    if (msg := settings.public_url_problem()) is not None:
        bad(f"{msg} (start the tunnel and paste its address into .env)")
    else:
        try:
            r = await _get(base + "/health")
            if r.status_code == 200:
                ok(f"{base}/health answers from the internet")
            else:
                bad(f"{base}/health answered HTTP {r.status_code}: is Friday running? "
                    "(this check works while `friday livecall` or `friday serve` is running)")
        except httpx.HTTPError as e:
            bad(f"{base}/health could not be reached ({type(e).__name__}). Is the tunnel up, and "
                "is Friday running? (run this again while `friday serve` is running)")
    tel_ready = bool(settings.sarvam_telephony_auth_id and settings.sarvam_telephony_auth_token)
    if tel_ready:
        try:
            from friday.voice.telephony.vobiz_probe import format_probe, probe_from_settings

            probe = await probe_from_settings(settings)
            out("  Vobiz account (read-only):")
            for line in format_probe(probe).splitlines():
                out(f"      {line}")
            if probe["issues"]:
                problems += len(probe["issues"])
                out("  [FIX]  the Vobiz issues listed above need fixing before a real call")
            else:
                ok("Vobiz account looks ready")
        except Exception as e:  # noqa: BLE001
            bad(f"could not read the Vobiz account: {e}")
    else:
        bad("Vobiz Auth ID/Token are not set, so the Vobiz account was not checked")
    try:
        r = await _get("https://api.sarvam.ai/")
        ok(f"Sarvam is reachable (HTTP {r.status_code})")
    except httpx.HTTPError as e:
        bad(f"Sarvam could not be reached ({type(e).__name__}): check your internet")
    if shutil.which("cloudflared"):
        ok("cloudflared (tunnel) is installed")
    else:
        bad("cloudflared not found. Install: winget install Cloudflare.cloudflared "
            "(or use ngrok)")
    out("")
    out("Everything looks ready." if problems == 0
        else f"{problems} thing(s) to fix before a live test call (see [FIX] above).")
    return 0 if problems == 0 else 1


# ------------------------------------------------------------------------------ livecall
def build_test_brief(
    to: str, goal: str, max_seconds: int, from_number: str | None, on_behalf_of: str,
    target_name: str = "Test business (the founder)",
) -> CallBrief:
    return CallBrief(
        task_id=f"livecall-{secrets.token_hex(4)}",
        requester_user_id="pilot",
        task_type=TaskType.ENQUIRY,
        goal=goal,
        target=ContactTarget(kind=TargetKind.BUSINESS, name=target_name, phone=to),
        on_behalf_of=on_behalf_of,
        questions=list(DEFAULT_QUESTIONS) if goal == DEFAULT_GOAL else [],
        constraints=[f"Test call: wrap up politely within {max_seconds} seconds."],
        from_number=from_number,
        max_duration_s=max_seconds,
        max_hold_s=min(60, max_seconds),
    )


@contextlib.contextmanager
def single_call_lock(directory: Path, stale_after_s: float):  # noqa: ANN201
    """Only one live test call at a time per laptop (lock file; stale locks expire)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LOCK_NAME
    if path.exists() and time.time() - path.stat().st_mtime > stale_after_s:
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError(
            f"another live call seems to be running (lock file {path}). Wait for it to finish; "
            "if you are sure none is running, delete that file."
        ) from None
    os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def write_transcript(result: CallResult, directory: Path, header: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"livecall-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    lines = [header, ""]
    for t in result.transcript.turns:
        lang = f" [{t.language.value}]" if t.language else ""
        lines.append(f"{t.speaker.value.upper()}{lang}: {t.text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def print_summary(result: CallResult, transcript_path: Path | None, est: float,
                  out: Callable[[str], None] = print) -> None:
    langs = ", ".join(dict.fromkeys(x.value for x in result.languages_heard)) or "n/a"
    out("\n===== CALL SUMMARY =====")
    out(f"Dial status   : {result.dial_status.value}")
    out(f"Outcome       : {result.outcome.value}")
    out(f"Duration      : {round(result.duration_s)} s (talk time)")
    out(f"Transcript    : {len(result.transcript.turns)} turn(s)")
    out(f"Languages     : {langs}")
    cost = result.cost_inr_est or est
    out(f"Estimated cost: about Rs {cost:.1f} (upper-bound estimate)")
    out(f"Safety blocks : {'none reported' if not result.error else result.error}")
    if transcript_path:
        out(f"Transcript file: {transcript_path}")


def preflight(settings: Settings, to: str, max_seconds: int, simulate: bool) -> list[str]:
    """Reasons the call must be refused (empty == go). No network."""
    refuse: list[str] = []
    if max_seconds > HARD_MAX_SECONDS:
        refuse.append(f"--max-seconds cannot be more than {HARD_MAX_SECONDS}.")
    if max_seconds < MIN_SECONDS:
        refuse.append(f"--max-seconds must be at least {MIN_SECONDS}.")
    est = estimate_cost_inr(max_seconds)
    if est > settings.pilot_max_spend_inr:
        refuse.append(
            f"Estimated cost Rs {est} is above the spend cap Rs {settings.pilot_max_spend_inr} "
            "(FRIDAY_PILOT_MAX_SPEND_INR). Use a shorter --max-seconds."
        )
    if simulate:
        return refuse
    if not settings.is_live:
        refuse.append("FRIDAY_MODE is not 'live'. Run `uv run friday init-env` or set it in .env.")
        return refuse
    if to not in settings.pilot_allowed_numbers:
        refuse.append(
            f"{to} is not in your allowed list, so Friday will not call it. To allow your own "
            f"phone, add this line to .env:  FRIDAY_PILOT_ALLOWED_NUMBERS={to}"
        )
    refuse += [f"setup problem: {p}" for p in settings.live_problems()]
    return refuse


async def run_livecall(
    settings: Settings,
    to: str,
    *,
    goal: str | None = None,
    max_seconds: int = 180,
    yes: bool = False,
    simulate: bool = False,
    on_behalf_of: str = "the Friday founder",
    out: Callable[[str], None] = print,
    ask: Callable[[str], str] = input,
    state_dir: Path | None = None,
) -> int:
    goal = goal or DEFAULT_GOAL
    state_dir = state_dir or Path("var") / "livecalls"
    if simulate:
        to = SIM_BUSINESS
        settings = settings.model_copy(update={"mode": "simulator", "llm_provider": "fake"})
    else:
        try:
            to = normalize_phone(to, settings.default_country_code)
        except ValueError:
            out(f"REFUSED: '{to}' is not a valid phone number (use +91XXXXXXXXXX).")
            return 2
    refuse = preflight(settings, to, max_seconds, simulate)
    if refuse:
        out("Friday will NOT place this call:")
        for r in refuse:
            out(f"  - {r}")
        return 2
    settings = settings.model_copy(
        update={"call_max_duration_s": max_seconds, "max_concurrent_calls": 1, "call_record": False}
    )
    from_number = None if simulate else (
        (settings.sarvam_caller_ids or settings.friday_numbers or [TRIAL_CALLER_ID])[0]
    )
    est = estimate_cost_inr(max_seconds)
    try:
        lock = single_call_lock(state_dir, stale_after_s=max_seconds + 300)
        lock.__enter__()
    except RuntimeError as e:
        out(f"REFUSED: {e}")
        return 2
    c = Container(settings)
    server: Any = None
    server_task: asyncio.Task | None = None
    app: Any = None
    try:
        from friday.api.app import create_app

        app = create_app(c, background=False, fast_pin_hash=True)
        runtime = app.state.runtime
        if simulate:
            await runtime.start(background=False)
        else:
            import uvicorn

            cfg = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning")
            server = uvicorn.Server(cfg)
            server_task = asyncio.create_task(server.serve())
            for _ in range(100):
                if server.started or server_task.done():
                    break
                await asyncio.sleep(0.1)
            if not server.started:
                out(f"REFUSED: could not start Friday on port {settings.port} "
                    "(is another program using it?).")
                return 2
            out(f"Friday is serving on port {settings.port}. Checking the public address...")
            base = settings.public_base_url.rstrip("/")
            try:
                r = await _get(base + "/health")
                reachable = r.status_code == 200
            except httpx.HTTPError:
                reachable = False
            if not reachable:
                out(f"REFUSED: {base}/health is not reachable from the internet. Is the tunnel "
                    "running and does FRIDAY_PUBLIC_BASE_URL match its address (it changes "
                    "every run)?")
                return 2
        out("")
        out("About to place a REAL call:" if not simulate else "About to run a SIMULATED call:")
        out(f"  From      : {from_number or '(simulator)'}")
        out(f"  To        : {to}")
        out(f"  Goal      : {goal}")
        out(f"  Max length: {max_seconds} s (hard cap)")
        out(f"  Est. cost : up to about Rs {est}")
        if not yes and ask("Type YES to place the call: ").strip() != "YES":
            out("Cancelled. No call was placed.")
            return 1
        brief = build_test_brief(to, goal, max_seconds, from_number, on_behalf_of)
        runner = c.call_runner
        out("Placing the call... answer your phone and talk. (Ctrl+C hangs up and stops.)")
        call_task = asyncio.create_task(
            runner.run(brief, _skip_ask_user, None, from_number=from_number)
        )
        waiters = {call_task} | ({server_task} if server_task else set())
        deadline = max_seconds + settings.call_ring_timeout_s + 45
        done, _ = await asyncio.wait(waiters, timeout=deadline, return_when=asyncio.FIRST_COMPLETED)
        if call_task not in done:
            out("Stopping the call (time limit or stop requested)...")
            runner.cancel(brief.task_id)
            try:
                await asyncio.wait_for(asyncio.shield(call_task), timeout=20)
            except (TimeoutError, asyncio.CancelledError):
                call_task.cancel()
                with contextlib.suppress(BaseException):
                    await call_task
        if call_task.cancelled() or call_task.exception() is not None:
            err = "cancelled" if call_task.cancelled() else call_task.exception()
            out(f"The call ended with an error: {err}")
            return 1
        result: CallResult = call_task.result()
        header = f"Friday live test call to {to} at {datetime.now().isoformat(timespec='seconds')}"
        path = write_transcript(result, state_dir, header)
        print_summary(result, path, est, out)
        return 0
    finally:
        if server is not None:
            server.should_exit = True
        if server_task is not None:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(server_task, timeout=10)
        if app is not None and getattr(app.state, "runtime", None) is not None:
            with contextlib.suppress(Exception):
                await app.state.runtime.stop()
        with contextlib.suppress(Exception):
            await c.aclose()
        lock.__exit__(None, None, None)


async def _skip_ask_user(_q: Any) -> None:
    return None


class LiveCallRefused(Exception):
    """The test call must not be placed (reasons are plain-language, safe to show)."""

    def __init__(self, reasons: list[str], status: int = 422) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons
        self.status = status


def result_summary(result: CallResult, transcript_path: Path | None, est: float) -> dict[str, Any]:
    """JSON-safe call summary (no phone numbers, no transcript text)."""
    langs = list(dict.fromkeys(x.value for x in result.languages_heard))
    return {
        "dial_status": result.dial_status.value,
        "outcome": result.outcome.value,
        "duration_s": round(result.duration_s),
        "turns": len(result.transcript.turns),
        "languages": langs,
        "estimated_cost_inr": round(result.cost_inr_est or est, 1),
        "error": result.error or None,
        "transcript_path": str(transcript_path) if transcript_path else None,
    }


async def place_test_call(
    c: Container,
    to: str,
    *,
    goal: str | None = None,
    max_seconds: int = 180,
    on_behalf_of: str = "the Friday founder",
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Place ONE short test call through an ALREADY RUNNING container's call runner.

    Same safety rules as ``friday livecall``: allow-list, hard max duration, spend cap, one call
    at a time (lock file), no recording. In a non-live (simulator) container the call goes to the
    simulated business. Raises ``LiveCallRefused`` before anything is dialled. Used by
    ``POST /admin/livecall``.
    """
    settings = c.settings
    simulate = not settings.is_live
    state_dir = state_dir or Path(settings.media_dir) / "livecalls"
    if simulate:
        to = SIM_BUSINESS
    else:
        try:
            to = normalize_phone(to, settings.default_country_code)
        except ValueError:
            raise LiveCallRefused(["not a valid phone number (use +91XXXXXXXXXX)"]) from None
    refuse = preflight(settings, to, max_seconds, simulate)
    if refuse:
        raise LiveCallRefused(refuse, status=403 if any("allowed list" in r for r in refuse)
                              else 422)
    goal = goal or DEFAULT_GOAL
    from_number = None if simulate else (
        (settings.sarvam_caller_ids or settings.friday_numbers or [TRIAL_CALLER_ID])[0]
    )
    est = estimate_cost_inr(max_seconds)
    try:
        lock = single_call_lock(state_dir, stale_after_s=max_seconds + 300)
        lock.__enter__()
    except RuntimeError as e:
        raise LiveCallRefused([str(e)], status=409) from None
    try:
        brief = build_test_brief(to, goal, max_seconds, from_number, on_behalf_of)
        runner = c.call_runner
        call_task = asyncio.create_task(
            runner.run(brief, _skip_ask_user, None, from_number=from_number)
        )
        deadline = max_seconds + settings.call_ring_timeout_s + 45
        done, _ = await asyncio.wait({call_task}, timeout=deadline)
        if call_task not in done:
            runner.cancel(brief.task_id)
            try:
                await asyncio.wait_for(asyncio.shield(call_task), timeout=20)
            except (TimeoutError, asyncio.CancelledError):
                call_task.cancel()
                with contextlib.suppress(BaseException):
                    await call_task
        if call_task.cancelled() or call_task.exception() is not None:
            err = "cancelled" if call_task.cancelled() else type(call_task.exception()).__name__
            return {"outcome": "error", "error": f"the call ended with an error: {err}",
                    "estimated_cost_inr": est}
        result: CallResult = call_task.result()
        header = f"Friday live test call at {datetime.now().isoformat(timespec='seconds')}"
        path = write_transcript(result, state_dir, header)
        return result_summary(result, path, est)
    finally:
        lock.__exit__(None, None, None)
