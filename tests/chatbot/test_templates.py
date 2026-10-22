"""The WhatsApp template drafts and their checker (`friday chatbot templates check`)."""

from __future__ import annotations

import copy as _copy
from pathlib import Path

import pytest
import yaml

from friday.chatbot import templates as T
from friday.core.config import Settings
from friday.core.templates import WHATSAPP_TEMPLATES, params_mismatch

REQUIRED = {
    "chatbot_morning_brief", "chatbot_followup", "chatbot_bill_reminder",
    "chatbot_call_outcome", "chatbot_reengage", "chatbot_consent",
}  # fmt: skip


def raw() -> dict:
    return yaml.safe_load(T.YAML_PATH.read_text(encoding="utf-8"))


def broken(mutate) -> T.Report:  # noqa: ANN001
    data = _copy.deepcopy(raw())
    mutate(data["templates"][0])
    return T.check(tuple(T.parse(data)), roots=[], doc=None)


# ---------------------------------------------------------------- the file as shipped
def test_the_drafts_cover_every_message_sent_outside_the_window():
    assert {d.key for d in T.load()} == REQUIRED
    for d in T.load():
        assert d.category in ("UTILITY", "MARKETING")
        assert sorted(v.label for v in d.variants) == ["en", "hi", "hinglish"]


def test_the_checker_passes_on_the_shipped_file():
    report = T.check()
    assert report.ok, [str(p) for p in report.problems]
    assert report.drafts == 6 and report.registrations == 18


def test_every_body_has_matching_placeholders_examples_and_buttons():
    for d in T.load():
        assert d.n_params == len(d.examples) >= 1
        for v in d.variants:
            nums = sorted({int(n) for n in T.PLACEHOLDER.findall(v.body)})
            assert nums == list(range(1, d.n_params + 1)), (d.key, v.label)
            assert not T.PLACEHOLDER.match(v.body.strip())
            assert 1 <= len(v.buttons) <= 3
            assert all(1 <= len(b.title) <= 25 for b in v.buttons)


def test_every_body_states_assistant_never_payment_otp_pin_why_and_stop():
    from friday.chatbot.composer import has_statement

    for d in T.load():
        for v in d.variants:
            assert has_statement(v.body) == [], (d.key, v.label)
            assert d.why[v.label] in v.body
            assert "stop" in v.body.lower()


def test_names_are_meta_legal_unique_and_do_not_reuse_registered_names():
    names = [(v.name, v.meta_language) for d in T.load() for v in d.variants]
    assert len(names) == len(set(names))
    core = {s.name for s in WHATSAPP_TEMPLATES.values()}
    for name, _ in names:
        assert T.NAME_RE.match(name) and name not in core


def test_the_hinglish_and_hindi_texts_share_a_name_and_english_has_its_own():
    for d in T.load():
        assert d.variant("hinglish").name == d.variant("hi").name == d.name
        assert d.variant("hinglish").meta_language == "en" and d.variant("hi").meta_language == "hi"
        assert d.variant("en").name != d.name and d.variant("en").meta_language == "en"


def test_each_fallback_is_a_registered_generic_template():
    for d in T.load():
        assert d.fallback in WHATSAPP_TEMPLATES


# ---------------------------------------------------------------- Settings.whatsapp_templates
def test_with_the_chatbot_on_settings_carry_every_name_from_the_file():
    s = Settings(_env_file=None, chatbot_onboarding=True)
    for key, name in T.template_names().items():
        assert s.whatsapp_templates[key] == name
    assert s.whatsapp_templates["nudge"] == "friday_nudge_v1"  # the core names are untouched


def test_with_the_chatbot_off_the_registry_is_exactly_the_core_one():
    s = Settings(_env_file=None)
    assert s.whatsapp_templates == {k: v.name for k, v in WHATSAPP_TEMPLATES.items()}


def test_an_explicit_override_of_a_name_wins(monkeypatch):
    monkeypatch.setenv("FRIDAY_WHATSAPP_TEMPLATES", '{"chatbot_followup": "my_followup"}')
    s = Settings(_env_file=None, chatbot_onboarding=True)
    assert s.whatsapp_templates["chatbot_followup"] == "my_followup"
    assert T.check(settings=s, roots=[], doc=None).problems  # and the checker notices


# ---------------------------------------------------------------- the checker catches mistakes
def test_a_placeholder_that_does_not_match_the_params_is_caught():
    def m(t):  # noqa: ANN001, ANN202
        t["languages"]["en"]["body"] = t["languages"]["en"]["body"].replace("{{2}}", "{{3}}")

    assert any("placeholders" in p.message for p in broken(m).problems)


def test_a_missing_example_is_caught():
    assert any("examples" in p.message for p in broken(lambda t: t["examples"].pop()).problems)


def test_a_body_that_starts_or_ends_with_a_variable_is_caught():
    def m(t):  # noqa: ANN001, ANN202
        t["languages"]["en"]["body"] = "{{1}} " + t["languages"]["en"]["body"]

    assert any("starts or ends" in p.message for p in broken(m).problems)


def test_a_body_without_the_plain_statement_or_the_why_is_caught():
    def no_statement(t):  # noqa: ANN001, ANN202
        t["languages"]["en"]["body"] = (
            "Namaste {{1}}, brief: {{2}}. Ye isliye aaya ki aapne chuna tha. 'stop' likhiye."
        )

    problems = [p.message for p in broken(no_statement).problems]
    assert any("statement" in p for p in problems)
    assert any("why" in p for p in problems)


def test_too_many_or_too_long_buttons_are_caught():
    def many(t):  # noqa: ANN001, ANN202
        t["languages"]["en"]["buttons"] += [{"title": "x", "payload": "a", "action": "ok"}] * 3

    assert any("buttons" in p.message for p in broken(many).problems)

    def long(t):  # noqa: ANN001, ANN202
        t["languages"]["en"]["buttons"][0]["title"] = "x" * 26

    assert any("title" in p.message for p in broken(long).problems)

    def unknown(t):  # noqa: ANN001, ANN202
        t["languages"]["en"]["buttons"][0]["action"] = "explode"

    assert any("unknown action" in p.message for p in broken(unknown).problems)


def test_a_wrong_category_name_or_fallback_is_caught():
    assert any(
        "category" in p.message for p in broken(lambda t: t.update(category="PROMO")).problems
    )
    assert any(
        "lowercase" in p.message for p in broken(lambda t: t.update(name="Friday-Brief")).problems
    )
    assert any(
        "fallback" in p.message for p in broken(lambda t: t.update(fallback="nope")).problems
    )
    assert any(
        "registered template" in p.message
        for p in broken(lambda t: t.update(name="friday_nudge_v1")).problems
    )


def test_a_name_missing_from_settings_is_caught():
    s = Settings(_env_file=None, chatbot_onboarding=True)
    s.whatsapp_templates.pop("chatbot_consent")
    assert any(
        "whatsapp_templates" in p.message for p in T.check(settings=s, roots=[], doc=None).problems
    )


# ---------------------------------------------------------------- the senders in the code
def write(tmp_path: Path, src: str) -> Path:
    f = tmp_path / "sender.py"
    f.write_text(src)
    return f


def test_a_sender_with_the_right_parameter_count_passes(tmp_path):
    f = write(tmp_path, "chatbot_template('chatbot_followup', [name, text], lang)\n")
    report = T.check(roots=[f], doc=None)
    assert report.ok and report.call_sites == 1


def test_a_sender_with_the_wrong_count_an_unknown_key_or_a_dynamic_key_is_caught(tmp_path):
    f = write(tmp_path, "chatbot_template('chatbot_followup', [name])\n")
    assert any("takes 2" in p.message for p in T.check(roots=[f], doc=None).problems)
    f = write(tmp_path, "chatbot_template('chatbot_nothing', [name])\n")
    assert any("unknown" in p.message for p in T.check(roots=[f], doc=None).problems)
    f = write(tmp_path, "chatbot_template(key, [name])\n")
    assert any("literal" in p.message for p in T.check(roots=[f], doc=None).problems)
    f = write(tmp_path, "chatbot_template('chatbot_followup', params)\n")
    assert any("literal list" in p.message for p in T.check(roots=[f], doc=None).problems)


def test_the_helper_builds_checked_references():
    ref = T.chatbot_template(
        "chatbot_followup", ["Rahul", "Kal ka interview kaisa raha?"], "hinglish"
    )
    assert (ref.key, ref.language, len(ref.params)) == ("chatbot_followup", "en", 2)
    assert T.chatbot_template("chatbot_followup", ["a", "b"], "hi").language == "hi"
    eng = T.chatbot_template("chatbot_followup", ["a", "b"], "en")
    assert (eng.key, eng.language) == ("chatbot_followup_en", "en")
    with pytest.raises(ValueError):
        T.chatbot_template("chatbot_followup", ["only one"])
    with pytest.raises(ValueError):
        T.chatbot_template("unknown", ["x"])


def test_core_templates_registered_in_friday_core_still_check_out():
    # the existing registry is the source of truth for the generic fallbacks
    for d in T.load():
        assert params_mismatch(d.fallback, WHATSAPP_TEMPLATES[d.fallback].n_params) is None


# ---------------------------------------------------------------- the document and the buttons
def test_the_document_is_rendered_from_the_file():
    doc = T.DOC_PATH.read_text(encoding="utf-8")
    assert (
        doc == T.render() + ("" if T.render().endswith("\n") else "\n")
        or doc.strip() == T.render().strip()
    )
    for d in T.load():
        for v in d.variants:
            assert f"`{v.name}`" in doc and v.body.split("\n")[0] in doc
    assert "PENDING_FOUNDER_APPROVAL" in doc


def test_a_tap_on_a_template_button_is_understood_by_payload_or_title():
    assert T.button_action("cb:tpl:stop") == "stop"
    assert T.button_action("cb:consent:yes") == "consent_yes"
    assert T.button_action(None, "Brief band karo") == "stop"
    assert T.button_action(None, "Kuch galat hai") == "human"
    assert T.button_action(None, "Theek hai") == "ok"
    assert T.button_action(None, "nothing like that") is None
    assert T.button_action(None, None) is None


async def test_a_tap_on_a_template_stop_button_pauses_messages(chat):
    from friday.core.models import ConsentKind, MessageKind

    await chat.onboard()
    msg = chat.channel.make_inbound(chat.phone, "x").model_copy(
        update={"kind": MessageKind.BUTTON_REPLY, "button_id": None, "text": "Brief band karo"}
    )
    out = await chat.send(msg)
    assert "khud se message nahi" in (out[0].text or "")
    user = await chat.user()
    assert not (await chat.c.repos.consents.latest(user.id, ConsentKind.PROACTIVE)).granted


async def test_the_consent_again_buttons_record_the_new_consent(chat):
    from friday.core.models import ConsentKind

    await chat.onboard()
    user = await chat.user()
    chat.clock.advance(days=40)
    out = await chat.tap_id("cb:consent:yes")
    assert "haan note kar li" in (out[0].text or "")
    consents = await chat.c.repos.consents.list_for_user(user.id)
    assert [c.granted for c in consents if c.kind == ConsentKind.TERMS_PRIVACY] == [True, True]
    chat.clock.advance(minutes=5)
    out = await chat.tap_id("cb:consent:no")
    assert "khud se message nahi" in (out[0].text or "")
    latest = await chat.c.repos.consents.latest(user.id, ConsentKind.TERMS_PRIVACY)
    assert latest is not None and latest.granted is False
    assert not (await chat.c.repos.consents.latest(user.id, ConsentKind.PROACTIVE)).granted


def test_the_templates_command_prints_ok_and_renders(capsys):
    from friday.cli import main

    assert main(["chatbot", "templates", "check"]) == 0
    assert "6 template drafts, 18 registrations" in capsys.readouterr().out
    assert main(["chatbot", "templates", "render"]) == 0
    assert capsys.readouterr().out.startswith("# WhatsApp templates")
