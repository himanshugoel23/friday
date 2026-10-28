# ruff: noqa: E501
"""Where probe results live: ``var/sitemcp/`` (git-ignored). Only counts, statuses, timings and a screenshot of a PUBLIC page.
Never a phone number, cookie, cart or logged-in page."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

MAX_HISTORY = 200
SITE_RE = "abcdefghijklmnopqrstuvwxyz0123456789_-"


def safe_site(site: str) -> str | None:
    return site if site and len(site) <= 30 and all(c in SITE_RE for c in site) else None


class ProbeStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _atomic(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ---- live runs
    def save_live(self, result: dict[str, Any], shot: bytes | None) -> None:
        site = safe_site(result["site"])
        if site is None:
            raise ValueError("bad site name")
        last = self.live_all()
        last[site] = result
        self._atomic(self.root / "live_last.json", json.dumps(last, indent=1).encode())
        line = json.dumps({k: result[k] for k in ("site", "finished_at", "overall", "items_found", "priced") if k in result})
        hist = self.root / "live_history.jsonl"
        old = hist.read_text().splitlines() if hist.exists() else []
        self._atomic(hist, ("\n".join([*old, line][-MAX_HISTORY:]) + "\n").encode())
        if shot:
            self._atomic(self.root / "shots" / f"{site}.png", shot)

    def live_all(self) -> dict[str, dict[str, Any]]:
        try:
            d = json.loads((self.root / "live_last.json").read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def shot(self, site: str) -> bytes | None:
        s = safe_site(site)
        if s is None:
            return None
        try:
            return (self.root / "shots" / f"{s}.png").read_bytes()
        except OSError:
            return None

    # ---- selector drift (friday sitemcp probe)
    def save_drift(self, report: dict[str, Any]) -> None:
        d = self.drift_all()
        d[report["site"]] = report
        self._atomic(self.root / "drift_last.json", json.dumps(d, indent=1).encode())

    def drift_all(self) -> dict[str, dict[str, Any]]:
        try:
            d = json.loads((self.root / "drift_last.json").read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}
