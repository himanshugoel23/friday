"""The reply composer: the chat-quality rules every chatbot message passes through.

Rules (docs/CHATBOT_ARCHITECTURE.md layer 7, enforced in code and covered by tests):

1. length caps: at most ``lines`` lines and ``chars`` characters per message (3 lines / 300 chars
   normally; the first-contact intro may be longer because it must say who Friday is, what she does
   and what she never does);
2. one question per message (at most one ``?``);
3. button counts and titles: at most 3 reply buttons, titles at most 20 characters, no empty or
   duplicate titles; a list message has at most 10 rows (title <= 24, description <= 72, opening
   label <= 20) and never carries reply buttons as well;
4. no line twice in a row: no repeated line inside a message, and a message identical to the one
   Friday sent just before is not sent again (a shorter alternative is sent instead, else nothing);
5. language mirroring (:func:`detect_language`, :func:`mirror_language`): Hinglish by default, the
   user's own language when it is clear;
6. a "why" clause on every proactive message, and the plain statement (assistant, never payments /
   OTP / PIN / card numbers, own data only, delete anytime) on the intro, on proactive text and on
   the message that closes onboarding.

``Composer.check`` returns the problems, ``Composer.compose`` returns a :class:`Composed` message
or ``None`` (a suppressed repeat). With ``strict`` a problem raises :class:`RuleViolation` (tests);
otherwise it is logged by rule name only and the message is repaired as far as possible (never
drops what the user must read).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from friday.core.logging import get_logger
from friday.core.models import ListMenu, ListRow, ReplyButton

log = get_logger(__name__)

MAX_BUTTONS = 3
MAX_BUTTON_TITLE = 20
MAX_LIST_ROWS = 10
MAX_ROW_TITLE = 24
MAX_ROW_DESCRIPTION = 72
MAX_LIST_LABEL = 20

# kind -> (max lines, max characters)
LIMITS: dict[str, tuple[int, int]] = {
    "default": (3, 300),
    "intro": (7, 600),  # first contact and the consent details
    "disclosure": (4, 360),  # closes onboarding: must restate the "never" list
    "proactive": (4, 400),  # a message Friday starts: reason + how to stop
    "assist": (5, 520),  # proactive intents / honest capability replies (may carry a connect link)
    "list": (14, 1100),  # "what do you remember": one line per item, a list not a sentence
    "internal": (5, 600),  # to the founder's support inbox (not shown to the user)
}
# kinds that must state plainly: assistant, never payments/OTP/PIN/cards, own data, delete anytime
STATEMENT_KINDS = frozenset({"intro", "disclosure", "proactive"})
PROACTIVE_KINDS = frozenset({"proactive"})

_ASSISTANT = re.compile(r"assistant|असिस्टेंट", re.I)
_NEVER = (
    re.compile(r"payment|पेमेंट", re.I),
    re.compile(r"otp|ओटीपी", re.I),
    re.compile(r"\bpin\b|पिन", re.I),
)
_OWN_DATA = re.compile(r"apna|own|अपना|आपका|aapka", re.I)
_DELETE = re.compile(r"delete|डिलीट|मिटा|mita", re.I)
_QUESTION = re.compile(r"[?？]")


class RuleViolation(ValueError):
    """A chat-quality rule was broken (``rule`` names it)."""

    def __init__(self, rule: str, detail: str = "") -> None:
        super().__init__(f"{rule}: {detail}" if detail else rule)
        self.rule = rule


@dataclass
class Composed:
    text: str
    buttons: list[ReplyButton] = field(default_factory=list)
    list_menu: ListMenu | None = None
    kind: str = "default"
    lang: str = "hinglish"

    @property
    def digest(self) -> str:
        return digest_of(self.text, self.buttons, self.list_menu)


def digest_of(text: str, buttons: Sequence[ReplyButton], menu: ListMenu | None = None) -> str:
    raw = text + "|" + "|".join(b.title for b in buttons)
    if menu is not None:
        raw += "|" + menu.button + "|" + "|".join(r.title for r in menu.rows)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------- language mirroring
def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN_WORD = re.compile(r"[a-zA-Z']+")
HINGLISH_WORDS = _words(
    "hai hain hoon ho tha thi the kya kyun kyu kaise kaun kab kahan nahi nahin nhi haan han "
    "ha ji mera meri mere mujhe mujhko main mai hum aap aapka aapki tum tumhara tera teri ko "
    "ka ki ke se mein me par pe aur ya lekin toh to bhi abhi kal aaj subah shaam raat karo "
    "kar kardo karna karni batao bata bol bolo chahiye chahta chahti dena do de dijiye lena "
    "lo le ghar kaam paisa paise accha achha theek thik bhai bhaiya didi mummy papa namaste "
    "shukriya dhanyavad baat baad pehle phir sab kuch koi kisi isse usse yeh ye woh wo wahan "
    "yahan bahut thoda zyada kam jaldi dobara wapas ruko chalo chalu band"
)
ENGLISH_WORDS = _words(
    "the is are am was were be been i you he she it we they my your his her our their this "
    "that these those a an and or but if then so of to in on at for with from by about what "
    "when where who whom why how can could would should will shall may might do does did have "
    "has had not no yes please thanks thank hello help want need call tell me us show give "
    "get make send book remind reminder today tomorrow tonight morning evening card bill pay "
    "time day week my"
)
_GREETINGS = _words("hi hii hiii hello hey hlo helo namaste namaskar ok okay yo sup")


def detect_language(text: str | None) -> str | None:
    """ "hi" (Devanagari), "hinglish", "en", or None when the text says nothing about it
    (a bare "hi", a number, an emoji)."""
    if not text:
        return None
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return None
    deva = len(_DEVANAGARI.findall(text))
    if deva and deva / len(letters) >= 0.3:
        return "hi"
    words = [w.lower().strip("'") for w in _LATIN_WORD.findall(text)]
    words = [w for w in words if w and w not in _GREETINGS]
    if not words:
        return None
    hing = sum(1 for w in words if w in HINGLISH_WORDS)
    eng = sum(1 for w in words if w in ENGLISH_WORDS)
    if hing and hing >= eng:
        return "hinglish"
    if eng and len(words) >= 2 and eng * 2 >= len(words):
        return "en"
    return None


def mirror_language(user_text: str | None, current: str = "hinglish") -> str:
    """The language to answer in: the one the user's message is written in when that is clear,
    otherwise ``current`` (Hinglish by default)."""
    return detect_language(user_text) or current


# ---------------------------------------------------------------------- statement checks
def has_statement(text: str) -> list[str]:
    """What is missing from the plain statement (empty list == complete)."""
    missing: list[str] = []
    if not _ASSISTANT.search(text):
        missing.append("assistant")
    if not all(p.search(text) for p in _NEVER):
        missing.append("never (payment, OTP, PIN)")
    return missing


def has_full_statement(text: str) -> list[str]:
    """The intro must also say: only the user's own data, delete anytime."""
    missing = has_statement(text)
    if not _OWN_DATA.search(text):
        missing.append("own data")
    if not _DELETE.search(text):
        missing.append("delete anytime")
    return missing


# ---------------------------------------------------------------------- the composer
def _lines(text: str) -> list[str]:
    return [ln for ln in text.split("\n") if ln.strip()]


class Composer:
    def __init__(self, *, strict: bool = False) -> None:
        self.strict = strict

    # ------------------------------------------------------------------ checks
    def check(
        self,
        text: str,
        buttons: Sequence[ReplyButton] = (),
        list_menu: ListMenu | None = None,
        *,
        kind: str = "default",
        why: str | None = None,
    ) -> list[str]:
        """Every rule this message breaks, as ``rule: detail`` strings (empty == fine)."""
        problems: list[str] = []
        max_lines, max_chars = LIMITS.get(kind, LIMITS["default"])
        lines = _lines(text)
        if not text.strip():
            problems.append("empty: no text")
        if len(lines) > max_lines:
            problems.append(f"lines: {len(lines)} > {max_lines}")
        if len(text) > max_chars:
            problems.append(f"chars: {len(text)} > {max_chars}")
        if len(_QUESTION.findall(text)) > 1:
            problems.append("one_question: more than one question")
        seen: set[str] = set()
        for ln in lines:
            key = ln.strip().lower()
            if key in seen:
                problems.append(f"repeat: line repeated: {ln.strip()[:30]}")
                break
            seen.add(key)
        titles = [b.title for b in buttons]
        if len(buttons) > MAX_BUTTONS:
            problems.append(f"buttons: {len(buttons)} > {MAX_BUTTONS}")
        if any(not t.strip() for t in titles):
            problems.append("buttons: empty title")
        if any(len(t) > MAX_BUTTON_TITLE for t in titles):
            problems.append(f"buttons: title longer than {MAX_BUTTON_TITLE}")
        if len({t.lower() for t in titles}) != len(titles):
            problems.append("buttons: duplicate title")
        if list_menu is not None:
            if buttons:
                problems.append("list: a list message cannot also carry reply buttons")
            if len(list_menu.rows) > MAX_LIST_ROWS:
                problems.append(f"list: {len(list_menu.rows)} rows > {MAX_LIST_ROWS}")
            if len(list_menu.button) > MAX_LIST_LABEL:
                problems.append(f"list: label longer than {MAX_LIST_LABEL}")
            for r in list_menu.rows:
                if len(r.title) > MAX_ROW_TITLE:
                    problems.append(f"list: row title longer than {MAX_ROW_TITLE}")
                if r.description and len(r.description) > MAX_ROW_DESCRIPTION:
                    problems.append(f"list: row description longer than {MAX_ROW_DESCRIPTION}")
        if kind in STATEMENT_KINDS:
            check = has_full_statement if kind == "intro" else has_statement
            if missing := check(text):
                problems.append("statement: missing " + ", ".join(missing))
        if kind in PROACTIVE_KINDS and not (why and why.strip() and why.strip() in text):
            problems.append("why: a proactive message needs its reason")
        return problems

    # ------------------------------------------------------------------ compose
    def compose(
        self,
        text: str,
        *,
        buttons: Sequence[ReplyButton] = (),
        list_menu: ListMenu | None = None,
        kind: str = "default",
        lang: str = "hinglish",
        last_digest: str | None = None,
        alt: str | None = None,
        why: str | None = None,
        footer: str | None = None,
    ) -> Composed | None:
        """Apply the rules. ``last_digest`` is the digest of the message sent just before; an
        identical one is replaced by ``alt`` (a shorter re-prompt) or dropped. ``why`` is appended
        to a proactive message that does not carry it yet; ``footer`` is an optional one-line
        statement appended to an onboarding step (Settings.chatbot_disclosure_every_step)."""
        text = self._clean(text)
        btns = list(buttons)
        if kind in PROACTIVE_KINDS and why and why.strip() not in text:
            text = f"{text}\n{why.strip()}"
        if footer and footer not in text:
            text = f"{text}\n{footer}"
        comp = Composed(text, btns, list_menu, kind, lang)
        if last_digest is not None and comp.digest == last_digest:
            if alt is None:
                return None
            kind = "default"  # a short re-prompt: the full statement was already made
            comp = Composed(self._clean(alt), btns, list_menu, kind, lang)
            if comp.digest == last_digest:
                return None
        problems = self.check(comp.text, comp.buttons, comp.list_menu, kind=kind, why=why)
        if problems:
            if self.strict:
                raise RuleViolation(problems[0].split(":", 1)[0], "; ".join(problems))
            for rule in sorted({p.split(":", 1)[0] for p in problems}):
                log.warning("chatbot message broke rule %s (kind=%s)", rule, kind)
            comp = self._repair(comp)
        return comp

    @staticmethod
    def _clean(text: str) -> str:
        lines = [" ".join(ln.split()) for ln in text.strip().split("\n")]
        out: list[str] = []
        for ln in lines:
            if ln and (not out or out[-1].lower() != ln.lower()):
                out.append(ln)  # a line is never repeated twice in a row
        return "\n".join(out)

    @staticmethod
    def _repair(comp: Composed) -> Composed:
        """Best-effort fix in production: never lose the reply, never send an invalid payload."""
        buttons = [
            ReplyButton(id=b.id, title=_clip(b.title, MAX_BUTTON_TITLE)) for b in comp.buttons
        ][:MAX_BUTTONS]
        menu = comp.list_menu
        if menu is not None:
            buttons = []
            menu = ListMenu(
                button=_clip(menu.button, MAX_LIST_LABEL),
                section=menu.section,
                rows=[
                    ListRow(
                        id=r.id,
                        title=_clip(r.title, MAX_ROW_TITLE),
                        description=_clip(r.description, MAX_ROW_DESCRIPTION)
                        if r.description
                        else None,
                    )
                    for r in menu.rows[:MAX_LIST_ROWS]
                ],
            )
        max_lines, max_chars = LIMITS.get(comp.kind, LIMITS["default"])
        text = "\n".join(_lines(comp.text)[:max_lines])
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return Composed(text, buttons, menu, comp.kind, comp.lang)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def buttons_for(*pairs: tuple[str, str]) -> list[ReplyButton]:
    """``buttons_for(("cb:skip", "Skip"))`` -> reply buttons."""
    return [ReplyButton(id=i, title=t) for i, t in pairs]
