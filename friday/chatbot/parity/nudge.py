# ruff: noqa: E501
"""Item 4: the window-reopen nudge. The wording lives in templates.yaml (chatbot_window_reopen)."""

from __future__ import annotations

from datetime import datetime, timedelta

from friday.chatbot.templates import chatbot_template

WINDOW = timedelta(hours=24)
_FALSE_URGENCY = ("urgent", "time-sensitive", "time sensitive", "immediately", "last chance",
                  "expires", "hurry", "jaldi", "turant", "अभी तुरंत", "तुरंत")


def window_closed(last_user_message_at: datetime | None, now: datetime) -> bool:
    return last_user_message_at is None or now - last_user_message_at >= WINDOW


def reopen_template(first_name: str, task: str, lang: str = "hinglish"):
    """The template reference for a window-reopen nudge (never sent from here)."""
    return chatbot_template("chatbot_window_reopen", [first_name, task], lang)


def has_false_urgency(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in _FALSE_URGENCY)
