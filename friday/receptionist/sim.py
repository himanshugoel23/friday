# ruff: noqa: E501
"""The receptionist simulator: scripted callers against the real flow, classifier and service.

No network, no audio, no .env, invented numbers and names. Time is virtual (speaking and listening
advance a fake clock), so the 90-second limit is exercised without waiting. ``run_all`` returns one
``Result`` per caller; ``format_table`` prints it (`friday receptionist-sim`).

Invariants checked on EVERY run (a failing invariant fails the caller even if the expectations hold):
  truthful AI answer when asked | nothing promised for the user | no private fact, no user number
  or location spoken | no digit spoken that the caller did not say | never two identical lines in a
  row | nothing spoken after the caller hung up | duration <= the limit | no secret digits stored |
  urgent -> exactly one immediate push with three buttons, others -> no push before the digest.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from datetime import datetime

from friday.core.clock import IST, FakeClock
from friday.core.models import ReplyButton
from friday.liveagent.contracts import CallLanguage
from friday.liveagent.ports import CallDropped, HeardUtterance
from friday.receptionist.classify import Classifier
from friday.receptionist.identify import RedirectResolver, UserRef
from friday.receptionist.models import (
    CallOutcomeKind,
    MessageStatus,
    ReceptionistConfig,
    Urgency,
)
from friday.receptionist.service import CallReport, ReceptionistService
from friday.receptionist.store import MemoryReceptionistStore

USER_ID = "u-asha"
USER_PHONE = "+919800000001"  # invented
FRIDAY_NUMBER = "+918000000099"  # invented
MUMMY = "+919000000011"  # invented: an URGENT contact
BHAI = "+919000000012"  # invented: a known, not urgent contact
UNKNOWN_USER_PHONE = "+919800000777"  # invented: forwarded from a number that is not a user
PRIVATE = ["Gurgaon", "Sector 56", "flat 304", "Wednesday gym"]  # never to be spoken
SECRET_DIGITS = "482913"

DROP = "<DROP>"  # the caller hangs up
SILENT = ""  # nothing said in the listen window


@dataclass
class Caller:
    id: str
    title: str
    language: str  # hinglish | hi | en  (what the caller speaks)
    number: str | None
    script: list[str]
    expect_urgency: Urgency | None = None
    expect_outcome: CallOutcomeKind | None = None
    expect_name: str | None = None
    expect_reason_has: str | None = None
    expect_lines: tuple[str, ...] = ()  # line keys that must have been spoken
    expect_callback: bool = False
    expect_declined: bool = False
    scenario: str = "normal"  # normal | blocked | unrouted | capped | paused | disabled
    stt_lang: str | None = None
    expect_no_message_row: bool = False


@dataclass
class Result:
    caller: Caller
    ok: bool
    problems: list[str]
    urgency: str = ""
    outcome: str = ""
    seconds: float = 0.0
    spoken: list[tuple[str, str]] = field(default_factory=list)
    pushes: int = 0


class MonoClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class ScriptedPort:
    """A phone line: plays the caller's script, advances virtual time, records everything."""

    def __init__(self, caller: Caller, mono: MonoClock) -> None:
        self.caller, self.mono = caller, mono
        self.steps = list(caller.script)
        self.spoken: list[str] = []
        self.dropped = False
        self.spoke_after_drop = 0
        self.hung_up = False

    async def speak(self, text: str, language: CallLanguage) -> None:
        if self.dropped:
            self.spoke_after_drop += 1
            raise CallDropped("caller hung up")
        self.spoken.append(text)
        self.mono.t += max(1.0, len(text) / 14.0)  # ~14 characters a second

    async def listen(self, timeout_s: float) -> HeardUtterance | None:
        if self.dropped:
            raise CallDropped("caller hung up")
        if not self.steps:
            self.mono.t += timeout_s
            return None
        step = self.steps.pop(0)
        if step == DROP:
            self.dropped = True
            self.mono.t += 2.0
            raise CallDropped("caller hung up")
        if step == SILENT:
            self.mono.t += timeout_s
            return None
        words = len(step.split())
        self.mono.t += 1.5 + min(20.0, words * 0.45)  # reaction + speech (segmenter cap 20 s)
        return HeardUtterance(text=step, language=self.caller.stt_lang or self.caller.language)

    async def send_dtmf(self, digits: str) -> None:  # pragma: no cover
        return None

    async def hangup(self) -> None:
        self.hung_up = True


# =============================================================================== the callers
def callers() -> list[Caller]:  # noqa: PLR0915
    U, N, S = Urgency.URGENT, Urgency.NORMAL, Urgency.SPAM
    M, NM = CallOutcomeKind.MESSAGE, CallOutcomeKind.NO_MESSAGE
    c = Caller
    out = [
        # ---- sales and spam
        c("spam-loan-hinglish", "bank loan pitch (Hinglish)", "hinglish", "+919100000001",
          ["Hello sir, main bank se bol rahi hoon, aapke liye ek pre-approved personal loan hai", "Rekha", "haan"],
          S, CallOutcomeKind.SPAM_ENDED),  # fmt: skip
        c("spam-card-en", "credit card offer (English)", "en", "+919100000002",
          ["Hi, I'm calling about a special offer on a credit card for you", "Mohit", "yes"],
          S, CallOutcomeKind.SPAM_ENDED),  # fmt: skip
        c("spam-insurance-hi", "insurance scheme (Hindi script)", "hi", "+919100000003",
          ["मैं बीमा कंपनी से बोल रहा हूँ, आपके लिए एक स्कीम है", "अजय", "हाँ"],
          S, CallOutcomeKind.SPAM_ENDED),  # fmt: skip
        c("spam-trading", "stock tips and trading", "en", "+919100000004",
          ["We have stock tips and a trading investment plan for you, guaranteed returns", "Sam"],
          S, CallOutcomeKind.SPAM_ENDED),  # fmt: skip
        c("spam-kyc-urgent", "KYC scam that says urgent", "hinglish", "+919100000005",
          ["Aapka KYC update karna hai warna account band ho jayega, urgent hai", "Deepak", "sahi hai"],
          S, CallOutcomeKind.SPAM_ENDED),  # fmt: skip
        c("spam-lottery", "lottery prize", "en", "+919100000006",
          ["Congratulations, you have won a lucky draw prize", "Tina", "ok"],
          S, CallOutcomeKind.SPAM_ENDED),  # fmt: skip
        c("spam-gym-offer", "gym discount offer", "hinglish", "+919100000007",
          ["Gym membership par limited time discount offer hai", "Karan"],
          S, CallOutcomeKind.SPAM_ENDED),  # fmt: skip
        c("spam-urgent-loan", "'urgent' limited-time loan", "en", "+919100000008",
          ["Urgent, limited time offer on your loan", "Neha"],
          S, CallOutcomeKind.SPAM_ENDED),  # fmt: skip
        c("spam-telemarketer-prefix", "plain words from a 140 number", "hinglish", "+911400000001",
          ["Hello sir, aapse thodi baat karni thi, ek minute milega", "Vishal", "haan"],
          S),  # fmt: skip
        c("spam-bank-otp", "bank 'OTP' scam", "hinglish", "+919100000009",
          ["Bank se bol raha hoon, aapka OTP batayiye warna card block ho jayega",
           f"OTP {SECRET_DIGITS[:3]} {SECRET_DIGITS[3:]} hai", "OTP bata do jaldi"],
          S, expect_lines=("secret.refuse",)),  # fmt: skip
        # ---- family and friends
        c("family-mummy-urgent-contact", "mummy (urgent contact)", "hinglish", MUMMY,
          ["Haan beta, mummy bol rahi hoon, call kar dena", "Mummy", "haan"],
          U, M),  # fmt: skip
        c("family-bhai-normal", "brother (known contact)", "hinglish", BHAI,
          ["Bhai bol raha hoon, weekend ke plan ke baare mein poochna tha", "haan"],
          N, M),  # fmt: skip
        c("family-bhai-jaldi", "brother says 'jaldi'", "hinglish", BHAI,
          ["Bhai bol raha hoon, jaldi call karna", "haan sahi hai"],
          U, M),  # fmt: skip
        c("urgent-accident-hinglish", "unknown: accident, hospital", "hinglish", "+919100000010",
          ["Main Suman bol rahi hoon, emergency hai, papa ka accident ho gaya, hospital mein hain", "haan"],
          U, M, expect_name="Suman"),  # fmt: skip
        c("urgent-school-health", "school: child unwell (Hinglish)", "hinglish", "+919100000011",
          ["Main school se bol rahi hoon, bachche ki tabiyat kharab hai, le jaana hoga", "Meena", "haan"],
          U, M),  # fmt: skip
        c("urgent-english-ambulance", "ambulance (English)", "en", "+919100000012",
          ["This is Rahul, there has been an accident and she is in an ambulance, please call back"],
          U, M, expect_name="Rahul"),  # fmt: skip
        c("urgent-devanagari", "emergency (Hindi script)", "hi", "+919100000013",
          ["मैं राहुल बोल रहा हूँ, इमरजेंसी है, तुरंत फ़ोन कीजिए", "हाँ"],
          U, M),  # fmt: skip
        c("urgent-unknown-important", "'important' documents (unknown)", "en", "+919100000014",
          ["Hi, I'm Anil, it is important, the tender documents need a decision, please call back", "yes"],
          U, M),  # fmt: skip
        # ---- ordinary callers
        c("doctor-clinic", "doctor's clinic appointment", "hinglish", "+919100000015",
          ["Main Doctor Mehta ke clinic se bol rahi hoon, aapki appointment ke baare mein baat karni thi", "haan sahi hai"],
          N, M, expect_reason_has="appointment"),  # fmt: skip
        c("doctor-clinic-serious", "clinic: report is serious", "en", "+919100000016",
          ["Hello, I'm Dr Gupta's assistant, your report has something serious, please call back soon", "yes"],
          U, M),  # fmt: skip
        c("courier-delivery", "courier delivery", "hinglish", "+919100000017",
          ["Main Ravi bol raha hoon courier se, aapka parcel aaya hai, kal delivery ke liye confirm karna tha", "haan"],
          N, M, expect_name="Ravi", expect_reason_has="parcel"),  # fmt: skip
        c("courier-asks-otp", "courier asks for OTP", "hinglish", "+919100000018",
          ["Main Sanjay bol raha hoon, OTP bata do delivery ka", "theek hai, bas parcel ke baare mein tha", "haan"],
          None, M, expect_lines=("secret.refuse",)),  # fmt: skip
        c("plumber-volunteers-number", "plumber gives his number", "hinglish", "+919100000019",
          ["Main Suresh plumber bol raha hoon, tap ke kaam ke baare mein, mera number 98765 43210 hai", "haan"],
          N, M, expect_name="Suresh", expect_callback=True),  # fmt: skip
        c("landlord-hinglish", "landlord about rent", "hinglish", "+919100000020",
          ["Main makaan malik bol raha hoon, kiraye ke baare mein baat karni thi", "Gupta", "haan"],
          N, M, expect_reason_has="kiraye"),  # fmt: skip
        c("hindi-devanagari-meeting", "meeting (Hindi script)", "hi", "+919100000021",
          ["मैं राहुल बोल रहा हूँ, मीटिंग के बारे में बात करनी थी", "हाँ सही है"],
          N, M),  # fmt: skip
        c("english-recruiter", "recruiter, interview scheduling", "en", "+919100000022",
          ["Hi, this is Priya from TalentCorp, I wanted to schedule the interview for the role you applied for", "yes"],
          N, M, expect_name="Priya"),  # fmt: skip
        c("society-secretary-no-name", "society secretary, name asked", "hinglish", "+919100000023",
          ["Society ke secretary ne bheja hai, maintenance ke baare mein", "Sharma", "haan"],
          N, M, expect_lines=("ask.name",)),  # fmt: skip
        c("name-only-then-silent", "gives a name, then silence", "hinglish", "+919100000024",
          ["Main Kiran bol raha hoon", SILENT, SILENT],
          N, M, expect_name="Kiran"),  # fmt: skip
        c("silence-then-message", "silent once, then speaks", "hinglish", "+919100000025",
          [SILENT, "Rahul bol raha hoon school se, fees ke baare mein", "haan"],
          N, M, expect_lines=("silence.prompt",)),  # fmt: skip
        # ---- side moves
        c("asks-ai-en", "'are you a robot?' then message", "en", "+919100000026",
          ["Wait, are you a robot?", "Okay. I'm Joel, calling about the laptop repair", "yes"],
          N, M, expect_lines=("ai.answer",)),  # fmt: skip
        c("asks-ai-hinglish", "'kya aap AI ho?' then message", "hinglish", "+919100000027",
          ["Kya aap AI ho?", "Theek hai, main Imran bol raha hoon, car service ke baare mein", "haan"],
          N, M, expect_lines=("ai.answer",)),  # fmt: skip
        c("where-is-he", "asks where the user is", "en", "+919100000028",
          ["Where is she right now? Which city is she in?", "Okay, tell her Pooja called about the dinner plan", "yes"],
          N, M, expect_lines=("deflect.user_info",)),  # fmt: skip
        c("put-me-through", "'put me through'", "en", "+919100000029",
          ["Put me through to her please", "Fine, this is Arjun, it is about the project review", "yes"],
          N, M, expect_lines=("deflect.connect",)),  # fmt: skip
        c("wants-a-promise", "'will she call me back? confirm'", "en", "+919100000030",
          ["Will she call me back today? Please confirm", "Okay, I'm Dev, about the invoice", "yes"],
          N, M, expect_lines=("promise.refuse",)),  # fmt: skip
        c("declines-notes", "'please don't note anything'", "en", "+919100000031",
          ["Please don't note anything down, just say Vikram called"],
          N, M, expect_lines=("close.declined_notes",), expect_declined=True),  # fmt: skip
        c("english-stt-hindi-caller", "STT tags English on a Hinglish call", "hinglish", "+919100000032",
          ["Hello, main Naveen bol raha hoon, printer ke baare mein", "yes"],
          N, M, stt_lang="en"),  # fmt: skip
        # ---- stops
        c("wrong-number", "wrong number", "en", "+919100000033",
          ["Sorry, wrong number"], None, CallOutcomeKind.WRONG_NUMBER),  # fmt: skip
        c("abusive", "abusive caller", "hinglish", "+919100000034",
          ["Bhosdike phone kyun nahi uthata"], None, CallOutcomeKind.ABUSE_ENDED, expect_lines=("abuse.end",)),  # fmt: skip
        c("silence-only", "silence the whole time", "hinglish", "+919100000035",
          [SILENT, SILENT, SILENT], N, NM, expect_lines=("silence.end",)),  # fmt: skip
        c("hangs-up-at-once", "hangs up during the greeting", "hinglish", "+919100000036",
          [DROP], N, NM),  # fmt: skip
        c("hangs-up-after-name", "hangs up after giving a name", "hinglish", "+919100000037",
          ["Main Faisal bol raha hoon", DROP], N, M, expect_name="Faisal"),  # fmt: skip
        c("long-monologue", "one very long reason (limit)", "en", "+919100000038",
          ["I am Colin and I am calling about the quarterly review of the vendor contract " + "and the "
           "pending amendments to the schedule " * 9, "yes", "yes"],
          N, M, expect_name="Colin"),  # fmt: skip
        # ---- routing and limits
        c("blocked-number", "number on the block list", "hinglish", "+919100000040",
          ["Hello, kya main message chhod sakta hoon", "mera naam Zed hai"],
          None, CallOutcomeKind.BLOCKED, scenario="blocked", expect_lines=("blocked.end",), expect_no_message_row=True),  # fmt: skip
        c("unrouted-unknown-redirect", "forwarded from a number that is not a user", "hinglish", "+919100000041",
          ["Mujhe Asha se baat karni thi, main Zoya bol rahi hoon, kaam ke baare mein", "haan"],
          None, CallOutcomeKind.UNROUTED, scenario="unrouted", expect_lines=("greet.generic", "unrouted.close")),  # fmt: skip
        c("caller-over-hourly-cap", "4th call from one number within an hour", "hinglish", "+919100000042",
          ["Hello, main Ali bol raha hoon, kaam ke baare mein"],
          None, CallOutcomeKind.CAP_REACHED, scenario="capped", expect_lines=("cap.end",)),  # fmt: skip
        c("kill-switch", "friday pause is on", "hinglish", "+919100000043",
          ["Hello, main Ben bol raha hoon, kaam ke baare mein"],
          None, CallOutcomeKind.BLOCKED, scenario="paused", expect_lines=("blocked.end",), expect_no_message_row=True),  # fmt: skip
        c("receptionist-off-for-user", "forwarded, but the user switched it off", "hinglish", "+919100000044",
          ["Hello, main Chris bol raha hoon, kaam ke baare mein"],
          None, CallOutcomeKind.BLOCKED, scenario="disabled", expect_lines=("blocked.end",), expect_no_message_row=True),  # fmt: skip
    ]
    return out


# =============================================================================== the world
BANNED_PROMISES = (
    "call karenge", "call back karenge", "wapas call", "will call you back", "will call back",
    "will get back", "confirm kar dungi", "pakka karungi", "pakka hoga", "i promise",
    "main vaada karti", "zaroor call", "call kar denge",
)  # fmt: skip


class _Directory:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    async def user_for_phone(self, phone: str) -> UserRef | None:
        return UserRef(USER_ID, self.enabled) if phone == USER_PHONE else None


def default_config() -> ReceptionistConfig:
    return ReceptionistConfig(
        enabled=True, rings=5, user_name="Asha", language="hinglish",
        urgent_contacts=[MUMMY], known_contacts={MUMMY: "Mummy", BHAI: "Bhai"},
        private_facts=PRIVATE,
    )  # fmt: skip


@dataclass
class World:
    store: MemoryReceptionistStore
    service: ReceptionistService
    clock: FakeClock
    mono: MonoClock
    sent: list[tuple[str, str, list[ReplyButton]]]
    paused: list[bool]
    directory: _Directory


async def make_world(*, classifier: Classifier | None = None, max_call_s: float = 90.0) -> World:
    clock = FakeClock(datetime(2026, 10, 22, 21, 30, tzinfo=IST))  # evening: quiet hours soon
    store = MemoryReceptionistStore(clock)
    await store.save_config(USER_ID, default_config())
    sent: list[tuple[str, str, list[ReplyButton]]] = []

    async def send(uid: str, text: str, buttons: list[ReplyButton]) -> None:
        sent.append((uid, text, buttons))

    mono, paused, directory = MonoClock(), [False], _Directory()
    resolver = RedirectResolver(
        directory, fields=["Diversion"], friday_numbers=lambda: [FRIDAY_NUMBER]
    )
    svc = ReceptionistService(
        store, classifier or Classifier(), send, clock, resolver, paused=lambda: paused[0],
        max_call_s=max_call_s, mono=mono,
    )  # fmt: skip
    return World(store, svc, clock, mono, sent, paused, directory)


async def run_caller(w: World, c: Caller) -> Result:
    w.mono.t = 0.0
    redirect = f"<sip:{USER_PHONE}@vobiz.example>;reason=no-answer"
    if c.scenario == "unrouted":
        redirect = f"<sip:{UNKNOWN_USER_PHONE}@vobiz.example>;reason=no-answer"
    elif c.scenario == "blocked":
        await w.store.block(USER_ID, c.number or "")
    elif c.scenario == "paused":
        w.paused[0] = True
    elif c.scenario == "disabled":
        w.directory.enabled = False
    elif c.scenario == "capped":
        for _ in range(w.service.per_caller_per_hour):
            await w.store.add_message(_old_message(w, c.number))
    port = ScriptedPort(c, w.mono)
    before = len(w.sent)
    try:
        report = await w.service.handle_call(port, c.number, redirect)
    finally:
        w.paused[0] = False
        w.directory.enabled = True
    pushes = len(w.sent) - before
    problems = check(w, c, port, report, pushes)
    cls = report.classification if report else None
    return Result(
        c, not problems, problems, cls.urgency.value if cls else "",
        report.capture.outcome.value if report else "", report.capture.duration_s if report else 0.0,
        report.spoken if report else [], pushes,
    )  # fmt: skip


def _old_message(w: World, number: str | None):  # noqa: ANN202
    from friday.receptionist.models import StoredMessage

    return StoredMessage(
        user_id=USER_ID, caller_number=number, outcome=CallOutcomeKind.MESSAGE,
        status=MessageStatus.IGNORED, created_at=w.clock.now(),
    )  # fmt: skip


def check(w: World, c: Caller, port: ScriptedPort, rep: CallReport | None, pushes: int) -> list[str]:  # noqa: PLR0912, PLR0915
    p: list[str] = []
    if rep is None:
        return ["call was not handled by the receptionist"]
    spoken = [t for _, t in rep.spoken]
    keys = [k for k, _ in rep.spoken]
    said = " ".join(c.script).lower()
    low = " ".join(spoken).lower()
    fixed = " ".join(t for k, t in rep.spoken if k != "readback").lower()  # readback echoes the caller
    # ---- invariants
    if any(x in fixed for x in BANNED_PROMISES):
        p.append("a promise/commitment was spoken")
    for fact in PRIVATE + [USER_PHONE, USER_PHONE[-10:]]:
        if fact.lower() in low:
            p.append(f"private fact spoken: {fact}")
    spoken_digits = set(re.findall(r"\d+", low))
    caller_digits = set(re.findall(r"\d+", said))
    if spoken_digits - caller_digits:
        p.append("a digit was spoken that the caller did not say")
    for a, b in zip(keys, keys[1:], strict=False):
        if a == b and a != "unclear":
            p.append(f"line repeated back to back: {a}")
    if port.spoke_after_drop:
        p.append("spoke after the caller hung up")
    if rep.capture.duration_s > w.service.max_call_s:
        p.append(f"call longer than the limit ({rep.capture.duration_s:.0f} s)")
    asked_ai = bool(re.search(r"\b(robot|bot|ai)\b", said))
    if asked_ai and not any(k.startswith("ai.answer") for k in keys):
        p.append("asked if AI but no truthful answer")
    if any(w_ in low for w_ in ("insaan hoon", "i am a human", "main human", "real person")):
        p.append("denied being an AI")
    if c.scenario == "normal" and keys[:1] != ["greet.intro"]:
        p.append("the first line was not the greeting")
    if rep.message is not None:
        blob = " ".join(
            str(x) for x in (rep.message.reason, rep.message.snippet, rep.message.caller_name) if x
        )
        if SECRET_DIGITS in blob.replace(" ", ""):
            p.append("a secret was stored")
    # ---- pushes
    if rep.classification and rep.classification.urgency == Urgency.URGENT:
        if pushes != 1:
            p.append(f"urgent call but {pushes} pushes")
        elif len(w.sent[-1][2]) != 3:
            p.append("urgent push without three buttons")
    elif pushes:
        p.append("non-urgent call was pushed before the digest")
    # ---- expectations
    if c.expect_urgency and (rep.classification is None or rep.classification.urgency != c.expect_urgency):
        got = rep.classification.urgency.value if rep.classification else "none"
        p.append(f"expected {c.expect_urgency.value}, got {got}")
    if c.expect_outcome and rep.capture.outcome != c.expect_outcome:
        p.append(f"expected outcome {c.expect_outcome.value}, got {rep.capture.outcome.value}")
    if c.expect_name and (rep.capture.caller_name or "").lower() != c.expect_name.lower():
        p.append(f"expected name {c.expect_name}, got {rep.capture.caller_name}")
    if c.expect_reason_has and c.expect_reason_has.lower() not in (rep.capture.reason or "").lower():
        p.append(f"reason lacks {c.expect_reason_has!r}")
    for k in c.expect_lines:
        if not any(x == k or x.startswith(k) for x in keys):
            p.append(f"line {k} was not spoken")
    if c.expect_callback and not rep.capture.callback_number:
        p.append("volunteered number not captured")
    if not c.expect_callback and rep.capture.callback_number:
        p.append("a call-back number appeared without being offered")
    if c.expect_declined and (rep.capture.reason or rep.capture.snippet):
        p.append("details stored although the caller declined")
    if c.expect_no_message_row and rep.message is not None and (rep.message.reason or rep.message.snippet):
        p.append("content stored for a refused call")
    if c.scenario in {"blocked", "paused", "disabled"} and pushes:
        p.append("a refused call produced a push")
    if c.scenario == "unrouted" and (rep.message is None or rep.message.user_id is not None):
        p.append("unrouted call was attributed to a user")
    return p


async def run_all(*, classifier: Classifier | None = None) -> list[Result]:
    results = []
    for c in callers():
        w = await make_world(classifier=classifier)  # a fresh world per caller (caps stay independent)
        results.append(await run_caller(w, c))
    return results


def format_table(results: list[Result]) -> str:
    out = [f"{'id':32} {'lang':8} {'urgency':8} {'outcome':12} {'sec':>4}  result"]
    for r in results:
        out.append(
            f"{r.caller.id:32} {r.caller.language:8} {r.urgency or '-':8} {r.outcome:12} "
            f"{r.seconds:4.0f}  {'ok' if r.ok else 'FAIL: ' + '; '.join(r.problems)}"
        )
    bad = sum(1 for r in results if not r.ok)
    out.append(f"\n{len(results) - bad}/{len(results)} callers passed")
    return "\n".join(out)


def add_parser(sub: argparse._SubParsersAction) -> None:  # noqa: SLF001
    p = sub.add_parser("receptionist-sim", help="run the scripted receptionist callers (offline)")
    p.add_argument("--show", metavar="ID", help="print the full conversation of one caller")
    p.add_argument("--morning", action="store_true", help="also print the digest and 'what did I miss?'")


def run_command(args: argparse.Namespace) -> int:
    import asyncio

    async def go() -> int:
        results = await run_all()
        if args.show:
            r = next((x for x in results if x.caller.id == args.show), None)
            if r is None:
                print("unknown caller id; ids:", ", ".join(x.caller.id for x in results))
                return 2
            print(f"{r.caller.title}  [{r.caller.language}]")
            for line in r.caller.script:
                print(f"  caller: {line or '(silence)'}")
            for key, text in r.spoken:
                print(f"  friday [{key}]: {text}")
            return 0
        print("OFFLINE SIMULATION. Invented callers and numbers; every Friday line is PENDING founder approval.")
        print(format_table(results))
        if args.morning:
            await _morning_demo()
        return 0 if all(r.ok for r in results) else 1

    return asyncio.run(go())


async def _morning_demo() -> None:
    w = await make_world()
    for c in callers():
        if c.scenario == "normal" and c.id in {
            "family-mummy-urgent-contact", "doctor-clinic", "courier-delivery", "spam-loan-hinglish",
            "english-recruiter", "plumber-volunteers-number",
        }:
            await run_caller(w, c)
    w.clock.set(datetime(2026, 10, 23, 8, 30, tzinfo=IST))
    print("\n--- morning digest (WhatsApp) ---")
    n = await w.service.tick([USER_ID])
    print(w.sent[-1][1] if n else "(nothing waiting)")
    print("\n--- 'what did I miss?' (text) ---")
    print(await w.service.missed_text(USER_ID))
    print("\n--- 'what did I miss?' (short spoken version, PENDING audio approval) ---")
    print(await w.service.missed_spoken(USER_ID))
