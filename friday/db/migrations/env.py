"""Alembic environment (S-5). Driven programmatically by ``friday.db.migrate``; the
sync/async split is handled by running migrations through ``run_sync`` on the engine
Friday already uses (asyncpg on Postgres, aiosqlite in dev)."""

from __future__ import annotations

import asyncio

from alembic import context

import friday.db.tables  # noqa: F401  (register tables)
from friday.db.base import Base

target_metadata = Base.metadata


def _render_item(type_, obj, autogen_context):  # noqa: ANN001, ANN202
    """Encrypted columns are plain TEXT in the schema (encryption is app-side)."""
    from friday.core.crypto import EncryptedText

    if type_ == "type" and isinstance(obj, EncryptedText):
        return "sa.Text()"
    return False


def _configure(connection) -> None:  # noqa: ANN001
    context.configure(
        render_item=_render_item,
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )


def _run(connection) -> None:  # noqa: ANN001
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async(engine) -> None:  # noqa: ANN001
    async with engine.connect() as conn:
        await conn.run_sync(_run)
        await conn.commit()


def run() -> None:
    engine = context.config.attributes.get("engine")
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
    elif engine is not None:
        asyncio.run(_run_async(engine))
    else:
        raise RuntimeError("friday.db.migrate provides the engine")


run()
