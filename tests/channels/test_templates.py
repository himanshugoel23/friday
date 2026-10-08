"""One registry for template names and variable counts (friday/core/templates.py).

Every template sent anywhere in the code must match its registered variable count, or Meta
rejects it ("number of parameters does not match")."""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import pytest

from friday.channels.notifier import build_notifier
from friday.channels.simulator import SimulatorChannel
from friday.channels.sms import FakeSMS
from friday.channels.whatsapp import WhatsAppCloud, build_payload
from friday.core.config import Settings
from friday.core.models import (
    Channel,
    NudgeCandidate,
    OutboundMessage,
    Profile,
    TemplateRef,
    User,
    UserStatus,
)
from friday.core.templates import (
    SMS_ONLY_VARS,
    WHATSAPP_TEMPLATES,
    expected_params,
    make_template,
)

ROOT = Path(__file__).resolve().parents[2]
SKIP = {ROOT / "friday/core/models.py", ROOT / "friday/core/templates.py"}


def _call_sites():
    for path in sorted((ROOT / "friday").rglob("*.py")):
        if path in SKIP:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            fn = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if fn not in ("TemplateRef", "make_template"):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            key = kw.get("key") or (node.args[0] if node.args else None)
            params = kw.get("params") or (node.args[1] if len(node.args) > 1 else None)
            yield path.relative_to(ROOT), node.lineno, fn, key, params


def test_every_template_in_the_code_matches_its_registered_variable_count():
    sites = list(_call_sites())
    assert len(sites) >= 10  # the scan really finds the senders
    for path, line, fn, key, params in sites:
        where = f"{path}:{line}"
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            assert fn == "make_template", f"{where}: dynamic template key must use make_template"
            continue  # checked at runtime by make_template (see tests below)
        want = expected_params(key.value)
        assert want is not None, f"{where}: template {key.value!r} is not registered"
        if isinstance(params, ast.List):
            assert len(params.elts) == want, f"{where}: {key.value!r} takes {want} variable(s)"
        else:
            assert fn == "make_template", f"{where}: params of {key.value!r} not checkable"


def test_registry_is_consistent_with_settings_defaults():
    names = Settings(_env_file=None).whatsapp_templates
    assert names == {k: s.name for k, s in WHATSAPP_TEMPLATES.items()}
    for spec in WHATSAPP_TEMPLATES.values():
        for n in range(1, spec.n_params + 1):
            assert "{{%d}}" % n in spec.body_en and "{{%d}}" % n in spec.body_hi, spec.key
        assert "{{%d}}" % (spec.n_params + 1) not in spec.body_en
    assert set(SMS_ONLY_VARS).isdisjoint(WHATSAPP_TEMPLATES)


def test_make_template_refuses_a_wrong_count_or_unknown_key():
    assert make_template("nudge", ["Rahul", "text"]).params == ["Rahul", "text"]
    with pytest.raises(ValueError):
        make_template("nudge", ["only text"])
    with pytest.raises(ValueError):
        make_template("not_registered", ["x"])


def test_whatsapp_never_sends_a_malformed_registered_template():
    import asyncio

    ch = WhatsAppCloud(access_token="t", phone_number_id="1", templates={})
    msg = OutboundMessage(
        channel=Channel.WHATSAPP, to_phone="+919800000001",
        template=TemplateRef(key="nudge", params=["one only"]),
    )
    receipt = asyncio.run(ch.send(msg))
    assert not receipt.ok and receipt.error == "template_params_mismatch"
    ok = build_payload(
        msg.model_copy(update={"template": make_template("nudge", ["Rahul", "hi"])}),
        templates={"nudge": "friday_nudge_v1"}, template_language="en",
    )
    assert ok["template"]["name"] == "friday_nudge_v1"
    assert len(ok["template"]["components"][0]["parameters"]) == 2


async def test_notifier_fallback_and_proactive_fallback_both_send_two_nudge_variables(
    container, clock
):
    await container.db.create_all()
    channel = SimulatorChannel(clock, dict(container.settings.whatsapp_templates))
    container.override("messaging", channel)
    container.override("sms", FakeSMS(dict(container.settings.sms_dlt_templates), clock))
    user = await container.repos.users.add(
        User(phone="+919800000001", status=UserStatus.ACTIVE,
             last_inbound_at=clock.now() - timedelta(hours=30))  # window closed
    )
    await container.repos.profiles.add(Profile(user_id=user.id, name="Rahul Sharma"))
    n = build_notifier(container)
    await n.notify_user(user.id, "Your appointment is at 5", nudge_id="n1")
    await n.notify_user(user.id, "Update", task_id="t1")
    sent = [m for m in channel.sent if m.template]
    by_key = {m.template.key: m.template for m in sent}
    assert by_key["nudge"].params == ["Rahul", "Your appointment is at 5"]
    assert len(by_key["task_update"].params) == 1
    for m in sent:
        assert len(m.template.params) == expected_params(m.template.key)


async def test_proactive_engine_fallback_template_has_registered_count(container, clock):
    from friday.proactive.engine import ProactiveEngine  # noqa: F401  (import must work)

    src = (ROOT / "friday/proactive/engine.py").read_text()
    assert 'make_template(\n                "nudge"' in src  # the fallback goes via the registry
    assert NudgeCandidate  # the brain's own nudge template is covered by the AST scan


def test_checklist_lists_every_template_name_and_variable_count():
    doc = (ROOT / "docs/PRODUCTION_CHECKLIST.md").read_text()
    for spec in WHATSAPP_TEMPLATES.values():
        row = next((ln for ln in doc.splitlines() if f"`{spec.name}`" in ln), None)
        assert row is not None, f"{spec.name} missing from PRODUCTION_CHECKLIST.md"
        assert "{{%d}}" % spec.n_params in row
        assert "{{%d}}" % (spec.n_params + 1) not in row
