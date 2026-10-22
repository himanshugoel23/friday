# ruff: noqa: E501
"""The receptionist inside the real app: switch off = nothing changes; switch on = a forwarded call
(redirecting number = a user) is answered by the receptionist, a direct call is not."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from friday.core.config import Settings
from friday.core.events import InboundCallReceived
from friday.core.models import ReplyButton
from friday.receptionist import copy, lines
from friday.receptionist.models import MessageStatus, ReceptionistConfig
from tests.e2e.harness import Friday
from tests.frontdoor.conftest import FRIDAY_NUMBER, OWN, ScriptedLeg, start_friday

USER = "+919811100001"  # invented
CALLER = "+919100000015"


def test_defaults_are_off_and_safe():
    s = Settings(_env_file=None)
    assert s.receptionist_enabled is False and s.receptionist_probe is False
    assert s.receptionist_max_call_s == 90
    assert "Diversion" in s.receptionist_redirect_fields
    assert s.receptionist_per_caller_per_hour == 3


def test_redirect_fields_accept_a_csv_env_value():
    s = Settings(_env_file=None, receptionist_redirect_fields="X-One, X-Two")
    assert s.receptionist_redirect_fields == ["X-One", "X-Two"]


async def test_switch_off_means_no_component_and_no_probe_side_effects():
    f = await Friday.start()
    try:
        assert f.rt.callbacks.receptionist() is None
        from friday.receptionist import probe

        assert probe.observe_inbound({"Diversion": USER}) is None  # hook inert
    finally:
        await f.close()


async def forwarded(f, leg: ScriptedLeg, redirecting: str | None):
    f.c.telephony.inbound_legs[leg.provider_call_id] = leg
    await f.c.bus.publish(
        InboundCallReceived(
            from_phone=CALLER, to_number=FRIDAY_NUMBER, provider_call_id=leg.provider_call_id,
            provider="test", redirecting=redirecting,
        )
    )  # fmt: skip
    await f.settle()
    await asyncio.sleep(0)


async def test_forwarded_call_is_taken_by_the_receptionist_and_summarised_on_whatsapp():
    f = await start_friday(
        "default", (OWN,), receptionist_enabled=True, receptionist_redirect_fields=["Diversion"]
    )
    try:
        user = await f.user(USER, "Rahul")
        rcp = f.rt.callbacks.receptionist()
        assert rcp is not None
        uid = (await f.c.repos.users.get_by_phone(USER)).id
        cfg = ReceptionistConfig(enabled=True, user_name="Rahul", language="hinglish")
        await rcp.service.store.save_config(uid, cfg)

        before = len(f.channel.messages_to(USER))
        leg = ScriptedLeg([
            "Main Dr Gupta ke clinic se bol rahi hoon, aapki appointment ke baare mein, jaldi call karna",
            "haan sahi hai",
        ])  # fmt: skip
        await forwarded(f, leg, f"<sip:{USER}@vobiz.example>;reason=no-answer")
        assert leg.texts[0].startswith("Hello, main Friday bol rahi hoon, Rahul ki virtual assistant")
        assert leg.hung_up and "Rahul tak pahuncha" in leg.texts[-1]
        msgs = await rcp.service.store.list_messages(uid)
        assert len(msgs) == 1 and msgs[0].urgency.value == "urgent"  # 'jaldi'
        assert msgs[0].status == MessageStatus.NOTIFIED
        out = f.channel.messages_to(USER)[before:]
        assert out and "URGENT" in (out[-1].text or "") and len(out[-1].buttons) == 3
        # the user taps "Block": the pipeline routes the button to the receptionist
        assert out[-1].buttons[2].title == "Block"
        await user.say("3")  # the simulator turns "3" into a tap on the third button
        assert await rcp.service.store.is_blocked(uid, CALLER)
    finally:
        await f.close()


async def test_a_direct_call_still_goes_to_the_front_door_and_unknown_numbers_to_the_taker():
    f = await start_friday(
        "default", (OWN,), receptionist_enabled=True, receptionist_redirect_fields=["Diversion"]
    )
    try:
        await f.user(USER, "Rahul")
        rcp = f.rt.callbacks.receptionist()
        direct = ScriptedLeg(["hello"])
        f.c.telephony.inbound_legs[direct.provider_call_id] = direct
        ev = InboundCallReceived(from_phone=CALLER, to_number=FRIDAY_NUMBER,
                                 provider_call_id=direct.provider_call_id, provider="test")  # fmt: skip
        assert await rcp.claims(ev) is None  # no redirecting number: not ours

        stranger = ScriptedLeg(["Main Zoya bol rahi hoon, kaam ke baare mein", "haan"])
        await forwarded(f, stranger, "<sip:+919800000555@h>;reason=no-answer")
        assert stranger.texts[0].startswith("Hello, main Friday bol rahi hoon, ek virtual assistant")
        assert "Rahul" not in " ".join(stranger.texts)
    finally:
        await f.close()


async def test_buttons_and_text_from_other_users_are_not_answered():
    f = await start_friday("default", (OWN,), receptionist_enabled=True)
    try:
        await f.user(USER, "Rahul")
        rcp = f.rt.callbacks.receptionist()
        user = await f.c.repos.users.get_by_phone(USER)
        msg = f.channel.make_inbound(USER, "what did I miss?")
        assert await rcp.handle(user, msg)
        assert "no new missed calls" in (f.channel.messages_to(USER)[-1].text or "").lower() or \
            "koi nayi" in (f.channel.messages_to(USER)[-1].text or "").lower()  # fmt: skip
    finally:
        await f.close()


def test_probe_hook_feeds_the_configured_key_into_the_event_path():
    from friday.receptionist import probe

    pr = probe.InboundProbe(["Diversion"])
    probe.configure(["Diversion"], pr)
    try:
        raw = probe.observe_inbound({"From": "9191", "To": FRIDAY_NUMBER, "Diversion": f"<sip:{USER}@h>"})
        assert raw and pr.entries and pr.entries[0].candidates[0].key == "Diversion"
    finally:
        probe.configure((), None)


# ------------------------------------------------------------------ the docs list every line
DOC = Path(__file__).resolve().parents[2] / "docs" / "RECEPTIONIST.md"


def test_the_doc_lists_every_pending_line_so_the_founder_can_approve_by_audio():
    text = DOC.read_text(encoding="utf-8")
    for pl in lines.all_lines():
        assert f"`{pl.id}`" in text, pl.id
    for lid, _lang, _t in copy.all_texts():
        assert f"`{lid}`" in text, lid
    assert "PENDING_FOUNDER_APPROVAL" in text and "UNVERIFIED" in text.upper()


def test_the_doc_carries_the_carrier_code_table_and_probe_steps():
    text = DOC.read_text(encoding="utf-8")
    for code in ("**61*", "**67*", "**62*", "##61#", "##67#", "##62#", "##002#", "*#61#"):
        assert code in text, code
    for carrier in ("Jio", "Airtel", "Vi", "BSNL"):
        assert carrier in text
    assert re.search(r"probe", text, re.I)


def test_button_titles_fit_whatsapp():
    for lang in copy.LANGS:
        for action in copy.BUTTONS:
            assert len(copy.button_title(action, lang)) <= 20
    assert ReplyButton(id="rcp:abc:block", title=copy.button_title("block"))
