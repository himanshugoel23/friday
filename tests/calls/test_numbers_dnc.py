"""Number helpers and the global do-not-call registry: hashing, isolation, opt-out detection."""

from __future__ import annotations

import json

import pytest

from friday.calls.dnc import (
    DncRegistry,
    MemoryDncStore,
    detect_opt_out,
    detect_wrong_number,
)
from friday.calls.numbers import NumberHasher, canonical, is_emergency
from friday.core.clock import FakeClock
from tests.calls.conftest import MUMMY, PLUMBER, make_cipher


def test_canonical_forms():
    assert canonical("90000 00001") == MUMMY
    assert canonical("090000 00001") == MUMMY
    assert canonical("+91-90000-00001") == MUMMY
    assert canonical("whatsapp:+919000000001") == MUMMY
    assert canonical("1800 123 4567") == "+9118001234567"
    assert canonical("112") is None and canonical("") is None and canonical("abc") is None


@pytest.mark.parametrize("raw", ["112", "+91 112", "0091 100", "1098", "01091", "tel:+91-108"])
def test_emergency_variants(raw):
    assert is_emergency(raw)


@pytest.mark.parametrize("raw", [MUMMY, "+911800123456", "1123456789", "+919810011223"])
def test_real_numbers_are_not_emergency(raw):
    assert not is_emergency(raw)


def _registry(seed=b"a"):
    store = MemoryDncStore()
    return DncRegistry(store, NumberHasher(make_cipher(seed)), FakeClock()), store


async def test_registry_stores_only_a_keyed_hash():
    reg, store = _registry()
    assert await reg.add("+91 90000 00001", "opt_out_call", source="req:abc")
    assert not await reg.add(MUMMY, "opt_out_call")  # second time: already there
    blob = json.dumps([vars(e) | {"created_at": str(e.created_at)} for e in store.rows.values()])
    assert "9000000001" not in blob and "0001" not in blob.replace("req:abc", "")
    (h,) = store.rows
    assert len(h) == 64 and h == NumberHasher(make_cipher()).hash(MUMMY)


async def test_same_number_any_spelling_is_blocked_other_numbers_are_not():
    reg, _ = _registry()
    await reg.add(MUMMY, "wrong_person")
    for form in (MUMMY, "090000 00001", "+91 90000-00001", "whatsapp:+919000000001"):
        assert await reg.is_blocked(form)
    assert not await reg.is_blocked(PLUMBER)
    assert not await reg.is_blocked("garbage")


async def test_hash_depends_on_the_secret_key():
    a, store_a = _registry(b"a")
    b, _ = _registry(b"b")
    await a.add(MUMMY, "opt_out_call")
    # a registry keyed differently cannot read the other's table: no cross-deployment lookup
    b.store = store_a
    assert not await b.is_blocked(MUMMY)


async def test_isolated_from_user_data():
    """The registry has no user dimension: a user's erasure never touches it, nothing in an entry
    names a user."""
    reg, store = _registry()
    await reg.add(MUMMY, "opt_out_call", source="req:xyz")
    entry = next(iter(store.rows.values()))
    assert set(vars(entry)) == {"number_hash", "reason", "source", "created_at"}


async def test_export_and_delete_for_the_number_owner():
    reg, _ = _registry()
    assert await reg.export(MUMMY) == []
    await reg.add(MUMMY, "opt_out_call")
    (row,) = await reg.export(MUMMY)
    assert row["reason"] == "opt_out_call" and "9000000001" not in json.dumps(row)
    assert await reg.delete(MUMMY) and not await reg.is_blocked(MUMMY)
    assert not await reg.delete(MUMMY)


async def test_unknown_reason_and_bad_number():
    reg, _ = _registry()
    with pytest.raises(ValueError):
        await reg.add(MUMMY, "because")
    assert await reg.add("112", "opt_out_call") is False  # never a valid dial target anyway


@pytest.mark.parametrize(
    "text",
    [
        "mujhe dobara call mat karo",
        "Please do not call me again",
        "stop calling this number",
        "call mat karna dobara",
        "mera number hata do list se",
        "dobara phone na karein",
        "I'm on DND, remove my number",
        "फोन मत करो",
    ],
)
def test_opt_out_phrases(text):
    assert detect_opt_out(text)


@pytest.mark.parametrize(
    "text", ["haan boliye", "main busy hoon, shaam ko call karna", "kaun bol raha hai", "ok thanks"]
)
def test_normal_speech_is_not_an_opt_out(text):
    assert not detect_opt_out(text)


def test_wrong_number_phrases():
    assert detect_wrong_number("yeh wrong number hai")
    assert detect_wrong_number("galat number lag gaya aapka")
    assert not detect_wrong_number("haan main bol raha hoon")
