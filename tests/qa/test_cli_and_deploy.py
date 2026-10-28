"""`friday qa ...` commands and the deploy scripts (Caddy and systemctl are shimmed)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from friday.cli import main
from friday.qa.live import REPORT_PREFIX

ROOT = Path(__file__).resolve().parents[2]
QA_HTTPS = ROOT / "deploy" / "qa-https.sh"
QA_LIVE = ROOT / "deploy" / "qa-live.sh"
LAB_HTTPS = ROOT / "deploy" / "lab-https.sh"


@pytest.fixture
def qa_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "qa"
    monkeypatch.setenv("FRIDAY_QA_DIR", str(d))
    monkeypatch.chdir(tmp_path)  # no .env here
    return d


def test_list_and_note_and_report(qa_dir: Path, capsys) -> None:  # noqa: ANN001
    assert main(["qa", "list"]) == 0
    out = capsys.readouterr().out
    assert (
        "salon_quote" in out and "REAL CALL" in out and "simulator" in out and "instructions" in out
    )
    assert main(["qa", "note", "salon_quote", "--verdict", "wording", "--note", "too long"]) == 0
    assert main(["qa", "note", "nope", "--verdict", "ok"]) == 2
    assert main(["qa", "note", "salon_quote"]) == 2  # neither verdict nor note
    assert main(["qa", "line", "table_booking.hook", "approve", "--note", "ok"]) == 0
    capsys.readouterr()
    assert main(["qa", "report"]) == 0
    out = capsys.readouterr().out
    assert "wording change" in out and "salon_quote" in out
    rows = [json.loads(x) for x in (qa_dir / "notes.jsonl").read_text().splitlines()]
    assert rows[0]["verdict"] == "wording" and rows[-1]["kind"] == "line"


def test_run_and_serve_refuse_without_qa_mode(qa_dir: Path, capsys, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr("builtins.input", lambda _p: pytest.fail("must not ask"))
    assert main(["qa", "run", "salon_quote"]) == 2
    assert "REFUSED" in capsys.readouterr().out
    assert main(["qa", "serve"]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_exec_refuses_without_the_approval_phrase(qa_dir: Path, capsys) -> None:  # noqa: ANN001
    assert main(["qa", "exec", "salon_quote", "--run-id", "r1"]) == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out
    report = json.loads(
        next(x for x in out.splitlines() if x.startswith(REPORT_PREFIX))[len(REPORT_PREFIX) :]
    )
    assert report["status"] == "refused"


def test_exec_refuses_when_qa_mode_is_off_even_with_the_phrase(qa_dir: Path, capsys) -> None:  # noqa: ANN001
    rc = main(["qa", "exec", "salon_quote", "--run-id", "r1", "--approved", "YES, call my phone"])
    assert rc == 2 and "QA mode will not start" in capsys.readouterr().out


def test_show_prints_the_plan_without_dialling(qa_dir: Path, capsys, monkeypatch) -> None:  # noqa: ANN001
    async def fake(settings, query, area, **kw):  # noqa: ANN001, ANN202
        return {
            "source": "sample",
            "items": [{"name": "Shreya Salon", "rating": None, "address": area}],
            "note": "Sample.",
        }

    monkeypatch.setattr("friday.qa.runner.places_shortlist", fake)
    assert main(["qa", "show", "salon_quote"]) == 0
    out = capsys.readouterr().out
    assert "REAL:" in out and "SIMULATED:" in out and "Shreya Salon" in out and "NOT dialled" in out
    assert main(["qa", "show", "nope"]) == 2


# ----------------------------------------------------------------------------- deploy scripts
BASE = "friday.example.org {\n    encode gzip\n    reverse_proxy 127.0.0.1:8000\n}\n"
WITH_ALL = (
    "friday.example.org {\n    encode gzip\n    handle_path /explore/* {\n"
    "        reverse_proxy 127.0.0.1:8765\n    }\n    handle /lab/* {\n"
    "        reverse_proxy 127.0.0.1:8766\n    }\n    handle {\n"
    "        reverse_proxy 127.0.0.1:8000\n    }\n}\n"
)


def _shim(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run(script: Path, tmp_path: Path, caddyfile: str, *args: str, caddy_ok: bool = True):  # noqa: ANN201
    cf = tmp_path / "Caddyfile"
    cf.write_text(caddyfile)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _shim(bin_dir / "caddy", f"exit {0 if caddy_ok else 1}\n")
    _shim(bin_dir / "systemctl", f'echo "$@" >> "{tmp_path}/systemctl.log"\n')
    env = {**os.environ, "CADDYFILE": str(cf), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    p = subprocess.run(
        ["bash", str(script), *args], env=env, capture_output=True, text=True, check=False
    )
    return p, cf.read_text()


def test_scripts_are_valid_bash_and_executable() -> None:
    for script in (QA_HTTPS, QA_LIVE, LAB_HTTPS):
        assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
        assert os.access(script, os.X_OK)


def test_qa_route_goes_to_8767_only(tmp_path: Path) -> None:
    p, text = run(QA_HTTPS, tmp_path, BASE)
    assert p.returncode == 0, p.stderr
    assert "handle /qa/* {\n        reverse_proxy 127.0.0.1:8767" in text
    assert "reverse_proxy 127.0.0.1:8000" in text
    assert "reload caddy" in (tmp_path / "systemctl.log").read_text()


def test_qa_route_keeps_explore_and_lab_and_can_be_removed(tmp_path: Path) -> None:
    p, text = run(QA_HTTPS, tmp_path, WITH_ALL)
    assert p.returncode == 0, p.stderr
    assert "/explore/*" in text and "127.0.0.1:8766" in text and "127.0.0.1:8767" in text
    p, text = run(QA_HTTPS, tmp_path, text, "--off")
    assert p.returncode == 0 and "/qa/" not in text and "/lab/*" in text and "/explore/*" in text


def test_lab_script_keeps_an_existing_qa_route(tmp_path: Path) -> None:
    p, text = run(QA_HTTPS, tmp_path, BASE)
    assert p.returncode == 0
    p, text = run(LAB_HTTPS, tmp_path, text)
    assert p.returncode == 0, p.stderr
    assert "127.0.0.1:8766" in text and "127.0.0.1:8767" in text
    p, text = run(LAB_HTTPS, tmp_path, text, "--off")
    assert "127.0.0.1:8767" in text and "127.0.0.1:8766" not in text


def test_invalid_caddyfile_is_restored(tmp_path: Path) -> None:
    p, text = run(QA_HTTPS, tmp_path, BASE, caddy_ok=False)
    assert p.returncode == 1 and text == BASE


def test_qa_live_script_turns_qa_mode_on_only_for_its_own_process() -> None:
    text = QA_LIVE.read_text()
    assert "export FRIDAY_QA_LIVE=true" in text and "friday qa serve" in text
    assert "--host 127.0.0.1" in text and "8767" in text
    assert "systemctl start friday" in text and "trap" in text  # the front door always comes back
    assert ".env" not in text.replace("never reads", "")  # the script does not read the env file
