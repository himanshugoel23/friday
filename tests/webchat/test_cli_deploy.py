# ruff: noqa: E501
"""`friday web ...` and deploy/web-https.sh (Caddy and systemctl are shimmed)."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
from pathlib import Path

from friday.core.config import Settings
from friday.webchat.cli import add_parser, run_command
from friday.webchat.registry import Registry

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "web-https.sh"
FOUNDER = "+919811100001"
BASE = "friday.example.org {\n    encode gzip\n    reverse_proxy 127.0.0.1:8000\n}\n"


def _args(*argv: str) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    add_parser(p.add_subparsers(dest="cmd"))
    return p.parse_args(["web", *argv])


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, mode="simulator", public_base_url="https://f.example.org", pilot_allowed_numbers=[FOUNDER], **kw)


def test_cli_invite_testers_revoke_feedback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FRIDAY_WEB_CHANNEL_ENABLED", raising=False)
    out: list[str] = []
    s = _settings()
    assert run_command(_args("invite", "--name", "Himanshu", "--phone", FOUNDER), s, out.append) == 0
    text = "\n".join(out)
    assert "https://f.example.org/web/" in text and FOUNDER not in text
    link_token = text.split("/web/")[1].split("/")[0]
    reg = Registry(tmp_path / "var" / "web")
    t = reg.by_token(link_token)
    assert t is not None and t.phone == FOUNDER
    assert link_token not in (tmp_path / "var" / "web" / "testers.json").read_text()
    out.clear()
    assert run_command(_args("invite", "--name", "X", "--phone", "+919800000000"), s, out.append) == 2
    assert "REFUSED" in out[0]
    out.clear()
    run_command(_args("testers"), s, out.append)
    assert "Himanshu" in out[0] and FOUNDER not in out[0] and "active" in out[0]
    reg.add_feedback(t, "wrong", "m1", "Hello there", "bad")
    out.clear()
    run_command(_args("feedback"), s, out.append)
    assert "wrong" in out[0] and "bad" in out[0]
    out.clear()
    assert run_command(_args("revoke", "Himanshu"), s, out.append) == 0
    assert Registry(tmp_path / "var" / "web").by_token(link_token) is None


def test_friday_web_is_a_registered_command():
    assert "web" in subprocess.run(["uv", "run", "friday", "--help"], capture_output=True, text=True, check=False, cwd=ROOT).stdout


def _shim(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(tmp_path: Path, caddyfile: str, *args: str):
    cf = tmp_path / "Caddyfile"
    cf.write_text(caddyfile)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _shim(bin_dir / "caddy", "exit 0\n")
    _shim(bin_dir / "systemctl", f'echo "$@" >> "{tmp_path}/systemctl.log"\n')
    env = {**os.environ, "CADDYFILE": str(cf), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    p = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)
    return p, cf.read_text()


def test_web_https_adds_and_removes_only_the_web_route(tmp_path):
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0
    with_lab = BASE.replace("    reverse_proxy", "    handle /lab/* {\n        reverse_proxy 127.0.0.1:8766\n    }\n    reverse_proxy")
    p, text = _run(tmp_path, with_lab)
    assert p.returncode == 0, p.stderr
    assert "handle /web/* {" in text and "noindex" in text and "handle /lab/* {" in text
    assert text.count("reverse_proxy 127.0.0.1:8000") == 2  # /web and the default
    p, text = _run(tmp_path, text, "--off")
    assert "/web/" not in text and "handle /lab/*" in text and "reverse_proxy 127.0.0.1:8000" in text
