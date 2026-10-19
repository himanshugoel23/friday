"""`friday consumer demo` runs offline, and the new text lives only in the pending copy module."""

from __future__ import annotations

import ast
import re
import socket
from pathlib import Path

import pytest

from friday.cli import main
from friday.integration import copy
from friday.integration.demo import run_demo

ROOT = Path(__file__).resolve().parents[2] / "friday" / "integration"


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    attempts: list[str] = []

    def refuse(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        attempts.append("connect")
        raise AssertionError("the demo tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    return attempts


async def test_the_demo_prints_both_scenarios_without_a_network(no_network):
    text = "\n".join(await run_demo("all"))
    assert no_network == []
    assert "OFFLINE DEMO" in text and "PENDING founder approval" in text
    assert "Call ka plan yeh hai" in text and "Mummy se baat ho gayi" in text  # scenario (a)
    assert "SBI Card Cashback use kijiye" in text and "Wajah:" in text  # scenario (d)
    assert "[EXAMPLE data, asli offer nahi]" in text  # invented rows are labelled as such
    assert "BSES" in text and "Paid" in text
    assert "+91" not in text and not re.search(r"(?<![0-9A-Za-z])[6-9]\d{9}(?!\d)", text)


def test_the_cli_command_exists_and_exits_zero(no_network, capsys):
    assert main(["consumer", "demo", "--scenario", "calls"]) == 0
    out = capsys.readouterr().out
    assert "a call to Mummy" in out and "Approve" in out


def test_the_copy_module_is_marked_pending_and_complete():
    assert copy.PENDING_FOUNDER_APPROVAL is True
    for key, variants in copy.LINES.items():
        assert set(variants) >= {"hinglish", "en"}, key
        assert all(v.strip() for v in variants.values())
    for key, variants in copy.SPOKEN.items():
        assert set(variants) >= {"hinglish", "hi", "en"}, key
    # every format field of the Hinglish line exists in the English one
    for variants in copy.LINES.values():
        assert set(re.findall(r"{(\w+)}", variants["hinglish"])) == set(
            re.findall(r"{(\w+)}", variants["en"])
        )


_ROMAN_HINDI = re.compile(
    r"\b(hai|nahi|kijiye|karo|karna|hoon|aap|aapka|mera|abhi|dobara|theek|bhejti|batao)\b", re.I
)


def test_no_user_facing_text_outside_the_copy_module():
    """Every new line is in copy.py (pending). Other modules may only hold regexes and keys."""
    offenders: list[str] = []
    for path in ROOT.glob("*.py"):
        if path.name in ("copy.py", "demo.py", "router.py"):  # demo: headings; router: regexes
            continue
        tree = ast.parse(path.read_text())
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        for n in ast.walk(tree):
            if (
                isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and id(n) not in docstrings
                and _ROMAN_HINDI.search(n.value)
                and len(n.value.split()) >= 2
            ):
                offenders.append(f"{path.name}:{n.lineno}: {n.value[:50]}")
    assert offenders == []
