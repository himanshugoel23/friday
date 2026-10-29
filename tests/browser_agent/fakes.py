# ruff: noqa: E501
"""Fakes for the browser agent: scripted pages (no network, no Chromium) and a scripted LLM."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from friday.browser_agent.agent import BrowserAgent
from friday.browser_agent.errors import ActionFailed, Blocked, Busy
from friday.browser_agent.stores import AgentLog, MemoryFacts, MemoryRunStore
from friday.browser_agent.types import Action, AskField, Element, PageSnapshot, RunSpec


def A(tool: str, **kw: Any) -> Action:
    base: dict[str, Any] = dict(tool=tool, note="", url=None, target=None, value_source=None, option=None, file_ref=None, key=None,
                                ms=None, question=None, kind=None, fields=None, suggest=None, summary=None, result=None, reason=None)
    base.update(kw)
    return Action(**base)


def F(key: str, label: str, default: str | None = None, options: list[str] | None = None) -> AskField:
    return AskField(key=key, label=label, default=default, options=options)


@dataclass
class FakePageSpec:
    title: str = ""
    text: str = ""
    elements: list[dict[str, Any]] = field(default_factory=list)  # {name, role, type?, options?, required?, submit?, goes_to?, href_host?, checked?}
    status: int = 200
    captcha: bool = False


class FakeBrowser:
    """A tiny site: url -> FakePageSpec. Clicking an element with ``goes_to`` navigates. Records every action (values included,
    so tests can assert what reached the page) in ``log``."""

    def __init__(self, pages: dict[str, FakePageSpec], start: str = "about:blank") -> None:
        self.pages, self.url = pages, start
        self.log: list[tuple[str, ...]] = []
        self.values: dict[str, str] = {}
        self.uploads: list[tuple[str, str]] = []
        self.upload_ok = True
        self.submitted = False
        self.shots = 0

    def spec(self) -> FakePageSpec:
        return self.pages.get(self.url, FakePageSpec(title="404", text="not found", status=404))

    def els(self) -> list[dict[str, Any]]:
        return self.spec().elements

    def by_id(self, eid: str) -> dict[str, Any]:
        i = int(eid[1:]) - 1
        if not (0 <= i < len(self.els())):
            raise ActionFailed("no such element")
        return self.els()[i]

    # --- AgentPage
    async def goto(self, url: str) -> None:
        self.log.append(("goto", url))
        self.url = url

    async def snapshot(self) -> PageSnapshot:
        sp = self.spec()
        els = []
        for i, e in enumerate(sp.elements, 1):
            els.append(Element(id=f"e{i}", role=e.get("role", "textbox"), name=e["name"], type=e.get("type", ""), options=e.get("options", []),
                               required=e.get("required", False), submit=e.get("submit", False), href_host=e.get("href_host", ""),
                               checked=e.get("checked"), value=self.values.get(e["name"], ""), autocomplete=e.get("autocomplete", "")))
        return PageSnapshot(url=self.url, title=sp.title, http_status=sp.status, text=sp.text, elements=els, captcha=sp.captcha)

    async def click(self, element_id: str) -> None:
        e = self.by_id(element_id)
        self.log.append(("click", e["name"]))
        if e.get("submit_marks"):
            self.submitted = True
        if e.get("goes_to"):
            self.url = e["goes_to"]

    async def fill(self, element_id: str, value: str) -> None:
        e = self.by_id(element_id)
        self.log.append(("fill", e["name"], value))
        self.values[e["name"]] = value

    async def select(self, element_id: str, option: str) -> None:
        e = self.by_id(element_id)
        self.log.append(("select", e["name"], option))
        self.values[e["name"]] = option

    async def check(self, element_id: str, checked: bool) -> None:
        e = self.by_id(element_id)
        self.log.append(("check", e["name"], str(checked)))
        e["checked"] = checked

    async def upload(self, element_id: str, path: str) -> bool:
        e = self.by_id(element_id)
        self.log.append(("upload", e["name"], path))
        self.uploads.append((e["name"], path))
        return self.upload_ok

    async def press(self, key: str) -> None:
        self.log.append(("press", key))

    async def wait(self, ms: int) -> None:
        return None

    async def screenshot(self) -> bytes:
        self.shots += 1
        return b"\xff\xd8\xff fake jpeg"

    def current_url(self) -> str:
        return self.url

    # helpers for assertions
    def typed(self) -> list[str]:
        return [x[2] for x in self.log if x[0] in ("fill", "select")]

    def clicked(self) -> list[str]:
        return [x[1] for x in self.log if x[0] == "click"]


class FakeProvider:
    def __init__(self, browser: FakeBrowser, *, block: str = "", busy: str = "") -> None:
        self.browser, self.block, self.busy = browser, block, busy
        self.opens = 0
        self.domains_seen: list[list[str]] = []
        self.reopened = 0

    @contextlib.asynccontextmanager
    async def session(self, user_id: str, spec: RunSpec, domains: list[str]):  # type: ignore[no-untyped-def]
        if self.busy:
            raise Busy(self.busy)
        if self.block:
            raise Blocked(self.block)
        self.opens += 1
        self.domains_seen.append(list(domains))
        yield self.browser

    async def reopen(self, user_id: str, spec: RunSpec) -> None:
        self.reopened += 1


class ScriptedLLM:
    """Returns the next scripted action (or calls it with the prompt). Records every prompt it was given."""

    def __init__(self, script: list[Action | Callable[[str], Action]], cost: float = 0.3) -> None:
        self.script, self.cost, self.prompts, self.i = list(script), cost, [], 0
        self.extract_answer = "the answer"
        self.parsed: dict[str, str] = {}

    async def decide(self, *, system: str, user: str) -> tuple[Action, float]:
        self.prompts.append(user)
        if self.i >= len(self.script):
            return A("give_up", reason="script ended"), self.cost
        nxt = self.script[self.i]
        self.i += 1
        a = nxt(user) if callable(nxt) else nxt
        return a, self.cost

    async def extract(self, *, question: str, page_text: str) -> tuple[str, float]:
        return self.extract_answer, 0.1

    async def parse_answers(self, *, fields: list[AskField], reply: str) -> tuple[dict[str, str], float]:
        return dict(self.parsed), 0.1


class FakeFiles:
    def __init__(self, refs: dict[str, str] | None = None) -> None:
        self.refs = refs or {}

    def resolve(self, user_id: str, file_ref: str) -> str | None:
        return self.refs.get(file_ref)


class FakeProofs:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save(self, user_id: str, run_id: str, what: str, url: str, png: bytes) -> tuple[str, str]:
        self.saved.append(dict(user=user_id, run=run_id, what=what, url=url, size=len(png)))
        return f"p{len(self.saved)}", f"/fake/p{len(self.saved)}.jpg"


class FakeLogin:
    def __init__(self, creds: tuple[str, str] | None = None, link: str | None = "https://f.example/secure/abc", code: str | None = None) -> None:
        self.creds, self.link, self.code = creds, link, code
        self.released: list[tuple[str, str]] = []

    def credential_link(self, user_id: str, site: str, hosts: list[str]) -> str | None:
        return self.link

    def release(self, user_id: str, site: str, host: str) -> tuple[str, str] | None:
        self.released.append((site, host))
        return self.creds

    def otp_link(self, user_id: str, site: str, run_id: str) -> str | None:
        return self.link

    def take_otp(self, run_id: str) -> str | None:
        c, self.code = self.code, None
        return c


class TickClock:
    """Minimal core Clock: manual time."""

    def __init__(self) -> None:
        self.t = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> None:
        self.t += timedelta(**kw)

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds=seconds)


@dataclass
class Rig:
    agent: BrowserAgent
    browser: FakeBrowser
    provider: FakeProvider
    llm: ScriptedLLM
    facts: MemoryFacts
    store: MemoryRunStore
    proofs: FakeProofs
    log: AgentLog
    clock: TickClock
    login: FakeLogin
    files: FakeFiles


def make_rig(pages: dict[str, FakePageSpec], script: list, *, facts: dict[str, str] | None = None, start: str = "about:blank",
             login: FakeLogin | None = None, files: dict[str, str] | None = None, store: Any = None, perf: Callable[[], float] | None = None,
             block: str = "", busy: str = "", cost: float = 0.3, user: str = "u1", **agent_kw: Any) -> Rig:
    browser = FakeBrowser(pages, start)
    provider = FakeProvider(browser, block=block, busy=busy)
    llm = ScriptedLLM(script, cost)
    mf = MemoryFacts({user: facts or {}})
    st = store or MemoryRunStore()
    proofs, lg, clock = FakeProofs(), AgentLog(), TickClock()
    lg_login = login or FakeLogin()
    ff = FakeFiles(files)
    kw: dict[str, Any] = dict(provider=provider, llm=llm, facts=mf, files=ff, store=st, proofs=proofs, login=lg_login, log_sink=lg, clock=clock)
    if perf is not None:
        kw["perf"] = perf
    kw.update(agent_kw)
    return Rig(BrowserAgent(**kw), browser, provider, llm, mf, st, proofs, lg, clock, lg_login, ff)


def spec(goal: str = "fill the form", domains: list[str] | None = None, **kw: Any) -> RunSpec:
    return RunSpec(goal=goal, allowed_domains=domains or ["jobs.example.com"], lang="en", **kw)


__all__ = ["A", "F", "FakePageSpec", "Path", "make_rig", "spec"]
