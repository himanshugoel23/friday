# ruff: noqa: E501
"""`friday doctor` lines for the general browser agent. Read-only; names and statuses only."""

from __future__ import annotations

from typing import Any

from friday.sitemcp.guard import read_mem_available_mb


def check(settings: Any, *, mem_reader: Any = read_mem_available_mb) -> list[tuple[str, str]]:
    on = bool(getattr(settings, "browser_agent_enabled", False))
    jobs = bool(getattr(settings, "job_apply_enabled", False))
    out = [("ok", f"browser agent: {'ON' if on else 'off'} (FRIDAY_BROWSER_AGENT_ENABLED), job-apply playbook {'ON' if jobs else 'off'} (FRIDAY_JOB_APPLY_ENABLED); no pay / sign / account-creation tool exists")]
    if jobs and not on:
        out.append(("warn", "job-apply playbook is on but the browser agent is off: nothing will run"))
    if on:
        if settings.resolve_llm() != "openai":
            out.append(("warn", "browser agent needs the OpenAI brain (FRIDAY_LLM_PROVIDER=openai); it stays off without it"))
        mem = mem_reader()
        if mem is not None and mem < float(getattr(settings, "site_mcp_min_free_mb", 250)):
            out.append(("warn", f"browser agent: only {mem:.0f} MB RAM available; runs will answer 'busy' until memory frees up"))
        out.append(("ok", f"browser agent limits per run: {settings.browser_agent_max_steps} steps, {settings.browser_agent_max_seconds:.0f} s active, INR {settings.browser_agent_max_cost_inr:g} estimated (cost is a guess, not measured)"))
        out.append(("ok", "browser agent: Chromium and Playwright checks are in the site MCP lines above (same shared browser)"))
    return out
