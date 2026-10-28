# ruff: noqa: E501
"""The QA page: one HTML page and a small JSON API behind an unguessable, expiring token.

    GET  /qa/<token>/                 the page (iPad friendly)
    GET  /qa/api/<token>/...          the API

Same pattern as the Chat Lab (``friday/lab/app.py``): a bad or expired token answers 404 with no
hint, responses are no-store / noindex / no-referrer. Unlike the lab this page can ring the
founder's own phone, so ``create_qa_app`` refuses to build unless every start-up rule holds
(``QaGuard.require_startable``: FRIDAY_QA_LIVE, live mode, pilot profile, exactly one allow-listed
number), and every run is checked again by the guard and needs the typed approval phrase.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from friday.lab.app import DEFAULT_TTL_HOURS, HEADERS, PAGE_CSP, TokenGate
from friday.qa import report as qa_report
from friday.qa import scenarios as sc
from friday.qa.config import APPROVAL_PHRASE, QaConfig
from friday.qa.runner import QaRunner
from friday.qa.safety import QaGuard, QaRefused
from friday.qa.store import QaStore

STATIC = Path(__file__).parent / "static"


class PlanIn(BaseModel):
    scenario: str
    params: dict[str, Any] = Field(default_factory=dict)


class RunIn(BaseModel):
    scenario: str
    approval: str = Field(default="", max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class RunRef(BaseModel):
    run_id: str


class NoteIn(BaseModel):
    scenario: str
    verdict: str = Field(default="", max_length=20)
    note: str = Field(default="", max_length=1000)


class LineIn(BaseModel):
    line_id: str = Field(max_length=120)
    decision: str = Field(max_length=10)
    note: str = Field(default="", max_length=1000)


def create_qa_app(
    settings: Any,
    qa: QaConfig | None = None,
    *,
    store: QaStore | None = None,
    runner: QaRunner | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    token: str | None = None,
    now: Callable[[], float] = time.time,
) -> FastAPI:
    qa = qa or QaConfig()
    store = store or (runner.store if runner else QaStore(qa.path))
    guard = runner.guard if runner else QaGuard(settings, qa, store)
    guard.require_startable()  # raises QaRefused: the page does not start otherwise
    if runner is None:
        from friday.qa.live import LabChat, SubprocessBackend

        runner = QaRunner(
            guard, store, SubprocessBackend(), LabChat(qa.path / "lab_notes.jsonl"), qa=qa
        )
    gate = TokenGate(ttl_hours, now, token)
    app = FastAPI(
        title="Friday QA", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.gate, app.state.runner, app.state.store, app.state.guard = gate, runner, store, guard

    def check(token_: str) -> None:
        if not gate.ok(token_):
            raise HTTPException(status_code=404)

    @app.exception_handler(QaRefused)
    async def _refused(request: Request, exc: QaRefused) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc), "code": exc.code}, status_code=403, headers=HEADERS
        )

    @app.exception_handler(KeyError)
    async def _missing(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": "not found"}, status_code=404, headers=HEADERS)

    def json_(data: Any) -> JSONResponse:
        return JSONResponse(data, headers=HEADERS)

    pages = APIRouter()

    @pages.get("/{token_}/")
    async def page(token_: str) -> HTMLResponse:
        check(token_)
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        html = html.replace("__API_BASE__", f"/qa/api/{token_}")
        return HTMLResponse(html, headers={**HEADERS, "Content-Security-Policy": PAGE_CSP})

    api = APIRouter()

    @api.get("/config")
    async def config(token_: str) -> JSONResponse:
        check(token_)
        calls, spend = store.today()
        return json_(
            {
                "number": guard.masked_target,
                "approval_phrase": APPROVAL_PHRASE,
                "max_seconds": guard.clamp_seconds(),
                "max_calls_per_day": qa.max_calls_per_day,
                "max_spend_inr": qa.max_spend_inr,
                "calls_today": calls,
                "spend_today_inr": spend,
                "countdown_s": qa.countdown_s,
                "token_seconds_left": gate.seconds_left(),
                "paused": guard._paused(),  # noqa: SLF001
            }
        )

    @api.get("/scenarios")
    async def scenarios(token_: str) -> JSONResponse:
        check(token_)
        return json_({"scenarios": runner.list_scenarios()})

    @api.post("/plan")
    async def plan(token_: str, body: PlanIn) -> JSONResponse:
        check(token_)
        sc.get(body.scenario)
        return json_(await runner.plan(body.scenario, body.params))

    @api.post("/run")
    async def run(token_: str, body: RunIn) -> JSONResponse:
        check(token_)
        sc.get(body.scenario)
        r = await runner.start(body.scenario, body.approval, body.params)
        return json_(r.to_json(runner.clock()))

    @api.get("/run/{run_id}")
    async def run_state(token_: str, run_id: str) -> JSONResponse:
        check(token_)
        return json_(runner.get(run_id).to_json(runner.clock()))

    @api.get("/current")
    async def current(token_: str) -> JSONResponse:
        check(token_)
        r = runner.current()
        return json_({"run": r.to_json(runner.clock()) if r else None})

    @api.post("/cancel")
    async def cancel(token_: str, body: RunRef) -> JSONResponse:
        check(token_)
        return json_(runner.cancel(body.run_id).to_json(runner.clock()))

    @api.post("/note")
    async def note(token_: str, body: NoteIn) -> JSONResponse:
        check(token_)
        sc.get(body.scenario)
        try:
            row = store.add_note(body.scenario, body.verdict, body.note)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return json_({"saved": True, "verdict": row["verdict"]})

    @api.post("/line")
    async def line(token_: str, body: LineIn) -> JSONResponse:
        check(token_)
        try:
            store.add_line_decision(body.line_id, body.decision, body.note)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return json_({"saved": True})

    @api.get("/report")
    async def report(token_: str) -> JSONResponse:
        check(token_)
        return json_({**qa_report.build(store), "text": qa_report.render(store)})

    @api.get("/report.txt")
    async def report_txt(token_: str) -> PlainTextResponse:
        check(token_)
        return PlainTextResponse(qa_report.render(store), headers=HEADERS)

    app.include_router(pages, prefix="/qa")
    app.include_router(api, prefix="/qa/api/{token_}")
    return app
