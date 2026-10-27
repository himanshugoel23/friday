"""Per-user Google OAuth: consent link, callback, refresh, revoke.

Flow (authorization-code with PKCE S256, offline access):

1. ``start(user_id)``  stores a single-use attempt (state nonce hash + PKCE verifier, encrypted)
   and returns a link to Friday's own consent page (copy in ``friday.google.consent_copy``).
2. The page's button sends the user to Google (``consent_url``): ``access_type=offline``,
   ``prompt=consent``, ``include_granted_scopes=false``, least scopes only.
3. ``handle_callback(state, code)`` verifies the signed state (bound to the user, 10 minutes,
   single use), exchanges the code with the PKCE verifier, reads the Google identity, stores the
   tokens ENCRYPTED, and refuses the connection when the calendar scope was not granted.
4. ``access_token(user_id)`` returns a valid access token, refreshing with a margin before
   expiry; ``invalid_grant`` marks the connection ``needs_reconnect``.
5. ``disconnect(user_id)`` revokes at Google (best effort) and ALWAYS deletes the local rows.

Tokens are never logged and never leave this module except as the Bearer header of a Google
call: log lines carry the user id and a short reason code only.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit

import httpx

from friday.core.clock import Clock, SystemClock
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.db.repositories.google import (
    CONNECTED,
    NEEDS_RECONNECT,
    GoogleConnection,
    GoogleRepo,
)
from friday.google import scopes as sc

log = get_logger(__name__)

HttpFactory = Callable[[], httpx.AsyncClient]


class GoogleError(Exception):
    """Base class. ``code`` is a short machine reason; the message never holds a token."""

    code = "google_error"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or (code or self.code))
        if code:
            self.code = code


class NotConfigured(GoogleError):
    code = "not_configured"


class InvalidState(GoogleError):
    code = "invalid_state"


class NotConnected(GoogleError):
    code = "not_connected"


class NeedsReconnect(GoogleError):
    code = "needs_reconnect"


class ScopeMissing(GoogleError):
    code = "scope_missing"


@dataclass(frozen=True)
class ConsentStart:
    link: str
    expires_at: datetime


@dataclass(frozen=True)
class CallbackResult:
    user_id: str
    scopes: list[str]
    email_masked: str | None


@dataclass(frozen=True)
class DisconnectResult:
    deleted: bool
    revoked: bool


@dataclass(frozen=True)
class ConnectionStatus:
    connected: bool
    status: str  # connected | needs_reconnect | not_connected
    scopes: list[str]
    email_masked: str | None
    gmail: bool
    drive: bool = False


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def pkce_challenge(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode()).digest())


def default_http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(10.0))


class GoogleOAuth:
    def __init__(
        self,
        settings: Settings,
        repo: GoogleRepo,
        *,
        clock: Clock | None = None,
        http: HttpFactory | None = None,
    ) -> None:
        self.s = settings
        self.repo = repo
        self.clock: Clock = clock or SystemClock()
        self._http = http or default_http
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ configuration
    @property
    def configured(self) -> bool:
        return bool(
            self.s.google_oauth_client_id
            and self.s.google_oauth_client_secret
            and self.s.google_redirect_uri
        )

    def _require_configured(self) -> None:
        if not self.configured:
            raise NotConfigured("Google connector is not configured on this server")

    @property
    def requested_scopes(self) -> list[str]:
        return sc.requested_scopes(self.s.google_gmail_enabled, self.s.family_drive_enabled)

    @property
    def public_base(self) -> str:
        parts = urlsplit(self.s.google_redirect_uri or "")
        return f"{parts.scheme}://{parts.netloc}"

    # ------------------------------------------------------------------ signed state
    def _sign(self, payload: str) -> str:
        key = self.s.derived_key("google_oauth_state")
        return _b64(hmac.new(key, payload.encode(), hashlib.sha256).digest())

    def make_state(self, user_id: str, nonce: str, expires_at: datetime) -> str:
        payload = f"{user_id}:{int(expires_at.timestamp())}:{nonce}"
        return f"{_b64(payload.encode())}.{self._sign(payload)}"

    def parse_state(self, state: str) -> tuple[str, str]:
        """(user_id, nonce) of a state whose signature and expiry are valid, else InvalidState.
        Single use is enforced separately, by the database."""
        try:
            body, sig = state.split(".", 1)
            payload = _unb64(body).decode()
            user_id, exp, nonce = payload.split(":", 2)
            expires = int(exp)
        except Exception:  # noqa: BLE001 - any malformed value is simply invalid
            raise InvalidState("malformed state") from None
        if not hmac.compare_digest(sig, self._sign(payload)):
            raise InvalidState("bad signature")
        if expires <= int(self.clock.now().timestamp()):
            raise InvalidState("state expired")
        return user_id, nonce

    # ------------------------------------------------------------------ step 1: link
    async def start(self, user_id: str) -> ConsentStart:
        self._require_configured()
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)[:96]  # 43..128 chars, RFC 7636
        expires_at = self.clock.now() + timedelta(seconds=self.s.google_state_ttl_s)
        await self.repo.create_state(
            user_id,
            nonce,
            code_verifier=verifier,
            scopes=self.requested_scopes,
            expires_at=expires_at,
        )
        state = self.make_state(user_id, nonce, expires_at)
        return ConsentStart(f"{self.public_base}/google/consent/{state}", expires_at)

    async def consent_url(self, state: str) -> str | None:
        """Google's consent URL for a pending attempt (None if unknown, used or expired)."""
        self._require_configured()
        try:
            user_id, nonce = self.parse_state(state)
        except InvalidState:
            return None
        pending = await self.repo.peek_state(user_id, nonce)
        if pending is None:
            return None
        params = {
            "client_id": self.s.google_oauth_client_id,
            "redirect_uri": self.s.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(pending.scopes),
            "state": state,
            "code_challenge": pkce_challenge(pending.code_verifier),
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "false",
        }
        return f"{self.s.google_auth_url}?{urlencode(params)}"

    # ------------------------------------------------------------------ step 3: callback
    async def handle_callback(self, state: str, code: str) -> CallbackResult:
        self._require_configured()
        user_id, nonce = self.parse_state(state)
        pending = await self.repo.consume_state(user_id, nonce)
        if pending is None:
            raise InvalidState("state unknown, used or expired")
        tok = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.s.google_redirect_uri,
                "code_verifier": pending.code_verifier,
            }
        )
        refresh, access = tok.get("refresh_token"), tok.get("access_token")
        granted = sc.normalise_granted(tok.get("scope"))
        if not access:
            raise GoogleError("no access token returned", code="bad_token_response")
        if not refresh or sc.CALENDAR_EVENTS not in granted:
            # Never keep a half connection: give back whatever Google handed over.
            await self._revoke(refresh or access)
            raise ScopeMissing(
                "calendar access was not granted"
                if refresh
                else "no refresh token returned (consent needed again)",
                code="scope_missing" if refresh else "no_refresh_token",
            )
        info = await self._userinfo(access)
        sub = str(info.get("sub") or "")
        if not sub:
            await self._revoke(refresh)
            raise GoogleError("no account id returned", code="bad_userinfo")
        email = info.get("email") if info.get("email_verified", True) else None
        now = self.clock.now()
        await self.repo.upsert(
            GoogleConnection(
                user_id=user_id,
                google_sub_hmac=self._sub_index(sub),
                email=email,
                scopes=granted,
                status=CONNECTED,
                refresh_token=refresh,
                access_token=access,
                access_expires_at=now + timedelta(seconds=int(tok.get("expires_in", 3600))),
            )
        )
        log.info("google connected user=%s scopes=%d", user_id, len(granted))
        return CallbackResult(user_id, granted, mask_email(email))

    def _sub_index(self, sub: str) -> str:
        key = self.s.derived_key("google_sub_index")
        return hmac.new(key, sub.encode(), hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------ tokens
    async def access_token(self, user_id: str, *, scope: str | None = None) -> str:
        """A valid access token for the user (refreshes early). Raises NotConnected or
        NeedsReconnect; callers treat both as "ask the user to connect again". With ``scope``,
        raises ScopeMissing unless the user granted it."""
        self._require_configured()
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            conn = await self.repo.get(user_id)
            if conn is None:
                raise NotConnected("no Google connection")
            if conn.status != CONNECTED:
                raise NeedsReconnect("reconnect needed")
            if scope is not None and scope not in conn.scopes:
                raise ScopeMissing(f"scope not granted: {scope}")
            margin = timedelta(seconds=self.s.google_token_expiry_margin_s)
            if (
                conn.access_token
                and conn.access_expires_at
                and conn.access_expires_at - margin > self.clock.now()
            ):
                await self.repo.touch(user_id)
                return conn.access_token
            return await self._refresh(conn)

    async def force_refresh(self, user_id: str) -> str:
        """After a 401 from a Google API: refresh regardless of the recorded expiry."""
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            conn = await self.repo.get(user_id)
            if conn is None:
                raise NotConnected("no Google connection")
            if conn.status != CONNECTED:
                raise NeedsReconnect("reconnect needed")
            return await self._refresh(conn)

    async def _refresh(self, conn: GoogleConnection) -> str:
        try:
            tok = await self._token_request(
                {"grant_type": "refresh_token", "refresh_token": conn.refresh_token}
            )
        except GoogleError as e:
            if e.code == "invalid_grant":
                await self.repo.set_status(conn.user_id, NEEDS_RECONNECT)
                log.warning("google needs_reconnect user=%s", conn.user_id)
                raise NeedsReconnect("Google rejected the refresh token") from None
            raise
        access = tok.get("access_token")
        if not access:
            raise GoogleError("no access token returned", code="bad_token_response")
        expires = self.clock.now() + timedelta(seconds=int(tok.get("expires_in", 3600)))
        await self.repo.set_access_token(
            conn.user_id, access, expires, refresh_token=tok.get("refresh_token")
        )
        await self.repo.touch(conn.user_id)
        return access

    async def granted_scopes(self, user_id: str) -> list[str]:
        conn = await self.repo.get(user_id)
        return list(conn.scopes) if conn else []

    # ------------------------------------------------------------------ disconnect / status
    async def disconnect(self, user_id: str) -> DisconnectResult:
        conn = await self.repo.get(user_id)
        revoked = False
        if conn is not None and self.configured:
            revoked = await self._revoke(conn.refresh_token)
        deleted = await self.repo.delete(user_id)  # even when the revoke call failed
        log.info("google disconnected user=%s revoked=%s", user_id, revoked)
        return DisconnectResult(deleted=deleted, revoked=revoked)

    async def status(self, user_id: str) -> ConnectionStatus:
        conn = await self.repo.get(user_id)
        if conn is None:
            return ConnectionStatus(False, "not_connected", [], None, False, False)
        return ConnectionStatus(
            connected=conn.status == CONNECTED,
            status=conn.status,
            scopes=list(conn.scopes),
            email_masked=mask_email(conn.email),
            gmail=sc.GMAIL_READONLY in conn.scopes,
            drive=sc.DRIVE_FILE in conn.scopes,
        )

    # ------------------------------------------------------------------ HTTP to Google
    async def _token_request(self, data: dict[str, str | None]) -> dict:
        body = {
            **{k: v for k, v in data.items() if v is not None},
            "client_id": self.s.google_oauth_client_id or "",
            "client_secret": self.s.google_oauth_client_secret.get_secret_value()  # type: ignore[union-attr]
            if self.s.google_oauth_client_secret
            else "",
        }
        try:
            async with self._http() as client:
                r = await client.post(self.s.google_token_url, data=body)
        except httpx.HTTPError as e:
            raise GoogleError(
                f"token endpoint unreachable ({type(e).__name__})", code="unreachable"
            ) from None
        payload = _json(r)
        if r.status_code != 200:
            err = str(payload.get("error") or f"http_{r.status_code}")
            raise GoogleError(f"token endpoint refused: {err}", code=err[:40])
        return payload

    async def _userinfo(self, access_token: str) -> dict:
        try:
            async with self._http() as client:
                r = await client.get(
                    self.s.google_userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as e:
            raise GoogleError(
                f"userinfo unreachable ({type(e).__name__})", code="unreachable"
            ) from None
        if r.status_code != 200:
            raise GoogleError("userinfo refused", code="bad_userinfo")
        return _json(r)

    async def _revoke(self, token: str) -> bool:
        try:
            async with self._http() as client:
                r = await client.post(self.s.google_revoke_url, data={"token": token})
            return r.status_code == 200
        except httpx.HTTPError:
            log.warning("google revoke call failed (rows are deleted anyway)")
            return False


def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
