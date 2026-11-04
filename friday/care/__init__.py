"""Care protocol: a protected response to distress or self-harm risk (docs/CARE_PROTOCOL.md).

Always on. Not a clinical tool. Entry points: :func:`assess` (rules, three languages),
:class:`CareService` (state machine, check-ins, the central gate).
"""

from friday.care.detect import Assessment, Tier, assess
from friday.care.service import CareService, CareState, CareStore, CareTurn

__all__ = ["Assessment", "CareService", "CareState", "CareStore", "CareTurn", "Tier", "assess"]
