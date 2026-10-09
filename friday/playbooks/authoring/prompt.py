"""The authoring prompt: what the script-author model is told, and how its reply is read.

OFFLINE use only (``friday playbook draft --live``). The model drafts the playbook file and the
simulated businesses; the existing loader/validator and dry-run decide whether the draft is any
good. Nothing here is ever sent during a call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from friday.core.models import CallOutcome
from friday.playbooks.authoring.knowledge import BusinessType
from friday.playbooks.intents import CONDITIONS, INPUT_NAMES, INTENTS, PLACEHOLDERS, SETTABLE
from friday.playbooks.model import DATA_DIR

PLAYBOOK_MARK = "=== PLAYBOOK ==="
PERSONAS_MARK = "=== PERSONAS ==="
END_MARK = "=== END ==="

OUTPUT_FORMAT = f"""OUTPUT FORMAT (exactly this, nothing before or after):
{PLAYBOOK_MARK}
<the complete playbook YAML>
{PERSONAS_MARK}
<the complete personas YAML>
{END_MARK}
No markdown fences, no commentary outside YAML comments. Both files are complete files, never
diffs."""

RULES = """HARD RULES (the validator and the dry run enforce them; breaking one rejects the draft):
1. Hinglish in Roman script only (Hindi words written in English letters, mixed naturally with
   English words). No Devanagari. Never switch to pure Hindi or pure English.
2. The AI disclosure is spoken first (line named by `disclosure:`). It is SHORT, says Friday is
   "ek AI assistant", and ends with the identity question, exactly like the salon opening:
   "Hello, main Friday, ek AI assistant, baat kar rahi hoon. Kya meri baat {business_name} se ho
   rahi hai?". The start step S0 asks nothing and just waits for the answer.
3. Friday never says or implies that something is booked or confirmed, except the SINGLE line
   marked `commit: true`, which only the `final` commit step may speak, and only when the user
   delegated the decision and the code-level check passes. Every other line that mentions
   confirming says the opposite ("abhi kuch confirm nahi kiya", "approval ke baad call karti
   hoon"). Keep the salon's S7 structure for this.
4. Approval rule: Friday collects the slot and the price and says she will call back after the
   user approves. She never decides for the user, never agrees to an advance, a booking amount
   or any payment ("Advance main abhi nahi de sakti, ... se poochh kar bataungi").
5. No secrets: never the words OTP, PIN, CVV, card, password, Aadhaar, UPI, account number; never
   the user's phone number or address (callbacks are "isi number par"). If the other side asks
   for them, the line is the salon's `no_secrets` / `s6_no_number` pattern.
6. Short lines: one idea, at most about 25 words, never more than 240 characters. No filler
   words (umm, aah), no emojis, no exclamation-mark enthusiasm.
7. Voice: JARVIS-style. Calm, precise, polite, unhurried, respectful ("ji", "sir", "madam" from
   the honorific input). Never pushy, never apologising more than once.
8. Only the CLOSED vocabularies below. Do not invent an intent, a condition, a slot name, a
   settable key or an input. Unknown words make the file invalid.
9. The playbook `id` is exactly the business type id you are given. Keep the salon's overall
   structure (S0 identity, S1 two minutes, S2 availability, S3 price, S4 preference, S5 advance
   and policy, S6 callback, S7 final) unless the business type clearly needs another step, and
   keep the `defaults:` block (stop calling, rude, wrong number, busy, are-you-bot, hold, repeat,
   off-topic, secrets, customer phone) so every step handles them.
10. Handle the awkward things this business type is known for with the existing intents
   (hold, "call back later", "WhatsApp pe bhej do", "visit karke batayenge", token system,
   walk-in only, booking amount): every one must lead to a safe end or back to the question,
   never to an unhandled intent, never to an unscripted word."""

PERSONA_RULES = """PERSONAS (the simulated businesses for the dry run):
* 20 to 25 personas, each a realistic person who answers the phone at THIS business type.
* Replies are keyed by the playbook LINE ID Friday last spoke (so a persona keeps working when
  wording changes). `disclosure` is the identity question. `<line>@<previous line>` answers
  "Sorry, ek baar phir?". A list is used in order (the last item repeats). A reply may be a
  mapping {say, hold_s, then, hangup, silence}.
* Include the awkward ones: busy and call later, puts Friday on hold, holds and never returns
  (expect call_outcome hold_timeout), asks who is calling, asks "robot hai?", answers in pure
  Hindi (Devanagari is allowed for the BUSINESS, never for Friday), wrong number, rude then
  hangs up, asks not to be called again (stop_request: true, outcome REFUSED), asks for an OTP,
  asks for the customer's phone number, price over budget, wants an advance or booking amount,
  nothing free, noisy line, off-topic question, a delegated booking that fits (BOOKED) and a
  delegated booking over the ceiling (SLOT_OFFERED), plus the specific surprises listed for the
  business type.
* `expect: {outcome: <an outcome defined in your playbook>}`. Be honest: expect what a sensible
  script SHOULD do, not what is easy to pass."""


def _closed_sets() -> str:
    outcomes = sorted(o.value for o in CallOutcome)
    return (
        "CLOSED VOCABULARIES\n"
        f"* Intents (what the other side can say; `ANY` = everything not listed): "
        f"{' '.join(sorted(INTENTS))}\n"
        f"* Conditions for `when:` (prefix ! negates): {' '.join(sorted(CONDITIONS))}\n"
        f"* Placeholders in lines: {' '.join(sorted(PLACEHOLDERS))}\n"
        f"* Inputs: {' '.join(sorted(INPUT_NAMES))}\n"
        f"* `set:` keys: {' '.join(sorted(SETTABLE))}\n"
        f"* Outcome `call_outcome` values: {' '.join(outcomes)}. Only the outcome BOOKED (the "
        "delegated commit) may map to `success`; BOOKED needs `commit: true`.\n"
        "* An action has exactly one of goto / outcome / repeat / stay / hold_s. `stay` needs a "
        "`say`. A `final` step needs an ANY branch and only closes the call. Only the `start` "
        "step may have no `ask`."
    )


def _salon_example() -> tuple[str, str]:
    play = (DATA_DIR / "salon_booking.yaml").read_text(encoding="utf-8")
    pers = (DATA_DIR / "salon_booking.personas.yaml").read_text(encoding="utf-8")
    head, _, rest = pers.partition("personas:\n")
    items = re.split(r"(?m)^(?=  - id: )", rest)
    more = "  # ... (more personas in the real file)\n"
    excerpt = head + "personas:\n" + "".join(items[:12]) + more
    return play, excerpt


def system_prompt() -> str:
    play, pers = _salon_example()
    return "\n\n".join(
        [
            "You are the offline SCRIPT AUTHOR for Friday, an AI assistant that phones Indian "
            "businesses on behalf of a user. You write the fixed script (a 'playbook') for ONE "
            "new business type. During a live call no model writes Friday's words: she speaks "
            "only the lines you write, and a model only classifies what the other side said. "
            "So every line you write will be spoken exactly, to a real person, in Friday's voice.",
            RULES,
            _closed_sets(),
            PERSONA_RULES,
            "WORKED EXAMPLE 1: the complete, validated salon playbook (salon_booking.yaml). "
            "Follow its format and its safety patterns exactly.\n<salon_playbook>\n"
            + play
            + "\n</salon_playbook>",
            "WORKED EXAMPLE 2: the format of the personas file (salon_booking.personas.yaml, "
            "first personas only).\n<salon_personas>\n" + pers + "\n</salon_personas>",
            OUTPUT_FORMAT,
        ]
    )


def knowledge_block(bt: BusinessType) -> str:
    data = bt.model_dump(exclude={"template", "id"})
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)


def draft_prompt(bt: BusinessType) -> str:
    sel = bt.template.select
    return (
        f"Write the playbook for the business type `{bt.id}` ({bt.title}).\n"
        f"* `id: {bt.id}`; task types {', '.join(sel.task_types)}; suggested select categories "
        f"{', '.join(sel.categories)}; keywords {', '.join(sel.keywords)}.\n"
        f"* The default `service` input: {bt.template.service_default}. The business is usually "
        f"called a {bt.template.noun}.\n"
        "Here is what we know about how this kind of business answers the phone (treat as "
        "background; the script must work even when reality differs):\n"
        f"<business_type>\n{knowledge_block(bt)}</business_type>\n\n"
        "Produce the playbook and 20 to 25 personas in the required output format."
    )


def repair_prompt(problems: list[str], playbook_text: str, personas_text: str) -> str:
    listed = "\n".join(f"- {p}" for p in problems[:60])
    return (
        "The validator rejected your draft. Fix EVERY problem below and reply with the complete, "
        "corrected files in the required format.\n"
        f"<problems>\n{listed}\n</problems>\n"
        f"<your_playbook>\n{playbook_text}\n</your_playbook>\n"
        f"<your_personas>\n{personas_text}\n</your_personas>"
    )


def patch_prompt(failures: list[str], playbook_text: str, personas_text: str) -> str:
    listed = "\n\n".join(failures[:40])
    return (
        "The draft is valid. We ran it against the simulated businesses and some failed. Patch "
        "the weak spots and reply with the complete files in the required format.\n"
        "* Fix the PLAYBOOK (a line, a branch, a route) in preference to changing a persona.\n"
        "* Change a persona's expectation only if the expectation itself was unrealistic, and say "
        "why in a YAML comment next to it.\n"
        "* SAFETY VIOLATIONS cannot be waived or worked around: never delete or soften a persona "
        "to make one disappear. Fix the script so Friday never does it.\n"
        "* Do not weaken any hard rule.\n"
        f"<failures>\n{listed}\n</failures>\n"
        f"<your_playbook>\n{playbook_text}\n</your_playbook>\n"
        f"<your_personas>\n{personas_text}\n</your_personas>"
    )


def retry_format_prompt(error: str) -> str:
    return (
        f"Your last reply could not be read: {error}\n"
        f"Reply again with the complete files, using exactly the markers {PLAYBOOK_MARK}, "
        f"{PERSONAS_MARK} and {END_MARK}, each on its own line."
    )


# =============================================================================== reply parsing
class ReplyParseError(ValueError):
    pass


@dataclass
class ParsedReply:
    playbook: str
    personas: str | None


_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n```\s*$", re.S)


def _unfence(s: str) -> str:
    s = s.strip("\n")
    m = _FENCE.match(s.strip())
    return (m.group(1) if m else s).strip("\n") + "\n"


def parse_reply(text: str, *, personas_required: bool = True) -> ParsedReply:
    """Split a model reply into the two files. Raises ``ReplyParseError`` (retried once)."""
    if PLAYBOOK_MARK not in text:
        raise ReplyParseError(f"the marker {PLAYBOOK_MARK} is missing")
    after = text.split(PLAYBOOK_MARK, 1)[1]
    if PERSONAS_MARK in after:
        play, _, rest = after.partition(PERSONAS_MARK)
        pers: str | None = rest.split(END_MARK, 1)[0]
    else:
        play, pers = after.split(END_MARK, 1)[0], None
    play = _unfence(play)
    if not play.strip():
        raise ReplyParseError("the playbook block is empty")
    if pers is not None:
        pers = _unfence(pers)
        if not pers.strip():
            pers = None
    if pers is None and personas_required:
        raise ReplyParseError(f"the marker {PERSONAS_MARK} or the personas block is missing")
    return ParsedReply(play, pers)


def format_reply(playbook_text: str, personas_text: str) -> str:
    return f"{PLAYBOOK_MARK}\n{playbook_text}\n{PERSONAS_MARK}\n{personas_text}\n{END_MARK}\n"
