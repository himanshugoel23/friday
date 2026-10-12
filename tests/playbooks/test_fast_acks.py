"""Short polite replies are understood by rules, so no ~2 s model call happens on the phone."""

import pytest

from friday.playbooks.intents import Intent
from friday.playbooks.understand import heuristic

REPLIES = [
    "हाँ जी बताइए।", "haan ji bataiye", "Haan ji, boliye sir", "जी बोलिए", "हां बोलिए",
    "ji haan boliye", "kya kaam hai", "boliye", "yes tell me",
]


@pytest.mark.parametrize("reply", REPLIES)
def test_invitation_to_speak_is_confident_continue(reply):
    u = heuristic(reply, step="S0")
    assert u.confident and u.intent in (Intent.CONTINUE.value, Intent.YES.value)


def test_a_longer_sentence_still_goes_to_the_model():
    assert not heuristic("haan ji bataiye aapko kya chahiye", step="S0").confident
