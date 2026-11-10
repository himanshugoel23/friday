"""Scam-check engine: invented examples in English, Roman Hinglish and Devanagari, plus false-positive checks."""

from __future__ import annotations

import json
import re

import pytest

from friday.core.interfaces import LLMResponse
from friday.robindevice import copy as C
from friday.robindevice import scamcheck as S

SL, RK, US, NS = "SCAM_LIKELY", "RISKY", "UNSURE", "NO_SIGNS_FOUND"

# (kind, text, allowed verdicts, category that must be present or None)
CASES = [
    # --- digital arrest / authority scripts
    ("text", "This is CBI officer. Your Aadhaar is linked to a drugs parcel. You are under digital arrest, stay on video call and do not tell anyone.", {SL}, "digital_arrest"),
    ("text", "TRAI notice: your mobile number will be disconnected in 2 hours for illegal activity. Call the police officer now.", {SL}, "digital_arrest"),
    ("text", "Aapke naam par parcel mein drugs mile hain. CBI aapko giraftar karegi. Video call par rahiye, kisi ko mat batana.", {SL}, "digital_arrest"),
    ("text", "मैं सीबीआई से बोल रहा हूँ। आपके नाम पर ड्रग्स का पार्सल मिला है, आपके खिलाफ वारंट है, वीडियो कॉल पर रहिए।", {SL}, "digital_arrest"),
    ("text", "Police station se bol raha hoon, aapke account se money laundering hui hai, aapke khilaf FIR hogi. Phone mat kaatna.", {SL}, "digital_arrest"),
    # --- OTP / PIN requests
    ("text", "Dear customer your account will be blocked. Share your OTP to verify immediately.", {SL}, "otp_pin"),
    ("text", "Sir OTP bata dijiye jo abhi aaya hai, warna khata band ho jayega.", {SL}, "otp_pin"),
    ("text", "कृपया अपना ओटीपी भेजिए ताकि खाता चालू रहे।", {SL}, "otp_pin"),
    ("text", "Please enter your UPI PIN to confirm.", {SL}, "otp_pin"),
    ("text", "Tell me the CVV and the card number on the back.", {SL}, "otp_pin"),
    # --- KYC / bank block
    ("text", "Your SBI account KYC has expired and will be blocked today. Click the link to update KYC immediately.", {RK, SL}, "kyc_block"),
    ("text", "आपका खाता ब्लॉक हो जाएगा, अभी लिंक पर क्लिक करके केवाईसी अपडेट कीजिए।", {RK, SL}, "kyc_block"),
    ("text", "Aapka PAN card band ho jayega, turant link par click karke update karein.", {RK, SL}, "kyc_block"),
    # --- utilities
    ("text", "Your electricity will be disconnected tonight at 9.30pm. Call this number immediately to update your bill.", {RK, SL}, "utility"),
    ("text", "Aaj raat bijli kat jayegi. Turant is number par call kijiye.", {RK, SL}, "utility"),
    ("text", "आपकी बिजली आज रात कट जाएगी, तुरंत इस नंबर पर कॉल करें।", {RK, SL}, "utility"),
    # --- refund / collect request
    ("text", "Your refund of Rs 4999 is ready. Approve the collect request and enter your PIN to receive it.", {SL}, "collect_refund"),
    ("text", "Cashback milega, bas QR code scan kijiye aur PIN daaliye.", {SL}, "collect_refund"),
    ("text", "रिफंड पाने के लिए अपना पिन डालें और रिक्वेस्ट मंज़ूर करें।", {SL}, None),
    # --- remote access
    ("text", "Please install AnyDesk and share the 9 digit code so I can fix your bank app.", {RK, SL}, "remote_access"),
    ("text", "TeamViewer download karo aur code bata do, hum aapka refund kar denge.", {RK, SL}, "remote_access"),
    ("text", "QuickSupport इंस्टॉल कीजिए और कोड बताइए।", {RK, SL}, "remote_access"),
    # --- APK / wedding card / parcel
    ("text", "Wedding invitation card.apk please open and install", {SL}, "apk_file"),
    ("text", "Your parcel tracking app: download and install RTO_challan.apk now", {SL}, "apk_file"),
    ("text", "Shaadi ka card download karke install karein, link par click kijiye", {SL, RK}, "apk_file"),
    ("text", "PM Kisan yojana ka naya app install karo: kisan_update.apk", {SL}, "apk_file"),
    # --- pension / life certificate
    ("text", "Your pension will stop. Update your life certificate by clicking this link today.", {RK, SL}, "pension"),
    ("text", "Aapki pension band ho jayegi, jeevan pramaan ke liye abhi call karein.", {RK, SL}, "pension"),
    ("text", "आपकी पेंशन रुक जाएगी, जीवन प्रमाण अपडेट के लिए लिंक पर क्लिक करें।", {RK, SL}, "pension"),
    # --- relative in trouble
    ("text", "Papa this is my new number. I had an accident, please send 30000 rupees urgently, do not tell mummy.", {SL}, "relative_trouble"),
    ("text", "Dadi main aapka pota hoon, police ne pakad liya hai, jaldi 20000 rupaye bhej do, kisi ko mat batana.", {SL}, "relative_trouble"),
    ("text", "पापा मेरा नया नंबर है, अस्पताल में हूँ, 25000 रुपये भेज दो, किसी को मत बताना।", {SL, RK}, "relative_trouble"),
    # --- investment groups
    ("text", "Join our VIP Telegram group for stock tips. Guaranteed profit 5% daily.", {RK, SL}, "investment"),
    ("text", "Work from home, like videos and earn Rs 5000 per day, daily income guaranteed.", {RK, SL}, "investment"),
    ("text", "व्हाट्सएप ग्रुप जॉइन करें, शेयर टिप्स से रोज़ 5% मुनाफ़ा पक्का।", {RK, SL}, None),
    # --- prize
    ("text", "Congratulations you have won a KBC lottery. Call now to claim your prize and pay the tax.", {RK, SL}, "prize"),
    # --- safe account
    ("text", "Transfer your savings to the RBI safe account for verification right now.", {SL}, "safe_account"),
    ("text", "Apne paise RBI ke verification account mein transfer kijiye jab tak jaanch chal rahi hai.", {SL}, "safe_account"),
    # --- urgency + secrecy + money
    ("text", "Send 15000 rupees urgently and do not tell anyone in the family.", {RK, SL}, None),
    ("text", "Turant 10000 rupaye bhej do, ghar walon ko mat batana.", {RK, SL}, None),
    # --- URLs
    ("url", "https://sbi-kyc-update.com/login", {SL}, "link_lookalike"),
    ("url", "http://hdfcbank.co/netbanking", {SL}, "link_lookalike"),
    ("url", "https://sbi.co.in.secure-login.xyz/kyc", {SL}, "link_lookalike"),
    ("url", "https://xn--hdfbank-9ya.com/", {SL}, "link_lookalike"),
    ("url", "https://uidai.gov.in@evil.example.com/aadhaar", {SL}, "link_lookalike"),
    ("url", "https://icicibnak.com/login", {SL}, "link_lookalike"),
    ("url", "https://bit.ly/3abcXYZ", {RK}, "link_shortener"),
    ("url", "https://example-shop.com/offer", {US}, "link_unknown"),
    ("url", "http://192.168.4.20/kyc", {RK, US}, "link_unknown"),
    ("url", "https://cdn.example.org/files/update.apk", {SL}, "apk_file"),
    ("url", "https://www.onlinesbi.sbi/", {NS}, None),
    ("url", "https://incometax.gov.in/iec/foportal", {NS}, None),
    ("url", "https://cybercrime.gov.in", {NS}, None),
    ("url", "https://sancharsaathi.gov.in/", {NS}, None),
    ("url", "https://www.indiapost.gov.in/", {NS}, None),
    ("url", "https://uidai.gov.in/", {NS}, None),
    # --- phone
    ("phone", "+92 300 1234567", {RK}, "number_international"),
    ("phone", "+44 20 7946 0958", {RK}, "number_international"),
    ("phone", "9876543210", {US}, None),
    ("phone", "+91 98765 43210", {US}, None),
    ("phone", "1400123456", {US}, "number_marketing"),
    ("phone", "1800 123 4567", {US}, None),
    # --- apps and files
    ("app_name", "AnyDesk", {RK}, "remote_access"),
    ("app_name", "TeamViewer QuickSupport", {RK}, "remote_access"),
    ("app_name", "SBI Rewards.apk", {SL}, "apk_file"),
    ("file_name", "wedding_card_invite.apk", {SL}, "apk_file"),
    ("file_name", "RTO_Challan.apk", {SL}, "apk_file"),
    ("file_name", "holiday_photo.jpg", {US}, None),
    ("screenshot_ref", "shot_20261104_abc123", {US}, "screenshot"),
    # --- FALSE POSITIVES: genuine / harmless messages must not alarm
    ("text", "Rs 1,200.00 debited from A/c XX1234 on 04-11-26 to ZOMATO via UPI. Ref 5123. If not you, call 1800 123 4567 - Example Bank", {NS}, None),
    ("text", "Your OTP for login is 482913. Do not share it with anyone. Valid for 10 minutes.", {NS}, None),
    ("text", "Never share your OTP, PIN or CVV with anyone. Bank staff will never ask for them.", {NS}, None),
    ("text", "बैंक आपसे कभी ओटीपी नहीं माँगता। अपना ओटीपी किसी को न बताएं।", {NS}, None),
    ("text", "Beta kal doctor ke paas chalna hai, 11 baje taiyar rehna.", {NS}, None),
    ("text", "पापा कल मैं आपको अस्पताल में चेकअप के लिए ले चलूँगा, सुबह तैयार रहिएगा।", {NS}, None),
    ("text", "Your appointment with Dr Mehta is confirmed for 5 Nov at 10:30 am. Please carry your previous reports.", {NS}, None),
    ("text", "Mummy, shaam ko aate waqt dahi le aana.", {NS}, None),
    ("text", "Happy birthday dadi! Hum sab Sunday ko aa rahe hain.", {NS}, None),
    ("text", "News: CBI arrested three people in a digital arrest scam. Beware of such calls, never believe them.", {NS, US}, None),
    ("text", "Your electricity bill for October is Rs 1,450, due on 15 Nov. Thank you.", {NS}, None),
    ("text", "Dear customer, your KYC is due. Please visit your nearest branch with your documents.", {NS}, None),
    ("text", "Your card ending 4821 has been blocked as per your request. Call 1800 123 4567 for queries.", {NS, US}, None),
    ("text", "Beta, mujhe 2000 rupaye bhej dena, dawai lani hai.", {NS, US}, None),
]


def test_at_least_60_cases():
    assert len(CASES) >= 60


@pytest.mark.parametrize("kind,text,verdicts,category", CASES, ids=[f"{i}-{c[0]}" for i, c in enumerate(CASES)])
def test_case(kind, text, verdicts, category):
    r = S.check_rules(kind, text)
    assert r.verdict in verdicts, (r.verdict, r.categories, r.score)
    if category:
        assert category in r.categories, r.categories


def test_all_language_outputs_present_and_never_say_safe():
    lines = []
    for table in (C.VERDICT_LABEL, C.REASONS, C.NEXT_STEPS):
        for variants in table.values():
            lines.extend(variants.values())
    for v in lines:
        assert not re.search(r"\bsafe\b|surakshit|सुरक्षित\b", v, re.I) or "सुरक्षित" in v and "खाते" in v or "safe account" in v
    for lang in C.LANGS:
        for kind, text, _, _ in CASES[:20]:
            r = S.check_rules(kind, text, lang)
            assert r.reason and r.next_step and r.headline
            assert "safe" not in (r.reason + r.next_step).replace("safe account", "").lower().replace("a 'safe'", "")


def test_positive_result_never_promises():
    r = S.check_rules("text", "Beta kal doctor ke paas chalna hai", "en")
    assert r.verdict == NS and "never share an OTP or PIN" in r.next_step and "safe" not in r.next_step.lower()
    for lang in ("hinglish", "hi"):
        r = S.check_rules("text", "Beta kal doctor ke paas chalna hai", lang)
        assert r.next_step == C.NEXT_STEPS["none_found"][lang].format(child=C.CHILD[lang])


def test_money_request_never_no_signs():
    r = S.check_rules("text", "Please send 5000 rupees to this account today")
    assert r.verdict != NS


def test_output_language_follows_parent():
    assert S.check_rules("text", "Share your OTP now", "hi").reason.startswith("इसमें")
    assert S.check_rules("text", "Share your OTP now", "hinglish").reason.startswith("Ismein")
    assert S.check_rules("text", "Share your OTP now", "en").reason.startswith("It asks")


def test_alert_child_rules():
    assert S.check_rules("text", "Share your OTP right now").alert_child
    assert not S.check_rules("text", "Beta kal doctor ke paas chalna hai").alert_child
    assert not S.check_rules("url", "https://bit.ly/abc").alert_child  # link-only risk does not wake the child
    assert not S.check_rules("phone", "+92 300 1234567").alert_child


def test_next_step_mentions_hang_up_and_1930():
    r = S.check_rules("text", "This is CBI. Your Aadhaar has a drugs parcel, you face arrest warrant, stay on video call")
    joined = " ".join(r.next_steps)
    assert "Hang up" in joined and "1930" in joined


def test_bad_kind():
    with pytest.raises(ValueError):
        S.check_rules("sms", "x")


def test_classify_number():
    assert S.classify_number("+91 98765 43210") == "mobile"
    assert S.classify_number("+1 415 555 0100") == "international"
    assert S.classify_number("1800 11 2233") == "toll_free"
    assert S.classify_number("56767") == "shortcode"
    assert S.classify_number("hello") is None


# --------------------------------------------------------------------------- LLM second opinion


class _LLM:
    def __init__(self, text):
        self.text, self.seen = text, []

    async def complete(self, **kw):
        self.seen.append(kw)
        return LLMResponse(text=self.text, model="fake")


async def test_llm_can_raise_but_not_to_scam_likely_alone():
    text = "Hello, a quiet offer just for you, reply soon"
    llm = _LLM(json.dumps({"verdict": "SCAM_LIKELY"}))
    r = await S.check("text", text, lang="en", llm=llm)
    assert r.verdict == RK and r.source == "rules+llm" and not r.alert_child
    assert llm.seen[0]["json_schema"] == S.SECOND_OPINION_SCHEMA


async def test_llm_never_lowers_a_rule_hit():
    llm = _LLM(json.dumps({"verdict": "NO_SIGNS_FOUND"}))
    r = await S.check("text", "Share your OTP right now", lang="en", llm=llm)
    assert r.verdict == SL and llm.seen == []  # rule hit: the model is not even asked


async def test_llm_garbage_is_ignored():
    for bad in ("not json", json.dumps({"verdict": "SAFE"}), json.dumps({"verdict": "RISKY", "x": 1})):
        r = await S.check("text", "Good morning, see you at the clinic", lang="en", llm=_LLM(bad))
        assert r.verdict == NS and r.source == "rules"


async def test_llm_gets_masked_text():
    llm = _LLM(json.dumps({"verdict": "UNSURE"}))
    await S.check("text", "call 9876543210 or mail a.b@example.com about your order", lang="en", llm=llm)
    body = llm.seen[0]["messages"][0].content
    assert "9876543210" not in body and "example.com" not in body


async def test_job_offer_with_an_upfront_fee_is_risky_but_warnings_and_plain_offers_are_not():
    """T18 miss closed: advance-fee job fraud (new category job_fee, weight 3 = RISKY)."""
    bad = ("Congratulations you are selected for a job at Amazon, pay Rs 2000 registration fee to confirm.",
           "Aapka naukri ke liye selection ho gaya hai. Joining ke liye 3000 rupaye registration fees bhej do.",
           "आपका नौकरी के लिए चयन हो गया है। कन्फर्म करने के लिए 2500 रुपये रजिस्ट्रेशन फीस भेजें।")
    for t in bad:
        r = await S.check("text", t)
        assert r.verdict in ("RISKY", "SCAM_LIKELY") and "job_fee" in r.categories, (t, r.verdict, r.categories)
    for t in ("Beware: no real company asks for a registration fee for a job. Never pay for a job offer.",
              "School registration fee for the new term is due next week, please pay at the office.",
              "Congratulations, you are selected for the job. Please bring your documents on Monday for joining."):
        assert (await S.check("text", t)).verdict in ("NO_SIGNS_FOUND", "UNSURE"), t


async def test_dinner_money_from_a_child_is_not_urgency_but_a_real_deadline_still_is():
    ok = await S.check("text", "Aaj raat ka khana bahar khayenge, 500 rupaye bhej do mujhe UPI se.")
    assert ok.verdict in ("NO_SIGNS_FOUND", "UNSURE")
    for t in ("Aaj raat tak 20000 rupaye bhej do, warna account band ho jayega.", "Aaj raat 10 baje tak 5000 rupaye bhej do aur kisi ko mat batana."):
        assert (await S.check("text", t)).verdict in ("RISKY", "SCAM_LIKELY"), t
    util = await S.check("text", "Aapka bijli connection aaj raat kat jayega, turant is number par call karein")
    assert util.verdict in ("RISKY", "SCAM_LIKELY")  # the utility-cut scam that uses 'aaj raat' is unchanged
