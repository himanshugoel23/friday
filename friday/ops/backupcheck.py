# ruff: noqa: E501
"""Backup / restore check for the Robin, Robin device and concierge tables (T19).

``deploy/backup.sh`` dumps the WHOLE Postgres database (``pg_dump`` with no table filter), so every ``robin_*`` table is in each backup.
This module proves the same thing on SQLite, the engine the tests use: dump a database to SQL text, load it into a fresh file, and compare
the row count and a checksum of every table. It prints table NAMES and COUNTS only, never a value (the data columns are encrypted anyway).

    python -m friday.ops.backupcheck /path/to/friday.db        # exit 0 = every table restored identically

On Postgres the same check is the restore drill in deploy/restore.md section C (row counts of the ``robin_*`` tables after ``pg_restore``).
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROBIN_PREFIX = "robin_"


def expected_robin_tables() -> list[str]:
    """Every model table of Robin, the device package and the concierge desk, read from the SQLAlchemy metadata (so a new table is never forgotten)."""
    import friday.db.tables  # noqa: F401
    from friday.db.base import Base

    return sorted(t for t in Base.metadata.tables if t.startswith(ROBIN_PREFIX))


@dataclass
class RestoreReport:
    counts: dict[str, int] = field(default_factory=dict)
    missing_in_source: list[str] = field(default_factory=list)
    missing_after_restore: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing_in_source or self.missing_after_restore or self.mismatched)

    def lines(self) -> list[str]:
        out = [f"{name}: {n} rows" for name, n in sorted(self.counts.items())]
        out += [f"MISSING in source: {n}" for n in self.missing_in_source]
        out += [f"MISSING after restore: {n}" for n in self.missing_after_restore]
        out += [f"DIFFERENT after restore: {n}" for n in self.mismatched]
        out.append("RESTORE CHECK OK" if self.ok else "RESTORE CHECK FAILED")
        return out


def _tables(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _fingerprint(con: sqlite3.Connection, table: str) -> tuple[int, str]:
    h = hashlib.sha256()
    n = 0
    for row in con.execute(f'SELECT * FROM "{table}" ORDER BY 1'):  # noqa: S608 - table name comes from sqlite_master
        h.update(repr(row).encode())
        n += 1
    return n, h.hexdigest()


def restore_check(source: str | Path, work_dir: str | Path | None = None, expected: list[str] | None = None) -> RestoreReport:
    """Dump ``source`` (a SQLite file) to SQL text, restore into a new file, and compare every table. Read-only on the source."""
    expected = expected_robin_tables() if expected is None else expected
    report = RestoreReport()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        src_tables = _tables(src)
        report.missing_in_source = [t for t in expected if t not in src_tables]
        dump = "\n".join(src.iterdump())
        before = {t: _fingerprint(src, t) for t in src_tables}
    finally:
        src.close()
    with tempfile.TemporaryDirectory(dir=work_dir) as td:
        dest = sqlite3.connect(str(Path(td) / "restored.db"))
        try:
            dest.executescript(dump)
            after_tables = _tables(dest)
            report.missing_after_restore = [t for t in before if t not in after_tables]
            for t in before:
                if t not in after_tables:
                    continue
                if _fingerprint(dest, t) != before[t]:
                    report.mismatched.append(t)
        finally:
            dest.close()
    report.counts = {t: before[t][0] for t in before if t.startswith(ROBIN_PREFIX)}
    return report


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m friday.ops.backupcheck <sqlite database file>")
        return 2
    if not Path(args[0]).is_file():
        print("no such file")
        return 2
    rep = restore_check(args[0])
    print("\n".join(rep.lines()))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
