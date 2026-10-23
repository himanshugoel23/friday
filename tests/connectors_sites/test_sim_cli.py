from __future__ import annotations

from friday.connectors.sites.sim_cli import main


def test_all_scenarios_pass(capsys):
    assert main(["--quiet"]) == 0
    out = capsys.readouterr().out
    assert "20/20" in out and "FAIL" not in out


def test_list_copy_and_unknown(capsys):
    assert main(["--list"]) == 0
    assert main(["--print-copy"]) == 0
    assert main(["--scenario", "nope"]) == 2
    assert "ack.en" in capsys.readouterr().out
