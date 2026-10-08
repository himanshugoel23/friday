"""Consent message: terms + privacy links and the grievance contact, calm, no emoji."""

from __future__ import annotations

import re

import pytest

from friday.brain.heuristics.onboarding import LegalLinks, onboarding_turn
from friday.core.config import Settings
from friday.core.models import Language, OnboardingStep

LINKS = LegalLinks(
    "https://friday.in/terms", "https://friday.in/privacy", "grievance@friday.in", "A. Rao"
)
EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿⭐✅⚠️]")


@pytest.mark.parametrize("lang", [Language.EN, Language.HI, Language.HINGLISH])
def test_consent_has_links_and_grievance_contact_in_every_language(ctx, lang):
    ctx.profile.language = lang
    turn, _ = onboarding_turn(ctx, OnboardingStep.CONSENT, None, LINKS)
    for needle in ("https://friday.in/terms", "https://friday.in/privacy", "grievance@friday.in",
                   "A. Rao"):
        assert needle in turn.reply
    assert "friday.example" not in turn.reply and not EMOJI.search(turn.reply)
    assert len(turn.reply) < 700
    assert [b.id for b in turn.buttons] == ["ob:consent:yes", "ob:consent:no"]
    if lang == Language.HI:
        assert re.search("[ऀ-ॿ]", turn.reply)


def test_unset_links_are_left_out_never_invented(ctx):
    turn, _ = onboarding_turn(ctx, OnboardingStep.CONSENT, None, LegalLinks())
    assert "http" not in turn.reply and "@" not in turn.reply
    turn, _ = onboarding_turn(ctx, OnboardingStep.CONSENT, None)
    assert "http" not in turn.reply


async def test_brain_reads_links_from_settings(brain, ctx):
    brain.settings = Settings(
        _env_file=None, terms_url="https://t.in/x", privacy_url="https://t.in/p",
        grievance_email="g@t.in",
    )
    turn = await brain.onboarding_turn(ctx, OnboardingStep.CONSENT, None)
    assert "https://t.in/x" in turn.reply and "https://t.in/p" in turn.reply and "g@t.in" in turn.reply
