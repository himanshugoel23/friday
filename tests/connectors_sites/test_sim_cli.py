from __future__ import annotations

from friday.connectors.sites.sim_cli import main


def test_all_scenarios_pass(capsys):
    assert main(["--quiet"]) == 0
    out = capsys.readouterr().out
    assert "scenarios as expected" in out and "FAIL" not in out
    done, total = out.split("scenarios as expected")[0].split()[-1].split("/")
    assert done == total and int(total) >= 20


def test_list_copy_and_unknown(capsys):
    assert main(["--list"]) == 0
    assert main(["--print-copy"]) == 0
    assert main(["--scenario", "nope"]) == 2
    assert "ack.en" in capsys.readouterr().out
