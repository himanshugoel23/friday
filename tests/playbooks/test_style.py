"""The founder's script style: checks, safe fixes, and learning from a correction."""

from __future__ import annotations

from pathlib import Path

from friday.playbooks.style import autofix, learn, lint_line, load_style
from friday.playbooks.style.core import StyleBook


def style() -> StyleBook:
    return load_style(learned_path=Path("/nonexistent.yaml"))


def test_formal_word_is_swapped_for_the_everyday_one():
    s = style()
    issues = lint_line("x", "Toh sabse nazdeek kaun sa slot available hoga?", s)
    assert any(i.kind == "swap" and i.suggestion == "nearest" for i in issues)
    assert (
        autofix("Toh sabse nazdeek kaun sa slot hoga?", s) == "Toh sabse nearest kaun sa slot hoga?"
    )


def test_placeholders_are_never_touched():
    assert autofix("{nazdeek} ka slot nazdeek", style()) == "{nazdeek} ka slot nearest"


def test_a_long_line_without_a_filler_is_flagged_and_a_filler_line_is_not():
    s = style()
    assert any(
        i.kind == "filler"
        for i in lint_line("x", "Sir haircut ke kya charges rahenge aapke yahan", s)
    )
    assert not any(
        i.kind == "filler" for i in lint_line("x", "Toh sir haircut ke kya charges rahenge", s)
    )
    assert not any(
        i.kind == "filler" for i in lint_line("ai_yes", "Haan ji main virtual assistant hoon", s)
    )


def test_stiff_ending_is_flagged():
    assert any(i.kind == "ending" for i in lint_line("x", "Toh sir slot available hai?", style()))


def test_learning_a_correction_adds_a_swap_and_an_example(tmp_path):
    path = tmp_path / "learned.yaml"
    got = learn("Sir, kripya aap batayein", "Sir, please aap batayein", learned_path=path)
    assert got["swaps"] == {"kripya": "please"}
    s = load_style(learned_path=path)
    assert s.swap["kripya"] == "please" and "Sir, please aap batayein" in s.golden
    learn(
        "Koi nazdeek slot", "Koi nearest slot", learned_path=path
    )  # second correction adds, keeps first
    assert load_style(learned_path=path).swap["nazdeek"] == "nearest"


def test_prompt_block_carries_rules_and_approved_examples():
    block = style().prompt_block()
    assert "filler" in block and "nearest" in block and "Approved examples" in block


def test_the_cli_checks_a_real_playbook_without_editing_it():
    import subprocess

    out = subprocess.run(
        ["uv", "run", "friday", "playbook", "style-check", "salon_booking"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "style issue(s) in salon_booking" in out.stdout


def test_ack_never_repeats_within_the_last_two():
    from friday.playbooks.engine import CallState
    from friday.playbooks.intents import ACK_POOL

    seen: list[str] = []
    st = CallState.__new__(CallState)
    st.acks = []
    for _ in range(200):
        fresh = [a for a in ACK_POOL if a not in st.acks[-2:]]
        assert fresh, "pool is large enough to always have a fresh acknowledgement"
        pick = fresh[len(seen) % len(fresh)]
        st.acks.append(pick)
        seen.append(pick)
    assert all(seen[i] not in seen[max(0, i - 2) : i] for i in range(len(seen)))
    assert len(set(seen)) >= 4


def test_the_playbook_engine_picks_acks_from_the_approved_pool():
    import re

    from friday.playbooks.engine import (
        Ctx,  # noqa: F401  (the {ack} placeholder lives in Ctx.value)
    )
    from friday.playbooks.intents import ACK_POOL

    assert re.fullmatch(r"[A-Za-z ]+", " ".join(ACK_POOL))
    assert "Achha theek hai sir" in ACK_POOL and len(ACK_POOL) == 6
