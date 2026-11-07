# ruff: noqa: E501
"""deploy/enable-robin.sh in dry mode (FRIDAY_ENV_FILE temp file; systemctl is a shim; no root, no restart, no network)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "enable-robin.sh"
PLANTED = "planted-env-value-0001"


def run(tmp: Path, env_text: str, *args: str):
    envf = tmp / ".env"
    envf.write_text(env_text)
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    sh = bin_dir / "systemctl"
    sh.write_text(f'#!/bin/bash\necho "systemctl $*" >> {tmp}/calls.log\n')
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FRIDAY_ENV_FILE": str(envf), "FRIDAY_APP": str(tmp)}
    p = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)
    return p, envf.read_text()


def kv(text: str) -> dict[str, str]:
    return dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln)


def test_syntax_and_executable():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0
    assert SCRIPT.stat().st_mode & stat.S_IEXEC


def test_on_sets_only_the_two_switches_and_never_restarts_in_dry_mode(tmp_path):
    base = f"SOME_SETTING={PLANTED}\nFRIDAY_ROBIN_AUTHORITY_DRY_RUN=true\nOTHER=1\n"
    p, env = run(tmp_path, base)
    assert p.returncode == 0, p.stdout + p.stderr
    new, old = kv(env), kv(base)
    assert new["FRIDAY_ROBIN_ENABLED"] == "true" and new["FRIDAY_ROBIN_DEVICE_ENABLED"] == "true"
    assert {k: v for k, v in new.items() if k not in ("FRIDAY_ROBIN_ENABLED", "FRIDAY_ROBIN_DEVICE_ENABLED")} == old
    for k in ("FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED", "FRIDAY_ROBIN_LISTEN_IN_ENABLED"):
        assert k not in new  # left alone (default off)
    assert PLANTED not in p.stdout + p.stderr and "PENDING" in p.stdout
    assert "AUTHORITY_CALLS_ENABLED  off" in p.stdout and "LISTEN_IN_ENABLED        off" in p.stdout
    assert not (tmp_path / "calls.log").exists()


def test_idempotent(tmp_path):
    _, once = run(tmp_path, "X=1\n")
    p, twice = run(tmp_path, once)
    assert p.returncode == 0 and twice == once and twice.count("FRIDAY_ROBIN_ENABLED=") == 1


def test_refuses_when_authority_dry_run_is_false(tmp_path):
    for val in ("false", "FALSE", "0", '"false"'):
        base = f"FRIDAY_ROBIN_AUTHORITY_DRY_RUN={val}\n"
        p, env = run(tmp_path, base)
        assert p.returncode == 3 and "REFUSED" in p.stdout and env == base, val


def test_refuses_when_authority_or_listen_in_already_on(tmp_path):
    for line in ("FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED=true", "FRIDAY_ROBIN_LISTEN_IN_ENABLED=true"):
        p, env = run(tmp_path, line + "\n")
        assert p.returncode == 3 and env == line + "\n"


def test_off_turns_the_two_switches_false_and_off_is_not_blocked_by_live_authority(tmp_path):
    p, env = run(tmp_path, "FRIDAY_ROBIN_ENABLED=true\nFRIDAY_ROBIN_DEVICE_ENABLED=true\nFRIDAY_ROBIN_AUTHORITY_DRY_RUN=false\n", "off")
    assert p.returncode == 0 and kv(env)["FRIDAY_ROBIN_ENABLED"] == "false" and kv(env)["FRIDAY_ROBIN_DEVICE_ENABLED"] == "false"


def test_bad_argument_and_missing_env_file(tmp_path):
    assert run(tmp_path, "", "banana")[0].returncode == 1
    p = subprocess.run(["bash", str(SCRIPT)], env={**os.environ, "FRIDAY_ENV_FILE": str(tmp_path / "nope")}, capture_output=True, text=True, check=False)
    assert p.returncode == 1


def test_web_test_script_no_longer_touches_the_robin_switches(tmp_path):
    web = (ROOT / "deploy" / "enable-web-test.sh").read_text()
    always = web.split("ALWAYS_OFF = [")[1].split("\n]")[0]
    assert "FRIDAY_ROBIN_ENABLED" not in always and "FRIDAY_ROBIN_DEVICE_ENABLED" not in always
    assert "KEPT = [" in web and "FRIDAY_ROBIN_LISTEN_IN_ENABLED" in always
