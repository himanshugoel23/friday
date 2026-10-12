"""PMGateway: which WhatsApp messages the project manager takes, and that replies are sent."""

from __future__ import annotations

from types import SimpleNamespace

from friday.core.models import InboundMessage, MessageKind, User
from friday.pm.gateway import PMGateway, call_window_ok
from friday.pm.state import MemoryTaskStore
from tests.pm.test_adapters import ITEMS, build


class Notifier:
    def __init__(self):
        self.sent = []

    async def notify_user(self, user_id, text, **kw):
        self.sent.append((user_id, text))


def gw(enabled=True):
    outcomes = {"p1": ("quote", 600), "p2": ("quote", 450), "p3": ("no_answer", None)}
    pm, _ = build(ITEMS, outcomes)
    notifier = Notifier()
    c = SimpleNamespace(
        settings=SimpleNamespace(pm_enabled=enabled, pm_min_confidence=0.6),
        get=lambda name: notifier if name == "notifier" else None,
    )

    async def inline(job):
        await job

    g = PMGateway(c, pm=pm, store=pm.store, spawn=inline)
    return g, notifier


def msg(text, kind=MessageKind.TEXT):
    return InboundMessage(channel="whatsapp", from_phone="+919811100001", kind=kind, text=text)


USER = User(phone="+919811100001")


async def test_disabled_takes_nothing():
    g, n = gw(enabled=False)
    assert await g.handle(USER, msg("AC repair ka rate batao Gurgaon")) is False and n.sent == []


async def test_salon_and_chatter_are_left_to_the_other_handlers():
    g, n = gw()
    assert await g.handle(USER, msg("haircut kitna lega")) is False  # quotes flow owns salon
    assert await g.handle(USER, msg("hello")) is False
    assert await g.handle(USER, msg("   ")) is False
    assert n.sent == []


async def test_non_salon_request_is_taken_and_answered():
    g, n = gw()
    assert await g.handle(USER, msg("AC repair ka rate batao Gurgaon")) is True
    assert n.sent, "the PM's first question or ack must reach the user"
    assert all(uid == USER.id for uid, _ in n.sent)


def test_call_window():
    from datetime import datetime

    from friday.core.clock import IST

    s = SimpleNamespace(quotes_call_window_start="09:00", quotes_call_window_end="19:00")
    assert call_window_ok(s, datetime(2026, 10, 12, 11, 0, tzinfo=IST))
    assert not call_window_ok(s, datetime(2026, 10, 12, 20, 0, tzinfo=IST))
    assert MemoryTaskStore().active_for_user("x") is None
