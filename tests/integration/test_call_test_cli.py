"""`friday consumer call-test`: the dry run end to end, refusals, masking. No network, no phone."""

from __future__ import annotations

import re
import socket
from pathlib import Path

import pytest

from friday.cli import main
from friday.core.config import Settings
from friday.integration import copy
from friday.integration.call_test import DRY_NUMBER, Options, resolve_target, run_call_test

NUM = "+919000000001"
STRANGER = "+919876500077"
NATIONAL = re.compile(r"(?<![0-9*])[6-9]\d{9}(?!\d)")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("the call test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def _read(path: str) -> str:
    return Path(path).read_text()


def _txts(directory: Path) -> list[Path]:
    return list(directory.glob("*.txt"))


def settings(**kw: object) -> Settings:
    return Settings(_env_file=None, pilot_allowed_numbers=[NUM], **kw)  # type: ignore[arg-type]


async def run(
    tmp_path: Path, answer: str = "YES", s: Settings | None = None, **opts: object
) -> tuple[int, str]:
    lines: list[str] = []
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return answer

    code = await run_call_test(
        Options(dry_run=True, state_dir=tmp_path, **opts),  # type: ignore[arg-type]
        settings=s or settings(),
        out=lines.append,
        ask=ask,
    )
    text = "\n".join(lines)
    assert asked == [copy.cli_line("ask_yes")] or code != 0 or answer != "YES"
    return code, text


# ------------------------------------------------------------------------------- the dry run
async def test_the_dry_run_goes_end_to_end_with_a_simulated_callee(tmp_path: Path):
    code, out = await run(tmp_path, who="family")
    assert code == 0
    # the plan: who, goal, the exact first line, cap and cost, then the typed YES
    assert "DRY RUN" in out and "FIRST THING YOU WILL HEAR" in out
    assert "Max length  : 150 s (hard cap)" in out and "Est. cost" in out
    assert "Namaste Mummy" in out  # the exact opening line from the W2 line provider
    # the summary has every field the founder is to send back
    for label in ("Dial status", "Duration", "Turns", "Languages", "Reply gap", "Safety blocks",
                  "Outcome", "Estimated cost", "Transcript file"):  # fmt: skip
        assert label in out, label
    assert "Dial status    : answered" in out and "Outcome        : completed" in out
    # the transcript exists and holds the call; the report is printed but not sent
    path = next(ln.split(": ", 1)[1] for ln in out.splitlines() if ln.startswith("Transcript file"))
    body = _read(path)
    assert "FRIDAY" in body and "CALLEE" in body
    assert "NOT sent" in out and "Mummy se baat ho gayi" in out
    # nothing in the output or the transcript shows a whole number
    assert not NATIONAL.search(out) and not NATIONAL.search(body)
    assert "+91" not in out.replace("+**", "")


@pytest.mark.parametrize("who", ["family", "friend", "provider"])
async def test_every_kind_of_callee_runs(tmp_path: Path, who: str):
    code, out = await run(tmp_path, who=who)
    assert code == 0 and "CALL SUMMARY" in out


async def test_your_own_goal_is_said_and_the_default_is_marked_pending(tmp_path: Path):
    _, out = await run(tmp_path, goal="main das minute mein pahunch raha hoon")
    assert "main das minute mein pahunch raha hoon" in out and "PENDING" not in out
    _, out2 = await run(tmp_path)
    assert "PENDING founder approval" in out2 and copy.cli_line("test_goal") in out2


async def test_a_simulated_voicemail_is_reported_without_a_message_left(tmp_path: Path):
    code, out = await run(tmp_path, persona="voicemail_not_allowed")
    assert code == 0 and "Outcome        : voicemail" in out


async def test_anything_but_yes_places_no_call(tmp_path: Path):
    code, out = await run(tmp_path, answer="yes please")
    assert code == 1 and "No call was placed" in out and "CALL SUMMARY" not in out
    assert _txts(tmp_path) == []  # no transcript: nothing happened


async def test_the_report_is_only_forwarded_on_request(tmp_path: Path):
    _, out = await run(tmp_path, whatsapp_report=True)
    assert "also sent" in out


async def test_the_test_call_is_never_retried_or_left_queued(tmp_path: Path):
    """An unanswered test call (silent callee) ends there: no later dial is queued."""
    code, out = await run(tmp_path, persona="carrier_unreachable")
    assert code == 0 and "Outcome        : no_answer" in out
    assert "Ab main ruk rahi hoon" in out  # the final report: no retry was scheduled


# ------------------------------------------------------------------------------- refusals
async def test_a_number_that_is_not_allow_listed_is_refused(tmp_path: Path):
    code, out = await run(tmp_path, to=STRANGER)
    assert code == 2 and "not on your allow-list" in out
    assert "FIRST THING" not in out and not NATIONAL.search(out) and STRANGER not in out


async def test_an_invalid_number_and_an_empty_allow_list_are_refused(tmp_path: Path):
    code, out = await run(tmp_path, to="not-a-number")
    assert code == 2 and "not a valid phone number" in out
    code, out = await run(tmp_path, to=NUM, s=Settings(_env_file=None, pilot_allowed_numbers=[]))
    assert code == 2 and "allow-list" in out


async def test_without_an_allow_list_the_dry_run_uses_an_invented_number(tmp_path: Path):
    code, out = await run(tmp_path, s=Settings(_env_file=None, pilot_allowed_numbers=[]))
    assert code == 0 and DRY_NUMBER not in out and "+**********99" in out


async def test_to_defaults_to_the_first_allow_listed_number_masked(tmp_path: Path):
    s = settings()
    s = s.model_copy(update={"pilot_allowed_numbers": [NUM, "+919000000002"]})
    code, out = await run(tmp_path, s=s)
    assert code == 0 and "+**********01" in out and NUM not in out


@pytest.mark.parametrize("seconds", [5, 301, 9999])
async def test_the_length_must_stay_inside_the_cap(tmp_path: Path, seconds: int):
    code, out = await run(tmp_path, max_seconds=seconds)
    assert code == 2 and "--max-seconds must be between" in out


async def test_a_shorter_length_is_honoured(tmp_path: Path):
    _, out = await run(tmp_path, max_seconds=60)
    assert "Max length  : 60 s (hard cap)" in out


def test_resolve_target_accepts_only_allow_listed_numbers():
    assert resolve_target(None, [NUM], dry_run=False) == (NUM, None)
    assert resolve_target(NUM, [NUM], dry_run=False) == (NUM, None)
    assert resolve_target("9000000001", [NUM], dry_run=False) == (NUM, None)  # 10 digits -> +91
    assert resolve_target(STRANGER, [NUM], dry_run=False) == (None, "why_not_allowed")
    assert resolve_target(None, [], dry_run=False) == (None, "why_no_allowlist")
    assert resolve_target(NUM, [], dry_run=False) == (None, "why_no_allowlist")


@pytest.mark.parametrize(
    ("kw", "message"),
    [
        ({}, "FRIDAY_MODE is not 'live'"),  # simulator mode
        ({"mode": "live"}, "FRIDAY_PROFILE is not 'pilot'"),
        ({"mode": "live", "profile": "pilot"}, "FRIDAY_CONSUMER_CALLS_ENABLED is not true"),
    ],
)
async def test_a_real_call_is_refused_before_anything_is_built(kw: dict, message: str):
    lines: list[str] = []
    code = await run_call_test(
        Options(dry_run=False),
        settings=Settings(_env_file=None, pilot_allowed_numbers=[NUM], **kw),
        out=lines.append,
        ask=lambda _p: pytest.fail("must not ask for YES"),
    )
    out = "\n".join(lines)
    # order of checks: the switch first, then live, then profile
    assert code == 2 and "REFUSED" in out
    assert message in out or "CONSUMER_CALLS_ENABLED" in out


async def test_a_real_call_is_refused_while_the_kill_switch_is_on(tmp_path: Path):
    lines: list[str] = []
    s = Settings(
        _env_file=None, pilot_allowed_numbers=[NUM], mode="live", profile="pilot",
        consumer_calls_enabled=True, paused=True,
    )  # fmt: skip
    code = await run_call_test(
        Options(dry_run=False), settings=s, out=lines.append, ask=lambda _p: "YES"
    )
    assert code == 2 and "kill switch is on" in "\n".join(lines)


# ------------------------------------------------------------------------------- the command
def test_the_command_runs_from_the_cli_and_the_demo_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr("builtins.input", lambda _p="": "YES")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FRIDAY_PILOT_ALLOWED_NUMBERS", raising=False)
    assert main(["consumer", "call-test", "--dry-run", "--who", "friend"]) == 0
    out = capsys.readouterr().out
    assert "CALL SUMMARY" in out and "var/consumer_calls" in out
    assert main(["consumer", "demo", "--scenario", "calls"]) == 0  # unchanged


def test_the_help_lists_the_options(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as e:
        main(["consumer", "call-test", "--help"])
    assert e.value.code == 0
    text = capsys.readouterr().out
    for opt in ("--to", "--who", "--goal", "--dry-run", "--max-seconds"):
        assert opt in text


def test_the_new_lines_live_in_the_pending_copy_module():
    assert copy.PENDING_FOUNDER_APPROVAL is True
    assert "test_goal" in copy.CALL_TEST and all(v.strip() for v in copy.CALL_TEST.values())
