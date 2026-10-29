# ruff: noqa: E501
"""The loop:  OBSERVE (compact snapshot) -> THINK (one strict-JSON action from the model) -> POLICY (plain code) -> ACT.

    start/resume -> session -> [ snapshot -> page guards (blocked / payment / domain) -> model -> policy -> act -> save ] ...
                                      |                                              |
                          stop: blocked, payment, budget                 pause: ask_user / request_confirmation
                                                                         (state saved; resumes on the user's chat reply)

Nothing a page says reaches the policy. The model picks one of 13 tools; there is no pay, no sign, no account-creation tool, and
the policy refuses the matching clicks and fields anyway. Typed values never enter a log, a prompt or the saved run state.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from friday.browser_agent import ask, rules, wording
from friday.browser_agent.errors import ActionFailed, Blocked, Busy
from friday.browser_agent.observe import SYSTEM, build_user_prompt, clip
from friday.browser_agent.policy import FACT_KEY, Policy, Verdict
from friday.browser_agent.ports import (
    AgentPage,
    BrowserLLM,
    FactSource,
    FileStore,
    LoginPort,
    PageProvider,
    ProofSink,
    RunStore,
)
from friday.browser_agent.stores import AgentLog, new_run_id
from friday.browser_agent.types import (
    TERMINAL,
    Action,
    AskField,
    HistoryItem,
    PageSnapshot,
    Pending,
    Permit,
    ProofRef,
    RunOutcome,
    RunSpec,
    RunState,
    Status,
)
from friday.core.clock import Clock, SystemClock
from friday.core.logging import get_logger

log = get_logger(__name__)
KEYS_OK = ("Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "PageDown", "PageUp", "Space")
SLUG = re.compile(r"[^a-z0-9]+")
_TRUTHY = re.compile(r"^\s*(yes|y|true|1|checked|haan|ha)\s*$", re.I)


def slug(s: str, n: int = 36) -> str:
    return SLUG.sub("_", s.lower()).strip("_")[:n] or "item"


def best_option(options: list[str], value: str) -> str | None:
    v = value.strip().lower()
    for o in options:
        if o.strip().lower() == v:
            return o
    hits = [o for o in options if v and (v in o.lower() or o.lower() in v)]
    return hits[0] if len(hits) == 1 else None


class _Stop(Exception):
    def __init__(self, outcome: RunOutcome) -> None:
        self.outcome = outcome


class BrowserAgent:
    def __init__(self, *, provider: PageProvider, llm: BrowserLLM, facts: FactSource, files: FileStore, store: RunStore,
                 proofs: ProofSink, login: LoginPort | None = None, log_sink: AgentLog | None = None, clock: Clock | None = None,
                 perf: Callable[[], float] = time.monotonic, ask_ttl_s: float = 86400.0, confirm_ttl_s: float = 1800.0,
                 permit_ttl_s: float = 600.0, max_asks: int = 4, max_refusals: int = 4,
                 file_names: Callable[[str], list[str]] | None = None) -> None:
        self.provider, self.llm, self.facts, self.files, self.store, self.proofs = provider, llm, facts, files, store, proofs
        self.login, self.log, self.clock, self.perf = login, log_sink or AgentLog(), clock or SystemClock(), perf
        self.ask_ttl, self.confirm_ttl, self.permit_ttl = ask_ttl_s, confirm_ttl_s, permit_ttl_s
        self.max_asks, self.max_refusals = max_asks, max_refusals
        self._file_names = file_names or (lambda _u: [])
        self._locks: dict[str, asyncio.Lock] = {}

    # ================================================================== public API
    def now_iso(self) -> str:
        return self.clock.now().isoformat(timespec="seconds")

    def _later(self, seconds: float) -> str:
        return (self.clock.now() + timedelta(seconds=seconds)).isoformat(timespec="seconds")

    async def start(self, user_id: str, spec: RunSpec, *, preask: list[AskField] | None = None) -> RunOutcome:
        """Create a run and drive it until it finishes or needs the user. Domains are checked HERE, by code. ``preask``: fields to ask first."""
        doms = [d.lower().strip() for d in spec.allowed_domains if d and d.strip()]
        if not doms or any(rules.domain_denied(d) for d in doms):
            state = RunState(id=new_run_id(), user_id=user_id, spec=spec, created_at=self.now_iso(), updated_at=self.now_iso())
            return self._end(state, Status.GAVE_UP, reason="no usable allowed site (government, identity and payment sites are never opened)")
        spec = spec.model_copy(update={"allowed_domains": doms})
        active = self.store.active_for(user_id)
        if active is not None:
            return RunOutcome(run_id=active.id, status=active.status, message=wording.line("already_running", spec.lang))
        state = RunState(id=new_run_id(), user_id=user_id, spec=spec, created_at=self.now_iso(), updated_at=self.now_iso())
        self.store.save(state)
        self.log("run_start", run=state.id, domains=",".join(doms), playbook=spec.playbook, steps=spec.max_steps)
        if preask:  # known gaps in the user's profile: ONE grouped question BEFORE the browser is opened (no browser, no model cost)
            return self._pause_fields(state, preask, doms[0])
        return await self._run(state)

    async def resume(self, run_id: str) -> RunOutcome | None:
        """After a restart or a 'busy': continue a run that is not waiting for the user."""
        state = self.store.load(run_id)
        if state is None or state.status in (Status.WAITING_USER, Status.WAITING_CONFIRM) or state.status in TERMINAL:
            return None
        return await self._run(state)

    async def cancel(self, run_id: str) -> RunOutcome | None:
        state = self.store.load(run_id)
        if state is None:
            return None
        if state.status in (Status.DONE, Status.CANCELLED):
            return None
        return self._end(state, Status.CANCELLED, reason="user")

    async def reply(self, run_id: str, text: str) -> RunOutcome | None:
        """The user's chat message answers the open question / confirmation of this run."""
        state = self.store.load(run_id)
        if state is None or state.pending is None:
            return None
        lang = state.spec.lang
        p = state.pending
        if self.clock.now() > datetime.fromisoformat(p.expires_at):
            return self._end(state, Status.EXPIRED, reason="no_reply")
        if ask.looks_secret(text):
            self.log("secret_reply_refused", run=state.id)  # the text itself is never logged
            return RunOutcome(run_id=state.id, status=state.status, message=wording.line("secret_refused", lang), question=p.question)
        if p.kind == "confirm":
            return await self._reply_confirm(state, p, text)
        if p.ask_kind in ("allow_domain", "allow_account"):
            return await self._reply_yes_no(state, p, text)
        if p.ask_kind in ("login", "otp"):
            if not ask.is_done(text) and ask.yes_no(text) is False:
                return self._end(state, Status.CANCELLED, reason="user")
            state.pending, state.status = None, Status.RUNNING
            return await self._run(state)
        if p.ask_kind == "yes_no":
            yn = ask.yes_no(text)
            if yn is None:
                return RunOutcome(run_id=state.id, status=state.status, message=p.question, question=p.question)
            state.notes.append(f"user answered {'yes' if yn else 'no'} to: {clip(p.question, 120)}")
            state.pending, state.status = None, Status.RUNNING
            return await self._run(state)
        return await self._reply_fields(state, p, text)

    def sweep(self) -> list[RunOutcome]:
        """Politely close runs whose question or confirmation timed out. Nothing irreversible ever happens on a timeout."""
        out = []
        for s in self.store.list_open():
            if s.pending is not None and self.clock.now() > datetime.fromisoformat(s.pending.expires_at):
                out.append(self._end(s, Status.EXPIRED, reason="no_reply"))
        return out

    def forget_user(self, user_id: str) -> int:
        return self.store.delete_user(user_id)

    # ================================================================== replies
    async def _reply_fields(self, state: RunState, p: Pending, text: str) -> RunOutcome:
        lang = state.spec.lang
        answers, left = ask.parse_reply(p.fields, text)
        if left and len(text) > 12 and not (ask.OK.match(text.strip())):
            try:  # a free-form reply: let the model map it onto the asked fields (it can only return the asked keys)
                got, cost = await self.llm.parse_answers(fields=left, reply=text)
                state.spent_inr += cost
                keys = {f.key for f in left}
                for k, v in got.items():
                    if k in keys and v and not ask.looks_secret(v):
                        answers.setdefault(k, v)
                left = [f for f in p.fields if f.key not in answers]
            except Exception:  # noqa: BLE001
                self.log("parse_answers_failed", run=state.id)
        facts = await self.facts.load(state.user_id)
        for key, val in answers.items():
            if ask.is_attest_key(key):
                state.attest[key[7:]] = val == "yes"
            elif re.fullmatch(r"q\d+", key):
                state.notes.append(f"user said: {clip(val, 160)}")
            elif FACT_KEY.match(key):
                await self.facts.remember(state.user_id, key, val)
                facts[key] = val
        self.log("answers_received", run=state.id, keys=",".join(sorted(k for k in answers if not ask.is_attest_key(k))), attest=len([k for k in answers if ask.is_attest_key(k)]))
        if left:
            p2 = p.model_copy(update={"fields": left, "question": ask.format_question(left, host=p.host, lang=lang)})
            state.pending = p2
            self.store.save(state)
            msg = (wording.line("not_understood", lang, labels=ask.pending_label(p2)) + "\n" + p2.question) if not answers else p2.question
            return RunOutcome(run_id=state.id, status=Status.WAITING_USER, message=msg, question=p2.question)
        state.pending, state.status = None, Status.RUNNING
        return await self._run(state)

    async def _reply_confirm(self, state: RunState, p: Pending, text: str) -> RunOutcome:
        yn = ask.yes_no(text)
        if yn is None:
            msg = ask.confirm_pending(p.summary, host=p.host, lang=state.spec.lang, again=True)
            return RunOutcome(run_id=state.id, status=Status.WAITING_CONFIRM, message=msg, question=msg)
        if not yn:
            self.log("confirmation_declined", run=state.id, host=p.host)
            return self._end(state, Status.CANCELLED, reason="declined")
        state.permits.append(Permit(id=p.id, summary=p.summary, host=p.host, expires_at=self._later(self.permit_ttl), label=p.target))
        state.pending, state.status = None, Status.RUNNING
        self.log("confirmation_granted", run=state.id, host=p.host, permit=p.id)
        return await self._run(state)

    async def _reply_yes_no(self, state: RunState, p: Pending, text: str) -> RunOutcome:
        yn = ask.yes_no(text)
        if yn is None:
            return RunOutcome(run_id=state.id, status=state.status, message=p.question, question=p.question)
        if not yn:
            return self._end(state, Status.GAVE_UP, reason="you declined: " + p.ask_kind.replace("_", " ") + " " + p.domain)
        if p.ask_kind == "allow_domain":
            state.extra_domains.append(p.domain)
            await self.provider.reopen(state.user_id, state.spec)
        else:
            state.spec.account_ok_hosts.append(p.domain)
        self.log("user_allowed", run=state.id, what=p.ask_kind, host=p.domain)
        state.pending, state.status = None, Status.RUNNING
        return await self._run(state)

    # ================================================================== driving
    def _domains(self, state: RunState) -> list[str]:
        return [*state.spec.allowed_domains, *state.extra_domains]

    async def _run(self, state: RunState) -> RunOutcome:
        lock = self._locks.setdefault(state.id, asyncio.Lock())
        async with lock:
            try:
                return await self._drive(state)
            except _Stop as s:
                return s.outcome
            except Exception as e:  # noqa: BLE001 - a bug must stop the run safely, never loop
                self.log("run_error", run=state.id, error=type(e).__name__)
                return self._end(state, Status.ERROR, reason=type(e).__name__)

    async def _drive(self, state: RunState) -> RunOutcome:
        state.status = Status.RUNNING
        domains = self._domains(state)
        try:
            async with self.provider.session(state.user_id, state.spec, domains) as page:
                await self._ensure_page(state, page, domains)
                return await self._loop(state, page, domains)
        except Blocked as e:
            return self._end(state, Status.BLOCKED, reason=e.reason)
        except Busy as e:
            state.status, state.reason = Status.BUSY, e.reason
            self.store.save(state)
            self.log("run_busy", run=state.id, reason=e.reason)
            return RunOutcome(run_id=state.id, status=Status.BUSY, message=wording.line("busy", state.spec.lang))

    async def _ensure_page(self, state: RunState, page: AgentPage, domains: list[str]) -> None:
        target = state.last_url or state.spec.start_url or f"https://{domains[0]}/"
        cur = page.current_url()
        if cur and cur not in ("about:blank",) and rules.host_of(cur) == rules.host_of(target):
            return
        v = Policy(state, domains, self.clock.now()).check_goto(target)
        if not v.ok:
            if rules.payment_url(target):
                raise _Stop(self._end(state, Status.PAYMENT_STOP, reason="payment address"))
            raise _Stop(self._end(state, Status.GAVE_UP, reason=v.reason))
        await page.goto(target)

    def _budget_stop(self, state: RunState) -> str:
        s = state.spec
        if state.step >= s.max_steps:
            return "steps"
        if state.active_s >= s.max_seconds:
            return "time"
        if state.spent_inr >= s.max_cost_inr:
            return "cost"
        return ""

    async def _loop(self, state: RunState, page: AgentPage, domains: list[str]) -> RunOutcome:
        facts = await self.facts.load(state.user_id)
        last_p = self.perf()
        while True:
            now_p = self.perf()
            state.active_s += max(0.0, now_p - last_p)
            last_p = now_p
            stop = self._budget_stop(state)
            if stop:
                return self._end(state, Status.BUDGET, reason=stop)
            snap = await page.snapshot()
            state.last_url = snap.url
            guard = self._page_guard(state, snap, domains)
            if guard is not None:
                return guard
            state.step += 1
            prompt = build_user_prompt(state, domains, facts, snap, files=self._file_names(state.user_id), extra=self._notes_block(state))
            try:
                action, cost = await self.llm.decide(system=SYSTEM, user=prompt)
            except Exception as e:  # noqa: BLE001
                state.refusals += 1
                self.log("model_error", run=state.id, error=type(e).__name__)
                if state.refusals >= self.max_refusals:
                    return self._end(state, Status.GAVE_UP, reason="the assistant model is not answering")
                continue
            state.spent_inr += cost
            out = await self._act(state, page, snap, action, facts, domains)
            state.updated_at = self.now_iso()
            self.store.save(state)
            if out is not None:
                return out
            if state.refusals >= self.max_refusals:
                return self._end(state, Status.GAVE_UP, reason="I kept being stopped by my own safety rules on this page")

    def _notes_block(self, state: RunState) -> str:
        if not state.notes:
            return ""
        return "NOTES (answers read earlier or given by the user):\n" + "\n".join("- " + n for n in state.notes[-6:]) + "\n"

    def _page_guard(self, state: RunState, snap: PageSnapshot, domains: list[str]) -> RunOutcome | None:
        host = rules.host_of(snap.url)
        if snap.http_status in (401, 403, 429):
            return self._end(state, Status.BLOCKED, reason=f"http_{snap.http_status}")
        if rules.page_has_captcha(snap):
            return self._end(state, Status.BLOCKED, reason="challenge")
        if rules.page_is_payment(snap):
            if state.spec.handover_payment_link and rules.host_allowed(host, domains):
                state.handover_url = snap.url
            return self._end(state, Status.PAYMENT_STOP, reason="payment step")
        if host and rules.domain_denied(host):
            return self._end(state, Status.GAVE_UP, reason="the page moved to a site Friday never opens")
        if host and not rules.host_allowed(host, domains):
            if state.asks >= self.max_asks:
                return self._end(state, Status.GAVE_UP, reason="the page moved to a site outside this task")
            return self._ask_binary(state, "allow_domain", host)
        return None

    # ================================================================== acting
    def _hist(self, state: RunState, a: Action, target: str, result: str) -> None:
        state.history.append(HistoryItem(step=state.step, tool=a.tool, target=clip(target, 50), result=clip(result, 140)))
        del state.history[:-30]

    def _refuse(self, state: RunState, a: Action, label: str, why: str) -> None:
        state.refusals += 1
        self._hist(state, a, label, "REFUSED: " + why)
        self.log("action_refused", run=state.id, tool=a.tool, label=label, why=why)

    async def _act(self, state: RunState, page: AgentPage, snap: PageSnapshot, a: Action, facts: dict[str, str], domains: list[str]) -> RunOutcome | None:
        pol = Policy(state, domains, self.clock.now())
        host = rules.host_of(snap.url)
        sig = f"{a.tool}|{a.target}|{a.value_source or a.option or a.url or a.key}|{host}{rules.strip_query(snap.url)}"
        state.recent_sigs = [*state.recent_sigs[-5:], sig]
        if state.recent_sigs.count(sig) >= 3 and a.tool not in ("wait", "finish", "give_up"):
            return self._end(state, Status.GAVE_UP, reason="I was repeating the same step without progress")
        t = a.tool
        if t == "give_up":
            return self._end(state, Status.GAVE_UP, reason=clip(a.reason or "not possible", 300))
        if t == "finish":
            if state.deferred:
                return self._flush(state, host)
            return self._end(state, Status.DONE, result=clip(a.result or "", 600))
        if t == "ask_user":
            return self._ask_user(state, snap, a, facts)
        if t == "request_confirmation":
            return self._request_confirmation(state, snap, a)
        if t == "wait":
            await page.wait(max(200, min(int(a.ms or 1000), 5000)))
            self._hist(state, a, "", "waited")
            return None
        if t == "screenshot_proof":
            await self._proof(state, page, a.note or "screenshot")
            self._hist(state, a, "", "proof saved")
            return None
        if t == "extract":
            q = clip(a.question or "", 200)
            if not q:
                self._refuse(state, a, "", "extract needs a question")
                return None
            try:
                ans, cost = await self.llm.extract(question=q, page_text=snap.text)
                state.spent_inr += cost
                state.notes.append(f"{q} -> {clip(ans, 300)}")
                del state.notes[:-12]
                self._hist(state, a, q, clip(ans, 120))
                state.refusals = 0
            except Exception:  # noqa: BLE001
                self._hist(state, a, q, "extract failed")
            return None
        v = pol.check_action(a, snap)
        el = next((e for e in snap.elements if e.id == (a.target or "")), None)
        if not v.ok:
            return self._on_refusal(state, snap, a, v, el, host)
        if t in ("goto", "click", "press") and state.deferred:
            return self._flush(state, host)  # never leave a page with unanswered fields: ask them all, once
        try:
            res = await self._execute(state, page, snap, a, v, el, facts)
        except ActionFailed:
            state.refusals += 1
            self._hist(state, a, v.label, "FAILED: the page did not accept that")
            return None
        if isinstance(res, RunOutcome):
            return res
        res = res or "ok"
        self._hist(state, a, v.label, res)
        if res.startswith("REFUSED"):
            state.refusals += 1
        elif not res.startswith("missing"):
            state.refusals = 0
        return None

    def _on_refusal(self, state: RunState, snap: PageSnapshot, a: Action, v: Verdict, el: Any, host: str) -> RunOutcome | None:
        if v.code == "payment":
            self.log("payment_stop", run=state.id, host=host, label=v.label)
            if state.spec.handover_payment_link:
                state.handover_url = snap.url
            return self._end(state, Status.PAYMENT_STOP, reason=v.label or "payment control")
        if v.code == "need_account":
            if rules.domain_denied(host) or state.asks >= self.max_asks:
                self._refuse(state, a, v.label, "accounts are not created here")
                return None
            return self._ask_binary(state, "allow_account", host)
        if v.code == "left_for_user":
            if v.label and v.label not in state.left_for_user:
                state.left_for_user.append(v.label)
            self._hist(state, a, v.label, "left for the user (ID numbers are never typed by Friday)")
            return None
        if v.code == "need_attest":
            self._refuse(state, a, v.label, "legal statement: use value_source attest:<short_key> so the user answers it themselves")
            return None
        if v.code == "domain" and a.tool == "goto":
            h = rules.host_of(a.url or "")
            self.log("goto_refused", run=state.id, host=h)
        why = v.reason
        if v.code == "need_confirm":
            why += " -> call request_confirmation with the exact text first"
        self._refuse(state, a, v.label, why)
        return None

    async def _execute(self, state: RunState, page: AgentPage, snap: PageSnapshot, a: Action, v: Verdict, el: Any, facts: dict[str, str]) -> str | RunOutcome | None:
        t = a.tool
        if t == "goto":
            await page.goto(a.url or "")
            self.log("goto", run=state.id, host=rules.host_of(a.url or ""))
            return "opened " + rules.host_of(a.url or "")
        if t == "press":
            key = a.key or ""
            if key not in KEYS_OK:
                return "REFUSED: key not allowed"
            if key == "Enter":
                for e in snap.elements:
                    if e.submit and rules.is_irreversible(e):
                        pv = Policy(state, self._domains(state), self.clock.now())._check_click(e, snap, rules.own_label(e)[:60])
                        if not pv.ok:
                            return "REFUSED: Enter would submit this form (" + pv.reason + ")"
                        v = pv
                        el = e
                        break
            await page.press(key)
            if v.via and el is not None:
                await self._after_irreversible(state, page, el, v)
            return "pressed " + key
        assert el is not None
        if t == "click":
            await page.click(el.id)
            self.log("click", run=state.id, label=v.label)
            if v.via:
                await self._after_irreversible(state, page, el, v)
            return "clicked"
        if t == "upload":
            ref = a.file_ref or ""
            path = self.files.resolve(state.user_id, ref)
            if not path:
                if v.label not in state.left_for_user:
                    state.left_for_user.append(f"attach {ref or 'file'} ({v.label})")
                return "no such file is registered; left for the user"
            if state.uploads.get(ref, 0) >= 2:
                return "REFUSED: upload already failed twice; left for the user"
            ok = await page.upload(el.id, path)
            self.log("upload", run=state.id, ref=ref, ok=ok)
            if not ok:
                state.uploads[ref] = state.uploads.get(ref, 0) + 1
                if state.uploads[ref] >= 2:
                    state.left_for_user.append(f"attach {ref} yourself")
                return "upload not confirmed by the page"
            return f"uploaded {ref}"
        # fill / select
        src = a.value_source if t == "fill" else (a.option or "")
        value, missing, wait_login = await self._resolve(state, src or "", el, a, facts, snap)
        if wait_login is not None:
            return wait_login
        if missing is not None:
            state.deferred = ask.merge_fields(state.deferred, [missing])
            self.log("field_missing", run=state.id, key=missing.key)
            return f"missing {missing.key}: noted, keep filling the others"
        assert value is not None
        label = v.label
        if el.role == "select":
            opt = best_option(el.options, value) if el.options else value
            if opt is None:
                state.deferred = ask.merge_fields(state.deferred, [AskField(key=self._key_for(src, el), label=clip(el.name, 80), options=el.options[:12])])
                return "missing: no option matches the stored answer; noted"
            await page.select(el.id, opt)
        elif el.role in ("checkbox", "radio"):
            if el.role == "radio":
                if not (value.strip().lower() in el.name.lower() or el.name.strip().lower() in value.lower()):
                    return "REFUSED: this radio does not match the stored answer; pick the one that does"
                await page.check(el.id, True)
            else:
                await page.check(el.id, bool(_TRUTHY.match(value)))
        else:
            await page.fill(el.id, value)
        self.log("fill", run=state.id, label=label, source=src.split(":")[0] if src.startswith(("vault", "otp")) else src)
        return f"set from {src.split(':')[0] if src.startswith(('vault', 'otp')) else src}"

    def _key_for(self, src: str, el: Any) -> str:
        if src.startswith("fact:") and FACT_KEY.match(src[5:]):
            return src[5:]
        return slug(el.name, 30)

    async def _resolve(self, state: RunState, src: str, el: Any, a: Action, facts: dict[str, str], snap: PageSnapshot) -> tuple[str | None, AskField | None, RunOutcome | None]:
        host = rules.host_of(snap.url)
        if src.startswith("fact:"):
            key = src[5:]
            if key in facts:
                return facts[key], None, None
            sug = a.suggest if (a.suggest and not ask.looks_secret(a.suggest)) else None
            return None, AskField(key=key, label=clip(el.name or el.placeholder or key, 80), default=clip(sug, 80) if sug else None, options=el.options[:12] or None), None
        if src.startswith("attest:"):
            k = src[7:]
            if k in state.attest:
                return ("yes" if state.attest[k] else "no"), None, None
            return None, AskField(key="attest:" + k, label=clip(el.name or el.placeholder, 300)), None
        if src in ("vault:username", "vault:password"):
            cred = self.login.release(state.user_id, state.spec.login_site or host, host) if self.login else None
            if cred is None:
                return None, None, self._ask_login(state, "login", host)
            return cred[0 if src.endswith("username") else 1], None, None
        if src == "otp":
            code = self.login.take_otp(state.id) if self.login else None
            if code is None:
                return None, None, self._ask_login(state, "otp", host)
            return code, None, None
        if src.startswith("text:"):
            return src[5:].strip(), None, None
        # a select with a plain option text (policy already checked it is on the page)
        return src, None, None

    # ================================================================== proofs
    async def _after_irreversible(self, state: RunState, page: AgentPage, el: Any, v: Verdict) -> None:
        await page.wait(800)
        what = f"clicked '{rules.own_label(el)[:60]}'"
        permit = next((p for p in state.permits if p.id == v.permit_id), None)
        if permit is not None:
            what += f": {clip(permit.summary, 120)}"
            if permit.action_class == "job_application_submit":
                what += " (standing opt-in)"
            state.permits = [p for p in state.permits if p.id != permit.id]
        if v.via == "standing":
            state.spec.standing_ok = []  # one application per run
            what += " (standing opt-in)"
        await self._proof(state, page, what)
        self.log("irreversible_done", run=state.id, via=v.via or "permit", host=rules.host_of(page.current_url()), label=rules.own_label(el)[:60])

    async def _proof(self, state: RunState, page: AgentPage, what: str) -> None:
        try:
            png = await page.screenshot()
            pid, path = self.proofs.save(state.user_id, state.id, what, page.current_url(), png)
        except Exception:  # noqa: BLE001 - a missing screenshot must not hide that the action happened
            pid, path = "", ""
        state.proofs.append(ProofRef(id=pid, what=clip(what, 200), where=rules.strip_query(page.current_url()), when=self.now_iso(), path=path))

    # ================================================================== pausing for the user
    def _flush(self, state: RunState, host: str) -> RunOutcome | None:
        """ONE grouped message with every missing field collected so far."""
        if state.asks >= self.max_asks:
            return self._end(state, Status.GAVE_UP, reason="I needed too many answers from you for this form")
        fields, state.deferred = state.deferred, []
        return self._pause_fields(state, fields, host)

    def _pause_fields(self, state: RunState, fields: list[AskField], host: str, link: str = "") -> RunOutcome:
        q = ask.format_question(fields, host=host or "the site", lang=state.spec.lang)
        state.pending = Pending(kind="ask", id=new_run_id(), question=q, ask_kind="info", fields=fields, host=host,
                                created_at=self.now_iso(), expires_at=self._later(self.ask_ttl), link=link)
        state.status, state.asks = Status.WAITING_USER, state.asks + 1
        self.store.save(state)
        self.log("ask_user", run=state.id, kind="info", fields=",".join(f.key for f in fields), host=host)
        return RunOutcome(run_id=state.id, status=Status.WAITING_USER, message=q, question=q)

    def _ask_binary(self, state: RunState, kind: str, host: str) -> RunOutcome:
        q = wording.line(kind, state.spec.lang, host=host)
        state.pending = Pending(kind="ask", id=new_run_id(), question=q, ask_kind=kind, host=host, domain=host,
                                created_at=self.now_iso(), expires_at=self._later(self.ask_ttl))
        state.status, state.asks = Status.WAITING_USER, state.asks + 1
        self.store.save(state)
        self.log("ask_user", run=state.id, kind=kind, host=host)
        return RunOutcome(run_id=state.id, status=Status.WAITING_USER, message=q, question=q)

    def _ask_login(self, state: RunState, kind: str, host: str) -> RunOutcome | None:
        site = state.spec.login_site or host
        link = None
        if self.login is not None:
            link = self.login.credential_link(state.user_id, site, [host]) if kind == "login" else self.login.otp_link(state.user_id, site, state.id)
        if not link or state.asks >= self.max_asks:
            return self._end(state, Status.GAVE_UP, reason="this needs a login that I cannot take safely here; please log in yourself")
        q = wording.line(kind, state.spec.lang, host=host, link=link)
        state.pending = Pending(kind="ask", id=new_run_id(), question=q, ask_kind=kind, host=host, link=link,
                                created_at=self.now_iso(), expires_at=self._later(self.ask_ttl))
        state.status, state.asks = Status.WAITING_USER, state.asks + 1
        self.store.save(state)
        self.log("ask_user", run=state.id, kind=kind, host=host)  # the link is not logged
        return RunOutcome(run_id=state.id, status=Status.WAITING_USER, message=q, question="")

    def _ask_user(self, state: RunState, snap: PageSnapshot, a: Action, facts: dict[str, str]) -> RunOutcome | None:
        host, kind = rules.host_of(snap.url), a.kind or "info"
        if state.asks >= self.max_asks:
            return self._end(state, Status.GAVE_UP, reason="I needed too many answers from you for this task")
        if kind in ("info", "choice", "attestation"):
            fields: list[AskField] = []
            for i, f in enumerate(a.fields or []):
                key = f.key if (kind != "attestation") else "attest:" + slug(f.key)
                if kind != "attestation" and not FACT_KEY.match(key):
                    key = f"q{state.asks}{i}"
                if key in facts and kind != "attestation":
                    continue  # never ask what we already know
                fields.append(f.model_copy(update={"key": key, "label": clip(f.label, 300 if kind == "attestation" else 100)}))
            if not fields and a.question and kind != "attestation":
                fields = [AskField(key=f"q{state.asks}0", label=clip(a.question, 160))]
            if kind == "attestation" and not fields and a.question:
                fields = [AskField(key="attest:" + slug(a.question), label=clip(a.question, 300))]
            merged = ask.merge_fields(state.deferred, fields)
            if not merged:
                self._refuse(state, a, "", "everything you asked is already known: use fact:<key>")
                return None
            state.deferred = []
            return self._pause_fields(state, merged, host)
        if kind == "yes_no":
            q = clip(a.question or "", 300)
            if not q:
                self._refuse(state, a, "", "ask_user needs a question")
                return None
            state.pending = Pending(kind="ask", id=new_run_id(), question=q, ask_kind="yes_no", host=host, created_at=self.now_iso(), expires_at=self._later(self.ask_ttl))
            state.status, state.asks = Status.WAITING_USER, state.asks + 1
            self.store.save(state)
            return RunOutcome(run_id=state.id, status=Status.WAITING_USER, message=q, question=q)
        if kind == "allow_domain":
            h = rules.host_of(a.url or "")
            if not h or rules.domain_denied(h) or rules.payment_url(a.url or ""):
                self._refuse(state, a, "", "that site cannot be allowed")
                return None
            return self._ask_binary(state, "allow_domain", h)
        if kind == "allow_account":
            if rules.domain_denied(host):
                self._refuse(state, a, "", "accounts are never created on this kind of site")
                return None
            return self._ask_binary(state, "allow_account", host)
        if kind in ("login", "otp"):
            return self._ask_login(state, kind, host)
        self._refuse(state, a, "", "unknown question kind")
        return None

    def _request_confirmation(self, state: RunState, snap: PageSnapshot, a: Action) -> RunOutcome | None:
        summary = clip(a.summary or "", 500)
        if not summary:
            self._refuse(state, a, "", "request_confirmation needs the exact text and consequence")
            return None
        if state.deferred:
            return self._flush(state, rules.host_of(snap.url))  # missing answers come first, in the same single message
        host = rules.host_of(snap.url)
        pol = Policy(state, self._domains(state), self.clock.now())
        if state.spec.playbook == "job_apply" and "job_application_submit" in state.spec.standing_ok and not pol._has_open_attestation(snap):
            state.permits.append(Permit(id=new_run_id(), summary=summary, host=host, expires_at=self._later(self.permit_ttl), action_class="job_application_submit"))
            state.spec.standing_ok = []  # ONE application per run: the standing opt-in is spent by this permit
            self._hist(state, a, "", "standing opt-in covers this application")
            self.log("standing_permit", run=state.id, host=host)
            return None
        el = next((e for e in snap.elements if e.id == (a.target or "")), None)
        label = rules.own_label(el)[:60] if el is not None else ""
        q = ask.confirm_pending(summary + (f'\nButton: "{label}"' if label else ""), host=host, lang=state.spec.lang)
        state.pending = Pending(kind="confirm", id=new_run_id(), question=q, summary=summary, target=label, host=host, created_at=self.now_iso(), expires_at=self._later(self.confirm_ttl))
        state.status = Status.WAITING_CONFIRM
        self.store.save(state)
        self.log("request_confirmation", run=state.id, host=host)
        return RunOutcome(run_id=state.id, status=Status.WAITING_CONFIRM, message=q, question=q)

    # ================================================================== ending
    def _manual(self, state: RunState) -> str:
        lang = state.spec.lang
        where = rules.strip_query(state.last_url) or (state.spec.allowed_domains[0] if state.spec.allowed_domains else "the site")
        txt = wording.line("manual_open", lang, where=where)
        labels = []
        for h in state.history:
            if h.tool == "fill" and h.target and h.target not in labels and not h.result.startswith(("REFUSED", "missing")):
                labels.append(h.target)
        labels += [f.label for f in state.deferred if not ask.is_attest_key(f.key)]
        if labels:
            txt += wording.line("manual_fields", lang, fields=", ".join(labels[:8]))
        if state.left_for_user:
            txt += wording.line("manual_left", lang, fields=", ".join(state.left_for_user[:6]))
        return txt

    def _message(self, state: RunState) -> str:
        lang, host = state.spec.lang, (rules.host_of(state.last_url) or (state.spec.allowed_domains[0] if state.spec.allowed_domains else "the site"))
        st = state.status
        proofs = "".join("\n" + wording.line("proof", lang, what=p.what, where=p.where, when=p.when) for p in state.proofs)
        if st == Status.DONE:
            msg = wording.line("done", lang, result=state.result or "finished") + proofs
            if state.left_for_user:
                msg += wording.line("manual_left", lang, fields=", ".join(state.left_for_user[:6]))
            return msg
        if st == Status.BLOCKED:
            return wording.line("blocked", lang, host=host, reason=state.reason, manual=self._manual(state))
        if st == Status.PAYMENT_STOP:
            link = wording.line("payment_link", lang, url=state.handover_url) if state.handover_url else ""
            return wording.line("payment", lang, link=link) + proofs
        if st == Status.BUDGET:
            what = {"steps": "steps", "time": "time", "cost": "budget"}.get(state.reason, "budget")
            return wording.line("budget", lang, what=what, manual=self._manual(state)) + proofs
        if st == Status.GAVE_UP:
            return wording.line("gave_up", lang, reason=state.reason or "not possible", manual=self._manual(state)) + proofs
        if st == Status.EXPIRED:
            return wording.line("expired", lang)
        if st == Status.CANCELLED:
            return wording.line("declined" if state.reason == "declined" else "cancelled", lang)
        return wording.line("error", lang, manual=self._manual(state))

    def _end(self, state: RunState, status: Status, *, reason: str = "", result: str = "") -> RunOutcome:
        state.status, state.pending = status, None
        state.reason = reason or state.reason
        state.result = redact(result) or state.result
        state.updated_at = self.now_iso()
        self.store.save(state)
        self.log("run_end", run=state.id, status=status.value, reason=reason, steps=state.step, cost_inr=round(state.spent_inr, 2), proofs=len(state.proofs))
        return RunOutcome(run_id=state.id, status=status, message=self._message(state), proofs=list(state.proofs), handover_url=state.handover_url)


def redact(s: str) -> str:
    from friday.voice.text import redact_secrets

    return redact_secrets(s or "")
