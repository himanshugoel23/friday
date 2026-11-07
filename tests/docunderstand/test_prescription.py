# ruff: noqa: E501
"""PRESCRIPTION type (T12): read with the fake reader, classified, handed to a sink at READ time, never stored here. Tested with fakes."""

from __future__ import annotations

import copy as _copy
from datetime import UTC, datetime

from friday.core.clock import FakeClock
from friday.core.scale import MemoryCache
from friday.docunderstand import copy
from friday.docunderstand.classify import classify
from friday.docunderstand.models import DocType
from friday.docunderstand.pipeline import DocLimits, DocumentPipeline
from friday.docunderstand.ports import FakeVision
from friday.docunderstand.prompts import EXTRACTION_INSTRUCTION
from friday.docunderstand.service import DocReply, DocumentService
from friday.docunderstand.store import MemoryDocStore
from tests.docunderstand import samples as S

NOW = datetime(2026, 10, 27, 5, 0, tzinfo=UTC)


async def _none_sink(user_id, doc):  # noqa: ANN001, ANN202
    return None


def service(sink=None):  # noqa: ANN001, ANN201
    clock = FakeClock(NOW)
    vision = FakeVision()
    store = MemoryDocStore()
    pipe = DocumentPipeline(vision, clock, MemoryCache(clock), DocLimits())
    return DocumentService(pipe, store, clock, prescription_sink=sink), store, vision


async def test_the_fake_reader_gives_a_prescription_with_the_four_fields():
    clock = FakeClock(NOW)
    pipe = DocumentPipeline(FakeVision(), clock, MemoryCache(clock), DocLimits())
    out = await pipe.process("u1", S.sample(S.PRESCRIPTION), "image/jpeg")
    assert out.kind == "extracted" and out.document is not None
    doc = out.document
    assert doc.doc_type == DocType.PRESCRIPTION
    assert set(doc.fields) == {"medicine", "dose_text", "times", "days"}
    assert doc.fields["medicine"].value == "Tab Zorvex; Tab Lumirel"
    assert doc.fields["days"].value == "30; 15"


def test_classification_by_layout_words_and_unrelated_types_are_unchanged():
    assert classify("Rx Tab Zorvex 5 mg 1-0-1 after food", None) == DocType.PRESCRIPTION
    assert classify("prescription", "prescription") == DocType.PRESCRIPTION
    assert classify(S.FLIGHT["text"], None) == DocType.FLIGHT  # a date like 2026-11-14 is not a 1-0-1 dose pattern
    assert classify("Booking confirmation 2026-11-14 hotel check-in 2026-11-17", None) == DocType.HOTEL
    assert classify("Amount due 1,240 due date 2026-11-20 bill", None) == DocType.BILL


def test_the_reader_instruction_names_the_type_and_forbids_advice():
    assert "prescription" in EXTRACTION_INSTRUCTION and "never interpret, correct or advise" in EXTRACTION_INSTRUCTION


async def test_a_prescription_is_handed_to_the_sink_and_never_stored_here():
    seen = []

    async def sink(user_id, doc):  # noqa: ANN001, ANN202
        seen.append((user_id, doc.doc_type, dict(doc.values())))
        return DocReply("confirm?")

    svc, store, vision = service(sink)
    out = await svc.handle_media("u1", "en", S.sample(S.PRESCRIPTION), "image/jpeg")
    assert out.text == "confirm?" and len(vision.calls) == 1
    assert seen and seen[0][1] == DocType.PRESCRIPTION and "Zorvex" in seen[0][2]["medicine"]
    assert await store.latest_open("u1") is None and await store.list_confirmed("u1") == []


async def test_no_sink_or_a_sink_that_says_no_refuses_and_keeps_nothing():
    for sink in (None, _none_sink):
        svc, store, _ = service(sink)
        out = await svc.handle_media("u1", "en", S.sample(S.PRESCRIPTION), "image/jpeg")
        assert out.text == copy.t("refuse.prescription", "en") and not out.buttons
        assert await store.latest_open("u1") is None


async def test_a_failing_sink_refuses_and_keeps_nothing():
    async def boom(user_id, doc):  # noqa: ANN001, ANN202
        raise RuntimeError("x")

    svc, store, _ = service(boom)
    out = await svc.handle_media("u1", "hinglish", S.sample(S.PRESCRIPTION), "image/jpeg")
    assert out.text == copy.t("refuse.prescription", "hinglish")
    assert await store.latest_open("u1") is None


async def test_other_documents_do_not_use_the_prescription_sink():
    calls = []

    async def sink(user_id, doc):  # noqa: ANN001, ANN202
        calls.append(1)
        return DocReply("x")

    svc, store, _ = service(sink)
    out = await svc.handle_media("u1", "en", S.sample(S.FLIGHT), "image/jpeg")
    assert not calls and out.buttons and await store.latest_open("u1") is not None


async def test_an_unreadable_prescription_is_not_routed():
    bad = _copy.deepcopy(S.PRESCRIPTION)
    bad["fields"] = {"medicine": "Tab Zorvex"}  # one field is below the minimum
    calls = []

    async def sink(user_id, doc):  # noqa: ANN001, ANN202
        calls.append(1)
        return DocReply("x")

    svc, _, _ = service(sink)
    out = await svc.handle_media("u1", "en", S.sample(bad), "image/jpeg")
    assert not calls and out.text == copy.t("refuse.unreadable", "en")


def test_prescription_lines_are_in_every_language_and_give_no_advice():
    for key in ("head.prescription", "refuse.prescription"):
        assert set(copy.TEXTS[key]) == set(copy.LANGS)
        for text in copy.TEXTS[key].values():
            assert not any(w in text.lower() for w in ("should take", "increase", "decrease", "safe to"))
