"""Framework-neutral HTTP handlers for the live view (mount under any server).

    GET  /live/<token>            consume the link, serve the page (404 if used / expired)
    GET  /live/f/<view>           masked PNG frame
    GET  /live/s/<view>           JSON state
    POST /live/takeover/<view>    pause Friday, user drives
    POST /live/giveback/<view>    Friday resumes
    POST /live/i/<view>           one input event (JSON)
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field

from friday.connectors.browser.port import BrowserError
from friday.connectors.session.liveview import LiveViewService

_SEC = {
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
}


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "text/plain"
    headers: dict[str, str] = field(default_factory=dict)


def _resp(status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> Response:
    return Response(status, body, ctype, {**_SEC, **(extra or {})})


_NOT_FOUND = _resp(404, b"not found", "text/plain")

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Friday live view</title>
<style>body{font-family:system-ui;margin:0;padding:16px;background:#111;color:#eee}
img{max-width:100%;border:1px solid #444;touch-action:none}button{padding:10px 16px;margin:4px 8px 8px 0}
#t{width:70%;padding:8px}</style></head><body>
<p id="s">Watching. Friday is working.</p>
<button id="take">Take over</button><button id="give" hidden>Give back to Friday</button>
<div id="kb" hidden><input id="t" autocomplete="off" placeholder="type here, then Send">
<button id="send">Send</button><button data-k="Enter">Enter</button>
<button data-k="Tab">Tab</button><button data-k="Backspace">Back</button></div>
<img id="f" alt="live page"><p>Password and code boxes are hidden in this picture on purpose.</p>
<script nonce="__N__">
const V="__V__";let mode="agent";const im=document.getElementById("f");
async function post(p,b){return fetch("/live/"+p+"/"+V,{method:"POST",
headers:{"Content-Type":"application/json"},body:JSON.stringify(b||{})});}
async function tick(){try{const r=await fetch("/live/f/"+V);if(r.status!==200){
document.getElementById("s").textContent="This view has ended.";return;}
im.src=URL.createObjectURL(await r.blob());
const s=await (await fetch("/live/s/"+V)).json();mode=s.mode;
document.getElementById("take").hidden=mode==="takeover"||!s.can_takeover;
document.getElementById("give").hidden=mode!=="takeover";
document.getElementById("kb").hidden=mode!=="takeover";
document.getElementById("s").textContent=mode==="takeover"?"You are in control. Friday is paused.":"Watching. Friday is working.";
}catch(e){}setTimeout(tick,1000);}
document.getElementById("take").onclick=()=>post("takeover");
document.getElementById("give").onclick=()=>post("giveback");
im.onclick=e=>{if(mode!=="takeover")return;const r=im.getBoundingClientRect();
post("i",{kind:"click",x:Math.floor((e.clientX-r.left)*im.naturalWidth/r.width),
y:Math.floor((e.clientY-r.top)*im.naturalHeight/r.height)});};
document.getElementById("send").onclick=()=>{const t=document.getElementById("t");
if(t.value){post("i",{kind:"type",text:t.value});t.value="";}};
document.querySelectorAll("[data-k]").forEach(b=>b.onclick=()=>post("i",{kind:"key",key:b.dataset.k}));
tick();</script></body></html>"""


class LiveViewHttp:
    def __init__(self, service: LiveViewService) -> None:
        self.svc = service

    async def handle(self, method: str, path: str, body: bytes = b"") -> Response:
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2 or parts[0] != "live":
            return _NOT_FOUND
        try:
            if method == "GET" and len(parts) == 2:
                vh = self.svc.open_view(parts[1])
                if vh is None:
                    return _NOT_FOUND
                nonce = secrets.token_urlsafe(12)
                html = _PAGE.replace("__V__", vh.view_id).replace("__N__", nonce)
                csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; "
                       "img-src blob:; connect-src 'self'; base-uri 'none'; form-action 'none'")
                return _resp(200, html.encode(), "text/html; charset=utf-8",
                             {"Content-Security-Policy": csp})
            if len(parts) != 3:
                return _NOT_FOUND
            kind, view = parts[1], parts[2]
            if method == "GET" and kind == "f":
                png = await self.svc.frame(view)
                return _NOT_FOUND if png is None else _resp(200, png, "image/png")
            if method == "GET" and kind == "s":
                st = self.svc.state(view)
                return _NOT_FOUND if st is None else _resp(
                    200, json.dumps(st).encode(), "application/json")
            if method == "POST" and kind in {"takeover", "giveback", "i"}:
                if kind == "takeover":
                    ok = await self.svc.start_takeover(view)
                elif kind == "giveback":
                    ok = await self.svc.give_back(view)
                else:
                    try:
                        event = json.loads(body or b"{}")
                    except ValueError:
                        return _resp(400, b"bad json", "text/plain")
                    if not isinstance(event, dict):
                        return _resp(400, b"bad event", "text/plain")
                    ok = await self.svc.send_input(view, event)
                return _resp(200 if ok else 404, b"{}" if ok else b"not found",
                             "application/json" if ok else "text/plain")
        except BrowserError as e:
            return _resp(400, str(e).encode()[:100], "text/plain")
        return _NOT_FOUND
