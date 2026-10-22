"""docs/CHATBOT_PILOT.md and .env.example stay in step with the code."""

from __future__ import annotations

from pathlib import Path

from friday.chatbot import copy, templates
from friday.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "CHATBOT_PILOT.md").read_text(encoding="utf-8")

SWITCHES = [
    "FRIDAY_CHATBOT_ONBOARDING", "FRIDAY_PILOT", "FRIDAY_CHATBOT_TESTERS", "FRIDAY_SUPPORT_INBOX",
    "FRIDAY_CHATBOT_OFFTOPIC", "FRIDAY_CHATBOT_FIRST_WINS", "FRIDAY_CHATBOT_DISCLOSURE_EVERY_STEP",
]  # fmt: skip


def test_the_pilot_doc_lists_every_pending_copy_id():
    missing = [i for i in copy.all_ids() if f"`{i}`" not in DOC]
    assert missing == []
    assert f"{len(copy.all_ids())} ids ({len(copy.LINES)} lines, {len(copy.BUTTONS)} buttons" in DOC


def test_the_doc_names_every_switch_and_the_env_example_lists_them():
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in SWITCHES:
        assert f"`{name}`" in DOC and name in env


def test_the_doc_says_what_is_pending_and_what_is_not_verified():
    for phrase in ("PENDING FOUNDER APPROVAL", "NOT verified", "Steps for the founder"):
        assert phrase in DOC
    for item in ("Real WhatsApp rendering", "Real template approval", "Real users' reactions"):
        assert item in DOC


def test_all_switches_default_to_off():
    s = Settings(_env_file=None)
    assert (s.chatbot_onboarding, s.pilot, s.chatbot_disclosure_every_step) == (False, False, False)
    assert s.support_inbox is None and s.chatbot_testers == []
    assert s.chatbot_offtopic == "redirect" and s.chatbot_first_wins == ["card", "day", "call"]


def test_the_switches_read_the_documented_env_names(monkeypatch):
    monkeypatch.setenv("FRIDAY_CHATBOT_ONBOARDING", "true")
    monkeypatch.setenv("FRIDAY_PILOT", "true")
    monkeypatch.setenv("FRIDAY_CHATBOT_TESTERS", "+919811100001,+919811100002")
    monkeypatch.setenv("FRIDAY_SUPPORT_INBOX", "+919811100009")
    s = Settings(_env_file=None)
    assert s.chatbot_onboarding and s.pilot
    assert s.chatbot_testers == ["+919811100001", "+919811100002"]
    assert s.support_inbox == "+919811100009"


def test_the_migration_is_the_head_the_doctor_expects():
    from friday.ops import doctor

    assert doctor.EXPECTED_HEAD_CHAIN == "0010_chatbot"
    assert "0010_chatbot" in DOC


def test_the_template_document_is_current():
    doc = (ROOT / "docs" / "WHATSAPP_TEMPLATES.md").read_text(encoding="utf-8")
    assert doc.strip() == templates.render().strip()


def test_schema_and_rls_cover_the_new_tables():
    root = ROOT / "deploy" / "supabase"
    schema, rls = (root / "schema.sql").read_text(), (root / "rls.sql").read_text()
    for table in ("chatbot_sessions", "chatbot_waitlist", "chatbot_inbox"):
        assert f"CREATE TABLE {table}" in schema
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;" in rls
