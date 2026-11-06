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
        store=_build_store(container),
    )
    mount_robin_device(app, service)
    _attach_sweep(container, service)
    from friday.robin.ports import register_erase_hook

    register_erase_hook("robindevice", service.erase_parent)  # 'delete everything' drops device rows, token cache and analyzers
    return service


def _build_store(container: Any) -> Any:
    """DB-backed store (migration 0020_robin_device) when the container has a database; else in memory."""
    from friday.robindevice.store import InMemoryDeviceStore

    try:
        db = container.get("repos").db
    except Exception:  # noqa: BLE001 - no database wired
        db = None
    if db is None:
        log.warning("robin device: no database, device state is kept in memory only (a restart forgets pairings)")
        return InMemoryDeviceStore()
    from friday.robindevice.dbmodel import DbDeviceStore

    return DbDeviceStore(db)


def _attach_sweep(container: Any, service: Any) -> None:
    """Let the Robin scheduler (``RobinHub.tick``) run ``DeviceService.sweep`` (S7 unreachable, S8 season)."""
    try:
        hub = container.get("robin")
    except Exception:  # noqa: BLE001
        hub = None
    if hub is not None and hasattr(hub, "attach_device_sweep"):
        hub.attach_device_sweep(service.sweep)
