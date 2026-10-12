"""Open questions: a model-written, fact-checked answer replaces the canned "poochh kar bataungi",
and the script then asks its own question again. Every guardrail lives in code."""

from __future__ import annotations

import pytest

from friday.playbooks.answerer import validate_answer
from friday.playbooks.engine import PlaybookPolicy

from .conftest import drive, make_brief

FACTS = {
    "user": "राहुल", "honorific": "sir", "business_called": "Shreya saloon",
    "user_wants": "haircut aur beard trim", "wanted_when": "kal shaam 5 baje", "mode": "quote_only",
}
Q = "Kitne log aayenge aur kis naam se booking karni hai?"


class FakeAnswerer:
    def __init__(self, text):
        self.text, self.seen = text, []

    async def answer(self, *, question, friday_said, facts, task_id=None):
        self.seen.append((question, friday_said, facts))
        return validate_answer(self.text, facts, question) if self.text else None


# ------------------------------------------------------------------ the code checks
@pytest.mark.parametrize(("text", "want"), [
    ("Ji, sirf {user} {honorific} ke liye, haircut aur beard trim.",
     "Ji, sirf राहुल sir ke liye, haircut aur beard trim."),
    ("Ji, kal shaam 5 baje ke liye poochh rahi hoon.", None),
    ("Yeh main {user} {honorific} se poochh kar bataungi.",
     "Yeh main राहुल sir se poochh kar bataungi."),
])
def test_good_answers_pass_and_names_are_filled_in(text, want):
    assert validate_answer(text, FACTS, Q) == (want or text)


@pytest.mark.parametrize("text", [
    "",
    "Ji, mera number 9876543210 hai.",                       # a phone number
    "Ji, booking confirm kar dijiye.",                        # confirms
    "Ji, booking {user} {honorific} ke naam se karni hai.",   # implies a booking in quote_only
    "Ji, advance de dungi.",                                 # money
    "OTP bhej dungi.",                                       # secret
    "Ji, 6 baje ka slot theek rahega.",                      # invented time
    "Main ek insaan hoon, ji.",                              # claims to be human
    "Ji, " + "bahut " * 40 + "accha.",                       # too long
    Q,                                                       # just repeats the question
])
def test_bad_answers_are_rejected(text):
    assert validate_answer(text, FACTS, Q) is None


def test_a_number_the_business_said_may_be_repeated():
    assert validate_answer("Ji, 3 log theek hai.", FACTS, "3 log aayenge?") is not None


# ------------------------------------------------------------------ through the real policy
async def run(answerer, *, open_questions=True):
    policy = PlaybookPolicy(llm_mode="never", answerer=answerer, open_questions=open_questions)
    return await drive(["Aap kahan se bol rahi hain, parking hai kya?"], policy=policy,
                       brief=make_brief())


async def test_grounded_answer_replaces_the_canned_line_and_the_script_continues():
    fa = FakeAnswerer(
        "Ji, main {user} {honorific} ki taraf se haircut aur beard trim ke liye poochh rahi hoon."
    )
    r = await run(fa)
    text = r.all_text()
    assert "Rahul sir ki taraf se haircut aur beard trim ke liye poochh rahi hoon" in text
    assert "ke kya charges rahenge" in text  # then the script asks its own question again
    q, said, facts = fa.seen[0]
    assert "parking" in q and facts["user_wants"] and facts["mode"] == "quote_only"


async def test_a_rejected_or_missing_answer_falls_back_to_the_canned_line():
    for ans in (FakeAnswerer("Mera number 9876543210 hai."), FakeAnswerer(None)):
        r = await run(ans)
        assert "poochh kar bataungi" in r.all_text()


async def test_off_by_default_and_without_an_answerer():
    fa = FakeAnswerer("Ji, main {user} {honorific} ke liye poochh rahi hoon.")
    assert "poochh kar bataungi" in (await run(fa, open_questions=False)).all_text()
    assert not fa.seen
    assert "poochh kar bataungi" in (await run(None)).all_text()


async def test_answer_failure_never_breaks_the_call():
    class Boom:
        async def answer(self, **kw):
            raise RuntimeError("model down")

    assert "poochh kar bataungi" in (await run(Boom())).all_text()
