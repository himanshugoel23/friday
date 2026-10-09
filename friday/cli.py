"""`friday` command line.

    uv run friday check     # show mode + resolved providers + which modules exist
    uv run friday initdb    # create tables in FRIDAY_DATABASE_URL
    uv run friday serve     # run the API (needs friday.api.app:create_app)
    uv run friday worker --roles voice,task   # background roles without the HTTP server
    uv run friday pause [--resume|--status]   # kill switch (no calls / nudges)
    uv run friday init-env | doctor | livecall --to +91... [--simulate]   # laptop live test
    uv run friday listen [--simulate | --restore] [--seconds N]   # front door: people call Friday
    uv run friday chat      # local WhatsApp simulator chat (needs friday.channels.cli:main)
    uv run friday loadtest --users 1000 --calls 200   # S-11 load test on the simulator

Owner: EM scaffold -> QA Engineer finalises the run commands.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import signal
import sys

from friday.core.config import Settings
from friday.core.container import FACTORIES, Container
from friday.core.logging import setup_logging
from friday.pause import install_pause_guard, is_paused, pause_status, set_paused


def _check(settings: Settings) -> int:
    c = Container(settings)
    print(f"mode: {settings.mode}   db: {settings.database_url.split('@')[-1]}")
    print(f"roles: {','.join(settings.roles)}")
    for component in FACTORIES:
        provider = c.provider_for(component)
        if provider == "off":
            print(f"  {component:20s} {provider:14s} DISABLED (provider not configured)")
            continue
        try:
            path = c.factory_path(component)
        except Exception as e:  # noqa: BLE001
            print(f"  {component:20s} {provider:14s} ERROR {e}")
            continue
        status = "ok" if c.is_available(component) else "not implemented yet"
        print(f"  {component:20s} {provider:14s} {path:60s} {status}")
    llm = settings.resolve_llm()
    if llm != "fake":
        have = "set" if settings.llm_key_configured() else "NOT SET"
        print(f"  llm brain: {llm}  key {settings.llm_key_name()} {have}  models: light="
              f"{settings.model_for('interpret')} call_turn={settings.model_for('call_turn')} "
              f"escalation={settings.model_for('', escalate=True)}")
    missing = c.missing_role_components()
    if missing:
        print(f"  ! components needed by roles {','.join(settings.roles)} but not implemented: "
              + ", ".join(missing))
    if not settings.is_live:
        return 0
    problems = settings.live_problems()
    for note in settings.optional_feature_notes():
        print(f"  disabled or simulated: {note}")
    if not problems:
        print("live configuration: OK")
        return 1 if missing else 0
    print(f"\nLIVE CONFIGURATION INCOMPLETE - {len(problems)} problem(s); Friday will not start:")
    for p in problems:
        print(f"  MISSING/UNSAFE  {p.removeprefix('missing ')}" if p.startswith("missing ")
              else f"  PROBLEM         {p}")
    print("Set them in the environment or .env (see .env.example), then re-run `friday check`.")
    return 1


def _pause(settings: Settings, *, resume: bool, status_only: bool) -> int:
    if not status_only:
        set_paused(settings, on=not resume)
    print(f"kill switch: {pause_status(settings)}")
    if status_only:
        return 3 if is_paused(settings) else 0
    if resume:
        if settings.paused:
            print("FRIDAY_PAUSED=true is still set in the environment: change it and restart.")
            return 1
        print("Resumed: queued calls and nudges continue now.")
        return 0
    print("Paused: no new calls or nudges. Inbound messages still get a polite notice.")
    print("Calls already in progress finish normally. Undo with: friday pause --resume")
    return 0


async def _worker(settings: Settings) -> None:
    from friday.api.runtime import Runtime

    c = Container(settings)
    runtime = Runtime(c)
    install_pause_guard(c)
    await runtime.start(background=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    print(f"friday worker running: roles={','.join(settings.roles)} (Ctrl-C to drain and stop)")
    await stop.wait()
    await runtime.stop()
    await c.aclose()


async def _initdb(settings: Settings) -> None:
    c = Container(settings)
    await c.db.create_all()
    await c.aclose()
    print("tables created")


# ------------------------------------------------------------------------- load test (S-11)
LOAD_BUSINESSES = (  # (phone, message) - reachable personas of friday/simworld/world.json
    ("+918040000001", "Looks Unisex Salon mein haircut book karo kal shaam"),
    ("+912040000002", "Dr. Sharma's Family Clinic mein appointment book karo kal subah"),
    ("+918040000003", "CoolCare AC Services mein AC repair book karo Saturday"),
    ("+918040000012", "Raju Plumbing Works ko call karke tap leak ka price pucho"),
    ("+912040000006", "Wellness Pharmacy Kothrud ko call karke Dolo 650 ka stock pucho"),
    ("+918040001008", "SafeShift Packers & Movers ko call karke shifting ka price pucho"),
)


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


class _LoadClock:
    """Wall-clock-speed clock that starts at a chosen IST instant."""

    def __init__(self, start):  # noqa: ANN001, ANN204
        import time

        self._start, self._t0, self._time = start, time.monotonic(), time

    def now(self):  # noqa: ANN201
        from datetime import timedelta

        return self._start + timedelta(seconds=self._time.monotonic() - self._t0)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds))


async def _loadtest(
    users: int, calls: int, dup_rate: float, timeout_s: float, roles: list[str]
) -> dict:
    import tempfile
    import time
    from collections import Counter, defaultdict
    from datetime import datetime
    from pathlib import Path

    from friday.api.runtime import Runtime
    from friday.core.clock import IST
    from friday.core.models import (
        Consent,
        ConsentKind,
        Profile,
        TaskStatus,
        User,
        UserStatus,
    )

    folder = Path(tempfile.mkdtemp(prefix="friday-load-"))
    settings = Settings(
        _env_file=None,
        mode="simulator",
        env="test",
        database_url=f"sqlite+aiosqlite:///{folder}/load.db",
        media_dir=str(folder / "media"),
        invite_only=False,
        roles=roles,
        queue_poll_interval_s=0.05,
        anthropic_api_key=None,
        sarvam_api_key=None,
        deepgram_api_key=None,
        elevenlabs_api_key=None,
        google_places_api_key=None,
    )
    # Monday 10:30 IST, advancing with the wall clock. (A FakeClock jumps whenever any call
    # sleeps, which would expire every other call's queue lease; simulated calls take 0 s.)
    clock = _LoadClock(datetime(2026, 1, 5, 10, 30, tzinfo=IST))
    c = Container(settings, clock=clock)
    await c.db.create_all()
    rt = Runtime(c, fast_pin_hash=True)
    await rt.start(background=True)
    channel = c.messaging
    brain = c.brain
    turn_ms: list[float] = []
    real_turn = brain.next_call_action

    async def timed_turn(*a, **k):  # noqa: ANN002, ANN003
        t0 = time.perf_counter()
        try:
            return await real_turn(*a, **k)
        finally:
            turn_ms.append((time.perf_counter() - t0) * 1000)

    brain.next_call_action = timed_turn

    # ---- N users (bulk, already onboarded: onboarding itself is covered by tests/e2e)
    phones: list[str] = []
    for i in range(users):
        phone = f"+9197{i:08d}"
        u = await c.repos.users.add(
            User(phone=phone, status=UserStatus.ACTIVE, onboarding_step=_done())
        )
        await c.repos.profiles.save(Profile(user_id=u.id, name=f"User{i}", city="Bengaluru"))
        await c.repos.consents.add(
            Consent(
                user_id=u.id, kind=ConsentKind.TERMS_PRIVACY, granted=True, evidence_text="I agree"
            )
        )
        phones.append(phone)

    depth_samples: list[int] = []
    queue = c.get("job_queue")

    async def sampler() -> None:
        while True:
            depth_samples.append(await queue.depth(due_only=False))
            await asyncio.sleep(0.25)

    sampling = asyncio.create_task(sampler())
    gate = asyncio.Semaphore(max(1, calls))  # at most M journeys (= live calls) in flight
    ack_ms: list[float] = []
    duplicates_sent = 0
    stuck: list[str] = []

    from friday.core.events import TaskStatusChanged

    user_phone: dict[str, str] = {}
    for phone in phones:
        user_phone[(await c.repos.users.get_by_phone(phone)).id] = phone
    latest: dict[str, TaskStatus] = {}  # phone -> status of the user's first (top-level) task
    first_task: dict[str, str] = {}
    changed: dict[str, asyncio.Event] = {p: asyncio.Event() for p in phones}

    async def on_status(ev: TaskStatusChanged) -> None:
        phone = user_phone.get(ev.user_id)
        if phone is None or first_task.setdefault(phone, ev.task_id) != ev.task_id:
            return
        latest[phone] = ev.new
        changed[phone].set()

    c.bus.subscribe(TaskStatusChanged, on_status)

    async def wait_task(phone: str, want: set[TaskStatus]) -> TaskStatus | None:
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            if latest.get(phone) in want:
                return latest[phone]
            changed[phone].clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(changed[phone].wait(), 1.0)
        return None

    async def journey(i: int, phone: str) -> None:
        nonlocal duplicates_sent
        async with gate:
            _biz, text = LOAD_BUSINESSES[i % len(LOAD_BUSINESSES)]
            msg = channel.make_inbound(phone, text)
            t0 = time.perf_counter()
            assert await rt.accept_inbound(msg) is True
            ack_ms.append((time.perf_counter() - t0) * 1000)
            if (i / max(1, users)) < dup_rate:  # provider re-delivers the same webhook
                duplicates_sent += 1
                assert await rt.accept_inbound(msg) is False
            state = await wait_task(
                phone, {TaskStatus.AWAITING_APPROVAL, TaskStatus.COMPLETED, TaskStatus.FAILED}
            )
            if state == TaskStatus.AWAITING_APPROVAL:
                await rt.accept_inbound(channel.make_inbound(phone, "1"))
                state = await wait_task(phone, {TaskStatus.COMPLETED, TaskStatus.FAILED})
            if state is None:
                stuck.append(phone)

    started = time.perf_counter()
    await asyncio.gather(*(journey(i, p) for i, p in enumerate(phones)))
    wall = time.perf_counter() - started
    sampling.cancel()

    # ---- accounting
    per_user_tasks: dict[str, list] = defaultdict(list)
    calls_by_task: dict[str, list] = {}
    cost_by_type: dict[str, list[float]] = defaultdict(list)
    status_count: Counter = Counter()
    total_calls = 0
    for phone in phones:
        user = await c.repos.users.get_by_phone(phone)
        for t in await c.repos.tasks.list_for_user(user.id):
            per_user_tasks[phone].append(t)
            cl = await c.repos.tasks.list_calls(t.id)
            calls_by_task[t.id] = cl
            total_calls += len(cl)
            status_count[t.status.value] += 1
            cost_by_type[t.type.value].append(sum(x.cost_inr_est for x in cl))
    lost_tasks = sum(1 for p in phones if not per_user_tasks[p])
    dup_tasks = sum(max(0, len(v) - 1) for v in per_user_tasks.values())
    unfinished = sum(1 for v in per_user_tasks.values() for t in v if not t.status.is_terminal)
    all_calls = [x for cl in calls_by_task.values() for x in cl]
    dup_calls = len(all_calls) - len({x.call_id for x in all_calls})
    dup_calls += sum(1 for t in (t for v in per_user_tasks.values() for t in v)
                     if len(calls_by_task[t.id]) > 2)
    lost_calls = sum(1 for t in (t for v in per_user_tasks.values() for t in v)
                     if t.status.value == "completed" and not calls_by_task[t.id])
    outbox = channel.outbox
    dup_msgs = len(outbox) - len({m.id for m in outbox})
    seen: Counter = Counter((m.to_phone, m.task_id, m.text) for m in outbox if m.text)
    dup_msgs += sum(v - 1 for v in seen.values() if v > 1)
    users_without_reply = sum(1 for p in phones if not channel.messages_to(p))
    result = {
        "users": users,
        "concurrent_calls": calls,
        "duplicate_webhooks_sent": duplicates_sent,
        "wall_s": round(wall, 1),
        "tasks": sum(len(v) for v in per_user_tasks.values()),
        "calls": total_calls,
        "messages_out": len(outbox),
        "task_throughput_per_s": round(sum(len(v) for v in per_user_tasks.values()) / wall, 2),
        "call_throughput_per_s": round(total_calls / wall, 2),
        "message_throughput_per_s": round(len(outbox) / wall, 2),
        "webhook_ack_ms_p50_p95": (round(_pct(ack_ms, 0.5), 1), round(_pct(ack_ms, 0.95), 1)),
        "call_turn_ms_p50_p95": (round(_pct(turn_ms, 0.5), 1), round(_pct(turn_ms, 0.95), 1)),
        "call_turns": len(turn_ms),
        "queue_depth_max": max(depth_samples or [0]),
        "queue_depth_p95": _pct([float(x) for x in depth_samples], 0.95),
        "task_status": dict(status_count),
        "task_status_by_business": {
            b: dict(Counter(t.status.value for v in per_user_tasks.values() for t in v
                            if t.target and t.target.phone == b))
            for b, _ in LOAD_BUSINESSES
        },
        "lost_tasks": lost_tasks,
        "duplicate_tasks": dup_tasks,
        "unfinished_tasks": unfinished,
        "stuck_users": len(stuck),
        "lost_calls": lost_calls,
        "duplicate_calls": dup_calls,
        "duplicate_messages": dup_msgs,
        "users_without_any_reply": users_without_reply,
        "inr_per_task_by_type": {
            k: {"tasks": len(v), "avg_inr": round(sum(v) / len(v), 2)}
            for k, v in cost_by_type.items()
        },
    }
    result["pass"] = not (
        lost_tasks or dup_tasks or unfinished or stuck or lost_calls or dup_calls
        or dup_msgs or users_without_reply
    )
    await rt.stop()
    await c.aclose()
    return result


def _done():  # noqa: ANN202
    from friday.core.models import OnboardingStep

    return OnboardingStep.DONE


def _print_load(r: dict) -> None:
    print("\nFRIDAY LOAD TEST (simulator, wall-speed sim clock, SQLite)")
    for k, v in r.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"      {kk}: {vv}")
        else:
            print(f"  {k}: {v}")
    print("RESULT:", "PASS (zero lost / duplicate items)" if r["pass"] else "FAIL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="friday")
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check")
    check.add_argument("--live", action="store_true", help="also run the read-only Vobiz probe")
    sub.add_parser("initdb")
    sub.add_parser("serve")
    pause = sub.add_parser("pause", help="kill switch: stop outbound calls and proactive messages")
    pause.add_argument("--resume", action="store_true", help="switch the kill switch OFF")
    pause.add_argument("--status", action="store_true", help="only show the current state")
    worker = sub.add_parser("worker", help="run background roles without the HTTP server")
    worker.add_argument("--roles", default=None, help="api,task,voice,proactive,batch (CSV)")
    sub.add_parser("chat")
    sub.add_parser("init-env", help="create .env from .env.example with fresh random secrets")
    sub.add_parser("doctor", help="read-only, free checks for the laptop live test")
    live = sub.add_parser("livecall", help="place ONE real test call to an allow-listed number")
    live.add_argument("--to", required=True, help="your own phone, E.164 e.g. +919812345678")
    live.add_argument("--goal", default=None)
    live.add_argument("--max-seconds", type=int, default=180)
    live.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    live.add_argument("--simulate", action="store_true", help="no network: simulated business")
    live.add_argument("--on-behalf-of", default="the Friday founder")
    listen = sub.add_parser(
        "listen", help="front door: link the Vobiz number to Friday and answer incoming calls"
    )
    listen.add_argument("--simulate", action="store_true",
                        help="offline: simulated callers + a simulated Vobiz account")
    listen.add_argument("--restore", action="store_true",
                        help="only put the Vobiz number's previous link back (after a crash)")
    listen.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    from friday.quality.cli import register as register_quality

    register_quality(sub)  # `friday review` / `friday eval` (docs/QUALITY_LOOP.md)
    load = sub.add_parser("loadtest", help="S-11: N users, M concurrent simulated calls")
    load.add_argument("--users", type=int, default=100)
    load.add_argument("--calls", type=int, default=20, help="max concurrent calls in flight")
    load.add_argument("--dup-rate", type=float, default=0.1, help="share of duplicated webhooks")
    load.add_argument("--timeout", type=float, default=300.0, help="per-journey timeout, s")
    load.add_argument("--roles", default="api,task", help="roles in the one process")
    load.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "init-env":
        from friday.pilot import init_env

        return init_env()
    if args.cmd == "eval":  # offline scenarios: never reads .env unless --live
        from friday.quality.cli import run_eval_command

        return run_eval_command(args, Settings)
    settings = Settings()
    setup_logging(settings.log_level, settings.log_json)
    if args.cmd == "review":
        from friday.quality.cli import run_review_command

        return run_review_command(args, settings)

    if args.cmd == "check":
        rc = _check(settings)
        if args.live:
            from friday.voice.telephony.vobiz_probe import run_live_check

            rc = run_live_check(settings) or rc
        return rc
    if args.cmd == "doctor":
        from friday.pilot import doctor

        return asyncio.run(doctor(settings))
    if args.cmd == "livecall":
        from friday.pilot import run_livecall

        try:
            return asyncio.run(
                run_livecall(
                    settings, args.to, goal=args.goal, max_seconds=args.max_seconds,
                    yes=args.yes, simulate=args.simulate, on_behalf_of=args.on_behalf_of,
                )
            )
        except KeyboardInterrupt:
            print("\nStopped by you (Ctrl+C).")
            return 130
    if args.cmd == "listen":
        from friday.pilot import run_listen

        setup_logging("WARNING", settings.log_json)  # plain-language output, not engineer logs

        try:
            return asyncio.run(
                run_listen(settings, simulate=args.simulate, restore_only=args.restore,
                           seconds=args.seconds)
            )
        except KeyboardInterrupt:
            print("\nStopped by you (Ctrl+C).")
            return 130
    if args.cmd == "initdb":
        asyncio.run(_initdb(settings))
        return 0
    if args.cmd == "pause":
        return _pause(settings, resume=args.resume, status_only=args.status)
    if args.cmd == "serve":
        import uvicorn

        from friday.api.app import create_app

        container = Container(settings)
        install_pause_guard(container)  # wraps instance methods; no-op until `friday pause`
        uvicorn.run(create_app(container), host=settings.host, port=settings.port)
        asyncio.run(container.aclose())
        return 0
    if args.cmd == "worker":
        if args.roles:
            settings = settings.model_copy(
                update={"roles": [r.strip() for r in args.roles.split(",") if r.strip()]}
            )
        asyncio.run(_worker(settings))
        return 0
    if args.cmd == "loadtest":
        setup_logging("ERROR", False)
        result = asyncio.run(
            _loadtest(
                args.users, args.calls, args.dup_rate, args.timeout, args.roles.split(",")
            )
        )
        if args.json:
            import json

            print(json.dumps(result, indent=2, default=str))
        else:
            _print_load(result)
        return 0 if result["pass"] else 1
    if args.cmd == "chat":
        try:
            chat = importlib.import_module("friday.channels.cli")
        except ModuleNotFoundError:
            print("simulator chat not implemented yet (friday/channels/cli.py:main)")
            return 1
        return int(chat.main() or 0)
    return 2


if __name__ == "__main__":
    sys.exit(main())
