# ruff: noqa: E501
"""T16: screen-first and listen-in through the full path, with FAKES ONLY (FakeCallBridge -> ScreeningService -> DeviceService.feed_call_turn -> S4P
alert port). No call is placed, no audio exists, the Vobiz adapter is only checked for its refusals."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from friday.core.clock import IST
from friday.robin import lines
from friday.robin.callbridge import BridgeRefused, FakeCallBridge, Turn, VobizCallBridge
from friday.robin.models import ConsentSource
from friday.robin.screening import ScreeningService, is_listen_trigger
from friday.robin.wiring import _DeviceConsent, _DeviceParents
from friday.robindevice.ports import FakeAlertPort
from friday.robindevice.service import DeviceService

DATA = yaml.safe_load((Path(__file__).parents[1] / "robindevice" / "call_dialogues.yaml").read_text(encoding="utf-8"))["dialogues"]
TIERS = ("NONE", "INFO", "WATCH", "HIGH")
SENTINEL = "zxqvtoken"


def script_of(d: dict, *, caller_only: bool = False) -> list[Turn]:
    out = []
    for i, line in enumerate(d["turns"]):
        who, text = line.split(": ", 1)
        if caller_only and who != "c":
            continue
        out.append(Turn("caller" if who == "c" else "parent", text, float(i * 15)))
    return out


class Rig:
    def __init__(self, w, fam, parent, bridge, svc, device, alerts):
        self.w, self.fam, self.parent, self.bridge, self.svc, self.device, self.alerts = w, fam, parent, bridge, svc, device, alerts


@pytest.fixture
async def rig(w):
    fam, parent = await w.family()
    await w.hub.fam.give_consent(parent.id, "call_listening", ConsentSource.ADMIN_CHAT)  # the child said yes for the parent
    alerts = FakeAlertPort()
    device = DeviceService(alerts=alerts, consent=_DeviceConsent(w.hub), parents=_DeviceParents(w.hub), now_ms=lambda: int(w.clock.now().timestamp() * 1000), brand="Robin")
    await device.store.ensure_loaded()
    device.set_policy(parent.id, shadow_days=0)
    device.store.state(parent.id).shadow_start_ms = device.now_ms() - 86_400_000  # GAP G1: an unpaired (server-side only) family never leaves the shadow week by itself
    bridge = FakeCallBridge()
    w.settings.robin_screen_unknown_enabled = True
    w.settings.robin_listen_in_enabled = True
    svc = ScreeningService(w.ctx, bridge=bridge, device=lambda: device)
    return Rig(w, fam, parent, bridge, svc, device, alerts)


def s4p(r: Rig) -> list[dict]:
    return [c for c in r.alerts.of(r.parent.id) if c["scenario"] == "S4P"]


# ---------------------------------------------------------------- corpus -> expected tiers, listen-in
@pytest.mark.parametrize("d", DATA, ids=[d["id"] for d in DATA])
async def test_listen_in_corpus_through_the_full_path(rig, d):
    rig.bridge.scripts["c1"] = script_of(d)
    res = await rig.svc.run_listen_in("c1", rig.fam, rig.parent)
    assert res.action in ("done", "stopped")
    top = TIERS.index(res.reason)
    if "min" in d:
        assert top >= TIERS.index(d["min"]), res
    if "max" in d:
        assert top <= TIERS.index(d["max"]), res
    if d.get("min") == "HIGH":
        assert s4p(rig) and any(c["tier"] == "HIGH" for c in s4p(rig))  # the tier drives S4P
        assert "listen.warn" in res.lines
        whispers = [e for e in rig.bridge.events if e[0] == "speak:parent"]
        assert len(whispers) == 1  # once, to the parent only
    if d.get("max") in ("NONE", "INFO"):
        assert not s4p(rig) and "listen.warn" not in res.lines
    assert rig.device.finish_call(rig.parent.id, "c1") is None  # finish_call already ran


# ---------------------------------------------------------------- corpus, screen-first (the caller's words only)
@pytest.mark.parametrize("d", DATA, ids=[d["id"] for d in DATA])
async def test_screen_first_corpus(rig, d):
    rig.bridge.scripts["c1"] = script_of(d, caller_only=True)
    res = await rig.svc.run_screen("c1", rig.fam, rig.parent)
    rang = any(e[0] == "ring_parent" for e in rig.bridge.events)
    if d.get("min") == "HIGH":
        assert res.action == "decline" and not rang
        assert rig.w.sender.texts(), "the child is told"
    if d.get("max") == "NONE":
        assert res.action in ("bridge", "decline")  # an empty caller script is declined, a calm one connects
        assert rang == (res.action == "bridge")
    assert rig.device.finish_call(rig.parent.id, "c1") is None


async def test_screening_line_is_spoken_before_the_parent_phone_rings_and_before_any_turn(rig):
    rig.bridge.scripts["c1"] = [Turn("caller", "Hello, I am the plumber, I am outside your gate about the water tank.", 0)]
    res = await rig.svc.run_screen("c1", rig.fam, rig.parent)
    assert res.action == "bridge"
    kinds = [e[0] for e in rig.bridge.events]
    assert kinds[:3] == ["answer", "speak:both", "turn"]
    assert kinds.index("ring_parent") > kinds.index("turn")
    assert rig.bridge.events[1][1] == lines.say("screen.ask", "hinglish", brand="Robin", parent="Papa")
    assert "screening" in lines.SPOKEN["screen.ask"]["en"] or "screen" in lines.SPOKEN["screen.ask"]["en"]


async def test_silent_unknown_caller_is_declined_and_known_caller_is_not_screened(rig):
    rig.bridge.scripts["c1"] = []
    assert (await rig.svc.run_screen("c1", rig.fam, rig.parent)).action == "decline"
    assert not any(e[0] == "ring_parent" for e in rig.bridge.events)
    known = await rig.svc.run_screen("c1", rig.fam, rig.parent, caller_known=True)
    assert known.action == "bridge" and known.reason == "known_caller"


# ---------------------------------------------------------------- the disclosure is always spoken first
async def test_disclosure_is_spoken_first_to_both_sides_in_every_language(rig):
    for lang in ("en", "hinglish", "hi"):
        rig.parent.language = lang
        rig.bridge.events.clear()
        rig.bridge.scripts["c1"] = script_of(DATA[0])
        await rig.svc.run_listen_in("c1", rig.fam, rig.parent)
        first_two = rig.bridge.events[:2]
        assert first_two[0] == ("join", "c1")
        assert first_two[1] == ("speak:both", lines.say("listen.disclose", lang, brand="Robin", parent="Papa"))
        assert [e[0] for e in rig.bridge.events].index("turn") > 1
        assert "AI" in first_two[1][1] and ("record" in first_two[1][1].lower() or "रिकॉर्ड" in first_two[1][1])


async def test_the_bridge_itself_refuses_an_empty_disclosure(rig):
    with pytest.raises(BridgeRefused):
        await rig.bridge.join("c1", disclosure="  ")
    with pytest.raises(BridgeRefused):
        await rig.bridge.answer("c1", screening_line="")

    async def no_legs(_ref):
        raise KeyError

    vb = VobizCallBridge(lambda *a, **k: None, ws_url="wss://x.invalid/ws", resolve_legs=no_legs, conference_xml_url=lambda ref: ref)  # type: ignore[arg-type]
    with pytest.raises(BridgeRefused):
        await vb.join("c1", disclosure="")
    with pytest.raises(BridgeRefused):
        await vb.join("c1", disclosure="hello")  # unknown call


# ---------------------------------------------------------------- consent, switches, pause
async def test_consent_off_the_bridge_is_never_touched(w):
    fam, parent = await w.family()  # no call_listening consent
    bridge = FakeCallBridge({"c1": script_of(DATA[0])})
    alerts = FakeAlertPort()
    device = DeviceService(alerts=alerts, consent=_DeviceConsent(w.hub), parents=_DeviceParents(w.hub), brand="Robin")
    w.settings.robin_screen_unknown_enabled = w.settings.robin_listen_in_enabled = True
    svc = ScreeningService(w.ctx, bridge=bridge, device=lambda: device)
    assert (await svc.run_listen_in("c1", fam, parent)).reason == "no_consent"
    assert (await svc.run_screen("c1", fam, parent)).reason == "no_consent"
    assert bridge.events == [] and alerts.calls == []


async def test_switches_off_by_default_and_no_bridge_attached(w):
    fam, parent = await w.family()
    await w.hub.fam.give_consent(parent.id, "call_listening", ConsentSource.ADMIN_CHAT)
    assert not w.settings.robin_screen_unknown_enabled and not w.settings.robin_listen_in_enabled
    assert (await w.hub.screening.run_listen_in("c1", fam, parent)).reason == "switch_off"
    assert (await w.hub.screening.run_screen("c1", fam, parent)).reason == "switch_off"
    w.settings.robin_listen_in_enabled = True
    assert (await w.hub.screening.run_listen_in("c1", fam, parent)).reason == "no_bridge"  # the hub ships with no bridge
    assert await w.hub.listen_in("c1", parent.phone) == "refused"


async def test_a_paused_parent_is_not_listened_to(rig):
    rig.parent.paused = True
    rig.bridge.scripts["c1"] = script_of(DATA[0])
    assert (await rig.svc.run_listen_in("c1", rig.fam, rig.parent)).reason == "not_active"
    assert rig.bridge.events == []


async def test_the_parent_can_stop_a_listen_in(rig):
    rig.bridge.scripts["c1"] = [Turn("caller", "Hello Papa how are you", 0), Turn("parent", "Robin, band karo, stop", 5), Turn("caller", "I am from the CBI, arrest warrant, do not tell anyone", 10)]
    res = await rig.svc.run_listen_in("c1", rig.fam, rig.parent)
    assert res.action == "stopped" and res.reason in ("NONE", "INFO")
    assert rig.bridge.events[-1] == ("leave", "") and sum(e[0] == "turn" for e in rig.bridge.events) == 2
    assert not s4p(rig)


def test_listen_trigger_words():
    assert is_listen_trigger("Robin, suno") and is_listen_trigger("Robin listen in") and is_listen_trigger("suno")
    assert not is_listen_trigger("Robin what is the weather") and not is_listen_trigger("I will listen to the radio at night when it is calm")


# ---------------------------------------------------------------- security paths ignore time of day
async def test_works_at_three_in_the_morning_and_in_quiet_hours(rig):
    rig.w.clock.set(rig.w.clock.now().replace(hour=3, minute=0, tzinfo=IST))
    assert rig.w.ctx.in_quiet(rig.parent, rig.fam)
    d = next(x for x in DATA if x.get("min") == "HIGH")
    rig.bridge.scripts["c1"] = script_of(d)
    res = await rig.svc.run_listen_in("c1", rig.fam, rig.parent)
    assert "listen.warn" in res.lines and s4p(rig)
    rig.bridge.scripts["c2"] = script_of(d, caller_only=True)
    assert (await rig.svc.run_screen("c2", rig.fam, rig.parent)).action == "decline"


# ---------------------------------------------------------------- no transcript is stored anywhere
async def test_no_transcript_text_is_persisted(rig):
    rig.bridge.scripts["c1"] = [
        Turn("caller", f"This is Inspector Sharma from the CBI, arrest warrant {SENTINEL}", 0),
        Turn("parent", f"What? {SENTINEL} I did not send anything", 5),
        Turn("caller", f"Stay on the line, do not tell anyone, transfer money now {SENTINEL}", 10),
    ]
    res = await rig.svc.run_listen_in("c1", rig.fam, rig.parent)
    assert res.reason in ("WATCH", "HIGH")
    seen: list[str] = [repr(rig.bridge.events), repr(rig.alerts.calls), repr(rig.w.sender.sent if hasattr(rig.w.sender, "sent") else rig.w.sender.texts())]
    for kind in ("audit", "pending", "incident", "alert"):
        seen.append(repr([r.data for r in await rig.w.store.list(rig.fam.id, kind)]))
    st = rig.device.store.peek(rig.parent.id)
    seen += [repr(st.events), repr(st.counters) if hasattr(st, "counters") else ""]
    assert SENTINEL not in " ".join(seen)
    assert rig.device._analyzers == {}  # the in-call analyzer (the only holder of the text window) is gone
    assert any(e.type == "call_pattern" for e in st.events)  # only cues, tier and time remain
    assert all(set(e.data) <= {"call_id", "tier", "score", "cue_ids"} for e in st.events if e.type == "call_pattern")


async def test_the_child_hears_the_level_but_never_the_words(rig):
    rig.bridge.scripts["c1"] = script_of(next(x for x in DATA if x.get("min") == "HIGH"))
    await rig.svc.run_listen_in("c1", rig.fam, rig.parent)
    note = rig.w.sender.texts()[-1]
    assert "HIGH" in note and "CBI" not in note and "warrant" not in note


async def _server_side_only(w, dialogue_id_pred):
    fam, parent = await w.family()
    await w.hub.fam.give_consent(parent.id, "call_listening", ConsentSource.ADMIN_CHAT)
    alerts = FakeAlertPort()
    device = DeviceService(alerts=alerts, consent=_DeviceConsent(w.hub), parents=_DeviceParents(w.hub), brand="Robin")
    w.settings.robin_listen_in_enabled = True
    d = next(x for x in DATA if dialogue_id_pred(x))
    svc = ScreeningService(w.ctx, bridge=FakeCallBridge({"c1": script_of(d)}), device=lambda: device)
    res = await svc.run_listen_in("c1", fam, parent)
    return res, alerts, parent, device


async def test_g1_closed_an_unpaired_family_still_alerts_the_child_on_call_pattern_high(w):
    """T16 gap G1 (closed): a server-side-only family (no phone ever paired, so ``shadow_start_ms`` is None and the engine says 'shadow') must NOT have a
    call-pattern HIGH silenced. S4P HIGH is exempt from the shadow week (per-tier ``shadow_exempt``); the child is alerted at any hour."""
    res, alerts, parent, device = await _server_side_only(w, lambda x: x.get("min") == "HIGH")
    assert res.reason == "HIGH" and "listen.warn" in res.lines
    assert device.store.state(parent.id).shadow_start_ms is None  # really the unpaired case
    assert [c["tier"] for c in alerts.of(parent.id) if c["scenario"] == "S4P"] == ["HIGH"]


