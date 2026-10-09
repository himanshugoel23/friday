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
        "FRIDAY_PUBLIC_BASE_URL": "",
    }
    for k in GENERATED_KEYS:
        sets[k] = secrets.token_urlsafe(32)
    for k, v in sets.items():
        text = _set_line(text, k, v)
    target.write_text(text, encoding="utf-8")
    to_fill = ["SARVAM_TELEPHONY_AUTH_ID", "SARVAM_TELEPHONY_AUTH_TOKEN", "SARVAM_API_KEY",
               "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SARVAM_CALLER_IDS", "FRIDAY_PUBLIC_BASE_URL",
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
    out("SARVAM_CALLER_IDS = your own Vobiz number in +91... format (calls are placed from it).")
    return 0


# ------------------------------------------------------------------------------ doctor
async def _get(url: str, headers: dict[str, str] | None = None, wait_s: float = 10.0):  # noqa: ANN202
    async with httpx.AsyncClient(timeout=wait_s, follow_redirects=True) as http:
        return await http.get(url, headers=headers)


async def doctor(settings: Settings, env_path: Path | None = None,
                 out: Callable[[str], None] = print, *, warn_vobiz_issues: bool = False) -> int:
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
    uv = shutil.which("uv") or (sys.prefix != sys.base_prefix)  # a server runs from its venv
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
            if probe["issues"] and warn_vobiz_issues:
                out("  [WARN] the Vobiz issues listed above do not stop answering calls, "
                    "but fix them before Friday phones anyone (ask Vobiz to turn call queue off)")
            elif probe["issues"]:
                problems += len(probe["issues"])
                out("  [FIX]  the Vobiz issues listed above need fixing before a real call")
            else:
                ok("Vobiz account looks ready")
            await _doctor_inbound_link(settings, out)
        except Exception as e:  # noqa: BLE001
            bad(f"could not read the Vobiz account: {e}")
    else:
        bad("Vobiz Auth ID/Token are not set, so the Vobiz account was not checked")
    try:
        r = await _get("https://api.sarvam.ai/")
        ok(f"Sarvam is reachable (HTTP {r.status_code})")
    except httpx.HTTPError as e:
        bad(f"Sarvam could not be reached ({type(e).__name__}): check your internet")
    own_https = base.startswith("https://") and "trycloudflare.com" not in base
    if own_https and settings.public_url_problem() is None:
        ok("own HTTPS address in use (no tunnel needed)")
    elif shutil.which("cloudflared"):
        ok("cloudflared (tunnel) is installed")
    else:
        bad("cloudflared not found. Install: winget install Cloudflare.cloudflared "
            "(or use ngrok)")
    out("")
    out("Everything looks ready." if problems == 0
        else f"{problems} thing(s) to fix before a live test call (see [FIX] above).")
    return 0 if problems == 0 else 1


async def _doctor_inbound_link(settings: Settings, out: Callable[[str], None]) -> None:
    """Read-only: which Vobiz application the front-door number rings today."""
    from friday.voice.telephony.vobiz_app import VobizAppManager

    number = (settings.sarvam_caller_ids or settings.friday_numbers or [None])[0]
    if not number or not settings.sarvam_telephony_auth_token:
        return
    mgr = VobizAppManager(
        settings.sarvam_telephony_auth_id or "",
        settings.sarvam_telephony_auth_token.get_secret_value(),
        base_url=settings.sarvam_telephony_base_url,
    )
    try:
        app = await mgr.current_link(number)
        what = f"application {app}" if app else "no application"
        out(f"  Inbound: {number} rings {what} today. `friday listen` points it at Friday while "
            "it runs and puts it back afterwards.")
    except Exception as e:  # noqa: BLE001
        out(f"  Inbound: could not read the link of {number} ({type(e).__name__})")
    finally:
        await mgr.aclose()


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
    if result.collected.get("playbook"):
        keys = ("outcome", "slot", "price_inr", "duration_min", "stylist", "advance_needed",
                "steps")
        got = ", ".join(f"{k}={result.collected[k]}" for k in keys if result.collected.get(k))
        out(f"Playbook      : {result.collected['playbook']} -> {got}")
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
    playbook: str | None = None,
    playbook_args: dict[str, Any] | None = None,
) -> int:
    goal = goal or DEFAULT_GOAL
    state_dir = state_dir or Path("var") / "livecalls"
    if playbook:
        # scripted call: fixed Hinglish lines, same guards (allow-list, spend cap, no approval
        # shortcuts: a test call has no delegation, so it can never book)
        from friday.playbooks.model import PlaybookError
        from friday.playbooks.select import playbook_test_brief

        try:
            playbook_test_brief(
                playbook, to=SIM_BUSINESS, user_first_name=on_behalf_of,
                max_seconds=max_seconds, from_number=None, **(playbook_args or {}),
            )
        except PlaybookError as e:
            out(f"REFUSED: playbook '{playbook}' cannot run: " + "; ".join(e.problems))
            return 2
        settings = settings.model_copy(update={"playbooks_enabled": True})
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
        (settings.sarvam_caller_ids or settings.friday_numbers or [None])[0]
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
        out(f"  Goal      : {goal}" if not playbook else
            f"  Playbook  : {playbook} (fixed Hinglish script; no delegation, cannot book)")
        out(f"  Max length: {max_seconds} s (hard cap)")
        out(f"  Est. cost : up to about Rs {est}")
        if not yes and ask("Type YES to place the call: ").strip() != "YES":
            out("Cancelled. No call was placed.")
            return 1
        if playbook:
            from friday.playbooks.select import playbook_test_brief

            brief = playbook_test_brief(
                playbook, to=to, user_first_name=on_behalf_of, max_seconds=max_seconds,
                from_number=from_number, **(playbook_args or {}),
            )
        else:
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
        (settings.sarvam_caller_ids or settings.friday_numbers or [None])[0]
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


# ------------------------------------------------------------------------------ listen
# `friday listen`: the front door. People call Friday's number and talk to Friday
# (docs/FRONT_DOOR.md).
SIM_CALLER = "+919800000011"  # simulated allow-listed caller (a new person, then the same person)
SIM_STRANGER = "+919800000099"  # simulated caller that is NOT allow-listed
SIM_FRIDAY_NUMBER = "+918065354620"
LISTEN_DIR = Path("var") / "livecalls"
LINK_STATE = Path("var") / "listen" / "vobiz_link.json"


def write_frontdoor_transcript(result: CallResult, summary: Any, directory: Path) -> Path:
    """One text file per call. Secrets are already redacted; the caller's number is masked."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"frontdoor-{stamp}-{summary.call_id[-6:]}.txt"
    lines = [
        f"Friday front-door call {summary.call_id} from {summary.caller} "
        f"({summary.kind.value}) at {datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for t in result.transcript.turns:
        lang = f" [{t.language.value}]" if t.language else ""
        who = "CALLER" if t.speaker.value == "callee" else t.speaker.value.upper()
        lines.append(f"{who}{lang}: {t.text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def print_call_summary(n: int, summary: Any, out: Callable[[str], None] = print) -> None:
    out(f"\n===== CALL {n} =====")
    if summary.route == "reject":
        out(f"Caller        : {summary.caller} ({summary.kind.value})")
        out(f"Outcome       : not served ({summary.end_reason}); heard a short fixed message")
        return
    langs = ", ".join(summary.languages) or "n/a"
    who = summary.kind.value + (" -> onboarded by voice" if summary.onboarded else "")
    out(f"Caller        : {summary.caller} ({who})")
    reason = f" ({summary.end_reason})" if summary.end_reason else ""
    out(f"Outcome       : {summary.outcome}{reason}")
    out(f"Duration      : {round(summary.duration_s)} s")
    out(f"Languages     : {langs}")
    out(f"Turns         : {summary.turns} (LLM turns {summary.llm_turns}); "
        f"reply time p50 {summary.p50_ms:.0f} ms, p95 {summary.p95_ms:.0f} ms (excluding network)")
    out(f"Tasks created : {len(summary.tasks)}")
    out(f"Estimated cost: about Rs {summary.cost_inr_est:.1f} (upper-bound estimate)")
    if summary.transcript_path:
        out(f"Transcript    : {summary.transcript_path}")


def listen_preflight(settings: Settings) -> list[str]:
    """Reasons `friday listen` must refuse (no network)."""
    refuse: list[str] = []
    if not settings.is_live:
        refuse.append("FRIDAY_MODE is not 'live'. Run `uv run friday init-env` or set it in .env.")
        return refuse
    if not settings.pilot_allowed_numbers:
        refuse.append(
            "FRIDAY_PILOT_ALLOWED_NUMBERS is empty, so nobody could call. Add your own phone, "
            "e.g. FRIDAY_PILOT_ALLOWED_NUMBERS=+919812345678"
        )
    if not (settings.sarvam_caller_ids or settings.friday_numbers):
        refuse.append("SARVAM_CALLER_IDS is empty: set it to the Vobiz number people will call.")
    if (msg := settings.public_url_problem()) is not None:
        refuse.append(f"{msg} (start the tunnel and paste its address into .env)")
    if not (settings.sarvam_telephony_auth_id and settings.sarvam_telephony_auth_token):
        refuse.append("Vobiz Auth ID / Auth Token are not set.")
    refuse += [f"setup problem: {p}" for p in settings.live_problems()]
    return refuse


@contextlib.asynccontextmanager
async def inbound_link(mgr: Any, base_url: str, number: str, secret: str,
                       out: Callable[[str], None] = print):  # noqa: ANN201
    """Link the number to the Friday application for the duration of the block, and ALWAYS put
    the previous link back afterwards (also on errors and Ctrl+C)."""
    link = await mgr.sync(base_url, number, secret)
    prev = (f"application {link.previous_app_id}" if link.previous_app_id
            else ("no application" if link.previous_known else "an unknown earlier link"))
    out(f"Vobiz: {number} now rings Friday (application {link.app_id}); it was linked to {prev}.")
    try:
        yield link
    finally:
        res = await asyncio.shield(mgr.restore(link))
        out(f"Vobiz: link {res.action}" + (f" ({res.detail})" if res.detail else ""))
        if not res.ok:
            out("WARNING: the number may still point at this (soon dead) address. "
                "Run `uv run friday listen --restore` to put it back.")


async def run_listen(
    settings: Settings,
    *,
    simulate: bool = False,
    restore_only: bool = False,
    seconds: float | None = None,
    out: Callable[[str], None] = print,
    state_dir: Path | None = None,
    link_state: Path | None = None,
) -> int:
    from friday.voice.frontdoor import FrontDoorCallFinished
    from friday.voice.telephony.vobiz_app import FakeVobizAccount, VobizAppManager

    state_dir = state_dir or LISTEN_DIR
    link_state = link_state or LINK_STATE

    def real_manager(s: Settings) -> VobizAppManager:
        token = s.sarvam_telephony_auth_token
        return VobizAppManager(
            s.sarvam_telephony_auth_id or "",
            token.get_secret_value() if token else "",
            base_url=s.sarvam_telephony_base_url,
            state_path=link_state,
        )

    if restore_only:
        if not (settings.sarvam_telephony_auth_id and settings.sarvam_telephony_auth_token):
            out("Vobiz Auth ID / Auth Token are not set.")
            return 2
        mgr = real_manager(settings)
        try:
            res = await mgr.restore()
        finally:
            await mgr.aclose()
        out(f"Vobiz: {res.action}" + (f" ({res.detail})" if res.detail else ""))
        return 0 if res.ok else 1

    # ---- configuration for this run (pilot profile, one call at a time, no recordings)
    update: dict[str, Any] = {
        "profile": "pilot", "call_record": False, "max_concurrent_calls": 1,
        "frontdoor_enabled": True, "frontdoor_max_concurrent": 1,
        "roles": ["api", "task", "voice"],  # no proactive nudges in a listening test
    }
    tmp: Any = None
    mgr: Any
    if simulate:
        import tempfile

        tmp = tempfile.TemporaryDirectory(prefix="friday-listen-")
        update |= {
            "mode": "simulator", "llm_provider": "fake", "pilot_allowed_numbers": [SIM_CALLER],
            "database_url": f"sqlite+aiosqlite:///{tmp.name}/listen.db",
            "media_dir": f"{tmp.name}/media", "invite_only": False,
            "public_base_url": "https://simulated.trycloudflare.com",
            "sarvam_caller_ids": [SIM_FRIDAY_NUMBER],
        }
        settings = settings.model_copy(update=update)
        previous = {"app_id": "SIM-PREVIOUS-APP", "app_name": "previous"}
        fake = FakeVobizAccount("MA_SIM", numbers={SIM_FRIDAY_NUMBER: "SIM-PREVIOUS-APP"},
                                applications=[previous])
        mgr = VobizAppManager("MA_SIM", "sim", transport=fake.transport,
                              state_path=Path(tmp.name) / "vobiz_link.json")
    else:
        settings = settings.model_copy(update=update)
        if refuse := listen_preflight(settings):
            out("Friday will NOT start listening:")
            for r in refuse:
                out(f"  - {r}")
            return 2
        mgr = real_manager(settings)
        stale = mgr.pending_restore()
        if stale is not None:
            out("A previous `friday listen` did not restore the number. Restoring it now...")
            res = await mgr.restore()
            out(f"Vobiz: {res.action}" + (f" ({res.detail})" if res.detail else ""))

    number = (settings.sarvam_caller_ids or settings.friday_numbers)[0]
    c = Container(settings)
    server: Any = None
    server_task: asyncio.Task | None = None
    app: Any = None
    calls: list[Any] = []
    finished = asyncio.Event()

    async def on_finished(ev: FrontDoorCallFinished) -> None:
        s = ev.summary
        if ev.result is not None:
            try:
                s = s.model_copy(update={"transcript_path": str(
                    write_frontdoor_transcript(ev.result, s, state_dir))})
            except OSError as e:
                out(f"(could not write the transcript: {e})")
        calls.append(s)
        print_call_summary(len(calls), s, out)
        finished.set()

    try:
        from friday.api.app import create_app

        await c.db.create_all()
        from friday.pause import install_pause_guard

        install_pause_guard(c)  # `friday pause` also stops what a call starts (as in `serve`)
        app = create_app(c, background=True, fast_pin_hash=True)
        runtime = app.state.runtime
        c.bus.subscribe(FrontDoorCallFinished, on_finished)
        if simulate:
            await runtime.start(background=True)
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
            out(f"Friday is serving on port {settings.port}. Running the read-only checks...\n")
            if await doctor(settings, out=out, warn_vobiz_issues=True) != 0:
                out("\nNot linking the number until the checks above pass.")
                return 2
        fd = runtime.front_door
        misses = await fd.prerender()
        if misses:
            out(f"Pre-rendered {misses} fixed voice lines into the cache (one-off cost).")
        link_scope = inbound_link(mgr, settings.public_base_url, number,
                                  settings.secret_key.get_secret_value(), out)
        async with link_scope:
            out("")
            if simulate:
                out(f"[simulated] Call {number} now. (A simulated caller will ring in.)")
                await _simulate_callers(c, number, out, finished)
            else:
                out(f"Call {number} now.")
                out(f"Allowed callers: {len(settings.pilot_allowed_numbers)} number(s). "
                    f"Max {settings.frontdoor_pilot_max_call_s} s per call, one call at a time, "
                    f"spend cap Rs {settings.pilot_max_spend_inr:g}. Press Ctrl+C to stop.")
                await _wait_until_stopped(seconds, server_task)
            out("\nStopping...")
        total = sum(x.cost_inr_est for x in calls)
        served = [x for x in calls if x.route == "serve"]
        out(f"\nSummary: {len(calls)} call(s), {len(served)} served, "
            f"estimated total cost about Rs {total:.1f}.")
        if served:
            p95 = max(x.p95_ms for x in served)
            out(f"Reply time (STT + LLM + TTS as measured here) worst p95: {p95:.0f} ms.")
        return 0
    finally:
        with contextlib.suppress(Exception):
            c.bus.unsubscribe(FrontDoorCallFinished, on_finished)
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
        with contextlib.suppress(Exception):
            await mgr.aclose()
        if tmp is not None:
            tmp.cleanup()


async def _wait_until_stopped(seconds: float | None, server_task: asyncio.Task | None) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    import signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)
    waiters = [asyncio.ensure_future(stop.wait())]
    if server_task is not None:
        waiters.append(server_task)
    try:
        await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    except KeyboardInterrupt:  # no signal handlers (Windows)
        pass
    finally:
        for w in waiters:
            if w is not server_task:
                w.cancel()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.remove_signal_handler(sig)


async def _simulate_callers(c: Container, number: str, out: Callable[[str], None],
                            finished: asyncio.Event) -> None:
    """Three simulated inbound calls through the REAL answer path (bus event -> classification ->
    front door): a new allow-listed caller who onboards and asks for a haircut, the same person
    calling again, and a stranger who is politely refused."""
    from friday.core.models import Language
    from friday.voice.simulator import SimParty

    tel = c.telephony
    scripts = [
        ("a new person: onboarding, then a request",
         SIM_CALLER, ["Asha", "Hindi", "haan",
                      "Looks Unisex Salon mein haircut book karo kal shaam", "haan", "nahi bas"]),
        ("the same person calls again: 'are you a bot?'",
         SIM_CALLER, ["", "kya aap ek bot ho?", "nahi bas"]),  # "" = the 2nd greeting clip
        ("a stranger (not allow-listed)", SIM_STRANGER, []),
    ]
    for label, caller, script in scripts:
        out(f"\n--- simulated call: {label}")
        party = SimParty(name="Caller", language=Language.HINGLISH, script=script)
        tel.register_party(caller, party)
        finished.clear()
        await tel.simulate_inbound_call(caller, number)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(finished.wait(), timeout=10)
    await asyncio.sleep(0.5)  # let the engine finish the booking call it started
