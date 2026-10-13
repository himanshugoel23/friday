"""Shared engine pieces for the new scripts: phone capture, negotiation prices, resume seeding."""

from __future__ import annotations

from friday.playbooks.engine import CallState, _digits, _seed_from_prior, _within
from friday.playbooks.intents import CONDITIONS, FACT_INPUTS, Intent
from friday.playbooks.understand import extract_phone, heuristic


def test_phone_is_taken_from_digits_only():
    assert extract_phone("mera number 98111 22334 hai") == "9811122334"
    assert extract_phone("+91 98111-22334") == "9811122334"
    assert extract_phone("account 123456789012") is None  # a longer run is not a mobile number
    assert extract_phone("nau aath ek ek ek") is None  # words are never guessed


def test_a_number_is_only_taken_where_the_script_asked_for_one():
    ask = {"extended": True, "allowed": [Intent.GIVES_NUMBER.value, Intent.SAME_NUMBER.value]}
    u = heuristic("98111 22334", step="S_wa", known=ask)
    assert u.intent == Intent.GIVES_NUMBER.value and u.phone == "9811122334"
    assert heuristic("yahi number hai", step="S_wa", known=ask).intent == "SAME_NUMBER"
    other = {"extended": True, "allowed": [Intent.GIVES_PRICE.value]}
    assert heuristic("98111 22334", step="S3", known=other).intent != "GIVES_NUMBER"


def test_price_limits():
    assert _digits("Rs 22,000") == 22000 and _digits("") is None
    assert _within(21000, "22000") and not _within(23000, "22000") and not _within(None, "1")


def test_resume_seeds_the_answers_already_given():
    st = CallState.__new__(CallState)
    st.price_inr = st.estimate_inr = st.slot_free = None
    st.times, st.notes, st.flags = [], {}, {}
    _seed_from_prior(
        st,
        {"resume": "yes", "prior_price_inr": "400", "prior_slot_free": "no",
         "prior_slot": "kal shaam 5 baje", "prior_notes": '{"batch_note": "subah 7 baje"}'},
    )
    assert st.price_inr == 400 and st.slot_free == "no" and st.times == ["kal shaam 5 baje"]
    assert st.notes == {"batch_note": "subah 7 baje"}
    st2 = CallState.__new__(CallState)
    st2.price_inr = None
    _seed_from_prior(st2, {"prior_price_inr": "400"})  # no resume flag: nothing is carried in
    assert st2.price_inr is None


def test_every_fact_has_a_condition():
    assert all(f"has_{f}" in CONDITIONS for f in FACT_INPUTS)
    assert {"is_resume", "price_le_target", "price_le_max", "alt_offered"} <= CONDITIONS
