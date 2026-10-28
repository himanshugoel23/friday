# ruff: noqa: E501
"""deploy/enable-web-test.sh: idempotent, non-secret switches only, never prints a value, `off` mode.
systemctl, apt-get and web-https.sh are shims; no root, no network."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from friday.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "enable-web-test.sh"
SECRET = "sk-TOPSECRET-VALUE-12345"
NUMBER = "+919811100001"
SECOND = "+919811100002"


def _shim(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(tmp: Path, env_text: str, *args: str) -> tuple[subprocess.CompletedProcess, str]:
    envf = tmp / ".env"
    envf.write_text(env_text)
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp / "calls.log"
    _shim(bin_dir / "systemctl", f'echo "systemctl $*" >> {log}; [ "$1" = is-active ] && echo active; exit 0')
    _shim(bin_dir / "apt-get", f'echo "apt-get $*" >> {log}; exit 0')
    web = tmp / "web-https.sh"
    _shim(web, f'echo "web-https $*" >> {log}')
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FRIDAY_ENV_FILE": str(envf),
        "FRIDAY_WEB_HTTPS_SCRIPT": str(web),
        "FRIDAY_APP": str(tmp),
    }
    p = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)
    return p, envf.read_text()


BASE = f"OPENAI_API_KEY={SECRET}\nFRIDAY_PILOT_ALLOWED_NUMBERS={NUMBER},{SECOND}\nFRIDAY_PUBLIC_BASE_URL=https://f.example.org\nFRIDAY_INVITE_ONLY=true\n"


def test_syntax_is_valid():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_on_sets_switches_prints_names_only_and_is_idempotent(tmp_path):
    p, env = _run(tmp_path, BASE)
    assert p.returncode == 0, p.stderr + p.stdout
    out = p.stdout + p.stderr
    for forbidden in (SECRET, NUMBER, SECOND, "f.example.org"):
        assert forbidden not in out
    assert "FRIDAY_WEB_CHANNEL_ENABLED" in out and "OPENAI_API_KEY" in out and "set" in out
    lines = dict(line.split("=", 1) for line in env.splitlines() if "=" in line)
    assert lines["FRIDAY_WEB_CHANNEL_ENABLED"] == "true" and lines["FRIDAY_PROFILE"] == "pilot"
    assert lines["FRIDAY_INVITE_ONLY"] == "false"
    assert lines["FRIDAY_VENDOR_CALL_REDIRECT_TO"] == NUMBER  # the FIRST allow-listed number
    assert lines["OPENAI_API_KEY"] == SECRET  # untouched
    assert (lines["FRIDAY_WEB_MAX_CALLS_PER_DAY"], lines["FRIDAY_WEB_MAX_SPEND_INR"], lines["FRIDAY_WEB_GLOBAL_MAX_SPEND_INR"]) == ("0", "0", "0")
    assert lines["FRIDAY_REFUND_CHASE_CALLS"] == "false"  # unapproved call lines stay off
    assert lines["FRIDAY_APPROACH_PLANNER_ENABLED"] == "true" and "FRIDAY_APPROACH_PLANNER_ENABLED" in out
    log = (tmp_path / "calls.log").read_text()
    assert "systemctl restart friday" in log and "web-https" in log
    p2, env2 = _run(tmp_path, env)
    assert p2.returncode == 0 and env2 == env  # running it again changes nothing


def test_every_switch_it_writes_is_a_real_setting_and_loads_true(tmp_path):
    _, env = _run(tmp_path, BASE)
    s = Settings(_env_file=str(tmp_path / ".env"), mode="simulator")
    for name in ("proof_enabled", "docs_enabled", "family_drive_enabled", "trips_enabled", "refunds_enabled",
                 "urgent_escalation_enabled", "receptionist_enabled", "parity_invites", "parity_ride_links",
                 "parity_inr_only", "parity_status", "guardrails_new_categories", "browser_login_otp_in_chat",
                 "chatbot_onboarding", "pilot"):
        assert getattr(s, name) is True, name
    for name in ("refund_chase_calls", "family_drive_sharing_enabled", "parity_digest", "parity_nudges", "parity_escalation"):
        assert getattr(s, name) is False, name
    assert s.vendor_call_redirect_to == NUMBER and s.invite_only is False and s.is_pilot


def test_whitespace_is_stripped(tmp_path):
    _, env = _run(tmp_path, "FRIDAY_PILOT_ALLOWED_NUMBERS= +91 98111 00001 \n")
    assert "FRIDAY_VENDOR_CALL_REDIRECT_TO=+919811100001" in env.splitlines()


def test_refuses_without_an_allow_listed_number_and_changes_nothing(tmp_path):
    before = "OPENAI_API_KEY=abc\nFRIDAY_PILOT_ALLOWED_NUMBERS=\n"
    p, env = _run(tmp_path, before)
    assert p.returncode != 0 and env == before
    assert "abc" not in p.stdout + p.stderr


def test_off_mode_switches_everything_off_and_keeps_keys_and_profile(tmp_path):
    _, on_env = _run(tmp_path, BASE)
    p, env = _run(tmp_path, on_env, "off")
    assert p.returncode == 0, p.stderr
    s = Settings(_env_file=str(tmp_path / ".env"), mode="simulator")
    assert not any((s.proof_enabled, s.trips_enabled, s.refunds_enabled, s.docs_enabled, s.parity_invites))
    assert s.invite_only is True and "FRIDAY_WEB_CHANNEL_ENABLED=false" in env.splitlines()
    assert f"OPENAI_API_KEY={SECRET}" in env.splitlines() and "FRIDAY_PROFILE=pilot" in env.splitlines()
    assert "web-https --off" in (tmp_path / "calls.log").read_text()
    assert SECRET not in p.stdout + p.stderr
