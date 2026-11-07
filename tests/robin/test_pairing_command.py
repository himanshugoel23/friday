# ruff: noqa: E501
"""T08: the child's chat command "pair phone for papa" -> a one-time pairing code with plain instructions and a robin://pair link. The child
enters it on the parent's phone; the parent never types. Fakes only (a fake device service); the real single-use rules are tested in
tests/robindevice and, through the real device service, in tests/e2e/robin/test_child_commands.py."""

from __future__ import annotations

import re

import pytest

from friday.core.models import Channel, InboundMessage, MessageKind
from tests.robin.conftest import CHILD_PHONE


class FakeDevice:
    def __init__(self, fail=False):
        self.fail, self.made = fail, []

    async def create_pairing_code(self, parent_id):
        if self.fail:
            raise KeyError("unknown parent")
        code = f"K7M2QX9{len(self.made)}"
        self.made.append((parent_id, code))
        return code


async def say(w, fam, text):
    user = await w.ctx.users.get(fam.owner_user_id)
    msg = InboundMessage(channel=Channel.WHATSAPP, from_phone=CHILD_PHONE, kind=MessageKind.TEXT, text=text)
    n = len(w.sender.sent)
    handled = await w.hub.handle(user, msg)
    return handled, [s.text for s in w.sender.sent[n:]]


@pytest.mark.parametrize("words", ["pair phone for papa", "Pair phone for Papa", "pair the phone", "pair papa's phone", "please pair phone for my father", "papa ka phone jodo", "pair app"])
async def test_pair_phrases_give_a_code_with_instructions_and_a_link(w, words):
    fam, parent = await w.family()
    dev = FakeDevice()
    w.hub.device_service = dev
    handled, out = await say(w, fam, words)
    assert handled and len(out) == 1
    assert dev.made == [(parent.id, "K7M2QX90")]
    text = out[0]
    assert "K7M2QX90" in text and "robin://pair?code=K7M2QX90" in text  # the code and the deep link
    assert "15 minutes" in text or "15 minute" in text  # expiry stated
    assert "Papa" in text and "Robin" in text  # plain, branded instructions
    assert re.search(r"does not have to type|kuch type nahi", text)  # the parent never types
    assert "Do not share" in text or "mat dijiye" in text


async def test_each_command_makes_a_fresh_code_and_the_code_is_not_kept_in_the_audit_log(w):
    fam, parent = await w.family()
    dev = FakeDevice()
    w.hub.device_service = dev
    _, a = await say(w, fam, "pair phone for papa")
    _, b = await say(w, fam, "pair phone for papa")
    assert dev.made[0][1] != dev.made[1][1] and "K7M2QX90" in a[0] and "K7M2QX91" in b[0]
    blob = " ".join(r.data.get("text", "") for r in await w.store.list(fam.id, "audit"))
    assert "K7M2QX9" not in blob and "robin://" not in blob
    assert any(r.data.get("event") == "pair_code" for r in await w.store.list(fam.id, "audit"))  # but the fact is logged


async def test_pairing_off_says_so_and_makes_no_code(w):
    fam, parent = await w.family()
    w.hub.device_service = None  # the device package is not mounted
    handled, out = await say(w, fam, "pair phone for papa")
    assert handled and "not switched on" in out[0]


async def test_unknown_parent_on_the_device_side_is_reported_not_raised(w):
    fam, parent = await w.family()
    w.hub.device_service = FakeDevice(fail=True)
    handled, out = await say(w, fam, "pair phone for papa")
    assert handled and "not switched on" in out[0]


async def test_before_the_parent_number_is_known_the_child_is_told_to_finish_setup(w):
    fam = await w.hub.fam.create_family(w.child_user, parent_label="Papa", child_name="Asha", child_language="en")
    w.hub.device_service = FakeDevice()
    handled, out = await say(w, fam, "pair phone for papa")
    assert handled and "finish setting up" in out[0]


async def test_a_user_without_a_family_gets_the_setup_hint(w):
    user = w.child_user
    n = len(w.sender.sent)
    handled = await w.hub.handle(user, InboundMessage(channel=Channel.WHATSAPP, from_phone=CHILD_PHONE, kind=MessageKind.TEXT, text="pair phone for papa"))
    assert handled and "set up Robin for my father" in w.sender.sent[n].text


async def test_pair_is_a_chat_command_for_the_child_only_and_never_matches_other_sentences(w):
    fam, parent = await w.family()
    w.hub.device_service = FakeDevice()
    for words in ("pair of shoes please", "I want to pair my headphones", "repair phone", "what is a pair"):
        handled, _ = await say(w, fam, words)
        assert not handled, words
    assert w.hub.device_service.made == []


async def test_help_lists_the_new_commands(w):
    fam, parent = await w.family()
    _, out = await say(w, fam, "robin help")
    assert "pair phone for papa" in out[0] and "what is on" in out[0]
