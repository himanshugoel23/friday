# ruff: noqa: E501
"""The guardrails engine: ``check`` (before the model) and ``check_reply`` (on the way out).

Code decides, by category, from the policy table; no language model is involved. See
docs/GUARDRAILS_MODULE.md for the order, the switches and the audit rules.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import UTC, datetime

from friday.guardrails import copy, legacy, rules, sensitive
from friday.guardrails.limiter import AbuseLimiter, LimiterConfig
from friday.guardrails.models import Action, Category, Context, Decision, ReplyDecision
from friday.guardrails.normalize import squash, variants
from friday.guardrails.policy import DISCLAIMERS, POLICY
from friday.guardrails.scope import is_out_of_scope, mask_numbers
from friday.guardrails.sensitive import OtpSink, PendingLogins

MAX_TEXT = 4000
_MINOR_TTL_USERS = 20_000

# phrase-level overrides: rule id -> (action, reply key)
_RULE_REPLY: dict[str, tuple[Action, str]] = {
    "out_of_scope.politics": (Action.REDIRECT, "politics"),
    "out_of_scope.identity": (Action.ALLOW, "identity"),
}


@dataclass
class GuardrailsConfig:
    """What is on. Existing behaviours follow ``enabled`` (and their old switches); everything new
    is separate and OFF unless asked for."""

    enabled: bool = True  # FRIDAY_GUARDRAILS_ENABLED: master switch (existing behaviours)
    legacy_safety: bool = True  # FRIDAY_CHATBOT_GUARDS: emergency / medicine / fake bill
    legacy_quick: bool = True  # FRIDAY_CHATBOT_QUICK_ANSWERS
    legacy_offtopic: str = "redirect"  # FRIDAY_CHATBOT_OFFTOPIC: redirect | wishlist_only | off
    new_categories: bool = False  # FRIDAY_GUARDRAILS_NEW_CATEGORIES
    rate_limit: bool = False  # FRIDAY_GUARDRAILS_RATE_LIMIT
    output_filter: bool = False  # FRIDAY_GUARDRAILS_OUTPUT_FILTER
    login_otp_in_chat: bool = False  # FRIDAY_GUARDRAILS_LOGIN_OTP_IN_CHAT
    snippet_chars: int = 60

    @classmethod
    def from_settings(cls, s: object) -> GuardrailsConfig:
        g = lambda name, default: getattr(s, name, default)  # noqa: E731
        return cls(
            enabled=bool(g("guardrails_enabled", True)),
            legacy_safety=bool(g("chatbot_guards", True)),
            legacy_quick=bool(g("chatbot_quick_answers", True)),
            legacy_offtopic=str(g("chatbot_offtopic", "redirect")),
            new_categories=bool(g("guardrails_new_categories", False)),
            rate_limit=bool(g("guardrails_rate_limit", False)),
            output_filter=bool(g("guardrails_output_filter", False)),
            login_otp_in_chat=bool(g("guardrails_login_otp_in_chat", False)),
        )

    @classmethod
    def all_on(cls) -> GuardrailsConfig:
        return cls(new_categories=True, rate_limit=True, output_filter=True, login_otp_in_chat=True)


# categories that exist only when the new switch is on (for docs, doctor and tests)
NEW_CATEGORIES = tuple(c for c, p in POLICY.items() if not p.legacy)
LEGACY_CATEGORIES = tuple(c for c, p in POLICY.items() if p.legacy)


def _first(rule_list: list[rules.Rule], views: list[str]) -> rules.Rule | None:
    for r in rule_list:
        if any(r.matches(v) for v in views):
            return r
    return None


class Guardrails:
    def __init__(
        self,
        config: GuardrailsConfig | None = None,
        *,
        limiter: AbuseLimiter | None = None,
        pending: PendingLogins | None = None,
        otp_sink: OtpSink | None = None,
        limiter_config: LimiterConfig | None = None,
    ) -> None:
        self.cfg = config or GuardrailsConfig()
        self.limiter = limiter or AbuseLimiter(limiter_config)
        self.pending = pending or PendingLogins()
        self.otp_sink = otp_sink
        self.log: deque[dict[str, object]] = deque(maxlen=500)  # masked audit ring for the Lab / review
        self._last_variant: OrderedDict[str, dict[str, int]] = OrderedDict()
        self._minors: OrderedDict[str, datetime] = OrderedDict()

    # ------------------------------------------------------------------ public API
    def begin_login(self, user_id: str, site: str, task_id: str, now: datetime | None = None) -> None:
        """Friday just started a login on ``site`` for the user: a login code typed next is accepted."""
        self.pending.start(user_id, site, task_id, now or datetime.now(UTC))

    def redact_stored(self, message: str | None, user_id: str | None, now: datetime | None = None) -> bool:
        """True when the STORED copy of this inbound message must be replaced by a placeholder: a
        card number, CVV, PIN, password, a payment / Aadhaar code, or a login code (explicitly
        framed, or typed while a login is pending). A bare number with no pending login is kept."""
        if not (self.cfg.enabled and self.cfg.new_categories):
            return False
        f = sensitive.find(message)
        if f is None:
            return False
        if f.kind != "login_code":
            return True
        return f.explicit or bool(user_id and self.pending.has_pending(user_id, now or datetime.now(UTC)))

    def check(self, message: str | None, context: Context | None = None) -> Decision:
        ctx = context or Context()
        now = ctx.now or datetime.now(UTC)
        text = (message or "")[:MAX_TEXT]
        if not self.cfg.enabled or not text.strip():
            return Decision(Category.IN_SCOPE, Action.ALLOW, rule="off" if not self.cfg.enabled else "empty")
        d: Decision | None = None
        if ctx.phase in ("pre", "all"):
            d = self._pre(text, ctx, now)
        if d is None and ctx.phase in ("post", "all"):
            d = self._post(text, ctx, now)
        if d is None:
            d = Decision(Category.IN_SCOPE, Action.ALLOW, rule="none")
        self._record(d, ctx, text)
        return d

    def check_reply(self, reply: str | None, context: Context | None = None) -> ReplyDecision:
        """Filter an outgoing reply: secrets and system text, claims to be human, dosing, invented
        numbers and promises are replaced; advice-like text gets a disclaimer."""
        ctx = context or Context()
        text = reply or ""
        if not self.cfg.enabled or not self.cfg.output_filter or not text.strip():
            return ReplyDecision(Action.ALLOW, text)
        hit = [name for name, pat in _REPLY_BLOCK if pat.search(text)]
        if ctx.known_numbers is not None:
            hit += _unknown_numbers(text, ctx.known_numbers)
        found = sensitive.find(text)
        if found is not None and found.kind in ("card_number", "cvv"):
            hit.append("echoes_card_data")
        if hit:
            key = "unverified_number" if hit == ["unknown_number"] else (
                "safety_medicine" if hit == ["dosing"] else "reply_fallback")
            out = copy.line(key, ctx.lang)
            self._log_reply(Action.REFUSE, hit, ctx)
            return ReplyDecision(Action.REFUSE, out, hit)
        notes = [dom for dom, pat in _REPLY_ADVICE if pat.search(text)]
        if notes:
            extra = " ".join(copy.line(DISCLAIMERS[d], ctx.lang) for d in notes)
            self._log_reply(Action.ALLOW_WITH_DISCLAIMER, [f"advice_{d}" for d in notes], ctx)
            return ReplyDecision(Action.ALLOW_WITH_DISCLAIMER, f"{text.rstrip()}\n{extra}", [f"advice_{d}" for d in notes])
        return ReplyDecision(Action.ALLOW, text)

    # ------------------------------------------------------------------ before the flows
    def _pre(self, text: str, ctx: Context, now: datetime) -> Decision | None:
        cfg = self.cfg
        new = cfg.new_categories
        views = variants(text)
        legacy_kind = None
        if cfg.legacy_safety:
            legacy_kind = legacy.safety_kind(text) or next(
                (k for v in views if (k := legacy.safety_kind(v))), None)
        sq = squash(text) if len(text) <= 120 else ""

        if new and ((r := _first(rules.SELF_HARM, views)) or _SQUASH_SELF_HARM.search(sq)):
            return self._decide(Category.SELF_HARM, r.id if r else "self_harm.squashed", ctx)
        if new and (r := _first(rules.EMERGENCY_EXTRA, views)):
            return self._decide(Category.EMERGENCY, r.id, ctx)
        if legacy_kind == "emergency" or (cfg.legacy_safety and _SQUASH_EMERGENCY.search(sq)):
            return self._decide(Category.EMERGENCY, "legacy.emergency", ctx)

        if new and (d := self._sensitive(text, ctx, now)) is not None:
            return d

        if cfg.rate_limit and ctx.user_id:
            verdict = self.limiter.note(ctx.user_id, text, now)
            if verdict == "silent":
                return Decision(Category.RATE_LIMITED, Action.REFUSE, rule="limiter.muted", silent=True)
            if verdict == "notice":
                return self._decide(Category.RATE_LIMITED, "limiter.notice", ctx)

        if new:
            if (r := _first(rules.MINORS, views)) is not None:
                if ctx.user_id:
                    self._remember_minor(ctx.user_id, now)
                return self._decide(Category.MINORS, r.id, ctx)
            if (ctx.is_minor or self._is_known_minor(ctx.user_id)) and rules.MINOR_SENSITIVE_SKILL.search(views[0]):
                return self._decide(Category.MINORS, "minors.skill", ctx)
            if r := _first(rules.PROMPT_INJECTION, views):
                return self._decide(Category.PROMPT_INJECTION, r.id, ctx)

        if legacy_kind == "forgery":
            return self._decide(Category.FAKE_DOCUMENTS, "legacy.forgery", ctx)
        if new:
            for group, cat in (
                (rules.FAKE_DOCUMENTS, Category.FAKE_DOCUMENTS),
                (rules.ILLEGAL, Category.ILLEGAL),
                (rules.HARASSMENT, Category.HARASSMENT_ABUSE),
                (rules.ADULT, Category.ADULT),
                (rules.PRIVACY, Category.PRIVACY_OTHERS),
            ):
                if r := _first(group, views):
                    reply_key = "fake_documents" if cat == Category.FAKE_DOCUMENTS else None
                    return self._decide(cat, r.id, ctx, reply_key=reply_key)
        if legacy_kind == "medicine" or (cfg.legacy_safety and _SQUASH_MEDICINE.search(sq) and not legacy._MED_EXEMPT.search(text)):
            return self._decide(Category.MEDICAL_ADVICE, "legacy.medicine", ctx)
        if new and (r := _first(rules.MEDICAL, views)):
            return self._decide(Category.MEDICAL_ADVICE, r.id, ctx)
        if new:
            for group, cat in (
                (rules.LEGAL, Category.LEGAL_ADVICE),
                (rules.FINANCIAL, Category.FINANCIAL_ADVICE),
                (rules.PROHIBITED, Category.PROHIBITED_ACTION),
            ):
                if r := _first(group, views):
                    return self._decide(cat, r.id, ctx)
        return None

    # ------------------------------------------------------------------ after the flows
    def _post(self, text: str, ctx: Context, now: datetime) -> Decision | None:
        cfg = self.cfg
        if cfg.legacy_quick and (quick := legacy.quick_answer(text, now)) is not None:
            return Decision(Category.FACTUAL, Action.ALLOW, rule="legacy.quick", reply_id=quick[0], quick=quick)
        if cfg.new_categories:
            views = variants(text)
            for group in (rules.IDENTITY, rules.POLITICS):
                if r := _first(group, views):
                    return self._decide(Category.OUT_OF_SCOPE, r.id, ctx)
        if cfg.legacy_offtopic != "off" and is_out_of_scope(text):
            action = Action.REDIRECT if cfg.legacy_offtopic == "redirect" else Action.ALLOW
            d = Decision(Category.OUT_OF_SCOPE, action, rule="legacy.out_of_scope")
            if action == Action.REDIRECT:
                d.reply_id, d.reply = "offtopic", copy.line("offtopic", ctx.lang)
            return d
        if cfg.new_categories and rules.SMALL_TALK.match(" ".join(text.split())):
            return Decision(Category.SMALL_TALK, Action.ALLOW, rule="small_talk")
        return None

    # ------------------------------------------------------------------ sensitive codes
    def _sensitive(self, text: str, ctx: Context, now: datetime) -> Decision | None:
        f = sensitive.find(text)
        if f is None:
            return None
        rule = f"sensitive_codes.{f.kind}"
        if f.kind == "login_code":
            p = None
            if self.cfg.login_otp_in_chat and ctx.user_id and self.otp_sink is not None:
                p = self.pending.claim(ctx.user_id, now)
            if p is None:
                if f.explicit:  # "otp hai 4821" but Friday started no login: refuse, never relay
                    return self._decide(Category.SENSITIVE_CODES, "sensitive_codes.unsolicited_code", ctx, reply_key="sensitive_unsolicited")
                return None  # a bare number with no pending login is not an OTP: left alone
            try:
                self.otp_sink(p.task_id, f.code or "")
            except Exception:  # noqa: BLE001 - never leak the code through an error
                self.pending.start(p.user_id, p.site, p.task_id, now)
                d = self._decide(Category.SENSITIVE_CODES, "sensitive_codes.sink_failed", ctx, reply_key="otp_failed", action=Action.ALLOW)
                return d
            return self._decide(Category.SENSITIVE_CODES, rule, ctx, reply_key="otp_ack", action=Action.ALLOW, route="browser_worker")
        key = {
            "unsolicited_code": "sensitive_unsolicited",
            "password": "sensitive_password",
        }.get(f.kind, "sensitive_payment")
        return self._decide(Category.SENSITIVE_CODES, rule, ctx, reply_key=key)

    # ------------------------------------------------------------------ decisions
    def _decide(
        self, cat: Category, rule: str, ctx: Context, *, reply_key: str | None = None,
        action: Action | None = None, route: str | None = None,
    ) -> Decision:
        pol = POLICY[cat]
        act = action or pol.action
        key = reply_key or pol.reply_key
        if rule in _RULE_REPLY:
            act, key = _RULE_REPLY[rule]
        reply = self._render(key, ctx) if key else None
        if pol.strike and self.cfg.rate_limit and ctx.user_id:
            self.limiter.strike(ctx.user_id, ctx.now or datetime.now(UTC))
        return Decision(cat, act, rule=rule, reply_id=key, reply=reply, route=route)

    def _render(self, key: str, ctx: Context) -> str:
        n = copy.n_variants(key)
        idx = 0
        if n > 1 and ctx.user_id:
            seen = self._last_variant.setdefault(ctx.user_id, {})
            self._last_variant.move_to_end(ctx.user_id)
            idx = (seen.get(key, -1) + 1) % n
            seen[key] = idx
            while len(self._last_variant) > _MINOR_TTL_USERS:
                self._last_variant.popitem(last=False)
        return copy.line(key, ctx.lang, idx)

    def _remember_minor(self, user_id: str, now: datetime) -> None:
        self._minors[user_id] = now
        self._minors.move_to_end(user_id)
        while len(self._minors) > _MINOR_TTL_USERS:
            self._minors.popitem(last=False)

    def _is_known_minor(self, user_id: str | None) -> bool:
        return bool(user_id and user_id in self._minors)

    # ------------------------------------------------------------------ audit
    def _record(self, d: Decision, ctx: Context, text: str) -> None:
        """Attach the masked audit record (nothing for plain allowed messages) and keep a ring copy."""
        loggable = d.action != Action.ALLOW or d.category in (Category.SENSITIVE_CODES, Category.RATE_LIMITED) or d.silent
        if not loggable:
            return
        pol = POLICY[d.category]
        snippet = mask_numbers(text, self.cfg.snippet_chars) if pol.audit_snippet else ""
        rec: dict[str, object] = {
            "category": d.category.value, "action": d.action.value, "rule": d.rule, "phase": ctx.phase,
            "lang": ctx.lang, "length": len(text), "snippet": snippet, "silent": d.silent,
            "user": hashlib.sha256((ctx.user_id or "-").encode()).hexdigest()[:8],
        }
        d.audit = rec
        self.log.append({**rec, "at": (ctx.now or datetime.now(UTC)).isoformat()})

    def _log_reply(self, action: Action, rules_hit: list[str], ctx: Context) -> None:
        self.log.append({
            "category": "reply_filter", "action": action.value, "rule": ",".join(rules_hit), "phase": "reply",
            "lang": ctx.lang, "length": 0, "snippet": "", "silent": False,
            "user": hashlib.sha256((ctx.user_id or "-").encode()).hexdigest()[:8],
            "at": (ctx.now or datetime.now(UTC)).isoformat(),
        })


# a few high-risk terms typed with stray gaps ("kh u d ko khatam"), matched on the squashed text
_SQUASH_SELF_HARM = re.compile(r"suicid|khudkokhatam|khudkomaar|marnachah|jeenekamann(?:ahi|ahi)|iwanttodie|endmylife")
_SQUASH_EMERGENCY = re.compile(r"cantbreathe|cannotbreathe|saansnahi|heartattack")
_SQUASH_MEDICINE = re.compile(r"(?:konsi|kaunsi|kaunsa|konsa|which)(?:dawai|dwai|dawa|medicine|tablet|goli)")

# ---------------------------------------------------------------------- reply-side rules
_I = re.IGNORECASE
_REPLY_BLOCK: list[tuple[str, re.Pattern[str]]] = [
    ("system_text", re.compile(r"\b(?:my\s+system\s+prompt|system\s+prompt\s*[:=]|my\s+instructions\s+(?:are|say)|FRIDAY_[A-Z][A-Z0-9_]{3,}|(?:api|secret)[_\s-]?key\s*[:=]|sk-[A-Za-z0-9_\-]{16,}|-----BEGIN\s+[A-Z ]*PRIVATE\s+KEY)", _I)),
    ("claims_human", re.compile(r"\b(?:i\s*(?:am|'m)\s+(?:a\s+)?(?:real\s+)?(?:human|person|woman|girl|man)\b(?!\s*(?:not|n't))|(?:main|mai)\s+(?:ek\s+)?(?:asli\s+)?(?:insaan|insan|human|ladki|aurat)\s+(?:hoon|hun|hu)\b)|(?:मैं|मै)\s+(?:एक\s+)?(?:असली\s+)?(?:इंसान|इंसान|लड़की)\s+(?:हूँ|हूं)", _I)),
    ("dosing", re.compile(r"\b(?:take|lein|lo|leni|khaiye|khao|le\s+lijiye|le\s+lo)\s+(?:\w+\s+){0,3}\d+\s*(?:mg|ml|mcg|tablets?|goli|gram)\b|\b\d+\s*(?:mg|ml|mcg)\s+(?:\w+\s+){0,3}(?:twice|thrice|daily|din\s+mein|subah|raat|every)\b", _I)),
    ("promise", re.compile(r"\b(?:guarantee[ds]?|100\s*%\s+(?:sure|safe|refund|certain)|pakka\s+(?:refund|paisa)|paisa\s+wapas\s+mil\s+(?:jayega|jaayega)|definitely\s+(?:get|receive)\s+(?:a\s+)?refund)\b", _I)),
    ("injection_echo", re.compile(r"\b(?:ignore\s+(?:all\s+)?previous\s+instructions|disregard\s+(?:the\s+)?above)\b", _I)),
]
_REPLY_ADVICE: list[tuple[str, re.Pattern[str]]] = [
    ("medical", re.compile(r"\b(?:symptoms?\s+(?:of|suggest|indicate)|could\s+be\s+(?:a\s+)?(?:infection|virus|flu|dengue)|medicine\s+(?:helps|can\s+help)|bukhar\s+(?:ke\s+liye|mein))\b", _I)),
    ("legal", re.compile(r"\b(?:you\s+(?:can|may|should)\s+(?:file|sue|take\s+legal)|legal\s+(?:action|notice)\s+(?:is|can)|under\s+(?:section|article)\s+\d+)\b", _I)),
    ("financial", re.compile(r"\b(?:you\s+should\s+(?:invest|buy|sell)|good\s+(?:investment|returns?)|mutual\s+funds?\s+(?:are|give)|returns?\s+of\s+\d+\s*%)\b", _I)),
]
_NUMBER = re.compile(r"(?<![\w.])(?:₹|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)(?![\w.])", _I)


def _unknown_numbers(text: str, known: frozenset[str]) -> list[str]:
    """Amounts or ids of 3+ digits in the reply that did not come from a tool or the user."""
    known_clean = {k.replace(",", "") for k in known}
    for m in _NUMBER.finditer(text):
        n = m.group(1).replace(",", "")
        if len(n.replace(".", "")) >= 3 and n not in known_clean:
            return ["unknown_number"]
    return []


# ---------------------------------------------------------------------- module-level entry points
_default: Guardrails | None = None


def default_engine() -> Guardrails:
    global _default
    if _default is None:
        _default = Guardrails()
    return _default


def check(message: str | None, context: Context | None = None, *, engine: Guardrails | None = None) -> Decision:
    """The single entry the chatbot pipeline calls BEFORE any model sees the message."""
    return (engine or default_engine()).check(message, context)


def check_reply(reply: str | None, context: Context | None = None, *, engine: Guardrails | None = None) -> ReplyDecision:
    """Filter a reply on its way out."""
    return (engine or default_engine()).check_reply(reply, context)
