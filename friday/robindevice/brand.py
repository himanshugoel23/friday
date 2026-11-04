"""The product name shown to parents. One place: setting ``brand_name`` (env FRIDAY_BRAND_NAME).

Read defensively: the setting may not exist yet on the merged Settings class. The Robin pilot sets 'Robin'.
"""

from __future__ import annotations

import os
from typing import Any

DEFAULT_BRAND = "Friday"


def brand_name(settings: Any = None) -> str:
    value = getattr(settings, "brand_name", None) if settings is not None else None
    if not value:
        value = os.environ.get("FRIDAY_BRAND_NAME")
    value = (str(value).strip() if value else "")[:24]
    return value or DEFAULT_BRAND
