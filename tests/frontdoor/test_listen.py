"""`friday listen`: refusals, the offline simulation, and the always-restore guarantee."""

from __future__ import annotations

import pytest

from friday.core.config import Settings
from friday.pilot import (
    SIM_FRIDAY_NUMBER,
    inbound_link,
    listen_preflight,
    run_listen,
    write_frontdoor_transcript,
)
from friday.voice.telephony.vobiz_app import FakeVobizAccount, VobizAppManager

OWN = "+919812345678"


def live_pilot(**kw) -> Settings:
    base = dict(
        _env_file=None, mode="live", profile="pilot", llm_provider="fake",
        public_base_url="https://abc-def.trycloudflare.com",
        sarvam_telephony_auth_id="id", sarvam_telephony_auth_token="tok",
        sarvam_caller_ids=["+918065354620"], sarvam_api_key="k",
        secret_key="s" * 32, pin_pepper="p", field_key="f", index_key="i",
        pilot_allowed_numbers=[OWN],
    )
    base.update(kw)
    return Settings(**base)


def test_listen_preflight_ok_and_refusals():
    assert listen_preflight(live_pilot()) == []
    assert any("FRIDAY_MODE" in r for r in listen_preflight(Settings(_env_file=None)))
    assert any("ALLOWED" in r for r in listen_preflight(live_pilot(pilot_allowed_numbers=[])))
    assert any("SARVAM_CALLER_IDS" in r for r in listen_preflight(live_pilot(sarvam_caller_ids=[])))
    assert any("https" in r for r in listen_preflight(live_pilot(public_base_url="http://localhost")))
    assert any("Auth" in r for r in listen_preflight(live_pilot(sarvam_telephony_auth_id=None)))


async def test_listen_refuses_without_touching_vobiz_or_the_network(tmp_path):
    out: list[str] = []
    rc = await run_listen(Settings(_env_file=None), out=out.append, state_dir=tmp_path,
                          link_state=tmp_path / "link.json")
    assert rc == 2 and any("will NOT start" in x for x in out)


async def test_restore_only_without_credentials_is_a_clear_error(tmp_path):
    out: list[str] = []
    rc = await run_listen(Settings(_env_file=None), restore_only=True, out=out.append,
                          link_state=tmp_path / "link.json")
    assert rc == 2 and any("Auth" in x for x in out)


async def test_simulated_listen_runs_the_whole_flow_offline(tmp_path):
    out: list[str] = []
    rc = await run_listen(
        Settings(_env_file=None), simulate=True, out=out.append, state_dir=tmp_path / "calls",
        link_state=tmp_path / "link.json",
    )
    text = "\n".join(out)
    assert rc == 0, text
    assert f"Call {SIM_FRIDAY_NUMBER} now" in text  # the instruction the founder acts on
    assert "now rings Friday" in text and "link reattached" in text  # linked, then restored
    assert text.count("===== CALL") == 3
    assert "onboarded by voice" in text  # call 1: a new person
    assert "(user)" in text  # call 2: recognised
    assert "not served (pilot: caller not in the allow-list)" in text  # call 3
    assert "Estimated cost" in text and "p95" in text and "Transcript" in text
    files = sorted((tmp_path / "calls").glob("frontdoor-*.txt"))
    assert len(files) == 2  # the refused caller has no transcript to keep
    body = files[0].read_text(encoding="utf-8")
    assert "AI assistant" in body and "CALLER" in body and "FRIDAY" in body
    assert not (tmp_path / "link.json").exists()


async def test_the_link_is_restored_even_when_serving_fails(tmp_path):
    fake = FakeVobizAccount("MA_T", numbers={"+918065354620": "777"},
                            applications=[{"app_id": "777", "app_name": "old"}])
    mgr = VobizAppManager("MA_T", "tok", transport=fake.transport, state_path=tmp_path / "s.json")
    out: list[str] = []
    with pytest.raises(RuntimeError, match="boom"):
        async with inbound_link(mgr, "https://x.trycloudflare.com", "+918065354620", "s" * 32,
                                out.append):
            assert fake.numbers["+918065354620"] != "777"
            raise RuntimeError("boom")
    assert fake.numbers["+918065354620"] == "777"
    assert any("reattached" in x for x in out)


async def test_a_failed_restore_tells_the_founder_how_to_fix_it(tmp_path):
    fake = FakeVobizAccount("MA_T", numbers={"+918065354620": "777"},
                            applications=[{"app_id": "777", "app_name": "old"}])
    mgr = VobizAppManager("MA_T", "tok", transport=fake.transport, state_path=tmp_path / "s.json")
    out: list[str] = []
    link = inbound_link(mgr, "https://x.trycloudflare.com", "+918065354620", "s" * 32, out.append)
    async with link:
        fake.fail[("POST", "/application")] = 500
    assert any("friday listen --restore" in x for x in out)
    assert (tmp_path / "s.json").exists()


def test_transcript_file_masks_the_number_and_redacts_secrets(tmp_path):
    from friday.core.models import (
        CallDirection,
        CallerKind,
        CallOutcome,
        CallResult,
        DialStatus,
        Speaker,
    )
    from friday.voice.frontdoor import FrontDoorSummary
    from friday.voice.text import redact_secrets

    r = CallResult(task_id="t", provider="x", to_phone=OWN, dial_status=DialStatus.ANSWERED,
                   outcome=CallOutcome.SUCCESS, direction=CallDirection.INBOUND)
    r.transcript.add(Speaker.CALLEE, redact_secrets("mera pin 4826 hai"))
    s = FrontDoorSummary(call_id="abc123456", caller="+91******5678", kind=CallerKind.USER,
                         route="serve", outcome="success")
    path = write_frontdoor_transcript(r, s, tmp_path)
    body = path.read_text(encoding="utf-8")
    assert "4826" not in body and OWN not in body and "+91******5678" in body
