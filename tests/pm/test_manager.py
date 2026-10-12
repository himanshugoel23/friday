# ruff: noqa: E501
import json

import pytest

from friday.pm.classifier import Classification, KeywordClassifier, ScriptedClassifier
from friday.pm.manager import ProjectManager
from friday.pm.slots import (
    GuardedRewriter,
    RuleSlotExtractor,
    detect_language,
    is_cancel,
    parse_yes_no,
)
from friday.pm.state import JsonFileTaskStore, MemoryTaskStore, Status
from friday.pm.steps import FakeStepAgents, StepContext, StepResult

FAR = [{"id": "a", "name": "A", "distance_km": 7.0}, {"id": "b", "name": "B", "distance_km": 8.5},
       {"id": "c", "name": "C", "distance_km": 9.0}]


def make(agents=None, store=None, **kw):
    agents = agents or FakeStepAgents()
    pm = ProjectManager(classifier=KeywordClassifier(), agents=agents,
                        store=store or MemoryTaskStore(), id_factory=lambda: "t1", **kw)
    return pm, agents


async def say(pm, text, tid="t1", **kw):
    return await pm.handle_message(text, task_id=None if tid is None else tid, **kw)


def log_kinds(pm, tid="t1"):
    return [d.kind for d in pm.store.load(tid).log]


# ------------------------------------------------------------------------- helpers


def test_language_yesno_cancel():
    assert detect_language("haircut kitna lega") == "hinglish"
    assert detect_language("how much") == "en"
    assert detect_language("हेयरकट कितना") == "hi"
    assert parse_yes_no("haan kar do") is True and parse_yes_no("nahi") is False
    assert parse_yes_no("maybe") is None
    assert is_cancel("cancel") and is_cancel("rehne do") and not is_cancel("cancel my gym booking "
                                                                            "that I made last week with them please")


def test_rule_extractor():
    ex = RuleSlotExtractor()
    s = ex.extract_sync("kal 5 baje haircut book kar do, max 800 for mummy in Sector 45", "salon")
    assert s["budget"] == 800 and s["delegation"] is True and s["for_whom"] == "mummy"
    assert "kal" in s["when"] and s["where"] == "Sector 45"
    assert ex.extract_sync("sirf price batao", "salon")["delegation"] is False
    assert "budget" not in ex.extract_sync("5 km door", "salon")


# ------------------------------------------------------------------------- clarification


async def test_one_question_at_a_time_max_two_rounds_then_defaults():
    pm, _ = make()
    r = await say(pm, "salon", tid=None)  # bucket other + category -> bucket question (round 1)
    assert r.pending_kind == "bucket" and len(r.messages) == 1
    r = await say(pm, "price batao")
    assert r.pending_kind == "slot" and len(r.messages) == 1   # one question: round 2
    task = pm.store.load("t1")
    assert task.rounds_used == 2
    r = await say(pm, "Sector 45 Gurgaon")  # service known from "salon" keyword; where answered
    assert r.pending_kind == "consent"
    assert task.rounds_used <= 2


async def test_stops_politely_when_required_slot_has_no_default():
    pm, _ = make()
    await say(pm, "haircut kitna lega", tid=None)          # asks where (round 1)
    r = await say(pm, "pata nahi")                          # unusable? text accepted as where
    assert pm.store.load("t1").slots["where"]
    # never-answered path: a category with two missing no-default slots
    pm2, _ = make()
    r = await pm2.handle_message("packers movers ka rate", task_id=None)
    assert r.pending_kind == "slot"
    r = await pm2.handle_message("Dwarka", task_id="t1")
    assert r.pending_kind == "slot"          # round 2 (details / when)
    r = await pm2.handle_message("pata nahi", task_id="t1")
    t = pm2.store.load("t1")
    assert t.rounds_used == 2
    assert t.status == Status.STOPPED and t.stop_reason.startswith("missing_slots")


async def test_unclear_category_asks_then_stops():
    pm, _ = make()
    r = await pm.handle_message("hello", task_id=None)
    assert r.pending_kind == "category"
    await pm.handle_message("kuch bhi", task_id="t1")
    r = await pm.handle_message("pata nahi", task_id="t1")
    assert pm.store.load("t1").status == Status.STOPPED
    assert pm.store.load("t1").rounds_used == 2


async def test_non_pm_buckets_are_handed_off():
    pm, agents = make()
    r = await pm.handle_message("salon ki service bahut kharab thi, refund chahiye", task_id=None)
    assert r.status == "handoff" and agents.calls == []


async def test_book_without_delegation_never_books():
    clf = ScriptedClassifier(default=Classification(bucket="book", category="salon", confidence=0.9))
    pm = ProjectManager(classifier=clf, agents=FakeStepAgents(), id_factory=lambda: "t1")
    await pm.handle_message("haircut Sector 45 kal", task_id=None)     # asks delegation? (round 1)
    t = pm.store.load("t1")
    assert t.pending and t.pending.slot == "delegation"
    r = await pm.handle_message("sirf price batao", task_id="t1")
    t = pm.store.load("t1")
    assert t.archetype == "availability" and "archetype_switch" in log_kinds(pm)
    assert t.slots["delegation"] is False
    assert r.pending_kind == "consent"


async def test_profile_places_used_for_parents():
    pm, _ = make()
    prof = {"home_place": "Sector 62 Noida", "parents_place": "Rohini Delhi"}
    await pm.handle_message("mummy ke liye haircut ka rate", task_id=None, profile=prof)
    assert pm.store.load("t1").slots["where"] == "Rohini Delhi"


# ------------------------------------------------------------------------- the quiet rule


async def test_one_ack_then_silence_until_question_or_outcome():
    pm, agents = make()
    r1 = await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    assert r1.pending_kind == "consent"
    assert "Samajh gayi" in r1.messages[0] and len(r1.messages) == 2   # ack + consent question
    r2 = await say(pm, "haan")
    assert len(r2.messages) == 1 and r2.messages[0].startswith("Report")  # outcome only
    task = pm.store.load("t1")
    assert len(task.outbox) == 3                                     # nothing else was said
    assert sum("Samajh gayi" in m for m in task.outbox) == 1


async def test_failures_are_silent_unless_user_must_decide():
    pm, agents = make(FakeStepAgents(pickup={"v1": False}))
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    r = await say(pm, "haan")
    assert len(r.messages) == 1                                       # just the report
    assert "vendor_skipped" in log_kinds(pm)


async def test_progress_messages_only_when_updates_on():
    pm, _ = make()
    r = await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None, updates_on=True)
    assert any("Update:" in m for m in r.messages)
    pm2, _ = make()
    r = await say(pm2, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    assert not any("Update:" in m for m in r.messages)


# ------------------------------------------------------------------------- failures


async def test_widen_flow_and_hard_max():
    pm, agents = make(FakeStepAgents(vendors=FAR))
    r = await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    assert r.pending_kind == "widen" and "8 km" in r.messages[-1]
    r = await say(pm, "haan")           # 8 km: vendor A (7.0) fits
    assert r.pending_kind == "consent"
    task = pm.store.load("t1")
    assert task.radius_km == 8.0
    shortlist = task.outputs["shortlist"]["vendors"]
    assert [v["id"] for v in shortlist] == ["a"]    # B (8.5) is beyond the radius: never shown
    assert "widen_offered" in log_kinds(pm) and "widen_accepted" in log_kinds(pm)


async def test_nothing_within_hard_max_stops():
    pm, _ = make(FakeStepAgents(vendors=[{"id": "x", "name": "X", "distance_km": 30}]))
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    await say(pm, "haan")     # 5 -> 8
    r = await say(pm, "haan")   # 8 -> 10
    t = pm.store.load("t1")
    assert t.status == Status.STOPPED and t.stop_reason == "no_vendors_within_hard_max"
    assert "10 km" in r.messages[-1]


async def test_widen_declined():
    pm, _ = make(FakeStepAgents(vendors=FAR))
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    await say(pm, "nahi")
    assert pm.store.load("t1").stop_reason == "widen_declined"


async def test_distance_is_a_hard_filter_even_if_an_agent_misbehaves():
    bad = [{"id": "far", "name": "Far", "distance_km": 55}, {"id": "nod", "name": "NoDist"},
           {"id": "ok", "name": "Ok", "distance_km": 3}]
    ag = FakeStepAgents(overrides={"shortlist": [StepResult(status="ok", data={"vendors": bad})]})
    pm, _ = make(ag)
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    t = pm.store.load("t1")
    assert [v["id"] for v in t.outputs["shortlist"]["vendors"]] == ["ok"]
    assert log_kinds(pm).count("distance_violation") == 2


async def test_no_pickup_goes_to_next_vendor_and_all_fail_stops():
    pm, ag = make(FakeStepAgents(pickup={"v1": False}))
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    await say(pm, "haan")
    calls = [v for s, v in ag.calls if s == "calls"]
    assert calls == ["v1", "v2", "v3", "v4"]       # v1 skipped, then 3 answered
    pm2, _ = make(FakeStepAgents(pickup={"v1": False, "v2": False, "v3": False, "v4": False}))
    await say(pm2, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    r = await say(pm2, "haan")
    assert pm2.store.load("t1").stop_reason == "all_vendors_failed"
    assert "phone nahi uthaya" in r.messages[-1]


async def test_book_stops_at_first_success():
    clf = ScriptedClassifier(default=Classification(bucket="book", category="salon", confidence=0.9))
    ag = FakeStepAgents(pickup={"v1": False})
    pm = ProjectManager(classifier=clf, agents=ag, id_factory=lambda: "t1")
    await pm.handle_message("book kar do haircut Sector 45 kal 5 baje", task_id=None)
    await pm.handle_message("haan", task_id="t1")
    assert [v for s, v in ag.calls if s == "calls"] == ["v1", "v2"]
    assert pm.store.load("t1").status == Status.DONE


async def test_over_budget_asks_user():
    ag = FakeStepAgents(prices={"v1": 900, "v2": 950, "v3": 1000})
    pm, _ = make(ag)
    await say(pm, "haircut Sector 45 Gurgaon max 500 kitna lega", tid=None)
    r = await say(pm, "haan")
    assert r.pending_kind == "over_budget" and "500" in r.messages[0] and "900" in r.messages[0]
    r = await say(pm, "haan")
    assert r.status == "done"


async def test_retryable_step_failure_then_stop():
    ag = FakeStepAgents(overrides={"search": [StepResult(status="failed", reason="timeout",
                                                         retryable=True)]})
    pm, _ = make(ag)
    r = await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    assert r.pending_kind == "consent"                       # one retry fixed it
    ag2 = FakeStepAgents(overrides={"search": [StepResult(status="failed", reason="x")]})
    pm2, _ = make(ag2)
    await say(pm2, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    assert pm2.store.load("t1").stop_reason == "step_failed:search:x"


async def test_agent_exception_is_contained():
    class Boom(FakeStepAgents):
        async def run(self, step, ctx):
            raise RuntimeError("secret detail")

    pm, _ = make(Boom())
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    t = pm.store.load("t1")
    assert t.status == Status.STOPPED and "exception:RuntimeError" in t.stop_reason


async def test_step_needs_user_question():
    ag = FakeStepAgents(overrides={"locate": [
        StepResult(status="needs_user", question="Which Sector 45: Gurgaon or Noida?")]})
    pm, _ = make(ag)
    r = await say(pm, "haircut Sector 45 kitna lega", tid=None)
    assert r.pending_kind == "step_question" and "Gurgaon or Noida" in r.messages[-1]
    r = await say(pm, "Gurgaon")
    assert r.pending_kind == "consent"


async def test_consent_declined_and_policy_block():
    pm, ag = make()
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    await say(pm, "nahi")
    assert pm.store.load("t1").stop_reason == "consent_declined"
    assert "calls" not in [s for s, _ in ag.calls]
    ag2 = FakeStepAgents(overrides={"consent": [StepResult(status="failed",
                                                           reason="blocked_by_policy")]})
    pm2, _ = make(ag2)
    await say(pm2, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    await say(pm2, "haan")
    assert pm2.store.load("t1").stop_reason == "step_failed:consent:blocked_by_policy"
    assert "calls" not in [s for s, _ in ag2.calls]


# ------------------------------------------------------------------------- interruptions


async def test_cancel_at_any_time():
    pm, ag = make()
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    r = await say(pm, "rehne do")
    t = pm.store.load("t1")
    assert t.status == Status.CANCELLED and "interrupt_cancel" in log_kinds(pm)
    assert all(s.status in ("done", "skipped") for s in t.plan)
    assert "calls" not in [s for s, _ in ag.calls]
    r = await say(pm, "haan")
    assert "band ho chuki" in r.messages[0]


async def test_change_replans_from_the_affected_step():
    pm, ag = make()
    await say(pm, "is there a slot at a salon in Indiranagar tomorrow 5 pm", tid=None)
    n_search = [s for s, _ in ag.calls].count("search")
    r = await say(pm, "actually make it tomorrow 7 pm")
    t = pm.store.load("t1")
    assert t.slots["when"] == "tomorrow 7 pm" and "replan" in log_kinds(pm)
    assert [s for s, _ in ag.calls].count("search") == n_search       # no re-search for a time
    assert r.pending_kind == "consent"
    # changing the place re-runs locate and search
    await say(pm, "nahi Sector 45 Gurgaon mein")
    assert [s for s, _ in ag.calls].count("search") == n_search + 1


async def test_change_after_done_is_refused_cleanly_and_new_task_needed():
    pm, _ = make()
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    await say(pm, "haan")
    r = await say(pm, "kal 7 baje")
    assert r.status == "done" and "band ho chuki" in r.messages[0]


# ------------------------------------------------------------------------- persistence


async def test_resume_after_restart(tmp_path):
    store = JsonFileTaskStore(tmp_path)
    pm, _ = make(store=store)
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    assert (tmp_path / "t1.json").exists()
    json.loads((tmp_path / "t1.json").read_text())                 # plain JSON
    pm2, ag2 = make(store=JsonFileTaskStore(tmp_path))             # "restart"
    r = await pm2.resume("t1")
    assert "Shortlist" in r.messages[0]                            # waiting question re-sent
    r = await pm2.handle_message("haan", task_id="t1")
    assert r.status == "done"
    assert [s for s, _ in ag2.calls][0] == "consent"               # earlier steps not repeated


async def test_resume_reruns_a_step_caught_mid_run():
    pm, ag = make()
    await say(pm, "haircut Sector 45 Gurgaon kitna lega", tid=None)
    t = pm.store.load("t1")
    t.pending, t.status = None, Status.RUNNING
    t.plan[7].status = "running"            # calls was interrupted by a crash
    t.outputs["_consent_user"] = True
    t.plan[6].status = "done"
    pm.store.save(t)
    await pm.resume("t1")
    assert pm.store.load("t1").status == Status.DONE and "resumed_step" in log_kinds(pm)


# ------------------------------------------------------------------------- boundaries


async def test_step_context_has_no_free_text_scripts():
    assert set(StepContext.model_fields) == {
        "task_id", "step", "bucket", "category", "slots", "radius_km", "hard_max_km",
        "n_vendors", "outputs", "vendor", "user_answer", "language"}


async def test_guarded_rewriter():
    async def good(t, lang):
        return "Kis area mein dekhun? (jaise Sector 45 Gurgaon)"

    async def lies(t, lang):
        return "Kis area mein dekhun? Call 9999999999?"

    async def boom(t, lang):
        raise RuntimeError

    base = "Kis area ya locality mein dekhun? (jaise Sector 45 Gurgaon)"
    assert await GuardedRewriter(good).write("where", base, "hinglish") == "Kis area mein dekhun? (jaise Sector 45 Gurgaon)"
    assert await GuardedRewriter(lies).write("where", base, "hinglish") == base
    assert await GuardedRewriter(boom).write("where", base, "hinglish") == base
    pm, _ = make(writer=GuardedRewriter(good))
    r = await pm.handle_message("haircut kitna lega", task_id=None)
    assert r.messages == ["Kis area mein dekhun? (jaise Sector 45 Gurgaon)"]


# ------------------------------------------------------------------------- channels


async def test_call_turn_short_question_background_and_whatsapp_outcome():
    pm, ag = make()
    t1 = await pm.handle_turn(None, "gym ki membership kitne ki hai", "call")
    assert t1.reply_text == "Kaunse area mein?" and t1.pending_slot == "where"
    t2 = await pm.handle_turn(t1.task_id, "Sector 62 Noida", "call")
    assert "WhatsApp" in t2.reply_text and t2.background and not t2.done
    assert [s for s, _ in ag.calls] == []                      # call turn stayed short
    bg = await pm.run_background(t1.task_id)
    assert bg.deliver_via == "whatsapp_text" and "Shortlist" in bg.messages[0]
    t3 = await pm.handle_turn(t1.task_id, "haan", "whatsapp_text")
    assert t3.done and t3.reply_text.startswith("Report")


async def test_call_defers_long_input_to_whatsapp():
    pm, _ = make()
    t = await pm.handle_turn(None, "packers movers ka rate chahiye Dwarka mein, kal", "call")
    assert "WhatsApp" in t.reply_text and len(t.whatsapp) == 1
    assert "BHK" in t.whatsapp[0]
    t = await pm.handle_turn(t.task_id, "2 BHK to Noida", "call")     # not taken by voice
    assert "WhatsApp" in t.reply_text
    assert "details" not in pm.store.load("t1").slots
    t = await pm.handle_turn(t.task_id, "2 BHK Dwarka se Noida", "whatsapp_text")
    assert t.pending_kind == "consent"


async def test_call_stop_is_also_sent_on_whatsapp():
    pm, _ = make()
    t = await pm.handle_turn(None, "hello", "call")
    assert t.reply_text == "Sorry, what service do you need?"
    t = await pm.handle_turn(t.task_id, "kuch", "call")
    t = await pm.handle_turn(t.task_id, "pata nahi", "call")
    assert t.done and len(t.whatsapp) == 1


async def test_unknown_channel_rejected():
    pm, _ = make()
    with pytest.raises(ValueError):
        await pm.handle_turn(None, "hi", "telegram")
