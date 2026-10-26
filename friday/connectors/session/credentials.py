"""Website password vault (founder decision 2026-10-26, docs/CREDENTIAL_VAULT.md).

Rules, each enforced in code and covered by a test:

* One encrypted slot per (user, site): AES-GCM through the field cipher, AAD binds the
  ciphertext to user + site, slot ids are blind indexes (a file listing shows no user or site).
* A password is accepted ONLY through the one-time secure page (``api/connectors_credentials.py``)
  and only with explicit consent. Never through WhatsApp chat, a tool argument or the model.
* ``release`` hands the password to the browser worker only when the page is on a host the user
  saved the login for. The ``Credential`` object cannot be printed, pickled or serialised.
* Banks, UPI / payments, IRCTC and government-ID sites are refused (``is_blocked``): OTP, card,
  UPI PIN and bank logins are never stored.
* Entries expire (default 90 days); ``delete`` / ``delete_user`` remove them for good.
* Plaintext exists only inside ``save``, ``release`` and the browser fill; it is never logged,
  audited, recorded or put in a trace.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from friday.connectors.session.vault import VaultStore
from friday.core.crypto import DecryptionError, FieldCipher

# Refused outright. Matched against the site key AND every host it is saved for.
_BLOCKED_WORDS = (
    "bank", "upi", "paytm", "phonepe", "gpay", "bhim", "npci", "razorpay", "payu", "billdesk",
    "cashfree", "irctc", "uidai", "aadhaar", "digilocker", "incometax", "epfo", "sebi",
    "zerodha", "groww", "upstox", "hdfc", "icici", "sbi", "axis", "kotak", "yesbank", "idfc",
    "bobibanking", "pnb", "canarabank", "visa", "mastercard", "americanexpress", "amex",
    "netbanking", "creditcard", "wallet",
)
MAX_FIELD = 256
MAX_SITE = 64


class CredentialError(ValueError):
    """Refused, with a plain reason (never contains the secret)."""


def is_blocked(site: str, hosts: Iterable[str] = ()) -> bool:
    for name in (site, *hosts):
        low = (name or "").lower()
        if any(w in low for w in _BLOCKED_WORDS):
            return True
    return False


def host_of(url_or_host: str) -> str:
    v = (url_or_host or "").strip().lower()
    return (urlsplit(v).hostname or "") if "://" in v else v.split("/")[0].split(":")[0]


def _host_ok(host: str, patterns: Iterable[str]) -> bool:
    host = host.lower().rstrip(".")
    for p in patterns:
        p = p.lower()
        if p.startswith("*."):
            if host.endswith(p[1:]) and host != p[2:]:
                return True
        elif host == p:
            return True
    return False


@dataclass(frozen=True)
class Credential:
    """The username and password, for the browser worker only. Prints as ``Credential(***)``."""

    username: str = field(repr=False)
    password: str = field(repr=False)

    def __repr__(self) -> str:
        return "Credential(***)"

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError("a Credential cannot be serialised")

    def __format__(self, spec: str) -> str:
        return "Credential(***)"


@dataclass(frozen=True)
class SavedLogin:
    """What the user may be shown about a saved login: never the password."""

    site: str
    username_hint: str  # "ra***"
    hosts: tuple[str, ...]
    saved_at: float


def _hint(username: str) -> str:
    return (username[:2] + "***") if len(username) > 2 else "***"


class CredentialVault:
    def __init__(self, store: VaultStore, cipher: FieldCipher, *, ttl_days: int = 90,
                 clock: Callable[[], float] = time.time) -> None:
        self._store, self._cipher = store, cipher
        self._ttl = ttl_days * 86400.0
        self._clock = clock

    def _slot(self, user_id: str, site: str) -> str:
        return self._cipher.blind_index(f"{user_id}|{site}", label="browser_cred_slot")[:48]

    def _uid(self, user_id: str) -> str:
        return self._cipher.blind_index(user_id, label="browser_cred_user")[:48]

    @staticmethod
    def _aad(user_id: str, site: str) -> str:
        return f"browser_cred:{user_id}:{site}"

    @staticmethod
    def _meta_aad(user_id: str) -> str:
        return f"browser_cred_meta:{user_id}"

    # ------------------------------------------------------------------ write
    def save(self, user_id: str, site: str, username: str, password: str, *,
             hosts: Iterable[str], consent: bool) -> SavedLogin:
        site = (site or "").strip().lower()
        host_list = sorted({host_of(h) for h in hosts if host_of(h) or str(h).startswith("*.")})
        if not consent:
            raise CredentialError("consent is required")
        if not site or len(site) > MAX_SITE or not host_list:
            raise CredentialError("a site and its host names are required")
        if is_blocked(site, host_list):
            raise CredentialError("this kind of site is never stored")
        if not username or not password:
            raise CredentialError("username and password are required")
        if len(username) > MAX_FIELD or len(password) > MAX_FIELD:
            raise CredentialError("value too long")
        now = self._clock()
        body = {"u": username, "p": password, "hosts": host_list, "site": site, "at": now}
        meta = {"site": site, "hint": _hint(username), "hosts": host_list, "at": now}
        self._store.put(self._slot(user_id, site), {
            "ct": self._cipher.encrypt(json.dumps(body), aad=self._aad(user_id, site)),
            "meta": self._cipher.encrypt(json.dumps(meta), aad=self._meta_aad(user_id)),
            "uid": self._uid(user_id), "saved_at": now, "expires_at": now + self._ttl,
        })
        return SavedLogin(site, _hint(username), tuple(host_list), now)

    # ------------------------------------------------------------------ read
    def _open(self, user_id: str, site: str) -> dict[str, Any] | None:
        site = (site or "").strip().lower()
        slot = self._slot(user_id, site)
        rec = self._store.get(slot)
        if rec is None:
            return None
        if self._clock() >= float(rec.get("expires_at", 0)):
            self._store.delete(slot)
            return None
        try:
            return json.loads(self._cipher.decrypt(rec["ct"], aad=self._aad(user_id, site)))
        except (DecryptionError, KeyError, ValueError):
            return None  # tampered or wrong slot: act as "nothing saved"

    def has(self, user_id: str, site: str) -> bool:
        return self._open(user_id, site) is not None

    def release(self, user_id: str, site: str, *, current_host: str) -> Credential | None:
        """The login, but only while the browser is on a host it was saved for."""
        body = self._open(user_id, site)
        if body is None or is_blocked(site, body["hosts"]):
            return None
        if not _host_ok(host_of(current_host), body["hosts"]):
            return None
        return Credential(body["u"], body["p"])

    def saved_logins(self, user_id: str) -> list[SavedLogin]:
        """Site names and a masked username only; the password is never part of this."""
        out = []
        for slot in self._store.slots_for_user(self._uid(user_id)):
            rec = self._store.get(slot)
            if not rec or self._clock() >= float(rec.get("expires_at", 0)):
                continue
            try:
                m = json.loads(self._cipher.decrypt(rec["meta"], aad=self._meta_aad(user_id)))
            except (DecryptionError, KeyError, ValueError):
                continue
            out.append(SavedLogin(m["site"], m["hint"], tuple(m["hosts"]), float(m["at"])))
        return sorted(out, key=lambda x: x.site)

    # ------------------------------------------------------------------ delete
    def delete(self, user_id: str, site: str) -> None:
        self._store.delete(self._slot(user_id, (site or "").strip().lower()))

    def delete_user(self, user_id: str) -> int:
        slots = self._store.slots_for_user(self._uid(user_id))
        for s in slots:
            self._store.delete(s)
        return len(slots)


def host_matches(host: str, patterns: Iterable[str]) -> bool:
    return _host_ok(host_of(host), list(patterns))


__all__ = ["Credential", "CredentialError", "CredentialVault", "SavedLogin", "host_matches",
           "is_blocked", "host_of"]
