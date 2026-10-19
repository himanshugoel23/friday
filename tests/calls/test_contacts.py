"""Contact book: nicknames, ambiguity, confirm-the-number-back, per-user isolation."""

from __future__ import annotations

import pytest

from friday.calls.contacts import ContactBook, MemoryContactStore
from friday.calls.numbers import NumberHasher
from tests.calls.conftest import MUMMY, PLUMBER, make_cipher

U1, U2 = "user-1", "user-2"


def book() -> ContactBook:
    return ContactBook(MemoryContactStore(), NumberHasher(make_cipher()))


async def test_nickname_and_relationship_resolution():
    b = book()
    c = await b.add(U1, "Sunita Goel", MUMMY, nicknames=["Mummy", "Maa"], relationship="mother")
    for ref in ("mummy", "Mummy ji", "maa", "mom", "Sunita"):
        r = await b.resolve(U1, ref)
        assert r.status == "found" and r.contact.id == c.id, ref


async def test_relationship_word_matches_without_a_nickname():
    b = book()
    await b.add(U1, "Sunita Goel", MUMMY, relationship="mother")
    assert (await b.resolve(U1, "mummy")).status == "found"


async def test_ambiguous_names_ask_with_last_four_digits_only():
    b = book()
    await b.add(U1, "Rakesh Sharma", "+919000000011")
    await b.add(U1, "Anil Sharma", "+919000000022")
    r = await b.resolve(U1, "Sharma ji")
    assert r.status == "ambiguous" and len(r.candidates) == 2
    question = b.ask_which("Sharma ji", r.candidates)
    assert "…0011" in question and "…0022" in question
    assert "9000000011" not in question


async def test_exact_name_beats_partial():
    b = book()
    await b.add(U1, "Rakesh Sharma", "+919000000011")
    await b.add(U1, "Sharma", "+919000000022")
    assert (await b.resolve(U1, "Sharma")).contact.number == "+919000000022"


async def test_unknown_name_is_none_and_typed_number_needs_confirmation():
    b = book()
    assert (await b.resolve(U1, "plumber")).status == "none"
    r = await b.resolve(U1, "90000 00002")
    assert r.status == "number" and r.number == PLUMBER and r.needs_confirmation
    assert (await b.resolve(U1, "12345")).status == "invalid"
    assert (await b.resolve(U1, "112")).status == "invalid"  # never a contact


async def test_confirm_back_flow():
    b = book()
    c = await b.add(U1, "Plumber", PLUMBER)
    r = await b.resolve(U1, "plumber")
    assert r.needs_confirmation and not c.confirmed
    text = b.confirm_number_back(c.name, c.number)
    assert "0002" in text and PLUMBER not in text
    await b.confirm(U1, c.id)
    assert not (await b.resolve(U1, "plumber")).needs_confirmation


async def test_book_is_per_user():
    b = book()
    c = await b.add(U1, "Mummy", MUMMY, relationship="mother")
    assert (await b.resolve(U2, "mummy")).status == "none"
    assert await b.store.get(U2, c.id) is None
    assert await b.confirm(U2, c.id) is None
    assert not await b.remove(U2, c.id)
    assert await b.remove(U1, c.id)


async def test_same_number_updates_instead_of_duplicating():
    b = book()
    a = await b.add(U1, "Maa", MUMMY, confirmed=True)
    again = await b.add(U1, "Mummy", MUMMY, nicknames=["mummy"], relationship="mother")
    assert again.id == a.id and again.confirmed and len(await b.store.list_for_user(U1)) == 1


async def test_cannot_save_emergency_or_junk():
    b = book()
    for bad in ("112", "100", "abc", "12345"):
        with pytest.raises(ValueError):
            await b.add(U1, "x", bad)


def test_repr_hides_the_number():
    import asyncio

    b = book()
    c = asyncio.run(b.add(U1, "Mummy", MUMMY))
    assert "9000000001" not in repr(c)
