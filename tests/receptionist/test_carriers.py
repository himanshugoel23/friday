# ruff: noqa: E501
from __future__ import annotations

import pytest

from friday.receptionist import carriers as C
from friday.receptionist.models import ReceptionistConfig
from friday.receptionist.setup import PROBE_STEPS, TestCallHelper, setup_text

NUM = "+918000000099"  # invented


@pytest.mark.parametrize(
    ("rings", "secs"), [(3, 15), (4, 20), (5, 25), (6, 30)]
)
def test_seconds_are_five_per_ring(rings, secs):
    assert C.no_reply_seconds(rings) == secs


def test_seconds_are_multiples_of_five_and_capped_by_the_carrier():
    for r in range(0, 12):
        s = C.no_reply_seconds(r)
        assert s % 5 == 0 and 15 <= s <= 30  # rings are clamped to 3-6
    assert C.no_reply_seconds(6, max_seconds=20) == 20
    assert C.no_reply_seconds(6, max_seconds=22) == 20  # never above a non-multiple maximum


@pytest.mark.parametrize("carrier", ["jio", "airtel", "vi", "bsnl"])
def test_code_set_for_every_carrier(carrier):
    cs = C.codes_for(carrier, ReceptionistConfig(rings=5), NUM)
    codes = {x.label: x.code for x in cs.activate}
    assert codes["no_answer"] == f"**61*{NUM}**25#"
    assert codes["busy"] == f"**67*{NUM}#"
    assert codes["unreachable"] == f"**62*{NUM}#"
    assert [c for _, c in cs.cancel] == ["##61#", "##67#", "##62#"]
    assert [c for _, c in cs.status] == ["*#61#", "*#67#", "*#62#"]
    assert cs.cancel_all == "##002#"
    assert not cs.carrier.verified  # nothing is verified until a probe on a real SIM says so
    assert any("NOT been verified" in n for n in cs.notices)


def test_options_switch_codes_off_and_national_format():
    cfg = ReceptionistConfig(rings=3, forward_busy=False, forward_unreachable=False)
    cs = C.codes_for("Airtel", cfg, NUM, number_style="national")
    assert [x.code for x in cs.activate] == ["**61*8000000099**15#"]


def test_carrier_aliases_and_unknown():
    assert C.find_carrier("Vodafone Idea").key == "vi"
    assert C.find_carrier("reliance jio").key == "jio"
    with pytest.raises(ValueError, match="unknown carrier"):
        C.codes_for("acme", ReceptionistConfig(), NUM)


def test_tel_link_encodes_the_hash():
    link = C.tel_link("**61*+918000000099**25#")
    assert link == "tel:**61*+918000000099**25%23"
    assert "#" not in link


def test_carrier_maximum_is_reported():
    c = C.Carrier("x", "X", max_no_reply_s=20)
    cs = C.codes_for(c, ReceptionistConfig(rings=6), NUM)
    assert cs.seconds == 20 and any("at most 20 seconds" in n for n in cs.notices)


@pytest.mark.parametrize("lang", ["hinglish", "en"])
def test_setup_text_has_the_voicemail_warning_and_the_codes(lang):
    cs = C.codes_for("jio", ReceptionistConfig(rings=5), NUM)
    text = setup_text(cs, lang)
    assert "**61*" in text and "##002#" in text and "*#61#" in text
    assert "voicemail" in text.lower()  # the carrier voicemail may win: must be switched off
    assert "general knowledge" in text


def test_probe_steps_cover_decline_and_each_carrier():
    joined = "\n".join(PROBE_STEPS)
    assert "Decline" in joined and "Jio, Airtel, Vi, BSNL" in joined and "##002#" in joined


async def test_test_call_helper_refuses_and_never_dials_by_default():
    cfg = ReceptionistConfig()
    refused = await TestCallHelper(allow_listed=lambda p: False, paused=lambda: False).run("+91", cfg)
    assert not refused.placed and "allow-listed" in refused.detail
    paused = await TestCallHelper(allow_listed=lambda p: True, paused=lambda: True).run("+91", cfg)
    assert not paused.placed and "kill switch" in paused.detail
    manual = await TestCallHelper(allow_listed=lambda p: True, paused=lambda: False).run("+91", cfg)
    assert not manual.placed and "another phone" in manual.detail


async def test_test_call_helper_reports_whether_the_forward_arrived():
    calls = []

    async def dial(phone: str) -> bool:
        calls.append(phone)
        return True

    async def waits(ok: bool):
        async def w(_t: float) -> bool:
            return ok

        return w

    h = TestCallHelper(allow_listed=lambda p: True, paused=lambda: False, dialer=dial,
                       wait_for_forward=await waits(True))  # fmt: skip
    r = await h.run("+919800000001", ReceptionistConfig())
    assert r.placed and r.found and calls == ["+919800000001"]
    h2 = TestCallHelper(allow_listed=lambda p: True, paused=lambda: False, dialer=dial,
                        wait_for_forward=await waits(False))  # fmt: skip
    r2 = await h2.run("+919800000001", ReceptionistConfig())
    assert r2.placed and not r2.found and "voicemail" in r2.detail
