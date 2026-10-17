from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.connectors_otp import otp_router
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.otp_tokens import OtpTokenRegistry

CODE = "482913"  # invented test code


def _setup(clock=None):
    tokens = OtpTokenRegistry(clock=clock) if clock else OtpTokenRegistry()
    channel = OneTimeOtpChannel()
    app = FastAPI()
    app.include_router(otp_router(tokens, channel), prefix="/connectors")
    return TestClient(app), tokens, channel


def test_get_shows_form_with_only_last_two_digits_and_no_side_effects():
    c, tokens, channel = _setup()
    t = tokens.create("task", "9000000042")
    r = c.get(f"/connectors/otp/{t}")
    assert r.status_code == 200
    assert "ending <b>..42</b>" in r.text and "9000000042" not in r.text
    assert "one-time-code" in r.text and "maxlength='8'" in r.text
    assert "never stores or logs it" in r.text and "payment codes" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert "noindex" in r.headers["x-robots-tag"]
    assert not channel.has_pending("task")  # GET did nothing
    assert c.get(f"/connectors/otp/{t}").status_code == 200  # still usable


def test_post_feeds_channel_once_and_never_echoes_code():
    c, tokens, channel = _setup()
    t = tokens.create("task", "9000000042")
    r = c.post(f"/connectors/otp/{t}", data={"code": CODE})
    assert r.status_code == 200 and "Done" in r.text
    assert CODE not in r.text and CODE not in str(r.headers) and CODE not in str(r.url)
    assert r.headers["cache-control"] == "no-store"
    assert channel.take("task") == CODE and channel.take("task") is None
    # single use: the token is gone
    assert c.post(f"/connectors/otp/{t}", data={"code": CODE}).status_code == 404
    assert c.get(f"/connectors/otp/{t}").status_code == 404


def test_bad_code_is_not_echoed_and_rate_limited_to_five():
    c, tokens, channel = _setup()
    t = tokens.create("task", "9000000042")
    for _ in range(4):
        r = c.post(f"/connectors/otp/{t}", data={"code": "12ab9"})
        assert r.status_code == 400 and "12ab9" not in r.text
    r = c.post(f"/connectors/otp/{t}", data={"code": "12ab9"})
    assert r.status_code == 429  # fifth try burns the link
    assert c.post(f"/connectors/otp/{t}", data={"code": CODE}).status_code == 404
    assert not channel.has_pending("task")


def test_valid_code_on_fifth_try_still_works():
    c, tokens, channel = _setup()
    t = tokens.create("task", "9000000042")
    for _ in range(4):
        c.post(f"/connectors/otp/{t}", data={"code": "x"})
    assert c.post(f"/connectors/otp/{t}", data={"code": CODE}).status_code == 200
    assert channel.take("task") == CODE


def test_unknown_expired_tokens_404_and_ttl_is_ten_minutes():
    now = [1000.0]
    c, tokens, _ = _setup(clock=lambda: now[0])
    assert c.get("/connectors/otp/nope").status_code == 404
    assert c.post("/connectors/otp/nope", data={"code": CODE}).status_code == 404
    t = tokens.create("task", "9000000042")
    now[0] += 599
    assert c.get(f"/connectors/otp/{t}").status_code == 200
    now[0] += 2
    assert c.get(f"/connectors/otp/{t}").status_code == 404
    assert c.post(f"/connectors/otp/{t}", data={"code": CODE}).status_code == 404


def test_cross_site_origin_refused_and_oversize_body_refused():
    c, tokens, channel = _setup()
    t = tokens.create("task", "9000000042")
    r = c.post(f"/connectors/otp/{t}", data={"code": CODE}, headers={"Origin": "https://evil.test"})
    assert r.status_code == 403 and not channel.has_pending("task")
    r = c.post(f"/connectors/otp/{t}", content=b"code=" + b"1" * 5000,
               headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413


def test_code_in_query_string_is_ignored_and_tokens_are_not_shared_between_apps():
    c, tokens, _ = _setup()
    t = tokens.create("task", "9000000042")
    assert c.get(f"/connectors/otp/{t}?code={CODE}").status_code == 200
    c2, _, ch2 = _setup()
    assert c2.post(f"/connectors/otp/{t}", data={"code": CODE}).status_code == 404
    assert not ch2.has_pending("task")
