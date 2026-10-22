# ruff: noqa: E501
"""Text that only the integration layer needs. PENDING_FOUNDER_APPROVAL.

Hear-before-change (CLAUDE.md rule 3): nothing in this module may be shown to a real user, or spoken
on a call, until the founder has approved the wording. The wording of each package still lives in
its own copy module (friday/calls/copy.py, friday/savings/copy.py, friday/lifestate/copy.py,
friday/google/consent_copy.py, friday/liveagent/lines.py); this module only holds the few lines that
belong to the seams between them. Placeholders use ``{name}`` format fields.

Two kinds of text:
* ``LINES``: messages on the user's WhatsApp.
* ``SPOKEN``: the only words the bridge adds to a call (they go into the brief the user approved,
  so they appear in the approval message through the opening-line preview and the plan).
"""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True

DEFAULT_LANGUAGE = "hinglish"

LINES: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- Google
    "google_connect_link": {
        "hinglish": "Google jodne ke liye yeh link kholiye (10 minute mein expire ho jata hai): {link}",
        "en": "Open this link to connect Google (it expires in 10 minutes): {link}",
    },
    "google_not_configured": {
        "hinglish": "Google abhi mere yahan set up nahi hai. Thoda wait kijiye.",
        "en": "Google is not set up on my side yet. Please wait a little.",
    },
    "google_connected": {
        "hinglish": "Google juda hua hai ({email}).",
        "en": "Google is connected ({email}).",
    },
    "google_needs_reconnect": {
        "hinglish": "Google ka connection tut gaya hai. 'google connect' likhiye, naya link bhejti hoon.",
        "en": "The Google connection broke. Write 'connect google' and I'll send a new link.",
    },
    "google_not_connected": {
        "hinglish": "Google juda nahi hai. Jodna ho to 'google connect' likhiye.",
        "en": "Google is not connected. Write 'connect google' to connect it.",
    },
    "google_disconnected": {
        "hinglish": "Google hata diya. Mere paas ab aapka Google ka koi data nahi hai.",
        "en": "Google is disconnected. I no longer hold any of your Google data.",
    },
    "google_disconnect_nothing": {
        "hinglish": "Google juda hi nahi tha.",
        "en": "Google was not connected.",
    },
    # ---------------------------------------------------------------- the user's day
    "day_empty": {
        "hinglish": "Aaj ke liye mere paas kuch noted nahi hai.",
        "en": "I have nothing noted for today.",
    },
    # ---------------------------------------------------------------- calls
    "intake_cancelled": {
        "hinglish": "Theek hai, call ka plan hata diya.",
        "en": "Okay, I dropped the call plan.",
    },
    "call_no_voice": {
        "hinglish": "Abhi call lagane ka rasta chalu nahi hai, isliye yeh call nahi hui.",
        "en": "The calling line is not switched on yet, so this call did not happen.",
    },
    # ---------------------------------------------------------------- bridge summaries (W2 -> W1)
    "summary_delivered": {
        "hinglish": "Aapka sandesh pahuncha diya.",
        "en": "I passed on your message.",
    },
    "summary_voicemail_left": {
        "hinglish": "Voicemail par chhota sa fixed message chhoda hai.",
        "en": "I left the short fixed message on voicemail.",
    },
    "summary_cut_off": {
        "hinglish": "Call ka time poora ho gaya, isliye baat adhoori rahi.",
        "en": "The call hit its time limit, so it is not finished.",
    },
    "summary_distress": {
        "hinglish": "Samne wale pareshan lag rahe the. Please unhe khud ek baar phone kar lijiye.",
        "en": "The person sounded distressed. Please call them yourself.",
    },
    "summary_hostile": {
        "hinglish": "Samne wale naraaz the, maine call tameez se band kar di.",
        "en": "The person was upset, so I ended the call politely.",
    },
    "summary_unresolved": {
        "hinglish": "Baat aage nahi badh paayi, isliye maine call band kar di.",
        "en": "We were not getting anywhere, so I ended the call.",
    },
    "summary_unanswered": {
        "hinglish": "Jawab nahi mila: {items}",
        "en": "Not answered: {items}",
    },
    "summary_health": {
        "hinglish": "Unhone apni sehat ke baare mein kuch kaha, ek baar haal-chaal pooch lijiye.",
        "en": "They mentioned a health problem; you may want to check on them.",
    },
    "summary_callback": {
        "hinglish": "Unhone {when} ke aas-paas call karne ko kaha.",
        "en": "They asked for a call around {when}.",
    },
}

SPOKEN: dict[str, dict[str, str]] = {
    # said to the callee in place of the purpose when the purpose is itself a question that the
    # ask list will put next (so the same sentence is not spoken twice)
    "goal_spoken_ask": {
        "hinglish": "Aapse ek sawaal poochna tha.",
        "hi": "आपसे एक सवाल पूछना था।",
        "en": "I had a question for you.",
    },
    # how the callee hears the user when the profile has no name
    "unnamed_user": {
        "hinglish": "mere user",
        "hi": "मेरे यूज़र",
        "en": "my user",
    },
}


def line(key: str, lang: str = DEFAULT_LANGUAGE, **fmt: object) -> str:
    variants = LINES[key]
    text = variants.get(lang) or variants[DEFAULT_LANGUAGE]
    return text.format(**fmt) if fmt else text


def spoken(key: str, lang: str = DEFAULT_LANGUAGE) -> str:
    variants = SPOKEN[key]
    return variants.get(lang) or variants[DEFAULT_LANGUAGE]


# ------------------------------------------------------------------------------ call-test CLI
# `friday consumer call-test` is a founder-only tool (English, printed on the server console, never
# sent to a user). PENDING_FOUNDER_APPROVAL like the rest. The one SPOKEN line is "test_goal": the
# default message of the test call when the founder gives no --goal (it is said verbatim).
CALL_TEST: dict[str, str] = {
    "banner_dry": "DRY RUN: nothing will be dialled. A simulated callee ({persona}) plays the other side.",
    "banner_real": "REAL CALL TEST: this places ONE real phone call from Friday to {to}.",
    "refuse": "REFUSED: {why}",
    "why_not_allowed": "{to} is not on your allow-list (FRIDAY_PILOT_ALLOWED_NUMBERS), so Friday will not call it.",
    "why_no_allowlist": "no number is on your allow-list. Set FRIDAY_PILOT_ALLOWED_NUMBERS to your own phone first.",
    "why_bad_number": "that is not a valid phone number (use +91XXXXXXXXXX).",
    "why_switch_off": "FRIDAY_CONSUMER_CALLS_ENABLED is not true.",
    "why_not_live": "FRIDAY_MODE is not 'live'.",
    "why_not_pilot": "FRIDAY_PROFILE is not 'pilot'; real consumer calls are pilot-only for now.",
    "why_paused": "the kill switch is on (run `friday pause --resume` or remove FRIDAY_PAUSED to continue).",
    "why_problem": "setup problem: {problem}",
    "why_seconds": "--max-seconds must be between {low} and {high}.",
    "why_gate": "the safety gate did not allow this call ({reasons}). Nothing was dialled.",
    "why_window": "it is outside the calling window for this kind of call, so nothing was dialled. Try again inside the window.",
    "user_created": "Note: no Friday user had this number, so a local test user was created for it.",
    "server_failed": "REFUSED: could not start Friday on port {port} (is `friday` still running? stop it first).",
    "server_unreachable": "REFUSED: {base}/health is not reachable from the internet. Check the tunnel/domain and FRIDAY_PUBLIC_BASE_URL.",
    "server_up": "Friday is serving on port {port}.",
    "head_plan": "The call plan",
    "plan_to": "  To          : {to} ({who})",
    "plan_goal": "  Goal        : {goal}",
    "plan_goal_default": "  Goal        : {goal}   [default test message, PENDING founder approval]",
    "plan_say": "  Friday says : {items}",
    "plan_ask": "  Friday asks : {items}",
    "plan_opening": "  FIRST THING YOU WILL HEAR (exact words):",
    "plan_opening_line": '    "{line}"',
    "plan_from": "  Caller ID   : {from_}",
    "plan_max": "  Max length  : {seconds} s (hard cap)",
    "plan_cost": "  Est. cost   : up to about Rs {cost} (upper-bound estimate)",
    "plan_recording": "  Recording   : {state}. No recording notice is played (founder decision).",
    "recording_on": "ON (the reference is kept for the retention period)",
    "recording_off": "OFF",
    "ask_yes": "Type YES to place the call: ",
    "cancelled": "Cancelled. No call was placed.",
    "placing": "Placing the call... answer your phone and talk. Ctrl+C hangs up and stops.",
    "stopped": "Stopped by you (Ctrl+C). The line was hung up.",
    "not_dialled": "No call was placed ({why}).",
    "head_report": "Report Friday would send on WhatsApp ({sent}):",
    "report_sent": "also sent",
    "report_not_sent": "NOT sent; add --whatsapp-report to send it",
    "head_summary": "===== CALL SUMMARY =====",
    "sum_dial": "Dial status    : {v}",
    "sum_duration": "Duration       : {v} s",
    "sum_turns": "Turns          : {v}",
    "sum_langs": "Languages      : {v}",
    "sum_gap": "Reply gap      : p50 {p50} ms, p95 {p95} ms ({n} replies)",
    "sum_gap_none": "Reply gap      : n/a (no replies measured)",
    "sum_safety": "Safety blocks  : {v}",
    "sum_outcome": "Outcome        : {v}",
    "sum_cost": "Estimated cost : about Rs {v}",
    "sum_transcript": "Transcript file: {v}",
    "sum_log": "Call log file  : {v}",
    "sum_none": "none",
    "send_back": "Send back only these summary lines. Never send keys, the .env file or a full number.",
    "test_goal": "Friday abhi test chal raha hai, aap mujhe aaram se sun sakte hain.",
}


def cli_line(key: str, **fmt: object) -> str:
    text = CALL_TEST[key]
    return text.format(**fmt) if fmt else text
