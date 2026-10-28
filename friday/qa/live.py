# ruff: noqa: E501
"""The backends that really place the QA calls, and the Chat Lab backend for the chat scenarios.

``LiveBackend`` REUSES the production paths, nothing is re-implemented:

  playbook   ``friday.pilot.run_livecall`` with a playbook (the vendor archetypes)
  goal       ``friday.pilot.run_livecall`` with a plain goal (trip hotel call, refund, care)
  consumer   ``friday.integration.call_test.run_call_test`` (the 'call someone for me' path)
  speak      a real call that plays the receptionist's real lines
  ring       a real ring (forwarding test)
  urgent     ``friday.urgent.telephony.TelephonyOwnNumberCaller`` (the escalation dial)

Every backend refuses unless a QA session is active (``QaGuard.session``) and the number is the
allow-listed one. The number is never printed: everything emitted goes through ``scrub_text``.

``SubprocessBackend`` is what the web page uses: it runs ``friday qa exec`` so each call has its own
process, its own in-process Friday server for the Vobiz callbacks (the front door service is stopped
by deploy/qa-live.sh while QA runs) and can be hung up with Ctrl-C (SIGINT).

UNVERIFIED on a live call: nobody has placed a QA call yet. Tests use fakes only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import signal
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from friday.integration.telephony import scrub_text
from friday.qa import override
from friday.qa.config import APPROVAL_PHRASE
from friday.qa.models import CallReport, CallSpec, Emit
from friday.qa.scenarios import Scenario

REPORT_PREFIX = "QA_REPORT "
SAMPLE_VENDORS = {
    "salon": ["Shreya Salon", "Glow Unisex Salon", "Looks Hair Studio"],
    "restaurant": ["Spice Route Restaurant", "Tandoor Tales", "Cafe Mocha"],
    "AC repair service": ["CoolCare AC Services", "Frost Air Solutions", "Sharma AC Repair"],
    "mobile phone shop": ["Sharma Mobiles", "Mobile World", "Gadget Hub"],
    "hotel": ["Hotel Example Palms", "Hotel Sunrise Inn", "The Grand Stay"],
    "cab service": ["Quick Cabs Gurugram", "Safe Ride Travels", "City Taxi Service"],
    "PG accommodation": ["Comfort PG for Men", "Green Nest PG", "Sai Residency PG"],
    "banquet hall": ["Royal Orchid Banquets", "Moti Mahal Banquet", "Celebration Lawns"],
}
_FALLBACK_VENDORS = ["Example Business One", "Example Business Two", "Example Business Three"]


def mask_lines(lines: Sequence[str]) -> list[str]:
    return [scrub_text(x) for x in lines]


# ----------------------------------------------------------------------------- the shortlist
async def shortlist(
    settings: Any, query: str, area: str, *, limit: int = 3, directory: Any = None
) -> dict[str, Any]:
    """A text-only shortlist of vendor names. Names, ratings and area only: never a phone number,
    and nothing in it is ever dialled (the call goes to the founder's own phone)."""
    note = ""
    try:
        if directory is None and getattr(settings, "google_places_api_key", None):
            from friday.core.container import Container

            directory = Container(settings).get("directory")
        if directory is not None:
            found = await directory.search(query, area, limit=limit * 2)
            items = [
                {"name": c.name, "rating": c.rating, "address": c.address or ""}
                for c in found
                if c.name
            ][:limit]
            if items:
                return {"source": "places", "items": items, "note": ""}
            note = "Places returned nothing."
    except Exception as e:  # noqa: BLE001 - a lookup problem must never block a QA run
        note = f"Places lookup failed ({type(e).__name__})."
    names = SAMPLE_VENDORS.get(query, _FALLBACK_VENDORS)[:limit]
    return {
        "source": "sample",
        "items": [{"name": n, "rating": None, "address": area} for n in names],
        "note": (note + " " if note else "") + "Sample names (not from Places).",
    }


# ----------------------------------------------------------------------------- helpers
def _parse_summary(lines: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ln in lines:
        if m := re.match(r"\s*Duration\s*:\s*(\d+)", ln):
            out["duration_s"] = float(m.group(1))
        elif m := re.match(r"\s*Dial status\s*:\s*(\S+)", ln):
            out["dial_status"] = m.group(1)
        elif m := re.match(r"\s*Outcome\s*:\s*(\S+)", ln):
            out["outcome"] = m.group(1)
        elif m := re.match(r"\s*Transcript file\s*:\s*(.+)$", ln):
            out["transcript_path"] = m.group(1).strip()
    return out


def read_transcript(path: str | None) -> list[dict[str, str]]:
    """The transcript file (numbers already masked by its writer) as [{who, text}]."""
    if not path:
        return []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, str]] = []
    for ln in text.splitlines():
        m = re.match(r"^\s*(?:[\d.]+s\s+)?([A-Za-z_ ]{2,16})(?:\s*\[[^\]]*\])?:\s*(.+)$", ln)
        if m:
            rows.append({"who": m.group(1).strip().lower(), "text": scrub_text(m.group(2))})
    return rows[:200]


def _status_from(dial: str | None, outcome: str | None, duration: float) -> str:
    d = (dial or "").lower()
    if d in {"busy", "no_answer", "voicemail"}:
        return "no_answer" if d != "busy" else "busy"
    if d == "failed":
        return "failed"
    return "completed" if duration > 0 or d == "answered" else "failed"


class LiveBackend:
    """Places the real QA call in THIS process (used by `friday qa exec`)."""

    def __init__(self, settings: Any, qa: Any) -> None:
        self.settings, self.qa = settings, qa

    # ------------------------------------------------------------------ entry
    async def run(self, spec: CallSpec, emit: Emit) -> CallReport:
        if override.active() is None:
            raise RuntimeError("QA calls run only inside QaGuard.session")
        if (
            spec.number not in set(self.settings.pilot_allowed_numbers)
            or len(self.settings.pilot_allowed_numbers) != 1
        ):
            raise RuntimeError("the number is not the one allow-listed number: not dialled")
        backend = spec.scenario.spec.get("backend")
        fn = getattr(self, f"_run_{backend}", None)
        if fn is None:
            raise RuntimeError(f"scenario {spec.scenario.id} has no call backend")
        return await fn(spec, emit)

    # ------------------------------------------------------------------ livecall paths
    def _playbook_args(self, spec: CallSpec) -> dict[str, Any]:
        sc = spec.scenario.spec
        service = str(sc.get("service") or "")
        args: dict[str, Any] = {
            "service": service.split(",")[0].strip(),
            "date_window": sc.get("date_window") or "",
            "salon_name": spec.vendor_name or None,
            "extra_inputs": dict(sc.get("inputs") or {}),
        }
        if "," in service:
            args["services"] = service
        return {k: v for k, v in args.items() if v}

    async def _livecall(
        self,
        spec: CallSpec,
        emit: Emit,
        *,
        playbook: str | None,
        goal: str | None,
        pb_args: dict[str, Any] | None,
    ) -> CallReport:
        from friday.pilot import run_livecall
        from friday.playbooks import model as pbm

        lines: list[str] = []

        def out(text: str) -> None:
            for part in str(text).splitlines() or [""]:
                lines.append(part)
                emit(scrub_text(part))

        pending = bool(spec.scenario.spec.get("pending"))
        if pending:
            pbm.use_pending_for_test()
        try:
            rc = await run_livecall(
                self.settings,
                spec.number,
                goal=goal,
                max_seconds=spec.seconds,
                yes=True,
                simulate=False,
                on_behalf_of=spec.first_name,
                out=out,
                playbook=playbook,
                playbook_args=pb_args,
            )
        finally:
            pbm.clear_pending_for_test()
        info = _parse_summary(lines)
        duration = float(info.get("duration_s", 0.0))
        path = info.get("transcript_path")
        refused = rc == 2 or any(x.startswith("REFUSED") or "will NOT place" in x for x in lines)
        status = (
            "refused"
            if refused
            else _status_from(info.get("dial_status"), info.get("outcome"), duration)
        )
        from friday.qa.safety import estimate_cost

        return CallReport(
            status=status,
            duration_s=duration,
            cost_inr=estimate_cost(max(duration, 10.0)) if not refused else 0.0,
            summary=f"{info.get('dial_status', 'n/a')} / {info.get('outcome', 'n/a')}",
            transcript=read_transcript(path),
            transcript_path=path,
            outcome=str(info.get("outcome", "")),
        )

    async def _run_playbook(self, spec: CallSpec, emit: Emit) -> CallReport:
        sc = spec.scenario.spec
        return await self._livecall(
            spec, emit, playbook=str(sc["playbook"]), goal=None, pb_args=self._playbook_args(spec)
        )

    async def _run_goal(self, spec: CallSpec, emit: Emit) -> CallReport:
        return await self._livecall(
            spec, emit, playbook=None, goal=str(spec.scenario.spec["goal"]), pb_args=None
        )

    # ------------------------------------------------------------------ consumer path
    async def _run_consumer(self, spec: CallSpec, emit: Emit) -> CallReport:
        from friday.integration.call_test import Options, run_call_test

        sc = spec.scenario.spec
        lines: list[str] = []

        def out(text: str) -> None:
            lines.append(str(text))
            emit(scrub_text(str(text)))

        opts = Options(
            to=spec.number,
            who=str(sc.get("who", "friend")),
            goal=str(sc.get("goal") or "") or None,
            name=spec.first_name,
            callee_name=str(sc.get("callee_name") or "") or None,
            max_seconds=spec.seconds,
        )
        rc = await run_call_test(
            opts, settings=self.settings, out=out, ask=lambda _p: "YES"
        )  # the approval phrase was already confirmed by the runner
        info: dict[str, Any] = {}
        for ln in lines:
            if m := re.search(r"Duration\D+(\d+)", ln):
                info["duration_s"] = float(m.group(1))
            if m := re.search(r"Dial status\D*:\s*(\S+)", ln):
                info["dial_status"] = m.group(1)
            if m := re.search(r"Outcome\D*:\s*(\S+)", ln):
                info["outcome"] = m.group(1)
            if m := re.search(r"(\S+consumer-call-\S+\.txt)", ln):
                info["transcript_path"] = m.group(1)
        duration = float(info.get("duration_s", 0.0))
        path = info.get("transcript_path")
        from friday.qa.safety import estimate_cost

        status = (
            "refused"
            if rc == 2
            else _status_from(info.get("dial_status"), info.get("outcome"), duration)
        )
        return CallReport(
            status=status,
            duration_s=duration,
            cost_inr=estimate_cost(max(duration, 10.0)) if status != "refused" else 0.0,
            summary="\n".join(scrub_text(x) for x in lines[-14:]),
            transcript=read_transcript(path),
            transcript_path=path,
            outcome=str(info.get("outcome", "")),
        )

    # ------------------------------------------------------------------ own-line calls
    @contextlib.asynccontextmanager
    async def serving(self, emit: Emit) -> AsyncIterator[Any]:
        """The Friday web app in this process, so Vobiz can call back during the call."""
        import uvicorn

        from friday.api.app import create_app
        from friday.core.container import Container
        from friday.pilot import _get

        s = self.settings
        c = Container(s)
        app = create_app(c, background=False, fast_pin_hash=True)
        server = uvicorn.Server(uvicorn.Config(app, host=s.host, port=s.port, log_level="warning"))
        task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started or task.done():
                    break
                await asyncio.sleep(0.1)
            if not server.started:
                raise RuntimeError(
                    f"Friday could not start on port {s.port} (is the front door still running?)"
                )
            try:
                reachable = (
                    await _get(s.public_base_url.rstrip("/") + "/health")
                ).status_code == 200
            except Exception:  # noqa: BLE001
                reachable = False
            if not reachable:
                raise RuntimeError(
                    "the public address is not reachable from the internet (FRIDAY_PUBLIC_BASE_URL)"
                )
            emit("Friday is serving; the public address answers.")
            yield c
        finally:
            server.should_exit = True
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(task, timeout=10)
            rt = getattr(app.state, "runtime", None)
            if rt is not None:
                with contextlib.suppress(Exception):
                    await rt.stop()
            with contextlib.suppress(Exception):
                await c.aclose()

    def _request(self, spec: CallSpec) -> Any:
        from friday.core.models import Language, OutboundCallRequest

        return OutboundCallRequest(
            to_phone=spec.number,
            task_id=spec.run_id,
            record=False,
            ring_timeout_s=self.settings.call_ring_timeout_s,
            max_duration_s=spec.seconds,
            language=Language.HINGLISH,
            metadata={"call_id": spec.run_id, "kind": "qa"},
        )

    async def _place(self, c: Any, spec: CallSpec) -> tuple[Any, Any]:
        leg = await c.get("telephony").place_call(self._request(spec))
        status = await leg.wait_for_answer(self.settings.call_ring_timeout_s)
        return leg, status

    async def _run_speak(self, spec: CallSpec, emit: Emit) -> CallReport:
        from friday.core.models import DialStatus, Language
        from friday.receptionist import lines as rl

        keys = tuple(spec.scenario.spec.get("keys", ()))
        slots = {"user": spec.first_name, "name": "Rohit", "reason": "meeting ka time"}
        transcript: list[dict[str, str]] = []
        async with self.serving(emit) as c:
            emit("Ringing your phone...")
            leg, status = await self._place(c, spec)
            try:
                if status != DialStatus.ANSWERED:
                    return CallReport(status="no_answer", summary=f"not answered ({status})")
                for key in keys:
                    text = rl.say(key, "hinglish", **slots)
                    if rl.LINE_STATUS != "APPROVED":
                        override.note_pending_line("receptionist", f"rcp.{key}.hinglish")
                    emit(f"Friday says [{key}]: {text}")
                    transcript.append({"who": "friday", "text": text})
                    await asyncio.wait_for(leg.speak(text, Language.HINGLISH), timeout=spec.seconds)
                    await asyncio.sleep(2.0)
                return CallReport(
                    status="completed",
                    summary=f"{len(keys)} lines played",
                    transcript=transcript,
                    duration_s=float(len(keys) * 8),
                    cost_inr=0.0,
                    outcome="played",
                )
            finally:
                with contextlib.suppress(Exception):
                    await leg.hangup()

    async def _run_ring(self, spec: CallSpec, emit: Emit) -> CallReport:
        from friday.core.models import DialStatus

        async with self.serving(emit) as c:
            emit("Ringing your phone (decline it to test forwarding)...")
            leg, status = await self._place(c, spec)
            try:
                if status == DialStatus.ANSWERED:
                    await asyncio.sleep(2.0)
                return CallReport(
                    status="completed" if status == DialStatus.ANSWERED else "no_answer",
                    summary=f"ring result: {status}",
                    outcome=str(status),
                )
            finally:
                with contextlib.suppress(Exception):
                    await leg.hangup()

    async def _run_urgent(self, spec: CallSpec, emit: Emit) -> CallReport:
        from friday.pause import is_paused
        from friday.urgent.models import RingResult
        from friday.urgent.telephony import TelephonyOwnNumberCaller

        async with self.serving(emit) as c:
            caller = TelephonyOwnNumberCaller(
                lambda: c.get("telephony"),
                self.settings,
                ring_timeout_s=self.settings.call_ring_timeout_s,
                max_seconds=min(45, spec.seconds),
                paused=lambda: is_paused(self.settings),
            )
            emit("Friday rings your phone now (the production escalation dial).")
            res = await caller.ring(
                user_id="qa",
                number=spec.number,
                line_key=str(spec.scenario.spec.get("line_key", "ring.urgent")),
                lang="hinglish",
                user_name=spec.first_name,
                dedupe_key=spec.run_id,
            )
        ok = res.result == RingResult.ANSWERED
        return CallReport(
            status="completed"
            if ok
            else ("refused" if res.result == RingResult.REFUSED else "no_answer"),
            summary=f"{res.result.value}: {res.detail}",
            outcome=res.result.value,
            duration_s=20.0 if ok else 0.0,
            cost_inr=0.0 if not ok else 3.0,
        )


# ----------------------------------------------------------------------------- in a subprocess
class SubprocessBackend:
    """Runs ``friday qa exec`` in a child process (what the web page uses)."""

    def __init__(
        self, base_cmd: Sequence[str] | None = None, env: dict[str, str] | None = None
    ) -> None:
        self.base_cmd = list(
            base_cmd
            or [
                sys.executable,
                "-c",
                "import sys; from friday.cli import main; sys.exit(main(sys.argv[1:]))",
            ]
        )
        self.env = env
        self.proc: asyncio.subprocess.Process | None = None

    def command(self, spec: CallSpec) -> list[str]:
        # the number is NOT on the command line: the child derives it from the allow-list
        cmd = [
            *self.base_cmd,
            "qa",
            "exec",
            spec.scenario.id,
            "--run-id",
            spec.run_id,
            "--seconds",
            str(spec.seconds),
            "--first-name",
            spec.first_name,
            "--approved",
            APPROVAL_PHRASE,
        ]
        if spec.vendor_name:
            cmd += ["--vendor", spec.vendor_name]
        if spec.area:
            cmd += ["--area", spec.area]
        return cmd

    async def run(self, spec: CallSpec, emit: Emit) -> CallReport:
        self.proc = await asyncio.create_subprocess_exec(
            *self.command(spec),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=self.env,
        )
        report: CallReport | None = None
        assert self.proc.stdout is not None
        async for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            if line.startswith(REPORT_PREFIX):
                with contextlib.suppress(ValueError):
                    report = CallReport.from_json(json.loads(line[len(REPORT_PREFIX) :]))
            elif line:
                emit(scrub_text(line))
        rc = await self.proc.wait()
        self.proc = None
        if report is None:
            return CallReport(
                status="failed", summary=f"the call process ended without a report (exit {rc})"
            )
        return report

    def hangup(self) -> None:
        """Ctrl-C the child: `run_livecall` hangs up and writes its transcript."""
        if self.proc is not None and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.send_signal(signal.SIGINT)


# ----------------------------------------------------------------------------- chat scenarios
class LabChat:
    """The chat scenarios on the Chat Lab engine (simulator only; never touches a real channel)."""

    def __init__(
        self, notes_path: Path | str = "var/qa/lab_notes.jsonl", world: Any = None
    ) -> None:
        self.notes_path, self._world = notes_path, world
        self._lock = asyncio.Lock()

    async def world(self) -> Any:
        if self._world is None:
            from friday.core.config import Settings
            from friday.lab.world import LabWorld

            self._world = await LabWorld.create(
                env=Settings(_env_file=None), notes_path=self.notes_path
            )
        return self._world

    async def close(self) -> None:
        if self._world is not None:
            await self._world.close()
            self._world = None

    async def run(self, scenario: Scenario, emit: Emit) -> CallReport:
        async with self._lock:
            w = await self.world()
            user = await w.new_user()
            transcript: list[dict[str, str]] = []
            for kind, content in scenario.messages:
                if kind == "voice":
                    msg, label = w.inbound_voice(user.phone, content), f"voice note: {content}"
                elif kind == "sample":
                    msg, label = w.inbound_sample(user.phone, content), f"file: {content}"
                else:
                    msg, label = w.inbound_text(user.phone, content), content
                emit(f"You ({kind}): {content}")
                transcript.append({"who": "you", "text": f"({kind}) {content}"})
                turn = await w.send_inbound(user.phone, msg, label)
                for o in turn.get("outputs", []):
                    text = o.get("text", "")
                    btn = f"  [{' | '.join(o['buttons'])}]" if o.get("buttons") else ""
                    emit(f"Friday: {text}{btn}")
                    transcript.append({"who": "friday", "text": text + btn})
            return CallReport(
                status="chat",
                summary=f"{len(scenario.messages)} message(s) sent on the simulator",
                transcript=transcript,
                outcome="chat",
            )
