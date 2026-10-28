# ruff: noqa: E501
"""The QA runner: plan -> typed/tapped approval -> visible 'ring now' countdown -> the call.

One run at a time. A call scenario only starts when the approval text is exactly
``APPROVAL_PHRASE`` ("YES, call my phone"). The countdown can be cancelled until the phone rings.
The guard (``QaGuard``) is asked at the start and again right before the dial, so the kill switch
(`friday pause`) and the caps are honoured at the last moment. Parameters can only be the
founder's first name, the area and the vendor name to say: a phone number is never a parameter, and
a phone-looking value anywhere in the parameters must be the allow-listed number or the run is refused.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from friday.integration.telephony import scrub_text
from friday.qa import scenarios as sc
from friday.qa.config import APPROVAL_PHRASE, QaConfig
from friday.qa.live import shortlist as places_shortlist
from friday.qa.models import FINAL, CallBackend, CallReport, CallSpec, ChatBackend, Run
from friday.qa.safety import QaGuard, QaRefused, estimate_cost
from friday.qa.store import QaStore

ALLOWED_PARAMS = ("first_name", "area", "vendor")
_PHONEISH = re.compile(r"\+?\d[\d\s\-().]{7,}\d")
_NAME_OK = re.compile(r"[^\w .,'&()/-]", re.UNICODE)


def clean(text: Any, limit: int) -> str:
    return _NAME_OK.sub("", str(text or "")).strip()[:limit]


class QaRunner:
    def __init__(
        self,
        guard: QaGuard,
        store: QaStore,
        calls: CallBackend,
        chat: ChatBackend | None = None,
        *,
        qa: QaConfig | None = None,
        first_name: str = sc.DEFAULT_FIRST_NAME,
        area: str = sc.DEFAULT_AREA,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.time,
        shortlist_fn: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self.guard, self.store, self.calls, self.chat = guard, store, calls, chat
        self.qa = qa or guard.qa
        self.first_name, self.area = first_name, area
        self.sleep, self.clock = sleep, clock
        self._shortlist = shortlist_fn or (lambda q, a: places_shortlist(guard.settings, q, a))
        self.runs: dict[str, Run] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------ listing
    def list_scenarios(self) -> list[dict[str, Any]]:
        verdicts = self.store.verdicts()
        out = []
        for s in sc.SCENARIOS:
            last = self.store.last_run(s.id)
            v = verdicts.get(s.id, {})
            out.append(
                {
                    "id": s.id,
                    "title": s.title,
                    "group": s.group,
                    "kind": s.kind,
                    "summary": s.summary,
                    "real": list(s.real),
                    "simulated": list(s.simulated),
                    "verdict": v.get("verdict", ""),
                    "notes": v.get("notes", [])[-3:],
                    "last_run": None
                    if last is None
                    else {
                        k: last.get(k)
                        for k in ("id", "ts", "phase", "status", "duration_s", "cost_inr")
                    },
                }
            )
        return out

    # ------------------------------------------------------------------ parameters
    def clean_params(self, params: dict[str, Any] | None) -> dict[str, str]:
        params = dict(params or {})
        for key, value in params.items():
            for m in _PHONEISH.finditer(str(value)):
                digits = re.sub(r"\D", "", m.group())
                self.guard.check_number(
                    digits and ("+" + digits if not digits.startswith("+") else digits)
                )
                # a phone-looking value that IS the allow-listed number is still not used as a number
            if key not in ALLOWED_PARAMS:
                raise QaRefused(
                    "bad_parameter",
                    f"'{key}' is not a QA parameter (only {', '.join(ALLOWED_PARAMS)}).",
                )
        return {
            "first_name": clean(params.get("first_name") or self.first_name, 30) or self.first_name,
            "area": clean(params.get("area") or self.area, 40) or self.area,
            "vendor": clean(params.get("vendor") or "", 60),
        }

    # ------------------------------------------------------------------ plan
    async def plan(self, sid: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        s = sc.get(sid)
        p = self.clean_params(params)
        secs = self.guard.clamp_seconds()
        out: dict[str, Any] = {
            "id": s.id,
            "title": s.title,
            "kind": s.kind,
            "summary": s.summary,
            "steps": list(s.steps),
            "hear": s.hear,
            "real": list(s.real),
            "simulated": list(s.simulated),
            "needs_approval": s.needs_approval,
            "approval_phrase": APPROVAL_PHRASE if s.needs_approval else "",
            "params": p,
            "shortlist": None,
            "vendor": "",
            "wait": "",
        }
        if s.kind == sc.KIND_CALL:
            out["number"] = self.guard.masked_target
            out["seconds"] = secs
            out["est_cost_inr"] = estimate_cost(secs)
            if s.shortlist_query:
                sl = await self._shortlist(s.shortlist_query, p["area"])
                out["shortlist"] = sl
                out["vendor"] = p["vendor"] or (sl["items"][0]["name"] if sl["items"] else "")
            if s.spec.get("backend") == "urgent":
                out["wait"] = (
                    f"Friday waits {self.qa.urgent_wait_minutes} minute(s) before calling (shortened for QA)."
                )
        return out

    # ------------------------------------------------------------------ start
    async def start(
        self, sid: str, approval: str = "", params: dict[str, Any] | None = None
    ) -> Run:
        s = sc.get(sid)
        busy = next((r for r in self.runs.values() if r.phase not in FINAL), None)
        if busy is not None:
            raise QaRefused(
                "busy", f"Another run is in progress ({busy.title}). Wait or cancel it."
            )
        if s.kind == sc.KIND_INFO:
            raise QaRefused(
                "nothing_to_run",
                "This scenario is instructions only: there is nothing for Friday to run.",
            )
        p = self.clean_params(params)
        run = Run(
            id=secrets.token_hex(4),
            scenario=s.id,
            title=s.title,
            kind=s.kind,
            created=self.clock(),
            real=list(s.real),
            simulated=list(s.simulated),
        )
        if s.kind == sc.KIND_CHAT:
            if self.chat is None:
                raise QaRefused("no_chat", "The chat engine is not available.")
            self.runs[run.id] = run
            self._tasks[run.id] = asyncio.create_task(self._run_chat(run, s))
            return run
        # a call: the exact approval phrase, the guard now, then the countdown
        if approval.strip() != APPROVAL_PHRASE:
            raise QaRefused("not_approved", f"Type exactly: {APPROVAL_PHRASE}")
        number, secs, est = self.guard.check_call(self.guard.target, None)
        vendor = p["vendor"]
        if s.shortlist_query and not vendor:
            sl = await self._shortlist(s.shortlist_query, p["area"])
            vendor = sl["items"][0]["name"] if sl["items"] else ""
        run.seconds, run.est_cost_inr = secs, est
        spec = CallSpec(
            scenario=s,
            number=number,
            seconds=secs,
            run_id=run.id,
            first_name=p["first_name"],
            vendor_name=vendor,
            area=p["area"],
            params=p,
        )
        self.runs[run.id] = run
        self._tasks[run.id] = asyncio.create_task(self._run_call(run, s, spec))
        return run

    # ------------------------------------------------------------------ the call run
    def _emit(self, run: Run) -> Callable[[str], None]:
        def emit(line: str) -> None:
            run.lines.append(scrub_text(line))
            if run.phase == "dialling" and re.search(
                r"placing the call|answer your phone|ringing|says", line, re.I
            ):
                run.phase = "in_call"

        return emit

    async def _run_call(self, run: Run, s: sc.Scenario, spec: CallSpec) -> None:
        emit = self._emit(run)
        try:
            wait_s = self.qa.countdown_s + (
                self.qa.urgent_wait_minutes * 60 if s.spec.get("backend") == "urgent" else 0
            )
            run.phase, run.ring_at = "countdown", self.clock() + wait_s
            emit(f"Ring now in {wait_s} seconds. Cancel to stop.")
            for _ in range(wait_s):
                if run.cancel_requested:
                    run.phase = "cancelled"
                    emit("Cancelled before the phone rang. Nothing was dialled.")
                    return
                await self.sleep(1)
            if run.cancel_requested:
                run.phase = "cancelled"
                emit("Cancelled before the phone rang. Nothing was dialled.")
                return
            # the last moment: kill switch, caps and the number are checked again
            spec.number, spec.seconds, _ = self.guard.check_call(spec.number, spec.seconds)
            run.phase = "dialling"
            emit("Dialling your phone now...")
            with self.guard.session(s.id, run.id):
                report = await self.calls.run(spec, emit)
            run.report = report
            self.guard.record_call(s.id, report.duration_s, report.cost_inr or run.est_cost_inr)
            run.phase = "failed" if report.status in {"failed", "refused"} else "done"
            if report.status == "refused":
                run.error = report.summary
        except QaRefused as e:
            run.phase, run.error = "refused", str(e)
            emit(f"REFUSED: {e}")
        except asyncio.CancelledError:
            run.phase = "cancelled"
            raise
        except Exception as e:  # noqa: BLE001 - the page shows it; never a stack trace with secrets
            run.phase, run.error = "failed", f"{type(e).__name__}: {scrub_text(str(e))[:300]}"
            emit(f"The run failed: {run.error}")
            # a failure after the dial started still counts against the caps (worst case)
            self.guard.record_call(s.id, 0.0, run.est_cost_inr)
        finally:
            self._save(run, s)

    async def _run_chat(self, run: Run, s: sc.Scenario) -> None:
        emit = self._emit(run)
        try:
            run.phase = "in_call"
            assert self.chat is not None
            run.report = await self.chat.run(s, emit)
            run.phase = "done"
        except Exception as e:  # noqa: BLE001
            run.phase, run.error = "failed", f"{type(e).__name__}: {scrub_text(str(e))[:300]}"
        finally:
            self._save(run, s)

    def _save(self, run: Run, s: sc.Scenario) -> None:
        rep = run.report
        self.store.add_run(
            {
                "id": run.id,
                "scenario": s.id,
                "title": s.title,
                "kind": s.kind,
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "phase": run.phase,
                "status": rep.status if rep else run.phase,
                "duration_s": rep.duration_s if rep else 0,
                "cost_inr": rep.cost_inr if rep else 0,
                "est_cost_inr": run.est_cost_inr,
                "real": run.real,
                "simulated": run.simulated,
                "outcome": rep.outcome if rep else "",
                "summary": scrub_text(rep.summary)[:600] if rep else run.error,
                "transcript": (rep.transcript if rep else [])[:200],
                "lines": run.lines[-80:],
                "error": run.error,
            }
        )

    # ------------------------------------------------------------------ control
    def cancel(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run.phase in FINAL:
            return run
        run.cancel_requested = True
        if run.phase in ("dialling", "in_call"):
            hang = getattr(self.calls, "hangup", None)
            if callable(hang):
                hang()
            run.lines.append("Hang-up requested.")
        return run

    def get(self, run_id: str) -> Run:
        try:
            return self.runs[run_id]
        except KeyError:
            raise KeyError("no such run") from None

    def current(self) -> Run | None:
        live = [r for r in self.runs.values() if r.phase not in FINAL]
        return live[-1] if live else (list(self.runs.values())[-1] if self.runs else None)

    async def wait(self, run_id: str) -> Run:
        task = self._tasks.get(run_id)
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return self.get(run_id)


__all__ = ["QaRunner", "CallReport"]
