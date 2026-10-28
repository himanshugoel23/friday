# ruff: noqa: E501
"""Scenario catalog rules, the live-backend refusals, the subprocess backend, the shortlist, the chat
backend and the report. No real call, no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from friday.playbooks.model import PENDING_DIR, get_playbook
from friday.qa import report as qa_report
from friday.qa import scenarios as sc
from friday.qa.config import APPROVAL_PHRASE
from friday.qa.live import REPORT_PREFIX, LabChat, LiveBackend, SubprocessBackend, shortlist
from friday.qa.models import CallSpec
from tests.qa.conftest import NUMBER, OTHER, World, make_settings

CALL_BACKENDS = {"playbook", "consumer", "goal", "speak", "ring", "urgent"}


def test_every_scenario_states_real_and_simulated_parts() -> None:
    for s in sc.SCENARIOS:
        assert s.real and s.simulated and s.steps and s.hear and s.title, s.id
    assert len({s.id for s in sc.SCENARIOS}) == len(sc.SCENARIOS)


def test_call_scenarios_have_a_known_backend_and_need_approval() -> None:
    for s in sc.SCENARIOS:
        if s.kind == sc.KIND_CALL:
            assert s.spec["backend"] in CALL_BACKENDS and s.needs_approval, s.id
        else:
            assert not s.needs_approval and s.kind in {sc.KIND_CHAT, sc.KIND_INFO}, s.id


def test_required_scenarios_exist() -> None:
    ids = set(sc.BY_ID)
    assert {
        "salon_quote",
        "vendor_table",
        "vendor_home_service",
        "vendor_stock_price",
        "vendor_hotel",
        "vendor_cab",
        "vendor_rental",
        "vendor_banquet",
        "consumer_family",
        "receptionist_greeting",
        "receptionist_forwarding_ring",
        "urgent_escalation",
        "trip_hotel_call",
        "refund_followup",
        "care_hold_rehearsal",
        "frontdoor_inbound",
        "chat_text",
        "chat_voice_note",
        "chat_documents",
    } <= ids


def test_no_scenario_asks_for_otp_pin_or_payment() -> None:
    for s in sc.SCENARIOS:
        assert not sc.has_secret_prompt(s), s.id
    assert sc.SECRET_WORDS.search("please tell me the OTP")


def test_no_scenario_carries_a_phone_number() -> None:
    import re

    for s in sc.SCENARIOS:
        assert not re.search(r"\d{8,}", " ".join(s.texts())), s.id


def test_vendor_scenarios_fill_every_required_input_of_their_playbook() -> None:
    """The pending archetype's required inputs are all covered, so the real call can be built."""
    base = {"user_first_name", "business_name"}
    for s in sc.SCENARIOS:
        if s.spec.get("backend") != "playbook":
            continue
        pb = get_playbook(s.spec["playbook"], PENDING_DIR if s.spec["pending"] else None)
        given = set(base) | set(s.spec["inputs"]) | {"service"}
        if s.spec.get("date_window"):
            given.add("date_window")
        missing = [
            n
            for n, spec in pb.inputs.items()
            if spec.required and n not in given and not spec.default
        ]
        assert not missing, (s.id, missing)
        assert set(s.spec["inputs"]) <= set(pb.inputs), (
            s.id,
            set(s.spec["inputs"]) - set(pb.inputs),
        )


def test_playbook_brief_accepts_the_scenario_inputs() -> None:
    from friday.playbooks.model import clear_pending_for_test, use_pending_for_test
    from friday.playbooks.select import playbook_test_brief

    use_pending_for_test()
    try:
        s = sc.get("vendor_table")
        brief = playbook_test_brief(
            "table_booking",
            to=NUMBER,
            user_first_name="Himanshu",
            max_seconds=180,
            from_number=None,
            service="table",
            date_window=s.spec["date_window"],
            salon_name="Spice Route Restaurant",
            extra_inputs=s.spec["inputs"],
        )
    finally:
        clear_pending_for_test()
    assert brief.playbook_inputs["people_count"] == "4"
    assert (
        brief.playbook_inputs["business_name"] == "Spice Route Restaurant"
    )  # the real vendor name


# ----------------------------------------------------------------------------- live backend
async def test_live_backend_refuses_outside_a_qa_session() -> None:
    spec = CallSpec(
        scenario=sc.get("salon_quote"), number=NUMBER, seconds=60, run_id="r", first_name="H"
    )
    with pytest.raises(RuntimeError, match="QaGuard.session"):
        await LiveBackend(make_settings(), None).run(spec, lambda _l: None)


async def test_live_backend_refuses_a_number_that_is_not_the_allow_listed_one(world: World) -> None:
    spec = CallSpec(
        scenario=sc.get("salon_quote"), number=OTHER, seconds=60, run_id="r", first_name="H"
    )
    with world.guard.session("salon_quote", "r"), pytest.raises(RuntimeError, match="allow-listed"):
        await LiveBackend(world.settings, world.qa).run(spec, lambda _l: None)


async def test_live_backend_playbook_call_goes_through_run_livecall(
    world: World, monkeypatch
) -> None:  # noqa: ANN001
    """The real code path is `friday.pilot.run_livecall`; here it is replaced by a recorder."""
    import friday.pilot as pilot

    seen: dict = {}

    async def fake_livecall(settings, to, **kw):  # noqa: ANN001, ANN202
        seen.update(to=to, **kw)
        kw["out"]("Placing the call... answer your phone")
        kw["out"](f"  To        : {to}")
        kw["out"]("Dial status   : answered")
        kw["out"]("Outcome        : success")
        kw["out"]("Duration      : 51 s (talk time)")
        return 0

    monkeypatch.setattr(pilot, "run_livecall", fake_livecall)
    spec = CallSpec(
        scenario=sc.get("vendor_table"),
        number=NUMBER,
        seconds=120,
        run_id="r1",
        first_name="Himanshu",
        vendor_name="Spice Route Restaurant",
    )
    emitted: list[str] = []
    with world.guard.session("vendor_table", "r1"):
        rep = await LiveBackend(world.settings, world.qa).run(spec, emitted.append)
    assert seen["to"] == NUMBER and seen["yes"] is True and seen["simulate"] is False
    assert seen["playbook"] == "table_booking" and seen["max_seconds"] == 120
    assert seen["playbook_args"]["salon_name"] == "Spice Route Restaurant"
    assert seen["playbook_args"]["extra_inputs"] == {"people_count": "4"}
    assert rep.status == "completed" and rep.duration_s == 51
    assert all(NUMBER[3:-2] not in line for line in emitted)  # the number is masked in the live log


async def test_pending_playbook_directory_is_used_only_during_the_call(
    world: World, monkeypatch
) -> None:  # noqa: ANN001
    import friday.pilot as pilot
    from friday.playbooks import model

    during: list = []

    async def fake_livecall(settings, to, **kw):  # noqa: ANN001, ANN202
        during.append(model._TEST_DIR)
        return 0

    monkeypatch.setattr(pilot, "run_livecall", fake_livecall)
    spec = CallSpec(
        scenario=sc.get("vendor_hotel"), number=NUMBER, seconds=60, run_id="r", first_name="H"
    )
    with world.guard.session("vendor_hotel", "r"):
        await LiveBackend(world.settings, world.qa).run(spec, lambda _l: None)
    assert during == [model.PENDING_DIR] and model._TEST_DIR is None


def test_pending_playbook_line_is_logged_by_id_only_on_a_qa_call(world: World) -> None:
    from types import SimpleNamespace

    from friday.playbooks.engine import PlaybookPolicy
    from friday.playbooks.model import DATA_DIR

    ctx = SimpleNamespace(dyn_answer=None, value=lambda name: "x")
    pending = get_playbook("table_booking", PENDING_DIR)
    line_id = next(iter(pending.lines))
    approved = get_playbook("salon_booking", DATA_DIR)
    approved_line = next(iter(approved.lines))
    render = PlaybookPolicy._render
    render(None, pending, line_id, ctx)  # outside QA: nothing is logged
    assert world.store.pending_heard() == {}
    with world.guard.session("vendor_table", "r7"):
        render(None, pending, line_id, ctx)
        render(None, approved, approved_line, ctx)  # an approved script is never logged
    assert list(world.store.pending_heard()) == [f"table_booking.{line_id}"]


# ----------------------------------------------------------------------------- subprocess
def test_subprocess_command_never_carries_the_number() -> None:
    spec = CallSpec(
        scenario=sc.get("salon_quote"),
        number=NUMBER,
        seconds=90,
        run_id="abc",
        first_name="Himanshu",
        vendor_name="Shreya Salon",
        area="Gurugram",
    )
    cmd = SubprocessBackend().command(spec)
    assert NUMBER not in " ".join(cmd) and "salon_quote" in cmd and APPROVAL_PHRASE in cmd


async def test_subprocess_backend_reads_the_report_and_masks_numbers(tmp_path: Path) -> None:
    script = tmp_path / "fake_friday.py"
    script.write_text(
        "import json, sys\n"
        "print('Placing the call... To +919800000042')\n"
        f"print({REPORT_PREFIX!r} + json.dumps({{'status': 'completed', 'duration_s': 33.0, 'cost_inr': 2.0, 'summary': 'ok'}}))\n"
    )
    be = SubprocessBackend(base_cmd=[sys.executable, str(script)])
    spec = CallSpec(
        scenario=sc.get("salon_quote"), number=NUMBER, seconds=60, run_id="r", first_name="H"
    )
    lines: list[str] = []
    rep = await be.run(spec, lines.append)
    assert rep.status == "completed" and rep.duration_s == 33.0
    assert lines and NUMBER[3:-2] not in lines[0] and lines[0].endswith("42")


async def test_subprocess_without_a_report_is_a_failed_run(tmp_path: Path) -> None:
    script = tmp_path / "boom.py"
    script.write_text("import sys\nprint('crash')\nsys.exit(3)\n")
    be = SubprocessBackend(base_cmd=[sys.executable, str(script)])
    spec = CallSpec(
        scenario=sc.get("salon_quote"), number=NUMBER, seconds=60, run_id="r", first_name="H"
    )
    rep = await be.run(spec, lambda _l: None)
    assert rep.status == "failed" and "exit 3" in rep.summary


# ----------------------------------------------------------------------------- shortlist
class Cand:
    def __init__(self, name: str) -> None:
        self.name, self.rating, self.address, self.phone = name, 4.5, "Sector 1", "+919876543210"


class Dir:
    async def search(self, query: str, location: str, **kw):  # noqa: ANN001, ANN202
        return [Cand("Glow Salon"), Cand("Looks Studio")]


async def test_shortlist_is_names_only_never_a_phone() -> None:
    out = await shortlist(make_settings(), "salon", "Gurugram", directory=Dir())
    assert out["source"] == "places" and [i["name"] for i in out["items"]] == [
        "Glow Salon",
        "Looks Studio",
    ]
    assert "9876543210" not in json.dumps(out) and all("phone" not in i for i in out["items"])


async def test_shortlist_falls_back_to_sample_names_when_places_fails() -> None:
    class Broken:
        async def search(self, *a, **k):  # noqa: ANN002, ANN003, ANN202
            raise RuntimeError("quota")

    out = await shortlist(make_settings(), "salon", "Gurugram", directory=Broken())
    assert out["source"] == "sample" and out["items"] and "not from Places" in out["note"]
    no_key = await shortlist(make_settings(), "restaurant", "Gurugram")
    assert no_key["source"] == "sample"


# ----------------------------------------------------------------------------- chat + report
async def test_chat_scenario_runs_on_the_lab_simulator(tmp_path: Path) -> None:
    chat = LabChat(tmp_path / "lab_notes.jsonl")
    try:
        lines: list[str] = []
        rep = await chat.run(sc.get("chat_text"), lines.append)
    finally:
        await chat.close()
    assert rep.status == "chat" and any(t["who"] == "friday" for t in rep.transcript)
    assert any(x.startswith("You (text)") for x in lines)


def test_report_lists_verdicts_and_pending_ids(world: World) -> None:
    world.store.add_note("salon_quote", "ok", "good")
    world.store.add_note("vendor_table", "wording", "too long")
    with world.guard.session("vendor_table", "r5"):
        from friday.qa import override

        override.note_pending_line("playbook:table_booking", "table_booking.hook")
    world.store.add_line_decision("table_booking.hook", "approve")
    text = qa_report.render(world.store)
    assert "OK" in text and "wording change" in text and "not yet judged" in text
    assert (
        "approve" in text and "table_booking.hook" in text and "(heard 1x in vendor_table)" in text
    )
    data = qa_report.build(world.store)
    assert data["pending_lines"][0]["decision"] == "approve"
