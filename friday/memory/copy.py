# ruff: noqa: E501
"""Wording for the memory list. PENDING_FOUNDER_APPROVAL (written lines, same rule as the chatbot)."""

from __future__ import annotations

PENDING_FOUNDER_APPROVAL = True

LINES = {
    "header": {
        "hinglish": "Mujhe aapke baare mein yeh yaad hai:",
        "hi": "मुझे आपके बारे में यह याद है:",
        "en": "Here is what I remember about you:",
    },
    "footer": {
        "hinglish": "Kuch galat ho toh 'bhool jao <cheez>' likhiye. Sab mitane ke liye 'delete everything'.",
        "hi": "कुछ गलत हो तो 'भूल जाओ <चीज़>' लिखिए। सब मिटाने के लिए 'delete everything'.",
        "en": "If something is wrong, write 'forget <item>'. To erase everything, write 'delete everything'.",
    },
    "empty": {
        "hinglish": "Abhi mujhe aapke baare mein kuch khaas yaad nahi hai. Jo aap batayenge, wahi yaad rakhungi.",
        "hi": "अभी मुझे आपके बारे में कुछ खास याद नहीं है। जो आप बताएँगे, वही याद रखूँगी।",
        "en": "I don't remember much about you yet. I only keep what you tell me.",
    },
    "source_said": {"hinglish": "aapne bataya", "hi": "आपने बताया", "en": "you told me"},
    "source_done": {"hinglish": "kaam hua", "hi": "काम हुआ", "en": "done together"},
    "source_inferred": {"hinglish": "mera andaza", "hi": "मेरा अंदाज़ा", "en": "my guess"},
}


def line(key: str, lang: str = "hinglish") -> str:
    v = LINES[key]
    return v.get(lang) or v["hinglish"]
