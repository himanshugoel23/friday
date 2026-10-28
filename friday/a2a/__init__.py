# ruff: noqa: E501
"""A2A (Agent2Agent) interface: every team member is an A2A agent; the PM is the A2A client.
Agents never call each other's Python. See docs/AGENT_TEAM_DESIGN.md."""

from friday.a2a.audit import A2AAudit
from friday.a2a.budget import BudgetExceeded, TaskBudget
from friday.a2a.client import A2AClient, A2AClientError
from friday.a2a.server import A2AServer, AgentReply, IncomingCall
from friday.a2a.transport import HttpTransport, InProcessTransport
from friday.a2a.types import AgentCard, Message, Part, Skill, Task, TaskState

__all__ = [
    "A2AAudit", "A2AClient", "A2AClientError", "A2AServer", "AgentCard", "AgentReply", "BudgetExceeded",
    "HttpTransport", "InProcessTransport", "IncomingCall", "Message", "Part", "Skill", "Task",
    "TaskBudget", "TaskState",
]  # fmt: skip
