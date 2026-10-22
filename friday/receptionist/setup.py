# ruff: noqa: E501
"""The setup page text (Hinglish / English), the forwarding PROBE plan and the test-call helper.

All user-facing text here is PENDING_FOUNDER_APPROVAL (see copy.py for the register). The codes come
from ``carriers.py`` and are general knowledge to verify per carrier.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from friday.receptionist.carriers import CodeSet
from friday.receptionist.models import ReceptionistConfig

_CONDITION_HI = {
    "no_answer": "jab aap call na uthayein",
    "busy": "jab aap busy hon ya call kaat dein",
    "unreachable": "jab phone band ho ya network na ho",
}


def setup_text(cs: CodeSet, lang: str = "hinglish") -> str:
    """The message Friday sends with the exact codes for this user's carrier and ring choice."""
    en = lang == "en"
    out: list[str] = []
    if en:
        out.append(
            f"Friday can answer the calls you miss. Pick up as usual; if you do not answer in "
            f"about {cs.rings} rings, Friday takes a message and sends you a summary."
        )
        out.append(f"Your carrier: {cs.carrier.name}. Dial these codes one by one (press call each time):")
    else:
        out.append(
            f"Friday woh calls utha sakti hai jo aap miss kar dein. Aap pehle ki tarah call uthayein; "
            f"agar aap lagbhag {cs.rings} ring tak nahi uthate, toh Friday message le legi aur aapko summary bhej degi."
        )
        out.append(f"Aapka carrier: {cs.carrier.name}. Yeh codes ek ek karke dial karein (har baar call dabayein):")
    for line in cs.activate:
        cond = line.condition_text if en else _CONDITION_HI[line.label]
        out.append(f"  {line.code}   ({cond})")
    if en:
        out.append(
            f"Check: dial {', '.join(c for _, c in cs.status)} and the screen should show Friday's number."
        )
        out.append(f"Turn off: dial {cs.cancel_all} (cancels all forwarding), or {', '.join(c for _, c in cs.cancel)}.")
        out.append(
            "IMPORTANT: your carrier's own voicemail may answer before Friday. If it does, switch the "
            "carrier voicemail OFF (carrier app or customer care) and dial the codes again."
        )
        out.append("Charges: forwarded calls may be charged by your carrier, depending on your plan.")
        out.append("Then press 'Test it': Friday rings your phone, you do not answer, and Friday confirms here.")
    else:
        out.append(
            f"Check karne ke liye {', '.join(c for _, c in cs.status)} dial karein; screen par Friday ka number dikhna chahiye."
        )
        out.append(f"Band karne ke liye {cs.cancel_all} dial karein (sab forwarding band), ya {', '.join(c for _, c in cs.cancel)}.")
        out.append(
            "ZARURI: aapke carrier ka apna voicemail Friday se pehle jawab de sakta hai. Agar aisa ho, "
            "carrier ka voicemail band karwayein (carrier app ya customer care se) aur codes dobara dial karein."
        )
        out.append("Charges: forwarded calls ka charge aapke plan ke hisaab se carrier laga sakta hai.")
        out.append("Phir 'Test it' dabayein: Friday aapko ring karegi, aap mat uthana, aur Friday yahin confirm karegi.")
    out.append(("Note: " if en else "Dhyan dein: ") + cs.notices[0])
    for n in cs.notices[1:]:
        out.append("- " + n)
    return "\n".join(out)


PROBE_STEPS = (
    "1. On the server set FRIDAY_RECEPTIONIST_PROBE=true (the switch FRIDAY_RECEPTIONIST_ENABLED can stay false) and restart `friday listen`.",
    "2. On YOUR phone (the founder's) set ONLY forwarding when unanswered to Friday's inbound number: the no-answer code from `friday receptionist codes --carrier <yours> --number <Friday number>`.",
    "3. From a SECOND phone, call your own number and do not answer (let it ring until it forwards), then repeat once with the second phone calling and you pressing Decline.",
    "4. Run `friday receptionist probe --show`. It prints, masked, every webhook key that arrived and any key whose value looks like your number.",
    "5. If a key is listed as a candidate, put its name first in FRIDAY_RECEPTIONIST_REDIRECT_FIELDS; if none, nothing carries it and the fallback (ask the caller whom they wanted) is needed. Send the output to the team; it contains no full numbers.",
    "6. Cancel with ##002#, check with *#61#, and repeat for each carrier you have a SIM for (Jio, Airtel, Vi, BSNL).",
)


@dataclass
class TestCallResult:
    __test__ = False

    placed: bool
    found: bool = False
    detail: str = ""


Dialer = Callable[[str], Awaitable[bool]]
ProbeWaiter = Callable[[float], Awaitable[bool]]


class TestCallHelper:
    __test__ = False  # not a pytest class

    """The "Test it" button. Friday rings the user's own phone; if they do not answer, the call is
    forwarded back and the probe sees it. Refuses anything but allow-listed numbers, and the kill
    switch (``friday pause``). With no dialer wired it only returns instructions (never dials)."""

    def __init__(
        self,
        *,
        allow_listed: Callable[[str], bool],
        paused: Callable[[], bool],
        dialer: Dialer | None = None,
        wait_for_forward: ProbeWaiter | None = None,
        wait_s: float = 60.0,
    ) -> None:
        self.allow_listed, self.paused = allow_listed, paused
        self.dialer, self.wait, self.wait_s = dialer, wait_for_forward, wait_s

    async def run(self, user_phone: str, config: ReceptionistConfig) -> TestCallResult:
        if self.paused():
            return TestCallResult(False, detail="paused: the kill switch is on")
        if not self.allow_listed(user_phone):
            return TestCallResult(False, detail="refused: not an allow-listed number")
        if self.dialer is None:
            return TestCallResult(
                False,
                detail=(
                    "no dialer wired: call your own number from another phone and do not answer "
                    f"(about {config.rings} rings), then run `friday receptionist probe --show`"
                ),
            )
        if not await self.dialer(user_phone):
            return TestCallResult(False, detail="the test call could not be placed")
        found = bool(self.wait) and await self.wait(self.wait_s)
        return TestCallResult(
            True,
            found,
            "forwarding works: Friday received the forwarded call"
            if found
            else "the call was placed but nothing was forwarded back in time; check the codes and the carrier voicemail",
        )
