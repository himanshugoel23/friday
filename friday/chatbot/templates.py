# ruff: noqa: E501
"""The WhatsApp template drafts (``templates.yaml``), the checker, and the sender helper.

Messages Friday sends outside the 24-hour window must be pre-approved Meta templates. The drafts
live in ``friday/chatbot/templates.yaml`` (PENDING_FOUNDER_APPROVAL); ``docs/WHATSAPP_TEMPLATES.md``
is rendered from it. :func:`check` is what ``friday chatbot templates check`` runs:

* every template's placeholders are ``{{1}}..{{n}}``, match the number of ``params`` and
  ``examples``, never start or end the body and never touch each other (Meta's rules);
* buttons: at most 3 quick replies, titles at most 25 characters, a known ``action``;
* every body says plainly that Friday is an assistant and that she never asks for payment, OTP or
  PIN, and carries its reason (the ``why`` sentence) and how to stop (the chat-quality statement
  rules of ``composer.py``);
* names are Meta-legal and unique, and do not collide with the registry in
  ``friday/core/templates.py``; the ``fallback`` each draft names is a real registered template;
* with the chatbot switched on, ``Settings.whatsapp_templates`` carries every logical key with the
  exact name from this file (so the channel sends the right template);
* every call of :func:`chatbot_template` in the code passes a known key and the right number of
  parameters (found by reading the source, like ``tests/channels/test_templates.py`` does).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from friday.chatbot import composer
from friday.core.models import TemplateRef

YAML_PATH = Path(__file__).with_name("templates.yaml")
ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = ROOT / "docs" / "WHATSAPP_TEMPLATES.md"

CATEGORIES = ("UTILITY", "MARKETING")
LANGS = ("en", "hi")  # Meta language codes of the primary name: Roman Hinglish (en) and Hindi (hi)
MAX_BODY = 1024
MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 25  # Meta: quick-reply text
NAME_RE = re.compile(r"^[a-z0-9_]{1,512}$")
PLACEHOLDER = re.compile(r"\{\{(\d+)\}\}")
# what the chatbot does when a template button is tapped (see ChatbotService._template_action)
BUTTON_ACTIONS = ("ok", "stop", "human", "consent_yes", "consent_no", "details")
SENDER_FUNCS = ("chatbot_template", "template_ref")


@dataclass(frozen=True)
class Button:
    title: str
    payload: str
    action: str


@dataclass(frozen=True)
class Variant:
    """One registration at Meta: a name + a language code + a body."""

    label: str  # hinglish | hi | en
    key: str
    name: str
    meta_language: str
    body: str
    buttons: tuple[Button, ...]


@dataclass(frozen=True)
class Draft:
    key: str
    name: str
    category: str
    purpose: str
    params: tuple[str, ...]
    examples: tuple[str, ...]
    fallback: str
    why: dict[str, str]
    variants: tuple[Variant, ...]

    @property
    def n_params(self) -> int:
        return len(self.params)

    def variant(self, lang: str) -> Variant:
        """The registration for a user language: hinglish / hi / en."""
        return next(v for v in self.variants if v.label == lang)

    @property
    def keys(self) -> list[str]:
        return sorted({v.key for v in self.variants})


@dataclass
class Problem:
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


@dataclass
class Report:
    problems: list[Problem] = field(default_factory=list)
    drafts: int = 0
    registrations: int = 0
    call_sites: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    def add(self, where: str, message: str) -> None:
        self.problems.append(Problem(where, message))


# ---------------------------------------------------------------------- loading
def _button(raw: dict[str, Any]) -> Button:
    return Button(str(raw["title"]), str(raw["payload"]), str(raw["action"]))


def parse(data: dict[str, Any]) -> list[Draft]:
    drafts: list[Draft] = []
    for t in data.get("templates") or []:
        variants: list[Variant] = []
        for lang, v in (t.get("languages") or {}).items():
            variants.append(
                Variant(
                    label="hinglish" if lang == "en" else lang,
                    key=t["key"],
                    name=t["name"],
                    meta_language=lang,
                    body=str(v["body"]),
                    buttons=tuple(_button(b) for b in v.get("buttons") or []),
                )
            )
        if (eng := t.get("english")) is not None:
            variants.append(
                Variant(
                    label="en",
                    key=eng["key"],
                    name=eng["name"],
                    meta_language="en",
                    body=str(eng["body"]),
                    buttons=tuple(_button(b) for b in eng.get("buttons") or []),
                )
            )
        drafts.append(
            Draft(
                key=t["key"],
                name=t["name"],
                category=str(t["category"]),
                purpose=str(t.get("purpose", "")),
                params=tuple(str(p) for p in t.get("params") or []),
                examples=tuple(str(e) for e in t.get("examples") or []),
                fallback=str(t.get("fallback", "")),
                why={k: str(v) for k, v in (t.get("why") or {}).items()},
                variants=tuple(variants),
            )
        )
    return drafts


@lru_cache(maxsize=1)
def load(path: Path = YAML_PATH) -> tuple[Draft, ...]:
    return tuple(parse(yaml.safe_load(path.read_text(encoding="utf-8"))))


def by_key() -> dict[str, Draft]:
    out: dict[str, Draft] = {}
    for d in load():
        for k in d.keys:
            out[k] = d
    return out


def template_names() -> dict[str, str]:
    """Logical key -> Meta name for every key in the file (merged into Settings when the chatbot
    is on)."""
    return {v.key: v.name for d in load() for v in d.variants}


# ---------------------------------------------------------------------- sending
def chatbot_template(key: str, params: list[str], lang: str = "hinglish") -> TemplateRef:
    """A ``TemplateRef`` for one of the drafts, checked against the file. ``lang`` is the user's
    language (hinglish / hi / en); the logical key and Meta language code follow from it. Raises
    ``ValueError`` for an unknown key or a wrong number of parameters."""
    draft = next((d for d in load() if key in (d.key, *d.keys)), None)
    if draft is None:
        raise ValueError(f"unknown chatbot template {key!r} (add it to chatbot/templates.yaml)")
    if len(params) != draft.n_params:
        raise ValueError(f"template {key!r} takes {draft.n_params} variable(s), got {len(params)}")
    v = draft.variant(lang if lang in ("hi", "en") else "hinglish")
    return TemplateRef.model_validate(
        {"key": v.key, "params": list(params), "language": v.meta_language}
    )


def button_action(button_id: str | None, title: str | None = None) -> str | None:
    """What a tap on a template button means: by payload when the channel carries it, else by the
    title (the channel does not send button payloads yet; see docs/CHATBOT_PILOT.md)."""
    for d in load():
        for v in d.variants:
            for b in v.buttons:
                if button_id and b.payload == button_id:
                    return b.action
    if title:
        t = " ".join(title.split()).lower()
        hits = {
            b.action for d in load() for v in d.variants for b in v.buttons if b.title.lower() == t
        }
        if len(hits) == 1:
            return hits.pop()
    return None


# ---------------------------------------------------------------------- the checker
def _fill(body: str, examples: tuple[str, ...]) -> str:
    return PLACEHOLDER.sub(
        lambda m: examples[int(m.group(1)) - 1] if int(m.group(1)) <= len(examples) else "?", body
    )


def _check_body(report: Report, where: str, d: Draft, v: Variant) -> None:
    nums = [int(n) for n in PLACEHOLDER.findall(v.body)]
    if sorted(set(nums)) != list(range(1, d.n_params + 1)):
        report.add(where, f"placeholders {sorted(set(nums))} do not match {d.n_params} param(s)")
    if re.search(r"\{\{[^}]*\}\}", PLACEHOLDER.sub("", v.body)):
        report.add(where, "malformed placeholder (use {{1}}, {{2}}...)")
    body = v.body.strip()
    if PLACEHOLDER.match(body) or re.search(r"\{\{\d+\}\}$", body):
        report.add(where, "body starts or ends with a variable (Meta rejects it)")
    if re.search(r"\{\{\d+\}\}\s*\{\{\d+\}\}", body):
        report.add(where, "two variables next to each other")
    if len(body) > MAX_BODY:
        report.add(where, f"body is {len(body)} characters (max {MAX_BODY})")
    if len(d.params) != len(d.examples):
        report.add(where, f"{len(d.params)} params but {len(d.examples)} examples")
    # the chat-quality statement rules on the body with the examples filled in
    filled = _fill(body, d.examples)
    why = d.why.get(v.label, "")
    if not why or why not in body:
        report.add(where, "the body does not carry its 'why' sentence")
    c = composer.Composer()
    for problem in c.check(filled, kind="proactive", why=why or None):
        report.add(where, problem)
    if "stop" not in body.lower():
        report.add(where, "the body does not say how to stop")


def _check_buttons(report: Report, where: str, v: Variant) -> None:
    if len(v.buttons) > MAX_BUTTONS:
        report.add(where, f"{len(v.buttons)} buttons (max {MAX_BUTTONS})")
    titles = [b.title.lower() for b in v.buttons]
    if len(set(titles)) != len(titles):
        report.add(where, "duplicate button title")
    for b in v.buttons:
        if not b.title or len(b.title) > MAX_BUTTON_TITLE:
            report.add(where, f"button title {b.title!r} must be 1-{MAX_BUTTON_TITLE} characters")
        if b.action not in BUTTON_ACTIONS:
            report.add(where, f"button {b.title!r}: unknown action {b.action!r}")
        if len(b.payload) > 128:
            report.add(where, f"button {b.title!r}: payload longer than 128")


def scan_call_sites(roots: list[Path]) -> list[tuple[Path, int, ast.Call]]:
    sites: list[tuple[Path, int, ast.Call]] = []
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in files:
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = getattr(node.func, "id", getattr(node.func, "attr", ""))
                    if fn in SENDER_FUNCS:
                        sites.append((path, node.lineno, node))
    return sites


def check(
    drafts: tuple[Draft, ...] | None = None,
    *,
    roots: list[Path] | None = None,
    settings: Any = None,
    doc: Path | None = DOC_PATH,
) -> Report:
    """Run every check; the report lists the problems (empty == pass)."""
    from friday.core.config import Settings
    from friday.core.templates import WHATSAPP_TEMPLATES

    ds = drafts if drafts is not None else load()
    report = Report(drafts=len(ds))
    seen_keys: dict[str, str] = {}
    seen_regs: set[tuple[str, str]] = set()
    core_names = {s.name for s in WHATSAPP_TEMPLATES.values()}
    cfg = settings or Settings(_env_file=None, chatbot_onboarding=True)
    configured = dict(cfg.whatsapp_templates)

    for d in ds:
        where = d.key
        if d.category not in CATEGORIES:
            report.add(where, f"category {d.category!r} must be UTILITY or MARKETING")
        if d.fallback and d.fallback not in WHATSAPP_TEMPLATES:
            report.add(where, f"fallback {d.fallback!r} is not in friday/core/templates.py")
        if not d.params:
            report.add(where, "no params")
        labels = [v.label for v in d.variants]
        if sorted(labels) != ["en", "hi", "hinglish"]:
            report.add(where, f"needs a hinglish, hi and en variant, has {sorted(labels)}")
        for v in d.variants:
            vw = f"{v.key}[{v.label}]"
            report.registrations += 1
            if not NAME_RE.match(v.name):
                report.add(vw, f"name {v.name!r} must be lowercase letters, digits and underscores")
            if v.name in core_names:
                report.add(vw, f"name {v.name!r} already belongs to a registered template")
            if (v.name, v.meta_language) in seen_regs:
                report.add(vw, f"{v.name!r} in language {v.meta_language!r} is registered twice")
            seen_regs.add((v.name, v.meta_language))
            if seen_keys.setdefault(v.key, v.name) != v.name:
                report.add(vw, f"key {v.key!r} maps to two different names")
            if v.key in WHATSAPP_TEMPLATES:
                report.add(vw, f"key {v.key!r} collides with a core template key")
            if configured.get(v.key) != v.name:
                report.add(
                    vw,
                    f"Settings.whatsapp_templates[{v.key!r}] is {configured.get(v.key)!r}, "
                    f"the file says {v.name!r}",
                )
            _check_body(report, vw, d, v)
            _check_buttons(report, vw, v)

    known = {k: d for d in ds for k in d.keys}
    for path, line, node in scan_call_sites(roots if roots is not None else [ROOT / "friday"]):
        if path == Path(__file__).resolve():
            continue
        report.call_sites += 1
        where = f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}:{line}"
        key = (
            node.args[0]
            if node.args
            else next((k.value for k in node.keywords if k.arg == "key"), None)
        )
        params = (
            node.args[1]
            if len(node.args) > 1
            else next((k.value for k in node.keywords if k.arg == "params"), None)
        )
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            report.add(where, "the template key must be a literal string")
            continue
        draft = known.get(key.value)
        if draft is None:
            report.add(where, f"unknown chatbot template {key.value!r}")
        elif isinstance(params, ast.List) and len(params.elts) != draft.n_params:
            report.add(
                where,
                f"{key.value!r} takes {draft.n_params} variable(s), the code sends {len(params.elts)}",
            )
        elif not isinstance(params, ast.List):
            report.add(where, f"the parameters of {key.value!r} must be a literal list")

    if doc is not None:
        if not doc.exists():
            report.add(str(doc.name), "missing (run: friday chatbot templates render)")
        else:
            text = doc.read_text(encoding="utf-8")
            for name in sorted({v.name for d in ds for v in d.variants}):
                if f"`{name}`" not in text:
                    report.add(doc.name, f"does not list {name}")
    return report


# ---------------------------------------------------------------------- rendering
def render(drafts: tuple[Draft, ...] | None = None) -> str:
    """docs/WHATSAPP_TEMPLATES.md, generated from the file."""
    ds = drafts if drafts is not None else load()
    out = [
        "# WhatsApp templates for messages outside the 24-hour window",
        "",
        "STATUS: DRAFT, PENDING_FOUNDER_APPROVAL. Nothing here has been submitted to Meta. The words",
        "are not approved; real template approval by Meta is not verified.",
        "",
        "This file is GENERATED from `friday/chatbot/templates.yaml` (edit that file, then run",
        "`uv run friday chatbot templates render > docs/WHATSAPP_TEMPLATES.md`). Check it with",
        "`uv run friday chatbot templates check` (placeholders, buttons, the plain statement, names",
        "against `friday/core/templates.py` and `Settings.whatsapp_templates`, and every sender in",
        "the code).",
        "",
        "How to register (Meta WhatsApp Manager, Message templates):",
        "1. Each draft below is registered under its `name` twice: language `en` with the Roman",
        "   Hinglish text (the product default) and language `hi` with the Devanagari text. The plain",
        "   English text is a separate name (`..._en_v1`, language `en`). Choose the category shown.",
        "2. Paste the body exactly, with the example values as the sample for {{1}}, {{2}}...",
        "3. Add the quick-reply buttons in the order shown (titles up to 25 characters).",
        "4. The chatbot passes the logical `key` as `TemplateRef.key`; `Settings.whatsapp_templates`",
        "   maps it to the Meta name (`FRIDAY_WHATSAPP_TEMPLATES` can override a name).",
        "5. Until a draft is approved the generic fallback named in each section keeps being used.",
        "",
        "| Logical key | Meta name | Category | Variables | Generic fallback |",
        "|---|---|---|---|---|",
    ]
    for d in ds:
        out.append(
            f"| `{d.key}` | `{d.name}` (+ `{d.variant('en').name}`) | {d.category} | {d.n_params} | `{d.fallback}` |"
        )
    for d in ds:
        out += ["", f"## `{d.name}` ({d.category})", "", d.purpose, ""]
        out.append(
            "Variables: " + "; ".join(f"{{{{{i}}}}} = {p}" for i, p in enumerate(d.params, 1))
        )
        out.append("")
        out.append(
            "Examples: " + "; ".join(f"{{{{{i}}}}} = {e!r}" for i, e in enumerate(d.examples, 1))
        )
        out.append("")
        out.append(f"Why sentence (must be in every body): {d.why['hinglish']}")
        for v in d.variants:
            title = {"hinglish": "Roman Hinglish", "hi": "Hindi", "en": "English"}[v.label]
            out += [
                "",
                f"### {title}: name `{v.name}`, language `{v.meta_language}`, key `{v.key}`",
                "",
            ]
            out += ["```text", *v.body.split("\n"), "```", ""]
            out.append(
                "Buttons: "
                + ", ".join(
                    f'"{b.title}" (payload `{b.payload}`, action {b.action})' for b in v.buttons
                )
            )
    out += [
        "",
        "## Notes and open points",
        "",
        "- Meta may re-categorise a UTILITY template as MARKETING (and charge accordingly). The",
        "  re-engage draft is submitted as MARKETING on purpose; the others are UTILITY because they",
        "  carry something the user asked for.",
        "- Roman Hinglish is submitted under language code `en` because Meta has no Hinglish code;",
        "  whether Meta accepts that is NOT verified.",
        "- The WhatsApp channel (`friday/channels/whatsapp.py`) sends body parameters only, not button",
        "  payloads; a tap on a template button arrives with the button title, which the chatbot maps",
        "  with `button_action` (`friday/chatbot/templates.py`). Sending payloads is a later change.",
        "- Nothing sends these templates yet: the notifier still falls back to the generic ones",
        "  (`nudge`, `task_update`, `reengage`). `chatbot_template(key, params, lang)` builds the",
        "  reference once a draft is approved and a sender is switched over.",
        "",
    ]
    return "\n".join(out)
