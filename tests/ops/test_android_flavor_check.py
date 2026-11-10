"""scripts/check-android-flavor.sh fails a `lite` APK that holds any bubble permission or component.

A fake aapt2 prints canned manifest dumps, so no Android SDK is needed. Negative controls prove the check can fail.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-android-flavor.sh"

BASE = ["android.permission.INTERNET", "android.permission.RECORD_AUDIO"]
BUBBLE = [
    "android.permission.SYSTEM_ALERT_WINDOW",
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
    "android.permission.FOREGROUND_SERVICE_MICROPHONE",
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.RECEIVE_BOOT_COMPLETED",
]
TREE_LITE = "E: manifest\n  E: application\n    E: activity\n      A: name=\"app.robin.parent.MainActivity\"\n    E: receiver\n      A: name=\"app.robin.parent.RobinWidget\"\n"
TREE_FULL = TREE_LITE + "    E: service\n      A: name=\"app.robin.parent.BubbleService\"\n    E: receiver\n      A: name=\"app.robin.parent.BootReceiver\"\n"


def _run(tmp_path: Path, flavor: str, perms: list[str], tree: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "perms.txt").write_text(
        "package: app.robin.parent\n" + "".join(f"uses-permission: name='{p}'\n" for p in perms)
    )
    (tmp_path / "tree.txt").write_text(tree)
    fake = tmp_path / "aapt2"
    fake.write_text(
        '#!/usr/bin/env bash\n'
        f'case "$*" in *"dump permissions"*) cat {tmp_path}/perms.txt;; *) cat {tmp_path}/tree.txt;; esac\n'
    )
    fake.chmod(0o755)
    return subprocess.run(
        ["bash", str(SCRIPT), flavor, "x.apk"],
        env={"AAPT2": str(fake), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )


def test_lite_clean_passes(tmp_path):
    r = _run(tmp_path, "lite", BASE, TREE_LITE)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "android.permission.INTERNET" in r.stdout  # the list is printed


def test_full_expected_passes(tmp_path):
    r = _run(tmp_path, "full", BASE + BUBBLE, TREE_FULL)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("forbidden", BUBBLE)
def test_lite_with_any_bubble_permission_fails(tmp_path, forbidden):
    r = _run(tmp_path, "lite", BASE + [forbidden], TREE_LITE)
    assert r.returncode == 1
    assert forbidden in r.stdout


def test_lite_with_unlisted_extra_permission_fails(tmp_path):
    r = _run(tmp_path, "lite", BASE + ["android.permission.READ_CONTACTS"], TREE_LITE)
    assert r.returncode == 1


@pytest.mark.parametrize("name", ["BubbleService", "BootReceiver"])
def test_lite_with_bubble_component_fails(tmp_path, name):
    r = _run(tmp_path, "lite", BASE, TREE_LITE + f'    E: service\n      A: name="app.robin.parent.{name}"\n')
    assert r.returncode == 1
    assert "component" in r.stdout


def test_full_missing_permission_or_component_fails(tmp_path):
    assert _run(tmp_path, "full", BASE + BUBBLE[:-1], TREE_FULL).returncode == 1
    assert _run(tmp_path, "full", BASE + BUBBLE, TREE_LITE).returncode == 1
