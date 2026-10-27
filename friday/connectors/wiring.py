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

from friday.connectors import catalog, login_copy
from friday.connectors.browser.backend import select_backend
from friday.connectors.browser.policy import NetworkPolicy
from friday.connectors.defaults import build_default_registry
from friday.connectors.flow import BrowserFlow, JsonTaskStore, Outgoing, register_browser_handler
from friday.connectors.otp import (
    CHAT_OTP_TTL_SECONDS,
    LOGIN_OTP,
    REFUSALS,
    OneTimeOtpChannel,
    PendingLoginRegistry,
    classify_chat_secret,
)
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
    r"^(?:forget\s+(?:all\s+)?my\s+logins?|delete\s+(?:all\s+)?my\s+logins?|forget\s+(?:all\s+)?logins?|"
    r"mere\s+logins?\s+(?:bhool\s+jao|delete\s+karo|mita\s+do)|logins?\s+(?:bhool\s+jao|delete\s+karo))$",
    re.IGNORECASE)
# "forget zomato", "forget my zomato login", "zomato login bhool jao"
FORGET_SITE = re.compile(
    r"^(?:(?:forget|delete|remove)\s+(?:my\s+)?(?P<a>[a-z0-9.]+?)(?:\s+login)?|"
    r"(?:mera\s+)?(?P<b>[a-z0-9.]+)\s+login\s+(?:bhool\s+jao|delete\s+karo|mita\s+do))$",
    re.IGNORECASE)
YES = re.compile(r"^(?:y|yes|yep|yeah|ok|okay|confirm|haan|han|ha|haa|ji\s*haan|theek\s*hai|kar\s*do|delete)$",
                 re.IGNORECASE)
NO = re.compile(r"^(?:n|no|nope|cancel|nahi|nahin|na|mat|rehne\s*do|stop|keep)$", re.IGNORECASE)
FORGET_CONFIRM_TTL_SECONDS = 120.0
BTN_YES, BTN_NO = "lg:yes", "lg:no"


def _line(key: str, lang: str, **kw: object) -> str:
    return login_copy.line(key, lang, **kw)


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
        # the vault object always exists so "forget" / "delete everything" can remove logins that
        # were saved while the switch was on; the SERVICE (links, autofill) only when it is on
        self.cred_vault = CredentialVault(FileVaultStore(s.credentials_dir), cipher,
                                          ttl_days=s.credentials_ttl_days)
        self.credentials: CredentialService | None = None
        if s.credentials_enabled:
            self.credentials = CredentialService(
                self.cred_vault, self.cred_tokens, s, self.audit, self.base_url)
        # a login code typed in chat: only while Friday itself started that login (default OFF)
        self.pending_logins: PendingLoginRegistry | None = (
            PendingLoginRegistry(ttl_seconds=s.login_otp_chat_ttl_seconds or CHAT_OTP_TTL_SECONDS)
            if s.login_otp_in_chat else None)
        self.log_redacted: Any = None  # async (user, msg): the pipeline stores the redacted row
        self._forget_asks: dict[str, tuple[str | None, float]] = {}  # user -> (site|None, expires)
        self._clock = time.monotonic
        self.live = LiveViewService(self.manager)
        self.live_http = LiveViewHttp(self.live)
        self.qr = QrStore()
        self.watcher = PauseWatcher(self.manager, pause_probe(core))
        self.manager.on_close(self.otp_tokens.revoke_task)
        if self.pending_logins is not None:
            self.manager.on_close(self.pending_logins.clear_task)
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
            takeover_link=self._takeover_link, pending_logins=self.pending_logins)

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
        if msg.kind == MessageKind.BUTTON_REPLY:
            bid = msg.button_id or ""
            if bid.startswith("bf:"):
                return await self.flow.handle_button(user.id, bid)
            if bid in (BTN_YES, BTN_NO):
                return await self._forget_answer(user, bid == BTN_YES, await self._lang(user))
        if msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE):
            return False
        text = (msg.text or "").strip()
        if not text:
            return False
        lang = await self._lang(user)
        if self._forget_open(user.id):  # a "delete them?" question is waiting for yes / no
            if YES.match(text):
                return await self._forget_answer(user, True, lang)
            if NO.match(text):
                return await self._forget_answer(user, False, lang)
            self._forget_asks.pop(user.id, None)  # anything else drops the question
        if MY_LOGINS.match(text) or FORGET_LOGINS.match(text) or SAVE_LOGIN.match(text):
            return await self._logins(user, text, lang)
        if await self._maybe_forget_site(user, text, lang):
            return True
        if not self.flow.matches(text) and not self.flow.has_active_task(user.id):
            return False
        await self.remember_profile(user)
        return await self.flow.handle_text(user.id, text, lang)

    # ---- a login code typed in the chat (founder decision 2026-10-27; default OFF)
    def chat_secret_candidate(self, text: str | None) -> bool:
        """Cheap check for the pipeline (no user needed): could this message be a login code or a
        secret we must refuse? Used to skip the user lookup for ordinary messages."""
        s = self.settings
        if not (s.enabled and s.login_otp_in_chat and text):
            return False
        return classify_chat_secret(text, login_site="").kind != "none"

    async def intercept_chat_secret(self, user: User, msg: InboundMessage) -> bool:
        """True when the message was a login code or a refused secret: it never goes on to the
        LLM or any other handler, the stored chat text is redacted at once, nothing is logged."""
        s = self.settings
        if (self.pending_logins is None or not (s.enabled and s.login_otp_in_chat)
                or not self.user_allowed(user)
                or msg.kind not in (MessageKind.TEXT, MessageKind.VOICE_NOTE) or not msg.text):
            return False
        pend = self.pending_logins.peek(user.id)
        verdict = classify_chat_secret(msg.text, login_site=pend.site if pend else None)
        if verdict.kind == "none":
            return False  # an unsolicited number is just a message
        lang = await self._lang(user)
        if self.log_redacted is not None:
            await self.log_redacted(user, msg)  # the row keeps "[redacted]", never the text
        msg.text = None
        if verdict.kind == LOGIN_OTP and pend is not None:
            self.pending_logins.consume(user.id)  # single use
            try:
                self.otp.submit(pend.task_id, verdict.code)  # straight to the browser worker
            except ValueError:
                return True
            self.audit.record("login_code_chat", user_id=user.id, site=pend.site)
            await self.notifier.notify_user(user.id, _line("code_taken", lang))
            return True
        if verdict.kind in REFUSALS:
            self.audit.record("chat_secret_refused", user_id=user.id, kind=verdict.kind)
            await self.notifier.notify_user(
                user.id, _line(login_copy.REFUSAL_LINE[verdict.kind], lang))
        return True

    # ---- login commands
    def _forget_open(self, user_id: str) -> bool:
        ask = self._forget_asks.get(user_id)
        if ask is None:
            return False
        if self._clock() >= ask[1]:
            self._forget_asks.pop(user_id, None)
            return False
        return True

    def _ask_forget(self, user_id: str, site: str | None) -> None:
        self._forget_asks[user_id] = (site, self._clock() + FORGET_CONFIRM_TTL_SECONDS)

    async def _confirm(self, user: User, text: str, lang: str) -> None:
        await self.notifier.notify_user(
            user.id, text, buttons=[ReplyButton(id=BTN_YES, title=_line("btn_forget_yes", lang)[:20]),
                                    ReplyButton(id=BTN_NO, title=_line("btn_forget_no", lang)[:20])])

    async def _forget_answer(self, user: User, yes: bool, lang: str) -> bool:
        ask = self._forget_asks.pop(user.id, None)
        if ask is None or self._clock() >= ask[1]:
            return True  # a stale button: swallowed, nothing deleted
        site = ask[0]
        if not yes:
            await self.notifier.notify_user(user.id, _line("forget_cancelled", lang))
        elif site:
            self.cred_tokens.revoke_user(user.id)
            self.cred_vault.delete(user.id, site)
            self.vault.disconnect(user.id, site)
            self.audit.record("credential_deleted", user_id=user.id, site=site, count=1)
            await self.notifier.notify_user(user.id, _line("forgotten_site", lang, site=site))
        else:
            n = await self.forget_user(user.id)
            await self.notifier.notify_user(user.id, _line("forgotten", lang, n=n))
        return True

    _NOT_SITES = frozenset({"everything", "all", "logins", "login", "my", "it", "this", "that", "me",
                            "password", "passwords", "history", "chat", "chats", "data", "number",
                            "contacts", "reminders", "memory", "memories"})

    async def _maybe_forget_site(self, user: User, text: str, lang: str) -> bool:
        m = FORGET_SITE.match(text)
        if m is None or not self.settings.credentials_allowed(user.id):
            return False
        name = (m.group("a") or m.group("b") or "").lower()
        if not name or name in self._NOT_SITES:
            return False
        spec = catalog.site(name)
        key = spec.key if spec is not None else name
        saved = {x.site for x in self.cred_vault.saved_logins(user.id)}
        if key not in saved and name not in saved:
            if spec is None:
                return False  # "forget it": not for us
            await self.notifier.notify_user(user.id, _line("forget_none", lang, site=spec.name))
            return True
        site = key if key in saved else name
        self._ask_forget(user.id, site)
        await self._confirm(user, _line("confirm_site", lang, site=site), lang)
        return True

    async def _logins(self, user: User, text: str, lang: str) -> bool:
        allowed = self.credentials is not None and self.settings.credentials_allowed(user.id)
        saved = self.cred_vault.saved_logins(user.id)
        if m := SAVE_LOGIN.match(text):
            if not allowed:
                await self.notifier.notify_user(user.id, _line("off", lang))
                return True
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
        if not allowed and not saved:
            await self.notifier.notify_user(user.id, _line("off", lang))
            return True
        if FORGET_LOGINS.match(text):  # with a yes / no question first
            if not saved:
                await self.forget_user(user.id)  # saved browser sessions only: nothing to ask
                await self.notifier.notify_user(user.id, _line("none", lang))
                return True
            self._ask_forget(user.id, None)
            await self._confirm(user, _line("confirm_all", lang, n=len(saved)), lang)
            return True
        if not saved:
            await self.notifier.notify_user(user.id, _line("none", lang))
        else:
            sites = ", ".join(f"{x.site} ({x.username_hint})" for x in saved)
            await self.notifier.notify_user(user.id, _line("list", lang, sites=sites))
        return True

    # ---- "delete everything" and "forget my logins"
    async def forget_user(self, user_id: str) -> int:
        """Delete saved logins (even when the switch was turned off since), the saved browser
        sessions, open links, a pending login code and any live session of this user."""
        self.cred_tokens.revoke_user(user_id)
        n = self.credentials.forget(user_id) if self.credentials is not None \
            else self.cred_vault.delete_user(user_id)
        self.vault.disconnect_user(user_id)
        if self.pending_logins is not None:
            task = self.pending_logins.consume(user_id)
            if task is not None:
                self.otp.wipe(task.task_id)
        self._forget_asks.pop(user_id, None)
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
