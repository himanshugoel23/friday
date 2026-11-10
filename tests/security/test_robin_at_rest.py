# ruff: noqa: E501, F811, F401
"""T03: encryption at rest for every Robin and RobinDevice table.

STATIC: every column of every table named ``robin*`` is either ``EncryptedJSON`` (AES-GCM) or on the short allow-list of
structural columns below (ids, states, times, and keyed/one-way hashes), each with a reason and a size cap that cannot hold
free text. A NEW plaintext column makes this test FAIL until a human decides: encrypt it or add it here with a reason.
DYNAMIC: a full family with a paired phone is planted with recognisable personal markers (names, a medicine, numbers, an
address-like phrase, spoken text); a raw ``SELECT *`` of every Robin table must contain none of them, and the phone number
must appear only as a keyed hash. Fakes only (SQLite)."""

from __future__ import annotations

import hashlib

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, text

import friday.db.tables  # noqa: F401 - registers the core tables
import friday.robin.dbmodel  # noqa: F401
import friday.robindevice.dbmodel  # noqa: F401
from friday.core.crypto import EncryptedJSON
from friday.db.base import Base
from friday.robin.alerts import RobinAlert
from friday.robin.medicine import Medicine
from friday.robin.models import ConsentSource, Tier
from tests.robin.conftest import (  # noqa: F401 - the Robin fixture, reused
    CHILD_PHONE,
    PARENT_PHONE,
    SECOND_PHONE,
    w,
)
from tests.robin.test_erase_all import B, Phone
from tests.robindevice.conftest import ev

# (table, column) -> reason. Plain columns hold ids, states, times and one-way hashes only; none can hold free text.
STRUCTURAL = {
    "id": "random row id", "created_at": "row time", "updated_at": "row time",
    "user_id": "id of the admin (child) user: the erasure key", "family_id": "row id", "member_id": "row id", "parent_id": "row id of the member",
    "status": "state word", "role": "role word", "kind": "record kind word", "item": "consent item name (a fixed list)",
    "source": "consent source word", "given_by": "consent basis word", "given_at": "time", "withdrawn_at": "time", "at": "time", "due_at": "time",
    "version": "row version counter", "expires_ms": "time",
    # human desk (0021_concierge): ids, fixed words and a position; the errand text, notes, proofs and audit counts are EncryptedJSON
    "priority": "fixed priority word (safety/health/convenience)", "lane": "fixed lane word", "claimed_by": "opaque staff id (no name)",
    "staff_id": "opaque staff id (no name)", "action": "fixed audit action word", "target_id": "id of the request or incident", "seq": "audit chain position",
}
HASHES = {
    ("robin_members", "phone_hash"): "keyed hash (NumberHasher) used for lookup",
    ("robin_device_states", "token_hash"): "SHA-256 of a 256-bit random device token (never the token)",
    ("robin_device_codes", "code_hash"): "keyed HMAC of the pairing code (short code, so keyed, not a bare hash)",
    ("robin_concierge_audit", "prev_hash"): "SHA-256 link of the audit chain", ("robin_concierge_audit", "entry_hash"): "SHA-256 of the audit entry",
}
KEYED = {("robin_records", "key"): "dedupe key: ids, dates and fixed words only; a medicine name is stored as a keyed hash (checked dynamically below)"}
PLAIN_TYPES = (String, Integer, BigInteger, Boolean, DateTime)
MAX_PLAIN_LEN = 64  # a plaintext column that can hold more than a key is a free-text column


def robin_tables():
    return [t for n, t in sorted(Base.metadata.tables.items()) if n.startswith("robin")]


def test_the_robin_tables_exist_and_are_all_seen():
    assert {t.name for t in robin_tables()} >= {"robin_families", "robin_members", "robin_consents", "robin_records", "robin_device_states", "robin_device_codes"}


def problems_for(tables) -> list[str]:
    problems = []
    for t in tables:
        for c in t.columns:
            if isinstance(c.type, EncryptedJSON):
                continue
            ok = c.name in STRUCTURAL or (t.name, c.name) in HASHES or (t.name, c.name) in KEYED
            if not ok:
                problems.append(f"{t.name}.{c.name} ({c.type}) is a PLAINTEXT column: encrypt it (EncryptedJSON) or allow-list it with a reason")
                continue
            base = getattr(c.type, "impl", c.type)  # TypeDecorators (UTCDateTime) are judged by what they wrap
            if not isinstance(base, PLAIN_TYPES) and not isinstance(c.type, PLAIN_TYPES):
                problems.append(f"{t.name}.{c.name}: allow-listed plain column has type {c.type}, expected a short scalar")
            elif isinstance(c.type, String) and (c.type.length or 10_000) > MAX_PLAIN_LEN:
                problems.append(f"{t.name}.{c.name}: plain String longer than {MAX_PLAIN_LEN} could hold free text")
    return problems


def test_every_robin_column_is_encrypted_or_a_known_structural_or_hash_column():
    assert not problems_for(robin_tables()), "\n".join(problems_for(robin_tables()))


def test_the_check_itself_catches_a_new_plaintext_column():
    """Negative control: run the SAME rule over a table with a new free-text column, a long string and an unknown name."""
    from sqlalchemy import Column, MetaData, Table, Text

    t = Table("robin_probe", MetaData(), Column("id", String(32)), Column("note", Text), Column("nickname", String(40)), Column("status", String(500)), Column("data", EncryptedJSON("robin_probe.data")))
    found = problems_for([t])
    assert len(found) == 3 and any("robin_probe.note" in f for f in found) and any("robin_probe.nickname" in f for f in found) and any("status: plain String longer" in f for f in found)


MARKERS = ["Metformin", "Ramesh Kumar", "Asha Verma", "Uncle Bhola", "12 Gandhi Road", "OTP bhej do", "9800000", "+91"]


async def test_raw_rows_hold_no_personal_marker_and_the_phone_only_as_a_keyed_hash(w, db):
    fam = await w.hub.fam.create_family(w.child_user, parent_label="Papa", child_name="Asha Verma", child_language="en")
    parent = await w.hub.fam.add_parent(fam, PARENT_PHONE, name="Ramesh Kumar")
    await w.hub.fam.set_second_contact(fam, SECOND_PHONE, "Uncle Bhola")
    for item in ("daily_checkin_calls", "medicine_reminders", "scam_check", "share_summary_with_child"):
        await w.hub.fam.give_consent(parent.id, item, ConsentSource.ADMIN_CHAT)
    for item in ("device_signals", "call_listening", "payment_alerts"):
        await w.hub.fam.admin_consent(fam, item)
    await w.hub.fam.update_settings(fam, safe_word_enabled=True)
    await w.hub.meds.add(fam, Medicine(name="Metformin", dose_text="500 mg", times=["09:00"], strips=2))
    await w.hub.meds.add(fam, Medicine(name="Metformin", dose_text="500 mg", times=["09:00"]), status="proposed")
    await w.hub.alerts.raise_alert(RobinAlert(parent.id, Tier.HIGH, "S5", "Rs 49,000 to a new payee at 12 Gandhi Road", money=True, amount_text="Rs 49,000"))
    phone = Phone(w, db)
    await phone.pair(parent.id)
    ms = int(w.clock.now().timestamp() * 1000)
    await phone.client.post(f"{B}/signals", headers=phone.h(), json={"events": [ev("camera_in_use_start", ms)]})
    await phone.service.feed_call_turn(parent.id, "c1", "caller", "OTP bhej do abhi police se bol raha hoon", 1.0)
    await phone.service.create_pairing_code(parent.id)

    seen_rows = 0
    async with db.engine.connect() as conn:
        for t in robin_tables():
            rows = (await conn.execute(text(f"SELECT * FROM {t.name}"))).all()  # noqa: S608 - fixed table names
            seen_rows += len(rows)
            blob = "\n".join(repr(tuple(r)) for r in rows)
            for needle in (*MARKERS, phone.token, PARENT_PHONE, CHILD_PHONE, SECOND_PHONE, PARENT_PHONE[3:], hashlib.sha256(PARENT_PHONE.encode()).hexdigest()):
                assert needle not in blob, (t.name, needle)
    assert seen_rows > 8
    async with db.engine.connect() as conn:
        hashes = [r[0] for r in (await conn.execute(text("SELECT phone_hash FROM robin_members"))).all()]
    assert hashes and all(len(h) == 64 and h not in (PARENT_PHONE, hashlib.sha256(PARENT_PHONE.encode()).hexdigest()) for h in hashes)
    await phone.client.aclose()
