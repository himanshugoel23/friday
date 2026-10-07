"""Logging setup and PII helpers.

Use ``get_logger(__name__)`` everywhere. Never log raw phone numbers, PINs, audio,
or full message bodies at INFO; use ``mask_phone`` / ``truncate``.

Owner: Engineering Manager (core, frozen).
"""

from __future__ import annotations

import logging
import re
import sys

_CONFIGURED = False

# SECURITY-26: loggers that can echo SQL parameters / request bodies (PII) at DEBUG.
QUIET_LOGGERS = (
    "httpx", "httpcore", "anthropic", "sqlalchemy.engine", "sqlalchemy.pool",
    "aiosqlite", "asyncpg", "websockets", "uvicorn.access",
)  # fmt: skip
PII_LOGGERS = ("sqlalchemy.engine", "aiosqlite", "asyncpg")
_PHONE_LIKE = re.compile(r"(?<!\d)(?:\+\d{1,3}[ \-]?)?\d{5}[ \-]?\d{5}(?!\d)|\+?\d{11,15}(?!\d)")


class RedactingFilter(logging.Filter):
    """Masks phone-like digit runs in every record; drops ``args`` of PII-bearing
    loggers entirely (SQL parameters)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith(PII_LOGGERS):
            record.msg = str(record.msg)
            record.args = None
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging
            return True
        record.msg = _PHONE_LIKE.sub(lambda m: mask_phone(re.sub(r"[ \-]", "", m.group())), message)
        record.args = None
        return True


def setup_logging(level: str = "INFO", json: bool = False) -> None:
    """Idempotent root logger configuration. Call once from the entrypoint."""
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level.upper())
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stderr)
    if json:
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    for noisy in QUIET_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def mask_phone(phone: str | None) -> str:
    """'+919876543210' -> '+91******3210'."""
    if not phone:
        return "<none>"
    if len(phone) <= 6:
        return "***"
    return phone[:3] + "*" * (len(phone) - 7) + phone[-4:]


def truncate(text: str | None, limit: int = 80) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
