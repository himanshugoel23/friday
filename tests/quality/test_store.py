"""TranscriptStore: consent gating, redaction, encryption at rest, retention, erasure, labels."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from friday.quality.labels import LABELS, normalise_rating, parse_rating_reply
from friday.quality.redact import redact_text
from tests.quality.conftest import make_call, make_user


# ------------------------------------------------------------------ consent gating
async def test_consented_caller_is_stored(app, store):
    await make_user(app)
    summary, result = make_call()
    res = await store.capture(summary, result)
    assert res.stored
    call = await store.get("call-1")
    assert call is not None and len(call.transcript) == 3
    assert call.meta["outcome"] == "success"


async def test_unknown_caller_stores_nothing(app, store):
    summary, result = make_call(phone="+919800000009")
    res = await store.capture(summary, result)
    assert not res.stored and await store.count() == 0


async def test_user_without_consent_stores_nothing(app, store):
    await make_user(app, consent=False)
    res = await store.capture(*make_call())
    assert not res.stored and "consent" in res.reason and await store.count() == 0


async def test_withdrawn_consent_stores_nothing(app, store):
    from friday.core.models import Consent, ConsentKind

    user = await make_user(app)
    await app.c.repos.consents.add(
        Consent(user_id=user.id, kind=ConsentKind.TERMS_PRIVACY, granted=False,
                recorded_at=app.c.clock.now() + timedelta(seconds=5))
    )
    assert not (await store.capture(*make_call())).stored


async def test_deleted_user_stores_nothing(app, store):
    from friday.core.models import UserStatus

    await make_user(app, status=UserStatus.DELETED)
    assert not (await store.capture(*make_call())).stored


async def test_explicit_no_consent_flag_wins(app, store):
    await make_user(app)
    assert not (await store.capture(*make_call(consented="false"))).stored


async def test_rejected_call_and_empty_transcript_store_nothing(app, store):
    await make_user(app)
    summary, result = make_call()
    summary.route = "reject"
    assert not (await store.capture(summary, result)).stored
    assert not (await store.capture(summary, None)).stored
    summary2, result2 = make_call(turns=[], call_id="empty")
    assert not (await store.capture(summary2, result2)).stored
    assert await store.count() == 0


async def test_same_call_is_stored_once(app, store):
    await make_user(app)
    assert (await store.capture(*make_call())).stored
    assert not (await store.capture(*make_call())).stored
    assert await store.count() == 1


# ------------------------------------------------------------------ redaction
def test_redact_secrets_digits_words_phones_and_names():
    assert "4826" not in redact_text("mera pin 4 8 2 6 hai")
    assert "four" not in redact_text("my pin is four eight two six").lower()
    out = redact_text("call me on +91 98123 45678 or 9812345678")
    assert out == "call me on +91******5678 or +91******5678"  # masked like mask_phone
    assert redact_text("my card is 4111 1111 1111 1111") == "my card is [number]"
    assert redact_text("Asha ji, haan", names=["Asha"]) == "[name] ji, haan"
    assert redact_text("Ashapura", names=["Asha"]) == "Ashapura"  # whole words only
    assert redact_text("haircut kal shaam") == "haircut kal shaam"  # untouched


async def test_stored_transcript_is_redacted_and_names_scrubbed(app, store):
    await make_user(app, name="Rahul Verma")
    turns = [
        ("friday", "Hello, this is Friday, an AI assistant. What is your name?"),
        ("callee", "mera naam Priya hai"),
        ("callee", "Rahul Verma here, my pin is 4 8 2 6, call 9812345678"),
        ("friday", "Please do not say a PIN."),
    ]
    await store.capture(*make_call(turns=turns))
    call = await store.get("call-1")
    blob = " ".join(t["text"] for t in call.transcript)
    for secret in ("4 8 2 6", "4826", "9812345678", "Rahul", "Verma", "Priya"):
        assert secret not in blob, secret
    assert "[name]" in blob and "[redacted]" in blob


# ------------------------------------------------------------------ encryption at rest
async def test_transcript_and_note_are_encrypted_in_the_database(app, store):
    await make_user(app)
    await store.capture(*make_call())
    await store.add_labels("call-1", ["good"], note="secret-note-about-caller")
    async with app.c.db.session() as s:
        row = (await s.execute(text("SELECT transcript, note FROM quality_calls"))).one()
    for raw in row:
        assert raw.startswith("v1:")  # AES-GCM envelope from friday.core.crypto
    assert "haircut" not in row[0] and "secret-note" not in row[1]
    call = await store.get("call-1")  # round trip decrypts
    assert call.transcript[1]["text"] == "haircut book karo kal"
    assert call.note == "secret-note-about-caller"


async def test_ciphertext_cannot_be_moved_to_another_column(app, store):
    from friday.core.crypto import DecryptionError, get_field_cipher

    await make_user(app)
    await store.capture(*make_call())
    async with app.c.db.session() as s:
        raw = (await s.execute(text("SELECT transcript FROM quality_calls"))).scalar_one()
    with pytest.raises(DecryptionError):
        get_field_cipher().decrypt(raw, aad="quality_calls.note")


# ------------------------------------------------------------------ retention
async def test_purge_removes_only_expired_rows(app, store):
    await make_user(app)
    await store.capture(*make_call(call_id="old"))
    app.clock.advance(days=20)
    await store.capture(*make_call(call_id="newer"))
    assert await store.purge_expired() == 0  # day 20: both inside 30 days
    app.clock.advance(days=11)  # day 31: "old" expired, "newer" is 11 days old
    assert await store.purge_expired() == 1
    assert await store.get("old") is None and await store.get("newer") is not None


async def test_retention_days_setting(app):
    from friday.quality.store import TranscriptStore

    await make_user(app)
    short = TranscriptStore(app.c.db, app.c.repos, clock=app.c.clock, retention_days=2)
    await short.capture(*make_call())
    app.clock.advance(days=3)
    assert await short.purge_expired() == 1
    assert app.c.settings.quality_transcript_retention_days == 30  # the default


async def test_daily_retention_job_also_purges_transcripts(app, store):
    from datetime import datetime

    from friday.core.clock import IST
    from friday.proactive.retention import RetentionJob

    await make_user(app)
    await store.capture(*make_call())
    app.clock.advance(days=40)
    out = await RetentionJob(app.c).run_daily(datetime(2026, 3, 1, 4, 0, tzinfo=IST).astimezone())
    assert out is not None and out["quality_transcripts"] == 1


# ------------------------------------------------------------------ erasure
async def test_delete_everything_removes_stored_transcripts(app, store):
    user = await make_user(app)
    other = await make_user(app, phone="+919811100002", name="Meera")
    await store.capture(*make_call(call_id="a"))
    await store.capture(*make_call(phone="+919811100002", call_id="b"))
    await app.c.repos.purger.purge_user(user.id)  # what InboundPipeline.delete_everything calls
    assert await store.get("a") is None
    assert await store.get("b") is not None  # other users untouched
    assert await store.erase_user(other.id) == 1 and await store.count() == 0


# ------------------------------------------------------------------ labels and ratings
async def test_labels_note_and_removal(app, store):
    await make_user(app)
    await store.capture(*make_call())
    assert await store.add_labels("call-1", ["robotic", "too_long"], note="reads like a script")
    assert await store.add_labels("call-1", ["robotic", "slow"])
    call = await store.get("call-1")
    assert call.labels == ["robotic", "too_long", "slow"] and call.note == "reads like a script"
    await store.add_labels("call-1", ["robotic"], remove=True)
    assert (await store.get("call-1")).labels == ["too_long", "slow"]
    assert (await store.recent(labelled=True))[0].call_id == "call-1"
    assert await store.recent(labelled=False) == []
    assert not await store.add_labels("missing", ["good"])


async def test_unknown_label_is_refused(app, store):
    await make_user(app)
    await store.capture(*make_call())
    with pytest.raises(ValueError):
        await store.add_labels("call-1", ["awesome"])
    assert (await store.get("call-1")).labels == []


def test_label_set_is_the_agreed_one():
    assert set(LABELS) == {"robotic", "interrupted_me", "cut_me_off", "wrong_answer", "too_long",
                           "good", "helpline_feel", "slow", "language_mismatch"}


async def test_record_rating(app, store):
    await make_user(app)
    await store.capture(*make_call())
    assert await store.record_rating("call-1", 4)
    assert (await store.get("call-1")).rating == 4
    assert await store.record_rating("call-1", "down")
    assert (await store.get("call-1")).rating == 1
    assert not await store.record_rating("not-stored", 5)  # no row, no rating kept
    for bad in (0, 6, "meh", True):
        with pytest.raises(ValueError):
            await store.record_rating("call-1", bad)


def test_rating_reply_parsing():
    assert normalise_rating(3) == 3 and normalise_rating("up") == 5
    assert parse_rating_reply("5") == 5 and parse_rating_reply("👍") == 5
    assert parse_rating_reply("👎") == 1 and parse_rating_reply("2 stars") == 2
    assert parse_rating_reply("book a table for 4 people tomorrow") is None
    assert parse_rating_reply("") is None
