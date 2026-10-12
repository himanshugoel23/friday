# ruff: noqa: E501
"""Server-side principle (docs/HANDOFF.md 2b): the job finishes without the user's phone,
the result is delivered later and never lost, and "status" returns it."""

from __future__ import annotations

from friday.quotes.models import Outcome, State
from tests.e2e.harness import Friday
from tests.quotes.conftest import USER_PHONE, FakeCalls, FakeDirectory, cand, make_user
from tests.quotes.test_flow import conv_of, to_shortlist

VENDORS = (("Glow Salon", 450), ("Royal Cuts", 800), ("Trendz Studio", 550))


async def run_all(qf):
    for name, price in VENDORS:
        await qf.calls.finish(name, Outcome.QUOTE, price)


async def test_phone_offline_for_the_whole_job(qf, rahul):
    """After the approval the user sends nothing more (phone off); the job still finishes,
    the comparison is sent once, and it is stored."""
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    sent_before = len(rahul.msgs())
    qf.channel.fail_phones.add(USER_PHONE)  # WhatsApp cannot reach the (switched off) phone right now
    await run_all(qf)  # vendor calls, comparison: no user input at all
    conv = await conv_of(qf)
    assert conv.state == State.AWAITING_BOOK and conv.final_text.startswith("haircut ke quotes")
    assert conv.delivery.failed and conv.delivery.sms_sent  # fell back to SMS at once
    assert len(rahul.msgs()) == sent_before  # nothing reached the phone yet
    sms = qf.c.sms.sent
    assert len(sms) == 1 and sms[0].to_phone == USER_PHONE
    assert sms[0].template.key == "user_task_update" and "Rs 450" in sms[0].template.params[0]
    assert len(sms[0].template.params[0]) <= 30


async def test_whatsapp_delivered_receipt_means_no_sms(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    await run_all(qf)
    conv = await conv_of(qf)
    assert conv.delivery.provider_id and not conv.delivery.failed
    await qf.flow.on_delivery_status(conv.delivery.provider_id, "delivered")
    qf.clock.advance(minutes=60)
    await qf.flow.tick()
    assert qf.c.sms.sent == [] and (await conv_of(qf)).delivery.delivered


async def test_no_receipt_after_n_minutes_sends_an_sms_once(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    await run_all(qf)
    qf.clock.advance(minutes=19)
    await qf.flow.tick()
    assert qf.c.sms.sent == []  # the default wait is 20 minutes
    qf.clock.advance(minutes=2)
    await qf.flow.tick()
    await qf.flow.tick()
    assert len(qf.c.sms.sent) == 1  # exactly one fallback
    assert (await conv_of(qf)).delivery.sms_sent


async def test_the_wait_and_the_sms_fallback_are_settings(qf, rahul):
    qf.c.settings.quotes_delivery_receipt_wait_min = 5
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    await run_all(qf)
    qf.clock.advance(minutes=6)
    await qf.flow.tick()
    assert len(qf.c.sms.sent) == 1
    qf.c.settings.quotes_sms_fallback = False
    await to_shortlist(qf, rahul)  # a new request with the fallback off
    await rahul.tap("Haan")
    qf.channel.fail_phones.add(USER_PHONE)
    await run_all(qf)
    assert len(qf.c.sms.sent) == 1


async def test_failed_status_from_meta_triggers_the_sms(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    await run_all(qf)
    pid = (await conv_of(qf)).delivery.provider_id
    await qf.flow.on_delivery_status(pid, "failed", "131026")
    assert len(qf.c.sms.sent) == 1


async def test_voice_callback_only_if_allowed(qf, rahul):
    qf.c.settings.quotes_voice_fallback = False
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    await run_all(qf)
    qf.clock.advance(minutes=25)
    await qf.flow.tick()
    qf.clock.advance(minutes=30)
    await qf.flow.tick()
    assert not (await conv_of(qf)).delivery.voice_requested
    qf.c.settings.quotes_voice_fallback = True
    await qf.flow.tick()
    assert (await conv_of(qf)).delivery.voice_requested


async def test_user_returns_later_and_asks_status(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    await run_all(qf)
    stored = rahul.last()
    qf.clock.advance(hours=30)  # outside the 24h window by now
    out = await rahul.say("status")
    assert out[0] == stored  # the stored result, again
    assert [b.title for b in rahul.last_msg().buttons][0].startswith("Book")
    out = await rahul.say("result")
    assert out[0] == stored


async def test_status_while_calls_are_running_and_with_nothing_yet(qf, rahul):
    assert (await rahul.say("status"))[0].startswith("Abhi koi request nahi hai")
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    assert (await rahul.say("status"))[0] == (
        "Abhi kaam chal raha hai. Quotes aate hi message karungi."
    )


async def test_never_asks_the_user_to_stay_online(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    await run_all(qf)
    text = rahul.all_text().lower()
    for bad in ("live location", "keep this chat", "stay online", "install", "download"):
        assert bad not in text


async def test_server_restart_mid_job_resumes_from_the_database(tmp_path):
    db = f"sqlite+aiosqlite:///{tmp_path}/r.db"
    f1 = await Friday.start(database_url=db, media_dir=str(tmp_path / "m"), quotes_flow_enabled=True)
    f1.c.override("directory", FakeDirectory([cand(1, "Glow Salon"), cand(2, "Royal Cuts"),
                                              cand(3, "Trendz Studio")]))
    f1.flow = f1.rt.pipeline.quotes
    f1.calls = f1.flow.calls = FakeCalls(f1)
    rahul = await make_user(f1)
    await to_shortlist(f1, rahul)
    await rahul.tap("Haan")
    assert f1.calls.names() == ["Glow Salon"]
    await f1.calls.finish("Glow Salon", Outcome.QUOTE, 450)
    assert f1.calls.names() == ["Glow Salon", "Royal Cuts"]
    await f1.close()  # the server goes down while Royal Cuts is being called

    f2 = await Friday.start(database_url=db, media_dir=str(tmp_path / "m"), quotes_flow_enabled=True,
                            create_tables=False, first_message_id=1_000_000)
    f2.c.override("directory", FakeDirectory([]))
    f2.flow = f2.rt.pipeline.quotes
    calls2 = f2.flow.calls = FakeCalls(f2)
    # the call to Royal Cuts finished while the server was down: its result is in the DB
    conv = await conv_of(f2)
    royal = next(v for v in conv.shortlist if v.name == "Royal Cuts")
    assert royal.status.value == "calling" and royal.task_id
    from friday.quotes.calls import CallReport

    calls2.reports[royal.task_id] = CallReport(True, Outcome.QUOTE, price_inr=800)
    await f2.flow.tick()  # what the worker loop does on startup
    trendz = next(v for v in (await conv_of(f2)).shortlist if v.name == "Trendz Studio")
    assert trendz.status.value == "calling"  # the job went on to the next vendor
    calls2.reports[trendz.task_id] = CallReport(True, Outcome.QUOTE, price_inr=550)
    await f2.flow.tick()
    conv = await conv_of(f2)
    assert conv.state == State.AWAITING_BOOK and "Rs 800" in conv.final_text
    party = f2.person(USER_PHONE)
    assert party.last().startswith("haircut ke quotes")


async def test_a_call_that_never_reports_back_is_given_up(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    qf.clock.advance(minutes=25)
    await qf.flow.tick()  # still no report: cancelled and counted as failed, then retried later
    assert qf.calls.cancelled
