# ruff: noqa: E501
"""Site MCP: one small MCP server per app (Zepto, Blinkit, Swiggy Instamart ...) that drives a normal browser as the
USER on their own account. Design, boundaries and server prerequisites: docs/SITE_MCP_DESIGN.md.

Switch: FRIDAY_SITE_MCP_ENABLED (default OFF). There is NO pay / place-order tool anywhere in this package.
"""

from friday.sitemcp.tools import FORBIDDEN_TOOL_WORDS, TOOL_NAMES

__all__ = ["FORBIDDEN_TOOL_WORDS", "TOOL_NAMES"]
