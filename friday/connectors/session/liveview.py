"""Live view + takeover, behind expiring single-use links.

Flow: ``create_link(task_id)`` -> token (24 random bytes, only its hash is kept). Opening the link
CONSUMES the token and yields a view id (also random, own expiry, bound to the task). The view polls
masked screenshots (rate limited). "Take over" pauses Friday and lets the user click / type into
the page; "Give back" resumes Friday. Ending the task, the kill switch, or expiry revokes everything.

What we do NOT capture: typed text and keys go straight to the page and are only counted; frames
always paint over password / OTP / phone inputs; cookies are never read here (the vault stores
them, encrypted, only on a clean close by the manager).
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from friday.connectors.session.manager import SessionManager, TakeoverError, TaskSession


def _h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


@dataclass
class _Link:
    task_id: str
    expires_at: float
    allow_takeover: bool


@dataclass
class ViewHandle:
    view_id: str
    task_id: str
    expires_at: float
    allow_takeover: bool


class LiveViewService:
    def __init__(self, manager: SessionManager, *, clock: Callable[[], float] = time.time) -> None:
        self.mgr, self._clock = manager, clock
        self._links: dict[str, _Link] = {}
        self._views: dict[str, ViewHandle] = {}
        self._last_frame: dict[str, tuple[float, bytes]] = {}
        manager.on_close(self.revoke_task)

    def create_link(self, task_id: str, *, allow_takeover: bool = True,
                    ttl: float | None = None) -> str:
        sess = self.mgr.get(task_id)
        if sess is None:
            raise TakeoverError("no such session")
        token = secrets.token_urlsafe(24)
        self._links[_h(token)] = _Link(
            task_id, self._clock() + (ttl or self.mgr.settings.live_link_ttl_seconds),
            allow_takeover)
        self.mgr.audit.record("live_link_created", task_id=task_id, user_id=sess.info.user_id,
                              site=sess.info.site)
        return token

    def open_view(self, token: str) -> ViewHandle | None:
        link = self._links.pop(_h(token), None)  # single use: gone even if expired
        if link is None or self._clock() >= link.expires_at or self.mgr.get(link.task_id) is None:
            return None
        view_id = secrets.token_urlsafe(24)
        vh = ViewHandle(view_id, link.task_id,
                        self._clock() + self.mgr.settings.live_view_ttl_seconds,
                        link.allow_takeover)
        self._views[_h(view_id)] = vh
        sess = self.mgr.get(link.task_id)
        assert sess is not None
        self.mgr.audit.record("live_view_opened", task_id=link.task_id,
                              user_id=sess.info.user_id, site=sess.info.site)
        return vh

    def _resolve(self, view_id: str) -> tuple[ViewHandle, TaskSession] | None:
        vh = self._views.get(_h(view_id))
        if vh is None:
            return None
        sess = self.mgr.get(vh.task_id)
        if self._clock() >= vh.expires_at or sess is None or sess.closed:
            self._views.pop(_h(view_id), None)
            return None
        return vh, sess

    def state(self, view_id: str) -> dict[str, Any] | None:
        r = self._resolve(view_id)
        if r is None:
            return None
        vh, sess = r
        return {"mode": sess.info.mode, "can_takeover": vh.allow_takeover,
                "host": sess.current_host(), "expires_in": int(vh.expires_at - self._clock())}

    async def frame(self, view_id: str) -> bytes | None:
        r = self._resolve(view_id)
        if r is None:
            return None
        _vh, sess = r
        now = self._clock()
        last = self._last_frame.get(view_id)
        if last and (now - last[0]) * 1000 < self.mgr.settings.frame_min_interval_ms:
            return last[1]
        png = await sess.frame()
        self._last_frame[view_id] = (now, png)
        return png

    async def start_takeover(self, view_id: str) -> bool:
        r = self._resolve(view_id)
        if r is None or not r[0].allow_takeover:
            return False
        r[1].begin_takeover()
        return True

    async def give_back(self, view_id: str) -> bool:
        r = self._resolve(view_id)
        if r is None or not r[1].takeover_active:
            return False
        r[1].give_back()
        return True

    async def send_input(self, view_id: str, event: Mapping[str, Any]) -> bool:
        r = self._resolve(view_id)
        if r is None:
            return False
        await r[1].takeover_input(event)
        return True

    def revoke_task(self, task_id: str) -> None:
        for k in [k for k, v in self._views.items() if v.task_id == task_id]:
            self._views.pop(k, None)
        for k in [k for k, v in self._links.items() if v.task_id == task_id]:
            self._links.pop(k, None)
        self._last_frame.clear()
