# ruff: noqa: E501
"""The reply writer inside the shopping / planner / intents gateways (fakes only).

* both switches off: no service is built and the chat text is untouched;
* log on, writer off: the chat text is byte for byte the same, and one record per writer call is written;
* writer on: the LlmWriter output is fact-checked in the live path; an invented price falls back to the template.
"""

from __future__ import annotations

import json

from friday.replywriter import ReplyLog, ReplyService
from tests.replywriter.helpers import ScriptedLLM, out
from tests.shopping.helpers import BIGBASKET, INSTAMART, SiteFake
from tests.shopping.test_shopping import texts, world
from tests.shopping.test_store_scope import ALL

DEFAULT = {"bigbasket": BIGBASKET, "instamart": INSTAMART}


async def test_both_switches_off_builds_no_service_and_changes_nothing(media_world, tmp_path):
    w, gw = await world(media_world, SiteFake(DEFAULT))
    assert w.runtime.pipeline.reply_service is None and not (tmp_path / "var").exists()
    again, _ = await world(media_world, SiteFake(DEFAULT))
    assert texts(await w.say("atta")) == texts(await again.say("atta"))


async def test_log_on_writer_off_is_byte_for_byte_the_same_text_and_writes_one_record_per_call(media_world, tmp_path):
    off, _ = await world(media_world, SiteFake(ALL))
    logged, _ = await world(media_world, SiteFake(ALL), reply_log_enabled=True, reply_log_dir=str(tmp_path / "rl"))
    rs = logged.runtime.pipeline.reply_service
    assert rs is not None and rs.writer_enabled is False and rs.log is not None
    a, b = texts(await off.say("atta price on blinkit")), texts(await logged.say("atta price on blinkit"))
    assert a == b  # the text the tester sees does not change
    items = ReplyLog.open(logged.runtime.pipeline.settings).items()
    assert sorted(i["intent"] for i in items) == ["ack", "price_compare"] and {i["writer"] for i in items} == {"legacy"}
    raw = (tmp_path / "rl" / "replies.jsonl").read_text()
    assert "9811100001" not in raw and "atta price on blinkit" not in raw  # no raw chat text, no phone
    rec = next(i for i in items if i["intent"] == "price_compare")
    assert rec["input"]["facts"]["store"] == "Blinkit" and rec["input"]["facts"]["products"][0]["price_paise"] == 24400 or rec["input"]["facts"]["products"][0]["price_paise"] == 21900


async def test_writer_on_uses_a_grounded_llm_reply_and_rejects_an_invented_price(media_world, tmp_path):
    w, _ = await world(media_world, SiteFake(ALL), reply_writer_enabled=True, reply_log_enabled=True, reply_log_dir=str(tmp_path / "rl"))
    rs: ReplyService = w.runtime.pipeline.reply_service
    rs.llm = ScriptedLLM(
        out("Looking at Blinkit only for atta, as you asked."),  # the ack: grounded
        out("Rajdhani is just Rs 199 on Blinkit.", "Want me to compare with Zepto, Instamart and BigBasket too?", question="Want me to compare with Zepto, Instamart and BigBasket too?"),  # invented price
    )
    msgs = texts(await w.say("atta price on blinkit"))
    body = "\n".join(msgs)
    assert msgs[0] == "Looking at Blinkit only for atta, as you asked."  # accepted
    assert "Rs 199" not in body and "Rs 219" in body and "Want me to compare with Zepto, Instamart and BigBasket too?" in body  # template took over
    items = {i["intent"]: i for i in ReplyLog.open(w.runtime.pipeline.settings).items()}
    assert items["ack"]["writer"] == "llm" and items["ack"]["fact_check"] == "ok"
    assert items["price_compare"]["writer"] == "template" and "unknown_number" in items["price_compare"]["fact_check"]
    assert json.loads(json.dumps(items["price_compare"]["output"]))["question"].endswith("too?")


async def test_writer_without_a_model_uses_the_template_writer(media_world):
    w, _ = await world(media_world, SiteFake(ALL), reply_writer_enabled=True)
    w.runtime.pipeline.reply_service.llm = None
    body = "\n".join(texts(await w.say("atta price on blinkit")))
    assert "Want me to compare with Zepto, Instamart and BigBasket too?" in body and "Rs 219" in body


async def test_delete_everything_erases_the_testers_log_records(media_world, tmp_path):
    w, _ = await world(media_world, SiteFake(ALL), reply_log_enabled=True, reply_log_dir=str(tmp_path / "rl"))
    await w.say("atta price on blinkit")
    pipeline = w.runtime.pipeline
    rl = ReplyLog.open(pipeline.settings)
    assert rl.stats()["records"] == 2
    await pipeline.delete_everything(w.user)
    assert ReplyLog.open(pipeline.settings).stats()["records"] == 0


async def test_intents_gateway_greets_through_the_writer_and_logs_it(media_world, tmp_path):
    w = await media_world(proactive_intents_enabled=True, reply_log_enabled=True, reply_log_dir=str(tmp_path / "rl"))
    msgs = texts(await w.say("Hi"))
    assert len(msgs) == 1 and msgs[0].startswith("Hi ") and "Main Friday hoon" in msgs[0] and msgs[0].rstrip().endswith("?")
    assert "haircut" not in msgs[0].lower() and "service" not in msgs[0].lower()
    (rec,) = ReplyLog.open(w.runtime.pipeline.settings).items()
    assert rec["intent"] == "greeting" and rec["writer"] == "legacy" and "<name>" not in msgs[0]
