# ruff: noqa: E501
"""T19: every deploy script that touches Robin keeps authority calls OFF + dry-run ON and listen-in OFF (static scan + dry runs on a temp env file).
No root, no restart (systemctl is a shim), no network."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
LOCKED = ("FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED", "FRIDAY_ROBIN_LISTEN_IN_ENABLED", "FRIDAY_ROBIN_SCREEN_UNKNOWN_ENABLED", "FRIDAY_ROBIN_AUTHORITY_DRY_RUN")
SCRIPTS = [("enable-robin.sh", ()), ("enable-robin-channels.sh", ("parent-whatsapp",)), ("enable-robin-channels.sh", ("forwarded-calls",)), ("enable-robin-channels.sh", ("concierge",))]


def run(tmp: Path, script: str, args: tuple[str, ...], env_text: str):
    envf = tmp / ".env"
    envf.write_text(env_text)
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    sh = bin_dir / "systemctl"
    sh.write_text(f'#!/bin/bash\necho "systemctl $*" >> {tmp}/calls.log\n')
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FRIDAY_ENV_FILE": str(envf), "FRIDAY_APP": str(tmp)}
    p = subprocess.run(["bash", str(DEPLOY / script), *args], env=env, capture_output=True, text=True, check=False)
    return p, envf.read_text()


def kv(text: str) -> dict[str, str]:
    return dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln)


def test_no_script_ever_turns_a_locked_switch_on():
    """Static: no deploy script contains an assignment that enables authority calls, listen-in or screen-first, or sets dry-run to false."""
    bad = re.compile(r"(FRIDAY_ROBIN_(AUTHORITY_CALLS_ENABLED|LISTEN_IN_ENABLED|SCREEN_UNKNOWN_ENABLED))=(true|1|yes|on)\b|FRIDAY_ROBIN_AUTHORITY_DRY_RUN=(false|0|no|off)\b", re.I)
    for f in list(DEPLOY.glob("*.sh")) + [ROOT / ".env.example"]:
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            assert not bad.search(line), f"{f.name}:{n} would unlock a Robin safety lock"
    for name, _args in SCRIPTS:
        text = (DEPLOY / name).read_text()
        setv_keys = re.findall(r'setv\s+"?(\$?[A-Z_]+)"?', text)
        assert not set(setv_keys) & set(LOCKED), (name, setv_keys)  # these scripts never WRITE a locked switch


@pytest.mark.parametrize(("script", "args"), SCRIPTS)
def test_on_leaves_the_locks_untouched_and_never_restarts_in_dry_mode(tmp_path, script, args):
    base = "FRIDAY_ROBIN_ENABLED=true\nFRIDAY_ROBIN_AUTHORITY_DRY_RUN=true\nOTHER=1\n"
    p, env = run(tmp_path, script, args, base)
    assert p.returncode == 0, p.stdout + p.stderr
    new = kv(env)
    for k in LOCKED:
        assert new.get(k) == kv(base).get(k), k  # unchanged (absent stays absent)
    assert "AUTHORITY_CALLS_ENABLED  off" in p.stdout and "LISTEN_IN_ENABLED        off" in p.stdout
    assert not (tmp_path / "calls.log").exists()


@pytest.mark.parametrize(("script", "args"), SCRIPTS)
@pytest.mark.parametrize("line", ["FRIDAY_ROBIN_AUTHORITY_DRY_RUN=false", "FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED=true", "FRIDAY_ROBIN_LISTEN_IN_ENABLED=true"])
def test_on_refuses_when_a_lock_is_open(tmp_path, script, args, line):
    base = f"FRIDAY_ROBIN_ENABLED=true\n{line}\n"
    p, env = run(tmp_path, script, args, base)
    assert p.returncode == 3 and "REFUSED" in p.stdout and env == base


def test_channels_script_needs_robin_core_first_and_off_is_always_allowed(tmp_path):
    p, env = run(tmp_path, "enable-robin-channels.sh", ("concierge",), "X=1\n")
    assert p.returncode == 3 and env == "X=1\n" and "enable-robin.sh" in p.stdout
    p, env = run(tmp_path, "enable-robin-channels.sh", ("concierge", "off"), "FRIDAY_ROBIN_CONCIERGE_ENABLED=true\nFRIDAY_ROBIN_AUTHORITY_DRY_RUN=false\n")
    assert p.returncode == 0 and kv(env)["FRIDAY_ROBIN_CONCIERGE_ENABLED"] == "false"


def test_channels_script_sets_only_its_own_switch_and_is_idempotent(tmp_path):
    base = "FRIDAY_ROBIN_ENABLED=true\nSOME=planted-env-value-0001\n"
    p, once = run(tmp_path, "enable-robin-channels.sh", ("forwarded-calls",), base)
    assert p.returncode == 0 and "planted-env-value-0001" not in p.stdout
    assert {k: v for k, v in kv(once).items() if k != "FRIDAY_ROBIN_FORWARDED_CALLS_ENABLED"} == kv(base)
    assert kv(once)["FRIDAY_ROBIN_FORWARDED_CALLS_ENABLED"] == "true"
    _, twice = run(tmp_path, "enable-robin-channels.sh", ("forwarded-calls",), once)
    assert twice == once


def test_channels_script_bad_arguments_and_syntax(tmp_path):
    f = DEPLOY / "enable-robin-channels.sh"
    assert subprocess.run(["bash", "-n", str(f)], check=False).returncode == 0 and f.stat().st_mode & stat.S_IEXEC
    for args in ((), ("banana",), ("concierge", "maybe")):
        assert run(tmp_path, "enable-robin-channels.sh", args, "FRIDAY_ROBIN_ENABLED=true\n")[0].returncode == 1


def test_example_env_keeps_the_locks_commented_or_safe():
    text = (ROOT / ".env.example").read_text()
    for line in text.splitlines():
        if line.startswith("FRIDAY_ROBIN_AUTHORITY_CALLS_ENABLED=") or line.startswith("FRIDAY_ROBIN_LISTEN_IN_ENABLED="):
            assert line.split("=", 1)[1].strip().lower() in ("false", "0", ""), line
        if line.startswith("FRIDAY_ROBIN_AUTHORITY_DRY_RUN="):
            assert line.split("=", 1)[1].strip().lower() in ("true", "1"), line
