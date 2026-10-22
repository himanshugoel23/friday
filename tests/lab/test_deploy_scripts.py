"""deploy/lab-https.sh adds and removes only the /lab route (Caddy and systemctl are shimmed)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAB_HTTPS = ROOT / "deploy" / "lab-https.sh"
CHAT_LAB = ROOT / "deploy" / "chat-lab.sh"

BASE = "friday.example.org {\n    encode gzip\n    reverse_proxy 127.0.0.1:8000\n}\n"
WITH_EXPLORE = (
    "friday.example.org {\n    encode gzip\n    handle_path /explore/* {\n"
    "        reverse_proxy 127.0.0.1:8765\n    }\n    handle {\n"
    "        reverse_proxy 127.0.0.1:8000\n    }\n}\n"
)


def _shim(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def run(tmp_path: Path, caddyfile: str, *args: str, caddy_ok: bool = True):
    cf = tmp_path / "Caddyfile"
    cf.write_text(caddyfile)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _shim(bin_dir / "caddy", f"exit {0 if caddy_ok else 1}\n")
    _shim(bin_dir / "systemctl", f'echo "$@" >> "{tmp_path}/systemctl.log"\n')
    env = {**os.environ, "CADDYFILE": str(cf), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    p = subprocess.run(
        ["bash", str(LAB_HTTPS), *args], env=env, capture_output=True, text=True, check=False
    )
    return p, cf.read_text()


def test_both_scripts_are_valid_bash():
    for script in (LAB_HTTPS, CHAT_LAB):
        assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
        assert os.access(script, os.X_OK)


def test_adds_the_lab_route_only_to_loopback_port_8766(tmp_path):
    p, text = run(tmp_path, BASE)
    assert p.returncode == 0, p.stderr
    assert "handle /lab/* {\n        reverse_proxy 127.0.0.1:8766" in text
    assert "reverse_proxy 127.0.0.1:8000" in text  # the front door is still the default
    assert "/explore" not in text
    assert "reload caddy" in (tmp_path / "systemctl.log").read_text()


def test_keeps_an_existing_explore_route(tmp_path):
    p, text = run(tmp_path, WITH_EXPLORE)
    assert p.returncode == 0, p.stderr
    assert "handle_path /explore/*" in text and "127.0.0.1:8765" in text
    assert text.index("/explore/*") < text.index("/lab/*") < text.index("127.0.0.1:8000")


def test_off_removes_only_the_lab_route(tmp_path):
    p, text = run(tmp_path, WITH_EXPLORE, "--off")
    assert p.returncode == 0 and "/lab" not in text and "/explore/*" in text
    p, text = run(tmp_path, BASE, "--off")
    assert p.returncode == 0 and "/lab" not in text and "reverse_proxy 127.0.0.1:8000" in text


def test_an_invalid_caddyfile_is_restored(tmp_path):
    p, text = run(tmp_path, BASE, caddy_ok=False)
    assert p.returncode == 1 and text == BASE
    assert not (tmp_path / "systemctl.log").exists()


@pytest.mark.parametrize("needle", ["--host 127.0.0.1", "friday lab", "as_friday", "var/lab"])
def test_chat_lab_script_runs_the_lab_as_the_friday_user_on_loopback(needle):
    assert needle in CHAT_LAB.read_text()
    assert ".env" not in [ln for ln in CHAT_LAB.read_text().splitlines() if "source" in ln]
