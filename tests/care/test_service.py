# ruff: noqa: E501
"""Care protocol state machine, check-ins (fake clock), gate, family consent, elder wording, copy."""

from __future__ import annotations

import re
from datetime import datetime

from friday.care import CareService, Tier, copy
from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.scale import MemoryCache

U = "user-1"
FORBIDDEN = re.compile(
    r"depress|diagnos|disorder|cheer up|everything will be|it will be okay|you will be fine|be positive|"
    r"think of the good|feelings are not facts|not a fact|order|shopping|\bjob\b|\bbuy\b|offer|feature|plan your",
    re.I,
)


def make(start=None, **kw):
    clock = FakeClock(start or datetime(2026, 1, 5, 14, 0, tzinfo=IST))
    sent: list[tuple[str, str]] = []

    async def sender(uid, text):
        sent.append((uid, text))

    svc = CareService(MemoryCache(clock), clock, sender=sender, **kw)
    return svc, clock, sent


# ------------------------------------------------------------------ the reply protocol
async def test_high_first_reply_shape_en():
    svc, _, _ = make()
    t = await svc.screen(U, "I want to die")
    assert t.tier == Tier.HIGH and t.redact and len(t.replies) == 1
    text = t.replies[0]
    lines = text.split("\n")
    assert 2 <= len(lines) <= 4
    assert "14416" in text and "112" in text
    assert text.count("?") == 1 and "hurting yourself" in text  # the direct question, once
    assert "trust" in text  # offer to draft a message for the user to send


async def test_question_is_asked_once_per_episode():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    for msg in ["I want to die", "I really want to kill myself", "no point living"]:
        t = await svc.screen(U, msg)
        assert "hurting yourself?" not in t.replies[0]
        assert "14416" in t.replies[0]


async def test_answer_yes_and_no_then_family_question():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    t = await svc.screen(U, "yes")
    assert "14416" in t.replies[0] and len(t.replies) == 2 and "yes or no" in t.replies[1]
    svc2, _, _ = make()
    await svc2.screen(U, "I want to die")
    t = await svc2.screen(U, "no")
    assert "staying right here" in t.replies[0]


async def test_draft_for_a_trusted_person_user_sends_it_themselves():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    await svc.screen(U, "no")
    t = await svc.screen(U, "my sister")
    text = t.replies[0]
    assert "sister" in text and "can't send it myself" in text
    t2 = await svc.screen(U, "Please yes")  # not a name, nothing breaks
    assert t2 is not None


async def test_named_person_after_the_ask():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    await svc.screen(U, "no")
    await svc.screen(U, "family reply yes")  # not a yes/no: held
    st = await svc.store.get(U)
    st.awaiting = "person"
    await svc.store.put(U, st)
    t = await svc.screen(U, "Riya")
    assert "Hi Riya" in t.replies[0]


async def test_no_diagnosis_no_pep_talk_no_product_chatter_in_any_line():
    for key, per_lang in copy.LINES.items():
        for lang, text in per_lang.items():
            if key == "paused_task":
                continue  # the one plain line about the open request
            assert not FORBIDDEN.search(text), (key, lang)


async def test_mirror_language():
    svc, _, _ = make()
    t = await svc.screen(U, "मैं मरना चाहता हूँ")
    assert "मुझे" in t.replies[0]
    svc2, _, _ = make()
    t = await svc2.screen(U, "mujhe jeene ka mann nahi karta")
    assert "Tele-MANAS 14416" in t.replies[0] and "aap" in t.replies[0].lower()
    t = await svc2.screen(U, "haan")  # a short answer keeps the language
    assert "shukriya" in t.replies[0].lower()


async def test_elevated_acknowledge_one_question_helpline_once():
    svc, _, _ = make()
    t = await svc.screen(U, "I feel hopeless")
    assert t.tier == Tier.ELEVATED and t.replies[0].count("?") == 1 and "14416" in t.replies[0]
    assert not await svc.blocked(U)  # ELEVATED does not stop features
    t2 = await svc.screen(U, "I am worthless")
    assert "14416" not in t2.replies[0]  # the helpline is mentioned once


async def test_third_party_line():
    svc, _, _ = make()
    t = await svc.screen(U, "my friend says he wants to die")
    assert t.tier == Tier.ELEVATED and "112" in t.replies[0]


async def test_ordinary_messages_are_not_touched():
    svc, _, _ = make()
    assert await svc.screen(U, "order milk") is None
    assert await svc.screen(U, "suicide prevention app idea") is None
    assert not await svc.blocked(U)


# ------------------------------------------------------------------ gate and release
async def test_gate_holds_neutral_messages_then_lets_the_user_through():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    assert await svc.blocked(U) and await svc.is_active(U)
    t1 = await svc.screen(U, "order milk")
    t2 = await svc.screen(U, "order milk")
    assert t1 and t2 and t1.replies != t2.replies and "14416" in t1.replies[0]
    assert await svc.screen(U, "order milk") is None  # third: the user is moving on
    assert not await svc.is_active(U)


async def test_okay_releases_and_cancels_checkins():
    svc, clock, sent = make()
    await svc.screen(U, "I want to die")
    t = await svc.screen(U, "I'm okay now")
    assert t.release and not await svc.blocked(U)
    clock.advance(hours=30)
    assert await svc.tick() == [] and sent == []


async def test_stop_releases_and_cancels_checkins():
    svc, clock, sent = make()
    await svc.screen(U, "I want to die")
    t = await svc.screen(U, "stop")
    assert t.release and "won't check in" in t.replies[0]
    clock.advance(hours=30)
    assert await svc.tick() == [] and sent == []


async def test_okay_with_ideation_in_the_same_message_stays_high():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    t = await svc.screen(U, "I'm okay but I still want to die")
    assert not t.release and await svc.blocked(U)


async def test_gate_expires_after_the_hold_window():
    svc, clock, _ = make()
    await svc.screen(U, "I want to die")
    clock.advance(hours=37)
    assert not await svc.blocked(U)


async def test_kill_switch_only_in_dev_and_test():
    svc, _, _ = make()
    svc.settings = Settings(_env_file=None, env="test", care_kill_switch=True)
    assert await svc.screen(U, "I want to die") is None
    svc.settings = Settings(_env_file=None, env="prod", care_kill_switch=True)
    assert svc.enabled and await svc.screen(U, "I want to die") is not None


async def test_no_feature_switch_can_turn_it_off():
    # nothing in Settings other than the test-only kill switch refers to care
    names = [n for n in Settings.model_fields if n.startswith("care_") and any(w in n for w in ("enable", "switch", "disable", "off"))]
    assert names == ["care_kill_switch"]


async def test_delete_everything_erases_state():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    await svc.forget(U)
    assert await svc.store.get(U) is None and not await svc.blocked(U)
    assert await svc.store.active_ids() == []


async def test_state_holds_no_user_words():
    svc, _, _ = make()
    await svc.screen(U, "I want to die, my name is Sunita and I live at 12 Park Road")
    await svc.screen(U, "no")
    await svc.screen(U, "Riya")
    blob = repr(svc.store.cache._data)
    assert "Sunita" not in blob and "Park Road" not in blob and "Riya" not in blob and "die" not in blob


# ------------------------------------------------------------------ own-number call
async def test_call_offer_only_when_allowed_and_only_on_explicit_yes():
    placed: list[str] = []

    async def allowed(uid):
        return True

    async def place(uid):
        placed.append(uid)
        return True

    svc, _, _ = make(call_allowed=allowed, place_call=place)
    await svc.screen(U, "I want to die")
    t = await svc.screen(U, "no")
    assert any("call me" in r for r in t.replies) and placed == []
    t = await svc.screen(U, "maybe later")  # no explicit request: no call
    assert placed == []
    t = await svc.screen(U, "call me")
    assert placed == [U] and "calling your number" in t.replies[0]


async def test_no_call_offer_by_default_or_when_not_allowed():
    async def denied(uid):
        return False

    for svc in (make()[0], make(call_allowed=denied)[0]):
        await svc.screen(U, "I want to die")
        t = await svc.screen(U, "no")
        assert not any("call me" in r for r in t.replies)
        t = await svc.screen(U, "call me")
        assert "can't place that call" in t.replies[0]


# ------------------------------------------------------------------ pausing open work
async def test_open_request_is_paused_with_one_plain_line():
    calls = []

    async def pause(uid):
        calls.append(uid)
        return True

    svc, _, _ = make(pause_work=pause)
    t = await svc.screen(U, "I want to die")
    assert t.replies[-1] == copy.line("paused_task", "en") and len(t.replies) == 2
    t = await svc.screen(U, "I want to die")
    assert calls == [U] and copy.line("paused_task", "en") not in t.replies


# ------------------------------------------------------------------ check-ins on a fake clock
async def test_same_day_then_next_morning_then_stop():
    svc, clock, sent = make(datetime(2026, 1, 5, 14, 0, tzinfo=IST))
    await svc.screen(U, "I want to die")
    assert await svc.tick() == []
    clock.advance(hours=3)
    assert await svc.tick() == []  # not yet (4 h of quiet)
    clock.advance(hours=1, minutes=1)
    await svc.tick()
    assert len(sent) == 1 and "checking in" in sent[0][1]
    clock.advance(hours=1)
    await svc.tick()
    assert len(sent) == 1  # once
    clock.set(datetime(2026, 1, 6, 8, 30, tzinfo=IST))
    await svc.tick()
    assert len(sent) == 1  # not before 09:00
    clock.set(datetime(2026, 1, 6, 9, 5, tzinfo=IST))
    await svc.tick()
    assert len(sent) == 2 and "Good morning" in sent[1][1]
    for h in (1, 5, 24):
        clock.advance(hours=h)
        await svc.tick()
    assert len(sent) == 2  # then stop


async def test_same_day_checkin_may_land_in_quiet_hours_but_morning_never_does():
    svc, clock, sent = make(datetime(2026, 1, 5, 22, 30, tzinfo=IST))
    await svc.screen(U, "I want to die")
    clock.set(datetime(2026, 1, 5, 23, 30, tzinfo=IST))  # 22:30 + 4h is capped to 23:30 (still the same day)
    await svc.tick()
    assert len(sent) == 1
    clock.set(datetime(2026, 1, 6, 7, 0, tzinfo=IST))
    await svc.tick()
    assert len(sent) == 1
    clock.set(datetime(2026, 1, 6, 9, 0, tzinfo=IST))
    await svc.tick()
    assert len(sent) == 2


async def test_a_message_resets_the_quiet_period():
    svc, clock, sent = make()
    await svc.screen(U, "I want to die")
    clock.advance(hours=3)
    await svc.screen(U, "still here, I want to die")
    clock.advance(hours=3)
    await svc.tick()
    assert sent == []  # only 3 h since the last message
    clock.advance(hours=1.1)
    await svc.tick()
    assert len(sent) == 1


async def test_checkin_failure_is_retried_next_tick():
    svc, clock, _ = make()
    fails = {"n": 1}
    got = []

    async def flaky(uid, text):
        if fails["n"]:
            fails["n"] = 0
            raise RuntimeError("down")
        got.append(text)

    svc.sender = flaky
    await svc.screen(U, "I want to die")
    clock.advance(hours=5)
    await svc.tick()
    assert got == []
    await svc.tick()
    assert len(got) == 1


async def test_tick_respects_shard_ownership():
    svc, clock, sent = make()
    await svc.screen(U, "I want to die")
    clock.advance(hours=5)
    await svc.tick(owns=lambda uid: False)
    assert sent == []
    await svc.tick(owns=lambda uid: True)
    assert len(sent) == 1


# ------------------------------------------------------------------ family consent
async def test_family_line_needs_consent_default_is_nothing_shared():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    assert await svc.family_line(U, "Sunita") is None  # not asked yet / no consent
    await svc.screen(U, "no")  # safety answer, then the family question
    assert await svc.family_line(U, "Sunita") is None
    await svc.screen(U, "no")  # family: no
    assert await svc.family_line(U, "Sunita") is None


async def test_family_consent_yes_gives_the_single_plain_line_once():
    svc, _, _ = make()
    await svc.screen(U, "I want to die")
    await svc.screen(U, "no")
    t = await svc.screen(U, "yes")
    assert "will not share what you wrote" in t.replies[0]
    line = await svc.family_line(U, "Sunita Devi")
    assert line == "Sunita Devi may need you, please call."
    assert "die" not in line and "suicid" not in line.lower()
    assert await svc.family_line(U, "Sunita Devi") is None  # once per episode


async def test_family_line_hinglish_and_hindi():
    svc, _, _ = make()
    await svc.screen(U, "mujhe jeene ka mann nahi karta")
    await svc.screen(U, "haan")
    await svc.screen(U, "haan")
    assert await svc.family_line(U, "Papa") == "Papa ko aapki zarurat ho sakti hai, please call kijiye."


async def test_emergency_words_override_consent():
    svc, _, _ = make()
    await svc.screen(U, "I took all my pills, call an ambulance")
    assert await svc.family_line(U, "Sunita") == "Sunita may need you, please call."


async def test_family_line_is_clean_of_injected_name_content():
    svc, _, _ = make()
    await svc.screen(U, "I took all my pills")
    line = await svc.family_line(U, "Ravi <b>http://x.y</b> 9876543210")
    assert "http" not in line and "9876543210" not in line and "<" not in line


async def test_elevated_only_never_produces_a_family_line():
    svc, _, _ = make()
    await svc.screen(U, "I feel hopeless")
    assert await svc.family_line(U, "Sunita") is None


# ------------------------------------------------------------------ elder wording
async def test_elder_speaker_gets_the_plain_variants():
    svc, _, _ = make()
    t = await svc.screen(U, "mujhe jeene ka mann nahi karta", elder=True)
    text = t.replies[0]
    assert text == copy.line("high_first", "hinglish", elder=True) != copy.line("high_first", "hinglish")
    assert "muft" in text and "14416" in text and "112" in text and text.count("?") == 1
    for line in text.split("\n"):
        assert len(line.split()) <= 20  # short sentences
    t = await svc.screen(U, "haan")
    assert t.replies[0] == copy.line("answer_yes", "hinglish", elder=True)


async def test_elder_check_hook():
    async def elder(uid):
        return True

    svc, _, _ = make(elder_check=elder)
    t = await svc.screen(U, "I want to die")
    assert t.replies[0] == copy.line("high_first", "en", elder=True)
    clock = svc.clock
    clock.advance(hours=5)
    sent = []

    async def sender(uid, text):
        sent.append(text)

    svc.sender = sender
    await svc.tick()
    assert sent == [copy.line("checkin_same_day", "en", elder=True)]


def test_elder_lines_exist_in_all_languages_and_stay_short():
    elder_keys = [k for k in copy.LINES if k.endswith("_elder")]
    assert {"high_first_elder", "answer_yes_elder", "answer_no_elder", "stay_elder", "elevated_first_elder"} <= set(elder_keys)
    for k in elder_keys:
        assert set(copy.LINES[k]) == set(copy.LANGUAGES)
        for text in copy.LINES[k].values():
            assert len(text.split("\n")) <= 4
            assert not FORBIDDEN.search(text)


# ------------------------------------------------------------------ copy structure
def test_every_line_in_three_languages_no_emoji_and_few_questions():
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
    for key, per_lang in copy.LINES.items():
        assert set(per_lang) == set(copy.LANGUAGES), key
        for lang, text in per_lang.items():
            assert text.strip() and not emoji.search(text), (key, lang)
            assert text.count("?") + text.count("？") <= 2, (key, lang)
    assert copy.PENDING_FOUNDER_APPROVAL and copy.HELPLINE == "14416" and copy.EMERGENCY == "112"


def test_helplines_named_in_every_support_line():
    for key in ("high_first", "answer_yes", "answer_no", "stay"):
        for lang in copy.LANGUAGES:
            text = copy.line(key, lang)
            assert "14416" in text and "112" in text, (key, lang)
