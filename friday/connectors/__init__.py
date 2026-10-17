"""Browser-based internal connectors (docs/CONNECTORS.md, docs/BROWSER_AGENT_PLAN.md).

One typed contract per use case (food first), several interchangeable backends behind it, a
registry with a kill switch, an action gate in front of every state-changing tool, and a scrubber
so no token, cookie, OTP or phone number reaches the model or the logs. Friday never pays: the
food connector stops at a QR / UPI-intent handoff for the user.
"""

from __future__ import annotations
