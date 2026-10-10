"""The loader/validator rejects bad playbooks and accepts the shipped one."""

# ruff: noqa: E501

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
    # v6 flow: the price FIRST (S3, with the intro), then (book mode) the slot (S2), the fallback
    # day (S2f), "yes but no time" (S2t), alternatives (S2b), the owner-only discount ask (S3b),
    # stylist (S4) and the closes (S7 booking, S7q price check).
    assert set(salon.steps) == {"S0", "S2", "S2f", "S2t", "S2b", "S3", "S3b", "S4", "S7", "S7q"}
    assert set(salon.outcomes) >= {
        "QUOTE_COLLECTED", "SLOT_OFFERED", "BOOKED", "NO_SLOT", "CALL_BACK_LATER", "WRONG_NUMBER", "UNCLEAR",
        "REFUSED", "NO_ANSWER",
    }


def test_yaml_yes_no_keys_are_not_booleans(salon):
    # plain YAML 1.1 turns YES/NO into True/False; the loader must not
    assert "YES" in salon.steps["S0"].branches and "NO" in salon.steps["S0"].branches


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
        (lambda d: d["steps"]["S2t"]["branches"]["NO"].update({"say": ["no_such_line"]}),
         "missing line 'no_such_line'"),
        (lambda d: d["lines"].update({"intro": "Aapka OTP bata dijiye?"}), "OTP/PIN/card"),
        (lambda d: d["lines"].update({"s4_ask": "Apna PIN bata dijiye"}), "OTP/PIN/card"),
        (lambda d: d["lines"].update({"s4_ask": "Card number bata dijiye"}), "OTP/PIN/card"),
        (lambda d: d["lines"].update({"s4_ask": "Debit card se advance de dungi"}), "OTP/PIN/card"),
        (lambda d: d["lines"].update({"intro": "क्या मैं दो मिनट ले सकती हूँ?"}), "Devanagari"),
        (lambda d: d["lines"].update({"no_secrets": "Aapka appointment confirm ho gaya."}),
         "claims or asks for a booking"),
        (lambda d: d["lines"].update({"no_secrets": "Booking pakka ho gayi, shukriya."}),
         "claims or asks for a booking"),
        (lambda d: d["lines"].update({"s2_appt_only": "Theek hai, kal 6 baje book kar dijiye."}),
         "claims or asks for a booking"),
        (lambda d: d["lines"].update({"intro": "I am a real human, can I have two minutes?"}),
         "claims to be human"),
        (lambda d: d["lines"].update({"intro": "Kya main {nope} le sakti hoon?"}),
         "unknown placeholder"),
        (lambda d: (d.update({"ai_disclosure": "first"}),
                    d["lines"].update({"disclosure": "Namaste, main Friday hoon."})),
         "must say that Friday is an AI"),
        (lambda d: d["lines"].update({"intro": "Bahut lamba " + "line " * 60}), "longer than"),
        (lambda d: d["steps"]["S2t"]["branches"]["NO"].update({"goto": "S99"}),
         "unknown step 'S99'"),
        (lambda d: d["steps"]["S2t"]["branches"]["NO"].update({"goto": "@nowhere"}),
         "unknown route"),
        (lambda d: d["steps"]["S2t"]["branches"]["SLOT_BUSY"].update(
            {"goto": None, "outcome": "NOPE"}), "unknown outcome"),
        (lambda d: d["steps"]["S2t"]["branches"]["SLOT_BUSY"].update({"when": ["moonphase"]}),
         "unknown condition"),
        (lambda d: d["steps"]["S2t"]["branches"]["NO"].update({"outcome": "NO_SLOT"}),
         "exactly one of"),
        (lambda d: d.update({"language": "english"}), "language must be 'hinglish'"),
        (lambda d: d.update({"version": 2}), "unsupported or missing version"),
        (lambda d: d.update({"start": "S99"}), "start step"),
        (lambda d: d["steps"].update(
            {"S9": {"ask": ["s2_ask"], "branches": {"YES": {"goto": "S2"}}}}), "unreachable"),
        (lambda d: d["outcomes"]["NO_SLOT"].update({"call_outcome": "success"}),
         "only BOOKED"),
        (lambda d: d["outcomes"]["NO_SLOT"].update({"call_outcome": "weird"}),
         "unknown call_outcome"),
        (lambda d: d["lines"].update({"s7_commit_free": "Theek hai, kal 6 baje confirm kar dijiye."}),
         "marked commit"),
        (lambda d: d["steps"]["S4"]["branches"]["NO"].update(
            {"say": ["s7_commit_free"], "goto": "S7"}), "commit line may only be spoken"),
        (lambda d: d["steps"]["S4"]["branches"]["NO"].update({"commit": True}), "commit"),
        (lambda d: d["steps"]["S2"]["branches"]["YES"][0].pop("when"), "use_requested_time needs"),
        (lambda d: d["steps"]["S4"].pop("branches"), "no branches"),
        (lambda d: d["defaults"].update({"BAD_INTENT": {"outcome": "REFUSED"}}),
         "unknown intent"),
        (lambda d: d["steps"]["S7"]["branches"].pop("ANY"), "final step needs an ANY"),
        (lambda d: d["limits"].update({"unknown_limit": 3}), "unknown_limit"),
        (lambda d: d["steps"]["S2t"]["branches"]["NO"].update({"set": {"price_inr": "1"}}),
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
    d["lines"]["intro"] = "Apna OTP batao"
    d["steps"]["S2t"]["branches"]["NO"]["goto"] = "S99"
    d["language"] = "english"
    with pytest.raises(PlaybookError) as e:
        validate_data(d)
    assert len(e.value.problems) >= 3


def test_negated_confirmation_lines_are_allowed(raw):
    d = copy.deepcopy(raw)
    d["lines"]["no_secrets"] = "Abhi kuch confirm nahi kiya, poochh kar aapko call karti hoon."
    assert validate_data(d)


def test_only_the_start_step_may_ask_nothing(raw):
    data = copy.deepcopy(raw)
    assert "ask" not in data["steps"]["S0"]  # the identity step waits for the salon's answer
    validate_data(data)  # fine as shipped
    data["steps"]["S2"]["ask"] = []
    assert "must ask something" in problems_of(data)


def test_a_silent_start_step_needs_a_disclosure_that_asks_the_question(raw):
    data = copy.deepcopy(raw)
    data["ai_disclosure"] = "first"
    data["lines"]["disclosure"] = "Hello, main Friday, ek AI assistant, baat kar rahi hoon."
    assert "disclosure line itself ends in a question" in problems_of(data)


# ------------------------------------------------------------------ ai_disclosure: on_request
def test_the_salon_playbook_declares_on_request(raw, salon):
    assert raw["ai_disclosure"] == "on_request" and salon.ai_disclosure == "on_request"
    assert "AI" not in salon.text("disclosure") and "AI" not in salon.text("intro")
    assert "virtual assistant" in salon.text("intro") and "AI" in salon.text("ai_yes")
    assert salon.reintro == "reintro" and "AI" not in salon.text("reintro")


def test_on_request_demands_the_ai_answer_on_every_are_you_bot_branch(raw):
    for mutate, expect in [
        (lambda d: d["lines"].update({"ai_yes": "Haan ji, main {user_spoken} {honorific} ki assistant hoon."}), "must say AI"),
        (lambda d: d["defaults"]["ARE_YOU_BOT"].update({"max_uses": 2}), "never run out"),
        (lambda d: d["steps"]["S0"]["branches"]["ARE_YOU_BOT"].update({"say": ["reintro"]}), "must say AI"),
        (lambda d: d["steps"]["S3"]["branches"].update({"ARE_YOU_BOT": {"say": ["offscript"], "repeat": True}}), "must say AI"),
        (lambda d: d["steps"]["S3"]["branches"].update({"ARE_YOU_BOT": {"say": ["ai_yes"], "repeat": True, "max_uses": 1}}), "never run out"),
        (lambda d: d["steps"]["S3"]["branches"].update({"ARE_YOU_BOT": {"say": ["ai_yes"], "repeat": True, "when": ["mode_book"]}}), "must not depend on a condition"),
        (lambda d: d["defaults"].pop("ARE_YOU_BOT"), "needs a defaults.ARE_YOU_BOT"),
        (lambda d: d.pop("reintro"), "needs `reintro:`"),
        (lambda d: d["lines"].update({"reintro": "Main Friday hoon, insaan hoon main."}), "claim to be human"),
    ]:
        data = copy.deepcopy(raw)
        mutate(data)
        assert expect in problems_of(data), expect


@pytest.mark.parametrize("opening", [
    "Hello, kya {user_spoken} {honorific} ke liye appointment mil sakta hai?",
    "Hello, {user_spoken} ji ki taraf se, kya meri baat {business_name_spoken} se ho rahi hai?",
    "Hello, kya meri baat {business_name_spoken} se ho rahi hai? Haircut ke liye.",
    "Hello, kya meri baat {business_name_spoken} se ho rahi hai",
    "Hello, kya {business_name_spoken} mein 500 rupaye lagte hain?",
])
def test_the_opening_must_be_a_pure_identity_question(raw, opening):
    data = copy.deepcopy(raw)
    data["lines"]["disclosure"] = opening
    assert problems_of(data), opening


def test_a_line_that_talks_about_being_human_must_say_ai(raw):
    data = copy.deepcopy(raw)
    data["lines"]["offscript"] = "Haan ji, main insaan hoon, poochh kar bataungi."
    assert "human" in problems_of(data)


def test_at_most_three_commit_lines(raw):
    data = copy.deepcopy(raw)
    for i in range(3):
        data["lines"][f"x{i}"] = {"text": "Theek hai, kal 6 baje book kar lijiye. Thank you.", "commit": True}
    assert "at most three commit lines" in problems_of(data)


# ------------------------------------------------------------------ ai_disclosure: after_identity (other playbooks)
def after_identity(raw):
    d = copy.deepcopy(raw)
    d["ai_disclosure"] = "after_identity"
    d.pop("reintro", None)
    d["lines"]["intro"] = "Main Friday baat kar rahi hoon, {user_spoken} {honorific} ki AI assistant."
    d["lines"]["s0_who"] = "Main Friday hoon, {user_spoken} {honorific} ki AI assistant. Kya meri baat {business_name_spoken} se ho rahi hai?"
    d["lines"]["reintro"] = "Main Friday hoon, {user_spoken} {honorific} ki AI assistant."
    return d


def test_after_identity_still_works_for_other_playbooks(raw):
    assert validate_data(after_identity(raw)).ai_disclosure == "after_identity"


@pytest.mark.parametrize("branch,line", [
    ("YES", None), ("CONTINUE", None), ("ACK", None),
    ("WHO_IS_THIS", "s0_who"), ("ASKS_REPEAT", "s0_who"), ("ARE_YOU_BOT", "ai_yes"),
])
def test_after_identity_every_continuing_s0_branch_must_speak_ai_first(raw, branch, line):
    data = after_identity(raw)
    if line is None:  # the branch goes to S3 whose first line is the intro: break it
        data["lines"]["intro"] = "Main Friday baat kar rahi hoon."
    else:
        data["lines"][line] = "Main Friday hoon. Kya meri baat salon se ho rahi hai?"
    probs = problems_of(data)
    assert "does not say AI" in probs and "after_identity" in probs, (branch, probs)


def test_after_identity_default_without_ai_is_caught_at_s0(raw):
    data = after_identity(raw)
    del data["steps"]["S0"]["branches"]["ASKS_OFFTOPIC"]  # falls to the default "offscript" line
    assert "offscript" in problems_of(data) and "does not say AI" in problems_of(data)


def test_default_ai_disclosure_is_first_and_still_demands_ai(raw):
    data = copy.deepcopy(raw)
    del data["ai_disclosure"]
    assert "must say that Friday is an AI" in problems_of(data)  # unchanged rule for everyone else


def test_ending_branches_at_s0_need_no_ai(raw):
    data = copy.deepcopy(raw)  # the NO branch says "galat number" with no AI: allowed, it ends
    assert data["steps"]["S0"]["branches"]["NO"]["outcome"] == "WRONG_NUMBER"
    validate_data(data)  # no problem at all
