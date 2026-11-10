# ruff: noqa: E501
"""T19 kill-switch drill: `friday robin pause-all` stops every Robin call and everything new from starting, keeps already-open alerts messaging the child,
and `--resume` brings the check-ins back. Tested with fakes (flag file in a temp dir, no restart, nothing dialled)."""

from __future__ import annotations

import pytest

from friday.core.config import Settings
from friday.robin import killswitch
from friday.robin.models import CallResult
from tests.e2e.robin.harness import RobinWorld


@pytest.fixture
async def pworld(tmp_path):
    w = await RobinWorld.start(device=True, pause_file=str(tmp_path / "PAUSED"))
    yield w
    await w.close()


async def test_pause_all_stops_calls_and_new_work_and_resume_brings_the_checkin_back(pworld):
    w = pworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family(checkin="9am")
    w.caller.answers = {"checkin.q.ate": "haan", "checkin.q.slept": "haan", "checkin.q.pain": "nahi", "checkin.q.mood": "theek", "checkin.q.strange": "nahi"}
    lines: list[str] = []
    assert killswitch.run(w.settings, resume=False, status_only=False, out=lines.append) == 0
    assert any("PAUSED" in x for x in lines) and w.hub.ctx.paused()
    n_calls, n_texts = len(w.caller.calls), len(w.child_texts())

    await w.advance(hours=1)  # 09:00 (08:00 start): the check-in is due, but the switch is on
    await w.advance(hours=2)
    assert len(w.caller.calls) == n_calls and w.calls(purpose="checkin") == []
    assert len(w.child_texts()) == n_texts, "no digest, reminder or greeting started while paused"

    assert killswitch.run(w.settings, resume=True, status_only=False, out=lines.append) == 0
    await w.advance(minutes=5)
    assert len(w.calls(purpose="checkin")) == 1, "back to normal after --resume"


async def test_sos_while_paused_still_messages_the_child_but_no_phone_rings(pworld):
    w = pworld
    w.script_calls(CallResult.ANSWERED)
    await w.setup_family()
    parent = await w.parent()
    killswitch.run(w.settings, resume=False, status_only=False, out=lambda _: None)
    n_calls, n_texts = len(w.caller.calls), len(w.child_texts())
    res = await w.hub.widget_sos(parent.id)
    assert res.alert.accepted
    assert len(w.child_texts()) > n_texts, "the child is still told"
    await w.advance(minutes=20)
    assert len(w.caller.calls) == n_calls, "the kill switch refuses every ring"


def test_status_and_exit_codes(tmp_path):
    s = Settings(_env_file=None, env="test", pause_file=str(tmp_path / "var" / "PAUSED"))
    out: list[str] = []
    assert killswitch.run(s, resume=False, status_only=True, out=out.append) == 0 and "running" in out[-1]
    assert killswitch.run(s, resume=False, status_only=False, out=out.append) == 0
    assert killswitch.run(s, resume=False, status_only=True, out=out.append) == 3 and "PAUSED" in out[-1]
    assert killswitch.run(s, resume=True, status_only=False, out=out.append) == 0
    assert killswitch.run(s, resume=False, status_only=True, out=out.append) == 0
    env_paused = Settings(_env_file=None, env="test", paused=True, pause_file=str(tmp_path / "x"))
    assert killswitch.run(env_paused, resume=True, status_only=False, out=out.append) == 1  # the env switch needs a restart


def test_cli_command_end_to_end(tmp_path, monkeypatch, capsys):
    import friday.cli as cli

    flag = tmp_path / "var" / "PAUSED"
    monkeypatch.setenv("FRIDAY_PAUSE_FILE", str(flag))
    monkeypatch.delenv("FRIDAY_PAUSED", raising=False)
    assert cli.main(["robin", "pause-all"]) == 0 and flag.exists()
    assert cli.main(["robin", "pause-all", "--status"]) == 3
    assert "PAUSED" in capsys.readouterr().out
    assert cli.main(["robin", "pause-all", "--resume"]) == 0 and not flag.exists()
