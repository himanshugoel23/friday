"""Parents (beneficiary + opt-in + own language), wellbeing check-ins with consent, location."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from friday.core.models import PersonConsent, TaskStatus, TaskType
from friday.db.tables import PersonRow
from tests.e2e.conftest import PAPA
from tests.e2e.harness import callee_lines

ADD_PAPA = "add my papa Suresh Verma +911140001016 Hindi, rehte hain Delhi"


async def _papa(friday, rahul):
    await rahul.say(ADD_PAPA)
    user = await rahul.user_row()
    (person,) = await friday.c.repos.people.list_for_owner(user.id)
    return person


async def test_circle_member_is_not_messaged_until_they_opt_in(friday, rahul):
    person = await _papa(friday, rahul)
    assert person.contact_consent != PersonConsent.OPTED_IN
    assert friday.channel.messages_to(PAPA) == []
    # a booking for papa runs, but papa gets no confirmation without consent
    await rahul.say("papa ke liye Dr. Sharma's Family Clinic mein appointment book karo kal subah")
    await rahul.say("1")
    assert friday.channel.messages_to(PAPA) == []


async def test_booking_for_a_parent_confirms_to_them_in_their_language_after_opt_in(
    friday, rahul
):
    person = await _papa(friday, rahul)
    await friday.c.notifier.request_person_opt_in(
        person, requester_name="Rahul", what="booking confirmations"
    )
    ask = friday.channel.messages_to(PAPA)
    assert len(ask) == 1 and ask[0].template is not None  # one opt-in template, nothing else
    await friday.person(PAPA).say("haan")
    person = await friday.c.repos.people.get(person.id)
    assert person.contact_consent == PersonConsent.OPTED_IN
    assert "said yes" in rahul.last()

    await rahul.say("papa ke liye Dr. Sharma's Family Clinic mein appointment book karo kal subah")
    await rahul.say("1")
    t = await rahul.task()
    assert t.status == TaskStatus.COMPLETED and t.beneficiary.person_id == person.id
    to_papa = friday.channel.messages_to(PAPA)
    confirm = to_papa[-1]
    assert "Dr. Sharma" in (confirm.text or "")
    # minimal content: no price, no Rahul's other details
    assert "₹" not in (confirm.text or "")


@pytest.mark.xfail(
    strict=True,
    reason="BUG-13: nothing ever calls Notifier.request_person_opt_in, so circle members are "
    "never asked; and checkin_consent is never set to OPTED_IN anywhere",
)
async def test_wellbeing_checkin_asks_the_parent_for_consent_first(friday, rahul):
    await _papa(friday, rahul)
    await rahul.say("papa ko roz subah call karke haal chaal poocho")
    assert friday.channel.messages_to(PAPA), "papa must be asked before any check-in call"


async def test_wellbeing_checkin_runs_only_after_consent_and_raises_an_alert(friday, rahul):
    person = await _papa(friday, rahul)
    await rahul.say("papa ko roz subah call karke haal chaal poocho")
    t = await rahul.task()
    assert t.type == TaskType.WELLBEING_CHECKIN and t.status == TaskStatus.NEEDS_INFO
    assert not await rahul.calls(t)  # no call without the parent's consent
    # papa consents (written straight to the table: the product never records it - BUG-13)
    async with friday.c.db.session() as session:
        await session.execute(
            update(PersonRow)
            .where(PersonRow.id == person.id)
            .values(checkin_consent="opted_in", contact_consent="opted_in")
        )
    await friday.engine.provide_info(t.id, t.spec.model_copy(update={"missing": []}))
    await friday.settle()
    await friday.advance(days=1)  # the series fires at 09:00 IST
    instances = [x for x in await rahul.tasks() if x.parent_task_id == t.id]
    assert instances, [x.status for x in await rahul.tasks()]
    calls = await rahul.calls(instances[0])
    assert calls and calls[0].to_phone == PAPA
    opening = calls[0].transcript.turns[1].text
    assert "AI" in opening and any("\u0900" <= ch <= "\u097f" for ch in opening)  # Hindi, disclosed
    assert "Alert: Suresh Verma" in rahul.last() and "112/108" in rahul.last()
    assert callee_lines(calls[0])


# ---------------------------------------------------------------- location (no app)
async def test_saved_office_resolves_near_my_office(friday, rahul):
    await rahul.say("save my office: Indiranagar, Bengaluru")
    user = await rahul.user_row()
    places = await friday.c.repos.places.list_for_owner(user.id)
    assert any(p.label.lower() == "office" for p in places)
    await rahul.say("mere office ke paas AC repair karne wala dhundo")
    t = await rahul.task()
    assert t.status == TaskStatus.AWAITING_APPROVAL
    assert "CoolCare AC Services" in rahul.last()


async def test_whatsapp_location_pin_is_acknowledged_and_stored(friday, rahul):
    await rahul.say("/pin 12.97,77.64")
    assert "Location mil gayi" in rahul.last()


async def test_typed_landmark_resolves_to_a_city_area(friday, rahul):
    await rahul.say("Indiranagar mein AC repair karne wala dhundo, 3 se quotes lo")
    t = await rahul.task()
    assert t.status == TaskStatus.AWAITING_APPROVAL and "CoolCare" in rahul.last()


@pytest.mark.xfail(
    strict=True,
    reason="BUG-15: after sharing a location pin, 'yahan ke paas ...' is geocoded as the text "
    "'yahan' and finds nobody; the pin is not used as the search origin",
)
async def test_near_me_uses_the_shared_pin(friday, rahul):
    await rahul.say("/pin 12.97,77.64")
    await rahul.say("yahan ke paas AC repair karne wala dhundo")
    t = await rahul.task()
    assert t.status == TaskStatus.AWAITING_APPROVAL
