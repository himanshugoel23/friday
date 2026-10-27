# ruff: noqa: E501
"""Category simulator: the real ``BrowserFlow`` + planner + adapters against every category package's
FAKE sites (``FAKE_SITES``), one case per site, three modes each:

* ``happy``       request -> clarifying questions -> approval -> login code -> payment QR / ride booked
* ``price_rise``  the price goes up after approval: Friday asks AGAIN with the exact total, then goes on
* ``cancel``      the user says no at the approval card: nothing is bought, nothing is paid

Used by ``friday browser-sim`` and by tests/integration_browser. No network, no real site, no money.
Every value here is invented; the "login code" is the fake sites' own test code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from friday.connectors import catalog
from friday.connectors.flow import BrowserFlow, Outgoing, TaskState
from friday.connectors.otp import OneTimeOtpChannel
from friday.connectors.registry import BackendKind, ConnectorRegistry, Registration, Status
from friday.connectors.sites import categories
from friday.connectors.sites.adapters import Profile
from friday.connectors.sites.locator import FakeRepairer

USER = "u-sim"
MODES_ALL = ("happy", "price_rise", "cancel")
MODES = MODES_ALL
PROFILE = Profile(address="Flat 4, Sector 12", area="Sector 12", phone="9000000001")


@dataclass
class Case:
    key: str
    request: str
    answers: dict[str, str] = field(default_factory=dict)  # pending slot -> the user's reply
    otp: str | None = None  # the fake site's own test login code (None: the fake needs no login)
    rise: dict[str, Any] = field(default_factory=lambda: {"price_bump_pct": 60})
    knobs: dict[str, Any] = field(default_factory=dict)
    ends_without_payment: bool = False  # a ride: no QR, the outcome is "booked"
    modes: tuple[str, ...] = MODES_ALL  # read-only cases (eRail) have nothing to approve

    @property
    def name(self) -> str:
        return self.key


def _otp_for(use_case: str, site: str) -> str | None:
    """The fake sites' own test login codes (invented; each fake accepts only its own)."""
    if use_case == "grocery" or use_case == "ride":
        return None  # their fakes start logged in
    if use_case in {"hotel", "flight", "bus"}:
        from friday.connectors.sites.fakes import stay_site

        return stay_site.OTP
    if use_case in {"train", "train_info"}:
        if site == "erail":
            return None  # information only: no login
        from friday.connectors.sites.fakes import train_site

        return train_site.OTP
    if use_case == "shopping":
        from friday.connectors.sites.fakes import shopping_site

        return shopping_site.OTP
    return "246810"  # food (swiggy): the fake food site's code


NAME = {k: s.name for k, s in ((s.key, s) for s in catalog.SITES)}
# per use case: request template ({site} = the site's name) + the answers to the follow-up questions
_TEMPLATES: dict[str, dict[str, Any]] = {
    "grocery": {"request": "{site} se 5 butter mangao", "answers": {}},
    "ride": {"request": "{site} auto Sector 12 se City Station", "answers": {},
             "rise": {"fare_bump_pct": 30}, "ends_without_payment": True},
    "hotel": {"request": "{site} hotel in Jaipur 10 nov for 2 nights",
              "answers": {"guest_name": "Asha Rao"}},
    "flight": {"request": "{site} Delhi to Mumbai flight 10 nov",
               "answers": {"passengers": "Asha Rao and Ravi Rao"}},
    "train": {"request": "{site} NDLS se BCT train 8 nov",
              "answers": {"cls": "3A", "quota": "general", "train": "12951",
                          "passengers": "Asha Verma 34 female lower; Ravi Verma 36 male upper"}},
    "train_info": {"request": "{site} NDLS se BCT train 8 nov", "answers": {}, "modes": ("happy",),
                   "ends_without_payment": True},
    "shopping": {"request": "{site} se buds kharidna", "answers": {"pick": "1", "variant": "black"}},
    "food": {"request": "{site} se order 2 chicken biryani from Behrouz", "answers": {}},
    "bus": {"request": "{site} Bengaluru se Hyderabad bus 10 nov",
            "answers": {"passengers": "Asha Rao and Ravi Rao", "boarding": "Silk Board",
                        "dropping": "Miyapur"}},
}


def cases() -> dict[str, Case]:
    """One case per adapter that has a fake site."""
    out: dict[str, Case] = {}
    fakes = categories.all_fake_sites()
    for key in sorted(fakes):
        site, use_case = key.split(".", 1)
        t = _TEMPLATES.get(use_case)
        spec = catalog.site(site)
        if t is None or spec is None or (use_case == "food" and site != "swiggy"):
            continue
        out[key] = Case(
            key, t["request"].format(site=site.title()), dict(t["answers"]), _otp_for(use_case, site),
            dict(t.get("rise", {"price_bump_pct": 60})), dict(t.get("knobs", {})),
            bool(t.get("ends_without_payment")), t.get("modes", MODES_ALL))
    return out


def fake_session(key: str, **knobs: Any) -> Any:
    """A browser session on the fake site (some packages hand back a site object with ``.session()``)."""
    obj = categories.all_fake_sites()[key](**knobs)
    if hasattr(obj, "goto"):
        return obj
    return obj.new_session() if hasattr(obj, "new_session") else obj.session()


class Provider:
    def __init__(self, make: Callable[[str], Any]) -> None:
        self._make, self.opened, self.closed, self.sessions = make, [], [], []

    async def open(self, user_id: str, task_id: str, site: str) -> Any:
        s = self._make(site)
        self.sessions.append(s)
        self.opened.append(task_id)
        return s

    async def close(self, task_id: str) -> None:
        self.closed.append(task_id)


def make_registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    for key in categories.all_adapters():
        site, use_case = key.split(".", 1)
        spec = catalog.site(site)
        reg.register(Registration(site, use_case, BackendKind.scripted_browser, Status.live, "sim"))
        reg.register(Registration(site, use_case, BackendKind.deep_link, Status.live, "sim",
                                  fallback_url=spec.home if spec else ""))
    return reg


@dataclass
class CatResult:
    case: Case
    mode: str
    messages: list[Outgoing]
    task: TaskState | None
    flow: BrowserFlow
    provider: Provider
    lang: str = "en"

    @property
    def kinds(self) -> list[str]:
        return [m.kind for m in self.messages]

    @property
    def cards(self) -> list[Outgoing]:
        return [m for m in self.messages if m.kind == "approval"]

    @property
    def phase(self) -> str:
        return self.task.phase.value if self.task else "-"

    def ok(self) -> bool:
        return not self.problems()

    def problems(self) -> list[str]:
        """What is wrong with this run (empty list = as expected)."""
        bad: list[str] = []
        c, kinds, phase = self.case, self.kinds, self.phase
        if self.mode not in c.modes:
            return [f"mode {self.mode} does not apply"]
        if not kinds or kinds[0] != "ack" or kinds.count("ack") != 1:
            bad.append("expected exactly one ack first")
        if self.mode == "cancel":
            if phase != "cancelled" or "payment" in kinds:
                bad.append(f"cancel: phase={phase}")
        elif self.mode == "price_rise":
            if len(self.cards) < 2 or "approved up to" not in self.cards[1].text.replace("ne", "ne"):
                bad.append("price_rise: no second approval card with the exact total")
            if phase != "done":
                bad.append(f"price_rise: phase={phase}")
        else:
            if phase != "done":
                bad.append(f"happy: phase={phase}")
        if self.mode != "cancel" and not c.ends_without_payment and "payment" not in kinds:
            bad.append("no payment message")
        if c.ends_without_payment and "payment" in kinds:
            bad.append("a ride must not have a payment phase")
        blob = " ".join(m.text for m in self.messages)
        if c.otp and c.otp in blob:
            bad.append("login code leaked into chat")
        return bad


def _credentials() -> Any:
    """A credential service holding the fake IRCTC login (invented user and password)."""
    import os

    from friday.connectors.session import (
        AuditLog,
        CredentialService,
        CredentialTokenRegistry,
        CredentialVault,
        InMemoryVaultStore,
    )
    from friday.connectors.session.settings import BrowserSettings
    from friday.connectors.sites.fakes.train_site import FAKE_PW, FAKE_USER
    from friday.core.crypto import FieldCipher, LocalKeyProvider

    cipher = FieldCipher(LocalKeyProvider({"k1": os.urandom(32)}, index_key=os.urandom(32)))
    vault = CredentialVault(InMemoryVaultStore(), cipher)
    vault.save(USER, "irctc", FAKE_USER, FAKE_PW, hosts=["fake.invalid"], consent=True)
    s = BrowserSettings(enabled=True, enabled_users="*", backend="fake", credentials_enabled=True,
                        credentials_enabled_users="*")
    return CredentialService(vault, CredentialTokenRegistry(), s, AuditLog())


async def run_case(case: Case, mode: str = "happy", lang: str = "en", *,
                   flow_hook: Callable[[BrowserFlow], None] | None = None) -> CatResult:
    knobs = {**case.knobs, **(case.rise if mode == "price_rise" else {})}
    if case.key == "swiggy.food":
        knobs.setdefault("otp", "246810")
    site, use_case = case.key.split(".", 1)
    otp, msgs = OneTimeOtpChannel(), []
    task_ref: dict[str, str] = {}
    provider = Provider(lambda _s: fake_session(case.key, **knobs))
    # fakes that need login read the code from the channel: the "user" types it on the secure page
    code = case.otp

    async def send(m: Outgoing) -> None:
        msgs.append(m)
        if m.kind == "login" and code and "code" in m.text.lower() and task_ref:
            otp.submit(task_ref["id"], code)

    async def noop(_: float) -> None:
        await asyncio.sleep(0)

    adapters = categories.all_adapters()
    creds = _credentials() if site == "irctc" else None
    flow = BrowserFlow(
        send=send, registry=make_registry(), sessions=provider, otp=otp, profile=lambda _u: PROFILE,
        login_link=lambda t: f"https://friday.invalid/otp/{t}", adapters=adapters,
        base_urls={k: "http://fake.invalid" for k in adapters}, repairer=FakeRepairer({}),
        enabled=lambda: True, mode_of=lambda _s: "scripted", otp_wait_s=0.05, poll_s=0.0, sleep=noop,
        credentials=creds)
    if flow_hook:
        flow_hook(flow)
    await flow.handle_text(USER, case.request, lang)
    approvals = [True, True] if mode == "price_rise" else ([False] if mode == "cancel" else [True])
    answers, seen = dict(case.answers), 0
    for _ in range(60):
        st = flow._store.active(USER)  # noqa: SLF001
        if st:
            task_ref["id"] = st.task_id
        await flow.idle()
        st = flow._store.active(USER)  # noqa: SLF001
        if st:
            task_ref["id"] = st.task_id
        fresh, seen = msgs[seen:], len(msgs)
        if not fresh:
            break
        m = fresh[-1]
        if m.kind == "question" and st and st.pending_slot in answers:
            await flow.handle_text(USER, answers.pop(st.pending_slot), lang)
        elif m.kind == "approval" and st and st.notes.get("await_phrase"):
            break  # waiting for the exact extra-approval phrase: the caller decides what to type
        elif m.kind == "approval" and st:
            yes = approvals.pop(0) if approvals else False
            await flow.handle_button(USER, f"bf:{'yes' if yes else 'no'}:{st.task_id}")
        elif m.kind == "payment" and st:
            await flow.handle_button(USER, f"bf:paid:{st.task_id}")
        elif m.kind == "login":
            if not code:
                break
        elif len(msgs) == seen:
            break
    await flow.idle()
    task = None
    for t in flow._store._d.values():  # noqa: SLF001
        task = t
    return CatResult(case, mode, msgs, task, flow, provider, lang)
