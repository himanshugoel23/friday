"""Notifier: 24h window -> template fallback, consent gate, SMS fallback, logging."""

from __future__ import annotations

from datetime import timedelta

import pytest

from friday.channels.notifier import CONSENT_REQUIRED, TEMPLATE_REQUIRED, Notifier, build_notifier
from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.core.events import MessageSent
from friday.core.models import (
    Business,
    Channel,
    InboundMessage,
    MidCallQuestion,
    OutboundMessage,
    Person,
    PersonConsent,
    ReplyButton,
    TemplateRef,
    User,
    UserStatus,
)

USER = "+919800000001"
DAD = "+919811111111"


@pytest.fixture
def channel(container) -> SimulatorChannel:
    ch = SimulatorChannel(container.clock, dict(container.settings.whatsapp_templates))
    container.override("messaging", ch)
    return ch


@pytest.fixture
def sms(container) -> FakeSMS:
    s = FakeSMS(dict(container.settings.sms_dlt_templates), container.clock)
    container.override("sms", s)
    return s


@pytest.fixture
async def notifier(container, channel, sms) -> Notifier:
    await container.db.create_all()
    return build_notifier(container)


@pytest.fixture
async def user(container, clock) -> User:
    return await container.repos.users.add(
        User(phone=USER, status=UserStatus.ACTIVE, last_inbound_at=clock.now())
    )


async def test_freeform_inside_window_and_logged(container, notifier, channel, user):
    sent = []

    async def on_sent(e: MessageSent) -> None:
        sent.append(e)

    container.bus.subscribe(MessageSent, on_sent)
    r = await notifier.notify_user(
        user.id, "Booked!", buttons=[ReplyButton(id="a:t:yes", title="OK")]
    )
    assert r.ok
    out = channel.last_to(USER)
    assert out.text == "Booked!" and out.template is None and out.buttons
    assert out.channel == Channel.SIMULATOR
    stored = await container.repos.messages.list_for_user(user.id)
    assert stored[-1].text == "Booked!"
    assert sent and sent[0].ok


async def test_template_outside_window(container, notifier, channel, user, clock):
    clock.advance(hours=25)
    await notifier.notify_user(
        user.id, "Your slot\nis confirmed", buttons=[ReplyButton(id="x", title="Y")]
    )
    out = channel.last_to(USER)
    assert out.text is None and out.buttons == []
    assert out.template.key == "task_update" and out.template.params == ["Your slot\nis confirmed"]
    # question -> question template; nudge -> nudge template
    await notifier.notify_user(user.id, "q?", question_id="q1")
    assert channel.last_to(USER).template.key == "question"
    await notifier.notify_user(user.id, "n", nudge_id="n1")
    assert channel.last_to(USER).template.key == "nudge"
    # caller-given template is used as-is
    tpl = TemplateRef(key="friday_appointment_reminder", params=["Looks", "6pm"])
    await notifier.notify_user(user.id, template=tpl)
    assert channel.last_to(USER).template == tpl


async def test_window_boundary(notifier, channel, user, clock):
    clock.advance(hours=23, minutes=59)
    await notifier.notify_user(user.id, "still free-form")
    assert channel.last_to(USER).template is None
    clock.advance(minutes=2)
    await notifier.notify_user(user.id, "now template")
    assert channel.last_to(USER).template is not None


async def test_sms_fallback_when_chat_fails(container, notifier, channel, sms, user):
    channel.fail_phones.add(USER)
    r = await notifier.notify_user(user.id, "Your booking at Looks Salon is confirmed for 6pm")
    assert not r.ok
    assert sms.sent and sms.sent[0].template.key == "user_task_update"
    assert len(sms.sent[0].template.params[0]) <= 30


async def test_circle_member_consent_gate(container, notifier, channel, user, clock):
    dad = await container.repos.people.upsert(
        Person(owner_user_id=user.id, name="Ramesh", relation="father", phone=DAD, notes="diabetic")
    )
    r = await notifier.message_person(dad.id, "Reminder: doctor at 10am")
    assert not r.ok and r.error == CONSENT_REQUIRED
    assert channel.messages_to(DAD) == []

    # one-time opt-in template is allowed and marks PENDING
    r = await notifier.request_person_opt_in(dad, requester_name="Rahul", what="a doctor visit")
    assert r.ok
    out = channel.last_to(DAD)
    assert out.template.key == "beneficiary_optin"
    assert out.template.params == ["Ramesh", "Rahul", "father", "a doctor visit"]
    assert "diabetic" not in " ".join(out.template.params)
    assert (await container.repos.people.get(dad.id)).contact_consent == PersonConsent.PENDING
    # still no free-form while pending
    assert (await notifier.message_person(dad.id, "hi")).error == CONSENT_REQUIRED

    dad = await container.repos.people.get(dad.id)
    dad.contact_consent = PersonConsent.OPTED_IN
    await container.repos.people.upsert(dad)
    # opted in but outside the person's own 24h window -> template required
    assert (await notifier.message_person(dad.id, "hi")).error == TEMPLATE_REQUIRED
    tpl = TemplateRef(key="beneficiary_reminder", params=["Ramesh", "Doctor"])
    assert (await notifier.message_person(dad.id, template=tpl)).ok
    # after dad writes in, free-form is fine
    await container.repos.messages.log_inbound(
        InboundMessage(
            channel=Channel.SIMULATOR, from_phone=DAD, text="ok", received_at=clock.now()
        )
    )
    assert (await notifier.message_person(dad.id, "See you at 10")).ok
    # opted out -> nothing, not even an opt-in request
    dad.contact_consent = PersonConsent.OPTED_OUT
    await container.repos.people.upsert(dad)
    assert not (await notifier.request_person_opt_in(dad, requester_name="R", what="x")).ok


async def test_ask_user_records_question_and_buttons(container, notifier, channel, user):
    q = MidCallQuestion(
        task_id="t" * 32, text="4pm or 6pm?", options=["4pm", "6pm", "Neither of these!"]
    )
    # question needs its task row for FK
    from friday.core.models import Task, TaskSpec, TaskType

    await container.repos.tasks.add(
        Task(
            id="t" * 32,
            requester_user_id=user.id,
            type=TaskType.BOOKING,
            spec=TaskSpec(type=TaskType.BOOKING, goal="x"),
        )
    )
    r = await notifier.ask_user(user.id, q)
    assert r.ok
    out = channel.last_to(USER)
    assert [b.id for b in out.buttons] == [f"q:{q.id}:0", f"q:{q.id}:1", f"q:{q.id}:2"]
    assert all(len(b.title) <= 20 for b in out.buttons)
    assert (await container.repos.tasks.get_question(q.id)).text == "4pm or 6pm?"


async def test_business_touch_whatsapp_then_sms(container, notifier, channel, sms, user):
    on_wa = Business(name="Looks", phone="+918040000001", whatsapp_phone="+919840000001")
    mobile = Business(name="Plumber", phone="+919845000001")
    landline = Business(name="Clinic", phone="+911123456789")
    for b in (on_wa, mobile, landline):
        await container.repos.businesses.upsert(b)
    tpl = TemplateRef(
        key="business_booking_confirmed", params=["Rahul", "Haircut Sat 6pm", "Friday"]
    )
    assert (await notifier.business_touch(on_wa, tpl, user_id=user.id)).ok
    assert channel.last_to("+919840000001").template == tpl
    assert (await notifier.business_touch(mobile, tpl, user_id=user.id)).ok
    assert sms.sent[-1].to_phone == "+919845000001"
    assert sms.sent[-1].template.key == "business_booking_confirmed"
    assert not (await notifier.business_touch(landline, tpl, user_id=user.id)).ok
    # free-form to a business outside its window is refused
    r = await notifier.message_business(on_wa, "Can you share the menu?", user_id=user.id)
    assert r.error == TEMPLATE_REQUIRED
    audit = await container.repos.audit.list_for_user(user.id)
    assert sum(1 for a in audit if a.action == "business_touch_sent") == 2


async def test_send_accepts_urgency_kwarg(notifier, channel, user):
    from friday.core.models import Urgency

    msg = OutboundMessage(channel=Channel.SIMULATOR, to_phone=USER, user_id=user.id, text="x")
    assert (await notifier.send(msg, urgency=Urgency.SAFETY)).ok


async def test_window_uses_last_inbound(notifier, user, clock):
    assert await notifier.user_in_window(user.id)
    clock.advance(timedelta(hours=24).total_seconds())
    assert not await notifier.user_in_window(user.id)
