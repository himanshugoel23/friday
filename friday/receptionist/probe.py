# ruff: noqa: E501
"""The forwarding probe: what does the provider's inbound webhook carry for a FORWARDED call?

UNKNOWN for Vobiz (docs do not say). The probe records, for every inbound webhook, the key names
and, for values that look like phone numbers, only a masked form. It also lists CANDIDATE keys:
any key (other than From / To) whose value is a phone number different from the caller and from
the dialled Friday number, which is where a redirecting number would show up. No full number and
no other value is ever written.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from friday.core.logging import mask_phone

_PHONEISH = re.compile(r"(?:\+?\d[\d\s\-()]{7,}\d)")
_BASE_KEYS = {"from", "to", "caller", "called", "callerid"}
PROBE_FILE = "probe.jsonl"


def _digits(v: str) -> str:
    return re.sub(r"\D", "", v)


def phone_like(value: str) -> list[str]:
    """Phone-number-like substrings of ``value`` (digits, at least 10)."""
    out = []
    for m in _PHONEISH.finditer(value or ""):
        d = _digits(m.group())
        if len(d) >= 10:
            out.append(d[-10:] if len(d) > 12 else d)
    return out


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and a[-10:] == b[-10:]


@dataclass
class Candidate:
    key: str
    masked: str
    configured: bool  # the key is already in FRIDAY_RECEPTIONIST_REDIRECT_FIELDS


@dataclass
class ProbeEntry:
    at: str
    keys: list[str]
    caller_masked: str
    dialled_masked: str
    candidates: list[Candidate] = field(default_factory=list)
    phone_keys: dict[str, str] = field(default_factory=dict)  # key -> masked number

    def to_json(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "keys": self.keys,
            "caller": self.caller_masked,
            "dialled": self.dialled_masked,
            "phone_keys": self.phone_keys,
            "candidates": [c.__dict__ for c in self.candidates],
        }


def analyse(
    params: Mapping[str, str], configured_fields: Iterable[str] = (), *, now: datetime | None = None
) -> ProbeEntry:
    cfg = {f.lower() for f in configured_fields}
    low = {k.lower(): (k, str(v)) for k, v in params.items()}
    caller = next((low[k][1] for k in ("from", "caller", "callerid") if k in low), "")
    dialled = next((low[k][1] for k in ("to", "called") if k in low), "")
    e = ProbeEntry(
        at=(now or datetime.now(UTC)).isoformat(timespec="seconds"),
        keys=sorted(params),
        caller_masked=mask_phone("+" + _digits(caller)) if _digits(caller) else "<none>",
        dialled_masked=mask_phone("+" + _digits(dialled)) if _digits(dialled) else "<none>",
    )
    for k, v in params.items():
        nums = phone_like(str(v))
        if not nums:
            continue
        masked = ",".join(mask_phone("+" + n) for n in nums)
        e.phone_keys[k] = masked
        if k.lower() in _BASE_KEYS:
            continue
        other = [n for n in nums if not _same(n, _digits(caller)) and not _same(n, _digits(dialled))]
        if other:
            e.candidates.append(Candidate(k, masked, k.lower() in cfg))
    return e


class InboundProbe:
    """Collects entries in memory and (when ``path`` is given) appends them to a JSONL file."""

    def __init__(self, configured_fields: Iterable[str] = (), path: Path | None = None) -> None:
        self.fields = list(configured_fields)
        self.path = path
        self.entries: list[ProbeEntry] = []
        self._waiters: list[Any] = []

    def record(self, params: Mapping[str, str], *, now: datetime | None = None) -> ProbeEntry:
        e = analyse(params, self.fields, now=now)
        self.entries.append(e)
        del self.entries[:-200]
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(e.to_json(), ensure_ascii=False) + "\n")
            except OSError:
                pass  # a probe must never break a call
        for w in list(self._waiters):
            if e.candidates:
                w.set()
        return e

    async def wait_for_candidate(self, timeout_s: float) -> bool:
        import asyncio

        ev = asyncio.Event()
        self._waiters.append(ev)
        try:
            await asyncio.wait_for(ev.wait(), timeout_s)
            return True
        except TimeoutError:
            return False
        finally:
            self._waiters.remove(ev)


def load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def format_report(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            "No inbound webhook recorded yet. Set FRIDAY_RECEPTIONIST_PROBE=true, restart "
            "`friday listen`, forward your phone to Friday's number and call yourself."
        )
    out = [f"{len(rows)} inbound webhook(s) recorded (numbers masked):"]
    for r in rows[-10:]:
        out.append(f"- {r['at']}  caller {r['caller']}  dialled {r['dialled']}")
        out.append(f"    keys: {', '.join(r['keys'])}")
        if r["candidates"]:
            for c in r["candidates"]:
                tag = "already configured" if c["configured"] else "ADD THIS KEY to FRIDAY_RECEPTIONIST_REDIRECT_FIELDS"
                out.append(f"    CANDIDATE redirecting-number key: {c['key']} = {c['masked']}  ({tag})")
        else:
            out.append("    no key carries a third number: the redirecting number was NOT delivered")
    return "\n".join(out)


# ---------------------------------------------------------------- hook used by the Vobiz adapter
_ACTIVE: dict[str, Any] = {"fields": (), "probe": None}
# keys whose NAME suggests a diversion, and every custom (x-*) header, are captured as call_fields
_CAPTURE_HINTS = ("diver", "history", "forward", "redirect", "original")
_MAX_FIELDS, _MAX_VALUE = 12, 300


def configure(fields: Iterable[str], probe: InboundProbe | None) -> None:
    """Called once at start-up (``wiring.build_receptionist``). With nothing configured
    ``observe_inbound`` does nothing, so the telephony adapter behaves exactly as before."""
    _ACTIVE["fields"] = tuple(fields)
    _ACTIVE["probe"] = probe


def observe_fields(params: Mapping[str, str]) -> dict[str, str]:
    """The diversion-related fields of an inbound answer webhook (configured keys, Diversion /
    History-Info style names and every ``x-*`` header), value-capped, WITHOUT the base From / To keys.
    Empty unless the receptionist or its probe is configured. Never raises; never logged."""
    try:
        if not (_ACTIVE["fields"] or _ACTIVE["probe"] is not None):
            return {}
        cfg = {str(f).lower() for f in _ACTIVE["fields"]}
        out: dict[str, str] = {}
        for k, v in params.items():
            kl = str(k).lower()
            if kl in _BASE_KEYS or v is None or not str(v).strip():
                continue
            if kl in cfg or kl.startswith(("x-", "x_")) or any(h in kl for h in _CAPTURE_HINTS):
                out[str(k)] = str(v)[:_MAX_VALUE]
            if len(out) >= _MAX_FIELDS:
                break
        return out
    except Exception:  # noqa: BLE001 - observing must never break a call
        return {}


def verdict(rows: list[dict[str, Any]]) -> tuple[str, str]:
    """(state, text) from recorded probe rows: ``not_run`` | ``delivered`` | ``not_delivered``."""
    if not rows:
        return "not_run", "probe has not been run (no webhook recorded)"
    keys = sorted({c["key"] for r in rows for c in r.get("candidates", [])})
    if keys:
        return "delivered", "the redirecting number IS delivered, in key(s): " + ", ".join(keys)
    return "not_delivered", f"the redirecting number was NOT delivered in {len(rows)} recorded call(s)"


def observe_inbound(params: Mapping[str, str]) -> str | None:
    """The raw redirecting-number value of an inbound webhook (first configured key present), and
    a masked probe record when the probe is on. Never raises."""
    try:
        probe: InboundProbe | None = _ACTIVE["probe"]
        if probe is not None:
            probe.record(params)
        low = {k.lower(): v for k, v in params.items()}
        for f in _ACTIVE["fields"]:
            v = low.get(str(f).lower())
            if v and str(v).strip():
                return str(v)
    except Exception:  # noqa: BLE001 - observing must never break a call
        return None
    return None
