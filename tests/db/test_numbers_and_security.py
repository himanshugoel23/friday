# ruff: noqa: ASYNC240
"""NP-1 repos, key rotation, KMS provider, object store, retention, consent receipts."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from friday.core.crypto import FieldCipher, LocalKeyProvider, set_field_cipher
from friday.core.models import (
    CallOutcome,
    CallResult,
    Consent,
    ConsentKind,
    DialStatus,
    FridayNumber,
    NumberHealth,
    NumberOutcome,
    NumberStatus,
    Person,
    PersonConsent,
    Place,
    Speaker,
    Task,
    TaskSpec,
    TaskType,
    Transcript,
    User,
    UserStatus,
)
from friday.db.repositories import Repositories, make_repositories

BIZ = "+919845000001"


@pytest.fixture
def repos(db, clock) -> Repositories:
    return make_repositories(db, clock, "test-secret")


async def _raw(db, table: str) -> str:
    async with db.engine.connect() as conn:
        rows = (await conn.execute(text(f"SELECT * FROM {table}"))).all()  # noqa: S608
    return repr(rows)


async def test_number_pool_round_trip(repos, clock, db):
    n = FridayNumber(
        phone="+918000000001",
        provider="simulator",
        city="Bengaluru",
        circle="KA",
        health=NumberHealth(calls=10, answered=6, score=0.8),
    )
    await repos.numbers.upsert(n)
    got = await repos.numbers.get(n.phone)
    assert got.health.answer_rate == 0.6 and got.circle == "KA"
    n.status = NumberStatus.COOLING
    await repos.numbers.upsert(n)
    assert [x.phone for x in await repos.numbers.list(statuses=[NumberStatus.COOLING])] == [n.phone]

    a = await repos.numbers.assign(BIZ, n.phone)
    assert a.number_phone == n.phone and a.previous_number is None
    a2 = await repos.numbers.assign(BIZ, "+918000000002")
    assert a2.previous_number == n.phone
    assert (await repos.numbers.get_assignment(BIZ)).number_phone == "+918000000002"
    assert BIZ not in await _raw(db, "number_assignments")

    for o in (NumberOutcome.ANSWERED, NumberOutcome.SHORT_CALL, NumberOutcome.NO_ANSWER):
        await repos.numbers.add_outcome(n.phone, o, business_phone=BIZ, duration_s=5)
        clock.advance(60)
    recent = await repos.numbers.recent_outcomes(n.phone)
    assert [r.outcome for r in recent][0] == NumberOutcome.NO_ANSWER
    since = clock.now() - timedelta(hours=1)
    assert await repos.numbers.count_outcomes(n.phone, since=since) == 3
    assert (
        await repos.numbers.count_outcomes(n.phone, since=since, outcomes=[NumberOutcome.ANSWERED])
        == 1
    )
    assert BIZ not in await _raw(db, "number_outcomes")

    assert not await repos.numbers.is_dnc(BIZ)
    await repos.numbers.add_dnc(BIZ, reason="dnc_request", number_phone=n.phone)
    await repos.numbers.add_dnc(BIZ, reason="again")  # idempotent
    assert await repos.numbers.is_dnc(BIZ)
    assert len(await repos.numbers.list_dnc()) == 1
    assert BIZ not in await _raw(db, "dnc_registry")


async def test_phones_encrypted_and_looked_up_by_blind_index(repos, db):
    u = await repos.users.add(User(phone="+919800000001"))
    assert "+919800000001" not in await _raw(db, "users")
    assert (await repos.users.get_by_phone("+919800000001")).id == u.id
    await repos.people.upsert(Person(owner_user_id=u.id, name="Ramesh", phone="+919811111111"))
    assert "Ramesh" not in await _raw(db, "people")
    assert len(await repos.people.find_by_phone("+919811111111")) == 1


async def test_field_key_rotation_reencrypts(repos, db, clock):
    from friday.db.repositories._base import SecretBox
    from friday.db.rotation import reencrypt_columns, reencrypt_identifiers

    old_key, new_key, idx = b"o" * 32, b"n" * 32, b"i" * 32
    set_field_cipher(FieldCipher(LocalKeyProvider({"k1": old_key}, index_key=idx)))
    try:
        u = await repos.users.add(User(phone="+919800000005"))
        await repos.places.upsert(
            Place(owner_user_id=u.id, label="Home", address_text="12 MG Road")
        )
        assert ":k1:" in await _raw(db, "places")
        set_field_cipher(
            FieldCipher(
                LocalKeyProvider({"k2": new_key, "k1": old_key}, current="k2", index_key=idx)
            )
        )
        counts = await reencrypt_columns(db)
        assert counts.get("places.address_text") == 1
        assert ":k1:" not in await _raw(db, "places")
        assert (await repos.places.list_for_owner(u.id))[0].address_text == "12 MG Road"
        assert await reencrypt_columns(db) == {}
    finally:
        set_field_cipher(None)

    from friday.core.models import AccountIdentifier

    ident = await repos.identifiers.upsert(
        AccountIdentifier(user_id=u.id, label="acct", value="99887766")
    )
    rotated = make_repositories(db, clock, "new-secret", previous_keys=["test-secret"])
    assert (await rotated.identifiers.get(ident.id)).value == "99887766"
    assert await reencrypt_identifiers(db, SecretBox("new-secret", previous=["test-secret"])) == 1
    fresh = make_repositories(db, clock, "new-secret")
    assert (await fresh.identifiers.get(ident.id)).value == "99887766"


def test_kms_provider_with_fake_unwrap(monkeypatch, settings):
    import base64
    import json

    from friday.core.container import Container
    from friday.core.interfaces import ProviderError
    from friday.db.kms import build_kms_key_provider

    dek = b"d" * 32
    monkeypatch.setenv(
        "FRIDAY_KMS_WRAPPED_KEYS", json.dumps({"kms1": base64.b64encode(b"wrapped").decode()})
    )
    s = settings.model_copy(update={"field_key_id": "arn:aws:kms:ap-south-1:1:key/x"})
    calls = []

    def unwrap(blob: bytes) -> bytes:
        calls.append(blob)
        return dek

    p = build_kms_key_provider(Container(s), unwrap=unwrap)
    cipher = FieldCipher(p)
    tok = cipher.encrypt("secret", aad="t.c")
    assert tok.startswith("v1:kms1:") and cipher.decrypt(tok, aad="t.c") == "secret"
    cipher.decrypt(tok, aad="t.c")
    assert calls == [b"wrapped"]  # unwrapped once, cached
    with pytest.raises(ProviderError):
        build_kms_key_provider(Container(settings), unwrap=unwrap)


async def test_object_store_local_and_s3(tmp_path):  # noqa: ASYNC240
    from friday.db.objectstore import LocalObjectStore, S3ObjectStore, delete_recording

    store = LocalObjectStore(tmp_path / "rec")
    url = await store.put("calls/abc.wav", b"RIFF", content_type="audio/wav")
    assert Path(url[7:]).exists()
    outside = tmp_path / "other.wav"
    outside.write_bytes(b"x")
    assert not await store.delete(outside.as_uri())  # not under the store root
    assert outside.exists()
    assert await delete_recording(url, store=store)
    assert not Path(url[7:]).exists()
    # path traversal is flattened into the store root
    esc = await store.put("../../etc/passwd.txt", b"x", content_type="text/plain")
    assert Path(esc[7:]).resolve().is_relative_to((tmp_path / "rec").resolve())

    class FakeS3:
        def __init__(self):
            self.objects = {}

        def put_object(self, **kw):
            self.objects[kw["Key"]] = kw["Body"]

        def delete_object(self, **kw):
            self.objects.pop(kw["Key"], None)

        def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
            return f"https://s3.example/{Params['Key']}?X-Amz-Expires={ExpiresIn}"

    s3 = S3ObjectStore.from_url("s3://friday-rec/recordings", client=FakeS3())
    u = await s3.put("c1.mp3", b"ID3", content_type="audio/mpeg")
    assert u == "s3://friday-rec/recordings/c1.mp3"
    signed = await s3.signed_url(u, expires_s=3600)
    assert "X-Amz-Expires=3600" in signed
    assert s3.lifecycle_rule(30)["Rules"][0]["Expiration"]["Days"] == 30
    assert await delete_recording(u, store=s3)
    assert s3.client.objects == {}

    class Tel:
        deleted = []

        async def delete_recording(self, url):
            self.deleted.append(url)

    assert await delete_recording("https://api.twilio.com/rec/RE1", store=s3, telephony=Tel())
    assert not await delete_recording("https://api.twilio.com/rec/RE2", store=s3)


async def test_object_store_required_in_live(settings):
    from friday.core.interfaces import ProviderError
    from friday.db.objectstore import build_object_store

    with pytest.raises(ProviderError):
        build_object_store(settings.model_copy(update={"mode": "live"}))


async def test_retention_job(repos, clock, db, tmp_path):  # noqa: ASYNC240
    from friday.db.objectstore import LocalObjectStore
    from friday.db.retention import add_pending_deletion, pending_deletions, run_retention

    store = LocalObjectStore(tmp_path)
    u = await repos.users.add(
        User(phone="+919800000011", status=UserStatus.ACTIVE, created_at=clock.now())
    )
    await repos.consents.add(Consent(user_id=u.id, kind=ConsentKind.TERMS_PRIVACY, granted=True))
    task = await repos.tasks.add(
        Task(
            requester_user_id=u.id,
            type=TaskType.BOOKING,
            spec=TaskSpec(type=TaskType.BOOKING, goal="x"),
        )
    )
    rec = await store.put("old.wav", b"RIFF", content_type="audio/wav")
    tr = Transcript()
    tr.add(Speaker.CALLEE, "old words")
    await repos.tasks.save_call(
        CallResult(
            task_id=task.id,
            provider="sim",
            to_phone=BIZ,
            dial_status=DialStatus.ANSWERED,
            outcome=CallOutcome.SUCCESS,
            transcript=tr,
            recording_url=rec,
            started_at=clock.now(),
        )
    )
    lurker = await repos.users.add(User(phone="+919800000012", created_at=clock.now()))
    await repos.places.upsert(
        Place(owner_user_id=u.id, label="pin", ephemeral=True, created_at=clock.now())
    )
    await add_pending_deletion(repos, "https://provider.example/rec/1")

    clock.advance(timedelta(days=31).total_seconds())
    out = await run_retention(repos, clock.now(), store=store)
    assert out["recordings"] == 1 and out["call_turns"] == 1
    assert not Path(rec[7:]).exists()
    call = (await repos.tasks.list_calls(task.id))[0]
    assert call.recording_url is None and call.transcript.turns == []
    assert out["preconsent_users"] == 1
    assert (await repos.users.get(lurker.id)).status == UserStatus.DELETED
    assert (await repos.users.get(u.id)).status == UserStatus.ACTIVE
    assert out["ephemeral_places"] == 1
    assert len(await pending_deletions(repos)) == 1  # provider can't delete -> retried later


async def test_consent_receipt_kept_without_pii(repos, db):
    """SECURITY-33."""
    u = await repos.users.add(User(phone="+919800000021"))
    dad = await repos.people.upsert(
        Person(
            owner_user_id=u.id,
            name="Ramesh",
            phone="+919811111122",
            contact_consent=PersonConsent.OPTED_IN,
        )
    )
    await repos.consents.add(
        Consent(
            user_id=u.id,
            kind=ConsentKind.TERMS_PRIVACY,
            granted=True,
            evidence_text="I agree - Rahul",
        )
    )
    await repos.consents.add(
        Consent(
            user_id=u.id,
            person_id=dad.id,
            kind=ConsentKind.BENEFICIARY_CONTACT,
            granted=True,
            evidence_text="haan",
        )
    )
    await repos.purger.purge_user(u.id)
    receipts = await repos.consents.list_for_user(u.id)
    assert len(receipts) == 2
    assert all(r.evidence_text is None and r.person_id is None for r in receipts)
    raw = await _raw(db, "consents")
    assert "Rahul" not in raw and "haan" not in raw and "+9198" not in raw


async def test_repos_retention_run_facade(repos, clock):
    out = await repos.retention.run(clock.now() + timedelta(days=40), 30, 7)
    assert set(out) >= {"recordings", "call_turns", "preconsent_users", "pending_deletions"}
