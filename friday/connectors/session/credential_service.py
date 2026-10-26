"""The password flow end to end: ask -> one-time page -> vault -> fill inside the worker.

``request_link`` is the only way a password can enter (the user types it on the secure page).
``autofill`` is the only way it leaves: straight into the site's own fields, inside the worker,
on a host the login was saved for. Nothing here returns a password to a caller that could show it
to a model, a log or a chat.
"""

from __future__ import annotations

from collections.abc import Iterable

from friday.connectors.session.audit import AuditLog
from friday.connectors.session.credential_tokens import CredentialTokenRegistry
from friday.connectors.session.credentials import (
    CredentialError,
    CredentialVault,
    SavedLogin,
    host_matches,
    host_of,
    is_blocked,
)
from friday.connectors.session.settings import BrowserSettings


class CredentialService:
    def __init__(self, vault: CredentialVault, tokens: CredentialTokenRegistry,
                 settings: BrowserSettings, audit: AuditLog | None = None,
                 base_url: str = "") -> None:
        self.vault, self.tokens, self.s = vault, tokens, settings
        self.audit = audit or AuditLog()
        self.base_url = base_url.rstrip("/")

    # ---- ask the user to save a login (returns the secure link, never asks in chat)
    def request_link(self, user_id: str, site: str, hosts: Iterable[str]) -> str:
        site = (site or "").strip().lower()
        host_list = tuple(sorted({h.strip().lower() for h in hosts if h.strip()}))
        if not self.s.credentials_allowed(user_id):
            raise CredentialError("saved logins are not switched on for this user")
        if is_blocked(site, host_list):
            self.audit.record("credential_refused", user_id=user_id, site=site, reason="blocked")
            raise CredentialError("this kind of site is never stored")
        if not host_list:
            raise CredentialError("host names are required")
        token = self.tokens.create(user_id, site, host_list)
        self.audit.record("credential_link", user_id=user_id, site=site)
        return f"{self.base_url}/connectors/credentials/{token}"

    # ---- what the user can see and delete
    def saved(self, user_id: str) -> list[SavedLogin]:
        return self.vault.saved_logins(user_id)

    def forget(self, user_id: str, site: str | None = None) -> int:
        self.tokens.revoke_user(user_id)
        if site:
            n = 1 if self.vault.has(user_id, site) else 0
            self.vault.delete(user_id, site)
        else:
            n = self.vault.delete_user(user_id)
        self.audit.record("credential_deleted", user_id=user_id, site=site or "*", count=n)
        return n

    # ---- use (inside the browser worker only)
    async def autofill(self, session, *, username_selector: str, password_selector: str,
                       submit_selector: str | None = None) -> bool:
        """Fill the saved login on the page the session is on. False when nothing is saved, the
        user is not enabled, or the page is on a host the login was not saved for."""
        user_id, site = session.info.user_id, session.info.site
        if not self.s.credentials_allowed(user_id):
            return False
        cred = self.vault.release(user_id, site, current_host=session.current_host())
        if cred is None:
            self.audit.record("credential_not_used", task_id=session.info.task_id,
                              user_id=user_id, site=site, host=host_of(session.current_host()))
            return False
        await session.fill(username_selector, cred.username)
        await session.fill(password_selector, cred.password)
        self.audit.record("credential_autofill", task_id=session.info.task_id,
                          user_id=user_id, site=site, host=host_of(session.current_host()),
                          fields=2)
        del cred
        if submit_selector:
            await session.click(submit_selector)
        return True


__all__ = ["CredentialService", "host_matches"]
