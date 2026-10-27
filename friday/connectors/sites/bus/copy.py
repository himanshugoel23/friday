# ruff: noqa: E501
"""User-facing lines of the BUS flow. PENDING founder approval (hear before change).

Same conventions as sites/copy.py (``en`` + Roman-script Hinglish ``hi``; ``render`` scrubs). The
operator's cancellation policy is READ BACK on the approval card, and the card says how long the seat
is held once the user says yes.
"""

from __future__ import annotations

from friday.connectors.contract import format_rupees
from friday.connectors.scrub import scrub_text

APPROVAL_PENDING = True
LANGS = ("en", "hi")

COPY: dict[str, dict[str, str]] = {
    "q_bus_origin": {"en": "Travelling from which city?", "hi": "Kaunse shehar se jana hai?"},
    "q_bus_destination": {"en": "Going to which city?", "hi": "Kaunse shehar jana hai?"},
    "q_bus_date": {"en": "Which date? (for example 2026-11-10)", "hi": "Kaunsi date? (jaise 2026-11-10)"},
    "q_bus_passengers": {"en": "Names of everyone travelling, exactly as on their ID. I never make up a name.",
                         "hi": "Jo jo travel kar rahe hain unke naam, ID jaise. Main kabhi naam khud nahi banati."},
    "q_bus_boarding": {"en": "Where will you board? Options: {options}", "hi": "Kahan se chadhenge? Options: {options}"},
    "q_bus_dropping": {"en": "Where will you get off? Options: {options}", "hi": "Kahan utrenge? Options: {options}"},
    "approve_bus": {
        "en": ("Please check:\nBus: {merchant} ({bus_type}), {when}\nSeats: {seats}\nPassengers: {names}\n"
               "Board: {boarding}\nDrop: {dropping}\nSeat price {subtotal}; fees and taxes get added. I will go ahead only "
               "if the final amount is {max_total} or less.\nOperator cancellation policy:\n{policy}\n"
               "The seat is held for about {hold_min} minutes after you say yes, so please answer soon.\n{shortlist}"
               "I never pay: you pay in your own UPI app. Go ahead?"),
        "hi": ("Ek baar dekh lijiye:\nBus: {merchant} ({bus_type}), {when}\nSeats: {seats}\nPassengers: {names}\n"
               "Kahan se: {boarding}\nKahan utarna: {dropping}\nSeat ka price {subtotal}; fees aur tax judte hain. Final amount "
               "{max_total} ya kam ho tabhi aage badhungi.\nOperator ka cancellation policy:\n{policy}\n"
               "Haan kehne ke baad seat lagbhag {hold_min} minute hold rehti hai, isliye jaldi jawab dijiye.\n{shortlist}"
               "Payment main kabhi nahi karti: aap apne UPI app se denge. Aage badhun?"),
    },
    "policy_row": {"en": "- {window}: {pct}% refund", "hi": "- {window}: {pct}% refund"},
    "shortlist": {"en": "Other buses I saw: {items}.\n", "hi": "Aur buses jo dikhi: {items}.\n"},
    "reason_hold": {"en": "the seat hold ran out, so the seats may be gone", "hi": "seat hold khatam ho gaya, seats ja sakti hain"},
    "reason_price": {"en": "ticket prices on the site went up", "hi": "site par ticket ke price badh gaye"},
}


def render(key: str, lang: str, **kw: object) -> str:
    table = COPY[key]
    return scrub_text((table.get(lang) or table["en"]).format(**kw))


def approval_text(p, lang: str = "en") -> str:  # noqa: ANN001 - a Proposal from sites/adapters.py
    d = p.details
    others = [f"{x['name']} from {format_rupees(x['from_paise'])}" for x in d.get("shortlist", []) if x["name"] != p.merchant]
    return render("approve_bus", lang, merchant=p.merchant, bus_type=d.get("bus_type", ""), when=p.when,
                  seats=", ".join(s["label"] for s in d["seats"]), names=", ".join(d["names"]),
                  boarding=f"{d['boarding']['name']} {d['boarding']['time']}".strip(),
                  dropping=f"{d['dropping']['name']} {d['dropping']['time']}".strip(),
                  subtotal=format_rupees(p.subtotal_paise), max_total=format_rupees(p.max_total_paise),
                  policy="\n".join(render("policy_row", lang, window=r["window"], pct=r["pct"]) for r in d["policy"]) or "-",
                  hold_min=max(1, int(d.get("hold_s", 600)) // 60),
                  shortlist=render("shortlist", lang, items="; ".join(others[:4])) if others else "")


def problem_text(problem, lang: str, site: str) -> str:  # noqa: ANN001
    if getattr(problem, "kind", "") == "need_info" and getattr(problem, "options", None):
        key = "q_bus_boarding" if problem.slot == "boarding" else "q_bus_dropping"
        return render(key, lang, options="; ".join(problem.options))
    return ""
