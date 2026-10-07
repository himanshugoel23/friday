"""AI-11 extraction (+ batch), AI-12 translate, AI-13 simulated business."""

from __future__ import annotations

import os

import pytest

from friday.brain.extraction import LLMDocumentExtractor, build_document_extractor
from friday.brain.fake_llm import FakeLLM
from friday.brain.sim_business import simulate_business_reply
from friday.core.container import Container
from friday.core.interfaces import DocumentExtractor
from friday.core.models import ExtractionKind, Language, MediaBlob, Speaker, Transcript
from friday.simworld import load_world

MENU = """Spice Route Menu
Paneer Tikka - 280
Dal Makhani : 240
Butter Naan .. 60 per piece
"""


async def test_extractor_conforms_and_parses_text_menu(brain_settings):
    ex = build_document_extractor(Container(brain_settings))
    assert isinstance(ex, DocumentExtractor)
    doc = await ex.extract(MediaBlob(data=MENU.encode(), mime="text/plain", filename="menu.txt"))
    assert doc.kind == ExtractionKind.MENU
    assert [(i.name, i.amount_inr) for i in doc.items] == [
        ("Paneer Tikka", 280), ("Dal Makhani", 240), ("Butter Naan", 60)]
    assert doc.items[2].unit == "per piece"


async def test_extractor_from_filename_metadata():
    ex = LLMDocumentExtractor(FakeLLM())
    doc = await ex.extract(MediaBlob(data=b"\xff\xd8jpeg", mime="image/jpeg",
                                     filename="coolcare_quote_699.jpg"))
    assert doc.kind == ExtractionKind.QUOTE and doc.quote.amount_inr == 699
    assert doc.business_name == "Coolcare"
    again = await ex.extract(MediaBlob(data=b"\xff\xd8jpeg", mime="image/jpeg",
                                       filename="coolcare_quote_699.jpg"))
    assert again == doc  # deterministic


async def test_extractor_sends_images_as_attachments():
    llm = FakeLLM()
    await LLMDocumentExtractor(llm).extract(MediaBlob(data=b"x", mime="image/png",
                                                      filename="menu.png"))
    call = llm.calls_for("extract")[-1]
    assert call.attachments and call.model == "claude-haiku-5-5"
    assert "untrusted" in call.system.lower()


async def test_batch_extraction_path():
    llm = FakeLLM()
    ex = LLMDocumentExtractor(llm)
    batch_id = await ex.submit_batch({
        "a": (MediaBlob(data=MENU.encode(), mime="text/plain", filename="menu.txt"),
              ExtractionKind.MENU, ""),
        "b": (MediaBlob(data=b"x", mime="image/jpeg", filename="movers_quote_18500.jpg"),
              ExtractionKind.QUOTE, "packers quote")})
    docs = await ex.collect_batch(batch_id)
    assert docs["a"].items[0].amount_inr == 280 and docs["b"].quote.amount_inr == 18500


@pytest.mark.live
async def test_live_vision_extraction():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    from friday.core.config import Settings

    ex = build_document_extractor(Container(Settings()))
    doc = await ex.extract(MediaBlob(data=MENU.encode(), mime="text/plain", filename="m.txt"))
    assert doc.items


# ------------------------------------------------------------------ translate


@pytest.mark.parametrize(("text", "target", "source", "expect"), [
    ("Kal subah 10 baje room khaali hai, 3500 per raat", Language.EN, Language.HINGLISH,
     "tomorrow morning 10 o'clock a room is available, 3500 per night"),
    ("Is breakfast included? Thank you", Language.HINGLISH, Language.EN,
     "Is nashta included?"),
    ("कमरा खाली है", Language.EN, Language.HI, "a room is available"),
    ("Namaskar, udya sakali room aahe", Language.HINGLISH, Language.MR,
     "namaste, kal subah room hai"),
])
async def test_translate_fake(brain, text, target, source, expect):
    out = await brain.translate(text, target=target, source=source)
    assert out.lower().startswith(expect.lower()[:12])
    for num in ("10", "3500"):
        if num in text:
            assert num in out


async def test_translate_keeps_numbers_even_if_llm_drops_them(brain, fake_llm):
    fake_llm.script("translate", {"text": "The room costs some money"})
    out = await brain.translate("Room 3500 ka hai", target=Language.EN,
                                source=Language.HINGLISH)
    assert "3500" in out


async def test_brain_is_a_translator(brain):
    from friday.core.interfaces import Brain, CallPolicy, Translator

    assert isinstance(brain, Translator) and isinstance(brain, CallPolicy)
    assert isinstance(brain, Brain)


# ------------------------------------------------------------------ simulated business


async def test_sim_business_is_deterministic_persona():
    world = load_world()
    salon = world.by_id("sim-looks-salon")
    tr = Transcript()
    llm = FakeLLM()
    greet = await simulate_business_reply(llm, salon, tr)
    assert greet.text == "Hello, Looks salon, boliye"
    tr.add(Speaker.CALLEE, greet.text)
    tr.add(Speaker.FRIDAY, "Saturday haircut ke liye slot available hai?")
    r1 = await simulate_business_reply(llm, salon, tr)
    r2 = await simulate_business_reply(llm, salon, tr)
    assert r1 == r2 and "4pm" in r1.text
    ac = world.by_id("sim-cool-ac")
    t2 = Transcript()
    t2.add(Speaker.CALLEE, "Hello")
    t2.add(Speaker.FRIDAY, "Could you do 600? Thoda discount?")
    r = await simulate_business_reply(llm, ac, t2)
    assert "629" in r.text  # 699 - 10%
