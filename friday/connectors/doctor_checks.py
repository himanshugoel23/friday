"""`friday doctor` section for the private browser. Read-only: no browser launched, no site contacted,
nothing spent. Reports names and ok/warn/fail, never values.

Registered in friday/ops/doctor.py as section "browser" (9. private browser). Lines: switch and kill
list, playwright / chromium / Xvfb, saved-logins switch, the per-site gate (enabled / cleared /
supervised), catalog coverage (sites with a fake-tested adapter, cleared sites), the category packages
that have not landed, .env and var/ not tracked, the tool-layer self test.
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SWITCH = "FRIDAY_BROWSER_ENABLED"
KILL = "FRIDAY_CONNECTORS_KILL"
TRUE = {"1", "true", "yes", "on"}


def env_from_settings(settings: Any) -> dict[str, str]:
    """The FRIDAY_BROWSER_* view of ``friday.core.config.Settings`` (so .env values count too)."""
    out: dict[str, str] = {}
    for name in type(settings).model_fields:
        if name.startswith("browser_"):
            v = getattr(settings, name)
            out[f"FRIDAY_{name.upper()}"] = ",".join(v) if isinstance(v, list) else (
                "" if v is None else str(v))
    out["FRIDAY_PUBLIC_BASE_URL"] = str(getattr(settings, "public_base_url", "") or "")
    return out


def _csv(raw: str) -> set[str]:
    return {p.strip().lower() for p in (raw or "").split(",") if p.strip()}


def _chromium_present() -> bool:
    cache = Path.home() / ".cache" / "ms-playwright"
    return cache.is_dir() and any(cache.glob("chromium*"))


def _tracked(paths: tuple[str, ...]) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", *paths], capture_output=True, text=True, timeout=10,
                             cwd=Path(__file__).resolve().parents[2]).stdout.split()
    except Exception:  # noqa: BLE001
        return []
    return [p for p in out if not p.endswith(".env.example")]


async def _selftest() -> list[str]:
    """Run the tool layer on fakes: default off, kill switch, approval before commit, no secret in audit."""
    from friday.mcp import CallContext, ToolError, build_browser_registry
    from friday.mcp.fakes import FakeApprovals, FakeBrowserBackend

    problems: list[str] = []
    be = FakeBrowserBackend({"shop.test"})
    reg = build_browser_registry(be.handlers(), approvals=FakeApprovals(be))
    ctx = CallContext("u", "t")
    try:
        await reg.call(ctx, "browser.open_task", {"site": "shop.test", "goal": "x"})
        problems.append("a user that was never enabled could open a task")
    except ToolError:
        pass
    reg.enable_user("u")
    tid = (await reg.call(ctx, "browser.open_task", {"site": "shop.test", "goal": "x"}))[
        "browser_task_id"]
    commit = {"browser_task_id": tid, "action": "click", "target": "#go", "intent": "commit"}
    try:
        await reg.call(ctx, "browser.act", commit)
        problems.append("irreversible step ran without approval")
    except ToolError:
        pass
    reg.kill()
    try:
        await reg.call(ctx, "browser.get_summary", {"browser_task_id": tid})
        problems.append("kill switch did not stop the tools")
    except ToolError:
        pass
    return problems


def _run_selftest() -> list[str]:
    """Own thread + own loop: the doctor itself already runs inside an event loop."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(_selftest())).result(timeout=30)


def check_browser(env: Mapping[str, str], *, offline: bool = True) -> Any:
    from friday.ops.doctor import FAIL, OK, SKIP, WARN, Section

    s = Section("browser")
    on = env.get(SWITCH, "").strip().lower() in TRUE
    if not on:
        s.add(OK, f"{SWITCH} is off (default); the private browser does nothing")
    else:
        s.add(WARN, f"{SWITCH} is ON: only named testers should have it; real-site runs are "
                    "founder-supervised only")
    kill = env.get(KILL, "").strip()
    s.add(WARN if kill else OK, f"{KILL} {'is set (some or all connectors are off)' if kill else 'is empty'}")

    if importlib.util.find_spec("playwright") is None:
        s.add(WARN if not on else FAIL, "playwright is not installed (uv sync --extra browser)")
    else:
        s.add(OK, "playwright is installed")
        s.add(OK if _chromium_present() else WARN,
              "chromium is downloaded" if _chromium_present()
              else "chromium not downloaded (uv run playwright install chromium)")
    if shutil.which("Xvfb") or shutil.which("xvfb-run"):
        s.add(OK, "virtual display (Xvfb) is available for headed Chromium")
    else:
        s.add(WARN if not on else FAIL, "Xvfb not found (apt install xvfb) - needed for headed Chromium")

    _gate_and_coverage(s, env, on)
    bad = _tracked((".env", "var"))
    s.add(FAIL if bad else OK, "the .env file or var/ is tracked by git" if bad
          else ".env and var/ are not tracked by git")
    try:
        problems = _run_selftest()
    except Exception as e:  # noqa: BLE001
        s.add(SKIP, f"tool-layer self test could not run ({type(e).__name__})")
    else:
        if problems:
            s.add(FAIL, "tool-layer self test: " + "; ".join(problems))
        else:
            s.add(OK, "tool layer self test: default off, approval before commit, kill switch (on fakes)")
    return s


def _gate_and_coverage(s: Any, env: Mapping[str, str], on: bool) -> None:
    from friday.connectors import catalog
    from friday.connectors.sites import categories
    from friday.ops.doctor import FAIL, OK, WARN

    enabled, cleared = _csv(env.get("FRIDAY_BROWSER_SITES_ENABLED", "")), _csv(
        env.get("FRIDAY_BROWSER_LEGAL_CLEARED", ""))
    supervised = env.get("FRIDAY_BROWSER_SUPERVISED", "").strip().lower() in TRUE
    known = {x.key for x in catalog.SITES}
    unknown = (enabled | cleared) - known
    if unknown:
        s.add(WARN, f"{len(unknown)} name(s) in SITES_ENABLED / LEGAL_CLEARED are not catalog sites "
                    "(typo? they are ignored)")
    live = [k for k in sorted(known) if catalog.effective_mode(
        k, enabled, supervised=supervised, cleared=cleared) in {"scripted", "official"}]
    if live:
        s.add(WARN, f"{len(live)} site(s) may run on the REAL site: {', '.join(live)} (cleared + "
                    "enabled + supervised). Founder watches every run.")
    else:
        s.add(OK, "no site may run on the real site (nothing cleared + enabled + supervised): "
                  "every request gets the link hand-over")
    adapters = categories.all_adapters()
    with_adapter = {k.split(".", 1)[0] for k in adapters}
    s.add(OK, f"catalog: {len(known)} sites in {len(catalog.coverage())} categories; "
              f"{len(with_adapter & known)} have a fake-tested adapter; {len(cleared & known)} cleared; "
              f"{len(enabled & known)} enabled")
    missing = categories.missing_packages()
    if missing:
        s.add(WARN, "category package(s) not landed: " + ", ".join(missing))
    broken = categories.failed_packages()
    if broken:
        s.add(WARN, "category package(s) failed to import: " + ", ".join(sorted(broken)))
    creds_on = env.get("FRIDAY_BROWSER_CREDENTIALS_ENABLED", "").strip().lower() in TRUE
    if creds_on and not on:
        s.add(WARN, "saved logins are ON but the browser master switch is off (they do nothing)")
    elif creds_on:
        users = _csv(env.get("FRIDAY_BROWSER_CREDENTIALS_ENABLED_USERS", ""))
        s.add(WARN, "saved website logins are ON for "
                    + ("EVERYONE (*)" if "*" in users else f"{len(users)} user(s)")
                    + "; passwords stay encrypted in the vault, never shown")
        base = env.get("FRIDAY_PUBLIC_BASE_URL", "").strip().lower()
        if base and not base.startswith("https://"):
            s.add(FAIL, "saved logins are ON but FRIDAY_PUBLIC_BASE_URL is not https: the secure "
                        "password page link would travel unencrypted")
        elif base:
            s.add(OK, "secure password page link is https (route /connectors/credentials/* must be "
                      "proxied: docs/CREDENTIAL_VAULT.md, Caddy note)")
    else:
        s.add(OK, "saved website logins are off (default)")
    if env.get("FRIDAY_BROWSER_LOGIN_OTP_IN_CHAT", "").strip().lower() in TRUE:
        s.add(WARN if on else OK,
              "login codes may be typed in WhatsApp chat (single use, ~5 min, only right after "
              "Friday starts a login, stored redacted); passwords and bank / payment / UPI PIN / "
              "card / Aadhaar codes are always refused. Consent wording must be approved"
              if on else "login-code-in-chat is set but the browser master switch is off (no effect)")
    else:
        s.add(OK, "login codes in chat are off (default); the secure code page is the only way")
