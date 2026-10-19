# ruff: noqa: E501
"""Deterministic reading of what the callee just said (Hinglish, Hindi, English).

No model, no network: ordered regex banks. The result is a closed ``CalleeIntent`` plus entities
(times, amounts, names) taken from the callee's own words, and a confidence that the engine logs.
Order matters: safety intents (distress, stop, wrong number, abuse, "are you a bot") are tested
before everything else so a stop request inside a longer sentence is never missed. An utterance that
matches nothing is ``unknown`` and the engine answers it with a safe clarifying move.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

from pydantic import BaseModel, Field

from friday.liveagent.ports import HeardUtterance


class CalleeIntent(StrEnum):
    # --- hard stops
    STOP_CALLING = "stop_calling"  # includes "I don't talk to bots" / "give me a human"
    WRONG_NUMBER = "wrong_number"
    DISTRESS = "distress"
    HOSTILE = "hostile"
    # --- identity and honesty
    WHO_IS_THIS = "who_is_this"
    ARE_YOU_AI = "are_you_ai"
    # --- availability
    BUSY_CALL_BACK_LATER = "busy_call_back_later"
    ASKS_TO_WAIT = "asks_to_wait"  # "ek minute", "hold on" (a human)
    ASKS_TO_REPEAT = "asks_to_repeat"
    # --- questions to Friday
    ASKS_ABOUT_USER = "asks_about_user"  # topic says what; shareable or private decided by brief
    ASKS_MONEY = "asks_money"  # asks the user to pay / send money
    ASKS_PERSONAL_DETAILS = "asks_personal_details"  # detail: secret | identity
    PROPOSES_COMMITMENT = "proposes_commitment"  # "pakka?", "6 baje aa jana", "book kar do"
    # --- replies
    AGREES = "agrees"
    REFUSES = "refuses"  # detail "bare_no" for a plain no (may just be an answer)
    GIVES_ANSWER = "gives_answer"  # a substantive reply (carries entities)
    OFF_TOPIC = "off_topic"
    # --- line signals
    SILENCE = "silence"
    VOICEMAIL_BEEP = "voicemail_beep"  # detail: greeting | beep
    UNREACHABLE = "unreachable"  # carrier recording: switched off / not reachable
    IVR_MENU = "ivr_menu"
    HOLD_MUSIC = "hold_music"
    UNKNOWN = "unknown"


HARD_STOP_INTENTS = frozenset(
    {
        CalleeIntent.STOP_CALLING,
        CalleeIntent.WRONG_NUMBER,
        CalleeIntent.DISTRESS,
        CalleeIntent.HOSTILE,
    }
)


class Entities(BaseModel):
    times: list[str] = Field(default_factory=list)  # normalised time phrases ("kal shaam 5 baje")
    amounts: list[str] = Field(default_factory=list)  # as heard ("500 rupay")
    names: list[str] = Field(default_factory=list)
    visit: bool = False
    booking: bool = False


class Understanding(BaseModel):
    intent: CalleeIntent
    confidence: float
    text: str  # the callee's words (raw)
    matched: str = ""  # the phrase that decided it
    detail: str | None = None
    topic: str | None = None  # for asks_about_user / asks_personal_details
    entities: Entities = Field(default_factory=Entities)
    flags: list[str] = Field(default_factory=list)  # wants_english | wants_hindi | health_mention
    stt_confidence: float | None = None
    audio_class: str = "human"


# ------------------------------------------------------------------ helpers

_DEV = "ऀ-ॿ"
_L = rf"(?<![\w{_DEV}])"
_R = rf"(?![\w{_DEV}])"


def _rx(*alts: str) -> re.Pattern[str]:
    """Alternatives (regex text, spaces mean any whitespace) matched as whole words."""
    body = "|".join(a.replace(" ", r"\s+") for a in alts).replace("\\??", "").replace("\\?", "")
    return re.compile(_L + "(?:" + body + ")" + _R, re.I)


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.replace("’", "'")
    t = re.sub(rf"[^\w{_DEV}'₹]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ------------------------------------------------------------------ banks

_DISTRESS = _rx(
    "bachao",
    "bachaao",
    "meri madad karo",
    "madad karo",
    "help me",
    "help help",
    "emergency",
    "ambulance",
    "heart attack",
    "chest pain",
    "seene mein dard",
    "seene me dard",
    "saans nahi",
    "saans nahin aa",
    "can'?t breathe",
    "cannot breathe",
    "gir gaya",
    "gir gayi",
    "gir gaye",
    "chakkar aa",
    "behosh",
    "mar jaunga",
    "mar jaungi",
    "mujhe darr lag",
    "khatre mein",
    "i am in danger",
    "i'm in danger",
    "someone is hurting",
    "fell down",
    "i fell",
    "need an ambulance",
    "bachaiye",
    "dil mein dard",
    "bohot dard ho raha",
    "bahut dard ho raha",
    "marne wala",
    "बचाओ",
    "मदद करो",
    "मेरी मदद",
    "सीने में दर्द",
    "साँस नहीं",
    "सांस नहीं",
    "गिर गया",
    "गिर गई",
    "चक्कर आ",
    "बेहोश",
    "एम्बुलेंस",
    "एंबुलेंस",
    "दिल में दर्द",
)
_STOP = _rx(
    "(call|phone|fone) mat (karo|karna|kijiye|kariye|kijiyega|karein)",
    "mat (call|phone|fone) (karo|karna|kijiye|kariye)",
    "dobara (call|phone|fone) (mat|na)",
    "dubara (call|phone|fone) (mat|na)",
    "dobara mat (call|phone)",
    "phir se (call|phone) mat",
    "(call|phone|fone) na kar(o|na|iye)",
    "dobara (is )?number (par|pe|per) (call )?mat",
    "bar bar (call|phone) mat",
    "baar baar (call|phone) mat",
    "stop calling",
    "stop call",
    "don'?t call( me| us)?( again)?",
    "do not call( me| us)?( again)?",
    "never call( me| us)?( again)?",
    "please stop( calling)?",
    "stop (it|this)",
    "remove (my|this) number",
    "number (hata|delete|remove|block)\\w*",
    "block (kar|this|my)\\w*",
    "blacklist",
    "\\bdnd\\b",
    "do not disturb",
    "pareshan mat",
    "harass(ing|ment)?",
    "complaint (kar|karunga|karungi|dar)\\w*",
    "police (ko|mein|me)\\b",
    "report (kar|karunga|karungi)",
    # no bots / wants a human
    "(bot|bots|robot|robots|machine|computer|ai|recording) se (mujhe )?(baat|bat|baatein|batein) (nahi|nahin|mat)",
    "(bot|bots|robot|robots|machine|ai) se (baat|bat) (karni )?(nahi|nahin|mat)",
    "(don'?t|do not|not) (want|wish|like) to (talk|speak|chat) (to|with) (a |an )?(bot|robot|machine|ai|computer|recording)",
    "(don'?t|do not) (talk|speak) (to|with) (a |an )?(bot|bots|robot|robots|machine|machines|ai|computers?)",
    "no (bots|robots|robot calls|ai calls)",
    "i hate (bots|robots)",
    "(kisi )?(insaan|insan|aadmi|admi|human|asli (aadmi|insaan)) se (hi )?(baat|bat) (karni|karna|karunga|karungi|karwao|karao)",
    "(i want|i need|let me talk to|put me through to|connect me to) (a |an |to )?(real |actual )?(human|person|man|woman|someone real)",
    "(real|actual) (human|person) (se )?(baat|bat|please)",
    "kisi insaan ko do",
    "insaan ko phone do",
    "asli insaan",
    "कॉल मत",
    "फोन मत",
    "फ़ोन मत",
    "दोबारा कॉल",
    "दुबारा कॉल",
    "दोबारा फोन मत",
    "फोन न करें",
    "कॉल न करें",
    "बॉट से बात नहीं",
    "रोबोट से बात नहीं",
    "मशीन से बात नहीं",
    "इंसान से बात",
    "नंबर हटा",
    "डू नॉट कॉल",
    "तंग मत",
    "परेशान मत",
)
_WRONG = _rx(
    "wrong number",
    "galat number",
    "ghalat number",
    "number galat",
    "yeh (mera )?number (unka|iska|uska) nahi",
    "yahan (koi )?[\\w ]{0,20}nahi (rehta|rahta|rehte|rahte|hai)",
    "yaha (koi )?[\\w ]{0,20}nahi (rehta|rahta|rehte|rahte)",
    "is naam (ka|ke|ki) (koi )?nahi",
    "koi (is )?naam (ka|ke|ki)? ?nahi",
    "is naam ka koi",
    "aap (kisko|kise|kis se|kisse) (dhoondh|dhundh|call)",
    "kisko (phone|call) kiya",
    "maine (kisi ko )?nahi (jaanta|jaanti|janta|janti)",
    "main (unhe|unko|inhe|inko) (nahi|nahin) (jaanta|jaanti|janta|janti)",
    "(nobody|no one) (here )?(by|with) that name",
    "you (have|got) the wrong number",
    "(this is|it is|it's) not (his|her|their|that) number",
    "i don'?t know (anyone|any one|who that is)",
    "you've dialed the wrong",
    "you have dialed the wrong",
    "no such person",
    "yahan koi nahi",
    "रॉन्ग नंबर",
    "रोंग नंबर",
    "गलत नंबर",
    "ग़लत नंबर",
    "यहाँ कोई",
    "यहां कोई",
    "इस नाम का कोई",
    "मैं उन्हें नहीं जानता",
    "मैं उन्हें नहीं जानती",
)
_HOSTILE = _rx(
    "bakwas",
    "bewakoof",
    "bevakoof",
    "pagal (hai|ho|ho gaye|ho gayi) kya",
    "chutiya",
    "chutiye",
    "madarchod",
    "bhenchod",
    "behenchod",
    "harami",
    "kameena",
    "kamina",
    "kutta",
    "kutte",
    "saala",
    "saali",
    "gandu",
    "bhosad\\w*",
    "randi",
    "gaali",
    "gali dunga",
    "gali dungi",
    "tameez (se|nahi)",
    "shut up",
    "shut it",
    "fuck\\w*",
    "bastard",
    "idiot",
    "stupid",
    "get lost",
    "go to hell",
    "piss off",
    "damn you",
    "nikal (jao|ja|yahan se)",
    "chup (kar|ho jao|raho)",
    "phone rakh",
    "fone rakh",
    "kaat do phone",
    "kaatna hai phone",
    "band kar (phone|bakwas)",
    "tere ko",
    "teri maa",
    "tumhari maa",
    "hang up (the )?phone",
    "stop (this )?nonsense",
    "nonsense",
    "scammer",
    "fraud (hai|call)",
    "thug",
    "चुप",
    "बकवास",
    "बेवकूफ",
    "पागल है क्या",
    "हरामी",
    "कमीना",
    "गाली",
    "निकल जा",
    "फोन रख",
    "फ़ोन रख",
    "गेट लॉस्ट",
)
_ARE_AI = _rx(
    "(are|r) (you|u) (a |an )?(ai|a\\.i\\.|bot|robot|machine|computer|human|real|real person|real human|person|recording|recorded|automated|artificial)",
    "is this (a |an )?(ai|bot|robot|machine|computer|recording|recorded|automated|real person|human)",
    "(am i|are we) (talking|speaking) (to|with) (a |an )?(ai|bot|robot|machine|computer|human|real person|person)",
    "(ai|bot|robot|machine|computer|automated|artificial intelligence|recorded)( hai| ho| hain)?( kya| na)?\\??$",
    "(robot|bot|machine|computer|ai|recording|recorded) (hai|ho|hain|bol)",
    "(aap|tum|tu|app) (robot|bot|machine|computer|ai|insaan|insan|human|asli|real)",
    "(insaan|insan|human|aadmi|admi|ladki|real|asli) (ho|hai|hain) (ya|kya)",
    "(kya|ya) (aap|tum) (insaan|insan|human|real|asli|ladki|robot|bot|machine|ai)",
    "real (person|human) (ho|hai|hain)",
    "recorded (message|voice|call) (hai|ho)",
    "automated (call|message|voice)",
    "artificial intelligence",
    "(machine|computer|recording) (se )?(baat|bol)",
    "kya (yeh|ye) (robot|bot|machine|recording|ai)",
    "koi (insaan|insan|aadmi|admi|ladki) (hai|bol|hain)",
    "are you real",
    "you sound like (a |an )?(robot|machine|bot|recording|ai)",
    "robot jaisi",
    "machine jaisi",
    "recording jaisi",
    "रोबोट",
    "रोबोट है",
    "बॉट",
    "मशीन है",
    "मशीन से",
    "कंप्यूटर",
    "इंसान हो",
    "इंसान है",
    "असली",
    "रिकॉर्डेड",
    "ए आई",
    "एआई",
)
_WHO = _rx(
    "kaun( bol| baat| hai| ho| hain|\\?|$)",
    "kaun (sa|si|se) number",
    "kaun (bol|baat) (raha|rahi|rahe)",
    "aap kaun",
    "tum kaun",
    "kon (bol|hai|ho|baat)",
    "kon hai",
    "kisne (phone|call|fone) kiya",
    "kisse baat",
    "kya naam hai (aapka|tumhara)",
    "aapka naam",
    "aap kahan se",
    "kahan se (bol|baat|call|phone)",
    "kis (company|firm|office|bank|department) se",
    "kis liye (phone|call) kiya",
    "kya (kaam|chahiye|baat) hai",
    "kaise phone kiya",
    "kyun (phone|call) kiya",
    "kyu (phone|call) kiya",
    "who is (this|it|speaking|calling)",
    "who'?s (this|that|speaking|calling)",
    "who are you",
    "who am i (speaking|talking) (to|with)",
    "who (is )?this",
    "who this",
    "may i know who",
    "what is this (about|regarding|call)",
    "which (company|number|bank) is this",
    "where are you calling from",
    "why (are you|did you) call(ing)?",
    "what do you want",
    "कौन",
    "आप कौन",
    "कौन बोल",
    "कौन बात",
    "किसने फोन",
    "किसने फ़ोन",
    "क्या नाम है",
    "कहाँ से बोल",
    "कहां से बोल",
    "किस कंपनी",
    "क्यों फोन",
    "क्या काम है",
    "क्या चाहिए",
)
_BUSY = _rx(
    "busy (hoon|hu|hun|hai|hain|hu abhi|abhi)",
    "main busy",
    "abhi busy",
    "bahut busy",
    "abhi (time|samay|fursat) nahi",
    "time nahi hai",
    "fursat nahi",
    "baad (mein|me|main) (call|phone|baat|karna|karo|karein|kariye|kijiye)",
    "baad mein (baat|bol|bataunga|batati)",
    "thodi der (baad|mein|me) (call|phone|baat)",
    "thodi der baad",
    "(call|phone) (karna|karo|kijiye|kariye) (baad|shaam|kal|subah|raat)",
    "(kal|shaam|subah|raat) ko (call|phone|baat)",
    "dobara (call|phone) (karna|karo|kijiye|kariye) (baad|shaam|kal|subah)",
    "meeting (mein|me|main) (hoon|hu|hun|hai)",
    "meeting chal",
    "in (a )?meeting",
    "driving",
    "gaadi chala",
    "gadi chala",
    "drive kar (raha|rahi)",
    "khana kha (raha|rahi)",
    "(can|could) you (please )?call (me )?(back|later)",
    "call (me )?(back )?later",
    "i'?m (busy|in a meeting|driving|at work)",
    "not (a good|the right) time",
    "bad time",
    "talk later",
    "call (me )?tomorrow",
    "call back (later|tomorrow|in)",
    "i'?ll call you back",
    "abhi baat nahi (ho|kar) sakta",
    "abhi baat nahi (ho|kar) sakti",
    "later please",
    "बिज़ी",
    "बिजी",
    "व्यस्त",
    "बाद में कॉल",
    "बाद में फोन",
    "बाद में बात",
    "अभी समय नहीं",
    "मीटिंग में",
    "थोड़ी देर बाद",
    "अभी नहीं",
)
_WAIT = _rx(
    "ek (minute|min|second|sec|pal|moment)",
    "1 (minute|min|second|sec)",
    "ruko",
    "ruk(iye|iyega|o)( zara)?",
    "zara ruk",
    "thoda (ruko|ruk|wait|intezaar|intezar)",
    "hold (kar|karo|kijiye|on)",
    "wait (karo|kijiye|kariye|karna|a (minute|second|moment|sec|bit))",
    "hold on( a (minute|second|moment))?",
    "hang on",
    "one (second|minute|moment|sec)",
    "just a (minute|second|moment|sec)",
    "give me a (minute|second|moment)",
    "bas ek",
    "abhi (aata|aati|dekhta|dekhti|bulata|bulati) hoon",
    "bulata hoon",
    "bulati hoon",
    "dekh(ta|ti) hoon",
    "dekhta hu",
    "let me (check|see|call)",
    "please hold",
    "wait a (minute|second|moment)",
    "एक मिनट",
    "एक सेकंड",
    "रुको",
    "रुकिए",
    "होल्ड",
    "ज़रा रुक",
    "जरा रुक",
    "बस एक",
    "देखता हूँ",
    "देखती हूँ",
    "बुलाता हूँ",
    "बुलाती हूँ",
)
_REPEAT = _rx(
    "kya (kaha|bola|boli|kahा|bol rahe|bol rahi)",
    "kya\\??$",
    "phir se( bolo| boliye| bataiye| kaho| kahiye)?",
    "fir se( bolo| boliye| bataiye)?",
    "dobara( bolo| boliye| bataiye| kaho| kahiye)?",
    "ek baar (aur|phir)( bolo| boliye| bataiye)?",
    "sunai nahi",
    "awaaz (nahi|kam|saaf nahi|nhi)",
    "awaz (nahi|kam|saaf nahi)",
    "samajh nahi aaya",
    "samajh nahi aayi",
    "samjha nahi",
    "samjhi nahi",
    "kya bataya",
    "kuch (suna|sunai) nahi",
    "thoda dheere",
    "dheere (bolo|boliye|bataiye)",
    "zor se (bolo|boliye)",
    "zara zor se",
    "louder please",
    "speak (up|louder|slowly)",
    "(can|could) you (please )?(repeat|say (that|it) again)",
    "(say|repeat) (that )?(again|once more|please)",
    "pardon( me)?",
    "sorry\\?",
    "excuse me\\?",
    "come again",
    "what did you say",
    "what was that",
    "i (can'?t|cannot|couldn'?t) (hear|understand)( you)?",
    "didn'?t (hear|catch|get) (that|you)",
    "what\\??$",
    "huh\\??$",
    "hello hello",
    "क्या कहा",
    "क्या बोला",
    "फिर से",
    "दोबारा बोल",
    "दोबारा बताइए",
    "सुनाई नहीं",
    "आवाज़ नहीं",
    "आवाज नहीं",
    "समझ नहीं आया",
    "समझ नहीं आई",
    "धीरे बोल",
    "ज़ोर से बोल",
    "क्या\\??$",
)
_ABOUT_USER = _rx(
    "(woh|wo|voh|vo|unhone|unho ne|unka|unki|unke|inka|inki|inke|uska|uski|uske) [\\w ]{0,30}(kahan|kab|kyun|kyu|kya|kaisa|kaisi|kaise|kitna|kitne|kitni|number|address|pata)",
    "(kahan|kaha|kidhar) (hain|hai|ho|rehte|rahte|gaye|gaya|gayi|hain woh)",
    "kab (aayenge|aayega|aayegi|aa rahe|aa raha|aa rahi|milenge|free hain|free hai|tak)",
    "khud (kyun|kyu) (nahi|call)",
    "khud (call|phone|baat) (kyun|kyu|kar)",
    "(unka|unki|uska|uski|inka|inki) (naam|number|pata|address|job|kaam|salary|umar|age|company|health|tabiyat)",
    "kya (karte|karta|karti|kar rahe|kar raha|kar rahi) hain?",
    "kaise hain (woh|wo|unki|unka)",
    "unki tabiyat",
    "kahan (kaam|job) karte",
    "kitna (kamate|kamata|kamati|salary)",
    "kya kaam karte",
    "shaadi",
    "shadi (hui|ho gayi|kab)",
    "is (he|she) (ok|okay|fine|well|home|there|free|available)",
    "where (is|are) (he|she|they|your (boss|owner)|[\\w ]{1,20})",
    "when (will|is|can) (he|she|they)",
    "what (does|do) (he|she|they) do",
    "why (didn'?t|doesn'?t|can'?t|won'?t) (he|she|they)",
    "(his|her|their) (number|address|name|job|salary|age|health|phone|location|email|work)",
    "how (is|are) (he|she|they)",
    "tell me about (him|her|them)",
    "where do (he|she|they) (live|work|stay)",
    "who (is|are) (he|she|they)",
    "who sent you",
    "वो कहाँ",
    "वह कहाँ",
    "वो कहां",
    "उनका नंबर",
    "उनका पता",
    "उनकी तबीयत",
    "कब आएँगे",
    "कब आएंगे",
    "खुद क्यों",
    "क्या करते हैं",
    "कहाँ रहते",
    "कहां रहते",
)
_MONEY = _rx(
    "(paise|paisa|rupay|rupaye|rupee|rupees|rs|amount|advance|token|deposit|payment|fees?|charges?|raashi|rakam) [\\w ]{0,25}\\b(bhej|bhejo|bhejiye|bhejna|bhej do|de do|dena|dijiye|de dijiye|do|transfer|pay|jama|chahiye|dena padega|karna padega)",
    "(bhej|bhejo|bhejiye|de do|dijiye|transfer|jama|pay) (kar )?[\\w ]{0,15}(paise|paisa|rupay|rupaye|amount|advance|payment|money|fees?)",
    "(upi|gpay|google pay|phonepe|phone pe|paytm|bhim|net ?banking|neft|imps|qr code|qr) [\\w ]{0,20}(kar|bhej|karo|karein|karna|karwa|se|par|pe|id|number|scan)",
    "(scan|pay|send|transfer|give|wire|lend) (me |us |him |her )?[\\w ]{0,10}(money|cash|rupees|amount|advance|payment|fees?|deposit)",
    "(need|want|require) (some )?(money|cash|an advance|advance|payment|a deposit|deposit)",
    "can you (pay|send|transfer|lend)",
    "will you pay",
    "pay (first|now|upfront|in advance)",
    "advance (do|dena|chahiye|dijiye|bhejo|payment)",
    "udhaar",
    "udhar (de|chahiye|do)",
    "loan (de|do|chahiye)",
    "paise (chahiye|bhejo|de do|dena|bhej do|udhaar)",
    "paise de (do|dijiye|dena)",
    "recharge (kara|karwa|kar) do",
    "token amount",
    "booking amount",
    "paise (bhej|do)",
    "pehle (paise|payment|advance)",
    "pehle pay",
    "पैसे (भेज|दे|चाहिए|दो|ट्रांसफर)",
    "(भेज|दे|ट्रांसफर) ?(दो|दीजिए|कर).{0,15}पैसे",
    "पैसे.{0,20}(भेज|दे दो|चाहिए)",
    "पैसा (भेज|दे|चाहिए|दो)",
    "एडवांस",
    "पेमेंट (कर|करो|करना|भेज)",
    "यूपीआई",
    "उधार",
    "रिचार्ज करा",
)
_SECRET = _rx(
    "o\\.?t\\.?p",
    "one time (password|pin|code)",
    "\\bcvv\\b",
    "\\bcvc\\b",
    "\\bm?pin\\b",
    "pin number",
    "pin (batao|bataiye|do|dijiye|bata)",
    "password",
    "passcode",
    "card number",
    "card (ka )?number",
    "card details",
    "debit card",
    "credit card",
    "expiry",
    "aadhaar|aadhar|adhaar|adhar",
    "\\bpan (card|number)",
    "net ?banking (id|password|login)",
    "verification code",
    "security code",
    "secret code",
    "upi pin",
    "atm pin",
    "card ke (peeche|pichhe)",
    "ओटीपी",
    "ओ टी पी",
    "पिन",
    "पासवर्ड",
    "सीवीवी",
    "कार्ड नंबर",
    "आधार",
    "पैन कार्ड",
    "कोड बताइए",
    "कोड बताओ",
)
_IDENTITY = _rx(
    "(date of birth|dob|birth ?date|birthday)",
    "janm ?(tithi|din|date)",
    "janmdin",
    "(registered|linked) (mobile|number|phone|email|mail|address)",
    "registered (number|mobile)",
    "(last|aakhri) (4|four|chaar|char|do|two|2|teen|three|3) (digits|ank)",
    "last 4",
    "account (number|no|nambar)",
    "customer (id|number)",
    "mother'?s? (maiden )?name",
    "father'?s? name",
    "(pita|papa) ka naam",
    "(mata|mummy|maa) ka naam",
    "(ghar|home|billing|permanent|current|residential) ?(ka )?address",
    "address (batao|bataiye|bata|do|dijiye|kya hai|confirm)",
    "(pin ?code|zip ?code|postal code)",
    "(security|secret) question",
    "verify (kar|your|his|her|the|account|identity|karna)",
    "verification",
    "authenti\\w+",
    "identity",
    "id proof",
    "(kyc|e-?kyc)",
    "email id",
    "(mobile|phone|contact|alternate) number (kya|batao|bataiye|do|dijiye|confirm|please|bata)",
    "(naam|name) (aur|and) (number|address|dob)",
    "full name",
    "जन्म ?(तिथि|दिन)",
    "रजिस्टर्ड (नंबर|मोबाइल)",
    "खाता नंबर",
    "अकाउंट नंबर",
    "पूरा नाम",
    "पता बताइए",
    "पता बताओ",
    "वेरिफ",
    "आईडी प्रूफ",
)
_COMMIT = _rx(
    "pakka( hai| karo| kar do| karein| kijiye| kariye| rahega| na)?",
    "pakka (kar|karo|karna)",
    "confirm (karo|kar do|kijiye|kariye|karein|kar dijiye|karna|hai)",
    "book (kar|karo|kijiye|kariye|karein|kar do|kar dijiye|karna)",
    "final (kar|karo|karein|kijiye|hai)",
    "done",
    "deal",
    "deal (hai|done|pakka)",
    "lock (kar|karo|it)",
    "aa (jana|jao|jaiye|jaoge|jaogi|jaiyega|jayenge|jayengi)",
    "aa (sakte|sakti|sakoge|sakogi) (ho|hain|hai)",
    "aayenge",
    "aaoge",
    "aaogi",
    "visit (karna|karo|kijiye|kariye|karein|kar lo)",
    "(ghar|home|site|shop|dukaan|office) (par|pe|per) (aana|aa|aayenge|aaoge)",
    "milne (aana|aa|aayenge|aaoge)",
    "pahunch (jana|jao|jaiye|jaoge|jaogi|jayenge)",
    "(will|can|could|would) you (come|visit|be there|pay|send|confirm|promise|commit|book|take|agree|give|do it)",
    "do you (confirm|promise|agree|commit)",
    "(please )?(confirm|book|promise|commit|guarantee|agree)( it| this| that| now| for me)?",
    "is that (a )?(deal|confirmed|final)",
    "shall we (finalise|finalize|book|confirm|fix)",
    "can we (fix|finalise|finalize|confirm|book)",
    "(promise|vaada|waada) (karo|kijiye|kar)",
    "(kal|aaj|parso|monday|tuesday|wednesday|thursday|friday|saturday|sunday|somvar|mangalvar|budhvar|guruvar|shukravar|shanivar|ravivar)( tak)? [\\w ]{0,25}(de (dena|do|dijiye|dogi|doge)|bhej (dena|do|dijiye|dogi|doge)|aa (jana|jao|jaiye|jaoge|jaogi)|pahunch)",
    "(tak|se pehle|ke andar) (de (dena|do|dijiye)|bhej (dena|do|dijiye)|aa (jana|jao|jaiye))",
    "(de|bhej|kar) dena",
    "(de|bhej|kar) dijiyega",
    "pakka bol",
    "haan bol do",
    "sign kar",
    "agree (karo|kar|karte|karengi)",
    "kab tak (de|karo|karogi|kar|bhej|aa)",
    "deal karte hain",
    "reserve (kar|karo)",
    "hold kar (do|lo|dijiye)",
    "पक्का",
    "कन्फ़र्म कर",
    "कन्फर्म कर",
    "बुक कर",
    "फाइनल कर",
    "आ जाना",
    "आ जाइए",
    "आ जाओ",
    "आ जाओगे",
    "आ जाओगी",
    "वादा",
)
_AGREE = _rx(
    "haan( ji| jee| bilkul| boliye| bolo| bataiye| batao| theek| thik| sahi)?",
    "han( ji| jee)?",
    "haa( ji| jee)?",
    "ha ji",
    "hanji",
    "ji( haan| han| bilkul| boliye| bataiye)?",
    "jee",
    "hm+",
    "hmm+",
    "mm+",
    "um+",
    "uh huh",
    "ok( ji| sir| madam)?",
    "okay",
    "okk",
    "k",
    "yes( please| ji| sure)?",
    "yeah",
    "yep",
    "yup",
    "sure",
    "right",
    "alright",
    "all right",
    "fine",
    "of course",
    "go ahead",
    "boliye( ji)?",
    "bataiye( ji)?",
    "bolo",
    "batao",
    "bol( rahe| rahi)? hai",
    "suniye",
    "sun raha",
    "sun rahi",
    "sunta hoon",
    "sunti hoon",
    "sun raha hoon",
    "sun rahi hoon",
    "theek( hai| h| ji)?",
    "thik( hai| h| ji)?",
    "achha",
    "accha",
    "acha",
    "achchha",
    "bilkul",
    "sahi( hai| baat)?",
    "chalo",
    "chalega",
    "chal jayega",
    "koi baat nahi",
    "koi na",
    "no problem",
    "no worries",
    "that'?s fine",
    "that works",
    "sounds good",
    "got it",
    "i see",
    "understood",
    "samajh gaya",
    "samajh gayi",
    "samjha",
    "samjhi",
    "pata hai",
    "malum hai",
    "theek hai ji",
    "hello",
    "hello ji",
    "helo",
    "hallo",
    "hi",
    "namaste",
    "namaskar",
    "pranam",
    "good (morning|afternoon|evening)",
    "salaam",
    "sat sri akal",
    "radhe radhe",
    "jai (shri|shree) (ram|krishna)",
    "kahiye",
    "kahiye ji",
    "speaking",
    "ji bol raha",
    "ji bol rahi",
    "haan main hi hoon",
    "main hi hoon",
    "yes speaking",
    "this is (he|she)",
    "that'?s me",
    "it'?s me",
    "ji main hi",
    "bol raha hoon",
    "bol rahi hoon",
    "हाँ",
    "हां",
    "हाँ जी",
    "हां जी",
    "जी",
    "जी हाँ",
    "जी हां",
    "ठीक है",
    "ठीक",
    "अच्छा",
    "बिल्कुल",
    "बोलिए",
    "बताइए",
    "बोलो",
    "हैलो",
    "हेलो",
    "नमस्ते",
    "नमस्कार",
    "सही है",
    "चलो",
    "ओके",
    "कहिए",
    "मैं ही हूँ",
    "मैं ही हूं",
    "समझ गया",
    "समझ गई",
    "प्रणाम",
)
_REFUSE = _rx(
    "nahi chahiye",
    "nahin chahiye",
    "nhi chahiye",
    "interested nahi",
    "interested nahin",
    "not interested",
    "no thanks",
    "no thank you",
    "mujhe (baat|bat) nahi (karni|karna)",
    "baat nahi karni",
    "baat nahi karna",
    "mana (hai|kar|karta|karti|karunga|karungi)",
    "main mana",
    "nahi (bataunga|batauga|bataungi|dunga|dungi|karunga|karungi|karna|karni|bol sakta|bol sakti|de sakta|de sakti|batana|bataunga)",
    "nahin (bataunga|dunga|dungi)",
    "(won'?t|will not|refuse to|can'?t|cannot|not going to|am not going to|don'?t want to) (tell|say|give|share|talk|discuss|do|answer|help)",
    "i (refuse|decline)",
    "not (now|today|possible|available)",
    "i can'?t help",
    "can'?t help (you|with that)",
    "no way",
    "not happening",
    "i don'?t (want|need|wish)",
    "no need",
    "we don'?t need",
    "i'?m not (interested|available)",
    "forget it",
    "leave it",
    "chhodiye",
    "chodo",
    "rehne do",
    "chhod do",
    "jaane do",
    "koi zarurat nahi",
    "zarurat nahi",
    "need nahi",
    "nahi karna",
    "नहीं चाहिए",
    "इंटरेस्टेड नहीं",
    "मना",
    "नहीं बताऊँगा",
    "नहीं बताऊंगा",
    "नहीं बताऊँगी",
    "बात नहीं करनी",
    "रहने दो",
    "छोड़ो",
    "ज़रूरत नहीं",
    "जरूरत नहीं",
)
_BARE_NO = _rx(
    "nahi", "nahin", "nhi", "nahi ji", "no", "nope", "na", "naa", "नहीं", "ना", "नहीं जी", "नही"
)
_OFFTOPIC = _rx(
    "mausam",
    "weather",
    "cricket",
    "match",
    "ipl",
    "politics",
    "election",
    "modi",
    "rahul",
    "bjp",
    "congress",
    "shaadi kab",
    "kya khaya",
    "khana kha liya",
    "recipe",
    "joke",
    "chutkula",
    "gaana",
    "gana sunao",
    "song",
    "movie",
    "film",
    "serial",
    "news",
    "kuch aur baat",
    "tell me a joke",
    "sing",
    "dance",
    "horoscope",
    "rashifal",
    "stock",
    "share market",
    "bitcoin",
    "petrol",
    "dollar",
    "gold rate",
    "sona",
    "chai",
    "tea",
    "love",
    "i love you",
    "girlfriend",
    "boyfriend",
    "marry me",
    "date",
    "dating",
    "pyaar",
    "ishq",
    "मौसम",
    "क्रिकेट",
    "चुनाव",
    "राजनीति",
    "चुटकुला",
    "गाना",
    "फिल्म",
    "ख़बर",
    "खबर",
    "राशिफल",
)
_VOICEMAIL = _rx(
    "leave (a |your )?(message|msg)",
    "please leave",
    "after the (beep|tone)",
    "at the (beep|tone)",
    "(beep|tone) ke baad",
    "beep ke baad",
    "baad mein (apna )?message",
    "message (chhod|chod|record) ",
    "message chhodein",
    "message chhodiye",
    "apna sandesh",
    "sandesh chhod",
    "voice ?mail",
    "mail ?box",
    "record(ed)? (your )?message",
    "not available to take your call",
    "unable to (take|answer) your call",
    "is not available( right now| at the moment)?",
    "can'?t come to the phone",
    "cannot come to the phone",
    "aapka call (voicemail|mailbox)",
    "abhi (uplabdh|available) nahi",
    "sampark nahi ho paa",
    "phone (utha|nahi utha) nahi",
    "is unavailable",
    "will (get back|call back) to you",
    "मैसेज छोड़",
    "संदेश छोड़",
    "बीप के बाद",
    "वॉइसमेल",
    "उपलब्ध नहीं",
    "संदेश रिकॉर्ड",
)
_BEEP = _rx("beep", "\\*beep\\*", "tone", "बीप", "toot", "tuut", "bip")
_UNREACH = _rx(
    "(switched|switch) off",
    "swiched off",
    "not reachable",
    "unreachable",
    "out of (coverage|network|service|reach)",
    "(number|phone|subscriber) (you|aap) (are calling|called|dial\\w*)",
    "the number you (have )?(dialed|dialled|called|are calling) (is|does|doesn'?t)",
    "does not exist",
    "doesn'?t exist",
    "not in service",
    "no longer in service",
    "temporarily (unavailable|out of service)",
    "(subscriber|customer) (is )?(busy|not answering|not reachable|switched off)",
    "network (se )?bahar",
    "kshetra se bahar",
    "number astitva mein nahi",
    "aapne jo number dial kiya",
    "jis (vyakti|subscriber) se aap sampark",
    "pahunch se bahar",
    "(phone|number|mobile) (band|bandh|switch off) hai",
    "स्विच ऑफ",
    "पहुँच से बाहर",
    "पहुंच से बाहर",
    "नेटवर्क क्षेत्र से बाहर",
    "आपके द्वारा डायल",
    "अस्तित्व में नहीं",
)
_IVR_KEYS = _rx(
    "press (\\d|zero|one|two|three|four|five|six|seven|eight|nine|star|hash|pound)",
    "dial (\\d|zero|one|two|three|four|five|six|seven|eight|nine)",
    "(\\d|ek|do|teen|chaar|paanch|chhe|saat|aath|nau|shunya|zero) (dabaiye|dabaye|dabayein|dabaen|dabana|dabao|dbaye|dbaiye|dbayein)",
    "(dabaiye|dabaye|dabayein|dabaen|dbaye|dbaiye)",
    "ke liye (\\d|ek|do|teen|char|chaar|paanch|panch|chhe|saat|aath|nau|shunya|zero)",
    "for (english|hindi) press",
    "angrezi ke liye",
    "hindi ke liye",
    "(to|for) (speak|talk) (to|with) (an? )?(agent|representative|executive|customer care)",
    "to repeat (this )?menu",
    "enter your",
    "please enter",
    "apna (number|mobile|account)( number)? (daliye|darj|enter|dalein|dalen)",
    "main menu",
    "दबाइए",
    "दबाएं",
    "दबायें",
    "दबाएँ",
    "के लिए \\d",
    "के लिए एक",
    "मुख्य मेनू",
)
_IVR_GREETING = _rx(
    "welcome to",
    "thank you for calling",
    "aapka swagat hai",
    "aapne [\\w ]{0,30}(sampark|call) kiya",
    "this call (may be|is being) recorded",
    "call (may be|is being) recorded",
    "quality and training",
    "namaskar",
    "swagat",
    "good (morning|afternoon|evening)",
    "how (may|can) i (help|assist)",
    "kaise madad",
    "kya madad",
    "बताइए आपकी",
    "स्वागत है",
    "कॉल रिकॉर्ड",
)
_HOLD = _rx(
    "your call is (important|being (held|transferred|connected))",
    "all (our )?(agents|representatives|executives|lines) are (busy|currently busy|engaged|occupied)",
    "please (hold|wait|stay on the line|stay on line|bear with us|remain on the line)",
    "kripya (pratiksha|intezaar|intezar|line par bane|hold)",
    "line par bane rahiye",
    "line par bane rahein",
    "line par rahiye",
    "aapki call (hamare liye )?(mahatvapurn|zaroori|important)",
    "sabhi (agents|executives|prativinidhi|lines) (abhi )?(vyast|busy|engaged)",
    "next available (agent|representative|executive)",
    "will be (with you|connected|answered) (shortly|soon|in a moment)",
    "estimated wait",
    "wait time",
    "you are (caller|number|position) ",
    "connecting you",
    "transferring (your call|you)",
    "aapko jod rahe",
    "aapki call transfer",
    "thank you for (holding|waiting|your patience)",
    "dhanyavaad (pratiksha|intezaar|aapke dhairya)",
    "hold music",
    "music playing",
    "प्रतीक्षा करें",
    "कृपया प्रतीक्षा",
    "लाइन पर बने रहें",
    "आपकी कॉल हमारे लिए",
    "सभी एजेंट",
    "कृपया होल्ड",
)
_ENGLISH_PLEASE = _rx(
    "english (mein|me|please|bolo|boliye)",
    "speak english",
    "in english",
    "angrezi mein",
    "english speak",
    "इंग्लिश में",
    "अंग्रेज़ी में",
    "अंग्रेजी में",
)
_HINDI_PLEASE = _rx(
    "hindi (mein|me|please|bolo|boliye)",
    "speak hindi",
    "in hindi",
    "hindi bolo",
    "hindi mein baat",
    "हिंदी में",
    "हिन्दी में",
)
_HEALTH = _rx(
    "tabiyat (theek|thik)? ?nahi",
    "tabiyat kharab",
    "bukhar",
    "sar dard",
    "sir dard",
    "dard ho raha",
    "bimar",
    "bimaar",
    "not feeling well",
    "sick",
    "unwell",
    "fever",
    "pain",
    "weak(ness)?",
    "kamzori",
    "तबीयत",
    "बुखार",
    "दर्द",
    "बीमार",
)

_TOPICS: list[tuple[str, re.Pattern[str]]] = [
    (
        "purpose",
        _rx(
            "kyun",
            "kyu",
            "why",
            "kis liye",
            "kis baare",
            "kya baat",
            "what for",
            "about what",
            "regarding",
            "kya kaam",
            "kya chahiye",
            "क्यों",
            "क्या काम",
        ),
    ),
    (
        "location",
        _rx(
            "kahan",
            "kaha",
            "kidhar",
            "where",
            "location",
            "kis shehar",
            "shehar",
            "city",
            "kahan hain",
            "कहाँ",
            "कहां",
        ),
    ),
    ("time", _rx("kab", "when", "kitne baje", "what time", "kitni der", "how long", "कब")),
    ("phone", _rx("number", "phone", "mobile", "contact", "whatsapp", "email", "नंबर", "फोन")),
    ("address", _rx("address", "pata", "ghar", "home", "residence", "पता", "घर")),
    (
        "health",
        _rx(
            "tabiyat",
            "health",
            "bimari",
            "bimaar",
            "dawai",
            "medicine",
            "doctor",
            "hospital",
            "sehat",
            "तबीयत",
            "सेहत",
        ),
    ),
    (
        "money",
        _rx(
            "salary",
            "kamate",
            "kamata",
            "income",
            "paisa",
            "paise",
            "kitna kamate",
            "budget",
            "bank",
            "savings",
            "rich",
            "loan",
            "तनख्वाह",
        ),
    ),
    (
        "job",
        _rx(
            "job",
            "kaam",
            "naukri",
            "company",
            "office",
            "business",
            "profession",
            "dhandha",
            "काम",
            "नौकरी",
        ),
    ),
    (
        "family",
        _rx(
            "shaadi",
            "wife",
            "husband",
            "patni",
            "pati",
            "bachche",
            "kids",
            "children",
            "parents",
            "family",
            "ghar wale",
            "शादी",
        ),
    ),
    ("identity", _rx("naam", "name", "kaun", "who", "age", "umar", "kitne saal", "नाम")),
    ("availability", _rx("free", "available", "fursat", "milenge", "meeting", "busy", "कब मिलेंगे")),
]

# ------------------------------------------------------------------ entities

_AMOUNT_WORDS = re.compile(r"(rs\.?|rupees?|rupay[ae]?|rupaye|inr|₹|रुपये|रुपए|रूपये|rs\b)", re.I)
_NAME_INTRO = re.compile(
    r"(?:main|mai|mera naam|my name is|this is|i am|i'm|मैं|मेरा नाम)\s+([A-Zऀ-ॿ][\wऀ-ॿ]{2,20})(?:\s+(?:bol|here|speaking|hoon|hun|बोल))",
    re.I,
)
_VISIT = _rx(
    "aa(na|ya|yenge|oge|ogi| jana| jao| jaiye)",
    "aayenge",
    "visit",
    "ghar (par|pe)",
    "site",
    "milne",
    "pahunch",
    "आना",
    "आएँगे",
    "आएंगे",
)
_BOOK = _rx("book", "booking", "reserve", "reservation", "slot", "appointment", "बुक", "बुकिंग")


_DEV_WORDS = {
    "बजे": "baje",
    "बजकर": "baje",
    "सुबह": "subah",
    "शाम": "shaam",
    "दोपहर": "dopahar",
    "रात": "raat",
    "कल": "kal",
    "आज": "aaj",
    "परसों": "parso",
}
_DEV_TIME = re.compile(
    r"(?:(?:कल|आज|परसों)\s+)?(?:(?:सुबह|शाम|दोपहर|रात)\s+)?[0-9०-९]{1,2}(?::[0-9]{2})?\s*(?:बजे|बजकर)"
)


_EN_PERIOD = {"morning": "subah", "afternoon": "dopahar", "evening": "shaam", "night": "raat"}
_EN_TIME_PHRASE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(?:o'?clock\s*)?(?:in the|at|of the)\s+(morning|afternoon|evening|night)",
    re.I,
)
_EN_TIME_SPAN = re.compile(
    r"(?:(?:day after tomorrow|tomorrow|today)\s+)?(?:at\s+)?\d{1,2}(?::\d{2})?\s*"
    r"(?:am|pm|a\.m\.|p\.m\.|o'?clock)?(?:\s*(?:in the|at|of the)\s+(?:morning|afternoon|evening|night))?",
    re.I,
)


def dev_to_roman(text: str) -> str:
    """Make a time phrase readable by the Roman-Hinglish time parser: Devanagari day/period/'baje'
    words and English 'tomorrow at 6 in the evening' become 'kal shaam 6 baje'."""
    out = text
    for dev, rom in _DEV_WORDS.items():
        out = out.replace(dev, f" {rom} ")
    out = re.sub(r"day after tomorrow", " parso ", out, flags=re.I)
    out = re.sub(r"\btomorrow\b", " kal ", out, flags=re.I)
    out = re.sub(r"\btoday\b", " aaj ", out, flags=re.I)

    def _en(m: re.Match[str]) -> str:
        mins = f":{m.group(2)}" if m.group(2) else ""
        return f" {_EN_PERIOD[m.group(3).lower()]} {m.group(1)}{mins} baje "

    out = _EN_TIME_PHRASE.sub(_en, out)
    return re.sub(r"\s+", " ", out)


def _entities(raw: str, t: str) -> Entities:
    from friday.playbooks import slots as sl

    ent = Entities()
    try:
        ent.times = [p.text for p in sl.parse_times(dev_to_roman(raw), limit=3)]
        if ent.times and re.search(r"[ऀ-ॿ]", raw):
            # Devanagari speech: keep the callee's own literal phrase so it can be read back as is
            spans = [m.group(0).strip() for m in _DEV_TIME.finditer(raw)]
            ent.times = spans or ent.times
        elif ent.times and not re.search(r"\b(baje|bje)\b", raw, re.I):
            # English speech: read it back in the callee's words ("tomorrow at 6 in the evening")
            spans = [
                m.group(0).strip()
                for m in _EN_TIME_SPAN.finditer(raw)
                if re.search(r"\d", m.group(0))
            ]
            ent.times = spans[: len(ent.times)] or ent.times
    except Exception:  # pragma: no cover - the slot parser never raises on text, but stay safe
        ent.times = []
    # amounts: a number next to a rupee word, or a rupee sign
    normalized = sl.normalise(raw)
    for val, s0, e0 in sl.words_to_numbers(raw):
        before = normalized[max(0, s0 - 4) : s0]
        after = normalized[e0 : e0 + 14]
        if _AMOUNT_WORDS.search(after) or "₹" in before or re.search(r"rs\.?\s*$", before):
            ent.amounts.append(str(val))
    m = _NAME_INTRO.search(raw)
    if m:
        ent.names.append(m.group(1))
    ent.visit = bool(_VISIT.search(t))
    ent.booking = bool(_BOOK.search(t))
    return ent


def _topic(t: str) -> str:
    for name, rx in _TOPICS:
        if rx.search(t):
            return name
    return "other"


# ------------------------------------------------------------------ main entry

_YES_DETAIL = "go_ahead"


def understand(utt: HeardUtterance | None) -> Understanding:
    """Classify one listen window. ``None`` or empty text with a human class means silence."""
    if utt is None:
        return Understanding(
            intent=CalleeIntent.SILENCE, confidence=0.95, text="", audio_class="silence"
        )
    raw = utt.text or ""
    t = norm(raw)
    ac = (utt.audio_class or "human").lower()
    base = {"text": raw, "stt_confidence": utt.confidence, "audio_class": ac}

    def done(intent: CalleeIntent, conf: float, matched: str = "", **kw: object) -> Understanding:
        return Understanding(intent=intent, confidence=conf, matched=matched, **base, **kw)  # type: ignore[arg-type]

    flags: list[str] = []
    if _ENGLISH_PLEASE.search(t):
        flags.append("wants_english")
    if _HINDI_PLEASE.search(t):
        flags.append("wants_hindi")
    if _HEALTH.search(t):
        flags.append("health_mention")

    # --- line classes first (they are not a person talking)
    if ac == "voicemail":
        detail = "beep" if _BEEP.search(t) and not _VOICEMAIL.search(t) else "greeting"
        return done(CalleeIntent.VOICEMAIL_BEEP, 0.9, "audio_class=voicemail", detail=detail)
    if ac == "hold_music":
        return done(CalleeIntent.HOLD_MUSIC, 0.9, "audio_class=hold_music")
    if ac == "queue_announcement" and not t:
        return done(CalleeIntent.HOLD_MUSIC, 0.8, "audio_class=queue_announcement")
    if ac == "ivr_prompt" and not t:
        return done(CalleeIntent.IVR_MENU, 0.7, "audio_class=ivr_prompt")
    if not t:
        return done(CalleeIntent.SILENCE, 0.9, "empty")

    # --- carrier / mailbox recordings
    m = _UNREACH.search(t)
    if m:
        return done(CalleeIntent.UNREACHABLE, 0.9, m.group(0))
    m = _VOICEMAIL.search(t)
    if m:
        return done(CalleeIntent.VOICEMAIL_BEEP, 0.9, m.group(0), detail="greeting")
    if _BEEP.search(t) and len(t.split()) <= 3:
        return done(CalleeIntent.VOICEMAIL_BEEP, 0.85, "beep", detail="beep")

    # --- safety intents (order matters)
    for rx, intent, conf, detail in (
        (_DISTRESS, CalleeIntent.DISTRESS, 0.95, None),
        (_STOP, CalleeIntent.STOP_CALLING, 0.95, None),
        (_WRONG, CalleeIntent.WRONG_NUMBER, 0.9, None),
        (_HOSTILE, CalleeIntent.HOSTILE, 0.85, None),
    ):
        m = rx.search(t)
        if m:
            return done(intent, conf, m.group(0), detail=detail, flags=flags)

    # --- a human asking us to wait ("ek minute") comes before the recorded announcements
    words_n = len(t.split())
    m = _WAIT.search(t)
    if (
        m
        and words_n <= 8
        and ac == "human"
        and not _IVR_KEYS.search(t)
        and not (_ARE_AI.search(t) or _WHO.search(t) or _SECRET.search(t) or _MONEY.search(t))
    ):
        return done(CalleeIntent.ASKS_TO_WAIT, 0.85, m.group(0), flags=flags)

    # --- IVR / hold announcements (recorded, long, menu-like)
    ivr = _IVR_KEYS.search(t)
    hold = _HOLD.search(t)
    if ac == "ivr_prompt" or ivr:
        return done(
            CalleeIntent.IVR_MENU,
            0.9 if ivr else 0.7,
            ivr.group(0) if ivr else "audio_class=ivr_prompt",
        )
    if hold or ac == "queue_announcement":
        return done(CalleeIntent.HOLD_MUSIC, 0.85, hold.group(0) if hold else "queue_announcement")
    g = _IVR_GREETING.search(t)
    if g and words_n >= 3:
        # "Thank you for calling X, how may I help you?": the agent invites us to speak
        return done(CalleeIntent.AGREES, 0.7, g.group(0), detail="agent_greeting", flags=flags)

    ent = _entities(raw, t)

    # --- questions to Friday
    m = _ARE_AI.search(t)
    if m:
        return done(CalleeIntent.ARE_YOU_AI, 0.9, m.group(0), flags=flags)
    m = _WHO.search(t)
    if m and not _ABOUT_USER.search(t):
        return done(CalleeIntent.WHO_IS_THIS, 0.85, m.group(0), entities=ent, flags=flags)
    m = _SECRET.search(t)
    if m:
        return done(
            CalleeIntent.ASKS_PERSONAL_DETAILS,
            0.95,
            m.group(0),
            detail="secret",
            topic="secret",
            flags=flags,
        )
    m = _MONEY.search(t)
    if m:
        return done(CalleeIntent.ASKS_MONEY, 0.85, m.group(0), entities=ent, flags=flags)
    m = _IDENTITY.search(t)
    if m:
        return done(
            CalleeIntent.ASKS_PERSONAL_DETAILS,
            0.85,
            m.group(0),
            detail="identity",
            topic=_topic(m.group(0)),
            flags=flags,
        )
    m = _BUSY.search(t)
    if m:
        return done(CalleeIntent.BUSY_CALL_BACK_LATER, 0.85, m.group(0), entities=ent, flags=flags)
    m = _OFFTOPIC.search(t)
    if m and not (ent.times or ent.amounts):
        return done(CalleeIntent.OFF_TOPIC, 0.7, m.group(0), flags=flags)
    m = _REPEAT.search(t)
    if m and len(t.split()) <= 9:
        return done(CalleeIntent.ASKS_TO_REPEAT, 0.8, m.group(0), flags=flags)
    m = _ABOUT_USER.search(t)
    if m:
        return done(
            CalleeIntent.ASKS_ABOUT_USER,
            0.8,
            m.group(0),
            topic=_topic(t),
            entities=ent,
            flags=flags,
        )
    m = _COMMIT.search(t)
    if m and (
        ent.times
        or ent.amounts
        or ent.visit
        or ent.booking
        or re.search(r"pakka|confirm|book|final|promise|deal|lock|reserve|वादा|पक्का", t)
    ):
        return done(CalleeIntent.PROPOSES_COMMITMENT, 0.8, m.group(0), entities=ent, flags=flags)
    m = _REFUSE.search(t)
    if m:
        return done(CalleeIntent.REFUSES, 0.8, m.group(0), flags=flags)

    # --- replies
    words = t.split()
    if _BARE_NO.fullmatch(t):
        return done(CalleeIntent.REFUSES, 0.6, t, detail="bare_no", flags=flags)
    agree = _AGREE.search(t)
    if ent.times or ent.amounts or ent.names or len(words) >= 4:
        # a substantive sentence: an answer (also covers "haan ji, kal subah 10 baje")
        return done(
            CalleeIntent.GIVES_ANSWER,
            0.7 if (ent.times or ent.amounts) else 0.55,
            agree.group(0) if agree else "",
            entities=ent,
            flags=flags,
        )
    if agree:
        return done(
            CalleeIntent.AGREES, 0.85 if len(words) <= 3 else 0.7, agree.group(0), flags=flags
        )
    if len(words) >= 2:
        return done(CalleeIntent.GIVES_ANSWER, 0.45, "", entities=ent, flags=flags)
    return done(CalleeIntent.UNKNOWN, 0.3, "", flags=flags)
