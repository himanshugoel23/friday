"""Word lists for the deterministic NLU (English / Hindi / Hinglish)."""

from __future__ import annotations

from friday.core.models import CareRequestKind

COMPANIES: dict[str, str] = {
    "airtel": "Airtel", "jio": "Jio", "reliance jio": "Jio", "vodafone": "Vi", "vi": "Vi",
    "bsnl": "BSNL", "act fibernet": "ACT Fibernet", "act": "ACT Fibernet", "hathway": "Hathway",
    "tata play": "Tata Play", "hdfc": "HDFC Bank", "hdfc bank": "HDFC Bank", "icici": "ICICI Bank",
    "sbi": "SBI", "axis": "Axis Bank", "kotak": "Kotak Mahindra Bank", "amazon": "Amazon",
    "flipkart": "Flipkart", "swiggy": "Swiggy", "zomato": "Zomato", "myntra": "Myntra",
    "indigo": "IndiGo", "air india": "Air India", "bescom": "BESCOM", "tata power": "Tata Power",
    "adani electricity": "Adani Electricity", "lic": "LIC", "paytm": "Paytm",
    "phonepe": "PhonePe", "uber": "Uber", "ola": "Ola", "makemytrip": "MakeMyTrip",
    "irctc": "IRCTC", "star health": "Star Health", "acko": "Acko", "bajaj": "Bajaj Finserv",
}

CARE_WORDS = ("customer care", "customer service", "complaint", "refund", "ticket", "dispute",
              "not working", "band hai", "down", "outage", "chargeback", "escalate",
              "raise a complaint", "cancel my subscription", "cancel subscription",
              "disconnect", "wrong charge", "overcharged", "deducted", "kat gaye", "helpline",
              "service request", "broadband", "connection", "kharab", "issue", "problem")

CARE_KIND_WORDS: list[tuple[CareRequestKind, tuple[str, ...]]] = [
    (CareRequestKind.REFUND, ("refund", "money back", "paise wapas", "credit", "reimburse")),
    (CareRequestKind.DISPUTE, ("dispute", "chargeback", "wrong charge", "fraud transaction")),
    (CareRequestKind.CANCELLATION, ("cancel my", "cancel subscription", "disconnect",
                                    "close my account", "port out", "band karwa")),
    (CareRequestKind.ESCALATION, ("escalate", "supervisor", "grievance", "nodal")),
    (CareRequestKind.TICKET_STATUS, ("status of", "ticket status", "complaint status",
                                     "what happened to my complaint")),
    (CareRequestKind.SERVICE_REQUEST, ("new connection", "upgrade", "change plan", "shift",
                                       "address change", "service request")),
    (CareRequestKind.COMPLAINT, ("complaint", "not working", "down", "band hai", "outage",
                                 "kharab", "issue", "problem")),
]

# category -> trigger words (first match wins; order matters)
CATEGORIES: list[tuple[str, tuple[str, ...]]] = [
    ("ac repair", ("ac repair", "ac service", "ac servicing", "ac mechanic", "ac guy",
                   "ac technician", "ac not cooling", "ac isn't cooling", "ac is not cooling",
                   "split ac", "air conditioner", "ac thanda nahi", "ac kharab")),
    ("packers and movers", ("packers", "movers", "shifting", "relocation")),
    ("salon", ("salon", "parlour", "parlor", "haircut", "hair cut", "barber", "facial",
               "spa", "beard trim", "hair colour", "manicure")),
    ("dentist", ("dentist", "dental", "teeth cleaning", "root canal")),
    ("cardiologist", ("cardiologist", "heart doctor", "heart specialist")),
    ("physiotherapist", ("physio", "physiotherapist", "physiotherapy")),
    ("diagnostic lab", ("lab test", "blood test", "home collection", "thyroid test",
                        "diagnostic", "pathology", "lab ")),
    ("nursing", ("nurse", "attendant", "caretaker")),
    ("clinic", ("doctor", "dr.", "dr ", "clinic", "checkup", "check-up", "consultation",
                "paediatrician", "pediatrician", "gynaec", "dermatologist", "ent ")),
    ("pharmacy", ("pharmacy", "chemist", "medical store", "medicine", "dawai", "dawa",
                  "tablet", "insulin", "dolo", "paracetamol", "syrup")),
    ("restaurant", ("restaurant", "table for", "dinner", "lunch reservation", "cafe",
                    "dhaba", "table book")),
    ("plumber", ("plumber", "plumbing", "tap", "leak", "pipe", "nal ")),
    ("electrician", ("electrician", "wiring", "fan repair", "switchboard", "light fitting")),
    ("carpenter", ("carpenter", "furniture repair", "door repair")),
    ("water supplier", ("water can", "water cans", "bisleri", "paani ki can", "water jar")),
    ("tiffin service", ("tiffin", "dabba", "meal service")),
    ("kirana", ("kirana", "grocery", "groceries", "atta", "ration")),
    ("tailor", ("tailor", "darzi", "blouse", "stitching", "alteration")),
    ("dry cleaner", ("dry clean", "dry cleaner", "laundry", "ironing")),
    ("mobile repair", ("phone repair", "mobile repair", "screen replacement")),
    ("car service", ("car service", "car wash", "mechanic", "garage", "bike service")),
    ("tutor", ("tutor", "tuition", "coaching", "classes for")),
    ("gym", ("gym", "fitness", "yoga class", "zumba")),
    ("school", ("school admission", "admission")),
    ("wedding vendor", ("caterer", "catering", "decorator", "photographer", "wedding venue",
                        "banquet", "venue")),
    ("interior designer", ("interior", "modular kitchen", "carpentry work")),
    ("rental broker", ("broker", "landlord", "1bhk", "2bhk", "3bhk", "flat on rent",
                       "house on rent", "pg ")),
    ("hotel", ("hotel", "homestay", "home stay", "guesthouse", "guest house", "resort",
               "stay in", "room for")),
]

DELEGATION_PHRASES = (
    "you decide", "your call", "your choice", "decide yourself", "decide for me",
    "just book", "book it directly", "go ahead and book", "book directly", "directly book",
    "no need to ask", "don't ask me", "dont ask me", "without asking", "without checking",
    "no need to check", "don't check with me", "dont check with me", "you can confirm",
    "confirm it yourself", "confirm directly", "whatever is free", "whatever's free",
    "jo bhi free ho", "jo free ho", "jo mile", "aap decide", "tum decide", "khud decide",
    "aap hi decide", "decide kar lo", "decide kar lena", "mujhse mat poocho",
    "mujhse mat pucho", "mujhse puchne ki zaroorat nahi", "poochne ki zaroorat nahi",
    "puchne ki zarurat nahi", "seedha book", "sidha book", "direct book", "book kar hi dena",
    "confirm kar dena", "confirm kar hi dena", "book kar dena bina", "bina puche",
    "bina pooche", "any slot", "koi bhi slot", "book any",
)

SMALL_TALK = ("hi", "hello", "hey", "hii", "namaste", "namaskar", "good morning",
              "good evening", "good night", "thanks", "thank you", "thx", "shukriya",
              "dhanyavaad", "how are you", "kaise ho", "kya haal", "ok thanks", "cool", "nice",
              "great", "👍", "🙏", "नमस्ते", "धन्यवाद", "शुक्रिया", "हेलो")

SECRET_WORDS = ("otp", "one time password", "pin", "mpin", "upi pin", "cvv", "cvc", "password",
                "passcode", "card number", "card no", "atm pin", "aadhaar", "aadhar", "pan card")
