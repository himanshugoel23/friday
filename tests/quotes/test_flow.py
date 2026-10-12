# ruff: noqa: E501
"""The WhatsApp quotes conversation, end to end, with a scripted vendor-call port."""

from __future__ import annotations

from datetime import timedelta

from friday.core.models import InboundMessage, MessageKind
from friday.quotes.models import Outcome, State
from tests.quotes.conftest import BLR, GURGAON, USER_PHONE, FakeDirectory, cand, make_user

REQ = "kal shaam parlour mein haircut karwana hai, quotes chahiye"


async def conv_of(qf):
    u = await qf.c.repos.users.get_by_phone(USER_PHONE)
    got = await qf.flow.store.latest_for_user(u.id)
    return got[0]


async def to_shortlist(qf, rahul, text=REQ, where="Sector 56 Gurgaon"):
    await rahul.say(text)
    return await rahul.say(where)


# ------------------------------------------------------------------ the happy paths
async def test_quote_only_happy_path_then_book(qf, rahul):
    out = await rahul.say(REQ)
    assert out == ["Aap kahan hain? Location pin bhejiye, ya likhiye jaise 'Sector 56 Gurgaon'."]
    out = await rahul.say("Sector 56 Gurgaon")
    assert "3 jagah mili" in out[-1] and "Glow Salon" in out[-1] and "AI assistant" in out[-1]
    assert [b.title for b in rahul.last_msg().buttons] == ["Haan, call karo", "Badlo"]
    assert qf.calls.placed == []  # nobody is called before the approval

    out = await rahul.tap("Haan")
    assert out == []  # no stage pings: silence until the outcome (founder rule)
    assert qf.calls.names() == ["Glow Salon"]  # one at a time by default
    assert qf.calls.placed[0]["mode"] == "quote_only"
    await qf.calls.finish("Glow Salon", Outcome.QUOTE, 450)
    assert qf.calls.names() == ["Glow Salon", "Royal Cuts"]
    await qf.calls.finish("Royal Cuts", Outcome.QUOTE, 800)
    await qf.calls.finish("Trendz Studio", Outcome.QUOTE, 550)
    text = rahul.last()
    assert text.startswith("haircut ke quotes (kal shaam):")
    lines = text.splitlines()
    assert lines[1:4] == ["Glow Salon: Rs 450", "Trendz Studio: Rs 550", "Royal Cuts: Rs 800"]
    assert [b.title for b in rahul.last_msg().buttons] == [
        "Book Glow Salon", "Book Trendz Studio", "Book Royal Cuts",
    ]
    assert (await conv_of(qf)).state == State.AWAITING_BOOK

    out = await rahul.tap("Book Glow")  # the time was only "kal shaam": one question
    assert out == ["Kitne baje ka slot book karun? Jaise: 6 baje."]
    out = await rahul.say("6 baje")
    assert out == []  # no "calling now" ping
    book = qf.calls.placed[-1]
    assert book["kind"] == "book" and book["name"] == "Glow Salon" and book["ceiling"] == 450
    await qf.calls.finish("Glow Salon", Outcome.BOOKED, 450)
    assert rahul.last() == "Booking pakki: Glow Salon, kal shaam 6 baje, Rs 450."
    assert (await conv_of(qf)).state == State.DONE


async def test_exact_time_gives_book_buttons_with_the_time(qf, rahul):
    await to_shortlist(qf, rahul, "haircut kal 6 baje chahiye parlour mein")
    await rahul.tap("Haan")
    for name, price in (("Glow Salon", 450), ("Royal Cuts", 800), ("Trendz Studio", 550)):
        await qf.calls.finish(name, Outcome.QUOTE, price)
    titles = [b.title for b in rahul.last_msg().buttons]
    assert titles[0] == "Book Glow Salon 6 PM"[:20] and all(len(t) <= 20 for t in titles)
    out = await rahul.tap("Book Glow")  # no further question: time and price are known
    assert out == []
    book = qf.calls.placed[-1]
    assert book["ceiling"] == 450 and book["kind"] == "book"


async def test_explicit_book_with_time_and_budget_calls_in_book_mode(qf, rahul):
    await to_shortlist(qf, rahul, "book kar do haircut kal 6 baje parlour mein 600 tak")
    await rahul.tap("Haan")
    assert qf.calls.placed[0]["mode"] == "book"
    await qf.calls.finish("Glow Salon", Outcome.BOOKED, 450)
    assert qf.calls.names() == ["Glow Salon"]  # booked: nobody else is called
    assert rahul.last().startswith("Booking pakki: Glow Salon")


async def test_booking_failure_gives_the_reason(qf, rahul):
    await to_shortlist(qf, rahul, "haircut kal 6 baje chahiye parlour mein")
    await rahul.tap("Haan")
    for name, price in (("Glow Salon", 450), ("Royal Cuts", 800), ("Trendz Studio", 550)):
        await qf.calls.finish(name, Outcome.QUOTE, price)
    await rahul.tap("Book Glow")
    await qf.calls.finish("Glow Salon", Outcome.NO_SLOT)
    assert rahul.last().splitlines()[0] == (
        "Glow Salon mein booking nahi ho payi: us time ka slot khali nahi tha."
    )
    assert [b.title for b in rahul.last_msg().buttons][0].startswith("Book Trendz")  # others stay


# ------------------------------------------------------------------ missing info, one at a time
async def test_asks_only_what_is_missing_one_at_a_time(qf, rahul):
    assert (await rahul.say("parlour jana hai"))[0].startswith("Kaunsi service chahiye")
    assert (await rahul.say("haircut aur beard trim"))[0].startswith("Kab chahiye")
    assert (await rahul.say("kal shaam 6 baje"))[0].startswith("Aap kahan hain")
    assert "ke paas" in (await rahul.say("Sector 56 Gurgaon"))[-1]
    conv = await conv_of(qf)
    assert conv.slots.services == ["haircut", "beard trim"] and conv.slots.exact_time


async def test_a_full_request_asks_nothing_but_the_location_pin(qf, rahul):
    out = await rahul.say("haircut kal 6 baje Sector 56 Gurgaon mein chahiye")
    assert "ke paas" in out[-1]  # straight to the shortlist


async def test_for_someone_else_asks_the_name_once(qf, rahul):
    assert (await rahul.say("kisi aur ke liye haircut kal shaam"))[0].startswith("Kiske liye")
    out = await rahul.say("Amit")
    assert out[0].startswith("Aap kahan hain")
    assert (await conv_of(qf)).slots.for_name == "Amit"


async def test_named_person_in_the_request_is_not_asked_again(qf, rahul):
    out = await rahul.say("Amit ke liye haircut kal shaam parlour mein")
    assert out[0].startswith("Aap kahan hain")
    assert (await conv_of(qf)).slots.for_name == "Amit"


# ------------------------------------------------------------------ location
async def test_location_pin_in_gurgaon_works(qf, rahul):
    await rahul.say(REQ)
    out = await rahul.pin(*GURGAON)
    assert "3 jagah mili" in out[-1]
    assert (await conv_of(qf)).slots.location.city == "gurgaon"


async def test_location_pin_in_bangalore_works(qf, rahul):
    await rahul.say(REQ)
    out = await rahul.pin(*BLR)
    assert (await conv_of(qf)).slots.location.city == "bangalore" and "jagah mili" in out[-1]


async def test_wrong_city_pin_and_text(qf, rahul):
    await rahul.say(REQ)
    out = await rahul.pin(19.07, 72.87)  # Mumbai
    assert out == [
        "Abhi sirf Gurgaon aur Bangalore mein kaam karti hoon. Jaldi aur shehar aayenge."
    ]
    assert (await conv_of(qf)).state == State.CANCELLED
    out = await rahul.say("haircut kal shaam Pune mein")
    assert out[0].startswith("Abhi sirf Gurgaon aur Bangalore")


async def test_unclear_location_asks_again_and_city_only_asks_for_the_area(qf, rahul):
    await rahul.say(REQ)
    assert (await rahul.say("Gurgaon"))[0].startswith("Yeh jagah mujhe nahi mili")
    out = await rahul.say("Sector 56 Gurgaon")
    assert "jagah mili" in out[-1]


# ------------------------------------------------------------------ vendor trouble
async def test_no_vendors_found(qf, rahul):
    qf.directory.items = []
    out = await to_shortlist(qf, rahul)
    assert out[-1].startswith("Wahan aas-paas koi aisi jagah nahi mili")
    assert (await conv_of(qf)).asking == "location"


async def test_vendor_without_phone_is_skipped(qf, rahul):
    qf.directory.items = [cand(1, "No Phone Salon", phone=False), cand(2, "Glow Salon")]
    out = await to_shortlist(qf, rahul)
    assert "Glow Salon" in out[-1] and "No Phone Salon" not in out[-1]


async def test_places_failure_is_an_honest_message_not_silence(qf, rahul):
    qf.directory.fail = True
    out = await to_shortlist(qf, rahul)
    assert out[-1] == "Abhi parlour search nahi ho pa raha. Thodi der baad dobara try kijiye."


async def test_change_shows_the_next_places_then_runs_out(qf, rahul):
    await to_shortlist(qf, rahul)
    out = await rahul.tap("Badlo")
    assert "Shine Parlour" in out[-1]
    out = await rahul.tap("Badlo")
    assert out[-1].startswith("Is area mein aur options nahi hain") or "jagah mili" in out[-1]


async def test_all_no_answer_retries_once_then_says_so(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    for name in ("Glow Salon", "Royal Cuts", "Trendz Studio"):
        await qf.calls.finish(name, Outcome.NO_ANSWER)
    assert len(qf.calls.placed) == 3  # the retry pass waits 10 minutes
    qf.clock.advance(minutes=11)
    await qf.flow.tick()
    assert qf.calls.names()[3:4] == ["Glow Salon"]  # one retry each, one at a time
    for name in ("Glow Salon", "Royal Cuts", "Trendz Studio"):
        if name != "Glow Salon":
            await qf.flow.tick()
        await qf.calls.finish(name, Outcome.NO_ANSWER)
    assert len(qf.calls.placed) == 6  # never more than one retry per vendor
    assert rahul.last().startswith("Is baar koi quote nahi mila: kisi ne phone nahi uthaya")
    assert [b.title for b in rahul.last_msg().buttons] == ["Dobara try karo", "Doosre dekho"]


async def test_mixed_results_report_everyone(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    await qf.calls.finish("Glow Salon", Outcome.QUOTE, 400)
    await qf.calls.finish("Royal Cuts", Outcome.DECLINED)
    await qf.calls.finish("Trendz Studio", Outcome.NO_ANSWER)
    qf.clock.advance(minutes=11)
    await qf.flow.tick()
    await qf.calls.finish("Trendz Studio", Outcome.NO_ANSWER)
    last = rahul.last()
    assert "Glow Salon: Rs 400" in last and "1 ne phone nahi uthaya." in last
    assert "1 ne mana kiya." in last


async def test_all_declined(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    for name in ("Glow Salon", "Royal Cuts", "Trendz Studio"):
        await qf.calls.finish(name, Outcome.DECLINED)
    assert "sabne mana kiya" in rahul.last()


async def test_call_that_cannot_be_placed_never_hangs_the_chat(qf, rahul):
    qf.calls.fail_place = True
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")  # each vendor is tried once, then once more after 10 minutes
    qf.clock.advance(minutes=11)
    await qf.flow.tick()
    assert "Is baar koi quote nahi mila" in rahul.last()


# ------------------------------------------------------------------ cancel / stop / change of mind
async def test_stop_mid_flow_cancels_calls_and_everything(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    out = await rahul.say("stop")
    assert out == ["Sab kuch band kar diya. Dobara shuru karna ho to kabhi bhi likhiye."]
    assert qf.calls.cancelled == [qf.calls.placed[0]["task_id"]]
    assert (await conv_of(qf)).state == State.CANCELLED
    await qf.calls.finish("Glow Salon", Outcome.QUOTE, 400)  # a late result changes nothing
    assert len(qf.calls.placed) == 1 and rahul.last().startswith("Sab kuch band")


async def test_cancel_and_no_at_the_approval_step(qf, rahul):
    await to_shortlist(qf, rahul)
    assert (await rahul.say("nahi"))[0].startswith("Theek hai, cancel kar diya")
    assert qf.calls.placed == []
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    assert (await rahul.say("cancel"))[0].startswith("Theek hai, cancel kar diya")


async def test_new_request_replaces_an_open_shortlist(qf, rahul):
    await to_shortlist(qf, rahul)
    out = await rahul.say("facial chahiye aaj shaam Sector 56 Gurgaon")
    assert "facial" in out[-1]


async def test_text_yes_works_like_the_button(qf, rahul):
    await to_shortlist(qf, rahul)
    assert await rahul.say("haan") == []
    assert qf.calls.names() == ["Glow Salon"]


async def test_voice_note_asks_for_text(qf, rahul):
    out = await rahul.say("/voice kal shaam parlour mein haircut chahiye")
    assert out == ["Abhi main voice note nahi sun paati. Text mein likh dijiye please."]
    assert qf.calls.placed == []


# ------------------------------------------------------------------ idempotency
async def test_duplicate_webhook_delivery_is_handled_once(qf, rahul):
    msg = qf.channel.make_inbound(USER_PHONE, REQ)
    await qf.rt.handle(msg)
    await qf.rt.handle(msg)  # Meta retried the same message id
    assert len(rahul.msgs()) == 1
    msg2 = qf.channel.make_inbound(USER_PHONE, "Sector 56 Gurgaon")
    for _ in range(2):
        await qf.rt.handle(msg2)
    assert sum("jagah mili" in t for t in rahul.texts()) == 1


async def test_double_tap_places_the_calls_once(qf, rahul):
    await to_shortlist(qf, rahul)
    go = rahul.last_msg().buttons[0].id
    await rahul.tap_id(go)
    n = len(rahul.msgs())
    await rahul.tap_id(go)  # impatient second tap: new message id, same button
    assert len(qf.calls.placed) == 1 and len(rahul.msgs()) == n
    msg = InboundMessage(channel=rahul.ch.channel, from_phone=USER_PHONE,
                         kind=MessageKind.BUTTON_REPLY, button_id=go, provider_message_id="same")
    await qf.rt.handle(msg)
    await qf.rt.handle(msg)
    assert len(qf.calls.placed) == 1


async def test_someone_elses_button_is_ignored(qf, rahul):
    await to_shortlist(qf, rahul)
    go = rahul.last_msg().buttons[0].id
    other = await make_user(qf, "+919811100002", "Priya")
    await other.tap_id(go)
    assert qf.calls.placed == [] and not other.msgs()


# ------------------------------------------------------------------ caps
async def test_per_user_daily_cap(qf, rahul):
    for _ in range(3):
        await to_shortlist(qf, rahul)
        await rahul.say("cancel")
    out = await rahul.say(REQ)
    assert out == ["Aaj ki 3 requests ho chuki hain. Kal phir bhejiye."]
    qf.clock.advance(hours=24)
    assert (await rahul.say(REQ))[0].startswith("Aap kahan hain")


async def test_cost_cap_per_request_stops_directory_calls(qf, rahul):
    qf.c.settings.quotes_max_places_calls_per_request = 2
    qf.directory.items = [cand(i, f"S{i}", phone=False) for i in range(1, 6)]
    await to_shortlist(qf, rahul)
    assert qf.directory.searches + qf.directory.details_calls <= 2


async def test_concurrent_calls_setting(qf, rahul):
    qf.c.settings.quotes_max_concurrent_calls = 2
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    assert qf.calls.names() == ["Glow Salon", "Royal Cuts"]
    qf.c.settings.quotes_max_concurrent_calls = 9  # clamped to 3 by the flow
    await qf.calls.finish("Glow Salon", Outcome.QUOTE, 400)
    assert len(qf.calls.names()) == 3


# ------------------------------------------------------------------ quiet hours / kill switch
async def test_outside_9_to_7_calls_are_queued_not_placed(qf, rahul):
    qf.clock.advance(hours=8)  # 19:00 IST
    await to_shortlist(qf, rahul)
    out = await rahul.tap("Haan")
    assert out == []  # queued silently; "status" explains
    assert (await rahul.say("status"))[0] == "Calls kal subah 9 baje shuru hongi. Quotes aate hi message karungi."
    assert qf.calls.placed == []
    await qf.flow.tick()
    assert qf.calls.placed == []
    qf.clock.advance(hours=14)  # 09:00 next day
    await qf.flow.tick()
    assert qf.calls.names() == ["Glow Salon"]


async def test_calls_stop_at_7pm_even_mid_list(qf, rahul):
    qf.clock.advance(hours=7, minutes=50)  # 18:50
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    qf.clock.advance(minutes=20)  # 19:10
    await qf.calls.finish("Glow Salon", Outcome.QUOTE, 450)
    assert qf.calls.names() == ["Glow Salon"]  # the next vendor waits for tomorrow
    qf.clock.advance(hours=14)
    await qf.flow.tick()
    assert qf.calls.names() == ["Glow Salon", "Royal Cuts"]


async def test_kill_switch_is_respected(qf, rahul, tmp_path):
    qf.c.settings.pause_file = str(tmp_path / "PAUSED")
    qf.c.settings.paused = True
    await to_shortlist(qf, rahul)
    out = await rahul.tap("Haan")
    assert out[0].startswith("Main thodi der ke break par hoon")
    assert qf.calls.placed == []
    qf.c.settings.paused = False
    assert await rahul.tap("Haan") == []
    assert qf.calls.names() == ["Glow Salon"]


async def test_test_mode_refuses_real_vendors(qf, rahul):
    s = qf.c.settings
    s.pilot_block_business_calls, s.pilot_allowed_numbers = True, ["+918607549916"]
    await to_shortlist(qf, rahul)
    out = await rahul.tap("Haan")
    assert out == ["Test mode mein asli jagah ko call nahi kar sakti. Kisi ko call nahi gaya."]
    assert qf.calls.placed == []


# ------------------------------------------------------------------ language mirroring
async def test_english_user_gets_english(qf, rahul):
    out = await rahul.say("Need a haircut tomorrow evening at a salon please")
    assert out == ["Where are you? Send a location pin, or type it like 'Sector 56 Gurgaon'."]
    out = await rahul.say("Sector 56 Gurgaon")
    assert out[-1].startswith("Found 3 places near Sector 56 Gurgaon")
    assert [b.title for b in rahul.last_msg().buttons] == ["Yes, call them", "Change"]
    await rahul.tap("Yes")
    for name, price in (("Glow Salon", 450), ("Royal Cuts", 800), ("Trendz Studio", 550)):
        await qf.calls.finish(name, Outcome.QUOTE, price)
    assert rahul.last().startswith("Quotes for haircut (tomorrow evening):")


async def test_devanagari_user_gets_devanagari(qf, rahul):
    out = await rahul.say("कल शाम पार्लर में हेयरकट चाहिए")
    assert out == ["आप कहाँ हैं? लोकेशन पिन भेजिए, या लिखिए जैसे 'Sector 56 Gurgaon'।"]
    out = await rahul.say("Sector 56 Gurgaon")
    assert "जगह मिलीं" in out[-1]
    assert [b.title for b in rahul.last_msg().buttons] == ["हाँ, कॉल करो", "बदलो"]


async def test_language_follows_the_user_when_they_switch(qf, rahul):
    await rahul.say(REQ)
    out = await rahul.say("Please send me the options near Sector 56 Gurgaon thanks")
    assert out[-1].startswith("Found")


# ------------------------------------------------------------------ messages are short, honest
async def test_every_message_is_short_and_buttons_fit(qf, rahul):
    await to_shortlist(qf, rahul)
    await rahul.tap("Haan")
    for name, price in (("Glow Salon", 450), ("Royal Cuts", 800), ("Trendz Studio", 550)):
        await qf.calls.finish(name, Outcome.QUOTE, price)
    for m in rahul.msgs():
        assert len(m.text or "") <= 600
        assert all(len(b.title) <= 20 for b in m.buttons) and len(m.buttons) <= 3
        assert not any(ord(ch) > 0x1F000 for ch in (m.text or ""))  # no emoji


async def test_flow_can_be_switched_off(qf, rahul):
    qf.c.settings.quotes_flow_enabled = False
    await rahul.say(REQ)
    assert not (await qf.flow.store.latest_for_user((await rahul.user_row()).id))


_ = (FakeDirectory, timedelta)


async def test_no_stage_pings_by_default_only_ack_questions_and_outcome(qf, rahul):
    await rahul.say(REQ)
    await rahul.say("Sector 56 Gurgaon")
    await rahul.tap("Haan")
    n = len(rahul.msgs())
    await qf.calls.finish("Glow Salon", Outcome.QUOTE, 450)
    await qf.calls.finish("Royal Cuts", Outcome.NO_ANSWER)
    assert len(rahul.msgs()) == n  # per-vendor results and call starts send nothing
    assert [t.split(":")[0][:12] for t in rahul.texts()][:2] == ["Aap kahan ha", "Theek hai, a"]


async def test_updates_switch_turns_progress_messages_on_per_request(qf, rahul):
    await rahul.say(REQ)
    await rahul.say("Sector 56 Gurgaon")
    go = rahul.last_msg().buttons[0].id
    assert (await rahul.say("updates on"))[0].startswith("Theek hai, is request ke progress updates")
    out = await rahul.tap_id(go)
    assert out == ["Theek hai, call kar rahi hoon. Saare quotes ek saath bhejungi."]
    assert (await rahul.say("updates band"))[0].startswith("Theek hai, updates nahi bhejungi")
