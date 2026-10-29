# ruff: noqa: E501
"""Problems found in the first live chat: (i) 'Hi' got the salon-service question, (ii) a failed lookup leaked 'no_result'.
Chat Lab world with fakes (no network, no real LLM)."""

from __future__ import annotations

import pytest

from friday.evidence import action_proof as ap
from friday.lab.world import LabWorld
from friday.replywriter import status_words as sw
from friday.style import check
from tests.evidence.test_action_proof import NOW, MemoryEvidenceStore, adapt

PHONE = "+919800000001"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for n in ("FRIDAY_MODE", "FRIDAY_PROFILE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "FRIDAY_LLM_PROVIDER"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.chdir("/")


async def talk(tmp_path, *messages: str) -> list[str]:
    w = await LabWorld.create(notes_path=tmp_path / "n.jsonl", overrides={})
    try:
        out = []
        for m in messages:
            turn = await w.send_inbound(PHONE, w.inbound_text(PHONE, m), m)
            out.append("\n".join(o["text"] or "" for o in turn.get("outputs") or []))
        return out
    finally:
        await w.close()


async def test_hi_is_a_warm_general_opener_not_a_service_menu(tmp_path):
    (reply,) = await talk(tmp_path, "Hi")
    assert reply.startswith("Hi Rahul!") and "Main Friday hoon" in reply  # name + who she is
    assert reply.rstrip().endswith("Aaj aapke liye kya karun?")  # exactly one open question
    low = reply.lower()
    assert "khana" in low and "shopping" in low and ("call" in low and "reminder" in low and "trip" in low)  # buckets across food / shopping / calls / travel / reminders
    assert not any(w in low for w in ("haircut", "beard", "facial", "waxing", "kaunsi service"))
    assert check.check(reply, kind="text") == []  # 5 lines, one question, no header


async def test_an_open_parlour_question_does_not_swallow_a_greeting(tmp_path):
    asked, greeting, answer = await talk(tmp_path, "parlour jana hai", "Hi", "haircut")
    assert asked.startswith("Kaunsi service chahiye")
    assert "Kaunsi service chahiye" not in greeting and greeting.startswith("Hi Rahul!")  # the root cause of the live bug
    assert "Kaunsi service chahiye" not in answer  # the open question stayed open: the answer moved the flow on


def test_internal_codes_have_plain_words_in_both_languages():
    for code in sw.WHAT:
        for lang in ("en", "hinglish"):
            text = sw.what_happened(code, lang)
            assert text and not sw.is_code(text)
    assert sw.what_happened("no_result", "en") == "I could not read live prices"
    assert sw.what_happened("lookup:blocked", "en") == "The site blocked us"
    assert "page looked different" in sw.what_happened("layout_changed", "en") and "location" in sw.what_happened("location_rejected", "en")
    assert sw.humanize("lookup no_result", "en") == "i could not read live prices"
    assert sw.what_happened("something_new", "en") == "I could not finish this"  # unknown codes get a safe sentence


@pytest.mark.parametrize("lang", ["en", "hinglish"])
@pytest.mark.parametrize("status", ["no_result", "blocked", "timeout", "unavailable", "layout_changed", "location_rejected"])
async def test_failed_proof_card_starts_with_what_happened_in_plain_words_and_never_shows_a_code(lang, status):
    msg = await ap.ProofService(MemoryEvidenceStore()).record(adapt({"status": status, "seen": f"lookup {status}"}, kind="lookup"), now=NOW, lang=lang)
    first = msg.text.splitlines()[0]
    assert first == sw.what_happened(status, lang) + "."  # starts with what happened
    assert not sw.is_code(msg.text) and "lookup" not in msg.text.lower()  # no snake_case code, no 'lookup:x'
    assert "_" not in status or status not in msg.text
    assert "Next:" in msg.text or "Aage:" in msg.text  # and says what Friday can do next
    assert check.check(msg.text, kind="proof") == []
    assert not sw.is_code(msg.items[0].payload.get("seen", ""))  # the stored evidence has no code either

