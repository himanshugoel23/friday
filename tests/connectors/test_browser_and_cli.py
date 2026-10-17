from __future__ import annotations

import pytest

from friday.cli import main
from friday.connectors.browser.playwright_session import browser_available, find_chromium
from friday.connectors.demo import run_demo_flow
from friday.connectors.recorder import StepRecorder

needs_browser = pytest.mark.skipif(
    not browser_available(), reason="playwright extra or Chromium not available")


def test_find_chromium_env_override(tmp_path, monkeypatch):
    exe = tmp_path / "chrome"
    exe.write_text("x")
    monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_PATH", str(exe))
    assert find_chromium() == str(exe)


@needs_browser
async def test_full_flow_on_fake_site_with_real_chromium(tmp_path):
    rec = StepRecorder()
    trace = str(tmp_path / "trace.zip")
    res = await run_demo_flow("playwright", rec, trace_to=trace)
    assert res.status == "payment_ready", res.message
    assert res.cart.grand_total_paise == res.handoff.amount_paise == 60335
    assert res.handoff.qr_png.startswith(b"\x89PNG")
    assert any(s.screenshot for s in rec.steps) and rec.done
    assert (tmp_path / "trace.zip").stat().st_size > 0
    assert "246810" not in " ".join(s.note for s in rec.steps)


async def test_sim_engine_demo_matches():
    rec = StepRecorder()
    res = await run_demo_flow("sim", rec)
    assert res.status == "payment_ready" and rec.done and rec.result["status"] == "payment_ready"


def test_cli_list_and_demo(capsys, tmp_path):
    assert main(["connectors", "list"]) == 0
    assert "zomato.food" in capsys.readouterr().out
    assert main(["connectors", "demo-pizza"]) == 2  # --fake is required
    assert main(["connectors", "demo-pizza", "--fake", "--engine", "sim",
                 "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "payment_ready" in out and (tmp_path / "report.html").exists()
