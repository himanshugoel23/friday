"""Playbook file format, loader and validator.

A playbook is ONE data file (YAML or JSON, ``friday/playbooks/data/<id>.yaml``) describing a
call as a small state machine with FIXED lines. A new business type is a new file; no code.

    version: 1
    id: salon_booking
    inputs: {...}            what the task must know before dialling
    outputs: [...]           what the call collects
    limits: {...}            duration / repeat / confusion limits
    lines: {id: "Hinglish text with {slots}"}      every word Friday may say
    routes: {name: [{when: [...], goto: S4}, ...]} shared "where next" decisions
    defaults: {INTENT: action}                     branches every step inherits
    steps: {S1: {ask: [...], branches: {INTENT: action}}}
    outcomes: {NAME: {call_outcome: ..., ...}}

``load_playbook`` returns a validated ``Playbook`` or raises ``PlaybookError`` listing every
problem. See docs/PLAYBOOKS.md for the founder-facing guide.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from friday.core.models import CallOutcome
from friday.core.safety import _SECRET_WORDS, looks_like_commitment
from friday.playbooks.intents import (
    ANY,
    CONDITIONS,
    INPUT_NAMES,
    INTENTS,
    PLACEHOLDERS,
    SETTABLE,
)
from friday.voice.text import strip_fillers

DATA_DIR = Path(__file__).with_name("data")
SUPPORTED_VERSIONS = frozenset({1})
MAX_LINE_CHARS = 240

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HUMAN_CLAIM = re.compile(
    r"\b(i am|i'm) (a )?(real )?(human|person|real person)\b|main insaan hoon|"
    r"main (ek )?(aadmi|ladki|insaan) hoon",
    re.I,
)
# words no Friday line may carry (the salon is never asked for, nor told, these)
_FORBIDDEN_WORDS = re.compile(
    r"(?<![\w])(otp|pin|cvv|cvc|card|debit|credit|password|passcode|aadhaar|aadhar|upi|"
    r"net ?banking|account number)(?![\w])",
    re.I,
)
# a sentence that claims a booking/confirmation happened or is being made
_CLAIM = re.compile(
    r"\b(confirmed|booked|reserved|pakka|ho gaya|ho gayi|ho gaye|book kar diya|confirm kar diya|"
    r"book kar liya|done|booking ho|confirm ho)\b",
    re.I,
)
_CONFIRM = re.compile(r"\bconfirm\w*\b", re.I)
_NEGATED_OR_FUTURE = re.compile(
    r"\bnahi\b|\bnahin\b|\bnot\b|\bkarke\b|\bse confirm\b|\bapproval\b|\bpoochh\b|\bpuchh\b|"
    r"\bcheck\b|\bpehle\b",
    re.I,
)
_SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+")

# sample values used to render every line once at load time
_SAMPLE: dict[str, str] = {
    "user_first_name": "Rahul", "service": "haircut", "for_whom": "Rahul",
    "date_window": "kal shaam", "budget": "600", "stylist_pref": "Amit",
    "callback_number": "yeh number", "slot": "kal shaam 6 baje", "price_inr": "500",
    "duration_min": "30", "stylist": "Amit", "honorific": "ji", "business_name": "Shreya salon",
}  # fmt: skip
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


class PlaybookError(ValueError):
    """The playbook file is invalid. ``problems`` lists everything wrong with it."""

    def __init__(self, problems: list[str], name: str = "playbook") -> None:
        self.problems = problems
        self.name = name
        super().__init__(f"{name}: " + "; ".join(problems))


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LineDef(_Strict):
    text: str
    commit: bool = False  # the one delegated-booking line


class LineRef(_Strict):
    """A line used at a point in the script, optionally conditional."""

    line: str
    when: list[str] = Field(default_factory=list)

    @field_validator("when", mode="before")
    @classmethod
    def _listify(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v


class Action(_Strict):
    """What happens for one (step, intent): speak, then move on or end."""

    when: list[str] = Field(default_factory=list)
    say: list[str | LineRef] = Field(default_factory=list)
    goto: str | None = None  # a step id, or "@route"
    outcome: str | None = None  # end the call with this outcome
    repeat: bool = False  # speak ``say`` (if any), then ask this step's question again
    stay: bool = False  # speak ``say`` only (it already contains the question), stay here
    hold_s: int | None = None  # wait silently (no speech), then re-ask this step
    commit: bool = False  # delegated commit (outcome BOOKED), still gated in code
    set: dict[str, str] = Field(default_factory=dict)
    max_uses: int | None = None  # per call; beyond it the branch counts as unhandled

    @field_validator("when", mode="before")
    @classmethod
    def _listify(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v


ActionOrList = Action | list[Action]


class Step(_Strict):
    ask: list[str | LineRef] = Field(default_factory=list)
    skip_when: list[str] = Field(default_factory=list)
    branches: dict[str, ActionOrList] = Field(default_factory=dict)
    final: bool = False  # nothing is asked; the actions only close the call
    max_visits: int | None = None  # e.g. the budget ask happens at most once

    @field_validator("skip_when", mode="before")
    @classmethod
    def _listify(cls, v: Any) -> Any:
        return [v] if isinstance(v, str) else v


class InputDef(_Strict):
    required: bool = False
    default: str | None = None


class Limits(_Strict):
    max_duration_s: int = 180
    max_repeats: int = 4  # one question may be asked at most this many times
    max_unclear_per_step: int = 2
    hold_max_s: int = 60
    max_turns: int = 30


class Confusion(_Strict):
    line: str  # "Sorry, ek baar phir?"
    outcome: str  # after max_unclear_per_step
    close: str | None = None  # spoken when giving up


class Select(_Strict):
    task_types: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class OutcomeDef(_Strict):
    call_outcome: str  # a friday.core.models.CallOutcome value
    description: str = ""
    collected: dict[str, str] = Field(default_factory=dict)  # facts added to CallResult.collected
    needs_quote: bool = False  # attach the Quote (price + slot)


class Playbook(_Strict):
    version: int
    id: str
    title: str = ""
    language: str = "hinglish"
    select: Select = Field(default_factory=Select)
    inputs: dict[str, InputDef] = Field(default_factory=dict)
    outputs: list[str] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)
    disclosure: str  # line id; the runner speaks it (AI disclosure first)
    confusion: Confusion
    lines: dict[str, str | LineDef]
    routes: dict[str, list[Action]] = Field(default_factory=dict)
    defaults: dict[str, ActionOrList] = Field(default_factory=dict)
    start: str
    steps: dict[str, Step]
    outcomes: dict[str, OutcomeDef]
    commit_step: str | None = None  # the only step allowed to book

    # filled by the loader, not by the file
    warnings: list[str] = Field(default_factory=list, exclude=True)
    source: str = Field(default="", exclude=True)

    # ------------------------------------------------------------------ helpers
    def line_def(self, line_id: str) -> LineDef:
        raw = self.lines[line_id]
        return raw if isinstance(raw, LineDef) else LineDef(text=raw)

    def text(self, line_id: str) -> str:
        return self.line_def(line_id).text

    def actions(self, a: ActionOrList) -> list[Action]:
        return a if isinstance(a, list) else [a]

    def all_actions(self) -> list[tuple[str, str, Action]]:
        """(where, intent, action) for every action in the file (steps, defaults, routes)."""
        out: list[tuple[str, str, Action]] = []
        for sid, step in self.steps.items():
            for intent, a in step.branches.items():
                out += [(f"steps.{sid}.{intent}", intent, x) for x in self.actions(a)]
        for intent, a in self.defaults.items():
            out += [(f"defaults.{intent}", intent, x) for x in self.actions(a)]
        for rid, lst in self.routes.items():
            out += [(f"routes.{rid}", "", x) for x in lst]
        return out

    def line_ids_used(self) -> set[str]:
        used = {self.disclosure, self.confusion.line}
        if self.confusion.close:
            used.add(self.confusion.close)
        for step in self.steps.values():
            used |= {_ref(x) for x in step.ask}
        for _w, _i, a in self.all_actions():
            used |= {_ref(x) for x in a.say}
        return used

    def placeholders_in(self, line_id: str) -> set[str]:
        return set(_PLACEHOLDER.findall(self.text(line_id)))

    def static_line_ids(self) -> list[str]:
        """Lines whose text depends only on the task's inputs (known before dialling), so the
        audio can be pre-rendered at call start."""
        input_only = INPUT_NAMES
        return [lid for lid in self.lines if self.placeholders_in(lid) <= input_only]

    def reachable_steps(self) -> set[str]:
        seen: set[str] = set()
        todo = [self.start]
        while todo:
            sid = todo.pop()
            if sid in seen or sid not in self.steps:
                continue
            seen.add(sid)
            step = self.steps[sid]
            acts = [x for a in step.branches.values() for x in self.actions(a)]
            acts += [x for a in self.defaults.values() for x in self.actions(a)]
            for a in acts:
                if a.goto:
                    if a.goto.startswith("@"):
                        for ra in self.routes.get(a.goto[1:], []):
                            if ra.goto and not ra.goto.startswith("@"):
                                todo.append(ra.goto)
                    else:
                        todo.append(a.goto)
        return seen


def _ref(x: str | LineRef) -> str:
    return x if isinstance(x, str) else x.line


def _cond_problems(where: str, conds: list[str]) -> list[str]:
    out = []
    for c in conds:
        if c.lstrip("!") not in CONDITIONS:
            allowed = ", ".join(sorted(CONDITIONS))
            out.append(f"{where}: unknown condition '{c}' (allowed: {allowed})")
    return out


def sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text.strip()) if s]


def line_problems(line_id: str, text: str, *, commit: bool = False) -> list[str]:
    """Everything wrong with one line's text (placeholders aside)."""
    p: list[str] = []
    where = f"line '{line_id}'"
    if not text.strip():
        return [f"{where}: empty"]
    if len(text) > MAX_LINE_CHARS:
        p.append(f"{where}: longer than {MAX_LINE_CHARS} characters (keep calls short)")
    if _DEVANAGARI.search(text):
        p.append(f"{where}: contains Devanagari; every line must be Hinglish (Roman script)")
    if strip_fillers(text) != text.strip():
        p.append(f"{where}: contains filler words/odd spacing (it would be changed before speech)")
    unknown = set(_PLACEHOLDER.findall(text)) - PLACEHOLDERS
    if unknown:
        p.append(f"{where}: unknown placeholder(s) {sorted(unknown)}")
    if re.search(r"\{[^a-z_}]|\{\}|\}[^ ]*\{", text) and not _PLACEHOLDER.search(text):
        p.append(f"{where}: malformed braces")
    sample = _PLACEHOLDER.sub(lambda m: _SAMPLE.get(m.group(1), "x"), text)
    if _FORBIDDEN_WORDS.search(sample) or _SECRET_WORDS.search(sample):
        p.append(f"{where}: mentions OTP/PIN/card/password style words (never allowed)")
    if _HUMAN_CLAIM.search(sample):
        p.append(f"{where}: claims to be human")
    if re.search(r"\d{6,}", sample):
        p.append(f"{where}: contains a long number")
    claims = looks_like_commitment(sample) or any(
        (_CLAIM.search(s) or _CONFIRM.search(s)) and not _NEGATED_OR_FUTURE.search(s)
        for s in sentences(sample)
    )
    if claims and not commit:
        p.append(
            f"{where}: claims or asks for a booking/confirmation; only the delegated-commit line "
            "(marked commit: true, used in the commit step) may do that"
        )
    if commit and not claims:
        p.append(f"{where}: marked commit but does not read as a confirmation")
    return p


def validate_data(data: dict[str, Any], name: str = "playbook") -> Playbook:
    """Validate a parsed playbook dict. Raises ``PlaybookError`` with ALL problems."""
    problems: list[str] = []
    version = data.get("version") if isinstance(data, dict) else None
    if version not in SUPPORTED_VERSIONS:
        raise PlaybookError([f"unsupported or missing version {version!r} (supported: 1)"], name)
    try:
        pb = Playbook.model_validate(data)
    except ValidationError as e:
        errs = [
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()
        ]
        raise PlaybookError(errs, name) from None

    if pb.language != "hinglish":
        problems.append("language must be 'hinglish' (founder decision: no language switching)")
    if pb.start not in pb.steps:
        problems.append(f"start step '{pb.start}' does not exist")
    for need in ("user_first_name",):
        if need not in pb.inputs:
            problems.append(f"inputs must declare '{need}'")
    for k in pb.inputs:
        if k not in INPUT_NAMES:
            problems.append(f"inputs.{k}: unknown input (allowed: {sorted(INPUT_NAMES)})")

    # ---- lines
    for lid in pb.lines:
        ld = pb.line_def(lid)
        problems += line_problems(lid, ld.text, commit=ld.commit)
    commit_lines = {lid for lid in pb.lines if pb.line_def(lid).commit}
    if len(commit_lines) > 1:
        problems.append(f"at most one commit line allowed, found {sorted(commit_lines)}")

    def need_line(where: str, lid: str) -> None:
        if lid not in pb.lines:
            problems.append(f"{where}: missing line '{lid}'")

    need_line("disclosure", pb.disclosure)
    need_line("confusion.line", pb.confusion.line)
    if pb.confusion.close:
        need_line("confusion.close", pb.confusion.close)
    if pb.disclosure in pb.lines:
        d = pb.text(pb.disclosure)
        if not re.search(r"\bAI\b", d):
            problems.append("the disclosure line must say that Friday is an AI")
        if not set(_PLACEHOLDER.findall(d)) <= INPUT_NAMES:
            problems.append("the disclosure line may only use inputs (it is spoken first)")
    if pb.confusion.outcome not in pb.outcomes:
        problems.append(f"confusion.outcome '{pb.confusion.outcome}' is not a defined outcome")

    # ---- outcomes
    valid_call = {o.value for o in CallOutcome}
    for oid, od in pb.outcomes.items():
        if od.call_outcome not in valid_call:
            problems.append(f"outcomes.{oid}: unknown call_outcome '{od.call_outcome}'")
    if "BOOKED" in pb.outcomes and pb.outcomes["BOOKED"].call_outcome != "success":
        problems.append("outcome BOOKED must map to call_outcome success")
    for oid, od in pb.outcomes.items():
        if od.call_outcome == "success" and oid != "BOOKED":
            problems.append(f"outcomes.{oid}: only BOOKED (the delegated commit) may be success")

    # ---- steps / actions
    def check_target(where: str, goto: str) -> None:
        if goto.startswith("@"):
            if goto[1:] not in pb.routes:
                problems.append(f"{where}: unknown route '{goto}'")
        elif goto not in pb.steps:
            problems.append(f"{where}: goto unknown step '{goto}'")

    def check_action(where: str, a: Action, *, in_final: bool, in_route: bool = False) -> None:
        problems.extend(_cond_problems(where, a.when))
        for item in a.say:
            need_line(where, _ref(item))
            if isinstance(item, LineRef):
                problems.extend(_cond_problems(where, item.when))
        if a.goto:
            check_target(where, a.goto)
        if a.outcome and a.outcome not in pb.outcomes:
            problems.append(f"{where}: unknown outcome '{a.outcome}'")
        kinds = sum(bool(x) for x in (a.goto, a.outcome, a.repeat, a.stay, a.hold_s))
        if kinds != 1:
            problems.append(f"{where}: needs exactly one of goto/outcome/repeat/stay/hold_s")
        if a.stay and not a.say:
            problems.append(f"{where}: 'stay' needs a say line")
        if a.hold_s is not None and not 1 <= a.hold_s <= pb.limits.hold_max_s:
            problems.append(f"{where}: hold_s must be 1..{pb.limits.hold_max_s} (hold_max_s)")
        for k in a.set:
            if k not in SETTABLE:
                problems.append(f"{where}: cannot set '{k}' (allowed: {sorted(SETTABLE)})")
        if a.commit and a.outcome != "BOOKED":
            problems.append(f"{where}: a commit action must end with outcome BOOKED")
        if a.outcome == "BOOKED" and not a.commit:
            problems.append(f"{where}: outcome BOOKED requires commit: true")
        if in_final and a.goto:
            problems.append(f"{where}: a final step only closes the call")
        said = {_ref(x) for x in a.say}
        if said & commit_lines and not a.commit:
            problems.append(f"{where}: the commit line may only be spoken by a commit action")
        if a.commit and not (said & commit_lines):
            problems.append(f"{where}: a commit action must speak the commit line")

    for sid, step in pb.steps.items():
        w = f"steps.{sid}"
        if not step.final and not step.ask:
            if sid != pb.start:
                problems.append(f"{w}: a step must ask something (or be final)")
            elif pb.disclosure in pb.lines and "?" not in pb.text(pb.disclosure):
                problems.append(
                    f"{w}: the start step may ask nothing only when the disclosure line itself "
                    "ends in a question (Friday then waits for the answer)"
                )
        for item in step.ask:
            need_line(f"{w}.ask", _ref(item))
            if isinstance(item, LineRef):
                problems.extend(_cond_problems(f"{w}.ask", item.when))
            if _ref(item) in commit_lines:
                problems.append(f"{w}.ask: the commit line cannot be an ask")
        problems.extend(_cond_problems(f"{w}.skip_when", step.skip_when))
        if step.skip_when and ANY not in step.branches:
            problems.append(f"{w}: skip_when needs an ANY branch (where to go when skipped)")
        if step.max_visits is not None and ANY not in step.branches:
            problems.append(f"{w}: max_visits needs an ANY branch (where to go when over it)")
        if step.final and ANY not in step.branches:
            problems.append(f"{w}: a final step needs an ANY branch (what it does on entry)")
        if not step.branches:
            problems.append(f"{w}: no branches")
        for intent, acts in step.branches.items():
            if intent != ANY and intent not in INTENTS:
                problems.append(
                    f"{w}.branches: unknown intent '{intent}' (closed set: {sorted(INTENTS)})"
                )
            lst = pb.actions(acts)
            for k, a in enumerate(lst):
                check_action(f"{w}.{intent}[{k}]", a, in_final=step.final)
            if isinstance(acts, list) and lst and lst[-1].when:
                problems.append(f"{w}.{intent}: the last alternative must have no 'when'")
        if any(a.commit for acts in step.branches.values() for a in pb.actions(acts)):
            if pb.commit_step != sid:
                problems.append(f"{w}: commit actions are only allowed in commit_step")
            if not step.final:
                problems.append(f"{w}: the commit step must be final")
    if pb.commit_step is not None and pb.commit_step not in pb.steps:
        problems.append(f"commit_step '{pb.commit_step}' does not exist")

    for intent, acts in pb.defaults.items():
        if intent not in INTENTS:
            problems.append(f"defaults: unknown intent '{intent}'")
        for k, a in enumerate(pb.actions(acts)):
            check_action(f"defaults.{intent}[{k}]", a, in_final=False)
            if a.commit:
                problems.append(f"defaults.{intent}: defaults cannot commit")
    for rid, lst in pb.routes.items():
        for k, a in enumerate(lst):
            check_action(f"routes.{rid}[{k}]", a, in_final=False, in_route=True)
        if lst and lst[-1].when:
            problems.append(f"routes.{rid}: the last alternative must have no 'when'")

    # ---- placeholders need a way to be filled
    # (lines using {price_inr} etc. are only valid where the engine can guarantee the value;
    #  the engine falls back to the confusion branch if a value is missing)

    # ---- reachability / unused
    if pb.start in pb.steps and not problems:
        reach = pb.reachable_steps()
        for sid in pb.steps:
            if sid not in reach:
                problems.append(f"step '{sid}' is unreachable from '{pb.start}'")
        used = pb.line_ids_used()
        pb.warnings = [f"line '{lid}' is never used" for lid in pb.lines if lid not in used]

    if problems:
        raise PlaybookError(problems, name)
    return pb


class _Loader(yaml.SafeLoader):
    """YAML 1.2 booleans: only true/false. (Plain YAML 1.1 turns the intent keys YES and NO
    into booleans, which would silently break a playbook.)"""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf")
)


def parse_text(text: str, *, suffix: str = ".yaml") -> dict[str, Any]:
    try:
        data = json.loads(text) if suffix == ".json" else yaml.load(text, Loader=_Loader)  # noqa: S506
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise PlaybookError([f"cannot parse file: {type(e).__name__}: {str(e)[:200]}"]) from None
    if not isinstance(data, dict):
        raise PlaybookError(["the file must contain a mapping at the top level"])
    return data


def load_playbook(path: str | Path) -> Playbook:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise PlaybookError([f"cannot read file: {e.strerror}"], p.name) from None
    try:
        pb = validate_data(parse_text(text, suffix=p.suffix.lower()), p.name)
    except PlaybookError as e:
        raise PlaybookError(e.problems, p.name) from None
    pb.source = str(p)
    return pb


def playbook_files(directory: Path | None = None) -> dict[str, Path]:
    d = directory or DATA_DIR
    out: dict[str, Path] = {}
    for p in sorted(d.glob("*")):
        if p.suffix.lower() in (".yaml", ".yml", ".json") and ".personas." not in p.name:
            out[p.name.split(".")[0]] = p
    return out


_CACHE: dict[str, Playbook] = {}


def get_playbook(name: str, directory: Path | None = None) -> Playbook:
    files = playbook_files(directory)
    if name not in files:
        raise PlaybookError([f"no playbook named '{name}' (have: {sorted(files)})"], name)
    key = f"{directory}:{name}:{files[name].stat().st_mtime_ns}"
    if key not in _CACHE:
        _CACHE[key] = load_playbook(files[name])
    return _CACHE[key]


def list_playbooks(directory: Path | None = None) -> list[tuple[str, str, str]]:
    """[(name, status, detail)] without raising: status is 'ok' or 'INVALID'."""
    out = []
    for name, path in playbook_files(directory).items():
        try:
            pb = load_playbook(path)
            out.append((name, "ok", f"v{pb.version}, {len(pb.steps)} steps, {len(pb.lines)} lines"))
        except PlaybookError as e:
            out.append((name, "INVALID", f"{len(e.problems)} problem(s)"))
    return out
