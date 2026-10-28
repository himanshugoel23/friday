# ruff: noqa: E501
"""The QA scenarios: what the founder can run by hand, and exactly what is REAL and what is SIMULATED.

Each scenario states, before anything happens:
  * what Friday will do (``steps``),
  * what the founder should hear or see (``hear``),
  * which parts are real (a real Vobiz + Sarvam call to HIS OWN phone, the production code path)
    and which are simulated (invented data, the Chat Lab engine, text shown only),
  * ``kind``: ``call`` (a real call, needs the typed/tapped approval phrase), ``chat`` (Chat Lab
    simulator, no call), ``info`` (instructions for something he does himself, no call from us).

No scenario places a call to anyone but the founder's allow-listed number: the number is never part of
a scenario, only ``QaGuard`` supplies it. No scenario asks for an OTP, PIN, password or payment.
Everything the page shows is in English; the words Friday SPEAKS stay Hinglish (the production lines).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

KIND_CALL, KIND_CHAT, KIND_INFO = "call", "chat", "info"
DEFAULT_FIRST_NAME = "Himanshu"
DEFAULT_AREA = "Gurugram"

# words a QA scenario may never contain (spoken, asked of the founder, or sent to a form)
SECRET_WORDS = re.compile(r"\b(otp|pin code|password|cvv|card number|upi pin|net ?banking)\b", re.I)


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    group: str
    kind: str
    summary: str
    steps: tuple[str, ...]
    hear: str
    real: tuple[str, ...]
    simulated: tuple[str, ...]
    spec: dict[str, Any] = field(default_factory=dict)
    messages: tuple[tuple[str, str], ...] = ()  # chat scenarios: (text | voice | sample, content)
    shortlist_query: str | None = None  # call scenarios that show a Places shortlist first
    needs_approval: bool = False

    def texts(self) -> list[str]:
        """Every string a scenario can say or ask (the no-secrets test reads these)."""
        out = [self.title, self.summary, self.hear, *self.steps, *self.real, *self.simulated]
        out += [c for _, c in self.messages]
        out += [str(v) for v in self.spec.values() if isinstance(v, str)]
        out += [str(v) for v in (self.spec.get("inputs") or {}).values()]
        return out


def _call(**kw: Any) -> Scenario:
    return Scenario(kind=KIND_CALL, needs_approval=True, **kw)


G_VENDOR = "Vendor calls (you play the business)"
G_CONSUMER = "Calls for the user"
G_INBOUND = "Inbound, receptionist, urgent"
G_FOLLOW = "Follow-up calls"
G_CHAT = "Chat features (simulator)"
G_OTHER = "Other"

_YOU_ARE_VENDOR = (
    "Your phone rings from Friday's caller ID. You play the business that picks up. "
    "Friday says she is a virtual assistant calling on your behalf."
)
_REAL_VENDOR = (
    "A real Vobiz call to your own phone, a real Sarvam voice, the production playbook engine "
    "(the same code a vendor call uses).",
    "The vendor's NAME in the script is real (from the Places shortlist when a Places key is set); "
    "the vendor's own number is never dialled and never shown.",
)
_SIM_VENDOR = (
    "The vendor, their prices and their answers (you improvise them).",
    "The WhatsApp request and the quote message to the user (WhatsApp is blocked by Meta): shown as text only.",
)


def _vendor(
    sid: str,
    title: str,
    query: str,
    playbook: str,
    service: str,
    *,
    date_window: str = "",
    extra: dict[str, str] | None = None,
    pending: bool = True,
    hear: str,
    note: str = "",
) -> Scenario:
    return _call(
        id=sid,
        title=title,
        group=G_VENDOR,
        summary=f"Friday phones a {query} on the user's behalf. The business search is replaced by your phone.",
        steps=(
            f"Show the Places shortlist for '{query}' as text (names only; nothing from it is dialled).",
            "Pick the top name and put it in the script as the real business name.",
            f"Dial YOUR phone (not the business) with the '{playbook}' script"
            + (
                " (PENDING version: every pending line spoken is logged by id)."
                if pending
                else " (the approved production script)."
            ),
            "You answer as the business and talk it through. Friday ends the call within 3 minutes.",
        ),
        hear=(note + " " if note else "") + hear,
        real=_REAL_VENDOR,
        simulated=_SIM_VENDOR,
        shortlist_query=query,
        spec={
            "backend": "playbook",
            "playbook": playbook,
            "pending": pending,
            "service": service,
            "date_window": date_window,
            "inputs": extra or {},
        },
    )


SCENARIOS: tuple[Scenario, ...] = (
    _vendor(
        "salon_quote",
        "Salon price-quote call (approved script)",
        "salon",
        "salon_booking",
        "haircut, beard trim",
        date_window="kal shaam",
        pending=False,
        hear="A short hook, then she asks the price for a haircut and beard trim tomorrow evening. She books nothing. She says she will come back after the user approves.",
    ),
    _vendor(
        "salon_quote_pending",
        "Salon price-quote call (PENDING script v7)",
        "salon",
        "salon_booking",
        "haircut, beard trim",
        date_window="kal shaam",
        pending=True,
        hear="Same job with the new pending wording. Compare it with the approved one; approve or reject each pending line id afterwards.",
    ),
    _vendor(
        "vendor_table",
        "Restaurant table booking",
        "restaurant",
        "table_booking",
        "table",
        date_window="aaj raat 8 baje",
        extra={"people_count": "4"},
        hear="She states the request: a table for 4 tonight at 8, then asks if it is free. If not free she never books another time on her own.",
    ),
    _vendor(
        "vendor_home_service",
        "Home service quote (AC repair)",
        "AC repair service",
        "home_service_visit",
        "AC repair",
        date_window="kal subah",
        extra={"items_description": "split AC not cooling"},
        hear="She describes the problem, asks for a visit charge and an estimate, and whether someone can come tomorrow morning.",
    ),
    _vendor(
        "vendor_stock_price",
        "Stock and price check (shop)",
        "mobile phone shop",
        "stock_and_price",
        "iPhone 15 128GB",
        extra={"delivery_area": "Sector 50"},
        hear="She asks if the model is in stock and the price, and whether there is home delivery.",
    ),
    _vendor(
        "vendor_hotel",
        "Hotel booking enquiry",
        "hotel",
        "hotel_booking",
        "room booking",
        extra={
            "checkin_date": "this Friday",
            "checkout_date": "Sunday",
            "guests": "2",
            "room_count": "1",
        },
        hear="She asks about a room for 2 from Friday to Sunday: availability and the rate. No booking is made.",
    ),
    _vendor(
        "vendor_cab",
        "Cab booking enquiry",
        "cab service",
        "cab_booking",
        "airport drop",
        extra={
            "from_place": "Sector 50 Gurugram",
            "to_place": "Terminal 3 Delhi airport",
            "pickup_time": "kal subah 6 baje",
            "people_count": "2",
        },
        hear="She asks for a cab to the airport tomorrow 6 am for 2 people and the fare.",
    ),
    _vendor(
        "vendor_rental",
        "Rental / PG enquiry",
        "PG accommodation",
        "pg_rental",
        "single sharing room",
        extra={"sharing_type": "single", "move_in_date": "next month"},
        hear="She asks about a single-sharing room, the rent and deposit, and the move-in date.",
    ),
    _vendor(
        "vendor_banquet",
        "Banquet hall enquiry",
        "banquet hall",
        "banquet_booking",
        "banquet booking",
        extra={"event_type": "birthday party", "guests": "60", "event_date": "next month"},
        hear="She asks if the hall is free on the event date for about 60 guests, and the per-plate or hall price.",
    ),
    _call(
        id="consumer_family",
        title="'Call someone for me' (family-style call)",
        group=G_CONSUMER,
        summary="The consumer call-for-me path: request, approval, safety gate, live call, report. The 'family member' is your own phone.",
        steps=(
            "Build the request as if the user had said 'call Mummy and tell her I will be late'.",
            "Run the production gate (your number only, the QA override lifts the daily cap and the calling window) and the approved-opening check.",
            "Dial YOUR phone. Friday opens with the greeting plus the line saying she is a virtual assistant calling for the user.",
            "You answer as the family member. The report Friday would send is printed here (not sent on WhatsApp).",
        ),
        hear="The opening line, then the short message in the user's words. She takes a reply and wraps up politely.",
        real=(
            "A real call through the consumer path (`friday consumer call-test`): gate, brief, live engine, report.",
        ),
        simulated=(
            "The WhatsApp request and the report message (printed only).",
            "The family member (you).",
        ),
        spec={
            "backend": "consumer",
            "who": "family",
            "callee_name": "Mummy",
            "goal": "main aaj thoda late aaunga, khana mat rukna",
        },
    ),
    _call(
        id="consumer_provider",
        title="'Call someone for me' (service provider)",
        group=G_CONSUMER,
        summary="Same consumer path, provider style: the callee is a plumber or a doctor's desk (you).",
        steps=(
            "Build a provider-style request: ask for a visit slot tomorrow.",
            "Gate, approval and live call exactly as in the family scenario, provider style.",
            "You answer as the provider.",
        ),
        hear="A more formal opening, then the question about tomorrow's slot.",
        real=("A real call through the consumer path.",),
        simulated=("The provider (you).",),
        spec={
            "backend": "consumer",
            "who": "provider",
            "callee_name": "Sharma ji",
            "goal": "kal subah koi slot mil sakta hai kya, plumber ki visit ke liye",
        },
    ),
    _call(
        id="receptionist_greeting",
        title="Receptionist: how she greets a caller (audio sample)",
        group=G_INBOUND,
        summary="Friday rings you and plays the receptionist's spoken lines in order, so you can hear every pending line.",
        steps=(
            "Friday rings your phone.",
            "She plays the receptionist lines one after another with short pauses: greeting, ask name, ask reason, read-back, close.",
            "Every pending line id spoken is logged. This is one-way playback; she does not listen.",
        ),
        hear="'Hello, main Friday bol rahi hoon, <name> ki virtual assistant ...' and the rest of the receptionist script.",
        real=(
            "A real call to your phone playing the real receptionist lines (friday/receptionist/lines.py).",
        ),
        simulated=(
            "The live listening/classification part of the receptionist (use the inbound scenario below to try that for real).",
        ),
        spec={
            "backend": "speak",
            "source": "receptionist",
            "keys": (
                "greet.intro",
                "ask.name",
                "ask.reason_named",
                "readback",
                "close.message",
                "ai.answer",
            ),
        },
    ),
    _call(
        id="receptionist_forwarding_ring",
        title="Receptionist: forwarding test ring",
        group=G_INBOUND,
        summary="Friday rings your phone once from her pool number so you can test call forwarding (decline it).",
        steps=(
            "Friday rings your phone and lets it ring.",
            "DECLINE the call (do not answer). With forwarding set up, the carrier sends it back to Friday's number.",
            "If you answer by mistake, Friday just hangs up; nothing is said.",
        ),
        hear="Nothing is spoken. You are looking at whether the call comes back to Friday and the 'forwarding works' text appears.",
        real=("A real ring from Friday's number to yours.",),
        simulated=(
            "The 'forwarding works' WhatsApp text (WhatsApp is blocked): check the server log instead.",
        ),
        spec={"backend": "ring"},
    ),
    _call(
        id="urgent_escalation",
        title="Urgent escalation: alert, then Friday phones you",
        group=G_INBOUND,
        summary="An urgent alert is shown as text; if you do not acknowledge it, after N minutes Friday calls your own number.",
        steps=(
            "Show the urgent alert text (simulated; WhatsApp is blocked).",
            "Wait N minutes (default 2, shown as a countdown). Do not acknowledge.",
            "Friday calls your own number through the production escalation dial and speaks the urgent line (PENDING, logged by id).",
        ),
        hear="'Hello <name>, main Friday bol rahi hoon. Aapke liye ek urgent message aaya hai. Kripya abhi WhatsApp dekh lijiye.' No digits, no names, no details.",
        real=("The escalation dial itself (friday/urgent/telephony.py) and the spoken line.",),
        simulated=(
            "The urgent WhatsApp alert and the Acknowledge button; the N-minute timer is shortened for QA.",
        ),
        spec={"backend": "urgent", "line_key": "ring.urgent"},
    ),
    _call(
        id="trip_hotel_call",
        title="Trip: hotel reconfirm call",
        group=G_FOLLOW,
        summary="The trip timeline proposes 'call the hotel to reconfirm'. The hotel is your phone; the trip data is invented.",
        steps=(
            "Show the trip proposal text built from invented trip data (simulated).",
            "You 'tap Yes' by approving here. Friday dials YOUR phone with the reconfirm questions.",
            "You answer as the hotel front desk.",
        ),
        hear="She says she is calling to reconfirm a booking and arrival, and asks the hotel questions from the trip module.",
        real=("A real call using the live engine with the trip module's own goal and questions.",),
        simulated=(
            "The trip, the hotel and the booking reference (invented).",
            "The proposal message and the Yes tap.",
        ),
        spec={
            "backend": "goal",
            "target_name": "Hotel Example Palms",
            "goal": "Confirm the hotel booking and arrival with Hotel Example Palms (reference EX-12345, arriving Friday afternoon): check the booking is in the user's name, check-in time, and early check-in.",
        },
    ),
    _call(
        id="refund_followup",
        title="Refund follow-up call",
        group=G_FOLLOW,
        summary="A refund has been pending for days; Friday phones the vendor to ask for its status. The vendor is your phone.",
        steps=(
            "Show the refund case (invented) and the follow-up proposal text (simulated).",
            "Dial YOUR phone as the vendor's support desk with the refund-status goal.",
            "You answer as support; say it will be done in 3 days, or ask for details.",
        ),
        hear="She asks about the status of a refund, gives the order reference slowly, asks for a time, and does not accept a vague answer.",
        real=("A real call using the live engine with the refund module's own goal sentence.",),
        simulated=(
            "The refund case, amount and order reference (invented).",
            "The vendor and the follow-up message.",
        ),
        spec={
            "backend": "goal",
            "target_name": "Example Store support",
            "goal": "Ask Example Store about the status of a refund the user is waiting for (order EX-9087, promised 7 days ago). Ask for a date and a reference; do not accept a vague answer.",
        },
    ),
    _call(
        id="care_hold_rehearsal",
        title="Customer care: hold-fighting rehearsal",
        group=G_FOLLOW,
        summary="Friday phones 'customer care' (you) to sort out a billing problem. You read a fake IVR and keep her on hold.",
        steps=(
            "Dial YOUR phone as the company's customer care.",
            "You play the IVR: say 'press 1 for billing, press 2 for new connection', then 'please hold', wait about 20 seconds, then answer as an agent.",
            "Friday should choose billing, wait on hold without hanging up, and re-introduce herself when the agent comes.",
        ),
        hear="She listens to the menu, navigates, waits patiently and then explains the billing issue.",
        real=("A real call with the care goal; she really waits on hold with you.",),
        simulated=(
            "The IVR (you read it aloud; there is no automatic IVR player), the company and the billing problem.",
        ),
        spec={
            "backend": "goal",
            "target_name": "Example Telecom customer care",
            "goal": "Customer-care call to Example Telecom about a double charge on last month's bill. Expect an IVR menu: choose the billing option, wait on hold, then explain the double charge and ask for a reversal and a complaint number.",
        },
    ),
    Scenario(
        id="frontdoor_inbound",
        title="Front door: you call Friday's number",
        group=G_INBOUND,
        kind=KIND_INFO,
        summary="Inbound call to Friday's number. Friday cannot start this one; you dial it.",
        steps=(
            "On the server run `friday listen` (stops the QA calls while it runs) or leave the front door service up.",
            "From your phone dial Friday's number (the caller ID Friday shows when she rings you).",
            "Talk to her. Then check `friday qa report` for the pending line ids if any were spoken.",
        ),
        hear="Her greeting, a conversation in Hinglish, and an honest 'I am a virtual assistant'.",
        real=("Everything: you call, she answers (the front door).",),
        simulated=("Nothing.",),
    ),
    Scenario(
        id="receptionist_inbound",
        title="Receptionist: set up forwarding and call yourself",
        group=G_INBOUND,
        kind=KIND_INFO,
        summary="Try the receptionist for real: forward your phone to Friday's number and have a second phone call you.",
        steps=(
            "Run the forwarding ring scenario first to prove forwarding comes back to Friday.",
            "From another phone, call your own number and do not answer.",
            "Friday's receptionist answers the forwarded call. Say a name and a reason; hang up.",
        ),
        hear="The receptionist greeting, 'who is calling and what is it about', a read-back, a polite close.",
        real=("The whole receptionist, if you do it yourself.",),
        simulated=("Nothing.",),
    ),
    Scenario(
        id="morning_checkin",
        title="Morning check-in call",
        group=G_OTHER,
        kind=KIND_INFO,
        summary="Not built in this version: Friday does not place a morning check-in call. Nothing to run.",
        steps=("Mark this as 'not built' in your notes if you expected it.",),
        hear="Nothing.",
        real=("Nothing.",),
        simulated=("Nothing.",),
    ),
    Scenario(
        id="chat_text",
        title="Chat: ask Friday for things in text",
        group=G_CHAT,
        kind=KIND_CHAT,
        summary="The text part of the chatbot on the Chat Lab engine: a greeting, a question and a savings question.",
        steps=(
            "Open a fresh simulated user.",
            "Send three text messages.",
            "Show Friday's replies.",
        ),
        hear="Short, warm, honest replies in your language (English, Hindi or Hinglish).",
        real=("The real message pipeline and chatbot code.",),
        simulated=(
            "Everything about WhatsApp (in-memory channel, fake numbers), the clock and the model (the Lab's fake model unless you started it with a key).",
        ),
        messages=(
            ("text", "Hi"),
            ("text", "kya kya kar sakti ho tum?"),
            ("text", "Which credit card should I use for a restaurant bill?"),
        ),
    ),
    Scenario(
        id="chat_voice_note",
        title="Chat: voice note (transcribed text)",
        group=G_CHAT,
        kind=KIND_CHAT,
        summary="A voice note arrives as its transcript; checks Hinglish and Devanagari handling.",
        steps=("Send two voice notes as transcripts.", "Show the replies."),
        hear="The reply should match the language of the note.",
        real=("The voice-note handling after transcription.",),
        simulated=("The audio and the speech-to-text (the transcript is typed for you).",),
        messages=(
            ("voice", "bhaiya kal subah AC theek karne wala bula do"),
            ("voice", "मुझे अगले हफ्ते की ट्रेन देखनी है"),
        ),
    ),
    Scenario(
        id="chat_documents",
        title="Proof and documents (fake data demo)",
        group=G_CHAT,
        kind=KIND_CHAT,
        summary="Friday reads an electricity bill, a restaurant receipt and a visiting card (sample files, invented data).",
        steps=(
            "Send the three sample files.",
            "Show what Friday understood and what she offers to do.",
        ),
        hear="A clear summary of each document, and no invented details.",
        real=("The document-understanding pipeline.",),
        simulated=("The files (samples with invented data), the model, WhatsApp.",),
        messages=(
            ("sample", "electricity-bill.pdf"),
            ("sample", "restaurant-receipt.jpg"),
            ("sample", "visiting-card.jpg"),
        ),
    ),
    Scenario(
        id="chat_trips_refunds",
        title="Trips, refunds and Drive in text (fake data)",
        group=G_CHAT,
        kind=KIND_CHAT,
        summary="Text commands for the trip timeline, a refund case and the family Drive, on the simulator with invented data.",
        steps=("Send a few text commands.", "Show the replies; no call is made."),
        hear="Short answers; nothing is sent to a real person and nothing real is stored.",
        real=("The command parsers and replies.",),
        simulated=(
            "All trip, refund and Drive data; the Drive itself is a stub (no Google account is touched).",
        ),
        messages=(
            ("text", "my trips"),
            ("text", "refund Example Store 799 rupees"),
            ("text", "mera refund kahan hai?"),
        ),
    ),
)

BY_ID: dict[str, Scenario] = {s.id: s for s in SCENARIOS}


def get(sid: str) -> Scenario:
    try:
        return BY_ID[sid]
    except KeyError:
        raise KeyError(f"no scenario named '{sid}'") from None


def has_secret_prompt(s: Scenario) -> bool:
    return any(SECRET_WORDS.search(t) for t in s.texts())


def parts(s: Scenario) -> dict[str, list[str]]:
    return {"real": list(s.real), "simulated": list(s.simulated)}
