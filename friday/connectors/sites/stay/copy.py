# ruff: noqa: E501
"""User-facing lines of the STAY flows (hotel, flight). PENDING founder approval (hear before change).

Same conventions as sites/copy.py: ``en`` and Roman-script Hinglish ``hi``; ``render`` scrubs the
result. Nothing here is approved wording. ``approval_text`` builds the approval card; the free-
cancellation deadline and what is non-refundable are READ BACK on it, and the cap includes taxes and
fees. The flow's ``QUESTION_KEY`` needs the ``q_stay_*`` keys (see docs/BROWSER_STAY_BUS.md).
"""

from __future__ import annotations

from datetime import datetime

from friday.connectors.contract import format_rupees
from friday.connectors.scrub import scrub_text

APPROVAL_PENDING = True
LANGS = ("en", "hi")

COPY: dict[str, dict[str, str]] = {
    "q_stay_destination": {"en": "Which city or area?", "hi": "Kaunsa shehar ya area?"},
    "q_stay_checkin": {"en": "Check-in date? (for example 2026-11-10)", "hi": "Check-in ki date? (jaise 2026-11-10)"},
    "q_stay_checkout": {"en": "Check-out date? (for example 2026-11-12)", "hi": "Check-out ki date? (jaise 2026-11-12)"},
    "q_stay_guest_name": {"en": "Whose name should the room be booked in? (as on the ID)",
                          "hi": "Room kiske naam par book karun? (ID jaisa naam)"},
    "q_flight_origin": {"en": "Flying from which city?", "hi": "Kaunse shehar se udna hai?"},
    "q_flight_depart_date": {"en": "Which date? (for example 2026-11-10)", "hi": "Kaunsi date? (jaise 2026-11-10)"},
    "q_flight_return_date": {"en": "Return date? (for example 2026-11-14)", "hi": "Wapsi ki date? (jaise 2026-11-14)"},
    "q_flight_passengers": {"en": "Names of everyone flying, exactly as on their ID. I never make up a name.",
                            "hi": "Jo jo travel kar rahe hain unke naam, ID jaise. Main kabhi naam khud nahi banati."},
    "approve_hotel": {
        "en": ("Please check:\n{merchant} ({area})\nRoom: {variant}\nDates: {when}\nGuest: {guest}\n"
               "Total {subtotal} including taxes and fees. I will go ahead only if the final amount is {max_total} or less.\n"
               "{cancel}\n{nonref}{shortlist}I never pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\n{merchant} ({area})\nRoom: {variant}\nDates: {when}\nGuest: {guest}\n"
               "Total {subtotal}, tax aur fees mila kar. Final amount {max_total} ya kam ho tabhi aage badhungi.\n"
               "{cancel}\n{nonref}{shortlist}Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?"),
    },
    "approve_flight": {
        "en": ("Please check:\nFlight: {merchant} ({area})\nFare: {variant}\nTravel: {when}\nPassengers: {guest}\n"
               "Total {subtotal} including taxes and fees; baggage and meals are not added. I will go ahead only if the final amount is {max_total} or less.\n"
               "{cancel}\n{nonref}{shortlist}I never pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\nFlight: {merchant} ({area})\nFare: {variant}\nSafar: {when}\nPassengers: {guest}\n"
               "Total {subtotal}, tax aur fees mila kar; baggage aur meal nahi joda. Final amount {max_total} ya kam ho tabhi aage badhungi.\n"
               "{cancel}\n{nonref}{shortlist}Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?"),
    },
    "cancel_free": {"en": "Free cancellation until {when}.", "hi": "{when} tak free cancellation."},
    "cancel_none": {"en": "No free cancellation: if you cancel, you may lose the money.",
                    "hi": "Free cancellation nahi hai: cancel karne par paisa katt sakta hai."},
    "nonref": {"en": "Non-refundable: {items}.\n", "hi": "Wapas nahi milega: {items}.\n"},
    "shortlist": {"en": "Other options I saw: {items}.\n", "hi": "Aur options jo dikhe: {items}.\n"},
    "foreign_currency": {
        "en": ("{site} shows prices in a currency other than rupees or needs a foreign-card route, so I stopped. "
               "Nothing was booked. You can finish it yourself here: {link}"),
        "hi": ("{site} par rupees ke bajay doosri currency dikh rahi hai ya foreign card chahiye, isliye ruk gayi. "
               "Kuch book nahi hua. Aap khud yahan poora kar sakte hain: {link}"),
    },
    "need_info": {"en": "I need one more detail before I look: {what}.", "hi": "Dekhne se pehle ek aur jaankari chahiye: {what}."},
    "reason_price": {"en": "the price on the site went up", "hi": "site par price badh gaya"},
    "reason_policy": {"en": "the cancellation terms on the site got worse", "hi": "site par cancellation ke terms kharab ho gaye"},
}


def render(key: str, lang: str, **kw: object) -> str:
    table = COPY[key]
    return scrub_text((table.get(lang) or table["en"]).format(**kw))


def fmt_when(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%b %Y')}, {(d.hour % 12) or 12}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"


def approval_text(p, lang: str = "en") -> str:  # noqa: ANN001 - a Proposal from sites/adapters.py
    d = p.details
    cancel = (render("cancel_free", lang, when=fmt_when(d["free_until"])) if d.get("free_until")
              else render("cancel_none", lang))
    nonref = render("nonref", lang, items=", ".join(d["nonrefundable"])) if d.get("nonrefundable") else ""
    others = [f"{x['name']} from {format_rupees(x['from_paise'])}" for x in d.get("shortlist", [])
              if x["name"] != p.merchant]
    return render("approve_hotel" if d.get("kind") == "hotel" else "approve_flight", lang,
                  merchant=p.merchant, area=p.area, variant=d.get("variant", ""), when=p.when,
                  guest=d.get("guest") or ", ".join(d.get("names", [])), subtotal=format_rupees(p.subtotal_paise),
                  max_total=format_rupees(p.max_total_paise), cancel=cancel, nonref=nonref,
                  shortlist=render("shortlist", lang, items="; ".join(others[:4])) if others else "")


def problem_text(problem, lang: str, site: str) -> str:  # noqa: ANN001 - a Problem / HandoverProblem
    kind = getattr(problem, "kind", "")
    if kind == "foreign_currency":
        return render("foreign_currency", lang, site=site, link=getattr(problem, "link", ""))
    if kind == "need_info":
        return render("need_info", lang, what=problem.what)
    return ""
