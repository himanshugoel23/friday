from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.connectors_watch import watch_router
from friday.connectors.fake_site import SimBrowserSession
from friday.connectors.recorder import MASK_SELECTORS, RecordingSession, StepRecorder
from friday.connectors.report import render_report, render_watch
from friday.connectors.watch import WatchRegistry


def _client(reg, admin=True):
    app = FastAPI()

    async def require_admin():
        return None

    app.include_router(watch_router(reg, require_admin if admin else None), prefix="/connectors")
    return TestClient(app)


def _rec():
    rec = StepRecorder()
    rec.tool = "get_menu"
    rec.add("goto", "http://x/menu", "open token=abc123secret page", b"\x89PNG\r\n\x1a\nxx")
    rec.finish({"status": "payment_ready"})
    return rec


def test_watch_page_state_and_images():
    reg = WatchRegistry()
    token = reg.create("t", _rec())
    c = _client(reg)
    page = c.get(f"/connectors/watch/{token}")
    assert page.status_code == 200 and "step/1.png" in page.text
    assert "abc123secret" not in page.text  # notes are scrubbed
    assert page.headers["cache-control"] == "no-store"
    assert c.get(f"/connectors/watch/{token}/state.json").json()["done"] is True
    assert c.get(f"/connectors/watch/{token}/latest.png").headers["content-type"] == "image/png"
    assert c.get(f"/connectors/watch/{token}/step/1.png").status_code == 200
    assert c.get(f"/connectors/watch/{token}/step/9.png").status_code == 404
    assert c.get(f"/connectors/watch/{token}/trace.zip").status_code == 404  # none recorded


def test_unknown_expired_and_revoked_tokens_404():
    now = [1000.0]
    reg = WatchRegistry(clock=lambda: now[0])
    c = _client(reg)
    assert c.get("/connectors/watch/nope").status_code == 404
    t1 = reg.create("t", _rec(), ttl_seconds=60)
    t2 = reg.create("t2", _rec(), ttl_seconds=600)
    assert c.get(f"/connectors/watch/{t1}").status_code == 200
    now[0] += 61
    for suffix in ("", "/state.json", "/latest.png", "/trace.zip"):
        assert c.get(f"/connectors/watch/{t1}{suffix}").status_code == 404
    assert c.post(f"/connectors/admin/revoke/{t2}").json() == {"revoked": True}
    assert c.get(f"/connectors/watch/{t2}").status_code == 404
    assert len({reg.create("a", _rec()) for _ in range(20)}) == 20


def test_no_revoke_route_without_admin_dependency():
    assert _client(WatchRegistry(), admin=False).post("/connectors/admin/revoke/x").status_code \
        in (404, 405)


def test_trace_served_when_present(tmp_path):
    reg = WatchRegistry()
    token = reg.create("t", _rec())
    z = tmp_path / "trace.zip"
    z.write_bytes(b"PK\x03\x04")
    reg.get(token).trace_path = str(z)
    assert _client(reg).get(f"/connectors/watch/{token}/trace.zip").content == b"PK\x03\x04"


async def test_recording_session_masks_and_hides_values(state):
    seen = []

    class Spy(SimBrowserSession):
        async def screenshot(self, mask_selectors=()):
            seen.append(tuple(mask_selectors))
            return await super().screenshot(mask_selectors)

    rec = StepRecorder()
    s = RecordingSession(Spy(state), rec)
    await s.goto("http://x/login")
    await s.fill("[data-testid=phone-input]", "9000000001")
    assert seen and all(m == MASK_SELECTORS for m in seen)
    assert "[data-testid=otp-input]" in MASK_SELECTORS and "input[type=password]" in MASK_SELECTORS
    assert "9000000001" not in " ".join(x.note for x in rec.steps)


def test_static_report_embeds_screenshots():
    html = render_report(_rec())
    assert "data:image/png;base64," in html and "payment_ready" in html
    assert "abc123secret" not in html
    assert "refresh" not in render_watch("t", _rec())  # finished runs stop refreshing
