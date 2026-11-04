"""In-memory per-parent state for the device side.

Phase 1 keeps this in process (a restart forgets events, counters, prompts and the shadow clock; the
paired devices would have to be re-paired). Persisting it is a wiring task for the lead (one table per
collection below; the shapes are plain dataclasses). What is held: signal events (enums, counts,
timestamps), counters, trusted-number HASHES, prompts, and the audit of what the child was told. Never
message text, contact names or digits.
"""

from __future__ import annotations

import hashlib
import secrets
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

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


class DeviceStore:
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

    # --- tokens
    def bind_token(self, parent_id: str, token_hash: str) -> None:
        self._by_token[token_hash] = parent_id

    def unbind_token(self, token_hash: str) -> None:
        self._by_token.pop(token_hash, None)

    def parent_for_token(self, token: str) -> ParentState | None:
        pid = self._by_token.get(sha256_hex(token))
        return self._parents.get(pid) if pid else None

    # --- pairing codes (single use, short lived, stored hashed)
    def put_code(self, parent_id: str, code: str, expires_ms: int) -> None:
        for h, (pid, _) in list(self._codes.items()):
            if pid == parent_id:
                del self._codes[h]  # one live code per parent
        self._codes[sha256_hex(code)] = (parent_id, expires_ms)

    def take_code(self, code: str, now_ms: int) -> str | None:
        entry = self._codes.pop(sha256_hex(code), None)
        if entry is None or entry[1] < now_ms:
            return None
        return entry[0]

    def drop(self, parent_id: str) -> None:
        st = self._parents.pop(parent_id, None)
        if st and st.device:
            self.unbind_token(st.device.token_hash)
        for h, (pid, _) in list(self._codes.items()):
            if pid == parent_id:
                del self._codes[h]
