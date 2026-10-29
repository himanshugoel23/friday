# ruff: noqa: E501
"""The inside of one step = the existing browser agent loop (observe, think, policy, act). This module only builds the small
RunSpec of the step and maps the loop's outcome to a ``StepResult``. The safety rules (payment stop, allow-list, injection
safety, no account creation, irreversible confirmation) are NOT repeated here: the loop's policy layer enforces them on every
action of every step.

Step loops run in their OWN run store (var/steps/runs), so the general browser-agent gateway never touches them."""

from __future__ import annotations

from typing import Any

from friday.browser_agent.agent import BrowserAgent
from friday.browser_agent.ports import FactSource, LoginPort, RunStore
from friday.browser_agent.types import RunOutcome, RunSpec, Status
from friday.steps.types import StepRequest, StepResult


class OverlayFacts:
    """The user's facts plus a per-user, in-memory overlay (delivery_area ...). The overlay never holds a secret."""

    def __init__(self, base: FactSource) -> None:
        self.base = base
        self._over: dict[str, dict[str, str]] = {}

    def set(self, user_id: str, facts: dict[str, str]) -> None:
        self._over[user_id] = dict(facts)

    def clear(self, user_id: str) -> None:
        self._over.pop(user_id, None)

    async def load(self, user_id: str) -> dict[str, str]:
        out = await self.base.load(user_id)
        out.update(self._over.get(user_id, {}))
        return out

    async def remember(self, user_id: str, key: str, value: str) -> None:
        await self.base.remember(user_id, key, value)


class StepLogin:
    """LoginPort for the step loops. The loop asks for the code by ITS run id; the guarded OTP channel holds it under the PLAN's key.
    This maps one to the other. Every other call passes through to the real login port."""

    def __init__(self, inner: LoginPort | None, store: RunStore) -> None:
        self.inner, self.store = inner, store
        self._keys: dict[str, str] = {}

    def bind(self, user_id: str, key: str) -> None:
        if key:
            self._keys[user_id] = key
        else:
            self._keys.pop(user_id, None)

    def credential_link(self, user_id: str, site: str, hosts: list[str]) -> str | None:
        return self.inner.credential_link(user_id, site, hosts) if self.inner else None

    def release(self, user_id: str, site: str, host: str) -> tuple[str, str] | None:
        return self.inner.release(user_id, site, host) if self.inner else None

    def otp_link(self, user_id: str, site: str, run_id: str) -> str | None:
        return self.inner.otp_link(user_id, site, self._keys.get(user_id, run_id)) if self.inner else None

    def take_otp(self, run_id: str) -> str | None:
        if self.inner is None:
            return None
        st = self.store.load(run_id)
        key = self._keys.get(st.user_id, run_id) if st is not None else run_id
        return self.inner.take_otp(key)


def build_step_agent(base: BrowserAgent, *, store: RunStore, overlay: OverlayFacts, login: StepLogin) -> BrowserAgent:
    """A BrowserAgent for step loops that shares the base agent's page provider, model, proofs and clock but has its own run store,
    the overlay facts and the plan-keyed login port."""
    return BrowserAgent(provider=base.provider, llm=base.llm, facts=overlay, files=base.files, store=store, proofs=base.proofs, login=login,
                        log_sink=base.log, clock=base.clock, perf=base.perf, ask_ttl_s=base.ask_ttl, confirm_ttl_s=base.confirm_ttl,
                        permit_ttl_s=base.permit_ttl, max_asks=base.max_asks, max_refusals=base.max_refusals, file_names=base._file_names)


class AgentStepWorker:
    def __init__(self, agent: BrowserAgent, overlay: OverlayFacts, login: StepLogin, *, max_seconds: float = 150.0, max_cost_inr: float = 4.0) -> None:
        self.agent, self.overlay, self.login = agent, overlay, login
        self.max_seconds, self.max_cost_inr = max_seconds, max_cost_inr

    async def run(self, req: StepRequest) -> StepResult:
        spec = RunSpec(goal=req.goal[:900], allowed_domains=req.domains, start_url=req.start_url or None, max_steps=req.max_steps,
                       max_seconds=self.max_seconds, max_cost_inr=self.max_cost_inr, playbook=f"step:{req.step.type.value}",
                       login_site=req.login_site, lang=req.lang)
        self.overlay.set(req.user_id, req.facts)
        self.login.bind(req.user_id, req.otp_key)
        try:
            out = await self.agent.start(req.user_id, spec)
            return self._map(out)
        finally:
            self.overlay.clear(req.user_id)
            self.login.bind(req.user_id, "")

    async def reply(self, run_id: str, text: str) -> StepResult:
        st = self.agent.store.load(run_id)
        if st is None:
            return StepResult(status="failed", reason="the step is no longer open")
        self.overlay.set(st.user_id, {})
        try:
            out = await self.agent.reply(run_id, text)
        finally:
            self.overlay.clear(st.user_id)
        return self._map(out) if out is not None else StepResult(status="failed", reason="the step is no longer open")

    async def cancel(self, run_id: str) -> None:
        await self.agent.cancel(run_id)

    def _map(self, out: RunOutcome) -> StepResult:
        st = self.agent.store.load(out.run_id)
        proofs = [{"id": p.id, "what": p.what, "where": p.where, "when": p.when} for p in out.proofs]
        reason = st.reason if st is not None else ""
        base: dict[str, Any] = {"run_id": out.run_id, "proofs": proofs, "reason": reason}
        s = out.status
        if s == Status.DONE:
            return StepResult(status="ok", text=(st.result if st is not None else ""), **base)
        if s in (Status.WAITING_USER, Status.WAITING_CONFIRM):
            return StepResult(status="waiting", message=out.message, **base)
        if s == Status.BLOCKED:
            return StepResult(status="blocked", **base)
        if s == Status.PAYMENT_STOP:
            return StepResult(status="payment_stop", **base)
        if s == Status.BUSY:
            if st is not None:  # a busy loop run must not stay open: the runner starts a fresh one when it retries
                self.agent.store.save(st.model_copy(update={"status": Status.CANCELLED}))
            return StepResult(status="busy", **base)
        if s == Status.CANCELLED:
            return StepResult(status="failed", **{**base, "reason": reason or "cancelled"})
        return StepResult(status="failed", **base)
