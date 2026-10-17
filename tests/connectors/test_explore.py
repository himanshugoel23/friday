"""Explore run: page-state rules, masking, secrets hygiene, blocked pages, end to end on the FAKE
site with real Chromium (skipped without it), the CLI and pack-run."""

from __future__ import annotations

import asyncio
import json
import re
import struct
import zipfile
import zlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.connectors_otp import otp_router
from friday.cli import main
from friday.connectors import explore_cli
from friday.connectors.browser.playwright_session import browser_available
from friday.connectors.explore import (
    ExploreConfig,
    Sanitiser,
    local_digits,
    mask_phone,
    run_explore,
)
from friday.connectors.fake_site import FakeSiteServer, FakeSiteState
from friday.connectors.food.zomato_live import (
    FORBIDDEN_CLICK,
    classify_page,
    parse_menu_rows,
    phone_regex,
)
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.otp_tokens import OtpTokenRegistry
from friday.connectors.pack import pack_run

needs_browser = pytest.mark.skipif(
    not browser_available(), reason="playwright extra or Chromium not available")

PHONE = "+919123456780"  # invented
PHONE_LOCAL = "9123456780"
CODE = "593817"  # invented fake-site code
GOOD_TEXT = "Order food from restaurants near you. Search for dishes, cuisines and more here."


# ------------------------------------------------------------------ pure rules
@pytest.mark.parametrize("status,title,text,markers,code", [
    (403, "Access Denied", "You don't have permission", [], "access_denied"),
    (429, "", GOOD_TEXT, [], "access_denied"),
    (500, "Oops", "Something broke on our side, please try later", [], "http_error"),
    (200, "Just a moment...", "Checking your browser before accessing", [], "bot_challenge"),
    (200, "Home", "Please verify you are human to continue to the site", [], "bot_challenge"),
    (200, "Home", GOOD_TEXT, ["iframe[src*=recaptcha i]"], "bot_challenge"),
    (200, "Home", "Access Denied. Reference #18.2a", [], "access_denied"),
    (200, "Home", "   ", [], "empty_page"),
    (200, "Home", "ok", [], "empty_page"),
])
def test_classify_blocked_pages(status, title, text, markers, code):
    verdict = classify_page(status=status, title=title, text=text, markers=markers)
    assert verdict is not None and verdict[0] == code and len(verdict[1]) > 20


def test_classify_normal_page_and_recaptcha_notice_is_not_blocked():
    assert classify_page(status=200, title="Zomato", text=GOOD_TEXT) is None
    assert classify_page(status=None, title="x", text=GOOD_TEXT + " Protected by reCAPTCHA") is None


def test_parse_menu_rows_defensive():
    rows = parse_menu_rows([
        "Margherita\n₹199.00\nAdd", "Pepperoni₹349\nNon-veg\nADD", "Veg Burger\nVeg\nRs. 99",
        "Coming soon\nAdd", "₹50", ""])
    assert [r["name"] for r in rows] == ["Margherita", "Pepperoni", "Veg Burger"]
    assert [r["price_text"] for r in rows] == ["199.00", "349", "99"]
    assert [r["veg"] for r in rows] == [False, False, True]


def test_forbidden_click_words():
    for bad in ("Place Order", "Pay now", "Pay ₹259", "Confirm order", "Cash on delivery", "COD"):
        assert FORBIDDEN_CLICK.search(bad), bad
    for ok in ("Proceed to pay", "Add", "Log in", "View cart", "Send code"):
        assert not FORBIDDEN_CLICK.search(ok), ok


def test_phone_helpers_and_sanitiser():
    assert local_digits("+919123456780") == local_digits("09123456780") == PHONE_LOCAL
    assert local_digits("+14155550123") == "" and local_digits("12345") == ""
    assert mask_phone(PHONE) == "..80" and PHONE_LOCAL not in mask_phone(PHONE)
    san = Sanitiser(PHONE_LOCAL)
    san.add_secret(CODE)
    out = san.text("Code sent to +91 91234-56780 / (91234) 56780 / 9123456780. You typed 593817.")
    assert "56780" not in out and CODE not in out
    assert phone_regex(PHONE_LOCAL).search("+91 9 1 2 3 4 5 6 7 8 0")
    san.clear_secrets()
    assert san.obj({"a": ["9123456780"]}) == {"a": ["[REDACTED_PHONE]"]}


# ------------------------------------------------------------------ png helper (mask check)
def _pixels(png: bytes) -> tuple[int, int, int, bytes]:
    pos, idat, w = 8, b"", (0, 0, 0)
    while pos < len(png):
        (n,) = struct.unpack(">I", png[pos:pos + 4])
        kind, data = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w = struct.unpack(">IIBBBBB", data)
            assert w[2] == 8 and w[6] == 0, "only 8-bit non-interlaced PNG supported"
        elif kind == b"IDAT":
            idat += data
        pos += 12 + n
    width, height, ctype = w[0], w[1], w[3]
    bpp = {2: 3, 6: 4}[ctype]
    raw, stride, rows, prev = zlib.decompress(idat), width * bpp, [], bytearray(width * bpp)
    for y in range(height):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return width, height, bpp, b"".join(rows)


def _magenta_pixels(png: bytes) -> int:
    _, _, bpp, data = _pixels(png)
    return sum(1 for i in range(0, len(data), bpp) if data[i:i + 3] == b"\xff\x00\xff")


# ------------------------------------------------------------------ end to end on the fake site
def _make(out: Path, state: FakeSiteState, **kw):
    srv = FakeSiteServer(state)
    base = srv.start()
    otp, tokens = OneTimeOtpChannel(), OtpTokenRegistry()
    app = FastAPI()
    app.include_router(otp_router(tokens, otp), prefix="/connectors")
    client = TestClient(app)
    submitted = []
    code = kw.pop("send_code", CODE)

    def waiting() -> None:  # the "founder" typing the code on the secure page
        token = tokens.create("t", PHONE_LOCAL[-2:])

        def post() -> None:
            r = client.post(f"/connectors/otp/{token}", data={"code": code})
            submitted.append(r.status_code)

        asyncio.get_running_loop().run_in_executor(None, post)

    cfg = ExploreConfig(
        out=out, base_url=base, headed=False, phone=PHONE, otp=otp, task_id="t", pace=(0, 0),
        allowed_hosts={"127.0.0.1"}, on_waiting_for_otp=waiting, say=lambda s: None,
        timeout_scale=0.3,
        otp_timeout_s=kw.pop("otp_timeout_s", 20), login_confirm_s=kw.pop("login_confirm_s", 3),
        **kw)
    return srv, cfg, submitted


def _all_files(out: Path):
    return [p for p in out.rglob("*") if p.is_file()]


def _needles_in(out: Path, needles: list[bytes]) -> list[str]:
    hits = []
    for p in _all_files(out):
        blobs = [p.read_bytes()]
        if p.suffix == ".zip":
            zf = zipfile.ZipFile(p)
            blobs = [zf.read(n) for n in zf.namelist()]
        for blob in blobs:
            hits += [f"{p.name}:{n!r}" for n in needles if n in blob]
    return hits


@needs_browser
async def test_full_explore_on_fake_site_leaves_no_secret_and_masks_inputs(tmp_path):
    state = FakeSiteState(otp=CODE)
    srv, cfg, submitted = _make(tmp_path / "run", state)
    try:
        st = await run_explore(cfg)
    finally:
        srv.stop()
    assert st["status"] == "done" and st["logged_in"] and st["blocked_reason"] is None
    assert submitted == [200]
    names = [s["step"] for s in st["steps"]]
    assert names[:5] == ["open_home", "location", "search", "restaurant", "menu"]
    assert names[5:] == ["login_open", "phone_entered", "code_requested", "waiting_for_code",
                         "logged_in"]
    assert st["menu_items"] == 4 and (cfg.out / "menu.json").exists()
    assert st["phone_hint"] == "..80"
    # which candidates matched is logged (names only)
    assert any(s["matched"].get("search_input") for s in st["steps"])
    # nothing added, nothing ordered
    assert all(not s.cart for s in state.sessions.values()) and not state.orders
    # no secret anywhere on disk or inside a trace
    assert _needles_in(cfg.out, [CODE.encode(), PHONE_LOCAL.encode(), b"91234 56780"]) == []
    assert (cfg.out / "trace-1-before-login.zip").stat().st_size > 0
    assert (cfg.out / "trace-2-after-login.zip").stat().st_size > 0
    # sanitised text + title per step
    step_dirs = sorted((cfg.out / "steps").iterdir())
    assert all((d / "text.txt").exists() and (d / "meta.json").exists() for d in step_dirs)
    assert "[REDACTED_PHONE]" in (cfg.out / "steps" / "08-code_requested" / "text.txt").read_text()
    # screenshots: inputs/phone are painted over in the login phase, not before
    shot = {d.name.split("-", 1)[1]: (d / "screenshot.png").read_bytes() for d in step_dirs}
    for login_step in ("login_open", "phone_entered", "code_requested", "waiting_for_code",
                       "logged_in"):
        assert _magenta_pixels(shot[login_step]) > 0 or login_step in {"logged_in"}, login_step
    assert _magenta_pixels(shot["phone_entered"]) > 500
    assert _magenta_pixels(shot["code_requested"]) > 500  # otp box + the "Code sent to" line
    assert _magenta_pixels(shot["open_home"]) == 0



@needs_browser
async def test_probe_stops_after_the_menu_without_login_or_phone(tmp_path):
    state = FakeSiteState(otp=CODE)
    srv, cfg, submitted = _make(tmp_path / "run", state, probe=True)
    cfg.phone = ""  # probe needs no number
    try:
        st = await run_explore(cfg)
    finally:
        srv.stop()
    assert st["status"] == "done" and not st["logged_in"] and st["blocked_reason"] is None
    assert [s["step"] for s in st["steps"]] == ["open_home", "location", "search", "restaurant",
                                               "menu"]
    assert submitted == [] and not state.orders


@needs_browser
async def test_login_page_mode_logs_in_from_slash_login_only(tmp_path):
    state = FakeSiteState(otp=CODE)
    srv, cfg, submitted = _make(tmp_path / "run", state, login_page=True)
    try:
        st = await run_explore(cfg)
    finally:
        srv.stop()
    assert st["status"] == "done" and st["logged_in"] and st["blocked_reason"] is None
    names = [s["step"] for s in st["steps"]]
    assert names[:2] == ["open_login_page", "login_open"]
    assert "search" not in names and submitted == [200] and not state.orders
    assert _needles_in(cfg.out, [CODE.encode(), PHONE_LOCAL.encode()]) == []

@needs_browser
async def test_add_item_stops_at_payment_handoff_without_paying(tmp_path):
    state = FakeSiteState(otp=CODE)
    srv, cfg, _ = _make(tmp_path / "run", state, add_item="margherita")
    try:
        st = await run_explore(cfg)
    finally:
        srv.stop()
    assert st["status"] == "done", st["blocked_reason"]
    assert [s["step"] for s in st["steps"]][-3:] == ["item_added", "cart_summary",
                                                     "payment_handoff"]
    assert st["handoff"] == {"qr_image_seen": True, "upi_link_seen": True}
    (order,) = state.orders.values()
    assert order["state"] == "Awaiting payment"  # reached the pay screen, nothing paid
    assert _needles_in(cfg.out, [CODE.encode(), PHONE_LOCAL.encode()]) == []


@needs_browser
@pytest.mark.parametrize("block,path,code", [
    ("captcha", "/", "bot_challenge"),
    ("captcha", "/search", "bot_challenge"),
    ("empty", "/", "empty_page"),
    ("empty", "/restaurant", "empty_page"),
    ("forbidden", "/", "access_denied"),
    ("forbidden", "/search", "access_denied"),
])
async def test_blocked_pages_end_cleanly_with_reason_and_screenshot(tmp_path, block, path, code):
    state = FakeSiteState(otp=CODE, block=block, block_path=path)
    srv, cfg, submitted = _make(tmp_path / "run", state)
    try:
        st = await run_explore(cfg)
    finally:
        srv.stop()
    assert st["status"] == "blocked" and st["blocked_reason"]["code"] == code
    assert len(st["blocked_reason"]["explanation"]) > 20 and st["finished_at"]
    on_disk = json.loads((cfg.out / "state.json").read_text())
    assert on_disk["blocked_reason"]["code"] == code
    last = sorted((cfg.out / "steps").iterdir())[-1]
    assert (last / "screenshot.png").stat().st_size > 0 and (last / "text.txt").exists()
    assert len(st["steps"]) <= 4 and not submitted  # no retry loop, never reached login
    assert (cfg.out / "report.html").exists()


@needs_browser
async def test_selector_missing_is_a_clean_stop(tmp_path):
    state = FakeSiteState(otp=CODE)
    state.restaurants = [r for r in state.restaurants if "Domino" not in r["name"]]
    srv, cfg, _ = _make(tmp_path / "run", state)
    try:
        st = await run_explore(cfg)
    finally:
        srv.stop()
    assert st["status"] == "blocked" and st["blocked_reason"]["code"] == "selector_missing"
    assert "restaurant" in st["blocked_reason"]["explanation"]


@needs_browser
async def test_no_code_in_time_and_wrong_code_stop_cleanly(tmp_path):
    srv, cfg, _ = _make(tmp_path / "a", FakeSiteState(otp=CODE), otp_timeout_s=1)
    cfg.on_waiting_for_otp = None  # nobody types a code
    try:
        st = await run_explore(cfg)
    finally:
        srv.stop()
    assert st["blocked_reason"]["code"] == "otp_timeout" and not st["logged_in"]

    srv, cfg, submitted = _make(tmp_path / "b", FakeSiteState(otp=CODE), send_code="111111")
    try:
        st = await run_explore(cfg)
    finally:
        srv.stop()
    assert submitted == [200] and st["blocked_reason"]["code"] == "login_not_confirmed"
    assert _needles_in(cfg.out, [b"111111", PHONE_LOCAL.encode()]) == []


# ------------------------------------------------------------------ CLI
def test_cli_help_lists_options(capsys):
    with pytest.raises(SystemExit) as e:
        main(["connectors", "zomato-explore", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for opt in ("--headed", "--headless", "--area", "--query", "--out", "--watch-host",
                "--watch-port", "--hold", "--add-item", "--fake", "--public-url"):
        assert opt in out
    with pytest.raises(SystemExit):
        main(["connectors", "pack-run", "--help"])


def test_cli_exits_clearly_when_no_phone_configured(monkeypatch, capsys):
    monkeypatch.setattr(explore_cli, "_load_phone", lambda: "")
    assert main(["connectors", "zomato-explore", "--headless"]) == 2
    out = capsys.readouterr().out
    assert "FRIDAY_PILOT_ALLOWED_NUMBERS" in out and "Nothing was run" in out


def test_cli_never_prints_the_phone_and_prints_both_urls(monkeypatch, capsys, tmp_path):
    async def fake_run(cfg, recorder=None):
        assert cfg.phone == PHONE and cfg.add_item is None and cfg.base_url.startswith("https://")
        cfg.on_waiting_for_otp()
        return {"status": "done", "blocked_reason": None}

    monkeypatch.setattr(explore_cli, "_load_phone", lambda: PHONE)
    monkeypatch.setattr(explore_cli, "run_explore", fake_run)
    monkeypatch.setenv("FRIDAY_PUBLIC_URL", "https://friday.example.test/")
    rc = main(["connectors", "zomato-explore", "--headless", "--watch-port", "8795",
               "--out", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 0 and "ending ..80" in out
    assert PHONE_LOCAL not in out and "9123456780"[:6] not in out
    assert re.search(r"WATCH PAGE: https://friday\.example\.test/connectors/watch/\S{20,}", out)
    assert re.search(r"CODE PAGE .*: https://friday\.example\.test/connectors/otp/\S{20,}", out)


# ------------------------------------------------------------------ pack-run
def _dirty_run(root: Path) -> Path:
    run = root / "run"
    step = run / "steps" / "01-open_home"
    step.mkdir(parents=True)
    (run / "state.json").write_text(json.dumps(
        {"status": "done", "note": "otp is 123456 for +91 98765 43210", "cookie": "sid=abc"}))
    (step / "text.txt").write_text(
        "Hello. Your OTP is 123456. Call 9876543210 or +91-91234-56780. "
        "token=abcdef0123456789abcdef0123456789abcd Authorization: Bearer abc.def.ghi123")
    (step / "elements.json").write_text(json.dumps([{"name": "Phone 98765 43210"}]))
    (step / "meta.json").write_text("{}")
    (step / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    (run / "trace-1-before-login.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    (run / "trace-2-after-login.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    (run / ".env").write_text("FRIDAY_SECRET=hunter2")
    (run / "storage_state.json").write_text('{"cookies": [{"value": "SECRETCOOKIE"}]}')
    return run


def test_pack_run_scrubs_and_uses_an_allow_list(tmp_path):
    run = _dirty_run(tmp_path)
    dest, included, skipped = pack_run(run)
    assert dest.name == "run-pack.zip"
    zf = zipfile.ZipFile(dest)
    names = set(zf.namelist())
    assert {"state.json", "steps/01-open_home/text.txt", "trace-1-before-login.zip",
            "steps/01-open_home/screenshot.png"} <= names
    assert ".env" not in names and "storage_state.json" not in names
    assert "trace-2-after-login.zip" not in names
    assert {".env", "storage_state.json", "trace-2-after-login.zip"} <= set(skipped)
    blob = b"".join(zf.read(n) for n in names if n.endswith((".txt", ".json")))
    for secret in (b"123456", b"98765", b"43210", b"91234", b"hunter2", b"SECRETCOOKIE",
                   b"abcdef0123456789", b"abc.def.ghi123"):
        assert secret not in blob, secret
    assert b"REDACTED" in blob
    _, included2, _ = pack_run(run, tmp_path / "x.zip", include_post_login_trace=True)
    assert "trace-2-after-login.zip" in included2


def test_pack_run_cli(tmp_path, capsys):
    run = _dirty_run(tmp_path)
    assert main(["connectors", "pack-run", str(run), "--zip", str(tmp_path / "o.zip")]) == 0
    assert (tmp_path / "o.zip").exists() and "Do NOT paste" in capsys.readouterr().out
    assert main(["connectors", "pack-run", str(tmp_path / "missing")]) == 2
