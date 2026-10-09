"""The loader/validator rejects bad playbooks and accepts the shipped one."""

from __future__ import annotations

import copy
import json
import re

import pytest

from friday.playbooks.intents import INTENTS
from friday.playbooks.model import (
    PlaybookError,
    list_playbooks,
    load_playbook,
    validate_data,
)


def problems_of(data) -> str:
    with pytest.raises(PlaybookError) as e:
        validate_data(data)
    return " | ".join(e.value.problems)


def test_shipped_salon_playbook_is_valid(salon):
    assert salon.id == "salon_booking" and salon.version == 1 and salon.language == "hinglish"
    assert salon.warnings == []  # no unused lines
    # S1-S7, S2b, S3b from the founder draft (plus S2t "yes but no time" and S3r read-back)
    assert {"S1", "S2", "S2b", "S3", "S3b", "S4", "S5", "S6", "S7"} <= set(salon.steps)
    assert set(salon.outcomes) >= {
        "SLOT_OFFERED", "BOOKED", "NO_SLOT", "CALL_BACK_LATER", "WRONG_NUMBER", "UNCLEAR",
        "REFUSED", "NO_ANSWER",
    }


def test_yaml_yes_no_keys_are_not_booleans(salon):
    # plain YAML 1.1 turns YES/NO into True/False; the loader must not
    assert "YES" in salon.steps["S1"].branches and "NO" in salon.steps["S1"].branches


def test_every_intent_used_is_in_the_closed_set(salon):
    for _where, intent, _a in salon.all_actions():
        assert not intent or intent in INTENTS or intent == "ANY"


def test_every_line_is_roman_hinglish(salon):
    for lid in salon.lines:
        assert not re.search(r"[ऀ-ॿ]", salon.text(lid)), lid
        assert re.search(r"[A-Za-z]", salon.text(lid)), lid


def test_json_format_loads(tmp_path, raw):
    p = tmp_path / "x.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    assert load_playbook(p).id == "salon_booking"


def test_list_playbooks_reports_status(tmp_path, raw):
    (tmp_path / "ok.yaml").write_text(json.dumps(raw), encoding="utf-8")
    (tmp_path / "bad.yaml").write_text("version: 1\nid: x\n", encoding="utf-8")
    rows = {n: s for n, s, _d in list_playbooks(tmp_path)}
    assert rows == {"ok": "ok", "bad": "INVALID"}


@pytest.mark.parametrize(
    ("mutate", "expect"),
    [
        (lambda d: d["steps"]["S2"]["branches"].update({"MAYBE": {"goto": "S3"}}),
         "unknown intent 'MAYBE'"),
        (lambda d: d["steps"]["S2"]["branches"]["NO"].update({"say": ["no_such_line"]}),
         "missing line 'no_such_line'"),
        (lambda d: d["lines"].update({"s1_ask": "Aapka OTP bata dijiye?"}), "OTP/PIN/card"),
        (lambda d: d["lines"].update({"s5_ask": "Apna PIN bata dijiye"}), "OTP/PIN/card"),
        (lambda d: d["lines"].update({"s5_ask": "Card number bata dijiye"}), "OTP/PIN/card"),
        (lambda d: d["lines"].update({"s5_ask": "Debit card se advance de dungi"}), "OTP/PIN/card"),
        (lambda d: d["lines"].update({"s1_ask": "क्या मैं दो मिनट ले सकती हूँ?"}), "Devanagari"),
        (lambda d: d["lines"].update({"thanks": "Aapka appointment confirm ho gaya."}),
         "claims or asks for a booking"),
        (lambda d: d["lines"].update({"thanks": "Booking pakka ho gayi, shukriya."}),
         "claims or asks for a booking"),
        (lambda d: d["lines"].update({"s2_appt_only": "Theek hai, kal 6 baje book kar dijiye."}),
         "claims or asks for a booking"),
        (lambda d: d["lines"].update({"s1_ask": "I am a real human, can I have two minutes?"}),
         "claims to be human"),
        (lambda d: d["lines"].update({"s1_ask": "Kya main {nope} le sakti hoon?"}),
         "unknown placeholder"),
        (lambda d: d["lines"].update({"disclosure": "Namaste, main Friday hoon."}),
         "must say that Friday is an AI"),
        (lambda d: d["lines"].update({"s1_ask": "Bahut lamba " + "line " * 60}), "longer than"),
        (lambda d: d["steps"]["S2"]["branches"]["NO"].update({"goto": "S99"}),
         "unknown step 'S99'"),
        (lambda d: d["steps"]["S2"]["branches"]["NO"].update({"goto": "@nowhere"}),
         "unknown route"),
        (lambda d: d["steps"]["S2"]["branches"]["SLOT_BUSY"].update(
            {"goto": None, "outcome": "NOPE"}), "unknown outcome"),
        (lambda d: d["steps"]["S2"]["branches"]["SLOT_BUSY"].update({"when": ["moonphase"]}),
         "unknown condition"),
        (lambda d: d["steps"]["S2"]["branches"]["NO"].update({"outcome": "NO_SLOT"}),
         "exactly one of"),
        (lambda d: d.update({"language": "english"}), "language must be 'hinglish'"),
        (lambda d: d.update({"version": 2}), "unsupported or missing version"),
        (lambda d: d.update({"start": "S99"}), "start step"),
        (lambda d: d["steps"].update(
            {"S9": {"ask": ["s1_ask"], "branches": {"YES": {"goto": "S1"}}}}), "unreachable"),
        (lambda d: d["outcomes"]["NO_SLOT"].update({"call_outcome": "success"}),
         "only BOOKED"),
        (lambda d: d["outcomes"]["NO_SLOT"].update({"call_outcome": "weird"}),
         "unknown call_outcome"),
        (lambda d: d["lines"].update({"s7_commit": "Theek hai, kal 6 baje confirm kar dijiye."}),
         "marked commit"),
        (lambda d: d["steps"]["S5"]["branches"]["NO"].update(
            {"say": ["s7_commit"], "goto": "S6"}), "commit line may only be spoken"),
        (lambda d: d["steps"]["S5"]["branches"]["NO"].update({"commit": True}), "commit"),
        (lambda d: d["steps"]["S4"].pop("branches"), "no branches"),
        (lambda d: d["defaults"].update({"BAD_INTENT": {"outcome": "REFUSED"}}),
         "unknown intent"),
        (lambda d: d["steps"]["S7"]["branches"].pop("ANY"), "final step needs an ANY"),
        (lambda d: d["limits"].update({"unknown_limit": 3}), "unknown_limit"),
        (lambda d: d["steps"]["S2"]["branches"]["NO"].update({"set": {"price_inr": "1"}}),
         "cannot set"),
    ],
)
def test_loader_rejects(raw, mutate, expect):
    data = copy.deepcopy(raw)
    mutate(data)
    assert expect in problems_of(data)


def test_non_mapping_and_unparseable_files(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(PlaybookError):
        load_playbook(p)
    p.write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(PlaybookError):
        load_playbook(p)
    with pytest.raises(PlaybookError):
        load_playbook(tmp_path / "missing.yaml")


def test_all_problems_are_listed_not_just_the_first(raw):
    d = copy.deepcopy(raw)
    d["lines"]["s1_ask"] = "Apna OTP batao"
    d["steps"]["S2"]["branches"]["NO"]["goto"] = "S99"
    d["language"] = "english"
    with pytest.raises(PlaybookError) as e:
        validate_data(d)
    assert len(e.value.problems) >= 3


def test_negated_confirmation_lines_are_allowed(raw):
    d = copy.deepcopy(raw)
    d["lines"]["thanks"] = "Abhi kuch confirm nahi kiya, poochh kar aapko call karti hoon."
    assert validate_data(d)


def test_only_the_start_step_may_ask_nothing(raw):
    data = copy.deepcopy(raw)
    assert "ask" not in data["steps"]["S0"]  # the identity step waits for the salon's answer
    validate_data(data)  # fine as shipped
    data["steps"]["S2"]["ask"] = []
    assert "must ask something" in problems_of(data)


def test_a_silent_start_step_needs_a_disclosure_that_asks_the_question(raw):
    data = copy.deepcopy(raw)
    data["lines"]["disclosure"] = "Hello, main Friday, ek AI assistant, baat kar rahi hoon."
    assert "disclosure line itself ends in a question" in problems_of(data)
