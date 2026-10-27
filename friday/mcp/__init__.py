"""In-process tool contract (MCP-shaped) for the private browser tools.

Every tool has a JSON schema, a permission level (read / reversible / irreversible), an audit entry per
call, a per-tool kill switch and per-user scoping. The same definitions can later be served by a remote
MCP server without changing callers. Fakes live in ``friday.mcp.fakes``.
"""

from friday.mcp.audit import AuditEntry, AuditLog
from friday.mcp.browser_tools import BROWSER_TOOLS, build_browser_registry
from friday.mcp.registry import CallContext, ToolError, ToolRegistry
from friday.mcp.schema import Level, ToolDef, validate

__all__ = [
    "BROWSER_TOOLS", "AuditEntry", "AuditLog", "CallContext", "Level", "ToolDef", "ToolError",
    "ToolRegistry", "build_browser_registry", "validate",
]
