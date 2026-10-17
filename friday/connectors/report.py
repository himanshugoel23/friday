"""HTML for the watch page and the static report (screenshots embedded as data: URIs)."""

from __future__ import annotations

import base64
import json
from html import escape

from friday.connectors.recorder import StepRecorder

_CSS = (
    "body{font:15px system-ui;margin:16px;max-width:900px}img{max-width:100%;border:1px solid #ccc}"
    ".step{margin:14px 0;padding-bottom:10px;border-bottom:1px solid #eee}small{color:#666}"
    "pre{background:#f5f5f5;padding:8px;overflow:auto}"
)


def _img(png: bytes) -> str:
    if not png:
        return ""
    return f'<img alt="screenshot" src="data:image/png;base64,{base64.b64encode(png).decode()}">'


def render_report(rec: StepRecorder, title: str = "Browser run") -> str:
    """Self-contained page (no external requests). Used for the static report."""
    steps = "".join(
        f'<div class="step"><b>#{s.n}</b> {escape(s.tool or "-")} / {escape(s.action)} '
        f"<small>{escape(s.url)}</small><br>{escape(s.note)}<br>{_img(s.screenshot)}</div>"
        for s in rec.steps
    )
    result = json.dumps(rec.result, indent=2, default=str) if rec.result is not None else "running"
    return (
        f"<!doctype html><meta charset=utf-8><title>{escape(title)}</title><style>{_CSS}</style>"
        f"<h1>{escape(title)}</h1><h2>Result</h2><pre>{escape(result)}</pre>"
        f"<h2>Steps</h2>{steps}"
    )


def render_watch(token: str, rec: StepRecorder) -> str:
    """Live page: polls state.json every 2 s and reloads images; steps link to /step/{n}.png."""
    rows = "".join(
        f'<div class="step"><b>#{s.n}</b> {escape(s.tool or "-")} / {escape(s.action)} '
        f"<small>{escape(s.url)}</small><br>{escape(s.note)}"
        + (f'<br><img loading="lazy" src="step/{s.n}.png">' if s.screenshot else "")
        + "</div>"
        for s in rec.steps
    )
    result = (json.dumps(rec.result, indent=2, default=str) if rec.result is not None
              else "running...")
    refresh = "" if rec.done else '<meta http-equiv="refresh" content="2">'
    return (
        f"<!doctype html><meta charset=utf-8>{refresh}<title>Friday browser run</title>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<meta name=referrer content=no-referrer><style>{_CSS}</style>"
        "<h1>Friday browser run</h1>"
        f"<p><small>{'finished' if rec.done else 'live (refreshes every 2 seconds)'}</small></p>"
        '<h2>Now</h2><img alt="latest" src="latest.png">'
        f"<h2>Result</h2><pre>{escape(result)}</pre><h2>Steps</h2>{rows}"
        '<p><a href="trace.zip">Playwright trace</a></p>'
    )
