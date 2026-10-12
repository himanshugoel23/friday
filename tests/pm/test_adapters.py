"""RealStepAgents driven by the real ProjectManager, with fake scouting and a fake call placer."""

from __future__ import annotations

from friday.core.models import BusinessCandidate, GeoPoint
from friday.pm.adapters import CallResult, RealStepAgents
from friday.pm.classifier import KeywordClassifier
from friday.pm.manager import ProjectManager
from friday.pm.state import MemoryTaskStore
from friday.scouting.models import (
    EligibilityResult,
    RankedItem,
    RankedShortlist,
    ScoutPlace,
    ScoutRequest,
    ScoutResult,
    SearchResult,
)


def item(i, name, km, *, phone=True, beyond=False):
    c = BusinessCandidate(
        provider="fake", place_id=f"p{i}", name=name, phone=f"+9112450000{i}" if phone else None,
        category="salon", rating=4.5, review_count=200, distance_km=km,
    )
    return RankedItem(rank=i, place=ScoutPlace(candidate=c), distance_km=km,
                      beyond_default_radius=beyond, score=1.0, components={}, reasons=["ok"])


def result(req, items):
    return ScoutResult(
        request=req, search=SearchResult(places=[]),
        eligibility=EligibilityResult(eligible=[], dropped=[]),
        shortlist=RankedShortlist(items=items),
    )


class FakePlacer:
    def __init__(self, outcomes):
        self.outcomes, self.placed, self.polls = outcomes, [], 0

    async def place(self, ctx, vendor):
        self.placed.append(vendor["id"])
        return vendor["id"]

    async def report(self, handle):
        self.polls += 1
        if self.polls == 1:
            return CallResult(finished=False)
        o = self.outcomes[handle]
        return CallResult(True, o[0], o[1])


async def _nosleep(_s):
    return None


def build(items, outcomes, *, policy=None, located=True):
    async def scout_fn(req: ScoutRequest):
        assert req.near is not None and req.radius_km
        return result(req, items)

    async def resolve(area):
        return GeoPoint(lat=28.42, lng=77.1) if located else None

    placer = FakePlacer(outcomes)
    agents = RealStepAgents(scout_fn=scout_fn, resolve_fn=resolve, placer=placer, policy=policy,
                            sleep=_nosleep, poll_s=0.0)
    pm = ProjectManager(classifier=KeywordClassifier(), agents=agents, store=MemoryTaskStore(),
                        id_factory=lambda: "t1")
    return pm, placer


ITEMS = [item(1, "Glow", 1.0), item(2, "Style", 2.0), item(3, "Cuts", 3.0),
         item(4, "FarOne", 4.0, beyond=True), item(5, "NoPhone", 1.5, phone=False)]


async def drive(pm, text, answers=()):
    r = await pm.handle_message(text, task_id=None)
    for a in answers:
        r = await pm.handle_message(a, task_id=r.task_id)
    return r


async def test_end_to_end_quotes_reach_the_report_and_skip_beyond_radius_and_no_phone():
    outcomes = {"p1": ("quote", 600), "p2": ("quote", 450), "p3": ("no_answer", None)}
    pm, placer = build(ITEMS, outcomes)
    r = await drive(pm, "haircut kitna lega", ["Sector 45 Gurgaon", "haan"])
    task = pm.store.load("t1")
    assert set(placer.placed) <= {"p1", "p2", "p3"} and "p4" not in placer.placed
    assert "p5" not in placer.placed
    text = " ".join(r.messages)
    assert "450" in text and "Style" in text
    assert task.outputs["compare"]["best"] == "p2"


async def test_policy_block_stops_before_any_call():
    async def deny(ctx):
        return False, "outside calling hours"

    pm, placer = build(ITEMS, {}, policy=deny)
    await drive(pm, "haircut kitna lega", ["Sector 45 Gurgaon", "haan"])
    assert placer.placed == []
    assert pm.store.load("t1").status.value in ("blocked", "failed", "stopped", "done", "cancelled")


async def test_unknown_area_asks_the_user():
    pm, _ = build(ITEMS, {}, located=False)
    r = await drive(pm, "haircut kitna lega", ["Sector 45 Gurgaon", "haan"])
    assert r.pending_kind == "step_question"
