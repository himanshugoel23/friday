import pytest
from sqlalchemy import Column, MetaData, String, Table, select, text

from friday.core.crypto import (
    DecryptionError,
    EncryptedJSON,
    EncryptedText,
    FieldCipher,
    LocalKeyProvider,
    set_field_cipher,
)
from friday.db import Database


def _provider(**kw) -> LocalKeyProvider:
    return LocalKeyProvider({"k1": b"a" * 32, **kw}, current="k1", index_key=b"i" * 32)


def test_roundtrip_aad_and_tamper():
    c = FieldCipher(_provider())
    token = c.encrypt("dad is diabetic", aad="people.notes")
    assert token.startswith("v1:k1:") and "diabetic" not in token
    assert c.decrypt(token, aad="people.notes") == "dad is diabetic"
    with pytest.raises(DecryptionError):
        c.decrypt(token, aad="places.address_text")  # swapped column
    with pytest.raises(DecryptionError):
        c.decrypt(token[:-4] + "AAAA", aad="people.notes")


def test_rotation_keeps_old_ciphertext_readable():
    old = FieldCipher(_provider())
    token = old.encrypt("secret", aad="t.c")
    new = FieldCipher(
        LocalKeyProvider({"k2": b"b" * 32, "k1": b"a" * 32}, current="k2", index_key=b"i" * 32)
    )
    assert new.decrypt(token, aad="t.c") == "secret"
    assert new.needs_rotation(token)
    assert new.encrypt("x", aad="t.c").startswith("v1:k2:")
    with pytest.raises(DecryptionError):
        FieldCipher(LocalKeyProvider({"k3": b"c" * 32}, index_key=b"i" * 32)).decrypt(
            token, aad="t.c"
        )


def test_blind_index_is_stable_and_keyed():
    a = FieldCipher(_provider()).blind_index("+919876543210", label="phone")
    assert a == FieldCipher(_provider()).blind_index("+919876543210", label="phone")
    other = LocalKeyProvider({"k1": b"a" * 32}, index_key=b"j" * 32)
    assert a != FieldCipher(other).blind_index("+919876543210", label="phone")


async def test_encrypted_column_types(settings):
    set_field_cipher(FieldCipher(_provider()))
    try:
        md = MetaData()
        t = Table(
            "enc_demo",
            md,
            Column("id", String, primary_key=True),
            Column("notes", EncryptedText("enc_demo.notes")),
            Column("spec", EncryptedJSON("enc_demo.spec")),
        )
        db = Database(settings.database_url)
        async with db.engine.begin() as conn:
            await conn.run_sync(md.create_all)
            await conn.execute(t.insert().values(id="1", notes="insulin daily", spec={"a": [1]}))
            raw = (await conn.execute(text("select notes, spec from enc_demo"))).one()
            assert "insulin" not in raw[0] and raw[1].startswith("v1:")
            row = (await conn.execute(select(t))).one()
            assert row.notes == "insulin daily" and row.spec == {"a": [1]}
        await db.dispose()
    finally:
        set_field_cipher(None)
