# ruff: noqa: E501
"""Local append-only store for waitlist sign-ups and anonymous page-view counts.

Sign-up lines hold: id, time, first name, phone (E.164), city, parent language, who it is for, worries, src, consent
version. Lines are encrypted with the process field cipher when one exists (else plain JSON, file mode 0600).
Page views are counted per day and per ``src`` only: no IP, no user agent.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

CONSENT_VERSION = "2026-11-04-a"
WORRIES = ("scam_calls", "medicines", "living_alone", "emergencies", "loneliness", "bills")
LANGS = ("hindi", "english", "punjabi", "marathi", "gujarati", "bengali", "tamil", "telugu", "kannada", "other")
FOR = ("mother", "father", "both", "other")
SRC_RE = re.compile(r"^[a-z0-9_-]{1,24}$")
_AAD = "robin_waitlist"


def clean_src(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    return s if SRC_RE.match(s) else "direct"


def clean_v(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    return s if re.match(r"^[a-z][a-z0-9]?$", s) or s == "legacy" else ""


def mask(phone: str) -> str:
    return "*" * max(0, len(phone) - 2) + phone[-2:]


class WaitlistStore:
    def __init__(self, root: str | Path, *, cipher: Any = None, now: Callable[[], datetime] | None = None) -> None:
        self.root = Path(root)
        self.cipher = cipher
        self.now = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ files
    def _path(self, name: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        return self.root / name

    def _write_lines(self, name: str, lines: list[str]) -> None:
        p = self._path(name)
        tmp = p.with_suffix(".tmp")
        tmp.write_text("".join(x + "\n" for x in lines), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)

    def _seal(self, row: dict[str, Any]) -> str:
        text = json.dumps(row, separators=(",", ":"), ensure_ascii=False)
        return self.cipher.encrypt(text, aad=_AAD) if self.cipher is not None else text

    def _open(self, line: str) -> dict[str, Any] | None:
        try:
            text = self.cipher.decrypt(line, aad=_AAD) if self.cipher is not None and not line.startswith("{") else line
            row = json.loads(text)
            return row if isinstance(row, dict) else None
        except Exception:  # noqa: BLE001 - a bad line never breaks the page
            return None

    def _rows(self) -> list[dict[str, Any]]:
        p = self.root / "signups.jsonl"
        if not p.exists():
            return []
        out = [self._open(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in out if r]

    # ------------------------------------------------------------------ sign-ups
    def add(self, *, name: str, phone: str, city: str, lang: str, whom: str, worries: list[str], src: str, v: str = "") -> tuple[str, bool]:
        """Returns (id, created). The same phone twice is idempotent (created=False)."""
        with self._lock:
            rows = self._rows()
            for r in rows:
                if r.get("phone") == phone:
                    return str(r["id"]), False
            row = {"id": secrets.token_hex(4), "ts": self.now().isoformat(timespec="seconds"), "name": name[:40], "phone": phone,
                   "city": city[:60], "lang": lang, "whom": whom, "worries": worries, "src": clean_src(src), "v": clean_v(v), "consent": CONSENT_VERSION}
            with self._path("signups.jsonl").open("a", encoding="utf-8") as f:
                f.write(self._seal(row) + "\n")
            os.chmod(self.root / "signups.jsonl", 0o600)
            return str(row["id"]), True

    def delete_phone(self, phone: str) -> int:
        with self._lock:
            p = self.root / "signups.jsonl"
            if not p.exists():
                return 0
            keep, gone = [], 0
            for line in p.read_text(encoding="utf-8").splitlines():
                row = self._open(line)
                if row is not None and row.get("phone") == phone:
                    gone += 1
                elif line.strip():
                    keep.append(line)
            self._write_lines("signups.jsonl", keep)
            return gone

    def delete_all(self) -> None:
        with self._lock:
            for n in ("signups.jsonl", "views.json"):
                (self.root / n).unlink(missing_ok=True)

    # ------------------------------------------------------------------ views
    def view(self, src: str, v: str = "") -> None:
        with self._lock:
            p = self._path("views.json")
            try:
                data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except ValueError:
                data = {}
            day = self.now().date().isoformat()
            key = f"{day}|{clean_src(src)}|{clean_v(v)}"
            data[key] = int(data.get(key, 0)) + 1
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)

    def _views(self) -> dict[str, int]:
        try:
            return {k: int(v) for k, v in json.loads((self.root / "views.json").read_text(encoding="utf-8")).items()}
        except (OSError, ValueError):
            return {}

    # ------------------------------------------------------------------ reports
    def count(self) -> int:
        return len(self._rows())

    def summary(self) -> str:
        rows = self._rows()
        views = self._views()
        today = self.now().date()
        days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        per_day = Counter(str(r["ts"])[:10] for r in rows)
        by_src, v_src = Counter(r.get("src", "direct") for r in rows), Counter()
        v_var = Counter()
        for k, n in views.items():
            parts = k.split("|")
            v_src[parts[1]] += n
            if len(parts) > 2 and parts[2]:
                v_var[parts[2]] += n
        total_views = sum(views.values())
        out = [f"Robin waitlist: {len(rows)} sign-ups, {total_views} page views"
               + (f" ({100 * len(rows) / total_views:.1f}% joined)" if total_views else "")]
        out.append("Last 7 days: " + ", ".join(f"{d[5:]}={per_day.get(d, 0)}" for d in days))
        if by_src:
            out.append("By source: " + ", ".join(f"{s}={n} of {v_src.get(s, 0)} views" for s, n in by_src.most_common(8)))
        by_var = Counter(r.get("v", "") for r in rows if r.get("v"))
        if by_var or v_var:
            out.append("By page variant: " + ", ".join(f"{k}={by_var.get(k, 0)} of {v_var.get(k, 0)} views" + (f" ({100 * by_var.get(k, 0) / v_var[k]:.1f}%)" if v_var.get(k) else "") for k in sorted(set(by_var) | set(v_var))))
        for label, key in (("Cities", "city"), ("Parent language", "lang"), ("For", "whom")):
            c = Counter(str(r.get(key, "")).strip().title() for r in rows if r.get(key))
            if c:
                out.append(f"{label}: " + ", ".join(f"{k}={n}" for k, n in c.most_common(8)))
        w = Counter(x for r in rows for x in r.get("worries", []))
        if w:
            out.append("Worries: " + ", ".join(f"{k}={n}" for k, n in w.most_common()))
        intl = sum(1 for r in rows if not str(r.get("phone", "")).startswith("+91"))
        out.append(f"Outside India (+ other country codes): {intl}")
        out.append("Latest: " + ", ".join(f"{r['name']} {mask(str(r['phone']))}" for r in rows[-5:]) if rows else "Latest: none yet")
        return "\n".join(out) + "\n"

    def csv(self) -> str:
        def q(v: Any) -> str:
            s = str(v).replace('"', '""')
            return f'"{s}"'
        head = "id,time,name,phone,city,parent_language,for,worries,src,variant,consent"
        lines = [head]
        for r in self._rows():
            lines.append(",".join(q(r.get(k, "")) if k != "worries" else q(";".join(r.get(k, [])))
                                  for k in ("id", "ts", "name", "phone", "city", "lang", "whom", "worries", "src", "v", "consent")))
        return "\n".join(lines) + "\n"
