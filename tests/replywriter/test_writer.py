# ruff: noqa: E501
"""write_reply: the LlmWriter is fact-checked on every output; any invented fact or style break => TemplateWriter."""

from __future__ import annotations

import pytest

from friday.replywriter import Facts, ReplyInput, TemplateWriter, write_reply
from friday.replywriter.factcheck import fact_violations, verify
from friday.replywriter.schema import WRITABLE, ReplyOutput
from tests.replywriter.helpers import GOOD, ScriptedLLM, compare_input, out

pytestmark = pytest.mark.asyncio


async def run(inp: ReplyInput, reply: object) -> ReplyOutput:
    return await write_reply(inp, llm=ScriptedLLM(reply), use_llm=True)


async def test_a_grounded_llm_reply_is_used():
    res = await run(compare_input(), GOOD)
    assert res.writer == "llm" and res.fact_check == "ok" and res.messages[-1].startswith("Want me to compare")
    assert [b.id for b in res.buttons] == []  # the model chose no button


async def test_invented_price_falls_back_to_the_template():
    bad = out("Rajdhani Chakki Atta 5 kg is Rs 199 on Blinkit.", "Want me to compare with Zepto, Instamart and BigBasket too?", question="Want me to compare with Zepto, Instamart and BigBasket too?")
    res = await run(compare_input(), bad)
    assert res.writer == "template" and res.fact_check.startswith("rejected:") and "unknown_number" in res.fact_check
    assert "199" not in "\n".join(res.messages) and "Rs 219" in "\n".join(res.messages)


async def test_invented_store_falls_back():
    res = await run(compare_input(), out("Zepto has it cheaper than Blinkit.", "Want me to compare with Zepto, Instamart and BigBasket too?", question="Want me to compare with Zepto, Instamart and BigBasket too?"))
    # Zepto IS a fact here (offered), so use a store that is not in the facts
    res = await run(compare_input(), out("Amazon has it cheaper than Blinkit.", "Compare with the others?", question="Compare with the others?"))
    assert res.writer == "template" and "unknown_store" in res.fact_check


async def test_invented_url_and_pack_fall_back():
    res = await run(compare_input(), out("See https://www.blinkit.com/prn/atta-evil for it.", "Compare too?", question="Compare too?"))
    assert res.writer == "template" and "unknown_url" in res.fact_check
    res = await run(compare_input(), out("The 10 kg pack of Rajdhani is the pick.", "Compare too?", question="Compare too?"))
    assert res.writer == "template" and "unknown_pack" in res.fact_check


async def test_a_cited_url_is_fine():
    assert fact_violations(compare_input(), "Open https://blinkit.com/p/atta to see it.") == []


async def test_internal_codes_never_reach_the_user():
    inp = ReplyInput(intent="lookup_failed", facts=Facts(store="Blinkit", status_codes=["no_result"]), lang="en", pending="retry")
    res = await run(inp, out("Blinkit gave no_result.", "Try again in a minute?", question="Try again in a minute?"))
    assert res.writer == "template" and "leaked_code" in res.fact_check


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (out("# Result\nBlinkit is cheapest", "Ok?"), "markdown_header"),
        (out("Which pincode?\nOr should I use the old one?"), "many_questions"),
        (out("Sorry, I can't do that."), "flat_refusal"),
        (out("Please tell me more. " * 25), "too_long"),
    ],
)
async def test_style_post_check_rejects(reply, code):
    inp = ReplyInput(intent="ask_one", facts=Facts(missing=["pincode"]), lang="en", pending="answer")
    res = await run(inp, reply)
    assert res.writer == "template" and code in res.fact_check


async def test_two_questions_across_messages_is_rejected():
    res = await run(compare_input(), out("Want Zepto?", "Or Blinkit?"))
    assert res.writer == "template" and "many_questions" in res.fact_check


async def test_garbage_and_errors_fall_back():
    for bad in ("not json", {"messages": [], "question": None, "buttons": [], "proofs": []}, {"extra": 1}, TimeoutError()):
        res = await run(compare_input(), bad)
        assert res.writer == "template" and res.fact_check == "rejected:llm_error"


async def test_a_button_the_caller_did_not_offer_is_dropped_not_trusted():
    res = await run(compare_input(), out(*GOOD["messages"], question=GOOD["question"], buttons=["shop:cmp:yes", "evil:button"]))
    assert res.writer == "llm" and [b.id for b in res.buttons] == ["shop:cmp:yes"]
    res = await run(compare_input(), out(*GOOD["messages"], question=GOOD["question"], proofs=["made-up-ref"]))
    assert res.writer == "template" and "unknown_proof" in res.fact_check


async def test_no_llm_or_switch_off_means_template_only():
    llm = ScriptedLLM(GOOD)
    res = await write_reply(compare_input(), llm=llm, use_llm=False)
    assert res.writer == "template" and llm.calls == []
    assert (await write_reply(compare_input())).writer == "template"


async def test_intents_without_typed_facts_never_reach_the_model():
    llm = ScriptedLLM(GOOD)
    res = await write_reply(ReplyInput(intent="passthrough", draft=["Kal ka reminder laga diya."]), llm=llm, use_llm=True)
    assert llm.calls == [] and res.messages == ["Kal ka reminder laga diya."] and "passthrough" not in WRITABLE


@pytest.mark.parametrize("lang", ["en", "hinglish"])
async def test_template_writer_output_satisfies_the_style_post_check(lang):
    inputs = [
        compare_input(lang=lang),
        compare_input(lang=lang, pending="place", facts=compare_input().facts.model_copy(update={"store": None, "stores_offered": []})),
        ReplyInput(intent="greeting", facts=Facts(name="Rahul"), lang=lang),
        ReplyInput(intent="greeting", lang=lang),
        ReplyInput(intent="ack", facts=Facts(store="Blinkit", category="atta"), lang=lang),
        ReplyInput(intent="ack", facts=Facts(stores=["Zepto", "Blinkit"], category="atta"), lang=lang),
        ReplyInput(intent="lookup_failed", facts=Facts(store="Blinkit", status_codes=["blocked"], stores_offered=["Zepto", "Instamart"], next_actions=["open_site"]), lang=lang, pending="compare_more"),
        ReplyInput(intent="lookup_failed", facts=Facts(status_codes=["no_result"]), lang=lang, pending="retry"),
        ReplyInput(intent="ask_one", facts=Facts(missing=["pincode"]), lang=lang, pending="answer"),
        ReplyInput(intent="honest_limit", facts=Facts(topic="place orders inside apps yet", next_actions=["paste_details"]), lang=lang),
        ReplyInput(intent="cancelled", lang=lang),
    ]
    tw = TemplateWriter()
    for inp in inputs:
        res = tw.write(inp)
        assert res.writer == "template" and 1 <= len(res.messages) <= 5
        assert verify(inp, res) == [], (inp.intent, verify(inp, res), res.messages)
        text = "\n".join(res.messages)
        assert "no_result" not in text and "blocked" not in text.lower().replace("blocked us", "")
