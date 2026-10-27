# ruff: noqa: E501
"""Wiring of the private browser into Friday (default OFF).

``build_browser_stack`` is called by the inbound pipeline ONLY when ``FRIDAY_BROWSER_ENABLED`` is
true. It builds, and owns, everything the browser needs: the session manager (+ backend, vault,
durable audit), the secure one-time pages (login code, saved logins, payment QR), the live view,
the credential service, the pause watcher and the ``BrowserFlow`` registered as the chatbot's
browser handler. Nothing here talks to a real site by itself: a site is automated only when
``catalog.effective_mode`` says so (adapter + cleared + enabled + supervised), else the user gets
the link.

Who sees what: the flow's ``Outgoing`` messages go out through the notifier; the user's login phone
lives only in an in-memory profile cache (never in task state, never logged); logins ("my logins",
"forget my logins") show site names and a masked hint, never a password.
"""

from __future__ import annotations

import re
import secrets
import time
from typing import TYPE_CHECKING, Any

from friday.connectors import catalog
from friday.connectors.browser.backend import select_backend
from friday.connectors.browser.policy import NetworkPolicy
from friday.connectors.defaults import build_default_registry
from friday.connectors.flow import BrowserFlow, JsonTaskStore, Outgoing, register_browser_handler
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.otp_tokens import OtpTokenRegistry
from friday.connectors.session import (
    AuditLog,
    CredentialError,
    CredentialService,
    CredentialTokenRegistry,
    CredentialVault,
    FileVaultStore,
    JsonlAuditSink,
    LiveViewHttp,
    LiveViewService,
    PauseWatcher,
    SessionManager,
    StorageVault,
    cipher_from_settings,
    pause_probe,
)
from friday.connectors.session.settings import BrowserSettings
from friday.connectors.sites.adapters import Profile
from friday.core.logging import get_logger
from friday.core.models import InboundMessage, MessageKind, ReplyButton, User

if TYPE_CHECKING:
    from friday.core.container import Container

log = get_logger(__name__)

QR_TTL_SECONDS = 900.0
QR_MAX = 50
MY_LOGINS = re.compile(
    r"^(?:my\s+logins?|saved\s+logins?|show\s+(?:my\s+)?(?:saved\s+)?logins?|"
    r"mere\s+logins?(?:\s+dikhao)?|saved\s+logins?\s+dikhao)$", re.IGNORECASE)
SAVE_LOGIN = re.compile(r"^(?:save|add|store)\s+(?:my\s+)?(?P<site>[a-z0-9.]+)\s+login$", re.IGNORECASE)
FORGET_LOGINS = re.compile(
    r"^(?:forget\s+(?:all\s+)?my\s+logins?|delete\s+(?:all\s+)?my\s+logins?|forget\s+logins?|"
    r"mere\s+logins?\s+(?:bhool\s+jao|delete\s+karo|mita\s+do)|logins?\s+(?:bhool\s+jao|delete\s+karo))$",
    re.IGNORECASE)

# PENDING founder approval (hear before change): every new user-facing line of this module
LOGIN_LINES = {
    "none": {"en": "I have no saved logins for you.",
             "hi": "Aapke koi saved login mere paas nahi hain."},
    "list": {"en": "Saved logins (passwords are never shown): {sites}. Say \"forget my logins\" to delete them all.",
             "hi": "Saved logins (password kabhi nahi dikhate): {sites}. Sab hatane ke liye \"forget my logins\" likhiye."},
    "forgotten": {"en": "Done. I deleted {n} saved login(s) and your saved browser sessions.",
                  "hi": "Ho gaya. Maine {n} saved login aur aapke saved browser sessions hata diye."},
    "off": {"en": "Saved logins are not switched on.", "hi": "Saved logins abhi chalu nahi hain."},
    "link": {"en": "Open this private page to save your {site} login. Never type it in chat: {link}",
             "hi": "Apna {site} login save karne ke liye yeh private page kholiye. Chat mein kabhi mat likhiye: {link}"},
    "refused": {"en": "I can't save that kind of login.", "hi": "Is tarah ka login main save nahi kar sakti."},
    "unknown_site": {"en": "I don't know that site.", "hi": "Yeh site main nahi jaanti."},
}


def _line(key: str, lang: str, **kw: object) -> str:
    return LOGIN_LINES[key].get(lang, LOGIN_LINES[key]["en"]).format(**kw)


class QrStore:
    """Short-lived, in-memory PNGs for the payment QR page. The token is the only credential."""

    def __init__(self, clock: Any = time.time, ttl: float = QR_TTL_SECONDS) -> None:
        self._clock, self._ttl = clock, ttl
        self._d: dict[str, tuple[bytes, float]] = {}

    def put(self, png: bytes) -> str:
        now = self._clock()
        for t in [t for t, (_, exp) in self._d.items() if exp <= now]:
            self._d.pop(t, None)
        while len(self._d) >= QR_MAX:
            self._d.pop(next(iter(self._d)))
        token = secrets.token_urlsafe(24)
        self._d[token] = (png, now + self._ttl)
        return token

    def get(self, token: str) -> bytes | None:
        item = self._d.get(token)
        if item is None or item[1] <= self._clock():
            self._d.pop(token, None)
            return None
        return item[0]


class ManagerSessionProvider:
    """Adapts ``SessionManager`` to ``flow.SessionProvider``: one isolated session per task, the
    network allow-list is the catalog's host list for that site (default deny)."""

    def __init__(self, manager: SessionManager) -> None:
        self.mgr = manager

    async def open(self, user_id: str, task_id: str, site: str) -> Any:
        policy = NetworkPolicy.for_hosts(sorted(catalog.policy_hosts(site)))
        return await self.mgr.open(user_id, site, task_id, policy=policy)

    async def close(self, task_id: str) -> None:
        await self.mgr.close(task_id)


class BrowserStack:
    def __init__(self, core: Any, notifier: Any, repos: Any, *, backend: Any = None,
                 registry: Any = None, settings: BrowserSettings | None = None,
                 audit: AuditLog | None = None, base_url: str | None = None) -> None:
        self.core, self.notifier, self.repos = core, notifier, repos
        self.settings = settings or BrowserSettings.from_core(core)
        s = self.settings
        self.base_url = (base_url or core.public_base_url).rstrip("/")
        self.audit = audit or AuditLog(sink=JsonlAuditSink(s.audit_file))
        cipher = cipher_from_settings(core)
        self.vault = StorageVault(FileVaultStore(s.vault_dir), cipher, ttl_days=s.vault_ttl_days,
                                  audit=self.audit)
        backend = backend or select_backend(
            s.backend, provider=s.cloud_provider, headed=s.headed, display=s.display,
            resolve_dns=s.resolve_dns)
        self.manager = SessionManager(backend, self.vault, s, audit=self.audit,
                                      paused=pause_probe(core))
        self.registry = registry or build_default_registry()
        self.otp = OneTimeOtpChannel()
        self.otp_tokens = OtpTokenRegistry()
        self.cred_tokens = CredentialTokenRegistry(ttl_seconds=s.credentials_link_ttl_seconds)
        self.credentials: CredentialService | None = None
        if s.credentials_enabled:
            self.credentials = CredentialService(
                CredentialVault(FileVaultStore(s.credentials_dir), cipher,
                                ttl_days=s.credentials_ttl_days),
                self.cred_tokens, s, self.audit, self.base_url)
        self.live = LiveViewService(self.manager)
        self.live_http = LiveViewHttp(self.live)
        self.qr = QrStore()
        self.watcher = PauseWatcher(self.manager, pause_probe(core))
        self.manager.on_close(self.otp_tokens.revoke_task)
        self._profiles: dict[str, Profile] = {}
        try:  # the ride-start code page lives on this server
            from friday.connectors.sites.ride import base as _ride

            _ride.LINK_BASE = f"{self.base_url}/ride/code"
        except ImportError:
            pass
        self.flow = BrowserFlow(
            send=self._send, registry=self.registry, sessions=ManagerSessionProvider(self.manager),
            otp=self.otp, profile=lambda uid: self._profiles.get(uid) or Profile(),
            login_link=self._login_link, base_urls={}, store=JsonTaskStore(_task_file(s)),
            enabled=lambda: s.enabled, mode_of=s.site_mode, credentials=self.credentials,
            takeover_link=self._takeover_link)

    # ---- lifecycle
    def register(self) -> None:
        register_browser_handler(self.flow)

    def start(self) -> None:
        self.register()
        self.watcher.start()

    async def stop(self) -> None:
        await self.watcher.stop()
        await self.manager.kill_all("shutdown")
        register_browser_handler(None)

    # ---- pieces the flow needs
    def _login_link(self, task_id: str) -> str:
        return f"{self.base_url}/connectors/otp/{self.otp_tokens.create(task_id)}"

    def _takeover_link(self, task_id: str) -> str:
        """Live view + takeover link for this task (the user logs in on the site's own page)."""
        try:
            return f"{self.base_url}/live/{self.live.create_link(task_id)}"
        except Exception:  # noqa: BLE001 - no live session: fall back to the one-time code page
            return self._login_link(task_id)

    async def _send(self, out: Outgoing) -> None:
        text = out.text
        media = None
        if out.image_png:
            media = f"{self.base_url}/connectors/qr/{self.qr.put(out.image_png)}.png"
        buttons = [ReplyButton(id=i, title=t[:20]) for i, t in out.buttons[:3]]
        await self.notifier.notify_user(
            out.user_id, text, buttons=buttons, media_url=media,
            media_mime="image/png" if media else None)

    async def remember_profile(self, user: User) -> Profile:
        """Refresh the in-memory profile the flow reads (address from the saved Home place, city
        as the area, the login phone). Nothing is persisted here."""
        address = area = ""
        try:
            places = await self.repos.places.list_for_owner(user.id)
            home = next((p for p in places if p.label.lower() in {"home", "ghar"}), None)
            if home is not None:
                address = home.formatted_address or home.address_text or ""
                area = home.city or ""
            if not area:
                area = (await self.repos.profiles.get_or_default(user.id)).city or ""
        except Exception:  # noqa: BLE001 - a missing profile just means the flow asks
            log.warning("browser profile lookup failed")
        prof = Profile(address=address, area=area, phone=re.sub(r"\D", "", user.phone)[-10:])
        self._profiles[user.id] = prof
        return prof

    def user_allowed(self, user: User) -> bool:
        return self.settings.user_allowed(user.id) or self.settings.user_allowed(user.phone)

    async def _lang(self, user: User) -> str:
        try:
            code = (await self.repos.profiles.get_or_default(user.id)).language
        except Exception:  # noqa: BLE001
            return "en"
        return "en" if getattr(code, "value", str(code)) == "en" else "hi"

    # ---- the inbound hook (pipeline calls this for every message of an active user)
    async def handle(self, user: User, msg: InboundMessage) -> bool:
        """True when the browser flow (or a login command) consumed the message."""
        if not self.settings.enabled or not self.user_allowed(user):
            return False
        if msg.kind == MessageKind.BUTTON_REPLY and (msg.button_id or "").startswith("bf:"):
            return await self.flow.handle_button(user.id, msg.button_id or "")
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE):
            return False
        text = (msg.text or "").strip()
        if not text:
            return False
        lang = await self._lang(user)
        if MY_LOGINS.match(text) or FORGET_LOGINS.match(text) or SAVE_LOGIN.match(text):
            return await self._logins(user, text, lang)
        if not self.flow.matches(text) and not self.flow.has_active_task(user.id):
            return False
        await self.remember_profile(user)
        return await self.flow.handle_text(user.id, text, lang)

    async def _logins(self, user: User, text: str, lang: str) -> bool:
        if self.credentials is None or not self.settings.credentials_allowed(user.id):
            await self.notifier.notify_user(user.id, _line("off", lang))
            return True
        if m := SAVE_LOGIN.match(text):
            spec = catalog.site(m.group("site"))
            if spec is None:
                await self.notifier.notify_user(user.id, _line("unknown_site", lang))
                return True
            try:
                link = self.credentials.request_link(user.id, spec.key, spec.hosts)
            except CredentialError:
                await self.notifier.notify_user(user.id, _line("refused", lang))
                return True
            await self.notifier.notify_user(user.id, _line("link", lang, site=spec.name, link=link))
            return True
        if FORGET_LOGINS.match(text):
            n = await self.forget_user(user.id)
            await self.notifier.notify_user(user.id, _line("forgotten", lang, n=n))
            return True
        saved = self.credentials.saved(user.id)
        if not saved:
            await self.notifier.notify_user(user.id, _line("none", lang))
        else:
            sites = ", ".join(f"{x.site} ({x.username_hint})" for x in saved)
            await self.notifier.notify_user(user.id, _line("list", lang, sites=sites))
        return True

    # ---- "delete everything" and "forget my logins"
    async def forget_user(self, user_id: str) -> int:
        """Delete saved logins, the saved browser sessions and any live session of this user."""
        n = self.credentials.forget(user_id) if self.credentials is not None else 0
        self.vault.disconnect_user(user_id)
        await self.manager.kill_user(user_id, "forget")
        self._profiles.pop(user_id, None)
        return n


def _task_file(s: BrowserSettings) -> Any:
    from pathlib import Path

    p = Path(s.vault_dir).parent / "browser_tasks.json"
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def build_browser_stack(c: Container, *, backend: Any = None) -> BrowserStack | None:
    """The stack for this process, or None while ``FRIDAY_BROWSER_ENABLED`` is off."""
    if not getattr(c.settings, "browser_enabled", False):
        return None
    messaging_notifier = c.notifier
    return BrowserStack(c.settings, messaging_notifier, c.repos, backend=backend)
