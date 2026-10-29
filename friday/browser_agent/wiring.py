# ruff: noqa: E501
"""Build the browser agent for the live pipeline. Returns None unless FRIDAY_BROWSER_AGENT_ENABLED (and an OpenAI brain)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from friday.browser_agent.agent import BrowserAgent
from friday.browser_agent.gateway import BrowserAgentGateway
from friday.browser_agent.jobapply import JobApplyService, JobLedger
from friday.browser_agent.llm import OpenAIBrowserLLM
from friday.browser_agent.pwpage import PoolPageProvider
from friday.browser_agent.stores import AgentLog, FileRefs, JsonRunStore, ProofStore, RepoFacts
from friday.core.logging import get_logger

log = get_logger(__name__)


class StackLogin:
    """LoginPort over the existing private-browser stack: vault link page, saved logins, secure OTP page, guarded login-OTP-in-chat."""

    def __init__(self, stack: Any) -> None:
        self.stack = stack

    def credential_link(self, user_id: str, site: str, hosts: list[str]) -> str | None:
        svc = getattr(self.stack, "credentials", None)
        if svc is None:
            return None
        try:
            return str(svc.request_link(user_id, site, hosts))
        except Exception:  # noqa: BLE001 - CredentialError: not enabled for this user / blocked kind of site
            return None

    def release(self, user_id: str, site: str, host: str) -> tuple[str, str] | None:
        vault = getattr(self.stack, "cred_vault", None)
        if vault is None:
            return None
        try:
            cred = vault.release(user_id, site, current_host=host)
        except Exception:  # noqa: BLE001
            return None
        return (cred.username, cred.password) if cred is not None else None

    def otp_link(self, user_id: str, site: str, run_id: str) -> str | None:
        tokens = getattr(self.stack, "otp_tokens", None)
        if tokens is None:
            return None
        pending = getattr(self.stack, "pending_logins", None)
        if pending is not None:
            pending.expect(user_id, site, run_id)  # arms the guarded 'code typed in chat' path: this user, this site, single use
        return f"{str(self.stack.base_url).rstrip('/')}/connectors/otp/{tokens.create(run_id)}"

    def take_otp(self, run_id: str) -> str | None:
        otp = getattr(self.stack, "otp", None)
        return otp.take(run_id) if otp is not None else None


def build_pool(settings: Any, hub: Any = None) -> Any:
    """Share the site-MCP pool (ONE Chromium, shared session cap) when it exists; else a pool of our own."""
    if hub is not None:
        return hub.pool
    from friday.sitemcp.chromium import SharedChromium
    from friday.sitemcp.guard import MemoryGuard, RobotsPolicy
    from friday.sitemcp.runtime import SessionPool

    return SessionPool(SharedChromium(), vault=None, robots=RobotsPolicy(), memory=MemoryGuard(float(settings.site_mcp_min_free_mb)),
                       max_sessions=int(settings.site_mcp_max_sessions), idle_s=float(settings.site_mcp_idle_s))


def build_agent(pipeline: Any, *, provider: Any = None, llm: Any = None) -> BrowserAgentGateway | None:
    s = pipeline.c.settings
    if not getattr(s, "browser_agent_enabled", False):
        return None
    if llm is None:
        if s.resolve_llm() != "openai":
            log.info("browser agent: needs the OpenAI brain; staying off")
            return None
        llm = OpenAIBrowserLLM(pipeline.c.get("llm"), model=s.browser_agent_model or s.openai_default_purpose_model,
                               in_inr_per_1k=s.browser_agent_in_inr_per_1k, out_inr_per_1k=s.browser_agent_out_inr_per_1k)
    root = Path(s.browser_agent_dir)
    if provider is None:
        hub = None
        if getattr(s, "site_mcp_enabled", False):
            from friday.sitemcp.wiring import build_hub

            hub = build_hub(s, browser_stack=getattr(pipeline, "browser", None))
        provider = PoolPageProvider(build_pool(s, hub))
    files = FileRefs(root)
    proofs = ProofStore(root, ttl_days=int(s.browser_agent_proof_days), clock=pipeline.clock)
    facts = RepoFacts(pipeline.repos)
    stack = getattr(pipeline, "browser", None)
    agent = BrowserAgent(provider=provider, llm=llm, facts=facts, files=files, store=JsonRunStore(root), proofs=proofs,
                         login=StackLogin(stack) if stack is not None else None, log_sink=AgentLog(), clock=pipeline.clock,
                         ask_ttl_s=s.browser_agent_ask_timeout_h * 3600, confirm_ttl_s=s.browser_agent_confirm_timeout_min * 60,
                         file_names=files.names)
    jobs = None
    if getattr(s, "job_apply_enabled", False):
        jobs = JobApplyService(agent, facts, JobLedger(root / "job_ledger.jsonl"), files, daily_cap=int(s.job_apply_daily_cap), now=pipeline.clock.now)
    return BrowserAgentGateway(pipeline, agent, jobs=jobs, settings=s, proofs=proofs)
