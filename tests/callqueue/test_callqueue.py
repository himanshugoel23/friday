# ruff: noqa: E501
"""Friday's own call queue: limits, pacing, priority, one-per-destination, idempotency, restart
safety, ring-timeout cancel, guards, kill switch, doctor, logs. Fakes only: no network, no calls."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from friday.callqueue import metrics
from friday.callqueue.doctor import check
from friday.callqueue.limits import Limits, resolve, save_probe
from friday.callqueue.queue import (
    CallQueue,
    GuardedDialer,
    QueueRefused,
    build_queue,
    install_call_queue,
)
from friday.callqueue.store import NORMAL, URGENT, QueueStore
from friday.core.config import Settings
from friday.core.models import DialStatus, OutboundCallRequest
from friday.pause import PausedError

NUMS = [f"+9190000000{i:02d}" for i in range(10)]


class Clk:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


async def tick(_seconds: float = 0) -> None:
    await asyncio.sleep(0.001)


async def settle(n: int = 15) -> None:
    for _ in range(n):
        await asyncio.sleep(0.002)


class FakeLeg:
    provider = "fake"

    def __init__(self, to: str, answer: DialStatus | None = DialStatus.ANSWERED) -> None:
        self.provider_call_id = f"uuid-{to[-2:]}"
        self.to = to
        self.status: DialStatus | None = (
            DialStatus.ANSWERED if answer == DialStatus.ANSWERED else None
        )
        self.answer = answer
        self.ended = False
        self.hangups = 0

    async def wait_for_answer(self, timeout_s: float) -> DialStatus:
        if self.answer is None:
            await asyncio.sleep(3600)
        return self.answer  # type: ignore[return-value]

    async def hangup(self) -> None:
        self.hangups += 1
        self.ended = True


class FakeTel:
    name = "fake"

    def __init__(
        self,
        clk: Clk,
        fail: set[str] | None = None,
        answer: DialStatus | None = DialStatus.ANSWERED,
    ) -> None:
        self.clk, self.fail, self.answer = clk, fail or set(), answer
        self.placed: list[tuple[str, float]] = []
        self.legs: dict[str, FakeLeg] = {}

    async def place_call(self, request: OutboundCallRequest) -> FakeLeg:
        if request.to_phone in self.fail:
            raise RuntimeError("boom")
        self.placed.append((request.to_phone, self.clk.t))
        leg = FakeLeg(request.to_phone, self.answer)
        self.legs[request.to_phone] = leg
        return leg


def req(to: str, task: str | None = None, **md: str) -> OutboundCallRequest:
    return OutboundCallRequest(
        to_phone=to,
        task_id=task or f"t-{to[-2:]}",
        ring_timeout_s=30,
        max_duration_s=300,
        metadata=md,
    )


def settings_for(tmp: Path, **kw: Any) -> Settings:
    return Settings(
        _env_file=None,
        **{"mode": "simulator", "env": "test", "call_queue_db": str(tmp / "q.db"), **kw},
    )


def make(
    tmp_path: Path, *, conc: int = 3, cps: float = float("inf"), clk: Clk | None = None, **qk: Any
):
    clk = clk or Clk()
    store = QueueStore(tmp_path / "q.db", clock=clk)
    q = CallQueue(store, limits=Limits(conc, cps), sleep=tick, poll_s=0.01, **qk)
    s = settings_for(tmp_path)
    tel = FakeTel(clk)
    d = GuardedDialer(tel.place_call, q, s)
    return clk, store, q, tel, d


@pytest.fixture(autouse=True)
def _reset() -> None:
    metrics.reset()


async def test_concurrency_cap_and_release_on_hangup(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=3)
    tasks = [asyncio.create_task(d.place_call(req(n))) for n in NUMS[:5]]
    await settle()
    assert len(tel.placed) == 3 and store.counts() == {"waiting": 2, "active": 3, "stale": 0}
    first = next(t for t in tasks if t.done())
    await first.result().hangup()  # slot released on hangup
    await settle()
    assert len(tel.placed) == 4
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert metrics.snapshot()["enqueued"] == 5


async def test_slot_released_on_not_answered_failure_and_cancel(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=1)
    tel.fail = {NUMS[0]}
    with pytest.raises(RuntimeError):
        await d.place_call(req(NUMS[0]))
    assert store.counts()["active"] == 0  # failed placement frees the slot
    tel.answer = DialStatus.NO_ANSWER
    leg = await d.place_call(req(NUMS[1]))
    assert await leg.wait_for_answer(30) == DialStatus.NO_ANSWER
    assert store.counts()["active"] == 0 and tel.legs[NUMS[1]].hangups == 1  # DELETE issued
    tel.answer = DialStatus.ANSWERED
    leg2 = await d.place_call(req(NUMS[2]))
    await leg2.wait_for_answer(30)
    assert store.counts()["active"] == 1
    # a waiter that is cancelled leaves nothing behind
    w = asyncio.create_task(d.place_call(req(NUMS[3])))
    await settle()
    w.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await w
    assert store.counts() == {"waiting": 0, "active": 1, "stale": 0}


async def test_start_rate_one_per_second(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=5, cps=1.0)
    tasks = [asyncio.create_task(d.place_call(req(n))) for n in NUMS[:3]]
    await settle()
    assert len(tel.placed) == 1  # the others wait for the 1 s gap
    for _ in range(2):
        clk.t += 1.0
        await settle()
    assert [round(t - tel.placed[0][1]) for _, t in tel.placed] == [0, 1, 2]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_urgent_before_normal_then_oldest(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=1)
    holder = await d.place_call(req(NUMS[0]))
    order = []
    ts = []
    for _i, (n, md) in enumerate(
        [(NUMS[1], {}), (NUMS[2], {}), (NUMS[3], {"kind": "urgent_escalation"})]
    ):
        clk.t += 1
        ts.append(asyncio.create_task(d.place_call(req(n, **md))))
        await settle(3)
    for _ in range(3):
        await holder.hangup()
        await settle()
        order.append(tel.placed[-1][0])
        holder = next(
            t
            for t in ts
            if t.done() and t.result().provider_call_id.endswith(tel.placed[-1][0][-2:])
        ).result()
    assert order == [NUMS[3], NUMS[1], NUMS[2]]
    assert (URGENT, NORMAL) == (0, 1)


async def test_one_call_per_destination(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=3)
    a = await d.place_call(req(NUMS[0], "a"))
    b = asyncio.create_task(d.place_call(req(NUMS[0], "b")))  # same number, different task
    c = asyncio.create_task(d.place_call(req(NUMS[1], "c")))
    await settle()
    assert c.done() and not b.done()  # the other number is not blocked behind it
    await a.hangup()
    await settle()
    assert b.done()
    b.result().inner.ended = True
    c.cancel()


async def test_idempotent_enqueue(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=1)
    await d.place_call(req(NUMS[0], "same", idempotency_key="k1"))
    with pytest.raises(QueueRefused) as ei:
        await d.place_call(req(NUMS[0], "other", idempotency_key="k1"))
    assert ei.value.code == "duplicate_call" and len(tel.placed) == 1
    e1, c1 = store.enqueue(key="z", number=NUMS[5], priority=1, ring_s=30, max_s=300)
    e2, c2 = store.enqueue(key="z", number=NUMS[5], priority=1, ring_s=30, max_s=300)
    assert c1 and not c2 and e1.id == e2.id


async def test_restart_safe_and_stale_slot_reclaimed(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=1, grace_s=10)
    await d.place_call(req(NUMS[0]))  # process "crashes" without releasing
    store.close()
    # new process, same file: the slot is still held ...
    store2 = QueueStore(tmp_path / "q.db", clock=clk)
    q2 = CallQueue(store2, limits=Limits(1, float("inf")), sleep=tick, poll_s=0.01)
    tel2 = FakeTel(clk)
    d2 = GuardedDialer(tel2.place_call, q2, settings_for(tmp_path))
    assert store2.counts()["active"] == 1
    w = asyncio.create_task(d2.place_call(req(NUMS[1])))
    await settle()
    assert not w.done()
    clk.t += 30 + 300 + 10 + 1  # ... until its deadline (ring + max call + grace) passes
    await settle()
    assert w.done() and metrics.snapshot()["reclaimed_stale"] == 1


async def test_unanswered_call_cancelled_after_ring_timeout_plus_grace(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=1, grace_s=10)
    tel.answer = None  # never answers, wait_for_answer never returns
    leg = await d.place_call(req(NUMS[0]))
    await settle()
    assert tel.legs[NUMS[0]].hangups == 0
    clk.t += 30  # ring timeout alone is not enough ...
    await settle()
    assert tel.legs[NUMS[0]].hangups == 0
    clk.t += 11  # ... plus the grace
    await settle()
    assert tel.legs[NUMS[0]].hangups == 1 and store.counts()["active"] == 0 and leg.released
    assert metrics.snapshot()["ring_cancelled"] == 1


async def test_answered_call_released_when_it_ends_or_exceeds_max(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=2, grace_s=10)
    a = await d.place_call(req(NUMS[0]))
    await a.wait_for_answer(30)
    b = await d.place_call(req(NUMS[1]))
    await b.wait_for_answer(30)
    clk.t += 100
    await settle()
    assert store.counts()["active"] == 2  # a live answered call is not cut
    tel.legs[NUMS[0]].ended = True  # caller hung up, nobody called hangup()
    await settle()
    assert store.counts()["active"] == 1
    clk.t += 400  # past ring + max duration + grace
    await settle()
    assert store.counts()["active"] == 0 and tel.legs[NUMS[1]].hangups == 1


async def test_allowlist_and_kill_switch_stay_in_force(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path)
    d.settings = settings_for(
        tmp_path, profile="pilot", mode="live", pilot_allowed_numbers=[NUMS[0]]
    )
    with pytest.raises(QueueRefused) as ei:
        await d.place_call(req(NUMS[1]))
    assert ei.value.code == "test_allowlist" and tel.placed == [] and store.counts()["waiting"] == 0
    await d.place_call(req(NUMS[0]))
    assert len(tel.placed) == 1
    # kill switch: a waiting call is dropped, not dialled
    pause = tmp_path / "PAUSED"
    d.settings = settings_for(tmp_path, pause_file=str(pause))
    pause.write_text("paused")
    with pytest.raises(PausedError):
        await d.place_call(req(NUMS[2]))
    assert len(tel.placed) == 1 and store.counts()["waiting"] == 0


async def test_max_wait_gives_up(tmp_path: Path) -> None:
    clk, store, q, tel, d = make(tmp_path, conc=1, max_wait_s=50)
    await d.place_call(req(NUMS[0]))
    w = asyncio.create_task(d.place_call(req(NUMS[1])))
    await settle()
    clk.t += 51
    with pytest.raises(QueueRefused) as ei:
        await asyncio.wait_for(w, 2)
    assert ei.value.code == "queue_wait_timeout"


async def test_logs_never_contain_phone_numbers(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    clk, store, q, tel, d = make(tmp_path, conc=1, grace_s=10)
    tel.answer = None
    await d.place_call(req(NUMS[3]))
    w = asyncio.create_task(d.place_call(req(NUMS[4])))
    await settle()
    clk.t += 50
    await settle()
    w.cancel()
    with contextlib.suppress(BaseException):
        await w
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "call queue" in text and "...03" in text  # only the last two digits
    for n in NUMS[:6]:
        assert n not in text and n[-8:] not in text
    raw = await asyncio.to_thread((tmp_path / "q.db").read_bytes)
    assert NUMS[3].encode() not in raw  # the state file keeps a hash + 2 digits, not the number


def test_install_is_noop_when_disabled_and_wraps_when_enabled(tmp_path: Path) -> None:
    clk = Clk()
    tel = FakeTel(clk)
    orig = tel.place_call

    def container(**kw: Any) -> SimpleNamespace:
        return SimpleNamespace(
            settings=settings_for(tmp_path, **kw),
            role_components=lambda: ["telephony"],
            get=lambda n: tel,
        )

    assert (
        install_call_queue(container()) == [] and tel.place_call == orig
    )  # default: direct dial, unchanged
    assert install_call_queue(container(call_queue_enabled=True)) == ["telephony.place_call"]
    assert tel.place_call != orig and tel._friday_call_queue is not None
    assert install_call_queue(container(call_queue_enabled=True)) == [
        "telephony.place_call"
    ]  # idempotent
    assert Settings(_env_file=None).call_queue_enabled is False


def test_limits_resolution_order(tmp_path: Path) -> None:
    s = settings_for(tmp_path)
    assert resolve(s) == Limits(3, 1.0, "default")
    assert save_probe(s, {"concurrent_calls_limit": 5, "cps_limit": 2})
    assert resolve(s) == Limits(5, 2.0, "account")
    s2 = settings_for(tmp_path, call_queue_max_concurrent=2)
    assert resolve(s2).max_concurrent == 2 and resolve(s2).cps == 2.0
    assert not save_probe(s, {"concurrent_calls_limit": None, "cps_limit": 0})


def test_build_queue_and_doctor(tmp_path: Path) -> None:
    off = check(settings_for(tmp_path))
    assert off[0][0] == "ok" and "OFF" in off[0][1]
    on_s = settings_for(tmp_path, call_queue_enabled=True)
    res = check(on_s)
    assert any("ON" in m for _, m in res) and any(st == "warn" and "defaults" in m for st, m in res)
    assert not any(st == "fail" for st, _ in res)
    q = build_queue(on_s)
    assert q.limits.max_concurrent == 3
    from friday.ops import doctor as d

    sec = d._check_call_queue(on_s)
    assert sec.name == "call_queue" and "call_queue" in d.SECTIONS
