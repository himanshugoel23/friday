"""scrub(): remove secrets from anything a model or a log line might see.

Targets: OTP-like codes near words like otp/code, cookies, bearer tokens, key=value secrets, long
hex / base64 blobs and phone numbers. Dict values under sensitive keys are dropped entirely. This
is a safety net, not the control: connectors also never put these values in their results.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

OTP = "[REDACTED_OTP]"
SECRET = "[REDACTED_SECRET]"
PHONE = "[REDACTED_PHONE]"
COOKIE = "[REDACTED_COOKIE]"
SENSITIVE_KEYS = re.compile(
    r"(?i)(otp|passcode|password|passwd|pin|cookie|token|secret|authorization|api[_-]?key|"
    r"session[_-]?id|csrf|cvv|card)"
)

_KW = r"(?:otp|one[- ]time|passcode|pass code|verification|security code|login code|code|pin)"
_OTP_AFTER = re.compile(rf"(?i)(\b{_KW}\b[^0-9\n]{{0,25}}?)(\d(?:[ -]?\d){{3,7}})(?!\d)")
_OTP_BEFORE = re.compile(rf"(?i)(?<![\d.])(\d{{4,8}})(?![\d.])(?=[^\n]{{0,30}}\b{_KW}\b)")
_COOKIE = re.compile(r"(?i)\b((?:set-)?cookie)\s*[:=]\s*[^\n]+")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}")
_KV_SECRET = re.compile(
    r"(?i)\b((?:access[_-]?|refresh[_-]?|id[_-]?|auth[_-]?)?token|api[_-]?key|secret|password|"
    r"passwd|session[_-]?id|sessionid|sid|csrf[_-]?token|authorization)(\"?\s*[:=]\s*\"?)"
    r"[^\s\"',;&]+"
)
_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_B64 = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/_-])")
_PHONE = re.compile(
    r"(?<![\w.])(?:\+\s?\d{1,3}[\s-]?\d[\d\s-]{7,12}\d|(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5})"
    r"(?![\w])"
)


def _b64_repl(m: re.Match[str]) -> str:
    s = m.group(0)
    # Only real-looking secrets: mixed letters and digits, and not a plain path / slug.
    if any(c.isdigit() for c in s) and any(c.isalpha() for c in s) and s.count("/") < 3:
        return SECRET
    return s


def scrub_text(text: str) -> str:
    text = _COOKIE.sub(lambda m: f"{m.group(1)}: {COOKIE}", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} {SECRET}", text)
    text = _KV_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{SECRET}", text)
    text = _OTP_AFTER.sub(lambda m: m.group(1) + OTP, text)
    text = _OTP_BEFORE.sub(OTP, text)
    text = _PHONE.sub(PHONE, text)
    text = _HEX.sub(SECRET, text)
    return _B64.sub(_b64_repl, text)


def scrub(obj: Any) -> Any:
    """Scrubbed copy of a str / dict / list / tuple / pydantic model (bytes are summarised)."""
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, bytes | bytearray):
        return f"<{len(obj)} bytes>"
    if isinstance(obj, BaseModel):
        return scrub(obj.model_dump())
    if isinstance(obj, dict):
        return {
            k: (SECRET if isinstance(k, str) and SENSITIVE_KEYS.search(k) and v else scrub(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list | tuple | set | frozenset):
        scrubbed = [scrub(v) for v in obj]
        return tuple(scrubbed) if isinstance(obj, tuple) else scrubbed
    return obj
