# ruff: noqa: E501
"""The safety policy, in plain code. It runs on EVERY action the model proposes, before the page is touched, and it
cannot be changed by anything the model or a page says: the allow-list, the tool set, the value sources and the permits
live in ``RunState`` / ``RunSpec`` which only the caller and the user's own chat replies can change.

Verdict codes: ok | refused | payment | need_confirm | need_account | left_for_user | need_attest
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from friday.browser_agent import rules
from friday.browser_agent.types import TOOLS, Action, Element, PageSnapshot, RunState
from friday.voice.text import redact_secrets

SEARCHY = re.compile(r"search|query|keyword|find|looking\s+for", re.I)
LONG_DIGITS = re.compile(r"\d{6,}")
FACT_KEY = re.compile(r"^[a-z][a-z0-9_.]{0,48}$")
STANDING_CLASSES = ("job_application_submit",)


@dataclass
class Verdict:
    ok: bool
    code: str = "ok"
    reason: str = ""
    via: str = ""  # permit | standing
    permit_id: str = ""
    label: str = ""

    @classmethod
    def refuse(cls, reason: str, code: str = "refused", label: str = "") -> Verdict:
        return cls(False, code, reason, label=label)


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Policy:
    def __init__(self, state: RunState, domains: list[str], now: datetime) -> None:
        self.state, self.domains, self.now = state, domains, now

    # ------------------------------------------------------------------ navigation
    def check_goto(self, url: str) -> Verdict:
        if rules.payment_url(url):
            return Verdict.refuse("payment address", "payment")
        host = rules.host_of(url)
        if not url.lower().startswith(("http://", "https://")) or not host:
            return Verdict.refuse("not a web address")
        if rules.domain_denied(host):
            return Verdict.refuse("this kind of site is never opened by Friday", "refused")
        if not rules.host_allowed(host, self.domains):
            return Verdict.refuse("site is not on this task's allow-list", "domain")
        return Verdict(True)

    # ------------------------------------------------------------------ value sources
    def check_source(self, src: str, el: Element) -> Verdict:
        """Only these sources exist. A free literal is never allowed except plain search words in a search box."""
        s = (src or "").strip()
        if rules.is_password(el):
            return Verdict(True) if s == "vault:password" else Verdict.refuse("passwords come only from the vault", "refused")
        if s == "vault:password":
            return Verdict.refuse("vault password only goes into a password field")
        if rules.is_otp(el) and el.role != "select":
            return Verdict(True) if s == "otp" else Verdict.refuse("login codes come only from the secure code page")
        if s == "otp":
            return Verdict.refuse("code source only for a code field")
        if rules.is_attestation(el):
            return Verdict(True) if s.startswith("attest:") and FACT_KEY.match(s[7:] or "-") else Verdict.refuse("needs the user's own yes/no", "need_attest")
        if s.startswith("attest:"):
            return Verdict.refuse("attestation source only for a declaration field")
        if s.startswith("fact:"):
            return Verdict(True) if FACT_KEY.match(s[5:]) else Verdict.refuse("bad fact key")
        if s == "vault:username":
            return Verdict(True)
        if s.startswith("text:"):
            lit = s[5:].strip()
            if el.role == "textbox" and (el.type == "search" or SEARCHY.search(rules.own_label(el))) and 0 < len(lit) <= 80 \
                    and "@" not in lit and not LONG_DIGITS.search(lit) and redact_secrets(lit) == lit:
                return Verdict(True)
            return Verdict.refuse("free text is only allowed in a search box; use a stored fact or ask the user")
        return Verdict.refuse("unknown value source")

    # ------------------------------------------------------------------ element actions
    def _find(self, snap: PageSnapshot, target: str | None) -> Element | None:
        return next((e for e in snap.elements if e.id == (target or "")), None)

    def check_action(self, a: Action, snap: PageSnapshot) -> Verdict:
        if a.tool not in TOOLS:
            return Verdict.refuse("no such tool")
        if a.tool == "goto":
            return self.check_goto(a.url or "")
        if a.tool in ("click", "fill", "select", "upload"):
            el = self._find(snap, a.target)
            if el is None:
                return Verdict.refuse("unknown element id; use an id from the latest snapshot", "refused")
            if el.disabled:
                return Verdict.refuse("that element is disabled")
            lab = rules.own_label(el)[:60]
            if rules.is_payment_element(el):
                return Verdict.refuse("payment control", "payment", lab)
            if a.tool == "click":
                if el.role in ("checkbox", "radio"):
                    return Verdict.refuse("set checkboxes and radios with fill and a value_source, not click", "refused", lab)
                return self._check_click(el, snap, lab)
            if rules.is_sensitive_id(el):
                return Verdict.refuse("ID numbers are never typed by Friday", "left_for_user", lab)
            if a.tool == "upload":
                return Verdict(True, label=lab) if el.role == "file" or el.type == "file" else Verdict.refuse("not a file input")
            if el.role == "file":
                return Verdict.refuse("use upload for file inputs", "refused", lab)
            src = a.value_source if a.tool == "fill" else (a.option if (a.option or "").startswith(("fact:", "attest:")) else "fact:__literal_option__")
            if a.tool == "select" and src == "fact:__literal_option__":
                # selecting a visible option of a dropdown/radio by its text is allowed only for NON-personal choices
                return self._check_option(el, a.option or "", lab)
            v = self.check_source(src or "", el)
            v.label = lab
            return v
        return Verdict(True)

    def _check_option(self, el: Element, option: str, lab: str) -> Verdict:
        if rules.is_attestation(el):
            return Verdict.refuse("needs the user's own yes/no", "need_attest", lab)
        if el.options and not any(option.strip().lower() == o.strip().lower() for o in el.options):
            return Verdict.refuse("option is not on the page")
        # choosing a plain option such as a sort order or a filter is fine; personal answers must come from facts
        if el.required and re.search(r"(gender|dob|birth|marital|nationality|religion|caste|disab|salary|ctc|notice|experience|relocat|visa|sponsor)", rules.own_label(el), re.I):
            return Verdict.refuse("personal answer: use a stored fact or ask the user", "refused", lab)
        return Verdict(True, label=lab)

    def _check_click(self, el: Element, snap: PageSnapshot, lab: str) -> Verdict:
        host = rules.host_of(snap.url)
        if rules.is_account_creation(el) and not rules.host_allowed(host, self.state.spec.account_ok_hosts):
            return Verdict.refuse("creating an account needs the user's ok for this site", "need_account", lab)
        if el.role == "link" and el.href_host:
            if rules.domain_denied(el.href_host):
                return Verdict.refuse("link to a site Friday never opens")
        if rules.is_irreversible(el):
            if rules.is_attestation(el):
                return Verdict.refuse("legal text must be confirmed by the user", "need_confirm", lab)
            p = self._permit_for(host)
            if p:
                return Verdict(True, via="permit", permit_id=p, label=lab)
            if (self.state.spec.playbook == "job_apply" and "job_application_submit" in self.state.spec.standing_ok
                    and not self._has_open_attestation(snap)):
                return Verdict(True, via="standing", label=lab)
            return Verdict.refuse("this cannot be undone: ask the user first", "need_confirm", lab)
        return Verdict(True, label=lab)

    def _has_open_attestation(self, snap: PageSnapshot) -> bool:
        """An unchecked legal box on the page: even with a standing opt-in, the user answers those themselves."""
        for e in snap.elements:
            if rules.is_attestation(e) and e.role in ("checkbox", "radio") and not e.checked:
                return True
        return False

    def _permit_for(self, host: str) -> str:
        for p in self.state.permits:
            if parse_iso(p.expires_at) > self.now and (not p.host or p.host == host):
                return p.id
        return ""
