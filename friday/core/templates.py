"""ONE source of truth for pre-approved message templates (WhatsApp + DLT SMS).

Every sender builds its ``TemplateRef`` through :func:`make_template`, which checks the
variable count against this registry, so a path that would fail Meta's "number of
parameters does not match" check fails in tests (and is refused at send time) instead of
in production. ``Settings.whatsapp_templates`` defaults are derived from here, and the
copy-paste table for Meta in docs/PRODUCTION_CHECKLIST.md section 4 mirrors it
(tests/channels/test_templates.py keeps the three in step).

Owner: Engineering Manager (core, additive).
"""

from __future__ import annotations

from dataclasses import dataclass

from friday.core.models import TemplateRef


@dataclass(frozen=True)
class TemplateSpec:
    key: str  # logical key used in code (TemplateRef.key)
    name: str  # exact Meta template name
    variables: tuple[str, ...]  # meaning of {{1}}, {{2}}, ... in order
    body_en: str
    body_hi: str
    buttons: tuple[str, ...] = ()
    category: str = "UTILITY"

    @property
    def n_params(self) -> int:
        return len(self.variables)


_SPECS: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        "task_update",
        "friday_task_update_v1",
        ("update text (max 900 chars)",),
        "Update from Friday: {{1}}",
        "Friday की तरफ से अपडेट: {{1}}",
        ("See details",),
    ),
    TemplateSpec(
        "question",
        "friday_question_v1",
        ("the question text",),
        "Friday has a question for you: {{1}} Tap to answer.",
        "Friday का एक सवाल है: {{1}} जवाब देने के लिए टैप करें।",
        ("Answer now",),
    ),
    TemplateSpec(
        "nudge",
        "friday_nudge_v1",
        ("user's first name", "nudge text (max 900 chars)"),
        "Hi {{1}}, a quick heads-up from Friday: {{2}}",
        "नमस्ते {{1}}, Friday की तरफ से एक छोटी सूचना: {{2}}",
        ("Yes, do it", "Not now", "Stop these"),
    ),
    TemplateSpec(
        "reengage",
        "friday_reengage_v1",
        ("text",),
        "Friday here. {{1}} Reply any time to continue.",
        "Friday यहाँ है। {{1}} आगे बढ़ने के लिए कभी भी जवाब दें।",
    ),
    TemplateSpec(
        "friday_biz_request",
        "friday_biz_request",
        ("on whose behalf (the user's name)", "the ask"),
        "Hello, this is Friday, an AI assistant contacting you on behalf of a customer, "
        "{{1}}. {{2}}",
        "नमस्ते, मैं Friday हूँ, एक AI असिस्टेंट, और एक ग्राहक, {{1}}, की ओर से संपर्क कर रही हूँ। {{2}}",
        ("Reply", "Stop messages"),
    ),
    TemplateSpec(
        "beneficiary_optin",
        "friday_beneficiary_optin",
        ("their name", "who added them", "relation", "what was booked or asked"),
        "Namaste {{1}}, I'm Friday, an AI assistant. {{2}} ({{3}}) has booked {{4}} for you. "
        "May I send you confirmations and reminders for it?",
        "नमस्ते {{1}}, मैं Friday हूँ, एक AI असिस्टेंट। {{2}} ({{3}}) ने आपके लिए {{4}} बुक किया है। "
        "क्या मैं इसकी पुष्टि और रिमाइंडर आपको भेज सकती हूँ?",
        ("Yes", "No"),
    ),
    TemplateSpec(
        "business_booking_declined",
        "friday_business_declined_v1",
        ("business name",),
        "Hello {{1}}, the customer who contacted you through Friday (an AI assistant) will not "
        "be going ahead with the booking. Thank you for your time.",
        "नमस्ते {{1}}, Friday (एक AI असिस्टेंट) के ज़रिए आपसे संपर्क करने वाले ग्राहक अब यह बुकिंग नहीं "
        "करेंगे। आपके समय के लिए धन्यवाद।",
        ("OK", "Stop messages"),
    ),
    TemplateSpec(
        "business_booking_confirmed",
        "friday_business_touch",
        ("customer name", "confirmed terms", "\"Friday\""),
        "Booking confirmed via {{3}} for {{1}}: {{2}}. Friday is an AI assistant that books on "
        "behalf of customers.",
        "{{3}} के ज़रिए {{1}} की बुकिंग पक्की हुई: {{2}}। Friday एक AI असिस्टेंट है जो ग्राहकों की ओर से "
        "बुकिंग करती है।",
        ("OK", "Stop messages"),
    ),
    TemplateSpec(
        "business_enquiry_thanks",
        "friday_business_thanks_v1",
        ("customer name", "\"Friday\""),
        "Thank you for speaking with {{2}}, an AI assistant, on behalf of {{1}} today.",
        "आज {{1}} की ओर से {{2}}, एक AI असिस्टेंट, से बात करने के लिए धन्यवाद।",
        ("Stop messages",),
    ),
)

WHATSAPP_TEMPLATES: dict[str, TemplateSpec] = {s.key: s for s in _SPECS}

# DLT SMS-only keys (Settings.sms_dlt_templates) and their {#var#} count. Keys that are also
# WhatsApp templates (business_*) keep the same variable count on both channels.
SMS_ONLY_VARS: dict[str, int] = {"user_task_update": 1, "user_reminder": 1}


def default_whatsapp_names() -> dict[str, str]:
    """Default ``Settings.whatsapp_templates``: logical key -> Meta template name."""
    return {k: s.name for k, s in WHATSAPP_TEMPLATES.items()}


def expected_params(key: str) -> int | None:
    """Registered variable count for ``key`` (None if unknown)."""
    if key in WHATSAPP_TEMPLATES:
        return WHATSAPP_TEMPLATES[key].n_params
    return SMS_ONLY_VARS.get(key)


def params_mismatch(key: str, n: int) -> str | None:
    """Plain-words problem if ``n`` params is wrong for ``key`` (None == fine)."""
    want = expected_params(key)
    if want is None:
        return f"unregistered template {key!r} (add it to friday/core/templates.py)"
    if want != n:
        return f"template {key!r} takes {want} variable(s), got {n}"
    return None


def make_template(key: str, params: list[str], language: str = "en") -> TemplateRef:
    """Build a ``TemplateRef`` checked against the registry. Raises ``ValueError``."""
    if problem := params_mismatch(key, len(params)):
        raise ValueError(problem)
    return TemplateRef(key=key, params=list(params), language=language)


def first_name_param(name: str | None) -> str:
    """The {{1}} of the nudge template."""
    parts = (name or "").split()
    return parts[0] if parts else "there"
