# ruff: noqa: E501
"""Fakes for the step runner tests: a scripted fake grocery site (no network, no Chromium), a scripted model, fake OTP channel,
fake saved places. The browser loop is the REAL BrowserAgent (policy layer included) over the fake pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from friday.browser_agent.stores import MemoryRunStore
from friday.shopping import places
from friday.shopping.agent import ShoppingAgent
from friday.steps.planner import StepPlanner
from friday.steps.runner import StepRunner
from friday.steps.store import MemoryPlanStore
from friday.steps.suggest import ShoppingSuggester
from friday.steps.worker import AgentStepWorker, OverlayFacts, StepLogin, build_step_agent
from tests.browser_agent.fakes import A, FakePageSpec, Rig, make_rig
from tests.shopping.helpers import BIGBASKET, INSTAMART, SiteFake

Z = "https://zepto.com/"
RES = Z + "results"
SHOP = Z + "shop"
OTPP = Z + "otp"
CODE = "482913"  # the fake login code: it must never show up anywhere but inside the fake page
PHONE = "+919800000042"

LINES = ("Aashirvaad Select Whole Wheat Atta | 5 kg | Rs 289 ; Pillsbury Chakki Fresh Atta | 5 kg | Rs 262 ; "
         "Fortune Chakki Fresh Atta | 5 kg | Rs 275 ; Aashirvaad Select Whole Wheat Atta | 10 kg | Rs 540")


def search_els() -> list[dict[str, Any]]:
    return [{"name": "Search for products", "role": "textbox", "type": "search"}, {"name": "Delivery location", "role": "textbox"},
            {"name": "Search", "role": "button", "goes_to": RES}]


def pages(login_wall: bool = False, payment_on_results: bool = False, captcha: bool = False) -> dict[str, FakePageSpec]:
    home = FakePageSpec("Zepto", "Groceries in 10 minutes", search_els())
    if login_wall:
        home = FakePageSpec("Zepto login", "Log in to see prices", [{"name": "Mobile number", "role": "textbox", "type": "tel"},
                                                                   {"name": "Send OTP", "role": "button", "goes_to": OTPP}])
    if captcha:
        home = FakePageSpec("Zepto", "Checking your browser", [], captcha=True)
    res_text = "Results for atta. " + LINES
    if payment_on_results:
        res_text += " Enter card number to pay"
    return {
        Z: home,
        SHOP: FakePageSpec("Zepto", "Groceries in 10 minutes", search_els()),
        OTPP: FakePageSpec("Enter code", "We sent a code", [{"name": "Enter OTP", "role": "textbox", "autocomplete": "one-time-code"},
                                                          {"name": "Verify", "role": "button", "goes_to": SHOP}]),
        RES: FakePageSpec("Results", res_text, [{"name": "Back", "role": "link", "goes_to": Z}]),
    }


# --- scripted model actions, one list per step
OPEN_FREE = [A("screenshot_proof"), A("finish", result="login_wall=no; location_prompt=yes; Zepto home page")]
OPEN_WALL = [A("screenshot_proof"), A("finish", result="login_wall=yes; location_prompt=no; Zepto asks to log in")]
SEARCH_OK = [A("fill", target="e2", value_source="fact:delivery_area"), A("fill", target="e1", value_source="text:atta"),
             A("click", target="e3"), A("finish", result="results visible")]
SEARCH_WALL = [A("finish", result="login_wall=yes")]
SEARCH_BAD_AREA = [A("fill", target="e2", value_source="fact:delivery_area"), A("finish", result="location=not_accepted")]
READ_OK = [A("screenshot_proof"), A("finish", result=LINES)]
READ_NONE = [A("finish", result="no_price")]
LOGIN_REQ = [A("fill", target="e1", value_source="fact:phone"), A("click", target="e2"), A("finish", result="code_requested")]
LOGIN_ENTER = [A("fill", target="e1", value_source="otp"), A("click", target="e2"), A("finish", result="logged_in=yes")]
LOGIN_ENTER_BAD = [A("fill", target="e1", value_source="otp"), A("finish", result="logged_in=no")]


class FakeUsers:
    def __init__(self, saved: dict[str, str] | None = None) -> None:
        self.saved = dict(saved or {})

    async def saved_area(self, user_id: str) -> str:
        return self.saved.get("home") or self.saved.get("pg") or ""

    async def area_from_reply(self, user_id: str, text: str) -> str:
        ans = places.parse_answer(text)
        if ans is None:
            return self.saved.get(places.kind_of(text) or "", "")
        self.saved[ans.kind] = ans.where
        return ans.where

    async def phone_tail(self, user_id: str) -> str:
        return PHONE[-2:]


class FakeOtp:
    """The guarded one-time channel: OtpPort for the runner and LoginPort for the browser loop. ``send`` plays the guarded chat flow."""

    def __init__(self, allow: bool = True) -> None:
        self.allow, self.codes, self.armed, self.wiped = allow, {}, [], []

    def arm(self, user_id: str, site: str, key: str) -> bool:
        self.armed.append((user_id, site.lower(), key))
        return self.allow

    def ready(self, key: str) -> bool:
        return key in self.codes

    def wipe(self, key: str) -> None:
        self.codes.pop(key, None)
        self.wiped.append(key)

    def send(self, key: str, code: str = CODE) -> None:
        self.codes[key] = code

    def credential_link(self, user_id: str, site: str, hosts: list[str]) -> str | None:
        return None

    def release(self, user_id: str, site: str, host: str) -> tuple[str, str] | None:
        return None

    def otp_link(self, user_id: str, site: str, run_id: str) -> str | None:
        return None

    def take_otp(self, key: str) -> str | None:
        return self.codes.pop(key, None)


@dataclass
class World:
    runner: StepRunner
    rig: Rig
    otp: FakeOtp
    users: FakeUsers
    plans: MemoryPlanStore
    sent: list[str] = field(default_factory=list)
    audit: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    @property
    def browser(self):  # noqa: ANN201
        return self.rig.browser

    def last(self) -> str:
        return self.sent[-1]

    def plan(self):  # noqa: ANN201
        return self.plans.active_for("u1") or max((p for p in self.plans._all()), key=lambda p: p.updated_at)

    def feed(self, *script: Any) -> None:
        for part in script:
            self.rig.llm.script.extend(part)


def make_world(page_set: dict[str, FakePageSpec], *script: Any, saved: dict[str, str] | None = None, suggest: bool = True, fallback: bool = False,
               otp: bool = True, planner_llm: Any = None, plans: Any = None, **kw: Any) -> World:
    rig = make_rig(page_set, [], facts={"phone": PHONE})
    w_otp = FakeOtp()
    overlay = OverlayFacts(rig.facts)
    run_store = MemoryRunStore()
    login = StepLogin(w_otp, run_store)
    worker = AgentStepWorker(build_step_agent(rig.agent, store=run_store, overlay=overlay, login=login), overlay, login)
    users = FakeUsers(saved)
    sent: list[str] = []
    audit: list[tuple[str, dict[str, object]]] = []

    async def say(user_id: str, text: str) -> None:
        sent.append(text)

    async def fb(st: Any) -> None:
        sent.append("FALLBACK:web-prices-for-" + st.plan.slots.get("item", ""))

    suggester = ShoppingSuggester(ShoppingAgent(SiteFake({"bigbasket": BIGBASKET, "instamart": INSTAMART})), store="Zepto") if suggest else None
    store = plans or MemoryPlanStore()
    runner = StepRunner(worker=worker, planner=StepPlanner(planner_llm), users=users, say=say, store=store, clock=rig.clock,
                        otp=w_otp if otp else None, suggester=suggester, fallback=fb if fallback else None,
                        audit=lambda e, **k: audit.append((e, k)), poll_interval_s=0, **kw)
    world = World(runner, rig, w_otp, users, store, sent, audit)
    world.feed(*script)
    return world
