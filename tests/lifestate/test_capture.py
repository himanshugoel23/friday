"""Hinglish capture: a big table of messages -> what Friday understood.

Clock: Monday 19 Oct 2026, 3 pm IST.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from friday.core.clock import IST, to_ist
from friday.lifestate.capture import PendingCapture, capture_message, parse_message, undo_last
from friday.lifestate.models import EventKind
from friday.lifestate.ports import LLMExtraction

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=IST)


def at(day: int, hour: int, minute: int = 0, month: int = 10, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=IST)


IV, M, A, T, P, B = (
    EventKind.INTERVIEW,
    EventKind.MEETING,
    EventKind.APPOINTMENT,
    EventKind.TRAVEL,
    EventKind.PERSONAL,
    EventKind.BILL_DUE,
)

# (message, status, kind, expected start in IST, word expected in the title)
EVENT_CASES = [
    ("kal 2 baje interview hai", "event", IV, at(20, 14), "interview"),
    ("parso shaam 6 baje dentist", "event", A, at(21, 18), "dentist"),
    ("bijli ka bill 20 ko", "bill", B, at(20, 9), "bijli"),
    ("kal subah 7 baje flight hai", "event", T, at(20, 7), "flight"),
    ("kal 10:30 baje meeting hai", "event", M, at(20, 10, 30), "meeting"),
    ("kal 10.30 baje meeting hai", "event", M, at(20, 10, 30), "meeting"),
    ("kal 2pm interview hai", "event", IV, at(20, 14), "interview"),
    ("kal 2 pm interview hai", "event", IV, at(20, 14), "interview"),
    ("kal 11 am meeting hai", "event", M, at(20, 11), "meeting"),
    ("kal 14:00 meeting hai", "event", M, at(20, 14), "meeting"),
    ("kal 9 baje meeting hai", "event", M, at(20, 9), "meeting"),
    ("kal 5 baje dentist hai", "event", A, at(20, 17), "dentist"),
    ("kal teen baje interview hai", "event", IV, at(20, 15), "interview"),
    ("kal do baje meeting hai", "event", M, at(20, 14), "meeting"),
    ("kal dopahar 1 baje doctor appointment hai", "event", A, at(20, 13), "doctor"),
    ("kal dopahar 12 baje meeting hai", "event", M, at(20, 12), "meeting"),
    ("kal shaam 7 baje party hai", "event", P, at(20, 19), "party"),
    ("kal 7 baje dinner hai", "event", P, at(20, 19), "dinner"),
    ("kal subah 11 baje interview hai", "event", IV, at(20, 11), "interview"),
    ("saade 3 baje interview hai kal", "event", IV, at(20, 15, 30), "interview"),
    ("kal saadhe 4 baje meeting hai", "event", M, at(20, 16, 30), "meeting"),
    ("dhai baje doctor appointment hai parso", "event", A, at(21, 14, 30), "doctor"),
    ("kal dedh baje meeting hai", "event", M, at(20, 13, 30), "meeting"),
    ("paune 5 baje dentist hai kal", "event", A, at(20, 16, 45), "dentist"),
    ("kal sawa 4 baje meeting hai", "event", M, at(20, 16, 15), "meeting"),
    ("raat 12 baje meeting hai", "event", M, at(20, 0), "meeting"),  # midnight ending today
    ("kal raat 12 baje flight hai", "event", T, at(21, 0), "flight"),  # end of kal
    ("kal raat 1 baje flight hai", "event", T, at(21, 1), "flight"),  # after kal's midnight
    ("aaj raat 9 baje dinner hai", "event", P, at(19, 21), "dinner"),
    ("aaj shaam 6 baje meeting hai", "event", M, at(19, 18), "meeting"),
    ("agle somvar 11 baje meeting hai", "event", M, at(26, 11), "meeting"),
    ("somvar ko 10 baje interview hai", "event", IV, at(26, 10), "interview"),
    ("mangalvar ko 10 baje interview hai", "event", IV, at(20, 10), "interview"),
    ("guruvar subah 9 baje meeting hai", "event", M, at(22, 9), "meeting"),
    ("next friday 4 baje meeting hai", "event", M, at(23, 16), "meeting"),
    ("agle hafte shukravar 4 baje meeting hai", "event", M, at(30, 16), "meeting"),
    ("ravivar ko 6 baje party hai", "event", P, at(25, 18), "party"),
    ("20 oct ko dentist 5 baje", "event", A, at(20, 17), "dentist"),
    ("5 november ko interview 11 baje", "event", IV, at(5, 11, month=11), "interview"),
    ("interview 25/10 ko 3 baje", "event", IV, at(25, 15), "interview"),
    ("interview 25/12/2026 ko 3 baje", "event", IV, at(25, 15, month=12), "interview"),
    ("3 din baad dentist 5 baje", "event", A, at(22, 17), "dentist"),
    ("2 hafte baad interview 10 baje", "event", IV, at(2, 10, month=11), "interview"),
    ("2 ghante baad meeting hai", "event", M, at(19, 17), "meeting"),
    ("aadha ghanta baad meeting hai", "event", M, at(19, 15, 30), "meeting"),
    ("30 minute mein meeting hai", "event", M, at(19, 15, 30), "meeting"),
    ("6 baje dentist hai", "event", A, at(19, 18), "dentist"),  # still ahead today
    ("2 baje meeting hai", "event", M, at(20, 14), "meeting"),  # 2 pm is over -> tomorrow
    ("kal 2 se 3 baje meeting hai", "event", M, at(20, 14), "meeting"),
    ("kal 2 baje se 4 baje tak interview hai", "event", IV, at(20, 14), "interview"),
    ("kal 10 se 11 am meeting hai", "event", M, at(20, 10), "meeting"),
    ("Kal 2 BAJE Interview Hai", "event", IV, at(20, 14), "nterview"),
]

BILL_CASES = [
    ("bijli ka bill 20 ko", at(20, 9)),
    ("wifi bill 5 tarikh", at(5, 9, month=11)),  # the 5th already passed -> next month
    ("credit card bill month end tak", at(31, 9)),
    ("insurance premium 30 october tak", at(30, 9)),
    ("gas bill agle mahine 10 tarikh", at(10, 9, month=11)),
    ("emi 31 ko", at(31, 9)),
]


@pytest.mark.parametrize("text,status,kind,start,title", EVENT_CASES)
def test_event_table(text, status, kind, start, title):
    p = parse_message(text, NOW)
    assert p.status == status, (text, p)
    assert p.kind == kind, (text, p)
    assert p.start is not None
    assert to_ist(p.start) == start, (text, to_ist(p.start), start)
    assert title.lower() in p.title.lower(), (text, p.title)


@pytest.mark.parametrize("text,start", BILL_CASES)
def test_bill_table(text, start):
    p = parse_message(text, NOW)
    assert p.status == "bill", (text, p)
    assert p.kind == EventKind.BILL_DUE
    assert to_ist(p.start) == start, (text, to_ist(p.start))


def test_table_has_at_least_forty_cases():
    assert len(EVENT_CASES) + len(BILL_CASES) >= 40


def test_month_end_in_a_short_month_and_next_month():
    p = parse_message("bill month end tak hai", datetime(2026, 2, 10, 9, tzinfo=IST))
    assert to_ist(p.start).date().isoformat() == "2026-02-28"
    p = parse_message("bill agle mahine ke end tak hai", NOW)
    assert to_ist(p.start).date().isoformat() == "2026-11-30"


def test_day_31_clamped_in_short_month():
    p = parse_message("bijli bill 31 ko", datetime(2026, 11, 2, 9, tzinfo=IST))
    assert to_ist(p.start).date().isoformat() == "2026-11-30"


def test_leap_year_date():
    p = parse_message("dentist 29 feb ko 4 baje", datetime(2027, 12, 1, 9, tzinfo=IST))
    assert to_ist(p.start).date().isoformat() == "2028-02-29"


def test_agle_weekday_on_the_same_weekday_is_next_week():
    p = parse_message("agle somvar 11 baje meeting hai", NOW)  # today is Monday
    assert to_ist(p.start).date().isoformat() == "2026-10-26"


def test_plain_weekday_today_with_time_already_over_means_next_week():
    p = parse_message("somvar 11 baje meeting hai", NOW)  # Monday 3 pm now; 11 am is over
    assert to_ist(p.start).date().isoformat() == "2026-10-26"


def test_monthly_bill_repeat():
    p = parse_message("internet bill har mahine 5 tarikh", NOW)
    assert p.status == "bill" and p.repeat is not None
    assert p.repeat.freq == "monthly" and p.repeat.day_of_month == 5


def test_end_time_range_sets_duration():
    p = parse_message("kal 2 se 4 baje meeting hai", NOW)
    assert (p.end - p.start).total_seconds() == 2 * 3600


# --------------------------------------------------------------------------- commitments
def test_recurring_medicine_commitment():
    p = parse_message("mummy ki dawai 8 baje roz", NOW)
    assert p.status == "commitment"
    assert p.repeat is not None and p.repeat.freq == "daily" and p.repeat.time == "08:00"
    assert to_ist(p.start) == at(20, 8)  # next 8 am after 3 pm
    assert p.person is not None and p.person.relationship == "mother"
    assert "dawai" in p.title


def test_weekly_repeat():
    p = parse_message("har somvar subah 9 baje gym yaad dilana", NOW)
    assert p.status == "commitment"
    assert p.repeat and p.repeat.freq == "weekly" and p.repeat.weekdays == [0]
    assert to_ist(p.start) == at(26, 9)


def test_call_mummy_tonight_is_a_commitment():
    p = parse_message("aaj raat mummy ko call karna hai", NOW)
    assert p.status == "commitment"
    assert to_ist(p.start) == at(19, 21)
    assert p.person and p.person.name == "mummy"


def test_reminder_phrase():
    p = parse_message("kal subah 6 baje yaad dilana passport lena hai", NOW)
    assert p.status == "commitment"
    assert to_ist(p.start) == at(20, 6)


# --------------------------------------------------------------------------- clarify / none
@pytest.mark.parametrize(
    "text,reason",
    [
        ("interview hai", "no_when"),
        ("kal interview hai", "no_time"),
        ("kal 12 baje meeting hai", "ask_12"),
        ("12 baje meeting hai", "ask_12"),
        ("kal interview tha", "kal_past"),
        ("agle hafte meeting hai", "week_only"),
        ("bill hai", "no_when"),
    ],
)
def test_one_clarifying_question(text, reason):
    p = parse_message(text, NOW)
    assert p.status == "clarify", (text, p)
    assert p.reason == reason
    assert p.question and p.question.count("?") == 1


@pytest.mark.parametrize(
    "text",
    [
        "hello kaise ho",
        "kal kya hai?",
        "book kar do kal dentist",
        "kal 2 baje doctor ko call kar do",
        "mujhe ek plumber chahiye",
        "",
        "x" * 700,
    ],
)
def test_not_a_life_statement(text):
    assert parse_message(text, NOW).status == "none"


async def test_clarify_then_answer_combines_both_messages(world, now):
    r1 = await capture_message(world.store, world.u1, "interview hai", now)
    assert r1.status == "clarify" and r1.pending is not None
    r2 = await capture_message(world.store, world.u1, "kal 2 baje", now, pending=r1.pending)
    assert r2.status == "captured"
    assert r2.events[0].kind == EventKind.INTERVIEW
    assert to_ist(r2.events[0].start) == at(20, 14)


async def test_ambiguous_twelve_asks_once_then_resolves(world, now):
    r1 = await capture_message(world.store, world.u1, "kal 12 baje meeting hai", now)
    assert r1.status == "clarify"
    r2 = await capture_message(world.store, world.u1, "raat", now, pending=r1.pending)
    assert r2.status == "captured" and to_ist(r2.events[0].start) == at(21, 0)


async def test_confirmation_states_the_resolved_day_and_time(world, now):
    r = await capture_message(world.store, world.u1, "kal 2 baje interview hai", now)
    assert "kal" in r.reply and "dopahar 2 baje" in r.reply and "interview" in r.reply


async def test_saying_it_twice_does_not_duplicate(world, now):
    await capture_message(world.store, world.u1, "kal 2 baje interview hai", now)
    await capture_message(world.store, world.u1, "kal 2 baje interview hai", now)
    assert len(await world.store.list_events(world.u1)) == 1


async def test_clash_is_mentioned(world, now):
    await capture_message(world.store, world.u1, "kal 2 baje interview hai", now)
    r = await capture_message(world.store, world.u1, "kal 2:30 baje dentist hai", now)
    assert r.clashes and "interview" in r.reply


async def test_bill_is_not_protected_and_events_are(world, now):
    a = await capture_message(world.store, world.u1, "bijli ka bill 20 ko", now)
    b = await capture_message(world.store, world.u1, "kal 2 baje interview hai", now)
    assert a.events[0].protected is False and b.events[0].protected is True


async def test_undo_removes_only_the_latest_fresh_item(world, now):
    await capture_message(world.store, world.u1, "kal 2 baje interview hai", now)
    await capture_message(world.store, world.u1, "parso 6 baje dentist hai", now)
    assert await undo_last(world.store, world.u1, now)
    left = await world.store.list_events(world.u1)
    assert [e.kind for e in left] == [EventKind.INTERVIEW]


async def test_recurring_commitment_is_stored_with_person(world, now):
    r = await capture_message(world.store, world.u1, "mummy ki dawai 8 baje roz", now)
    c = r.commitments[0]
    assert c.repeat and c.person and c.person.name == "mummy"
    assert "roz" in r.reply


# --------------------------------------------------------------------------- LLM hook
class FakeLLM:
    def __init__(self, got):
        self.got, self.calls = got, 0

    async def extract(self, text, now):
        self.calls += 1
        if isinstance(self.got, Exception):
            raise self.got
        return self.got


async def test_llm_hook_only_runs_when_rules_find_nothing(world, now):
    llm = FakeLLM(LLMExtraction(title="Yoga class", start=at(21, 7), kind="personal"))
    r = await capture_message(world.store, world.u1, "kal 2 baje interview hai", now, llm=llm)
    assert llm.calls == 0 and r.status == "captured"
    r = await capture_message(world.store, world.u1, "arre haan wo yoga wali cheez", now, llm=llm)
    assert llm.calls == 1 and r.status == "captured" and r.via_llm
    assert r.events[0].title == "Yoga class"


@pytest.mark.parametrize(
    "got",
    [
        LLMExtraction(title="", start=at(21, 7)),
        LLMExtraction(title="x", start=at(1, 7, month=1, year=2020)),  # long past
        LLMExtraction(title="x", start=at(21, 7, year=2030)),  # too far
        LLMExtraction(title="x", start=at(21, 7), end=at(20, 7)),  # end before start
        RuntimeError("boom"),
        None,
    ],
)
async def test_llm_proposals_are_validated(world, now, got):
    llm = FakeLLM(got)
    r = await capture_message(world.store, world.u1, "arre wo cheez yaad hai na", now, llm=llm)
    assert r.status == "none"
    assert await world.store.list_events(world.u1) == []


async def test_llm_not_asked_for_questions_or_task_requests(world, now):
    llm = FakeLLM(LLMExtraction(title="x", start=at(21, 7)))
    await capture_message(world.store, world.u1, "kal kya hai?", now, llm=llm)
    await capture_message(world.store, world.u1, "dentist book kar do", now, llm=llm)
    assert llm.calls == 0


def test_pending_capture_type():
    assert PendingCapture("a").text == "a"
