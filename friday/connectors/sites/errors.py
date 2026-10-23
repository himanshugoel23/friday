"""Errors of the agent layer. Messages carry selector KEYS and reasons, never page text."""

from __future__ import annotations

from friday.connectors.contract import ConnectorError


class DomainNotAllowed(ConnectorError):
    """The browser was asked to open a host that is not on the site's allow-list."""


class UnsafeAction(ConnectorError):
    """The safety gate refused an action (secret typing, payment wording, no approval)."""


class VerifyFailed(ConnectorError):
    """The page after an action is not what we expected (block page, error banner, no result)."""


class SiteBlocked(ConnectorError):
    """CAPTCHA / bot check / access denied. We stop; we never try to get around it."""


class OutOfStock(ConnectorError):
    """Something the user asked for is sold out or taken. ``names`` lists what (page labels)."""

    def __init__(self, message: str, names: list[str] | None = None) -> None:
        super().__init__(message)
        self.names = names or []


class RepairBudgetExceeded(ConnectorError):
    """More than the allowed number of selector repairs were needed for one task."""
