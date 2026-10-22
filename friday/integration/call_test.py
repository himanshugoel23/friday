"""``friday consumer call-test``: ONE test call from Friday to the founder's allow-listed phone.

It runs the whole consumer path with the real parts: request -> brief -> exact opening line (W2
line provider) -> approval (you type YES) -> W1 gate -> W1 orchestrator -> W2 live engine on the
production ``ConsumerTelephonyFactory`` (a real Sarvam/Vobiz call) -> W1 report. Then it prints a
summary and the transcript path.

* ``--to`` must be on ``FRIDAY_PILOT_ALLOWED_NUMBERS`` (omitted: the first allow-listed number).
  Nothing else is ever dialled. Numbers are printed masked to the last two digits.
* ``--dry-run`` runs everything except the dial, on a simulated callee persona, an in-memory
  database and a fake clock: it needs no phone, no network and no keys.
* No automatic retry: a test call that is not answered is not redialled. A request that would only
  be dialled later (outside the calling window) is cancelled, never left queued.
* The report is printed here; it is only sent on WhatsApp with ``--whatsapp-report``.

All printed lines live in friday/integration/copy.py (``CALL_TEST``, pending approval).
UNVERIFIED on a live call.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.calls.models import CalleeKind, CallStatus, Limits, PurposeKind
from friday.calls.settings import CallsSettings
from friday.calls.understand import Draft
from friday.core.clock import IST, FakeClock
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.core.models import ReplyButton, User, UserStatus, normalize_phone
from friday.integration.copy import cli_line
from friday.integration.telephony import (
    DEFAULT_LOG_DIR,
    CallLog,
    ConsumerTelephonyFactory,
    mask2,
    scrub_text,
)

log = get_logger(__name__)

DRY_NUMBER = "+919800000099"  # invented: the dry run's callee when nothing is allow-listed
DRY_USER_PHONE = "+919800000001"  # invented
DEFAULT_PERSONA = "friendly_elder"
MIN_SECONDS = 30

# who -> (W1 callee kind, relationship word the brief carries, name Friday addresses)
WHO: dict[str, tuple[CalleeKind, str, str | None]] = {
    "family": (CalleeKind.FAMILY_FRIEND, "mother", "Mummy"),
    "friend": (CalleeKind.FAMILY_FRIEND, "friend", None),
    "provider": (CalleeKind.PROVIDER, "service provider", None),
}


@dataclass
class Options:
    to: str | None = None
    who: str = "friend"
    goal: str | None = None
    name: str | None = None  # how the callee hears the user (disclosure line)
    callee_name: str | None = None
    max_seconds: int | None = None
    dry_run: bool = False
    persona: str = DEFAULT_PERSONA
    whatsapp_report: bool = False
    state_dir: Path | None = None


# ----------------------------------------------------------------------------- small helpers
class _Capture:
    """Stands in for the user's WhatsApp: keeps what Friday would send; forwards only on request."""

    def __init__(self, real: Any = None, forward: bool = False) -> None:
        self.real, self.forward = real, forward
        self.messages: list[tuple[str, list[str]]] = []

    async def send(
        self, user_id: str, text: str, buttons: Sequence[ReplyButton] = (), *, urgent: bool = False
    ) -> None:
        self.messages.append((text, [b.title for b in buttons]))
        if self.forward and self.real is not None:
            await self.real.send(user_id, text, buttons, urgent=urgent)


class _InlineTasks:
    """Task port that queues nothing: the CLI runs the one attempt itself, so no job can fire
    later (for example when the service starts again)."""

    def __init__(self) -> None:
        self.created: list[str] = []

    async def create(self, *, key: str, request: Any, run_at: datetime, parent_task_id=None) -> str:  # noqa: ANN001
        self.created.append(key)
        return f"inline:{key}"

    async def cancel(self, task_id: str) -> None:
        return None


@dataclass
class World:
    c: Any
    orch: Any
    factory: ConsumerTelephonyFactory
    settings: Settings
    clock: Any
    user_phone: str
    cleanup: Callable[[], Any]
    real: bool


def _refuse(out: Callable[[str], None], key: str, **fmt: object) -> int:
    out(cli_line("refuse", why=cli_line(key, **fmt)))
    return 2


def _first(values: Sequence[str]) -> str | None:
    return values[0] if values else None


def resolve_target(
    to: str | None, allow: Sequence[str], *, dry_run: bool
) -> tuple[str | None, str | None]:
    """(number, refusal key). The number must be on the allow-list; nothing else is ever dialled."""
    if to:
        try:
            number = normalize_phone(to, "+91")
        except ValueError:
            return None, "why_bad_number"
    else:
        number = _first(allow) or (DRY_NUMBER if dry_run else None)
        if number is None:
            return None, "why_no_allowlist"
    if allow:
        return (number, None) if number in set(allow) else (None, "why_not_allowed")
    if dry_run and number == DRY_NUMBER:
        return number, None
    return None, "why_no_allowlist"


def preflight(settings: Settings, cs: CallsSettings, seconds: int, *, dry_run: bool) -> str | None:
    """Reasons a REAL call must be refused before anything is built (key of CALL_TEST)."""
    from friday.pause import is_paused

    if not MIN_SECONDS <= seconds <= cs.max_call_seconds:
        return "why_seconds"
    if dry_run:
        return None
    if not settings.consumer_calls_enabled:
        return "why_switch_off"
    if not settings.is_live:
        return "why_not_live"
    if not settings.is_pilot:
        return "why_not_pilot"
    if is_paused(settings) or not cs.enabled:
        return "why_paused"
    return None


def _percentile(values: list[float], pct: float) -> float | None:
    from friday.integration.telephony import percentile

    return percentile(values, pct)


# ----------------------------------------------------------------------------- worlds
async def _dry_world(settings: Settings, to: str, persona: str, state_dir: Path) -> World:
    from friday.core.container import Container
    from friday.db import Database
    from friday.integration.sim import PersonaTelephony
    from friday.integration.telephony import PersonaLineOpener
    from friday.integration.wiring import build_stack

    clock = FakeClock(datetime(2026, 1, 5, 10, 0, tzinfo=IST))
    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=clock)
    c.override_db(db)
    c.install_field_cipher()
    opener = PersonaLineOpener(PersonaTelephony({to: persona}))

    def line(**parts: Any) -> ConsumerTelephonyFactory:
        return ConsumerTelephonyFactory(
            settings=settings,
            opener=opener,
            simulated=True,
            clock=clock,
            log_dir=state_dir,
            **parts,
        )

    async def send(user_id: str, text: str, buttons: Any) -> None:
        return None  # the CLI replaces the orchestrator's notifier; nothing is ever sent

    router = build_stack(
        settings=settings, clock=clock, repos=c.repos, send=send, queue=c.get("job_queue"),
        consumer_line=line,
    )  # fmt: skip
    assert router is not None and router.calls is not None

    async def cleanup() -> None:
        from friday.core.crypto import set_field_cipher

        await c.aclose()
        set_field_cipher(None)

    orch = router.calls.orchestrator
    return World(c, orch, orch.engine.factory, settings, clock, DRY_USER_PHONE, cleanup, False)


async def _real_world(settings: Settings, out: Callable[[str], None]) -> World | int:
    """The server's own container, with the web app served in this process (Vobiz calls back into
    it for the answer and the audio stream), exactly like ``friday livecall``."""
    import uvicorn

    from friday.api.app import create_app
    from friday.core.container import Container
    from friday.pilot import _get

    c = Container(settings)
    app = create_app(c, background=False, fast_pin_hash=True)
    cfg = uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning")
    server = uvicorn.Server(cfg)
    server_task = asyncio.create_task(server.serve())

    async def cleanup() -> None:
        server.should_exit = True
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(server_task, timeout=10)
        rt = getattr(app.state, "runtime", None)
        if rt is not None:
            with contextlib.suppress(Exception):
                await rt.stop()
        with contextlib.suppress(Exception):
            await c.aclose()

    for _ in range(100):
        if server.started or server_task.done():
            break
        await asyncio.sleep(0.1)
    if not server.started:
        out(cli_line("server_failed", port=settings.port))
        await cleanup()
        return 2
    out(cli_line("server_up", port=settings.port))
    base = settings.public_base_url.rstrip("/")
    try:
        reachable = (await _get(base + "/health")).status_code == 200
    except Exception:  # noqa: BLE001
        reachable = False
    if not reachable:
        out(cli_line("server_unreachable", base=base))
        await cleanup()
        return 2
    router = c.get("consumer")
    factory = getattr(getattr(getattr(router, "calls", None), "orchestrator", None), "engine", None)
    factory = getattr(factory, "factory", None)
    if not isinstance(factory, ConsumerTelephonyFactory):
        out(cli_line("refuse", why=cli_line("why_not_pilot")))
        await cleanup()
        return 2
    return World(c, router.calls.orchestrator, factory, settings, c.clock, "", cleanup, True)


# ----------------------------------------------------------------------------- the flow
async def _user_for(w: World, phone: str, out: Callable[[str], None]) -> User:
    users = w.c.repos.users
    user = await users.get_by_phone(phone)
    if user is None:
        user = await users.add(User(phone=phone, status=UserStatus.ACTIVE))
        if w.real:
            out(cli_line("user_created"))
    return user


def _print_plan(
    out: Callable[[str], None],
    *,
    to: str,
    who: str,
    brief: Any,
    default_goal: bool,
    seconds: int,
    cost: float,
    from_label: str,
    recording: bool,
) -> None:
    out("")
    out(cli_line("head_plan"))
    out(cli_line("plan_to", to=mask2(to), who=who))
    key = "plan_goal_default" if default_goal else "plan_goal"
    out(cli_line(key, goal=scrub_text(brief.goal)))
    if brief.must_say:
        out(cli_line("plan_say", items="; ".join(brief.must_say)))
    if brief.ask_list:
        out(cli_line("plan_ask", items="; ".join(brief.ask_list)))
    out(cli_line("plan_opening"))
    out(cli_line("plan_opening_line", line=brief.opening_line))
    out(cli_line("plan_from", from_=from_label))
    out(cli_line("plan_max", seconds=seconds))
    out(cli_line("plan_cost", cost=cost))
    out(
        cli_line("plan_recording", state=cli_line("recording_on" if recording else "recording_off"))
    )


def print_summary(
    out: Callable[[str], None],
    *,
    log_: CallLog | None,
    outcome: Any,
    safety: int,
    cost: float,
) -> None:
    out("")
    out(cli_line("head_summary"))
    out(cli_line("sum_dial", v=log_.dial_status if log_ else "not dialled"))
    duration = round(outcome.duration_s) if outcome is not None else 0
    out(cli_line("sum_duration", v=duration))
    out(cli_line("sum_turns", v=log_.turns if log_ else 0))
    out(cli_line("sum_langs", v=", ".join(log_.languages) if log_ and log_.languages else "n/a"))
    gaps = [float(g) for g in (log_.reply_gaps_ms if log_ else [])]
    if gaps:
        out(
            cli_line(
                "sum_gap",
                p50=round(_percentile(gaps, 50) or 0),
                p95=round(_percentile(gaps, 95) or 0),
                n=len(gaps),
            )  # fmt: skip
        )
    else:
        out(cli_line("sum_gap_none"))
    out(cli_line("sum_safety", v=safety if safety else cli_line("sum_none")))
    out(cli_line("sum_outcome", v=outcome.status.value if outcome is not None else "none"))
    out(cli_line("sum_cost", v=cost))
    if log_ and log_.transcript_path:
        out(cli_line("sum_transcript", v=log_.transcript_path))
    if log_ and log_.log_path:
        out(cli_line("sum_log", v=log_.log_path))
    out(cli_line("send_back"))


def estimate_cost(seconds: float) -> float:
    from friday.pilot import estimate_cost_inr

    return estimate_cost_inr(seconds)


async def run_call_test(
    opts: Options,
    *,
    settings: Settings | None = None,
    out: Callable[[str], None] = print,
    ask: Callable[[str], str] = input,
) -> int:
    dry = opts.dry_run
    base = settings or (Settings(_env_file=None) if dry else Settings())
    cs = CallsSettings()
    state_dir = opts.state_dir or DEFAULT_LOG_DIR
    kind, relationship, default_name = WHO[opts.who]

    to, why = resolve_target(opts.to, base.pilot_allowed_numbers, dry_run=dry)
    if to is None:
        return _refuse(out, why or "why_no_allowlist", to=mask2(opts.to))
    seconds = opts.max_seconds or cs.test_call_seconds
    if (why := preflight(base, cs, seconds, dry_run=dry)) is not None:
        return _refuse(out, why, low=MIN_SECONDS, high=cs.max_call_seconds)
    if not dry:
        for problem in base.live_problems():
            return _refuse(out, "why_problem", problem=problem)

    if dry:
        settings_ = base.model_copy(
            update={
                "mode": "simulator",
                "env": "dev",
                "profile": "pilot",
                "database_url": "sqlite+aiosqlite:///:memory:",
                "consumer_calls_enabled": True,
                "pilot_allowed_numbers": [to],
                "pilot_block_business_calls": True,
                "call_record": False,
                "anthropic_api_key": None,
                "sarvam_api_key": None,
            }  # fmt: skip
        )
        out(cli_line("banner_dry", persona=opts.persona))
    else:
        settings_ = base
        out(cli_line("banner_real", to=mask2(to)))

    lock: Any = None
    world: World | None = None
    request = None
    orch = None
    try:
        if not dry:
            from friday.pilot import single_call_lock

            try:
                lock = single_call_lock(state_dir, stale_after_s=seconds + 300)
                lock.__enter__()
            except RuntimeError as e:
                out(cli_line("refuse", why=str(e)))
                return 2
            built = await _real_world(settings_, out)
            if isinstance(built, int):
                return built
            world = built
        else:
            world = await _dry_world(settings_, to, opts.persona, state_dir)
        orch = world.orch
        user = await _user_for(world, to if world.real else world.user_phone, out)
        profile = await world.c.repos.profiles.get_or_default(user.id)
        display = opts.name or profile.name
        default_goal = not opts.goal
        goal = opts.goal or cli_line("test_goal")
        draft = Draft(
            callee_ref=opts.callee_name or default_name, callee_kind=kind, kind_confident=True,
            purpose=goal, purpose_kind=PurposeKind.INFORM, language="hinglish",
            limits=Limits(max_duration_s=seconds), raw_text=goal,
        )  # fmt: skip
        request, brief, _ = await orch.create_from_draft(
            draft, user=user, message_id=f"calltest:{secrets.token_hex(6)}",
            callee_name=opts.callee_name or default_name, callee_number=to, number_confirmed=True,
            kind=kind, relationship=relationship, user_display_name=display,
        )  # fmt: skip
        fresh, _prompt = await orch.approval.prepare(request, brief)  # the exact opening line
        await orch.store.save_brief(fresh)

        decision = await orch.gate.decide(request, fresh, user, world.clock.now())
        blockers = [r for r in decision.reasons if r != "approval_missing"]
        if decision.verdict.value == "deny" or blockers:
            code = "why_window" if blockers == ["outside_window"] else "why_gate"
            out(cli_line("refuse", why=cli_line(code, reasons=",".join(decision.reasons))))
            await orch.cancel(request.id)
            return 2

        ids = list(settings_.sarvam_caller_ids or settings_.friday_numbers or [])
        from_label = "(simulated)" if dry else (mask2(ids[0]) if ids else "(chosen at dial time)")
        cost = estimate_cost(seconds)
        _print_plan(
            out, to=to, who=opts.who, brief=fresh, default_goal=default_goal, seconds=seconds,
            cost=cost, from_label=from_label, recording=bool(settings_.call_record),
        )  # fmt: skip
        if ask(cli_line("ask_yes")).strip() != "YES":
            out(cli_line("cancelled"))
            await orch.cancel(request.id)
            return 1

        approved = orch.approval.approve(fresh, fresh.content_hash()[:8], world.clock.now())
        await orch.store.save_brief(approved)
        capture = _Capture(orch.notifier, forward=opts.whatsapp_report)
        orch.notifier, orch.tasks, orch.max_attempts = capture, _InlineTasks(), 1
        submitted = await orch.submit(request.id)
        if submitted.status != CallStatus.SCHEDULED:
            out(cli_line("not_dialled", why=submitted.status.value))
            return 2
        out(cli_line("placing"))
        outcome = await orch.execute(request.id)
        after = await orch.store.get_request(request.id)
        if outcome is None or (after is not None and after.status == CallStatus.SCHEDULED):
            await orch.cancel(request.id)  # never leave a later dial queued
            out(cli_line("not_dialled", why="not run"))
            return 2
        log_ = next((x for x in reversed(world.factory.logs)), None)
        results = getattr(orch.engine, "results", [])
        safety = (log_.safety_blocks if log_ else 0) or (
            sum(
                1 for e in results[-1].events if e.kind in {"guard", "hard_stop", "policy_rejected"}
            )
            if results
            else 0
        )
        print_summary(
            out, log_=log_, outcome=outcome, safety=safety,
            cost=estimate_cost(outcome.duration_s) if log_ and log_.turns else 0.0,
        )  # fmt: skip
        out("")
        out(
            cli_line(
                "head_report",
                sent=cli_line("report_sent" if opts.whatsapp_report else "report_not_sent"),
            )
        )
        for text, buttons in capture.messages:
            for ln in scrub_text(text).splitlines():
                out(f"  | {ln}")
            if buttons:
                out("  | [" + "] [".join(buttons) + "]")
        return 0
    except KeyboardInterrupt:
        out(cli_line("stopped"))
        return 130
    finally:
        if request is not None and orch is not None:
            with contextlib.suppress(Exception):
                req = await orch.store.get_request(request.id)
                if (
                    req is not None
                    and not req.status.is_terminal
                    and req.status
                    in (
                        CallStatus.CALLING,
                        CallStatus.SCHEDULED,
                        CallStatus.AWAITING_APPROVAL,
                    )
                ):
                    await orch.cancel(request.id)  # an interrupted call is closed, not redialled
        if world is not None:
            with contextlib.suppress(Exception):
                await world.cleanup()
        if lock is not None:
            lock.__exit__(None, None, None)


# ----------------------------------------------------------------------------- CLI glue
def add_arguments(sub: Any) -> None:
    p = sub.add_parser(
        "call-test",
        help="place ONE test call from Friday to your own allow-listed phone (needs typing YES)",
    )
    p.add_argument("--to", default=None, help="must be on the allow-list (default: the first one)")
    p.add_argument("--who", choices=sorted(WHO), default="friend")
    p.add_argument("--goal", default=None, help="the message of the call, in your own words")
    p.add_argument("--name", default=None, help="how the callee hears your name")
    p.add_argument("--callee-name", default=None, help="how Friday addresses the callee")
    p.add_argument(
        "--max-seconds", type=int, default=None, help="at most FRIDAY_CALLS_TEST_CALL_SECONDS"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="everything except the dial (simulated callee)"
    )
    p.add_argument("--persona", default=DEFAULT_PERSONA, help="dry run only: the simulated callee")
    p.add_argument(
        "--whatsapp-report", action="store_true", help="also send the report on WhatsApp"
    )


def run_command(args: argparse.Namespace) -> int:
    opts = Options(
        to=args.to, who=args.who, goal=args.goal, name=args.name, callee_name=args.callee_name,
        max_seconds=args.max_seconds, dry_run=args.dry_run, persona=args.persona,
        whatsapp_report=args.whatsapp_report,
    )  # fmt: skip
    try:
        return asyncio.run(run_call_test(opts))
    except KeyboardInterrupt:
        print("\n" + cli_line("stopped"))
        return 130
