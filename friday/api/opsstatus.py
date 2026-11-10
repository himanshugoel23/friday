"""Read-only update status for the small server: ``GET /ops-status/{token}`` (docs/AUTOUPDATE.md).

The auto-updater (deploy/autoupdate.sh) writes a plain-text report; this serves it so the developer
can read it without a console. Off unless FRIDAY_OPS_STATUS_TOKEN is set (16+ chars). The report
holds no secrets: git commit ids and migration/doctor lines only.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

_DEFAULT_FILE = "/opt/friday/var/autoupdate/status.txt"
_MAX_BYTES = 60_000


def _token() -> str:
    # The server's .env is read by pydantic only, not exported to the process: look in both places.
    env = os.environ.get("FRIDAY_OPS_STATUS_TOKEN")
    return env or str(dotenv_values(".env").get("FRIDAY_OPS_STATUS_TOKEN") or "")


def _read(path: Path) -> PlainTextResponse:
    try:
        data = path.read_bytes()[-_MAX_BYTES:]
    except OSError:
        return PlainTextResponse("no report yet\n")
    return PlainTextResponse(data.decode("utf-8", "replace"))


def _authorised(token: str) -> None:
    expected = _token()
    if len(expected) < 16 or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=404, detail="Not Found")


_REVIEW_COLS = (
    "label",
    "week",
    "shadow_active",
    "signals_seen",
    "would_alert_child",
    "would_nudge",
    "ceilings_hit",
    "fine_taps",
    "checkin_done",
    "checkin_unanswered",
    "checkin_answered_pct",
    "sos_device",
    "sos_incidents",
    "falls",
    "authority_dry_runs",
)
_REVIEW_DAYS = 14
CHECKLIST = (
    "Daily review (about 5 minutes, counts only):",
    "1. Open this page. Any family with would alert child much higher than this was fine? Note it.",
    "2. Any ceilings hit above 0? The nudge ceiling works; is the limit too tight?",
    "3. Check-in answered rate low for a family? Ask the child by chat whether the time suits.",
    "4. Any SOS or fall count? Read the incident in the child's chat, not here.",
    "5. Authority dry-run entries: is the script template calm and complete? Nothing was dialled.",
    "6. Write one line in HANDOFF: tune a rule, or leave it. No rule change without a test.",
)


async def _review_doc(request: Request) -> dict:
    """Founder review data (T17): integers and labels F1, F2... only. No id, name or text."""
    from datetime import timedelta

    c = request.app.state.container
    try:
        hub = c.get("robin") if c.settings.robin_enabled else None
    except Exception:  # noqa: BLE001 - a broken Robin build reads as off
        hub = None
    svc = getattr(hub, "device_service", None)
    if hub is None or svc is None:
        return {"status": "off", "families": [], "authority": {}}
    store = hub.ctx.store
    since = hub.ctx.clock.now() - timedelta(days=_REVIEW_DAYS)
    rows: list[dict] = []
    authority: dict[str, int] = {}
    for i, pid in enumerate(
        sorted(svc.store.parent_ids()), start=1
    ):  # label = position in the sorted list, not reversible to an id
        cnt = svc.review_counts(pid)
        if cnt is None:
            continue
        row = {
            "label": f"F{i}",
            **cnt,
            "checkin_done": 0,
            "checkin_unanswered": 0,
            "checkin_answered_pct": -1,
            "sos_device": cnt.pop("sos"),
            "sos_incidents": 0,
            "falls": 0,
            "authority_dry_runs": 0,
        }
        member = await store.get_member(pid)
        if member is not None:
            fid = member.family_id
            for r in await store.list(fid, "checkin", since=since):
                if r.status in ("done", "unanswered"):
                    row[f"checkin_{r.status}"] += 1
            for r in await store.list(fid, "incident", since=since):
                sc = str((r.data or {}).get("scenario") or "").lower()
                row["sos_incidents"] += 1 if sc == "sos" else 0
                row["falls"] += 1 if sc == "fall" else 0
            for r in await store.list(fid, "audit", since=since):
                d = r.data or {}
                if d.get("event") == "authority" and d.get("dry_run"):
                    k = "112" if d.get("kind") == "112" else "1930"
                    authority[k] = authority.get(k, 0) + 1
                    row["authority_dry_runs"] += 1
        total = row["checkin_done"] + row["checkin_unanswered"]
        row["checkin_answered_pct"] = (100 * row["checkin_done"]) // total if total else -1
        rows.append(row)
    return {"status": "ok", "families": rows, "authority": authority, "hub": hub}


def _script_templates(hub: object, authority: dict[str, int]) -> list[str]:
    """The dry-run script as a template: every personal slot is a placeholder."""
    say = hub.ctx.say  # type: ignore[attr-defined]
    out = []
    if authority.get("112"):
        out.append(
            f"112 x{authority['112']}: "
            + say(
                "authority.script_112",
                "hinglish",
                name="<name>",
                address="<address>",
                what="<what>",
                callback="<callback>",
            )
        )
    if authority.get("1930"):
        out.append(
            f"1930 x{authority['1930']}: "
            + say("authority.bridge_1930", "hinglish", child="<child>", parent="<parent>")
        )
    return out


def _review_text(doc: dict) -> str:
    if doc["status"] != "ok":
        return "status=off\n"
    lines = ["Robin shadow-week review (counts only, last 14 days, nothing here is live)", ""]
    for r in doc["families"]:
        pct = "n/a" if r["checkin_answered_pct"] < 0 else f"{r['checkin_answered_pct']}%"
        lines.append(
            f"{r['label']}: week {r['week']} ({'shadow' if r['shadow_active'] else 'live'}), "
            f"signals seen {r['signals_seen']}, would alert child {r['would_alert_child']}, "
            f"would nudge {r['would_nudge']}, ceilings hit {r['ceilings_hit']}, "
            f"this was fine {r['fine_taps']}, check-in answered {pct} "
            f"({r['checkin_done']}/{r['checkin_done'] + r['checkin_unanswered']}), "
            f"SOS taps {r['sos_device']}, SOS incidents {r['sos_incidents']}, falls {r['falls']}, "
            f"authority dry-runs {r['authority_dry_runs']}"
        )
    if not doc["families"]:
        lines.append("no families with a paired device yet")
    lines += ["", "Authority dry-run script (template, personal parts replaced by placeholders):"]
    lines += _script_templates(doc["hub"], doc["authority"]) or ["none logged"]
    lines += ["", *CHECKLIST]
    return "\n".join(lines) + "\n"


def ops_status_router() -> APIRouter:
    router = APIRouter()

    @router.get("/{token}", response_class=PlainTextResponse)
    def status(token: str) -> PlainTextResponse:
        _authorised(token)
        return _read(Path(os.environ.get("FRIDAY_OPS_STATUS_FILE", _DEFAULT_FILE)))

    @router.get("/{token}/logs", response_class=PlainTextResponse)
    def logs(token: str) -> PlainTextResponse:
        _authorised(token)
        default = str(Path(_DEFAULT_FILE).with_name("logs.txt"))
        return _read(Path(os.environ.get("FRIDAY_OPS_LOGS_FILE", default)))

    @router.get("/{token}/calls", response_class=PlainTextResponse)
    async def calls(token: str, request: Request, n: int = 5) -> PlainTextResponse:
        _authorised(token)
        from friday.ops import callreview

        if not callreview.enabled():  # off by default: same 404 as a wrong token
            raise HTTPException(status_code=404, detail="Not Found")
        c = request.app.state.container
        return PlainTextResponse(await callreview.render_review(c.db, c.settings, n))

    @router.get("/{token}/bench", response_class=PlainTextResponse)
    def bench(token: str) -> PlainTextResponse:
        _authorised(token)
        from friday.bench import ops as bench_ops

        if not bench_ops.enabled():  # off by default: same 404 as a wrong token
            raise HTTPException(status_code=404, detail="Not Found")
        return _read(Path(bench_ops.report_path()))

    def _waitlist(request: Request) -> object:
        st = request.app.state.container.settings
        if not st.robin_waitlist_enabled:
            raise HTTPException(status_code=404, detail="Not Found")
        from friday.robinwaitlist.wiring import store_for

        return store_for(st)

    @router.get("/{token}/waitlist", response_class=PlainTextResponse)
    def waitlist(token: str, request: Request) -> PlainTextResponse:
        _authorised(token)
        return PlainTextResponse(_waitlist(request).summary())  # type: ignore[attr-defined]

    @router.get("/{token}/waitlist.csv", response_class=PlainTextResponse)
    def waitlist_csv(token: str, request: Request) -> PlainTextResponse:
        _authorised(token)
        headers = {
            "Content-Disposition": 'attachment; filename="robin_waitlist.csv"',
            "Cache-Control": "no-store",
        }
        return PlainTextResponse(_waitlist(request).csv(), media_type="text/csv", headers=headers)  # type: ignore[attr-defined]

    async def _robin_doc(request: Request) -> dict:
        """Robin counts: integers and a status word only (T05). Off -> status off."""
        from friday.robin.opscounts import robin_counts

        c = request.app.state.container
        try:
            hub = c.get("robin") if c.settings.robin_enabled else None
        except Exception:  # noqa: BLE001 - a broken Robin build is reported as off, never as a stack trace
            hub = None
        return await robin_counts(hub, getattr(hub, "device_service", None))

    @router.get("/{token}/robin.json")
    async def robin_json(token: str, request: Request) -> JSONResponse:
        _authorised(token)
        return JSONResponse(await _robin_doc(request), headers={"Cache-Control": "no-store"})

    @router.get("/{token}/robin", response_class=PlainTextResponse)
    async def robin_text(token: str, request: Request) -> PlainTextResponse:
        _authorised(token)
        lines: list[str] = []

        def walk(prefix: str, node: object) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(f"{prefix}.{k}" if prefix else str(k), v)
            else:
                lines.append(f"{prefix}={node}")

        walk("", await _robin_doc(request))
        return PlainTextResponse("\n".join(lines) + "\n", headers={"Cache-Control": "no-store"})

    @router.get("/{token}/review", response_class=PlainTextResponse)
    async def review_text(token: str, request: Request) -> PlainTextResponse:
        _authorised(token)
        return PlainTextResponse(
            _review_text(await _review_doc(request)), headers={"Cache-Control": "no-store"}
        )

    @router.get("/{token}/review.csv", response_class=PlainTextResponse)
    async def review_csv(token: str, request: Request) -> PlainTextResponse:
        _authorised(token)
        doc = await _review_doc(request)
        rows = [",".join(_REVIEW_COLS)] + [
            ",".join(str(r[k]) for k in _REVIEW_COLS) for r in doc["families"]
        ]
        headers = {
            "Content-Disposition": 'attachment; filename="robin_review.csv"',
            "Cache-Control": "no-store",
        }
        return PlainTextResponse("\n".join(rows) + "\n", media_type="text/csv", headers=headers)

    def _probe_store(request: Request) -> object | None:
        """The site MCP probe store, or None while the probe switch is off (routes 404)."""
        st = request.app.state.container.settings
        if not st.site_mcp_probe_enabled:
            return None
        from friday.sitemcp.wiring import store_for

        return store_for(st)

    @router.get("/{token}/probe", response_class=PlainTextResponse)
    def probe(token: str, request: Request) -> PlainTextResponse:
        _authorised(token)
        store = _probe_store(request)
        if store is None:
            raise HTTPException(status_code=404, detail="Not Found")
        from friday.sitemcp.live import render_report

        return PlainTextResponse(render_report(store))  # type: ignore[arg-type]

    @router.get("/{token}/shot/{site}")
    def shot(token: str, site: str, request: Request) -> Response:
        """Last screenshot of a PUBLIC page (anonymous probe only, never logged in)."""
        _authorised(token)
        store = _probe_store(request)
        png = store.shot(site) if store is not None else None  # type: ignore[attr-defined]
        if png is None:
            raise HTTPException(status_code=404, detail="Not Found")
        headers = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}
        return Response(png, media_type="image/png", headers=headers)

    return router
