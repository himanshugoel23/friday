# ruff: noqa: E501
"""Persistent queue state (stdlib sqlite, WAL): safe across processes and restarts, no migration.

States: waiting -> active -> done | reclaimed;  waiting -> expired | cancelled.
Only a hash of the destination and its last two digits are stored.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from friday.callqueue.limits import Limits

URGENT, NORMAL = 0, 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL,
  dest TEXT NOT NULL,
  tail TEXT NOT NULL,
  priority INTEGER NOT NULL,
  state TEXT NOT NULL,
  enqueued_at REAL NOT NULL,
  started_at REAL,
  deadline_at REAL,
  ring_s REAL NOT NULL,
  max_s REAL NOT NULL,
  provider_call_id TEXT,
  outcome TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS entries_live_key ON entries(key) WHERE state IN ('waiting','active');
CREATE INDEX IF NOT EXISTS entries_state ON entries(state, priority, enqueued_at);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v REAL NOT NULL);
"""


def dest_hash(number: str) -> str:
    return hashlib.sha256(("friday-callqueue:" + number).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class Entry:
    id: int
    key: str
    tail: str
    priority: int
    state: str
    enqueued_at: float
    started_at: float | None
    deadline_at: float | None
    ring_s: float
    max_s: float
    provider_call_id: str | None
    outcome: str | None


_COLS = "id,key,tail,priority,state,enqueued_at,started_at,deadline_at,ring_s,max_s,provider_call_id,outcome"


class QueueStore:
    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time) -> None:
        self.path = str(path)
        self.clock = clock
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self._db.execute("PRAGMA busy_timeout=10000")
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def get(self, entry_id: int) -> Entry | None:
        row = self._db.execute(f"SELECT {_COLS} FROM entries WHERE id=?", (entry_id,)).fetchone()
        return Entry(*row) if row else None

    def enqueue(
        self, *, key: str, number: str, priority: int, ring_s: float, max_s: float
    ) -> tuple[Entry, bool]:
        """Idempotent: a live (waiting/active) entry with the same key is returned, not duplicated."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                f"SELECT {_COLS} FROM entries WHERE key=? AND state IN ('waiting','active')", (key,)
            ).fetchone()
            if row:
                self._db.execute("COMMIT")
                return Entry(*row), False
            cur = self._db.execute(
                "INSERT INTO entries(key,dest,tail,priority,state,enqueued_at,ring_s,max_s) "
                "VALUES(?,?,?,?,'waiting',?,?,?)",
                (key, dest_hash(number), number[-2:], priority, self.clock(), ring_s, max_s),
            )
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        e = self.get(int(cur.lastrowid or 0))
        assert e is not None
        return e, True

    def try_grant(self, entry_id: int, limits: Limits, grace_s: float) -> tuple[bool, float, int]:
        """Atomically start ``entry_id`` if it is the first eligible waiter and every limit allows.

        Stale active slots (past their deadline: a crashed process never released them) are
        reclaimed first. Returns (granted, retry_after_s, reclaimed_count)."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            now = self.clock()
            reclaimed = self._db.execute(
                "UPDATE entries SET state='reclaimed', outcome='stale' "
                "WHERE state='active' AND deadline_at IS NOT NULL AND deadline_at < ?",
                (now,),
            ).rowcount
            me = self._db.execute(
                "SELECT state, ring_s, max_s FROM entries WHERE id=?", (entry_id,)
            ).fetchone()
            if not me or me[0] != "waiting":
                self._db.execute("COMMIT")
                return False, 0.0, reclaimed
            active = self._db.execute("SELECT dest FROM entries WHERE state='active'").fetchall()
            busy = {r[0] for r in active}
            gate = 0.0
            if len(active) >= limits.max_concurrent:
                gate = 1.0
            last = self._db.execute("SELECT v FROM meta WHERE k='last_start'").fetchone()
            if last and now - last[0] < limits.min_start_gap_s:
                gate = max(gate, limits.min_start_gap_s - (now - last[0]))
            # first eligible waiter in (priority, age) order; one live call per destination
            first_id = None
            for wid, wdest in self._db.execute(
                "SELECT id, dest FROM entries WHERE state='waiting' ORDER BY priority, enqueued_at, id"
            ):
                if wdest in busy:
                    continue
                first_id = wid
                break
            if first_id != entry_id or gate > 0:
                self._db.execute("COMMIT")
                return False, gate or 0.25, reclaimed
            self._db.execute(
                "UPDATE entries SET state='active', started_at=?, deadline_at=? WHERE id=?",
                (now, now + me[1] + me[2] + grace_s, entry_id),
            )
            self._db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('last_start', ?)", (now,))
            self._db.execute("COMMIT")
            return True, 0.0, reclaimed
        except BaseException:
            self._db.execute("ROLLBACK")
            raise

    def finish(self, entry_id: int, state: str, outcome: str) -> bool:
        cur = self._db.execute(
            "UPDATE entries SET state=?, outcome=? WHERE id=? AND state IN ('waiting','active')",
            (state, outcome, entry_id),
        )
        return cur.rowcount > 0

    def set_call_id(self, entry_id: int, provider_call_id: str) -> None:
        self._db.execute(
            "UPDATE entries SET provider_call_id=? WHERE id=?", (provider_call_id, entry_id)
        )

    def counts(self) -> dict[str, int]:
        out = {"waiting": 0, "active": 0, "stale": 0}
        for st, n in self._db.execute(
            "SELECT state, COUNT(*) FROM entries WHERE state IN ('waiting','active') GROUP BY state"
        ):
            out[st] = n
        out["stale"] = self._db.execute(
            "SELECT COUNT(*) FROM entries WHERE state='active' AND deadline_at < ?", (self.clock(),)
        ).fetchone()[0]
        return out

    def prune(self, older_than_s: float = 7 * 86400) -> int:
        return self._db.execute(
            "DELETE FROM entries WHERE state NOT IN ('waiting','active') AND enqueued_at < ?",
            (self.clock() - older_than_s,),
        ).rowcount
