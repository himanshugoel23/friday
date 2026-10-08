"""Key rotation maintenance (SECURITY-13).

* ``reencrypt_columns``     - every ``EncryptedText``/``EncryptedJSON`` column: rows whose
  ciphertext was written under an old key id (``FieldCipher.needs_rotation``), or legacy
  plaintext, are re-encrypted under the current key id.
* ``reencrypt_identifiers`` - ``account_identifiers.value_encrypted`` (``SecretBox``,
  MultiFernet) re-encrypted under the current identifier key.

Both run in batches and are idempotent; run them after adding a new current key.
"""

from __future__ import annotations

from sqlalchemy import Text, select, type_coerce, update

from friday.core.crypto import EncryptedText, FieldCipher, get_field_cipher
from friday.db.base import Base
from friday.db.repositories._base import SecretBox
from friday.db.session import Database


def encrypted_columns() -> list[tuple[str, str, EncryptedText]]:
    import friday.db.tables  # noqa: F401  (register tables)

    out = []
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if isinstance(col.type, EncryptedText):
                out.append((table.name, col.name, col.type))
    return out


async def reencrypt_columns(
    db: Database, cipher: FieldCipher | None = None, *, batch: int = 500
) -> dict[str, int]:
    """Returns ``{"table.column": rows_rewritten}``."""
    cipher = cipher or get_field_cipher()
    counts: dict[str, int] = {}
    for table_name, col_name, col_type in encrypted_columns():
        table = Base.metadata.tables[table_name]
        pk = list(table.primary_key.columns)
        col = table.c[col_name]
        raw = type_coerce(col, Text)
        done = 0
        async with db.session() as s:
            rows = (await s.execute(select(*pk, raw.label("raw")).where(col.is_not(None)))).all()
            for row in rows:
                value = row.raw
                if cipher.is_ciphertext(value):
                    if not cipher.needs_rotation(value):
                        continue
                    plain = cipher.decrypt(value, aad=col_type.aad)
                else:
                    plain = value  # legacy plaintext row -> encrypt now
                token = cipher.encrypt(plain, aad=col_type.aad)
                cond = [c == getattr(row, c.name) for c in pk]
                await s.execute(update(table).where(*cond).values({col_name: type_coerce(token, Text)}))
                done += 1
                if done % batch == 0:
                    await s.flush()
        if done:
            counts[f"{table_name}.{col_name}"] = done
    return counts


async def reencrypt_identifiers(db: Database, box: SecretBox) -> int:
    from friday.db.tables import AccountIdentifierRow

    n = 0
    async with db.session() as s:
        for row in (await s.execute(select(AccountIdentifierRow))).scalars():
            if box.needs_rotation(row.value_encrypted):
                row.value_encrypted = box.rotate(row.value_encrypted)
                n += 1
    return n
