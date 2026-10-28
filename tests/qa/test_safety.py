"""Safety gates: QA mode switch, allow-list, caps, kill switch, override scope. Fakes only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from friday.qa import override
from friday.qa.config import HARD_MAX_CALL_SECONDS, QaConfig
from friday.qa.safety import QaGuard, QaRefused, startup_problems
from friday.qa.store import QaStore
from tests.qa.conftest import NUMBER, OTHER, World, make_qa, make_settings


def test_qa_mode_is_off_by_default() -> None:
    assert QaConfig().live is False
    assert any("FRIDAY_QA_LIVE" in p for p in startup_problems(make_settings(), QaConfig()))


@pytest.mark.parametrize(
    "kw,needle",
    [
        ({"mode": "simulator"}, "FRIDAY_MODE"),
        ({"profile": "default"}, "FRIDAY_PROFILE"),
        ({"pilot_allowed_numbers": []}, "exactly one"),
        ({"pilot_allowed_numbers": [NUMBER, OTHER]}, "exactly one"),
    ],
)
def test_refuses_to_start_unless_environment_is_exact(
    tmp_path: Path, kw: dict, needle: str
) -> None:
    problems = startup_problems(make_settings(**kw), make_qa(tmp_path))
    assert any(needle in p for p in problems)
    guard = QaGuard(make_settings(**kw), make_qa(tmp_path), QaStore(tmp_path))
    with pytest.raises(QaRefused):
        guard.require_startable()


def test_starts_when_everything_is_right(world: World) -> None:
    assert world.guard.problems() == []
    assert world.guard.target == NUMBER


def test_number_is_only_shown_as_last_two_digits(world: World) -> None:
    masked = world.guard.masked_target
    assert masked.endswith("42") and NUMBER[3:-2] not in masked


def test_only_the_allow_listed_number_may_be_called(world: World) -> None:
    assert world.guard.check_call(NUMBER)[0] == NUMBER
    with pytest.raises(QaRefused) as e:
        world.guard.check_call(OTHER)
    assert e.value.code == "number_not_allowed"
    assert OTHER[3:-2] not in str(e.value)  # refusal text is masked too


def test_a_flow_that_supplies_another_number_is_refused(world: World) -> None:
    with pytest.raises(QaRefused):
        world.guard.check_call(NUMBER, extra_numbers=(OTHER,))
    with pytest.raises(QaRefused):
        world.guard.check_call(None)


def test_kill_switch_is_honoured(world: World) -> None:
    world.paused = True
    with pytest.raises(QaRefused) as e:
        world.guard.check_call(NUMBER)
    assert e.value.code == "kill_switch"


def test_real_pause_flag_is_read(tmp_path: Path) -> None:
    flag = tmp_path / "paused"
    flag.write_text("paused\n")
    s = make_settings(pause_file=str(flag))
    guard = QaGuard(s, make_qa(tmp_path), QaStore(tmp_path / "s"))
    with pytest.raises(QaRefused) as e:
        guard.check_call(NUMBER)
    assert e.value.code == "kill_switch"


def test_call_length_is_capped_at_three_minutes(tmp_path: Path) -> None:
    qa = make_qa(tmp_path, call_seconds=600)
    assert qa.seconds == HARD_MAX_CALL_SECONDS == 180
    guard = QaGuard(make_settings(), qa, QaStore(tmp_path / "s"))
    assert guard.check_call(NUMBER, 900)[1] == 180
    assert guard.clamp_seconds(10) == 30


def test_daily_call_cap(world: World) -> None:
    for _ in range(world.qa.max_calls_per_day):
        world.guard.record_call("x", 10, 1.0)
    with pytest.raises(QaRefused) as e:
        world.guard.check_call(NUMBER)
    assert e.value.code == "daily_call_cap"


def test_default_caps_are_20_calls_and_100_rupees() -> None:
    qa = QaConfig()
    assert qa.max_calls_per_day == 20 and qa.max_spend_inr == 100.0


def test_daily_spend_cap(tmp_path: Path) -> None:
    w = World(tmp_path, max_spend_inr=10.0)
    w.guard.record_call("x", 100, 9.0)
    with pytest.raises(QaRefused) as e:
        w.guard.check_call(NUMBER, 180)
    assert e.value.code == "daily_spend_cap"


def test_caps_count_only_today(world: World) -> None:
    store = world.store
    store.add_ledger("old", 100, 99.0, now=datetime(2020, 1, 1, tzinfo=UTC))
    assert store.today() == (0, 0.0)
    world.guard.check_call(NUMBER)


# ----------------------------------------------------------------------------- override scope
def test_override_is_off_outside_a_session(world: World) -> None:
    assert override.active() is None
    assert override.override_allows(NUMBER, world.settings) is False
    assert override.pending_lines_allowed(world.settings) is False


def test_override_is_on_only_inside_a_session_and_only_for_the_number(world: World) -> None:
    with world.guard.session("salon_quote", "r1"):
        assert override.override_allows(NUMBER, world.settings) is True
        assert override.override_allows(OTHER, world.settings) is False
        assert override.pending_lines_allowed(world.settings) is True
    assert override.override_allows(NUMBER, world.settings) is False  # off again


def test_override_is_off_again_after_an_error(world: World) -> None:
    with pytest.raises(RuntimeError), world.guard.session("x"):
        raise RuntimeError("boom")
    assert override.active() is None


def test_override_does_not_work_in_the_wrong_environment(world: World) -> None:
    with world.guard.session("x"):
        assert override.override_allows(NUMBER, make_settings(mode="simulator")) is False
        assert override.override_allows(NUMBER, make_settings(profile="default")) is False
        assert (
            override.pending_lines_allowed(make_settings(pilot_allowed_numbers=[NUMBER, OTHER]))
            is False
        )


def test_session_refuses_without_qa_mode(tmp_path: Path) -> None:
    guard = QaGuard(make_settings(), make_qa(tmp_path, live=False), QaStore(tmp_path))
    with pytest.raises(QaRefused), guard.session("x"):
        pass


def test_pending_line_is_logged_only_inside_a_session(world: World) -> None:
    override.note_pending_line("urgent", "urg.ring.urgent.hinglish")
    assert world.store.pending_heard() == {}
    with world.guard.session("urgent_escalation", "r9"):
        override.note_pending_line("urgent", "urg.ring.urgent.hinglish")
        override.note_pending_line("urgent", "urg.ring.urgent.hinglish")
    heard = world.store.pending_heard()
    assert heard["urg.ring.urgent.hinglish"]["count"] == 2
    assert heard["urg.ring.urgent.hinglish"]["scenarios"] == ["urgent_escalation"]


# ----------------------------------------------------------------------------- the real gates
async def test_urgent_dial_refuses_pending_line_outside_qa() -> None:
    from friday.urgent.telephony import TelephonyOwnNumberCaller

    caller = TelephonyOwnNumberCaller(object(), make_settings())
    out = await caller.ring(
        user_id="u",
        number=NUMBER,
        line_key="ring.urgent",
        lang="hinglish",
        user_name="Himanshu",
        dedupe_key="k",
    )
    assert out.detail == "line_pending"


async def test_urgent_dial_plays_pending_line_in_qa_only_to_the_number(world: World) -> None:
    from friday.core.models import DialStatus
    from friday.urgent.telephony import TelephonyOwnNumberCaller

    spoken: list[str] = []
    dialled: list[str] = []

    class Leg:
        async def wait_for_answer(self, _t: float) -> DialStatus:
            return DialStatus.ANSWERED

        async def speak(self, text: str, _lang: object) -> None:
            spoken.append(text)

        async def hangup(self) -> None:
            return None

    class Tel:
        async def place_call(self, req: object) -> Leg:
            dialled.append(req.to_phone)  # type: ignore[attr-defined]
            return Leg()

    caller = TelephonyOwnNumberCaller(Tel(), world.settings)
    with world.guard.session("urgent_escalation", "r2"):
        ok = await caller.ring(
            user_id="u",
            number=NUMBER,
            line_key="ring.urgent",
            lang="hinglish",
            user_name="Himanshu",
            dedupe_key="k1",
        )
        other = await caller.ring(
            user_id="u",
            number=OTHER,
            line_key="ring.urgent",
            lang="hinglish",
            user_name="Himanshu",
            dedupe_key="k2",
        )
    assert ok.detail == "spoken" and dialled == [NUMBER] and "Himanshu" in spoken[0]
    assert other.detail == "line_pending"  # another number: the override does not apply
    assert "urg.ring.urgent.hinglish" in world.store.pending_heard()
