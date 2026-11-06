"""Per-parent state for the device side, behind one interface with two implementations.

``DeviceStorePort`` is what ``DeviceService`` uses. ``InMemoryDeviceStore`` (this file) is for tests and for
a process with no database. ``DbDeviceStore`` (friday/robindevice/dbmodel.py, migration 0020_robin_device)
keeps the same shapes in encrypted JSON so a restart keeps pairings, tokens (HASH only), events, prompts,
the shadow clock and counters. What is held: signal events (enums, counts, timestamps), counters,
trusted-number HASHES, prompts, and the audit of what the child was told. Never message text, contact
names or digits. ``state_to_dict`` / ``state_from_dict`` are the one serialisation both use.
"""

from __future__ import annotations

import hashlib
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

from friday.robindevice.ports import Sensitivity

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
PAIR_CODE_TTL_S = 15 * 60
MAX_EVENTS = 2000
MAX_SEEN_IDS = 5000
MAX_LOG = 500


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_device_token() -> str:
    return "rbn_" + secrets.token_urlsafe(32)


def new_pair_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


@dataclass
class Event:
    id: str
    type: str
    ts_ms: int
    data: dict[str, Any]


@dataclass
class Device:
    token_hash: str
    paired_ms: int
    last_seen_ms: int
    app_version: str = ""
    os_sdk: int = 0
    roles: dict[str, bool] = field(default_factory=dict)
    battery_low: bool = False


@dataclass
class Prompt:
    id: str
    scenario: str
    tier: str
    key: str  # copy key
    incident: str
    created_ms: int
    not_before_ms: int
    expires_ms: int
    full_screen: bool
    fmt: dict[str, Any]
    pattern: str = ""
    call_hash: str | None = None
    state: str = "open"  # open | acked | dismissed


@dataclass
class Fired:
    rank: int
    ts_ms: int
    shadow: bool
    resolved_until_ms: int = 0


@dataclass
class ParentState:
    parent_id: str
    device: Device | None = None
    events: list[Event] = field(default_factory=list)
    seen_ids: OrderedDict[str, None] = field(default_factory=OrderedDict)
    counters: dict[str, int] = field(default_factory=dict)
    prompts: dict[str, Prompt] = field(default_factory=dict)
    fired: dict[str, Fired] = field(default_factory=dict)
    trusted: set[str] = field(default_factory=set)
    fine_counts: dict[str, int] = field(default_factory=dict)
    nudge_times: list[int] = field(default_factory=list)
    shadow_nudge_times: list[int] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)  # exactly what the child was told
    findings: list[dict[str, Any]] = field(default_factory=list)  # engine log (shadow and live)
    external: dict[str, int] = field(default_factory=dict)  # e.g. checkin_unanswered -> ts
    # preferences (set by the family side)
    sensitivity: Sensitivity = "balanced"
    payment_threshold_paise: int | None = None
    shadow_days: int | None = None
    shadow_start_ms: int | None = None
    support_window_until_ms: int = 0
    paused_until_ms: int = 0  # 0 = not paused; a huge value = until resume
    s7_open: bool = False
    stopped: bool = False  # the PARENT pressed stop; only the parent device can resume
    consent_basis: str = "admin_on_behalf"

    def bump(self, key: str, n: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + n

    def remember_id(self, event_id: str) -> bool:
        """True if new, False if seen before."""
        if event_id in self.seen_ids:
            return False
        self.seen_ids[event_id] = None
        while len(self.seen_ids) > MAX_SEEN_IDS:
            self.seen_ids.popitem(last=False)
        return True

    def log(self, row: dict[str, Any]) -> None:
        self.findings.append(row)
        del self.findings[:-MAX_LOG]

    def record_audit(self, row: dict[str, Any]) -> None:
        self.audit.append(row)
        del self.audit[:-200]



class DeviceStorePort(Protocol):
    """Sync reads of the loaded state, async persistence. ``save`` is called after every service operation."""

    def state(self, parent_id: str) -> ParentState: ...
    def peek(self, parent_id: str) -> ParentState | None: ...
    def parent_ids(self) -> list[str]: ...
    def bind_token(self, parent_id: str, token_hash: str) -> None: ...
    def unbind_token(self, token_hash: str) -> None: ...
    def touch(self, parent_id: str) -> None: ...
    async def ensure_loaded(self) -> None: ...
    async def parent_for_token(self, token: str) -> ParentState | None: ...
    async def put_code(self, parent_id: str, code: str, expires_ms: int) -> None: ...
    async def take_code(self, code: str, now_ms: int) -> str | None: ...
    async def save(self, parent_id: str) -> None: ...
    async def save_dirty(self) -> None: ...
    async def refresh(self, parent_id: str) -> ParentState | None: ...
    async def drop(self, parent_id: str) -> None: ...


class InMemoryDeviceStore:
    def __init__(self) -> None:
        self._parents: dict[str, ParentState] = {}
        self._by_token: dict[str, str] = {}
        self._codes: dict[str, tuple[str, int]] = {}  # sha256(code) -> (parent_id, expires_ms)

    # --- parents
    def state(self, parent_id: str) -> ParentState:
        st = self._parents.get(parent_id)
        if st is None:
            st = self._parents[parent_id] = ParentState(parent_id)
        return st

    def peek(self, parent_id: str) -> ParentState | None:
        return self._parents.get(parent_id)

    def parent_ids(self) -> list[str]:
        return list(self._parents)

    # --- persistence hooks (nothing to persist here)
    def touch(self, parent_id: str) -> None:  # noqa: ARG002
        return None

    async def ensure_loaded(self) -> None:
        return None

    async def save(self, parent_id: str) -> None:  # noqa: ARG002
        return None

    async def save_dirty(self) -> None:
        return None

    async def refresh(self, parent_id: str) -> ParentState | None:
        return self._parents.get(parent_id)

    # --- tokens
    def bind_token(self, parent_id: str, token_hash: str) -> None:
        self._by_token[token_hash] = parent_id

    def unbind_token(self, token_hash: str) -> None:
        self._by_token.pop(token_hash, None)

    async def parent_for_token(self, token: str) -> ParentState | None:
        pid = self._by_token.get(sha256_hex(token))
        return self._parents.get(pid) if pid else None

    # --- pairing codes (single use, short lived, stored hashed)
    async def put_code(self, parent_id: str, code: str, expires_ms: int) -> None:
        for h, (pid, _) in list(self._codes.items()):
            if pid == parent_id:
                del self._codes[h]  # one live code per parent
        self._codes[sha256_hex(code)] = (parent_id, expires_ms)

    async def take_code(self, code: str, now_ms: int) -> str | None:
        entry = self._codes.pop(sha256_hex(code), None)
        if entry is None or entry[1] < now_ms:
            return None
        return entry[0]

    async def drop(self, parent_id: str) -> None:
        st = self._parents.pop(parent_id, None)
        if st and st.device:
            self.unbind_token(st.device.token_hash)
        for h, (pid, _) in list(self._codes.items()):
            if pid == parent_id:
                del self._codes[h]


DeviceStore = InMemoryDeviceStore  # the name the service and the tests always used


# --------------------------------------------------------------------------- serialisation (shared by the DB store)
def _scrub_audit(row: dict[str, Any]) -> dict[str, Any]:
    """The audit keeps what the child was told; precise coordinates are not kept at rest."""
    det = row.get("details")
    if isinstance(det, dict) and "location" in det:
        row = {**row, "details": {**det, "location": True}}
    return row


def state_to_dict(st: ParentState) -> dict[str, Any]:
    d = st.device
    return {
        "v": 1,
        "device": None if d is None else {
            "token_hash": d.token_hash, "paired_ms": d.paired_ms, "last_seen_ms": d.last_seen_ms,
            "app_version": d.app_version, "os_sdk": d.os_sdk, "roles": dict(d.roles), "battery_low": d.battery_low,
        },
        "events": [{"id": e.id, "type": e.type, "ts_ms": e.ts_ms, "data": e.data} for e in st.events],
        "seen_ids": list(st.seen_ids),
        "counters": dict(st.counters),
        "prompts": {k: dict(vars(p)) for k, p in st.prompts.items()},
        "fired": {k: dict(vars(f)) for k, f in st.fired.items()},
        "trusted": sorted(st.trusted),
        "fine_counts": dict(st.fine_counts),
        "nudge_times": list(st.nudge_times),
        "shadow_nudge_times": list(st.shadow_nudge_times),
        "audit": [_scrub_audit(r) for r in st.audit],
        "findings": list(st.findings),
        "external": dict(st.external),
        "sensitivity": st.sensitivity,
        "payment_threshold_paise": st.payment_threshold_paise,
        "shadow_days": st.shadow_days,
        "shadow_start_ms": st.shadow_start_ms,
        "support_window_until_ms": st.support_window_until_ms,
        "paused_until_ms": st.paused_until_ms,
        "s7_open": st.s7_open,
        "stopped": st.stopped,
        "consent_basis": st.consent_basis,
    }


def state_from_dict(parent_id: str, d: dict[str, Any]) -> ParentState:
    st = ParentState(parent_id)
    dev = d.get("device")
    if dev:
        st.device = Device(**dev)
    st.events = [Event(e["id"], e["type"], int(e["ts_ms"]), dict(e.get("data") or {})) for e in d.get("events", [])]
    st.seen_ids = OrderedDict((k, None) for k in d.get("seen_ids", []))
    st.counters = {k: int(v) for k, v in (d.get("counters") or {}).items()}
    st.prompts = {k: Prompt(**v) for k, v in (d.get("prompts") or {}).items()}
    st.fired = {k: Fired(**v) for k, v in (d.get("fired") or {}).items()}
    st.trusted = set(d.get("trusted", []))
    st.fine_counts = {k: int(v) for k, v in (d.get("fine_counts") or {}).items()}
    st.nudge_times = [int(x) for x in d.get("nudge_times", [])]
    st.shadow_nudge_times = [int(x) for x in d.get("shadow_nudge_times", [])]
    st.audit = list(d.get("audit", []))
    st.findings = list(d.get("findings", []))
    st.external = {k: int(v) for k, v in (d.get("external") or {}).items()}
    st.sensitivity = d.get("sensitivity", "balanced")
    st.payment_threshold_paise = d.get("payment_threshold_paise")
    st.shadow_days = d.get("shadow_days")
    st.shadow_start_ms = d.get("shadow_start_ms")
    st.support_window_until_ms = int(d.get("support_window_until_ms", 0))
    st.paused_until_ms = int(d.get("paused_until_ms", 0))
    st.s7_open = bool(d.get("s7_open", False))
    st.stopped = bool(d.get("stopped", False))
    st.consent_basis = d.get("consent_basis", "admin_on_behalf")
    return st
