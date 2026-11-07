"""Short-lived spoken replies for the widget (``reply_audio_url``).

The reply is Robin's own text-to-speech, never the parent's recording. It lives in memory only (never on disk, never in the
database), behind an unguessable token (256 random bits), for ``ttl_s`` seconds, and is DELETED by the first fetch. The token is the
credential, so a player that cannot send headers still works; a wrong, used or expired token is a plain 404. The URL carries no
parent id. A cap on the number of waiting clips keeps memory bounded on a small server.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,64}")
MAX_CLIP_BYTES = 1_048_576
DEFAULT_TTL_S = 90.0
DEFAULT_MAX_CLIPS = 64
SAFE_MIME = re.compile(r"[a-z]+/[a-z0-9.+-]+(; ?[a-z0-9=.+ -]+)?", re.I)


@dataclass
class _Clip:
    parent_id: str
    data: bytes
    mime: str
    expires: float


class ReplyAudioStore:
    def __init__(self, ttl_s: float = DEFAULT_TTL_S, max_clips: int = DEFAULT_MAX_CLIPS, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s, self.max_clips, self._clock = ttl_s, max_clips, clock
        self._clips: dict[str, _Clip] = {}

    def put(self, parent_id: str, data: bytes, mime: str) -> str | None:
        """Hold ``data`` and return its token, or None when it is empty/too big (the reply is then text only)."""
        if not data or len(data) > MAX_CLIP_BYTES:
            return None
        self.sweep()
        while len(self._clips) >= self.max_clips:
            self._clips.pop(next(iter(self._clips)))  # oldest first
        token = secrets.token_urlsafe(32)
        self._clips[token] = _Clip(parent_id, data, mime if SAFE_MIME.fullmatch(mime or "") else "application/octet-stream", self._clock() + self.ttl_s)
        return token

    def take(self, token: str) -> tuple[bytes, str] | None:
        """The clip for ``token`` and DELETE it (one fetch). None when unknown, used or expired."""
        if not TOKEN_RE.fullmatch(token or ""):
            return None
        clip = self._clips.pop(token, None)
        if clip is None or clip.expires <= self._clock():
            return None
        return clip.data, clip.mime

    def sweep(self) -> int:
        now = self._clock()
        dead = [t for t, c in self._clips.items() if c.expires <= now]
        for t in dead:
            del self._clips[t]
        return len(dead)

    def drop_parent(self, parent_id: str) -> int:
        dead = [t for t, c in self._clips.items() if c.parent_id == parent_id]
        for t in dead:
            del self._clips[t]
        return len(dead)

    def __len__(self) -> int:
        return len(self._clips)
