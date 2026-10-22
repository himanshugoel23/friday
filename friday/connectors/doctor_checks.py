"""`friday doctor` section for the private browser. Read-only: no browser launched, no site contacted,
nothing spent. Reports names and ok/warn/fail, never values.

Register (5 lines, in friday/ops/doctor.py): add "browser" to SECTIONS, TITLES["browser"] = "9. private
browser", and in run_sections:
    "browser": lambda: __import__("friday.connectors.doctor_checks", fromlist=["x"]).check_browser(
        os.environ),
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
