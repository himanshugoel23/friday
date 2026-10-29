# ruff: noqa: E501
"""Persistence: run state (restart-safe), proofs (small, auto-expiring), facts (the user's erasable memory), event log.

Run state holds the goal, step history (element LABELS, never typed values), the open question and the permits. It holds NO
password, code or stored fact value: answers go to the user's memory (``FactSource``), which "forget" and "delete everything"
already erase."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import uuid
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from friday.browser_agent import rules
from friday.browser_agent.types import TERMINAL, RunState
from friday.core.logging import get_logger
from friday.voice.text import redact_secrets

log = get_logger(__name__)
SAFE_ID = re.compile(r"^[a-f0-9]{8,32}$")
MAX_PROOF_BYTES = 700_000


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]


# ----------------------------------------------------------------------------- run store
class MemoryRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, str] = {}

    def save(self, state: RunState) -> None:
        self._runs[state.id] = state.model_dump_json()

    def load(self, run_id: str) -> RunState | None:
        raw = self._runs.get(run_id)
        return RunState.model_validate_json(raw) if raw else None

    def _all(self) -> list[RunState]:
        return [RunState.model_validate_json(v) for v in self._runs.values()]

    def active_for(self, user_id: str) -> RunState | None:
        mine = [s for s in self._all() if s.user_id == user_id and s.status not in TERMINAL]
        return max(mine, key=lambda s: s.updated_at) if mine else None

    def list_open(self) -> list[RunState]:
        return [s for s in self._all() if s.status not in TERMINAL]

    def delete_user(self, user_id: str) -> int:
        gone = [k for k, v in self._runs.items() if RunState.model_validate_json(v).user_id == user_id]
        for k in gone:
            del self._runs[k]
        return len(gone)


class JsonRunStore:
    """One JSON file per run, written atomically (survives a restart in the middle of a write)."""

    def __init__(self, root: Path | str) -> None:
        self.dir = Path(root) / "runs"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        if not SAFE_ID.match(run_id):
            raise ValueError("bad run id")
        return self.dir / f"{run_id}.json"

    def save(self, state: RunState) -> None:
        data = state.model_dump_json()
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
            os.replace(tmp, self._path(state.id))
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    def load(self, run_id: str) -> RunState | None:
        try:
            return RunState.model_validate_json(self._path(run_id).read_text())
        except (OSError, ValueError):
            return None

    def _all(self) -> list[RunState]:
        out: list[RunState] = []
        for p in self.dir.glob("*.json"):
            with contextlib.suppress(OSError, ValueError):
                out.append(RunState.model_validate_json(p.read_text()))
        return out

    def active_for(self, user_id: str) -> RunState | None:
        mine = [s for s in self._all() if s.user_id == user_id and s.status not in TERMINAL]
        return max(mine, key=lambda s: s.updated_at) if mine else None

    def list_open(self) -> list[RunState]:
        return [s for s in self._all() if s.status not in TERMINAL]

    def delete_user(self, user_id: str) -> int:
        n = 0
        for s in self._all():
            if s.user_id == user_id:
                with contextlib.suppress(OSError):
                    self._path(s.id).unlink()
                    n += 1
        return n

    def purge_finished(self, now: datetime, keep_days: int = 30) -> int:
        n = 0
        for s in self._all():
            if s.status in TERMINAL and s.updated_at and datetime.fromisoformat(s.updated_at) < now - timedelta(days=keep_days):
                with contextlib.suppress(OSError):
                    self._path(s.id).unlink()
                    n += 1
        return n


# ----------------------------------------------------------------------------- proofs
class ProofStore:
    """A proof is one screenshot + what / where / when. Small (<= 700 KB), kept ``ttl_days`` (default 14), then purged."""

    def __init__(self, root: Path | str, *, ttl_days: int = 14, clock: Any = None) -> None:
        self.root, self.ttl = Path(root) / "proofs", timedelta(days=ttl_days)
        self.root.mkdir(parents=True, exist_ok=True)
        self._now = (lambda: clock.now()) if clock is not None else (lambda: datetime.now(UTC))

    def _udir(self, user_id: str) -> Path:
        return self.root / hashlib.sha256(user_id.encode()).hexdigest()[:12]

    def save(self, user_id: str, run_id: str, what: str, url: str, png: bytes) -> tuple[str, str]:
        d = self._udir(user_id)
        d.mkdir(parents=True, exist_ok=True)
        pid = uuid.uuid4().hex[:12]
        meta = {"id": pid, "run": run_id, "what": redact_secrets(what)[:200], "where": rules.strip_query(url),
                "when": self._now().isoformat(timespec="seconds"), "image": ""}
        ext = "jpg" if png[:3] == b"\xff\xd8\xff" else "png"
        if png and len(png) <= MAX_PROOF_BYTES:
            (d / f"{pid}.{ext}").write_bytes(png)
            meta["image"] = f"{pid}.{ext}"
        (d / f"{pid}.json").write_text(json.dumps(meta))
        return pid, str(d / (meta["image"] or f"{pid}.json"))

    def list_for(self, user_id: str) -> list[dict[str, Any]]:
        d = self._udir(user_id)
        out = []
        for p in sorted(d.glob("*.json")) if d.exists() else []:
            with contextlib.suppress(OSError, ValueError):
                out.append(json.loads(p.read_text()))
        return out

    def purge(self) -> int:
        n, cutoff = 0, self._now() - self.ttl
        for p in self.root.glob("*/*.json"):
            try:
                meta = json.loads(p.read_text())
                if datetime.fromisoformat(meta["when"]) < cutoff:
                    for f in (p, p.with_name(meta.get("image") or "-")):
                        with contextlib.suppress(OSError):
                            f.unlink()
                    n += 1
            except (OSError, ValueError, KeyError):
                continue
        return n

    def delete_user(self, user_id: str) -> int:
        d, n = self._udir(user_id), 0
        for f in list(d.glob("*")) if d.exists() else []:
            with contextlib.suppress(OSError):
                f.unlink()
                n += 1
        return n


# ----------------------------------------------------------------------------- facts
class MemoryFacts:
    """Tests and the playbook preview: facts in a dict."""

    def __init__(self, initial: dict[str, dict[str, str]] | None = None) -> None:
        self.data = {u: dict(v) for u, v in (initial or {}).items()}

    async def load(self, user_id: str) -> dict[str, str]:
        return dict(self.data.get(user_id, {}))

    async def remember(self, user_id: str, key: str, value: str) -> None:
        self.data.setdefault(user_id, {})[key] = value


FACT_PREFIX = "ba:"


class RepoFacts:
    """The user's profile + what the agent learned, in the existing erasable ``Fact`` table (key ``ba:<key>``)."""

    def __init__(self, repos: Any) -> None:
        self.repos = repos

    async def load(self, user_id: str) -> dict[str, str]:
        out: dict[str, str] = {}
        with contextlib.suppress(Exception):
            user = await self.repos.users.get(user_id)
            if user is not None and user.phone:
                out["phone"] = user.phone
            prof = await self.repos.profiles.get(user_id)
            if prof is not None:
                if prof.name:
                    out["full_name"] = prof.name
                if prof.city:
                    out["current_city"] = prof.city
        for f in await self.repos.facts.list_for_user(user_id):
            if f.key.startswith(FACT_PREFIX):
                out[f.key[len(FACT_PREFIX):]] = f.value
        return out

    async def remember(self, user_id: str, key: str, value: str) -> None:
        from friday.core.models import Fact, FactKind

        await self.repos.facts.upsert(Fact(user_id=user_id, kind=FactKind.PREFERENCE, key=FACT_PREFIX + key, value=value[:400]))


# ----------------------------------------------------------------------------- files
class FileRefs:
    """File references the USER registered (resume ...). The model only ever names a ref; it never supplies a path."""

    ALLOWED_EXT = (".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg")
    MAX_BYTES = 5_000_000

    def __init__(self, refs: dict[str, dict[str, str]] | None = None) -> None:
        self.refs = refs or {}  # user_id -> {ref: path}

    def register(self, user_id: str, ref: str, path: str) -> bool:
        p = Path(path)
        if p.suffix.lower() not in self.ALLOWED_EXT or not p.is_file() or p.stat().st_size > self.MAX_BYTES:
            return False
        self.refs.setdefault(user_id, {})[ref] = str(p)
        return True

    def resolve(self, user_id: str, file_ref: str) -> str | None:
        return self.refs.get(user_id, {}).get(file_ref)

    def names(self, user_id: str) -> list[str]:
        return sorted(self.refs.get(user_id, {}))


# ----------------------------------------------------------------------------- event log (no secrets)
class AgentLog:
    """Structured events for the audit trail and tests. Values typed into forms NEVER reach it: only sources, labels, ids, statuses."""

    def __init__(self, sink: Any = None, keep: int = 500) -> None:
        self.events: deque[dict[str, Any]] = deque(maxlen=keep)
        self.sink = sink  # optional callable(event: str, **detail)

    def __call__(self, event: str, **detail: object) -> None:
        clean = {k: (redact_secrets(v)[:200] if isinstance(v, str) else v) for k, v in detail.items()}
        self.events.append({"event": event, **clean})
        log.info("browser_agent %s %s", event, {k: v for k, v in clean.items() if k != "note"})
        if self.sink is not None:
            with contextlib.suppress(Exception):
                self.sink(event, **clean)
