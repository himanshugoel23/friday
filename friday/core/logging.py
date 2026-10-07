"""Logging setup and PII helpers.

Use ``get_logger(__name__)`` everywhere. Never log raw phone numbers, PINs, audio,
or full message bodies at INFO; use ``mask_phone`` / ``truncate``.

Owner: Engineering Manager (core, frozen).
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


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
    root.addHandler(handler)
    for noisy in ("httpx", "httpcore", "anthropic", "sqlalchemy.engine"):
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
