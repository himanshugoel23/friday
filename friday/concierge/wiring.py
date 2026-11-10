# ruff: noqa: E501
"""Mount the human desk when FRIDAY_ROBIN_CONCIERGE_ENABLED is on AND the lead has wired the real ports.

The container component ``concierge_ports`` is a dict with ``directory`` (StaffDirectory), ``totp`` (TotpVerifier), ``family`` (FamilyLookup)
and optional ``emergency`` (EmergencyReroute; default = the Robin alert engine), ``bridge`` (MaskedBridge), ``pager`` (Pager).
Until the directory, TOTP verifier and family lookup are wired nothing is mounted: this package never falls back to fakes in a live app.
The real masked-contact bridge, TOTP verifier, staff directory and pager are unbuilt [U].
"""

from __future__ import annotations

from typing import Any

from friday.concierge import humanport
from friday.concierge.audit import AuditLog
from friday.concierge.auth import Sessions
from friday.concierge.console import build_console
from friday.concierge.desk import DeskService
from friday.concierge.service import ConciergeService, DeskSettings
from friday.core.logging import get_logger

log = get_logger(__name__)
REQUIRED = ("directory", "totp", "family")


class RobinEmergencyReroute:
    """Distress text in an errand goes to the AI emergency path (friday/robin alerts), never to a human errand queue."""

    async def reroute(self, *, member_id: str, parent_id: str, reason: str) -> str | None:  # noqa: ARG002
        from friday.robin.alerts import RobinAlert, raise_alert
        from friday.robin.models import Tier

        res = await raise_alert(RobinAlert(parent_member_id=parent_id, tier=Tier.HIGH, scenario="concierge_distress", why="Asked for help in a request", dedupe_key=f"concierge:{member_id}"))
        return res.incident_id


class NullPager:
    """No pager is built yet [U]: every page 'fails', so the desk logs 'did not answer' and the family ladder carries on."""

    async def page(self, staff_id: str, handoff_id: str) -> bool:  # noqa: ARG002
        return False


def build_ports(container: Any) -> dict[str, Any]:  # noqa: ARG001
    """Default for the container: only the Robin-backed emergency adapter exists. The rest is [U] and wired by the lead."""
    return {"emergency": RobinEmergencyReroute()}


def build_store(container: Any) -> Any:
    from friday.concierge.store import InMemoryConciergeStore

    try:
        db = container.get("repos").db
    except Exception:  # noqa: BLE001
        db = None
    if db is None:
        log.warning("concierge: no database, desk state is kept in memory only (a restart forgets it)")
        return InMemoryConciergeStore()
    from friday.concierge.dbmodel import DbConciergeStore

    return DbConciergeStore(db)


def build_desk(container: Any, ports: dict[str, Any], store: Any | None = None) -> dict[str, Any]:
    st = store or build_store(container)
    cfg = DeskSettings.from_settings(container.settings)
    audit = AuditLog(st, container.clock)
    service = ConciergeService(store=st, audit=audit, clock=container.clock, family=ports["family"], directory=ports["directory"],
                               emergency=ports.get("emergency") or RobinEmergencyReroute(), bridge=ports.get("bridge"), settings=cfg)
    desk = DeskService(store=st, audit=audit, clock=container.clock, directory=ports["directory"], pager=ports.get("pager") or NullPager(), settings=cfg)
    sessions = Sessions(ports["directory"], ports["totp"], container.clock, idle_timeout_s=cfg.idle_timeout_s)
    return {"store": st, "audit": audit, "service": service, "desk": desk, "sessions": sessions}


def maybe_mount(app: Any, container: Any) -> dict[str, Any] | None:
    if not getattr(container.settings, "robin_concierge_enabled", False):
        return None
    try:
        ports = container.get("concierge_ports")
    except Exception:  # noqa: BLE001
        ports = None
    if not ports or any(k not in ports for k in REQUIRED):
        log.warning("FRIDAY_ROBIN_CONCIERGE_ENABLED is on but the staff directory, TOTP verifier or family lookup is not wired; desk not mounted")
        return None
    parts = build_desk(container, ports)
    app.include_router(build_console(parts["service"], parts["desk"], parts["sessions"], parts["audit"], secure_cookie=bool(getattr(container.settings, "is_live", False))), prefix="/concierge")
    app.state.concierge = parts
    humanport.register_human_joined(parts["desk"].is_human_joined)  # the AI ladder stops re-ringing once a person joined
    from friday.robin.ports import register_erase_hook

    register_erase_hook("concierge", parts["service"].erase_parent)  # "delete everything" drops errands and handoffs of that parent
    return parts
