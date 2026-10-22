"""The doctor names a missing ffmpeg; the server installer installs it."""

from __future__ import annotations

from pathlib import Path

import pytest

from friday.core.config import Settings
from friday.ops import doctor as d

REPO = Path(__file__).resolve().parents[2]


def _lines(section: d.Section) -> str:
    return "\n".join(f"{c.status} {c.message}" for c in section.checks)


def test_doctor_warns_naming_ffmpeg_when_voice_replies_are_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(d.shutil, "which", lambda name: None)
    text = _lines(d.check_switches(Settings(_env_file=None, voice_note_replies=True)))
    assert "FRIDAY_VOICE_NOTE_REPLIES=on" in text and "FRIDAY_DEVANAGARI_INPUT=off" in text
    assert d.WARN + " ffmpeg is MISSING" in text and "apt-get install -y ffmpeg" in text


def test_doctor_only_notes_ffmpeg_while_the_switch_is_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(d.shutil, "which", lambda name: None)
    text = _lines(d.check_switches(Settings(_env_file=None)))
    assert d.OK + " ffmpeg is MISSING" in text and "FRIDAY_VOICE_NOTE_REPLIES=off" in text


def test_doctor_is_quiet_when_ffmpeg_is_there(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        d.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None
    )
    text = _lines(d.check_switches(Settings(_env_file=None, voice_note_replies=True)))
    assert "ffmpeg is installed" in text and "MISSING" not in text


def test_the_server_installer_installs_ffmpeg() -> None:
    script = (REPO / "deploy" / "small-server.sh").read_text()
    apt_lines = [ln for ln in script.splitlines() if "apt-get install -y" in ln and "python3" in ln]
    assert apt_lines and "ffmpeg" in apt_lines[0]
