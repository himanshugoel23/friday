# ruff: noqa: E501
"""The scenario runner: approval phrase, countdown, cancel, one at a time, ledger, notes. Fakes only."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from friday.qa import override
from friday.qa import scenarios as sc
from friday.qa.config import APPROVAL_PHRASE
from friday.qa.models import CallReport
from friday.qa.runner import QaRunner
from friday.qa.safety import QaRefused
from tests.qa.conftest import NUMBER, OTHER, World, _no_sleep, fake_shortlist


async def test_call_needs_the_exact_approval_phrase(world: World) -> None:
    for bad in ("", "yes", "YES", "yes, call my phone", "YES call my phone"):
        with pytest.raises(QaRefused) as e:
            await world.runner.start("salon_quote", bad)
        assert e.value.code == "not_approved"
    assert world.calls.specs == []


async def test_a_call_runs_with_countdown_then_dials_the_allow_listed_number(world: World) -> None:
    run = await world.runner.start("salon_quote", APPROVAL_PHRASE)
    await world.runner.wait(run.id)
    assert run.phase == "done"
    assert any("Ring now in 3 seconds" in line for line in run.lines)
    (spec,) = world.calls.specs
    assert spec.number == NUMBER and spec.seconds <= 180
    assert spec.vendor_name == "Shreya Salon"  # the real vendor name is kept in the script
    assert run.report and run.report.status == "completed"
    # the QA override was on during the call and is off afterwards
    assert world.calls.active_during[0] is not None and override.active() is None


async def test_ledger_and_run_row_are_written(world: World) -> None:
    run = await world.runner.start("vendor_table", APPROVAL_PHRASE)
    await world.runner.wait(run.id)
    calls, spend = world.store.today()
    assert calls == 1 and spend == 3.5
    (row,) = world.store.runs()
    assert row["scenario"] == "vendor_table" and row["real"] and row["simulated"]
    assert row["transcript"][0]["who"] == "friday"


async def test_cancel_during_countdown_dials_nothing(tmp_path: Path) -> None:
    w = World(tmp_path, countdown_s=30)
    gate = asyncio.Event()

    async def slow(_s: float) -> None:
        await gate.wait()

    w.runner.sleep = slow
    run = await w.runner.start("salon_quote", APPROVAL_PHRASE)
    await asyncio.sleep(0)
    assert run.phase == "countdown"
    w.runner.cancel(run.id)
    gate.set()
    await w.runner.wait(run.id)
    assert run.phase == "cancelled" and w.calls.specs == []
    assert w.store.today() == (0, 0.0)


async def test_kill_switch_is_checked_again_right_before_the_dial(world: World) -> None:
    async def pause_during_countdown(_s: float) -> None:
        world.paused = True

    world.runner.sleep = pause_during_countdown
    run = await world.runner.start("salon_quote", APPROVAL_PHRASE)
    await world.runner.wait(run.id)
    assert run.phase == "refused" and "kill switch" in run.error.lower()
    assert world.calls.specs == []


async def test_kill_switch_stops_a_start(world: World) -> None:
    world.paused = True
    with pytest.raises(QaRefused) as e:
        await world.runner.start("salon_quote", APPROVAL_PHRASE)
    assert e.value.code == "kill_switch"


async def test_only_one_run_at_a_time(world: World) -> None:
    hold = asyncio.Event()
    world.calls.hold = hold
    run = await world.runner.start("salon_quote", APPROVAL_PHRASE)
    await asyncio.sleep(0.01)
    with pytest.raises(QaRefused) as e:
        await world.runner.start("vendor_table", APPROVAL_PHRASE)
    assert e.value.code == "busy"
    hold.set()
    await world.runner.wait(run.id)


async def test_hangup_is_forwarded_to_the_backend(world: World) -> None:
    world.calls.hold = asyncio.Event()
    run = await world.runner.start("salon_quote", APPROVAL_PHRASE)
    for _ in range(20):
        await asyncio.sleep(0.01)
        if run.phase == "in_call":
            break
    world.runner.cancel(run.id)
    await world.runner.wait(run.id)
    assert world.calls.hung == 1


async def test_a_phone_number_is_never_a_parameter(world: World) -> None:
    for params in ({"number": OTHER}, {"vendor": f"Shop {OTHER}"}, {"area": "call 9876543210"}):
        with pytest.raises(QaRefused):
            await world.runner.start("salon_quote", APPROVAL_PHRASE, params)
    assert world.calls.specs == []


async def test_unknown_parameters_are_refused(world: World) -> None:
    with pytest.raises(QaRefused) as e:
        await world.runner.start("salon_quote", APPROVAL_PHRASE, {"to": "x"})
    assert e.value.code == "bad_parameter"


async def test_the_dialled_number_ignores_anything_in_the_scenario(world: World) -> None:
    for s in sc.SCENARIOS:
        assert OTHER not in " ".join(s.texts()) and NUMBER not in " ".join(s.texts())


async def test_chat_scenario_needs_no_approval_and_calls_no_one(world: World) -> None:
    run = await world.runner.start("chat_text", "")
    await world.runner.wait(run.id)
    assert run.phase == "done" and world.chat.ran == ["chat_text"] and world.calls.specs == []
    assert world.store.today() == (0, 0.0)


async def test_info_scenarios_have_nothing_to_run(world: World) -> None:
    with pytest.raises(QaRefused) as e:
        await world.runner.start("frontdoor_inbound", APPROVAL_PHRASE)
    assert e.value.code == "nothing_to_run"


async def test_urgent_scenario_waits_n_minutes_visibly(tmp_path: Path) -> None:
    w = World(tmp_path, countdown_s=3, urgent_wait_minutes=2)
    ticks: list[float] = []

    async def count(s: float) -> None:
        ticks.append(s)

    w.runner.sleep = count
    run = await w.runner.start("urgent_escalation", APPROVAL_PHRASE)
    await w.runner.wait(run.id)
    assert len(ticks) == 3 + 120 and run.phase == "done"


async def test_plan_shows_masked_number_shortlist_and_real_vs_simulated(world: World) -> None:
    plan = await world.runner.plan("salon_quote")
    assert plan["number"].endswith("42") and NUMBER not in str(plan)
    assert plan["shortlist"]["items"][0]["name"] == "Shreya Salon"
    assert plan["vendor"] == "Shreya Salon" and plan["real"] and plan["simulated"]
    assert plan["approval_phrase"] == APPROVAL_PHRASE and plan["est_cost_inr"] > 0


async def test_failure_after_dial_still_counts_against_the_caps(world: World) -> None:
    async def boom(spec, emit):  # noqa: ANN001, ANN202
        raise RuntimeError("provider exploded " + NUMBER)

    world.calls.run = boom  # type: ignore[method-assign]
    run = await world.runner.start("salon_quote", APPROVAL_PHRASE)
    await world.runner.wait(run.id)
    assert run.phase == "failed" and NUMBER[3:-2] not in run.error
    assert world.store.today()[0] == 1


async def test_report_refused_is_a_failed_run(world: World) -> None:
    world.calls.report = CallReport(status="refused", summary="not allow-listed")
    run = await world.runner.start("salon_quote", APPROVAL_PHRASE)
    await world.runner.wait(run.id)
    assert run.phase == "failed" and run.error == "not allow-listed"


def test_runner_default_shortlist_is_text_only(world: World) -> None:
    r = QaRunner(
        world.guard,
        world.store,
        world.calls,
        world.chat,
        qa=world.qa,
        sleep=_no_sleep,
        shortlist_fn=fake_shortlist,
    )
    assert r.list_scenarios()[0]["id"] == "salon_quote"
