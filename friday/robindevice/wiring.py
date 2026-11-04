"""Mount the device API when FRIDAY_ROBIN_DEVICE_ENABLED is on AND the lead has wired the family ports.

The family package registers its adapters on the container as ``robin_device_ports`` (a dict with
``alerts``, ``consent``, ``parents`` and optional ``voice``/``llm``). Until then nothing is mounted: this
package never falls back to fakes in a live app.
"""

from __future__ import annotations

from typing import Any

from friday.core.logging import get_logger
from friday.robindevice.brand import brand_name

log = get_logger(__name__)


def maybe_mount(app: Any, container: Any) -> Any | None:
    settings = container.settings
    if not getattr(settings, "robin_device_enabled", False):
        return None
    try:
        ports = container.get("robin_device_ports")
    except Exception:  # noqa: BLE001 - not wired yet
        log.warning("FRIDAY_ROBIN_DEVICE_ENABLED is on but robin_device_ports is not wired; device API not mounted")
        return None
    if not ports:
        log.warning("FRIDAY_ROBIN_DEVICE_ENABLED is on but the family package is off (FRIDAY_ROBIN_ENABLED); device API not mounted")
        return None
    from friday.robindevice.api import mount_robin_device
    from friday.robindevice.service import DeviceService

    service = DeviceService(
        alerts=ports["alerts"], consent=ports["consent"], parents=ports["parents"],
        voice=ports.get("voice"), llm=ports.get("llm"), brand=brand_name(settings),
    )
    mount_robin_device(app, service)
    return service
