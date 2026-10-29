# ruff: noqa: E501
"""Errors a page provider may raise. The loop maps them to stable run statuses."""

from __future__ import annotations


class Blocked(Exception):
    """The site showed a challenge / denial / robots rule. We stop (no captcha solving, no retry loop)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Busy(Exception):
    """No browser capacity right now (RAM guard, session cap, page cap, pacing). The run stays resumable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ActionFailed(Exception):
    """The page could not do the action (element gone, timeout). Message carries no page content."""
