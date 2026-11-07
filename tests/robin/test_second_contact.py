# ruff: noqa: E501
"""T08: the second contact receives exactly the alert line, only when they were named in advance (and agreed), by WhatsApp with an SMS
fallback; and delivery to the CHILD: WhatsApp -> SMS (the Notifier) -> chat inbox, with the delivery-failed flag that escalates one rung
earlier. Fakes only: nothing is sent or dialled."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from friday.core.models import Channel, InboundMessage, MessageKind, OutboundMessage
from friday.robin import lines
from friday.robin.models import CallResult, Tier
from friday.robin.wiring import make_second_sender
from tests.robin.conftest import CHILD_PHONE, SECOND_PHONE
from tests.robin.test_alerts_sos import alert, ready


class FakeNotifier:
    """Stands in for channels/notifier.Notifier: WhatsApp ``send`` and DLT ``send_sms``; either can be told to refuse."""

    def __init__(self, wa_ok=True, sms_ok=True, has_sms=True):
        self.wa_ok, self.sms_ok = wa_ok, sms_ok
        self.wa: list[OutboundMessage] = []
        self.sms: list[tuple[str, object]] = []
        if has_sms:
            self.send_sms = self._send_sms

    async def send(self, msg):
        self.wa.append(msg)
        return SimpleNamespace(ok=self.wa_ok, error=None if self.wa_ok else "template_required")

    async def _send_sms(self, phone, template):
        self.sms.append((phone, template))
        return SimpleNamespace(ok=self.sms_ok, error=None if self.sms_ok else "sms_failed")


async def second_world(w, notifier):
    fam, parent = await ready(w, second=True)
    second = await w.ctx.second(fam)
    second.call_ok = True
    await w.store.save_member(second, fam.owner_user_id)
    w.ctx.extra_senders["second"] = make_second_sender(lambda: notifier)
    return fam, parent, second


async def test_the_named_second_contact_gets_exactly_the_alert_line_and_nothing_else(w):
    n = FakeNotifier()
    fam, parent, second = await second_world(w, n)
    w.caller.script(CallResult.NO_ANSWER)
    await w.hub.alerts.raise_alert(alert(parent, tier=Tier.EMERGENCY, scenario="S1", why="unknown caller 22 minutes", dedupe_key="e1"))
    expected = lines.say("alert.second", "hinglish", brand="Robin", why="unknown caller 22 minutes", **await w.ctx.slots(fam))
    to_second = [m for m in n.wa if m.to_phone == SECOND_PHONE]
    assert [m.text for m in to_second] == [expected]  # exactly the line the engine built
    assert all(m.template is None and not m.buttons and m.media_url is None for m in to_second)
    assert CHILD_PHONE not in expected and "+91" not in expected  # no data beyond the alert line
    assert {m.to_phone for m in n.wa} == {SECOND_PHONE}  # nobody else was messaged by this sender


async def test_a_contact_who_was_not_named_in_advance_never_receives_anything(w):
    n = FakeNotifier()
    fam, parent = await ready(w)  # no second contact was named
    w.ctx.extra_senders["second"] = make_second_sender(lambda: n)
    w.caller.script(CallResult.NO_ANSWER)
    await w.hub.alerts.raise_alert(alert(parent, tier=Tier.EMERGENCY, scenario="S1", dedupe_key="e1"))
    assert n.wa == [] and n.sms == []
    inc = (await w.store.list(fam.id, "incident"))[0]
    assert {st["result"] for st in inc.data["steps"] if st["action"] in ("wa_second", "call_second") and st["state"] == "done"} == {"no_second_contact"}


async def test_the_sender_refuses_the_child_the_parent_and_a_contact_who_did_not_agree(w):
    n = FakeNotifier()
    fam, parent, second = await second_world(w, n)
    send = w.ctx.extra_senders["second"]
    for other in (parent, await w.ctx.child(fam)):
        with pytest.raises(PermissionError):
            await send(other, "x")
    second.call_ok = False
    with pytest.raises(PermissionError):
        await send(second, "x")
    assert n.wa == [] and n.sms == []


async def test_outside_the_24h_window_whatsapp_is_refused_and_the_same_line_goes_by_sms(w):
    n = FakeNotifier(wa_ok=False)  # the second contact is not a Friday user: a free-text WhatsApp is refused (template needed, Meta blocked)
    fam, parent, second = await second_world(w, n)
    await w.ctx.extra_senders["second"](second, "Papa may need help.")
    assert len(n.wa) == 1 and len(n.sms) == 1
    phone, template = n.sms[0]
    assert phone == SECOND_PHONE and template.params == ["Papa may need help."]  # the same alert line, one DLT variable


async def test_unreachable_second_contact_is_recorded_as_could_not_send(w):
    n = FakeNotifier(wa_ok=False, sms_ok=False)
    fam, parent, second = await second_world(w, n)
    assert await w.ctx.tell_second(fam, second, "alert") is False
    n2 = FakeNotifier(wa_ok=False, has_sms=False)  # no SMS provider at all
    w.ctx.extra_senders["second"] = make_second_sender(lambda: n2)
    assert await w.ctx.tell_second(fam, second, "alert") is False
    w.caller.script(CallResult.NO_ANSWER)
    await w.hub.alerts.raise_alert(alert(parent, tier=Tier.EMERGENCY, scenario="S1", dedupe_key="e2"))
    audit = [r.data["text"] for r in await w.store.list(fam.id, "audit") if r.data.get("event") == "message"]
    assert any("second contact: could not send" in t for t in audit)


# ============================================================================ delivery to the child
async def test_an_unreachable_child_causes_earlier_escalation(w):
    fam, parent = await ready(w)
    w.caller.script(CallResult.NO_ANSWER)
    spacing = fam.settings.call_spacing_min * 60

    async def child_rings(incident_id):
        return [r for r in await w.store.list(fam.id, "audit") if r.data.get("event") == "call" and r.data.get("purpose") == "escalation_child" and r.data.get("incident_id") == incident_id]

    # a reachable child: the first ring of a HIGH alert is one spacing in, so nothing rings after 90 s
    ok = await w.hub.alerts.raise_alert(alert(parent, dedupe_key="ok1"))
    w.go(seconds=90)
    await w.hub.alerts.tick()
    assert await child_rings(ok.incident_id) == []
    # an unreachable child (the send raises): the ladder moves one rung earlier, so the ring comes before one full spacing
    w.go(hours=3)
    w.sender.fail = True
    res = await w.hub.alerts.raise_alert(alert(parent, dedupe_key="down1"))
    inc = await w.store.get(res.incident_id)
    assert inc.data["delivery_failed"] is True
    assert next(st for st in inc.data["steps"] if st["action"] == "wa_child")["result"] == "failed"
    w.go(seconds=90)
    assert spacing > 90
    await w.hub.alerts.tick()
    assert len(await child_rings(res.incident_id)) == 1
    flagged = [x for x in await w.store.list(fam.id, "audit") if x.data.get("event") == "delivery_failed"]
    assert len(flagged) == 1  # flagged once per incident


async def test_a_message_the_childs_phone_could_not_receive_waits_in_the_chat_inbox_and_is_shown_once(w):
    fam, parent = await ready(w)
    w.sender.fail = True
    await w.hub.alerts.raise_alert(alert(parent, dedupe_key="held1", why="unknown caller 22 minutes"))
    assert w.sender.sent == [] and await w.ctx.inbox.count(fam) >= 1
    w.sender.fail = False  # the child comes back and writes
    user = await w.ctx.users.get(fam.owner_user_id)
    msg = InboundMessage(channel=Channel.WHATSAPP, from_phone=CHILD_PHONE, kind=MessageKind.TEXT, text="medicines")
    await w.hub.handle(user, msg)
    texts = w.sender.texts()
    assert any("held these messages" in t for t in texts) and any("unknown caller 22 minutes" in t for t in texts)
    n = len(texts)
    await w.hub.handle(user, msg)  # shown once
    assert not any("unknown caller 22 minutes" in t for t in w.sender.texts()[n:])
    assert await w.ctx.inbox.count(fam) == 0


async def test_a_held_message_stays_held_if_the_phone_is_still_unreachable(w):
    fam, parent = await ready(w)
    w.sender.fail = True
    await w.hub.alerts.raise_alert(alert(parent, dedupe_key="held2"))
    held = await w.ctx.inbox.count(fam)
    assert held >= 1
    assert await w.ctx.inbox.deliver(fam, w.sender) == 0  # still failing
    assert await w.ctx.inbox.count(fam) == held
    assert lines.CHAT["inbox.head"]  # the PENDING line that introduces them
