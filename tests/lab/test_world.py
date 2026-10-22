"""The lab's world without HTTP: inbound message kinds, tracing hygiene, the CLI link."""

from __future__ import annotations

import pytest

from friday.core.models import MessageKind
from friday.lab.cli import lab_url
from friday.lab.world import LabError, LabWorld
from tests.lab.conftest import RAHUL


@pytest.fixture
async def world(tmp_path):
    w = await LabWorld.create(notes_path=tmp_path / "notes.jsonl")
    try:
        yield w
    finally:
        await w.close()


async def test_attachments_build_the_simulator_inbound_kinds(world):
    loc = world.inbound_location(RAHUL, 12.9716, 77.5946)
    assert loc.kind == MessageKind.LOCATION
    assert (loc.location.lat, loc.location.lng) == (12.9716, 77.5946)

    card = world.inbound_contact(RAHUL, "Neha", "+919000000010")
    assert card.kind == MessageKind.CONTACT
    assert card.contact_phone == "+919000000010" and card.text == "Neha"

    voice = world.inbound_voice(RAHUL, "mera din")
    assert voice.kind == MessageKind.VOICE_NOTE and voice.media_mime == "audio/ogg"
    blob = await world.channel.fetch_media(voice.media_url)  # what the fake STT will read
    assert blob.data == b"mera din"

    pdf = world.inbound_sample(RAHUL, "electricity-bill.pdf")
    assert pdf.kind == MessageKind.DOCUMENT and pdf.media_mime == "application/pdf"
    img = world.inbound_sample(RAHUL, "restaurant-receipt.jpg")
    assert img.kind == MessageKind.IMAGE and img.media_mime == "image/jpeg"

    up = world.inbound_file(RAHUL, "scan.pdf", "application/pdf", b"%PDF-1.4 fake")
    assert up.kind == MessageKind.DOCUMENT
    assert (await world.channel.fetch_media(up.media_url)).data == b"%PDF-1.4 fake"
    with pytest.raises(LabError):
        world.inbound_file(RAHUL, "big.png", "image/png", b"0" * (5 * 1024 * 1024 + 1))
    with pytest.raises(LabError):
        world.inbound_contact(RAHUL, "Real", "+919876543210")


async def test_a_typed_slash_command_behaves_like_the_simulator(world):
    assert world.inbound_text(RAHUL, "/pin 28.4,77.0").kind == MessageKind.LOCATION
    assert world.inbound_text(RAHUL, "/voice hello").kind == MessageKind.VOICE_NOTE
    assert world.inbound_text(RAHUL, "/doc bill.pdf").kind == MessageKind.DOCUMENT


async def test_the_probes_are_removed_when_the_world_closes(tmp_path):
    from friday.integration import copy as integration_copy
    from friday.integration import router as router_mod
    from friday.lifestate import copy as life_copy

    before = (
        integration_copy.line,
        life_copy.confirm_event,
        router_mod.capture_message,
        router_mod.parse_purchase,
    )
    w = await LabWorld.create(notes_path=tmp_path / "n.jsonl")
    assert life_copy.confirm_event is not before[1]  # wrapped while the lab runs
    await w.close()
    after = (
        integration_copy.line,
        life_copy.confirm_event,
        router_mod.capture_message,
        router_mod.parse_purchase,
    )
    assert after == before


async def test_the_product_still_works_if_a_probe_breaks(world, monkeypatch):
    """A tracing bug must never change what the user gets."""
    from friday.lab import trace

    monkeypatch.setattr(trace, "_short", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(trace, "finish_trace", lambda t: None)
    msg = world.inbound_text(RAHUL, "mausam kaisa hai")  # goes through the brain probe
    t = await world.send_inbound(RAHUL, msg, "x")
    assert t["outputs"] and t["outputs"][0]["text"]


async def test_new_users_get_fresh_invented_numbers(world):
    a, b = await world.new_user(), await world.new_user()
    assert a.phone != b.phone and a.saved is False
    for u in (a, b):
        assert world.clean_phone(u.phone) == u.phone
    assert [u.key for u in world.users[:3]] == ["rahul", "priya", "sunita"]


def test_lab_url_accepts_the_public_url_with_or_without_the_lab_path():
    assert lab_url("http://127.0.0.1:8766", "T") == "http://127.0.0.1:8766/lab/T/"
    assert lab_url("https://host.example/", "T") == "https://host.example/lab/T/"
    assert lab_url("https://host.example/lab", "T") == "https://host.example/lab/T/"
