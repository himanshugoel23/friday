"""Provider block / reject signals (NP-4) -> ``"blocked"`` | ``"rejected"`` | None.

A carrier or analytics app blocking Friday's caller ID must reach the number pool's
health score. The runner turns a signal into ``CallResult.error = "call blocked by ..."``
(dial_status FAILED), which Backend B's engine maps to ``NumberOutcome.BLOCKED/REJECTED``.
SIP codes: 603 Decline -> rejected; 403 Forbidden, 607 Unwanted, 608 Rejected by
intermediary (spam analytics) -> blocked.
TODO(verify per provider docs): Twilio ``SipResponseCode`` on the status callback,
Exotel call-details ``Reason``, Vobiz/Plivo ``HangupCauseName``.
"""

from __future__ import annotations

import re

_SIP = {"603": "rejected", "403": "blocked", "607": "blocked", "608": "blocked"}
_BLOCK = re.compile(r"spam|block|unwanted|reputation|blacklist|scam", re.I)
_REJECT = re.compile(r"reject|declin|refus", re.I)


def block_signal(sip_code: str | int | None = None, reason: str | None = None) -> str | None:
    if sip_code is not None and str(sip_code) in _SIP:
        return _SIP[str(sip_code)]
    if reason:
        if _BLOCK.search(reason):
            return "blocked"
        if _REJECT.search(reason):
            return "rejected"
    return None
