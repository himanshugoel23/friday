"""Persistence: SQLAlchemy 2 async (SQLite dev/tests, Postgres-ready).

  base.py      - Declarative Base, UTCDateTime, JSON type          (EM scaffold)
  tables.py    - ORM tables mirroring friday.core.models            (EM scaffold)
  session.py   - Database (engine + session factory)                (EM scaffold)
  repositories/ - row <-> domain model conversion, queries          (Backend Engineer)

Owner after scaffold hand-off: Backend Engineer. Other modules never import ORM
rows; they receive domain models from repositories/services.
"""

from friday.db.session import Database

__all__ = ["Database"]
