from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from friday.connectors.contract import (
    Cart,
    CartLine,
    Charge,
    PaymentHandoff,
    format_rupees,
    rupees_to_paise,
)
from friday.connectors.gate import ActionGate, Verdict
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.registry import BackendKind, ConnectorRegistry, Registration, Status
from friday.connectors.scrub import scrub
from tests.connectors.conftest import TASK, make_grant

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8


def _line(qty=2, unit=1000):
    return CartLine(item_id="a", name="A", qty=qty, unit_price_paise=unit,
                    line_total_paise=qty * unit)


def test_money_parse_and_format():
    assert rupees_to_paise("₹1,234.50") == 123450
    assert rupees_to_paise("-₹20.00") == 2000
    assert format_rupees(60335) == "₹603.35"
    with pytest.raises(ValueError):
        rupees_to_paise("free")


def test_cart_valid_and_totals_mismatch_rejected():
    ok = Cart(restaurant_id="r", lines=[_line()], subtotal_paise=2000,
              fees=[Charge(name="d", amount_paise=100)], taxes=[Charge(name="g", amount_paise=50)],
              discount_paise=10, grand_total_paise=2140)
    assert ok.items()[0].qty == 2
    for bad in ({"grand_total_paise": 2141}, {"subtotal_paise": 1999},
                {"discount_paise": 99999, "grand_total_paise": 0}):
        data = dict(restaurant_id="r", lines=[_line()], subtotal_paise=2000,
                    fees=[Charge(name="d", amount_paise=100)],
                    taxes=[Charge(name="g", amount_paise=50)], discount_paise=10,
                    grand_total_paise=2140) | bad
        with pytest.raises(ValidationError):
            Cart(**data)


def test_negative_and_float_money_rejected():
    with pytest.raises(ValidationError):
        Charge(name="x", amount_paise=-1)
    with pytest.raises(ValidationError):
        Charge(name="x", amount_paise=10.5)
    with pytest.raises(ValidationError):
        CartLine(item_id="a", name="A", qty=2, unit_price_paise=1000, line_total_paise=1999)


def test_handoff_has_no_room_for_credentials():
    PaymentHandoff(kind="upi_intent", amount_paise=100, merchant="m",
                   upi_link="upi://pay?pa=x@y&pn=M&am=1.00&cu=INR")
    with pytest.raises(ValidationError):
        PaymentHandoff(kind="upi_intent", amount_paise=100, merchant="m",
                       upi_link="upi://pay?pa=x@y&pin=1234")
    with pytest.raises(ValidationError):
        PaymentHandoff(kind="qr", amount_paise=100, merchant="m")
    with pytest.raises(ValidationError):
        PaymentHandoff(kind="qr", amount_paise=100, merchant="m", qr_png=b"nope")
    with pytest.raises(ValidationError):
        PaymentHandoff(kind="qr", amount_paise=100, merchant="m", qr_png=PNG, otp="1")
    assert "qr_png" not in repr(PaymentHandoff(kind="qr", amount_paise=1, merchant="m",
                                               qr_png=PNG))


# ---------------------------------------------------------------- gate
def _args(**kw):
    base = {"task_id": TASK, "connector": "zomato.food", "restaurant_id": "r-dom-1",
            "items": [{"item_id": "i-marg", "qty": 2}, {"item_id": "i-garlic", "qty": 1}]}
    return base | kw


def test_gate_reads_allowed_pay_never():
    g = ActionGate()
    for t in ("search_restaurants", "get_menu", "track_order"):
        assert g.decide(t, {}, []) == Verdict.allow
    for t in ("pay", "place_order", "execute_payment", "wire_money"):
        assert g.decide(t, _args(), [make_grant()]) == Verdict.deny


def test_gate_blocks_without_grant_and_allows_with():
    g = ActionGate()
    assert g.decide("build_cart", _args(), []) == Verdict.ask
    assert g.decide("build_cart", _args(), [make_grant()]) == Verdict.allow
    # item order does not matter
    rev = _args(items=list(reversed(_args()["items"])))
    assert g.decide("build_cart", rev, [make_grant()]) == Verdict.allow


def test_gate_scope_mismatches_denied():
    g = ActionGate()
    grants = [make_grant()]
    assert g.decide("build_cart", _args(restaurant_id="r-dom-2"), grants) == Verdict.deny
    more = _args(items=[{"item_id": "i-marg", "qty": 3}, {"item_id": "i-garlic", "qty": 1}])
    assert g.decide("build_cart", more, grants) == Verdict.deny
    extra = _args(items=_args()["items"] + [{"item_id": "i-coke", "qty": 1}])
    assert g.decide("build_cart", extra, grants) == Verdict.deny
    assert g.decide("build_cart", _args(task_id="other"), grants) == Verdict.ask
    over = _args(total_paise=100_001)
    assert g.decide("get_payment_handoff", over, grants) == Verdict.deny
    assert g.decide("get_payment_handoff", _args(), grants) == Verdict.deny  # no total
    assert g.decide("get_payment_handoff", _args(total_paise=60_000), grants) == Verdict.allow


def test_gate_expired_and_one_time():
    now = datetime.now(UTC)
    g = ActionGate(now=lambda: now)
    old = make_grant(expires_at=now - timedelta(seconds=1))
    assert g.decide("build_cart", _args(), [old]) == Verdict.ask
    one = make_grant()
    one.mark_used("build_cart")
    assert g.decide("build_cart", _args(), [one]) == Verdict.ask
    assert g.decide("get_payment_handoff", _args(total_paise=1000), [one]) == Verdict.allow


# ---------------------------------------------------------------- otp
def test_otp_single_use_and_hidden_repr():
    ch = OneTimeOtpChannel()
    ch.submit("t", "987654")
    assert "987654" not in repr(ch) and "987654" not in str(ch)
    assert ch.has_pending("t")
    assert ch.take("t") == "987654"
    assert ch.take("t") is None and not ch.has_pending("t")


def test_otp_expiry_isolation_and_validation():
    now = [0.0]
    ch = OneTimeOtpChannel(ttl_seconds=10, clock=lambda: now[0])
    ch.submit("a", "1234")
    ch.submit("b", "5678")
    now[0] = 11
    assert ch.take("a") is None and not ch.has_pending("b")
    with pytest.raises(ValueError) as e:
        ch.submit("a", "12ab")
    assert "12ab" not in str(e.value)
    ch.submit("a", "1234")
    ch.wipe("a")
    assert ch.take("a") is None


# ---------------------------------------------------------------- scrub
def test_scrub_removes_secrets():
    text = (
        "Your OTP is 482913. Call +91 98765 43210 or 9876543210.\n"
        "Set-Cookie: sid=abcdef123456; Path=/\n"
        "Authorization: Bearer eyJhbGciOi.payload.sig1234\n"
        "token=abc123secret key api_key: Zx9\n"
        f"hash {'a1' * 20} blob {'Ab3' * 20}\n"
        "123456 is your verification code"
    )
    out = scrub(text)
    for leak in ("482913", "98765 43210", "9876543210", "abcdef123456", "eyJhbGciOi",
                 "abc123secret", "a1" * 20, "Ab3" * 20, "123456"):
        assert leak not in out, leak


def test_scrub_keeps_normal_text_and_walks_objects():
    plain = "Margherita ₹199.00 x 2, order FK1A2B3C"
    assert scrub(plain) == plain
    assert "https://x.example/a/b/c/d" in scrub("see https://x.example/a/b/c/d")
    obj = {"otp": "123456", "cookie": "k=v", "ok": ["call 9876543210"], "raw": b"abc"}
    out = scrub(obj)
    assert out["otp"] != "123456" and out["cookie"] != "k=v"
    assert "9876543210" not in out["ok"][0] and out["raw"] == "<3 bytes>"


# ---------------------------------------------------------------- registry
def test_registry_prefers_by_order_and_kill_switch():
    r = ConnectorRegistry()
    r.register(Registration("s", "food", BackendKind.llm_browser, Status.live, "1"))
    r.register(Registration("s", "food", BackendKind.scripted_browser, Status.live, "1"))
    assert r.select("s", "food").backend == BackendKind.scripted_browser
    r.register(Registration("s", "food", BackendKind.official_mcp, Status.degraded, "1"))
    assert r.select("s", "food").backend == BackendKind.scripted_browser
    r.set_status("s", "food", BackendKind.official_mcp, Status.live)
    assert r.select("s", "food").backend == BackendKind.official_mcp
    r.set_status("s", "food", BackendKind.official_mcp, Status.off)
    r.kill("s", "food")
    assert r.select("s", "food") is None
    assert {row["status"] for row in r.describe()} == {"off"}
    r.revive("s", "food")
    assert r.select("s", "food") is not None
    r.seed_kill_from_env({"FRIDAY_CONNECTORS_KILL": "s.food"})
    assert r.select("s", "food") is None
