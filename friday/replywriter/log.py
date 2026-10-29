# ruff: noqa: E501
"""Local, append-only training-data log of the reply writer (docs/REPLY_WRITER.md, "Data policy").

* Only when FRIDAY_REPLY_LOG_ENABLED. Testers only (the founder and his wife). Nothing leaves the server:
  ``export`` writes a local file and never uploads anything.
* Table-free: one JSONL file ``var/replylog/replies.jsonl`` (dir 0700, file 0600). Each line is encrypted with
  the existing field cipher when one is given (line = ciphertext token), else plain JSON.
* One record per writer call: the ReplyInput (facts only; no phone, no user id, no raw user text; the first name
  is replaced by ``<name>``), the chosen output, which writer produced it, the fact-check result, a timestamp.
  Later events are APPENDED, never edited in place: a thumbs reaction, a review (approved / rejected / edited with
  the founder's gold answer). Reading folds the events into their record.
* Retention (default 90 days) and a size cap drop the oldest records (events go with them). ``delete_all`` and
  ``erase_user`` are hard deletes (file rewritten, no tombstones).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import threading
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from friday.calls.privacy import scrub
from friday.core.logging import get_logger
from friday.replywriter.schema import ReplyInput, ReplyOutput

log = get_logger(__name__)
FILE = "replies.jsonl"
AAD = "replylog"
DEFAULT_DIR = "var/replylog"
TARGET_EXAMPLES = 1000
EXPORT_SYSTEM = "You are Friday's reply writer. Given the intent and facts as JSON, write the chat reply as JSON."
_URL_QUERY = re.compile(r"(https?://[^\s?#\"]+)[?#][^\s\"]*")
_MIN_PRUNE_GAP = timedelta(hours=1)


def user_ref(user_id: str) -> str:
    return hashlib.sha256(f"replylog:{user_id}".encode()).hexdigest()[:16]


def text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:20]


def _clean(value: Any, name: str | None) -> Any:
    """Recursively scrub strings: long digit runs (phones), URL queries, the user's first name."""
    if isinstance(value, str):
        out = _URL_QUERY.sub(r"\1", scrub(value))
        if name and len(name) >= 2:
            out = re.sub(rf"\b{re.escape(name)}\b", "<name>", out, flags=re.I)
        return out
    if isinstance(value, list):
        return [_clean(v, name) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v, name) for k, v in value.items()}
    return value


def _split_gold(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return parts[:5] or [text.strip()]


class ReplyLog:
    def __init__(
        self,
        directory: str | Path = DEFAULT_DIR,
        *,
        retention_days: int = 90,
        max_bytes: int = 20 * 1024 * 1024,
        cipher: Any = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.dir = Path(directory)
        self.retention_days, self.max_bytes, self.cipher = retention_days, max_bytes, cipher
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._last_prune: datetime | None = None
        self.unreadable = 0

    @classmethod
    def from_settings(cls, settings: Any, *, cipher: Any = None, now: Callable[[], datetime] | None = None) -> ReplyLog:
        return cls(
            getattr(settings, "reply_log_dir", DEFAULT_DIR),
            retention_days=int(getattr(settings, "reply_log_retention_days", 90)),
            max_bytes=int(float(getattr(settings, "reply_log_max_mb", 20)) * 1024 * 1024),
            cipher=cipher, now=now,
        )

    @classmethod
    def open(cls, settings: Any, *, now: Callable[[], datetime] | None = None) -> ReplyLog:
        """The log for these settings, encrypted with the process field cipher when one is available."""
        cipher = None
        try:
            from friday.core.crypto import get_field_cipher

            cipher = get_field_cipher()
        except Exception:  # noqa: BLE001 - no cipher (dev profile without keys): plain 0600 file
            log.info("replylog: no field cipher; plain 0600 file")
        return cls.from_settings(settings, cipher=cipher, now=now)

    @property
    def path(self) -> Path:
        return self.dir / FILE

    # ------------------------------------------------------------------ file plumbing
    def _encode(self, obj: dict[str, Any]) -> str:
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        return self.cipher.encrypt(raw, aad=AAD) if self.cipher is not None else raw

    def _decode(self, line: str) -> dict[str, Any] | None:
        line = line.strip()
        if not line:
            return None
        try:
            if self.cipher is not None and self.cipher.is_ciphertext(line):
                line = self.cipher.decrypt(line, aad=AAD)
            obj = json.loads(line)
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001 - an unreadable line (key changed, damaged) is skipped and counted
            self.unreadable += 1
            return None

    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            os.chmod(self.dir, 0o700)

    def _append(self, obj: dict[str, Any]) -> None:
        self._ensure_dir()
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, (self._encode(obj) + "\n").encode())
        finally:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)

    def _rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [r for r in (self._decode(ln) for ln in fh) if r]

    def _rewrite(self, rows: list[dict[str, Any]]) -> None:
        self._ensure_dir()
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".replies-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(self._encode(r) + "\n")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    # ------------------------------------------------------------------ writing
    def record(self, user_id: str, inp: ReplyInput, out: ReplyOutput, *, name: str | None = None) -> str:
        """One record per writer call. Returns its id."""
        rid = hashlib.sha256(f"{user_id}{self._now().isoformat()}{os.urandom(4).hex()}".encode()).hexdigest()[:16]
        name = name or inp.facts.name
        rec = {
            "kind": "record", "id": rid, "ts": self._now().isoformat(timespec="seconds"), "user": user_ref(user_id),
            "intent": inp.intent, "input": _clean(inp.model_dump(mode="json", exclude_none=True), name),
            "output": _clean({"messages": out.messages, "question": out.question, "buttons": [b.id for b in out.buttons], "proofs": out.proofs}, name),
            "writer": out.writer, "fact_check": out.fact_check,
            "hashes": [text_hash(m) for m in out.messages],
        }
        with self._lock:
            self._append(rec)
            self._maybe_prune()
        return rid

    def react_by_text(self, text: str, kind: str, note: str = "") -> bool:
        """The tester's thumbs up/down (or 'wrong') on a sent message: attach to the newest record that sent it."""
        h = text_hash(text)
        with self._lock:
            hit = next((r for r in reversed(self._rows()) if r.get("kind") == "record" and h in r.get("hashes", [])), None)
            if hit is None:
                return False
            self._append({"kind": "event", "event": "reaction", "id": hit["id"], "reaction": kind, "note": _clean(note[:300], None), "ts": self._now().isoformat(timespec="seconds")})
        return True

    def review(self, rid: str, status: str, gold_text: str | None = None) -> bool:
        """The founder's decision: approved | rejected | edited (gold_text = his version, the gold answer)."""
        if status not in ("approved", "rejected", "edited") or (status == "edited" and not (gold_text or "").strip()):
            return False
        with self._lock:
            if not any(r.get("kind") == "record" and r.get("id") == rid for r in self._rows()):
                return False
            ev: dict[str, Any] = {"kind": "event", "event": "review", "id": rid, "status": status, "ts": self._now().isoformat(timespec="seconds")}
            if status == "edited":
                ev["gold"] = _split_gold(_clean(gold_text, None))
            self._append(ev)
        return True

    # ------------------------------------------------------------------ reading
    def items(self) -> list[dict[str, Any]]:
        """Records with their events folded in, newest first: status, reactions, gold."""
        with self._lock:
            rows = self._rows()
        recs: dict[str, dict[str, Any]] = {}
        for r in rows:
            if r.get("kind") == "record":
                recs[r["id"]] = {**r, "status": "pending", "reactions": [], "gold": None}
        for r in rows:
            rec = recs.get(r.get("id", ""))
            if r.get("kind") != "event" or rec is None:
                continue
            if r["event"] == "reaction":
                rec["reactions"].append({"kind": r["reaction"], "note": r.get("note", "")})
            elif r["event"] == "review":
                rec["status"], rec["gold"] = r["status"], r.get("gold")
        return sorted(recs.values(), key=lambda x: x["ts"], reverse=True)

    def stats(self) -> dict[str, Any]:
        its = self.items()
        ready = sum(1 for i in its if i["status"] in ("approved", "edited"))
        return {
            "records": len(its),
            "by_writer": dict(Counter(i["writer"] for i in its)),
            "by_intent": dict(Counter(i["intent"] for i in its)),
            "by_status": dict(Counter(i["status"] for i in its)),
            "fact_check_rejected": sum(1 for i in its if str(i["fact_check"]).startswith("rejected")),
            "reactions": dict(Counter(r["kind"] for i in its for r in i["reactions"])),
            "approved_examples": ready,
            "fine_tune_target": TARGET_EXAMPLES,
            "oldest": its[-1]["ts"] if its else None,
            "newest": its[0]["ts"] if its else None,
            "bytes": self.path.stat().st_size if self.path.exists() else 0,
            "unreadable_lines": self.unreadable,
            "retention_days": self.retention_days,
        }

    # ------------------------------------------------------------------ export / delete / retention
    def export_approved(self, out_path: str | Path | None = None) -> tuple[Path, int]:
        """Write approved (and founder-edited) examples as fine-tuning JSONL. LOCAL FILE ONLY, nothing is uploaded."""
        target = Path(out_path) if out_path else self.dir / f"export-{self._now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for it in reversed(self.items()):
                if it["status"] not in ("approved", "edited"):
                    continue
                if it["status"] == "edited" and it["gold"]:
                    msgs = it["gold"]
                    last = [ln for ln in msgs[-1].splitlines() if ln.strip()][-1].strip()
                    answer = {"messages": msgs, "question": last if last.endswith("?") else None}
                else:
                    answer = {"messages": it["output"]["messages"], "question": it["output"].get("question")}
                fh.write(json.dumps({"messages": [
                    {"role": "system", "content": EXPORT_SYSTEM},
                    {"role": "user", "content": json.dumps(it["input"], ensure_ascii=False)},
                    {"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)},
                ]}, ensure_ascii=False) + "\n")
                n += 1
        return target, n

    def delete_all(self) -> int:
        """Hard delete: every record and event, plus old exports. Returns the number of records removed."""
        with self._lock:
            n = sum(1 for r in self._rows() if r.get("kind") == "record")
            for f in (self.path, *self.dir.glob("export-*.jsonl"), *self.dir.glob(".replies-*.tmp")):
                with contextlib.suppress(OSError):
                    f.unlink()
        return n

    def erase_user(self, user_id: str) -> int:
        """A tester was erased ('delete everything'): drop their records and events."""
        ref = user_ref(user_id)
        with self._lock:
            rows = self._rows()
            gone = {r["id"] for r in rows if r.get("kind") == "record" and r.get("user") == ref}
            if not gone:
                return 0
            self._rewrite([r for r in rows if r.get("id") not in gone])
        return len(gone)

    def prune(self) -> int:
        with self._lock:
            return self._prune()

    def _maybe_prune(self) -> None:
        now = self._now()
        too_big = self.path.exists() and self.path.stat().st_size > self.max_bytes
        if too_big or self._last_prune is None or now - self._last_prune >= _MIN_PRUNE_GAP:
            self._prune()

    def _prune(self) -> int:
        self._last_prune = self._now()
        rows = self._rows()
        cutoff = (self._now() - timedelta(days=self.retention_days)).isoformat(timespec="seconds")
        recs = [r for r in rows if r.get("kind") == "record"]
        drop = {r["id"] for r in recs if r["ts"] < cutoff}
        keep = [r for r in rows if r.get("id") not in drop]
        size = sum(len(self._encode(r)) + 1 for r in keep)
        if size > self.max_bytes:  # size cap: oldest records go first, down to 90% of the cap
            for r in sorted((r for r in keep if r.get("kind") == "record"), key=lambda r: r["ts"]):
                if size <= self.max_bytes * 0.9:
                    break
                drop.add(r["id"])
                size -= len(self._encode(r)) + 1
            keep = [r for r in keep if r.get("id") not in drop]
        if drop:
            self._rewrite(keep)
            log.info("replylog: pruned %d record(s)", len(drop))
        return len(drop)
