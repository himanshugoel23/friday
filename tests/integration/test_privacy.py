"""(g) No plain phone number, private fact, token or card-like string in any log line or outgoing
message across the call, savings, life-state and Google flows."""

from __future__ import annotations

import re

from tests.google.conftest import connect_user
from tests.integration.conftest import MUMMY, SIS, World, add_contact, close_world, make_world

PHONE = re.compile(r"(?<![0-9A-Za-z])(?:\+?91[\s-]?)?[6-9]\d{9}(?![0-9A-Za-z])")
CARD = re.compile(r"(?<![0-9A-Za-z])(?:\d[ -]?){13,19}(?![0-9A-Za-z])")
SECRET_FACT = "85000"
CARD_NUMBER = "4111 1111 1111 1111"


def spoken_by_friday(w: World) -> str:
    return "\n".join(t for line in w.telephony.lines for t, _l, _t in line.spoken)


def assert_clean(w: World, caplog, tokens: set[str] = frozenset()) -> None:  # noqa: B006
    out = w.all_out()
    logs = caplog.text
    spoken = spoken_by_friday(w)
    for name, blob in (("message", out), ("log", logs), ("spoken", spoken)):
        assert not PHONE.search(blob), f"a plain phone number reached a {name}"
        assert not CARD.search(blob), f"a card-like string reached a {name}"
        assert SECRET_FACT not in blob, f"a private fact reached a {name}"
        for tok in tokens:
            assert tok not in blob, f"a Google token reached a {name}"
    assert "Bearer " not in logs and "client_secret" not in logs and "refresh_token" not in out


async def test_call_flow_leaks_nothing(world: World, caplog):
    world.telephony.assign(MUMMY, "friendly_elder")
    world.telephony.assign(SIS, "voicemail_with_beep")
    await add_contact(world, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
    await add_contact(world, "Neha", SIS, nicknames=["neha"], relationship="friend")
    # a private fact the user asks us not to share, and a number typed in the message
    await world.say(
        f"mummy ko phone karke bata do ki main late hoon. mat batana salary {SECRET_FACT}"
    )
    approval = world.channel.last_to(world.phone)
    assert approval is not None and SECRET_FACT not in (approval.text or "")
    await world.tap("Approve")
    await world.run_jobs()
    await world.say(f"{SIS[3:]} ko phone karke bata do ki party hai")  # a typed number
    await world.say("Neha ko phone karke bata do ki kal party hai")
    await world.tap("Approve")
    for hours in (0, 1, 3):  # retries until it gives up
        await world.advance(hours=hours)
        await world.run_jobs()
    assert world.telephony.dialled.count(MUMMY) == 1 and world.telephony.dialled.count(SIS) == 3
    assert_clean(world, caplog)
    # the job payloads carry ids only
    for job in world.c.get("job_queue").jobs.values():
        assert not PHONE.search(str(job.payload))


async def test_wrong_number_and_opt_out_reports_leak_nothing(world: World, caplog):
    for persona in ("wrong_number", "stop_calling"):
        w = world
        w.telephony.assign(MUMMY, persona)
        if persona == "wrong_number":
            await add_contact(w, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
        else:
            await w.consumer.calls.orchestrator.dnc.delete(MUMMY)
        await w.say("mummy ko phone karke bata do ki main late hoon")
        await w.tap("Approve")
        await w.run_jobs()
    assert_clean(world, caplog)


async def test_savings_flow_leaks_no_card_number(world: World, caplog):
    r = await world.say(f"mere paas HDFC Regalia hai card {CARD_NUMBER} cvv 123")
    assert r and CARD_NUMBER.replace(" ", "") not in (r[-1].text or "").replace(" ", "")
    assert await world.consumer.savings.wallet.list(world.user.id) == []  # nothing stored
    await world.say("mere paas HDFC Regalia aur SBI Cashback hai")
    await world.say("Zomato pe 640")
    await world.say(
        "Electricity bill Rs 1,240.50 BSES due 25 Jan 2026. Account 1234567890123456, pay now"
    )
    assert_clean(world, caplog)


async def test_life_state_flow_leaks_no_private_text(world: World, caplog):
    await world.say(f"kal 2 baje interview hai, salary {SECRET_FACT} ki baat hogi")
    world.set_time(world.at(14, 30, day=6))
    await world.say("hello")
    summary = world.brain.contexts[-1].day_summary or ""
    assert SECRET_FACT not in summary and "salary" not in summary
    world.set_time(world.at(15, 45, day=6))
    await world.tick()
    await world.say("mera din")
    assert_clean(world, caplog)


async def test_google_flow_leaks_no_token(caplog):
    w = await make_world(google=True)
    try:
        assert w.fake_google is not None
        await w.say("google connect karo")
        await connect_user(w.consumer.google.oauth(), w.fake_google, w.user.id)
        await w.say("google status")
        await w.consumer.periodic()
        await w.say("google disconnect karo")
        tokens = w.fake_google.all_tokens_seen() | {
            "test-client-secret-value",
        }
        # the consent link is a one-time capability link, not a token: it is allowed in the chat
        assert_clean(w, caplog, tokens=tokens)
    finally:
        await close_world(w)


def test_the_detectors_do_catch_what_they_are_for():
    assert PHONE.search("call +919000000001 now") and PHONE.search("9000000001")
    assert CARD.search("card 4111 1111 1111 1111") and CARD.search("4111-1111-1111-1111")
    assert not PHONE.search("number ending 0001") and not PHONE.search("Rs 1,240.50")
    assert not CARD.search("2026-01-05 04:30:00")
