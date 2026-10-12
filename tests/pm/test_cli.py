import json

import pytest

from friday.cli import main
from friday.pm.cli import list_scenarios


def test_scenarios_listed():
    assert {"happy_quote", "widen_and_no_pickup", "call_gym"} <= set(list_scenarios())


@pytest.mark.parametrize("name", list_scenarios())
def test_pm_sim_runs_every_scenario(name, capsys):
    assert main(["pm-sim", name, "--log"]) == 0
    out = capsys.readouterr().out
    assert "PLAN" in out and "DECISION LOG" in out


def test_classify_offline_json(capsys, monkeypatch):
    for k in ("OPENAI_API_KEY", "FRIDAY_OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert main(["classify", "haircut kitna lega", "--channel", "call"]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(last)
    assert data["bucket"] == "quote" and data["category"] == "salon" and data["channel"] == "call"
