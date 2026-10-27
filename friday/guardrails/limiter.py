# ruff: noqa: E501
"""Abuse and volume gate, per user (layer 1 of docs/CHATBOT_GUARDRAILS.md).

* more than ``max_per_minute`` messages in a minute, or the same message ``repeat_limit`` times
  within ``repeat_window``, mutes the user for ``mute_for``;
* ``strike_limit`` strikes (harmful requests) within ``strike_window`` also mute, for ``strike_mute``;
* the user hears ONE notice when the mute starts; while muted the answer is silence;
* messages that are safety-critical bypass the gate (the engine never asks it about those).

In memory and per process (a restart forgets mutes, which only ever errs towards letting people
talk); state is bounded. Nothing here stores message text, only a short hash of it.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MAX_USERS = 20_000


@dataclass
class LimiterConfig:
    max_per_minute: int = 20
    repeat_limit: int = 4
    repeat_window: timedelta = timedelta(minutes=2)
    mute_for: timedelta = timedelta(minutes=5)
    strike_limit: int = 3
    strike_window: timedelta = timedelta(hours=24)
    strike_mute: timedelta = timedelta(minutes=30)


@dataclass
class _State:
    stamps: deque[datetime] = field(default_factory=deque)
    repeats: deque[tuple[datetime, str]] = field(default_factory=deque)
    strikes: deque[datetime] = field(default_factory=deque)
    muted_until: datetime | None = None
    notified: bool = False


def _h(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").lower().split()).encode()).hexdigest()[:12]


class AbuseLimiter:
    def __init__(self, config: LimiterConfig | None = None) -> None:
        self.cfg = config or LimiterConfig()
        self._users: OrderedDict[str, _State] = OrderedDict()

    def _state(self, user_id: str) -> _State:
        st = self._users.get(user_id)
        if st is None:
            st = self._users[user_id] = _State()
            while len(self._users) > MAX_USERS:
                self._users.popitem(last=False)
        else:
            self._users.move_to_end(user_id)
        return st

    def note(self, user_id: str, text: str, now: datetime) -> str:
        """Record one message. ``ok`` | ``notice`` (just muted: say the one line) | ``silent``."""
        st = self._state(user_id)
        if st.muted_until is not None:
            if now < st.muted_until:
                return "silent"
            st.muted_until, st.notified = None, False
        c = self.cfg
        st.stamps.append(now)
        while st.stamps and now - st.stamps[0] > timedelta(minutes=1):
            st.stamps.popleft()
        h = _h(text)
        st.repeats.append((now, h))
        while st.repeats and now - st.repeats[0][0] > c.repeat_window:
            st.repeats.popleft()
        too_fast = len(st.stamps) > c.max_per_minute
        repeated = sum(1 for _, x in st.repeats if x == h) >= c.repeat_limit
        if too_fast or repeated:
            return self._mute(st, now, c.mute_for)
        return "ok"

    def strike(self, user_id: str, now: datetime) -> str:
        """Count one harmful request. ``notice`` when this one trips the mute, else ``ok``."""
        st = self._state(user_id)
        c = self.cfg
        st.strikes.append(now)
        while st.strikes and now - st.strikes[0] > c.strike_window:
            st.strikes.popleft()
        if len(st.strikes) >= c.strike_limit:
            st.strikes.clear()
            return self._mute(st, now, c.strike_mute)
        return "ok"

    def _mute(self, st: _State, now: datetime, span: timedelta) -> str:
        st.muted_until = now + span
        first = not st.notified
        st.notified = True
        return "notice" if first else "silent"

    def is_muted(self, user_id: str, now: datetime) -> bool:
        st = self._users.get(user_id)
        return bool(st and st.muted_until and now < st.muted_until)

    def strikes(self, user_id: str) -> int:
        st = self._users.get(user_id)
        return len(st.strikes) if st else 0
