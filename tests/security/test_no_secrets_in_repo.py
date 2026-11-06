# ruff: noqa: E501
"""T03: the repo is PUBLIC. Walk the tree and fail on key-shaped strings and real-looking phone numbers.

Excluded: ``.venv``, ``var``, ``.git``, ``.claude`` (worktrees), caches, ``node_modules`` and every ``.env`` / ``.env.*`` file
(never opened; the committed template ``.env.example`` is the one exception, it is a public file and is scanned).
Phone numbers: any Indian-mobile-shaped or ``+``-international number is a hit unless it is on the allow-list
(``tests/security/secrets_allowlist.txt``: one entry per line, ``kind :: regex :: path-glob :: reason``; a phone regex is matched, in full, against the digits only: the last 10 for an Indian
mobile, all digits for an international number; a key regex against the matched text). The scanner proves
itself with a negative control: strings assembled at run time (so this file never contains one) MUST be flagged.
"""

from __future__ import annotations

import fnmatch
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name("secrets_allowlist.txt")
EXCLUDE_DIRS = {".venv", "venv", "var", ".git", ".claude", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "htmlcov", "dist", "build", ".idea", ".vscode"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".onnx", ".pdf", ".woff", ".woff2", ".ttf", ".zip", ".gz", ".db", ".sqlite3", ".pyc", ".mp3", ".wav", ".ogg", ".opus", ".lock"}
MAX_BYTES = 2_000_000

KEY_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai/anthropic style key": re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}"),
    "aws access key id": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "github token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    "slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "meta/whatsapp token": re.compile(r"\bEAA[A-Za-z0-9]{60,}"),
    "stripe/razorpay live key": re.compile(r"\b(?:sk|rk|pk)_live_[A-Za-z0-9]{16,}|\brzp_live_[A-Za-z0-9]{10,}"),
    "twilio sid/token": re.compile(r"\bAC[0-9a-f]{32}\b|\bSK[0-9a-f]{32}\b"),
    "private key block": re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "assigned secret": re.compile(r"""(?ix)\b(?:api[_-]?key|secret|token|passwd|password|auth)[a-z_]*\s*[:=]\s*["'](?=[A-Za-z0-9+/_=-]{24,}["'])(?=[^"']*\d)(?=[^"']*[A-Za-z])[A-Za-z0-9+/_=-]{24,}["']"""),
}
# +91 / 91 / 0 prefixed Indian mobiles (6-9 start, 10 digits) and any other "+country number" of 10-14 digits
PHONE_PATTERNS: dict[str, re.Pattern[str]] = {
    "indian mobile": re.compile(r"(?<![\w.])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?![\w])"),
    "international number": re.compile(r"(?<![\w.])\+(?!91)[1-9]\d{9,13}(?!\d)"),
}


@dataclass(frozen=True)
class Hit:
    kind: str
    what: str
    path: str
    line: int
    text: str

    def show(self) -> str:
        return f"{self.path}:{self.line}: {self.kind} [{self.what}]  {self.text[:6]}...(masked)"


def iter_files(root: Path) -> Iterator[Path]:
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
        for name in sorted(files):
            if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
                continue  # never opened
            p = Path(dirpath) / name
            if p.suffix.lower() in SKIP_SUFFIXES or p.is_symlink() or p == ALLOWLIST:  # the allow-list names the values it allows
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield p


def scan_text(path: str, text: str) -> list[Hit]:
    hits: list[Hit] = []
    for n, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:  # minified blobs: only keys matter
            line = line[:4000]
        for what, rx in KEY_PATTERNS.items():
            for m in rx.finditer(line):
                hits.append(Hit("key", what, path, n, m.group(0)))
        for what, rx in PHONE_PATTERNS.items():
            for m in rx.finditer(line):
                digits = re.sub(r"\D", "", m.group(0))
                if len(digits) >= 10:
                    hits.append(Hit("phone", what, path, n, m.group(0)))
    return hits


def load_allowlist() -> list[tuple[str, re.Pattern[str], str, str]]:
    out = []
    for raw in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = [p.strip() for p in raw.split(" :: ")]
        assert len(parts) == 4 and all(parts), f"bad allow-list line (need 'kind :: regex :: path-glob :: reason'): {raw}"
        kind, rx, glob, reason = parts
        assert kind in ("key", "phone"), raw
        out.append((kind, re.compile(rx), glob, reason))
    return out


def national(hit: Hit) -> str:
    """What a phone allow-list entry is matched against: digits only, the last 10 for an Indian mobile (so +91, spaces and dashes do not matter)."""
    d = re.sub(r"\D", "", hit.text)
    return d[-10:] if hit.what == "indian mobile" else d


def allowed(hit: Hit, allow: list[tuple[str, re.Pattern[str], str, str]]) -> bool:
    subject = national(hit) if hit.kind == "phone" else hit.text
    return any(k == hit.kind and rx.fullmatch(subject) and fnmatch.fnmatch(hit.path, glob) for k, rx, glob, _ in allow)


def scan_tree(root: Path) -> list[Hit]:
    allow = load_allowlist()
    found: list[Hit] = []
    for p in iter_files(root):
        rel = p.relative_to(root).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found += [h for h in scan_text(rel, text) if not allowed(h, allow)]
    return found


def test_the_repo_tree_has_no_key_shaped_strings_and_no_real_looking_phone_numbers():
    hits = scan_tree(ROOT)
    assert not hits, (
        "Public repo: remove it, or (for an INVENTED number / a documented placeholder) add a line to tests/security/secrets_allowlist.txt.\n"
        + "\n".join(h.show() for h in hits[:40])
    )


def test_negative_control_the_scanner_flags_planted_strings():
    """Strings are assembled at run time so this file itself stays clean. If a pattern stops matching, this fails."""
    planted_keys = {
        "openai/anthropic style key": "sk-" + "A1b2C3d4" * 4,
        "aws access key id": "AKIA" + "ABCDEFGHIJKLMNOP",
        "github token": "ghp_" + "a1B2c3D4e5" * 4,
        "slack token": "xoxb-" + "1234567890-abcdef",
        "google api key": "AIza" + "Sy" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5pQr",
        "private key block": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "jwt": "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abcdefghij1234567890",
        "assigned secret": 'api_key = "' + "Zx9Qw8Er7Ty6Ui5Op4As3Df2" + '"',
    }
    for what, value in planted_keys.items():
        assert any(h.what == what for h in scan_text("planted.txt", f"x = {value}\n")), what
    for number in ("+91" + "98765" + "43210", "98765 43210", "+1" + "415555" + "0132", "0" + "9876543210"):
        assert any(h.kind == "phone" for h in scan_text("planted.md", f"call me on {number} now\n")), number
    assert not scan_text("ok.md", "build 1234567890123 at 2026-11-06, id 0123456789abcdef, port 8080\n")


def test_negative_control_a_planted_file_in_a_temp_tree_fails_and_the_allowlist_can_clear_it(tmp_path, monkeypatch):
    secret = "sk-" + "Q9w8E7r6T5y4U3i2O1p0" * 2
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text(f"token: {secret}\nring +91{'9812345678'}\n", encoding="utf-8")
    (tmp_path / ".env").write_text(f"KEY={secret}\n", encoding="utf-8")  # must never be read
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.py").write_text(f"K = '{secret}'\n", encoding="utf-8")
    empty = tmp_path / "empty-allow.txt"
    empty.write_text("# nothing allowed\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ALLOWLIST", empty)
    hits = scan_tree(tmp_path)
    assert {(h.path, h.kind) for h in hits} == {("docs/note.md", "key"), ("docs/note.md", "phone")}  # .env and .venv were not opened
    allow = tmp_path / "allow.txt"
    allow.write_text("phone :: 9812345678 :: docs/*.md :: test fixture, invented\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ALLOWLIST", allow)
    assert {(h.path, h.kind) for h in scan_tree(tmp_path)} == {("docs/note.md", "key")}


def test_the_allowlist_is_well_formed_and_every_entry_has_a_reason():
    entries = load_allowlist()
    assert all(reason for *_, reason in entries)
