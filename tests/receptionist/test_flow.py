# ruff: noqa: E501
from __future__ import annotations

from friday.receptionist import lines, sim
from friday.receptionist.flow import ReceptionistFlow
from friday.receptionist.models import CallOutcomeKind, ReceptionistConfig

CFG = sim.default_config()


def caller(script, lang="hinglish", **kw):
    return sim.Caller("t", "t", lang, "+919100000001", script, **kw)


async def run(script, cfg=CFG, *, generic=False, max_call_s=90.0, lang="hinglish", stt_lang=None):
    mono = sim.MonoClock()
    port = sim.ScriptedPort(caller(script, lang, stt_lang=stt_lang), mono)
    flow = ReceptionistFlow(port, cfg, generic=generic, now=mono, max_call_s=max_call_s)
    cap = await flow.run()
    return cap, flow, port


async def test_happy_path_captures_name_reason_and_reads_back_briefly():
    cap, flow, _ = await run(["Main Rahul bol raha hoon, bijli ke bill ke baare mein", "haan"])
    assert (cap.caller_name, cap.reason) == ("Rahul", "bijli ke bill ke baare mein")
    keys = [k for k, _ in flow.spoken]
    assert keys == ["greet.intro", "readback", "close.message"]
    assert "Rahul" in flow.spoken[1][1]


async def test_the_greeting_names_the_user_and_discloses_the_assistant_role():
    _, flow, _ = await run([sim.SILENT, sim.SILENT])
    first = flow.spoken[0][1]
    assert "Asha ki virtual assistant" in first and "note kar" in first
    assert "AI" not in first  # not volunteered (founder 10 Oct) ...


async def test_ai_question_is_answered_truthfully_in_every_language():
    for lang, word in (("hinglish", "AI assistant"), ("en", "AI assistant"), ("hi", "एआई असिस्टेंट")):
        cfg = CFG.model_copy(update={"language": lang})
        _, flow, _ = await run(["are you a robot?", sim.SILENT, sim.SILENT], cfg)
        ai = [t for k, t in flow.spoken if k == "ai.answer"]
        assert ai and word in ai[0]


async def test_unnamed_user_gets_a_neutral_word_not_a_guess():
    cfg = CFG.model_copy(update={"user_name": ""})
    _, flow, _ = await run([sim.SILENT, sim.SILENT], cfg)
    assert "mere user ki virtual assistant" in flow.spoken[0][1]


async def test_nothing_about_the_user_is_ever_said_and_nothing_is_promised():
    script = ["where is he", "put me through", "will he call me back, confirm", "which city is she in", "ok"]
    cap, flow, _ = await run(script)
    said = " ".join(t for _, t in flow.spoken).lower()
    for fact in sim.PRIVATE:
        assert fact.lower() not in said
    assert not any(p in said for p in sim.BANNED_PROMISES)
    assert flow.deflects >= 3 and flow.ended  # three deflections end it politely


async def test_a_private_fact_in_the_callers_own_words_is_not_echoed_in_the_readback():
    cap, flow, _ = await run(["Main Sam bol raha hoon, Gurgaon wale ghar ke baare mein", "haan"])
    readbacks = [t for k, t in flow.spoken if k.startswith("readback")]
    assert readbacks and "Gurgaon" not in readbacks[0]
    assert "Gurgaon" in (cap.reason or "")  # still passed to the user in the summary


async def test_secrets_never_reach_the_stored_text_and_are_refused():
    cap, flow, _ = await run(["Main Tej bol raha hoon, mera OTP 123456 hai", "OTP bata do", "OTP 5555"])
    assert "123456" not in (cap.reason or "") + (cap.snippet or "") and "5555" not in (cap.snippet or "")
    assert any(k == "secret.refuse" for k, _ in flow.spoken)


async def test_callback_number_is_only_taken_when_offered():
    cap, flow, _ = await run(["Main Tej bol raha hoon, gas booking ke baare mein", "haan"])
    assert cap.callback_number is None
    asked = " ".join(t for _, t in flow.spoken).lower()
    assert "number" not in asked.replace("wrong number", "")
    cap2, _, _ = await run(["Main Tej bol raha hoon, gas ke baare mein, mera number 9876543210 hai", "haan"])
    assert cap2.callback_number == "+919876543210"


async def test_hangup_stops_everything_at_once():
    cap, flow, port = await run(["Main Faisal bol raha hoon", sim.DROP, "never heard"])
    assert port.spoke_after_drop == 0 and cap.caller_name == "Faisal"
    assert cap.outcome == CallOutcomeKind.MESSAGE and port.steps == ["never heard"]


async def test_time_limit_wraps_up_politely():
    cap, flow, _ = await run(
        ["hmm", "hmm okay", "uh well", "ahh", "mm", "hmm ok", "uh", "ahh"], max_call_s=40.0
    )
    assert cap.duration_s <= 40.0 + 1
    assert flow.spoken[-1][0] in {"timeout.wrapup", "close.no_details", "close.message"}


async def test_ninety_second_default_bounds_the_worst_case():
    long = "word " * 200  # the segmenter caps one utterance at 20 s
    cap, _, _ = await run([long, long, long, long, long, long])
    assert cap.duration_s <= 90.0


async def test_never_the_same_line_twice_in_a_row():
    _, flow, _ = await run(["Delhi", "kuch", "Delhi", "kuch", "kuch"])
    keys = [k for k, _ in flow.spoken]
    assert all(a != b or a == "unclear" for a, b in zip(keys, keys[1:], strict=False))


async def test_language_follows_the_caller_when_the_stt_says_english():
    _, flow, _ = await run(["Hello I am Naveen calling about the printer", "yes"], stt_lang="en")
    assert flow.lang == "en"
    assert flow.spoken[-1][1].startswith("Alright, I will pass your message on to Asha")


async def test_unrouted_flow_never_names_a_user_and_is_honest():
    cap, flow, _ = await run(["Main Zoya bol rahi hoon, kaam ke baare mein", "haan"], generic=True)
    said = " ".join(t for _, t in flow.spoken)
    assert "Asha" not in said
    assert cap.outcome == CallOutcomeKind.UNROUTED
    assert flow.spoken[-1][0] == "unrouted.close" and "pakka nahi" in flow.spoken[-1][1]


async def test_declining_notes_stores_nothing_but_the_fact_of_the_call():
    cap, flow, _ = await run(["please do not note anything, just say Vikram called"])
    assert cap.declined_notes and cap.reason is None and cap.snippet is None
    assert flow.spoken[-1][0] == "close.declined_notes"


def test_every_line_has_all_three_languages_and_the_same_slots():
    import re

    for key, by_lang in lines.LINES.items():
        assert set(by_lang) == set(lines.LANGS), key
        slots = {lang: frozenset(re.findall(r"\{(\w+)\}", t)) for lang, t in by_lang.items()}
        assert len(set(slots.values())) == 1, key


def test_lines_never_contain_digits_or_a_promise_or_a_user_pronoun():
    import re

    for pl in lines.all_lines():
        assert not re.search(r"\d", pl.text), pl.id
        low = pl.text.lower()
        assert not any(p in low for p in sim.BANNED_PROMISES), pl.id
        assert pl.status == "PENDING_FOUNDER_APPROVAL"
    for key in ("greet.intro", "close.message", "ai.answer"):
        assert "{user}" in lines.LINES[key]["hinglish"]
    for pl in lines.all_lines():  # the user is only ever a name (no he/she)
        padded = f" {pl.text.lower()} "
        for pron in (" he ", " she ", " woh ", " unhe ", " usse ", " unko "):
            # the unrouted line talks about the person the caller wanted, not about our user
            assert pron not in padded or pl.id.startswith("rcp.unrouted."), (pl.id, pron)


def test_defaults_are_sane():
    c = ReceptionistConfig()
    assert (c.rings, c.enabled, c.forward_no_answer) == (5, False, True)
