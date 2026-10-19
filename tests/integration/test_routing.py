"""The front door: the right handler gets the message, and with the switches off (or no intent
matching) the old flows behave exactly as before."""

from __future__ import annotations

import pytest

from friday.core.config import Settings
from friday.core.models import InboundMessage, MessageKind
from friday.integration.buttons import ButtonRegistry, Handled, prefix_of
from friday.integration.wiring import Switches, build_consumer
from tests.integration.conftest import MUMMY, World, add_contact, close_world, make_world

LATE = "mummy ko phone karke bata do ki main late hoon"
SALON = "kal shaam parlour mein haircut karwana hai, quotes chahiye"


def shape(msgs) -> list[tuple[str, list[str]]]:  # noqa: ANN001
    return [(m.text or "", [b.title for b in m.buttons]) for m in msgs]


# ------------------------------------------------------------------------------- switches
def test_all_four_switches_default_to_off():
    s = Settings(_env_file=None)
    assert (s.consumer_calls_enabled, s.savings_enabled) == (False, False)
    assert (s.lifestate_enabled, s.google_enabled) == (False, False)
    assert not Switches.of(s).any


def test_switches_read_the_documented_env_names(monkeypatch):
    for name in (
        "FRIDAY_CONSUMER_CALLS_ENABLED",
        "FRIDAY_SAVINGS_ENABLED",
        "FRIDAY_LIFESTATE_ENABLED",
        "FRIDAY_GOOGLE_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    s = Settings(_env_file=None)
    assert Switches.of(s).calls and Switches.of(s).savings
    assert Switches.of(s).lifestate and Switches.of(s).google


def test_the_component_is_none_while_every_switch_is_off(off_world: World):
    assert off_world.c.get("consumer") is None
    assert build_consumer(off_world.c) is None


async def test_partial_switches_build_only_their_parts():
    w = await make_world(calls=False, savings=True, lifestate=False)
    try:
        r = w.consumer
        assert r.savings is not None and r.calls is None and r.life is None and r.google is None
        assert r.buttons.owns("bill:x:paid") and not r.buttons.owns("callap:x:approve:abcd1234")
    finally:
        await close_world(w)


# ------------------------------------------------------------------------------- old flows
async def test_switches_off_every_message_reaches_the_brain_as_before(off_world: World):
    for text in (LATE, "kaun sa card Zomato pe 640", "kal 2 baje interview hai", "mera din"):
        replies = await off_world.say(text)
        assert replies and replies[-1].text == "I can make calls for you."  # the FakeBrain's reply
    assert off_world.brain.seen[-4:] == [
        LATE,
        "kaun sa card Zomato pe 640",
        "kal 2 baje interview hai",
        "mera din",
    ]


async def test_switches_off_the_context_has_no_day_summary(off_world: World):
    await off_world.say("hello")
    assert off_world.brain.contexts[-1].day_summary is None


async def test_the_salon_quotes_flow_answers_the_same_with_the_switches_on():
    off = await make_world(calls=False, savings=False, lifestate=False)
    on = await make_world()
    try:
        a = await off.say(SALON)
        b = await on.say(SALON)
        assert a and shape(a) == shape(b)  # same words, same buttons
        a2 = await off.say("Sector 56 Gurgaon")
        b2 = await on.say("Sector 56 Gurgaon")
        assert shape(a2) == shape(b2)
        assert on.brain.seen == off.brain.seen  # the brain saw exactly the same
    finally:
        await close_world(off)
        await close_world(on)


async def test_nothing_matching_falls_through_to_the_brain(world: World):
    for text in ("hello", "what is the weather", "mujhe ek pizza chahiye"):
        replies = await world.say(text)
        assert replies and replies[-1].text == "I can make calls for you."
    assert world.brain.seen[-3:] == ["hello", "what is the weather", "mujhe ek pizza chahiye"]


async def test_a_business_call_keeps_its_approved_playbook(world: World):
    replies = await world.say("Taj restaurant ko call karke table book karo")
    assert world.brain.seen[-1] == "Taj restaurant ko call karke table book karo"
    assert replies and not any("Call ka plan" in (m.text or "") for m in replies)


async def test_an_active_quote_conversation_keeps_its_free_text(world: World):
    first = await world.say(SALON)
    assert "Aap kahan hain" in (first[-1].text or "")  # the quotes flow really started
    store = world.consumer.life.store
    await world.say("kal 2 baje interview hai")  # an answer inside the salon flow
    assert await store.list_events(world.user.id) == []  # not captured as a life event


# ------------------------------------------------------------------------------- buttons
def test_registry_ignores_unknown_and_foreign_ids():
    reg = ButtonRegistry()
    assert prefix_of("q:1:2") is None and prefix_of("n:1:ack") is None and prefix_of(None) is None
    assert prefix_of("led:1:used") == "led" and prefix_of("callap:1:approve:ab") == "callap"
    assert not reg.owns("led:1:used")


async def test_registry_dispatch_unknown_returns_none_and_a_crashing_handler_is_swallowed():
    reg = ButtonRegistry()
    assert await reg.dispatch("u", "nonsense") is None
    assert await reg.dispatch("u", "led:1:used") is None  # known prefix, nobody registered

    async def boom(user_id: str, button_id: str) -> Handled:
        raise RuntimeError("secret detail")

    reg.register("bill", boom)
    res = await reg.dispatch("u", "bill:1:paid")
    assert res is not None and res.text is None


def test_registry_refuses_a_prefix_nobody_owns():
    with pytest.raises(ValueError):
        ButtonRegistry().register("zzz", lambda u, b: None)  # type: ignore[arg-type]


async def test_unknown_button_id_changes_nothing_and_goes_the_old_way(world: World):
    msg = InboundMessage(
        channel=world.channel.channel, from_phone=world.phone, kind=MessageKind.BUTTON_REPLY,
        text="Something", button_id="zz:1:2", provider_message_id="x1",
    )  # fmt: skip
    before = len(world.channel.messages_to(world.phone))
    await world.runtime.handle(msg)
    assert world.brain.seen[-1] == "Something"  # old behaviour: the title goes to the brain
    assert len(world.channel.messages_to(world.phone)) == before + 1


async def test_a_tap_on_someone_elses_request_is_swallowed(world: World):
    await add_contact(world, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
    await world.say(LATE)
    approval = world.channel.last_to(world.phone)
    approve_id = approval.buttons[0].id
    from friday.core.models import User, UserStatus

    other = await world.c.repos.users.add(User(phone="+919800000055", status=UserStatus.ACTIVE))
    msg = InboundMessage(
        channel=world.channel.channel, from_phone=other.phone, kind=MessageKind.BUTTON_REPLY,
        text="Approve", button_id=approve_id, provider_message_id="x2",
    )  # fmt: skip
    await world.runtime.handle(msg)
    await world.run_jobs()
    assert world.telephony.dialled == []
    assert world.channel.messages_to(other.phone) == []  # nothing, not even a refusal


async def test_an_old_approval_button_cannot_approve_an_edited_plan(world: World):
    world.telephony.assign(MUMMY, "friendly_elder")
    await add_contact(world, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
    await world.say(LATE)
    old_approve = world.channel.last_to(world.phone).buttons[0].id
    await world.tap("Edit")
    r = await world.say("main thodi der mein aaungi")  # the edit: a new plan, a new approval
    new_prompt = r[-1]
    assert "thodi der mein aaungi" in (new_prompt.text or "") and new_prompt.buttons
    assert new_prompt.buttons[0].id != old_approve
    stale = world.channel.make_inbound(world.phone, "1")
    stale = stale.model_copy(
        update={"kind": MessageKind.BUTTON_REPLY, "button_id": old_approve, "text": "Approve"}
    )
    await world.runtime.handle(stale)
    await world.run_jobs()
    assert world.telephony.dialled == []  # the old tap approved nothing
    await world.say("1")  # the new Approve
    await world.run_jobs()
    assert world.telephony.dialled == [MUMMY]
    brief = await world.c.repos.consumer_calls.get_brief(
        (await world.c.repos.consumer_calls.list_for_user(world.user.id))[0].id
    )
    assert brief is not None and brief.goal == "main thodi der mein aaungi"


async def test_cancel_words_drop_a_half_finished_call_request(world: World):
    r = await world.say("plumber ko call karo kal aane ke liye")
    assert r  # one question at a time
    r = await world.say("cancel")
    assert "hata diya" in (r[-1].text or "")
    r = await world.say("500 rupees tak")  # no longer an answer to anything
    assert world.brain.seen[-1] == "500 rupees tak"


# ------------------------------------------------------------------------------- savings
async def test_savings_commands_and_buttons_are_routed(world: World):
    r = await world.say("mere paas HDFC Regalia aur SBI Cashback hai")
    assert "HDFC" in (r[-1].text or "")
    r = await world.say("mere cards")
    assert "Regalia" in (r[-1].text or "")
    assert world.brain.seen == []  # the brain never saw any of it


# ------------------------------------------------------------------------------- Google
async def test_google_connect_status_disconnect_intents():
    w = await make_world(calls=False, savings=False, lifestate=False, google=True)
    try:
        assert w.fake_google is not None
        r = await w.say("google connect karo")
        assert "friday.example/google/consent/" in (r[-1].text or "")
        r = await w.say("google status")
        assert "juda nahi" in (r[-1].text or "")
        from tests.google.conftest import connect_user

        await connect_user(w.consumer.google.oauth(), w.fake_google, w.user.id)
        r = await w.say("google status")
        assert "juda hua hai" in (r[-1].text or "") and "alice" not in (r[-1].text or "")
        r = await w.say("google disconnect karo")
        assert "hata diya" in (r[-1].text or "")
        r = await w.say("google disconnect karo")
        assert "juda hi nahi tha" in (r[-1].text or "")
        assert w.brain.seen == []
    finally:
        await close_world(w)


async def test_google_switch_off_the_intent_goes_to_the_brain(world: World):
    await world.say("google connect karo")
    assert world.brain.seen[-1] == "google connect karo"


async def test_google_not_configured_says_so(world: World):
    from tests.integration.conftest import settings_with  # noqa: F401

    w = await make_world(calls=False, savings=False, lifestate=False, google=True)
    try:
        w.c.settings.google_oauth_client_secret = None  # type: ignore[assignment]
        r = await w.say("connect google")
        assert "set up nahi hai" in (r[-1].text or "")
    finally:
        await close_world(w)


async def test_without_a_telephony_line_a_call_request_is_answered_honestly(world: World):
    """Production default until a real line is wired: say so, store nothing, dial nothing."""
    world.consumer.line_available = False
    await add_contact(world, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
    r = await world.say(LATE)
    assert "rasta chalu nahi hai" in (r[-1].text or "") and not r[-1].buttons
    assert await world.c.repos.consumer_calls.list_for_user(world.user.id) == []
    assert world.brain.seen == []


async def test_the_container_default_has_no_line():
    from friday.integration.wiring import build_stack

    w = await make_world()
    try:
        router = build_stack(
            settings=w.c.settings, clock=w.clock, repos=w.c.repos,
            send=lambda *a: None, queue=w.c.get("job_queue"),
        )  # fmt: skip
        assert router is not None and router.line_available is False
        assert w.consumer.line_available is True  # the test world plugs in a simulated line
    finally:
        await close_world(w)


@pytest.mark.parametrize(
    "text",
    [
        "kal subah 8 baje mujhe cab chahiye",
        "kal ka mausam kaisa hai",
        "book a table tomorrow 8pm",
        "aaj shaam 6 baje pizza order karo",
        "what time is it",
        "Sharma ji ka number kya hai",
        "haan",
        "thanks",
    ],
)
async def test_requests_and_questions_are_never_taken_for_life_statements(world: World, text):
    replies = await world.say(text)
    assert world.brain.seen[-1] == text and replies[-1].text == "I can make calls for you."
    assert await world.consumer.life.store.list_events(world.user.id) == []
    assert world.consumer._capture.get(world.user.id) is None  # no half-open question either
