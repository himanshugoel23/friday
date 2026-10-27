"""The list message on the wire, and the chatbot next to the consumer router and the old flows."""

from __future__ import annotations

from friday.channels.whatsapp import build_payload, parse_message
from friday.core.models import Channel, ListMenu, ListRow, OutboundMessage
from tests.chatbot.conftest import TESTER


def test_a_list_message_becomes_a_graph_api_interactive_list():
    menu = ListMenu(
        button="Menu dekhein",
        rows=[
            ListRow(id="cb:menu:call", title="Kisi ko call karwao", description="Aapke liye call"),
            ListRow(id="cb:menu:stop", title="Messages band karo"),
        ],
    )
    msg = OutboundMessage(
        channel=Channel.WHATSAPP, to_phone="+919811100001", text="Chuniye", list_menu=menu
    )
    body = build_payload(msg, templates={}, template_language="en")
    inter = body["interactive"]
    assert body["type"] == "interactive" and inter["type"] == "list"
    assert inter["body"]["text"] == "Chuniye" and inter["action"]["button"] == "Menu dekhein"
    rows = inter["action"]["sections"][0]["rows"]
    assert rows[0] == {
        "id": "cb:menu:call",
        "title": "Kisi ko call karwao",
        "description": "Aapke liye call",
    }
    assert rows[1] == {"id": "cb:menu:stop", "title": "Messages band karo"}


def test_a_list_reply_arrives_as_a_button_reply():
    m = parse_message(
        {
            "from": "919811100001",
            "id": "wamid.1",
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "cb:menu:day", "title": "Mera din"},
            },
        }
    )
    assert m is not None and m.button_id == "cb:menu:day" and m.text == "Mera din"


async def test_the_consumer_router_still_gets_its_messages_when_the_chatbot_is_on(make_chat):
    chat = await make_chat(savings_enabled=True, lifestate_enabled=True)
    try:
        await chat.onboard()
        chat.channel.clear()
        out = await chat.say("mere paas HDFC Regalia card hai")
        assert out and "Regalia" in " ".join(m.text or "" for m in out)
        assert chat.brain.seen == []  # the savings flow answered, not the brain
        out = await chat.say("mera din")
        assert out  # the life-state brief
        assert chat.brain.seen == []
    finally:
        await chat.c.aclose()


async def test_menu_beats_the_consumer_router_and_the_brain(make_chat):
    chat = await make_chat(savings_enabled=True, lifestate_enabled=True)
    try:
        await chat.onboard()
        out = await chat.say("help")
        assert out[-1].list_menu is not None
    finally:
        await chat.c.aclose()


async def test_an_existing_active_user_gets_the_menu_without_any_onboarding(chat):
    from friday.core.models import Profile, User, UserStatus

    u = await chat.c.repos.users.add(User(phone=TESTER, status=UserStatus.ACTIVE))
    await chat.c.repos.profiles.save(Profile(user_id=u.id, name="Founder"))
    out = await chat.say("menu")
    assert out[-1].list_menu is not None
    await chat.say("kuch bhi yaar")
    assert chat.brain.seen[-1] == "kuch bhi yaar"
    assert await chat.c.repos.chatbot.session_for_user(u.id) is None  # no session was invented
