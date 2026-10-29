# ruff: noqa: E501
"""PROOF cards for every completed or attempted action (calls, lookups, cart/checkout, forms). Fakes only."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from friday.core.clock import IST
from friday.core.models import (
    CallOutcome,
    CallResult,
    CallTurn,
    ContactTarget,
    DialStatus,
    Speaker,
    TargetKind,
    Task,
    TaskResult,
    TaskSpec,
    TaskType,
    Transcript,
)
from friday.evidence import action_proof as ap
from friday.evidence.models import EvidenceKind
from friday.evidence.store import MemoryEvidenceStore
from friday.style import check

NOW = datetime(2026, 10, 29, 11, 0, tzinfo=IST)


class FakeObjects:
    def __init__(self) -> None:
        self.put_keys: list[str] = []

    async def put(self, key: str, data: bytes, content_type: str = "") -> str:
        self.put_keys.append(key)
        return key


def adapt(result, kind="cart", **kw):
    return ap.adapt_result(result, kind=kind, what="atta 5 kg", user_id="u1", task_id="t1", now=NOW, **kw)


# ------------------------------------------------------------------ the adapter reads public fields only
def test_adapter_reads_objects_and_dicts_and_strips_link_secrets():
    obj = SimpleNamespace(status="ok", url="https://shop.example.test/cart/42?token=SECRET#x", total=480, order_id="ZP-1234", screenshot=b"png", masked=True)
    a = adapt(obj, kind="form")
    assert (a.outcome, a.where, a.amount, a.reference, a.masked) == ("done", "shop.example.test", "Rs 480", "ZP-1234", True)
    assert a.link == "https://shop.example.test/cart/42" and "SECRET" not in a.link
    b = adapt({"status": "blocked", "site": "Zepto", "message": "bot check page"}, kind="lookup")
    assert (b.outcome, b.where, b.seen) == ("failed", "Zepto", "bot check page")
    c = adapt({}, kind="nonsense")
    assert (c.kind, c.outcome, c.link) == ("lookup", "attempted", "")  # a missing field just leaves a line out


def test_checkout_preview_is_never_done():
    assert adapt({"status": "ok", "total": 480}, kind="checkout").outcome == "checkout"
    assert adapt({"status": "error"}, kind="checkout").outcome == "failed"


# ------------------------------------------------------------------ the card + storage + expiry + erasure
async def test_card_for_a_finished_action_with_masked_screenshot_expires_and_is_erased():
    store, objects = MemoryEvidenceStore(), FakeObjects()
    svc = ap.ProofService(store, objects, retention_days=90)
    msg = await svc.record(adapt({"status": "ok", "url": "https://shop.example.test/o/9", "order_id": "ZP-1234", "total": 480, "screenshot": b"png", "masked": True}), now=NOW, lang="en")
    assert msg.text.startswith("Done. Proof:")
    for needle in ("What: atta 5 kg", "Where: shop.example.test", "When:", "Amount: Rs 480", "Reference: ZP-1234", "Link: https://shop.example.test/o/9", "Screenshot attached.", "90 days"):
        assert needle in msg.text
    assert check.check(msg.text, kind="proof") == []
    kinds = {i.kind for i in store.items}
    assert kinds == {EvidenceKind.ACTION_PROOF, EvidenceKind.SCREENSHOT}
    assert all(i.expires_at == NOW + timedelta(days=90) for i in store.items)
    assert msg.media == b"png" and objects.put_keys == ["evidence/u1/t1/cart.png"]
    # not yet expired, then expired: rows go and the screenshot key is handed back for deletion
    assert await store.expire(NOW + timedelta(days=89)) == (0, [])
    n, keys = await store.expire(NOW + timedelta(days=91))
    assert n == 2 and keys == ["evidence/u1/t1/cart.png"] and store.items == []


async def test_unmasked_screenshot_is_dropped_not_stored_not_sent():
    store, objects = MemoryEvidenceStore(), FakeObjects()
    msg = await ap.ProofService(store, objects).record(adapt({"status": "ok", "screenshot": b"png", "masked": False}), now=NOW, lang="en")
    assert msg.media is None and objects.put_keys == [] and "Screenshot attached." not in msg.text
    assert {i.kind for i in store.items} == {EvidenceKind.ACTION_PROOF} and not any(i.object_key for i in store.items)


async def test_failed_and_stopped_attempts_say_what_was_seen():
    store = MemoryEvidenceStore()
    svc = ap.ProofService(store)
    stop = await svc.record(adapt({"status": "stopped", "message": "payment page, card form"}, kind="checkout"), now=NOW, lang="en")
    assert "Nothing was charged" in stop.text and "Saw: payment page, card form" in stop.text
    fail = await svc.record(adapt({"status": "timeout", "message": "page never loaded"}, kind="form"), now=NOW, lang="hinglish")
    assert fail.text.startswith("Yeh nahi ho paya.") and "Dikha: page never loaded" in fail.text


async def test_card_without_a_store_promises_no_retention():
    msg = await ap.ProofService(None).record(adapt({"status": "ok"}, kind="lookup"), now=NOW, lang="en")
    assert "days" not in msg.text and msg.items[0].kind == EvidenceKind.ACTION_PROOF


# ------------------------------------------------------------------ calls
def _task() -> Task:
    return Task(
        requester_user_id="u1", type=TaskType.BOOKING, spec=TaskSpec(type=TaskType.BOOKING, goal="table for 4"),
        target=ContactTarget(kind=TargetKind.BUSINESS, name="Spice Hub", phone="+918040000001"),
    )


def _call(said: str, *, answered: bool = True) -> CallResult:
    turns = [CallTurn(speaker=Speaker.CALLEE, text=said)] if said else []
    return CallResult(
        task_id="t", provider="stub", to_phone="+918040000001",
        dial_status=DialStatus.ANSWERED if answered else DialStatus.NO_ANSWER,
        outcome=CallOutcome.SUCCESS if answered else CallOutcome.FAILED,
        transcript=Transcript(turns=turns), telephony_seconds=95,
    )


def test_call_card_reference_only_if_the_callee_said_it():
    t = _task()
    said = ap.adapt_call(t, _call("Confirmed, your booking number is BK4821."), TaskResult(success=True, summary="ok", details={"reference": "BK4821"}), now=NOW)
    assert (said.kind, said.outcome, said.where, said.reference) == ("call", "done", "Spice Hub", "BK4821")
    invented = ap.adapt_call(t, _call("Confirmed for Saturday."), TaskResult(success=True, summary="ok", details={"reference": "BK9999"}), now=NOW)
    assert invented.reference == ""  # nobody said it: not proof


def test_unanswered_call_is_an_attempted_card_with_what_happened():
    a = ap.adapt_call(_task(), _call("", answered=False), None, now=NOW)
    assert a.outcome == "attempted" and "not answered" in a.seen


# ------------------------------------------------------------------ send_card (gateway helper)
class FakePipeline:
    def __init__(self, enabled: bool, evidence=None) -> None:
        self.settings = SimpleNamespace(style_layer_enabled=enabled, proof_retention_days=30)
        self.repos = SimpleNamespace(evidence=evidence)
        self.clock = SimpleNamespace(now=lambda: NOW)
        self.sent: list[str] = []

    async def reply(self, user, text, buttons=()):  # noqa: ANN001
        self.sent.append(text)


async def test_send_card_off_sends_nothing_on_sends_one_and_stores_only_for_a_task():
    user = SimpleNamespace(id="u1")
    off = FakePipeline(False)
    assert await ap.send_card(off, user, {"status": "ok"}, kind="lookup", what="atta", lang="en") is None and off.sent == []
    store = MemoryEvidenceStore()
    on = FakePipeline(True, store)
    await ap.send_card(on, user, {"status": "ok"}, kind="lookup", what="atta", lang="en")
    assert len(on.sent) == 1 and store.items == []  # no task: card sent, nothing stored, no retention promise
    assert "days" not in on.sent[0]
    await ap.send_card(on, user, {"status": "ok"}, kind="form", what="form", lang="en", task_id="t9")
    assert len(on.sent) == 2 and "30 days" in on.sent[1] and store.items[0].task_id == "t9"


async def test_send_card_never_raises():
    class Boom:
        async def add_items(self, items):  # noqa: ANN001
            raise RuntimeError("db down")

    p = FakePipeline(True, Boom())
    assert await ap.send_card(p, SimpleNamespace(id="u1"), {"status": "ok"}, kind="form", what="f", lang="en", task_id="t") is None
