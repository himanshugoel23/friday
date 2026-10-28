"""Remote read of the last bench report: ``GET /ops-status/<token>/bench`` (404 unless switched on)."""

from __future__ import annotations

import os

from dotenv import dotenv_values

SWITCH = "FRIDAY_OPS_BENCH_ENABLED"
DEFAULT_FILE = "/opt/friday/var/bench/last.txt"
MAX_BYTES = 60_000


def enabled() -> bool:
    v = os.environ.get(SWITCH) or str(dotenv_values(".env").get(SWITCH) or "")
    return v.strip().lower() in ("1", "true", "yes", "on")


def report_path() -> str:
    return os.environ.get("FRIDAY_OPS_BENCH_FILE", DEFAULT_FILE)
