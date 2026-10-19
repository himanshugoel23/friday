# ruff: noqa: E501
"""EVERY user-facing line of the savings engine lives in this one module.

PENDING_FOUNDER_APPROVAL: none of these lines has been approved yet (hear-before-change rule:
the founder reviews and approves the wording before it goes to a real user). Change wording here
only, never inline in the logic. Rupee figures are always passed in from the calculator or the
ledger; nothing in this file computes or invents one.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from friday.savings.money import format_rate, format_rs

if TYPE_CHECKING:  # pragma: no cover
    from friday.savings.bills import Bill
    from friday.savings.calculator import Option, Ranking
    from friday.savings.savings_ledger import MonthlySummary

PENDING_FOUNDER_APPROVAL = True

# ------------------------------------------------------------------ labels

CATEGORY_LABEL = {
    "food_delivery": "Food delivery",
    "dining": "Restaurant",
    "grocery": "Grocery",
    "fuel": "Petrol/diesel",
    "travel": "Travel",
    "cab": "Cab/auto",
    "online_shopping": "Online shopping",
    "electronics": "Electronics",
    "bills_utilities": "Bill payment",
    "mobile_recharge": "Mobile recharge",
    "entertainment": "Entertainment",
    "pharmacy": "Dawai/pharmacy",
    "rent": "Rent",
    "wallet_load": "Wallet load",
    "insurance": "Insurance",
    "education": "Fees/education",
    "other": "Is kharch",
    "all": "Har kharch",
}
MERCHANT_LABEL = {"dominos": "Domino's", "bigbasket": "BigBasket", "makemytrip": "MakeMyTrip"}


def label(category: str) -> str:
    return CATEGORY_LABEL.get(category, category.replace("_", " ").title())


def merchant_label(merchant: str) -> str:
    return MERCHANT_LABEL.get(merchant, merchant.title())


def when_phrase(days_left: int) -> str:
    if days_left == 0:
        return "aaj"
    if days_left == 1:
        return "kal"
    if days_left > 1:
        return f"{days_left} din baad"
    return f"{-days_left} din pehle"


def date_phrase(d: date) -> str:
    return f"{d.day} {d:%b}"


# ------------------------------------------------------------------ safety

SENSITIVE_REFUSAL = (
    "Card number, CVV, expiry, OTP ya PIN mujhe kabhi mat bhejiye, main inhe save nahi karti. "
    "Bas bank aur card ka naam batayiye, jaise 'HDFC Regalia'."
)
EXAMPLE_NOTE = "[EXAMPLE data, asli offer nahi]"
NEUTRALITY_FOOTER = "Ranking sirf aapke reward se banti hai, kisi bank ya app se commission nahi."

# ------------------------------------------------------------------ reason clause (calculator)


def reason_clause(
    *,
    category: str,
    rate_bp: int,
    reward_type: str,
    reward_paise: int,
    cap_left_paise: int | None,
    cap_hit: bool,
    per_txn_cap_paise: int | None,
    exclusion: str | None,
    min_spend_paise: int | None,
    zero_spend: bool,
) -> str:
    """One clause saying why this card gets this reward. Never empty."""
    cat = label(category)
    if zero_spend:
        return "Rs 0 ke kharch pe koi reward nahi banta"
    if exclusion:
        what = label(exclusion) if exclusion in CATEGORY_LABEL else merchant_label(exclusion)
        return f"{what} pe is card pe reward nahi milta"
    if min_spend_paise:
        return f"{format_rs(min_spend_paise)} se kam ke kharch pe reward nahi milta"
    if cap_left_paise == 0:
        return f"{cat} ka is mahine ka cap poora ho chuka hai"
    rate = format_rate(rate_bp)
    if reward_type == "discount":
        head = f"{cat} pe {rate}% discount milega"
    elif reward_type == "points":
        head = f"{cat} pe {rate}% value ke points milenge"
    else:
        head = f"{cat} pe {rate}% milega"
    if cap_left_paise is not None:
        head += f", cap me {format_rs(cap_left_paise)} bacha hai"
    if cap_hit and per_txn_cap_paise is not None and reward_paise == per_txn_cap_paise:
        head += f", ek payment pe {format_rs(per_txn_cap_paise)} tak hi milta hai"
    return head


# ------------------------------------------------------------------ asking

ASK_AMOUNT = "Kitne ka kharch hai? Jaise 'Zomato pe 640' ya 'petrol 2000'."
ASK_WHICH_AMOUNT = "Mujhe ek se zyada amount dikhe. Kaunsa kharch karna hai? Ek amount likhiye."


def ask_category(options: tuple[str, ...] = ()) -> str:
    if options:
        names = ", ".join(label(o) for o in options)
        return f"Ye in me se kis cheez pe hai: {names}? Naam ke saath dobara likhiye."
    return "Ye kis cheez pe kharch hai? Jaise food order, grocery, petrol, travel ya shopping."


NO_CARDS_FOR_QUESTION = (
    "Pehle bata dijiye aapke paas kaun se cards hain, jaise 'mere paas HDFC Regalia aur "
    "SBI Cashback hai'. Sirf naam, number nahi."
)

# ------------------------------------------------------------------ recommendation


def _unit(opt: Option) -> str:
    return {"cashback": "cashback", "points": "ke points (andaaza)", "discount": "discount"}.get(
        opt.reward_type, "reward"
    )


def _flags(opt: Option, age_note: str) -> str:
    out = []
    if opt.example:
        out.append(EXAMPLE_NOTE)
    if opt.confirm_on_app:
        out.append(age_note)
    return " ".join(out)


CONFIRM_ON_APP = "Ye rule purana ya unconfirmed hai, apne card app me ek baar confirm kar lijiye."


def spend_phrase(ranking: Ranking) -> str:
    where = f"{merchant_label(ranking.merchant)} pe" if ranking.merchant else f"{label(ranking.category)} pe"
    return f"{where} {format_rs(ranking.spend_paise)}"


def recommendation(ranking: Ranking, shown: int = 3) -> str:
    top = ranking.top
    assert top is not None
    head = spend_phrase(ranking)
    lines: list[str]
    if ranking.nothing_earned:
        lines = [
            f"{head}: aapke kisi card se is pe reward nahi milega ({top.reason}). "
            "Jo card aapko theek lage wahi use kar lijiye."
        ]
    else:
        lines = [
            f"{head}: {top.display} use kijiye, {format_rs(top.reward_paise)} {_unit(top)}. "
            f"Wajah: {top.reason}."
        ]
        flag = _flags(top, CONFIRM_ON_APP)
        if flag:
            lines.append(flag)
        rest = list(ranking.options[1:shown])
        if rest:
            lines.append("Doosre cards:")
            for o in rest:
                lines.append(f"- {o.display}: {format_rs(o.reward_paise)} ({o.reason})")
    if ranking.unknown:
        names = ", ".join(u.display for u in ranking.unknown)
        lines.append(f"In cards ke verified rules mere paas nahi hain, isliye compare nahi kiya: {names}.")
    lines.append(NEUTRALITY_FOOTER)
    return "\n".join(lines)


def no_rules_answer(ranking: Ranking) -> str:
    names = ", ".join(u.display for u in ranking.unknown)
    return (
        f"{spend_phrase(ranking)}: aapke cards ({names}) ke verified rules mere paas abhi nahi "
        "hain, isliye main andaaza nahi lagaungi. Apne card app me offers dekh lijiye."
    )


def outcome_buttons(entry_id: str) -> list[tuple[str, str]]:
    return [
        (f"led:{entry_id}:used", "Isse pay kiya"),
        (f"led:{entry_id}:other", "Doosra card"),
        (f"led:{entry_id}:skip", "Nahi kharida"),
    ]


OUTCOME_USED = "Note kar liya. Ye is mahine ke bachat ke hisaab me ginungi."
OUTCOME_OTHER = "Theek hai, ye bachat me nahi ginungi."
OUTCOME_SKIP = "Theek hai, kuch note nahi kiya."
OUTCOME_ALREADY = "Ye pehle hi note ho chuka hai, dobara nahi ginungi."
OUTCOME_UNKNOWN = "Ye sawaal mujhe nahi mila. Naya sawaal puchh lijiye."

# ------------------------------------------------------------------ wallet


def wallet_added(new: list[str], dup: list[str], unclear: list[str], no_rules: list[str]) -> str:
    parts = []
    if new:
        parts.append("Maine note kiya: " + ", ".join(new) + ". Sirf bank aur card ka naam save hua hai.")
    if dup:
        parts.append("Ye pehle se the: " + ", ".join(dup) + ".")
    if unclear:
        parts.append(
            "In ka card ka naam samajh nahi aaya: " + ", ".join(unclear)
            + ". Bank ke saath card ka naam bhi likhiye, jaise 'HDFC Regalia'."
        )
    if no_rules:
        parts.append(
            "In cards ke verified rules abhi mere paas nahi hain: " + ", ".join(no_rules)
            + ". Inke liye main andaaza nahi lagaungi."
        )
    if new:
        parts.append("Galat ho to likhiye 'SBI Cashback hata do'.")
    return " ".join(parts)


def wallet_removed(name: str) -> str:
    return f"Hata diya: {name}."


def wallet_not_found(query: str) -> str:
    return f"'{query}' naam ka card aapke wallet me nahi mila. 'mere cards' likhkar list dekh lijiye."


def wallet_ambiguous(query: str, names: list[str]) -> str:
    return f"'{query}' se ek se zyada cards mile: {', '.join(names)}. Poora naam likhiye."


WALLET_EMPTY = "Abhi aapne koi card nahi bataya. Jaise likhiye: 'mere paas HDFC Regalia hai'."


def wallet_list(cards: list[str], usual: str | None) -> str:
    body = "\n".join(f"- {c}" for c in cards)
    tail = f"\nUsual card: {usual}." if usual else ""
    return f"Aapke cards (sirf naam):\n{body}{tail}"


def usual_set(name: str) -> str:
    return f"Theek hai, {name} aapka usual card hai. Bachat isi se compare hoke ginungi."


# ------------------------------------------------------------------ bills

_KIND_NAME = {
    "electricity": "Bijli",
    "gas": "Gas",
    "water": "Paani",
    "broadband": "Broadband",
    "mobile": "Mobile",
    "dth": "DTH",
    "credit_card": "Credit card",
    "other": "",
}
BILL_BUTTON_OK = "Sahi hai"
BILL_BUTTON_NO = "Galat hai"
BILL_BUTTON_PAID = "Paid"
BILL_BUTTON_SNOOZE = "Snooze"
BILL_BUTTON_NOTMINE = "Not mine"


def _amount(bill: Bill) -> str:
    return format_rs(bill.amount_paise) if bill.amount_paise is not None else "amount pata nahi"


def bill_title(bill: Bill) -> str:
    kind = _KIND_NAME.get(bill.kind.value, "")
    if kind and kind.lower() not in bill.biller.lower():
        return f"{bill.biller} ({kind})"
    return bill.biller


def bill_confirm(bill: Bill) -> tuple[str, list[tuple[str, str]]]:
    extra = f" Minimum due {format_rs(bill.min_due_paise)}." if bill.min_due_paise else ""
    link = "" if not bill.pay_link else " Pay link bhi mila hai (aap khud pay karenge)."
    text = (
        f"Maine ye samjha: {bill_title(bill)} bill, {_amount(bill)}, due {date_phrase(bill.due_date)}."
        f"{extra}{link} Sahi hai? Sahi hone par 3 din pehle, 1 din pehle aur due date ke din yaad "
        "dilaungi."
    )
    from friday.savings.bills import bill_button_id

    return text, [
        (bill_button_id(bill.id, "ok"), BILL_BUTTON_OK),
        (bill_button_id(bill.id, "notmine"), BILL_BUTTON_NO),
    ]


def bill_need_due(missing: list[str]) -> str:
    return (
        "Is bill me due date mujhe nahi mili. Bill dobara forward kariye, ya likhiye jaise "
        "'bijli bill Rs 1240 due 25 Oct'."
        if "due_date" in missing
        else "Bill samajh nahi aaya. Due date aur amount ke saath dobara bhejiye."
    )


BILL_CONFIRMED = "Theek hai, bill yaad rakhungi. Pay aap khud karenge, main sirf yaad dilaungi."


def bill_confirmed(bill: Bill) -> str:
    link = f" Pay link: {bill.pay_link}" if bill.pay_link else ""
    return f"{BILL_CONFIRMED}{link}"


def bill_reminder_reason(bill: Bill, days_left: int) -> str:
    return (
        f"aapne {bill_title(bill)} ka bill add kiya tha aur uski due date "
        f"{date_phrase(bill.due_date)} ({when_phrase(days_left)}) hai"
    )


def bill_reminder_message(bill: Bill, days_left: int) -> tuple[str, list[tuple[str, str]]]:
    from friday.savings.bills import bill_button_id

    when = when_phrase(days_left)
    if days_left < 0:
        line = f"{bill_title(bill)} bill ({_amount(bill)}) ki due date {date_phrase(bill.due_date)} nikal chuki hai."
    else:
        line = f"{bill_title(bill)} bill {_amount(bill)} {when} due hai ({date_phrase(bill.due_date)})."
    if bill.pay_link:
        pay = f"Pay link: {bill.pay_link}\nPay aap khud karenge, Friday pay nahi karti."
    else:
        pay = "Pay karne ke liye apni biller app ya UPI app use kijiye. Friday pay nahi karti."
    return f"{line}\n{pay}", [
        (bill_button_id(bill.id, "paid"), BILL_BUTTON_PAID),
        (bill_button_id(bill.id, "snooze"), BILL_BUTTON_SNOOZE),
        (bill_button_id(bill.id, "notmine"), BILL_BUTTON_NOTMINE),
    ]


def bill_paid(bill: Bill) -> str:
    return f"Theek hai, {bill_title(bill)} bill paid mark kar diya."


def bill_snoozed(hour: int) -> str:
    return f"Theek hai, kal subah {hour} baje phir yaad dilaungi."


BILL_DISMISSED = "Theek hai, ye bill hata diya. Galti se hata ho to bill phir forward kar dijiye."
BILL_UNKNOWN = "Ye bill mujhe nahi mila. 'meri bills' likhkar list dekh lijiye."
BILLS_NONE = "Abhi koi bill yaad rakhne ke liye nahi hai. Bill forward kijiye, main due date note kar lungi."


def bills_list(bills: list[Bill], today: date) -> str:
    lines = ["Aapki bills:"]
    for b in bills:
        left = (b.due_date - today).days
        flag = " (due date nikal gayi)" if left < 0 else ""
        status = " [snoozed]" if b.status.value == "snoozed" else ""
        lines.append(
            f"- {bill_title(b)}: {_amount(b)}, due {date_phrase(b.due_date)} ({when_phrase(left)}){flag}{status}"
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ savings summary

_BASELINE_TEXT = {
    "usual_card": "aapke usual card ka reward",
    "next_best": "aapke doosre best card ka reward",
    "none": "koi doosra card nahi",
}


def monthly_summary(s: MonthlySummary) -> str:
    if s.counted == 0:
        tail = (
            f" {s.awaiting_answer} sawaal abhi jawab ka intezaar kar rahe hain."
            if s.awaiting_answer
            else ""
        )
        return (
            "Is mahine abhi tak aapne koi bachat confirm nahi ki, isliye main koi figure nahi "
            f"bata rahi.{tail}"
        )
    base = " ya ".join(_BASELINE_TEXT[b] for b in s.baselines) or _BASELINE_TEXT["none"]
    extra = ""
    if s.low_confidence_not_counted:
        extra = (
            f" {s.low_confidence_not_counted} entry nahi gini kyunki unka rule purana ya "
            "unconfirmed tha."
        )
    return (
        f"Friday ne is mahine {format_rs(s.saved_paise)} bachaye. Ye sirf {s.counted} baar ka hai "
        "jab aapne khud bataya ki aapne meri batayi hui card use ki. "
        f"Hisaab: meri batayi card ka reward minus {base}.{extra}"
    )
