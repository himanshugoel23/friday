"""The lab's HTTP surface: tokens, the page, and the endpoints, through FastAPI's TestClient."""

from __future__ import annotations

import json
import re

import pytest

from friday.lab.world import PERSONAS
from tests.lab.conftest import PHONE_RE, PRIYA, RAHUL, SECRET_ENV, SUNITA, Lab

CALL_REQUEST = "mummy ko call karke bata do ki main late hoon"


# ------------------------------------------------------------------ tokens and the page
def test_every_page_and_api_needs_the_token(lab):
    c = lab.client
    assert c.get(f"/lab/{lab.token}/").status_code == 200
    for bad in ("nope", "x" * 32, lab.token[:-1], lab.token + "x"):
        assert c.get(f"/lab/{bad}/").status_code == 404
        assert c.get(f"/lab/api/{bad}/config").status_code == 404
        assert (
            c.post(f"/lab/api/{bad}/send", json={"phone": RAHUL, "text": "hi"}).status_code == 404
        )
        assert c.get(f"/lab/api/{bad}/export.md", params={"phone": RAHUL}).status_code == 404
    for path in (
        "/",
        "/lab",
        "/lab/",
        "/lab/api",
        "/lab/api/config",
        "/health",
        "/docs",
        "/openapi.json",
    ):
        assert c.get(path).status_code == 404


def test_the_token_is_unguessable_and_not_in_any_log_line(lab, caplog):
    assert len(lab.token) >= 32
    lab.get("/config")
    assert lab.token not in caplog.text


def test_tokens_expire(make_lab):
    lab = make_lab(ttl_hours=8)
    assert lab.get("/config").status_code == 200
    lab.clock["t"] += 7.9 * 3600
    assert lab.get("/config").status_code == 200
    lab.clock["t"] += 0.2 * 3600
    assert lab.get("/config").status_code == 404
    assert lab.client.get(f"/lab/{lab.token}/").status_code == 404
    assert lab.post("/send", phone=RAHUL, text="hi").status_code == 404


def test_default_ttl_is_eight_hours(lab):
    left = lab.get("/state", phone=RAHUL).json()["token_seconds_left"]
    assert 8 * 3600 - 5 <= left <= 8 * 3600


def test_the_page_is_one_self_contained_file(lab):
    r = lab.client.get(f"/lab/{lab.token}/")
    assert r.status_code == 200
    html = r.text
    assert f"/lab/api/{lab.token}" in html and "__API_BASE__" not in html
    assert not re.search(r"""(src|href)\s*=\s*["'](https?:)?//""", html)  # no CDN, no external file
    assert "prefers-color-scheme" in html and "data-theme" in html  # light and dark
    assert 'name="viewport"' in html
    assert "<title>Friday Chat Lab</title>" in html
    h = r.headers
    assert h["cache-control"] == "no-store" and h["x-robots-tag"] == "noindex"
    assert h["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in h["content-security-policy"]
    assert "connect-src 'self'" in h["content-security-policy"]


def test_config_lists_users_personas_chips_and_attachments(lab):
    cfg = lab.get("/config").json()
    assert [u["phone"] for u in cfg["users"]] == [RAHUL, PRIYA, SUNITA]
    assert set(cfg["personas"]) == set(PERSONAS) and len(cfg["personas"]) == 6
    texts = [c["text"] for c in cfg["chips"]]
    for want in (
        "hi",
        CALL_REQUEST,
        "HDFC Regalia aur SBI Cashback hai",
        "Zomato pe 640",
        "kal 2 baje interview hai",
        "mera din",
        "menu",
        "delete everything",
        "कल 2 बजे interview है",
    ):
        assert want in texts
    assert {"Gurgaon", "Bangalore"} <= set(cfg["location_presets"])
    assert cfg["contact_presets"] and cfg["sample_files"]
    assert cfg["mode"] == "simulator" and cfg["llm"] == {"mode": "fake", "real_available": False}


# ------------------------------------------------------------------ a scripted session
def finish_onboarding(lab: Lab, phone: str, snap: dict) -> dict:
    for _ in range(8):
        if snap["user"].get("status") == "active":
            return snap
        titles = [b["title"] for e in Lab.outs(snap) for b in e.get("buttons") or []]
        pick = next((t for t in titles if t in ("Skip", "Later")), None)
        snap = lab.tap(phone, pick, snap) if pick else lab.say(phone, "skip")
    raise AssertionError("onboarding did not finish")


def test_new_user_goes_hi_onboarding_card_call_approve_report(lab):
    cfg = lab.post("/new-user").json()
    phone = cfg["phone"]
    assert re.fullmatch(r"\+919800\d{6}", phone) and phone not in (RAHUL, PRIYA, SUNITA)
    assert lab.get("/state", phone=phone).json()["user"]["exists"] is False

    snap = lab.say(phone, "hi")
    assert snap["turn"]["route"]["handler"] == "onboarding"
    assert snap["user"]["status"] == "onboarding"
    assert snap["entries"][0]["dir"] == "in" and snap["entries"][0]["status"] == "read"

    for line in ("Rahul", "Delhi"):
        snap = lab.say(phone, line)
    snap = lab.tap(phone, "Hinglish", snap)  # a language button
    snap = lab.tap(phone, "Playful", snap)  # a tone button
    assert "agree" in " ".join(b["title"].lower() for e in Lab.outs(snap) for b in e["buttons"])
    snap = lab.tap(phone, "I agree", snap)
    snap = lab.say(phone, "4827")
    snap = lab.say(phone, "4827")
    snap = finish_onboarding(lab, phone, snap)
    assert snap["user"]["consent_terms"] is True and snap["user"]["pin_set"] is True
    assert snap["user"]["name"] == "R****"  # the name is masked in the panel

    snap = lab.say(phone, "mere paas HDFC Regalia aur SBI Cashback hai")
    assert snap["turn"]["route"]["handler"] == "consumer.savings"
    snap = lab.say(phone, "Zomato pe 640")
    assert "SBI Card Cashback" in Lab.text_of(snap)
    assert snap["turn"]["slots"]["purchase"]["merchant"]

    snap = lab.say(phone, CALL_REQUEST)
    assert snap["turn"]["route"]["handler"] == "consumer._call_turn"
    snap = lab.say(phone, "+91 90000 00001")
    snap = lab.say(phone, "haan")
    plan = Lab.outs(snap)[-1]
    assert [b["title"] for b in plan["buttons"]] == ["Approve", "Edit", "Cancel"]

    snap = lab.tap(
        phone, "Approve", snap
    )  # approve -> gate -> call job -> simulated Mummy -> report
    turn = snap["turn"]
    assert [g["verdict"] for g in turn["guards"] if g["gate"] == "call_gate"][-1] == "allow"
    call = turn["calls"][0]
    assert call["persona"] == "friendly_elder" and call["status"] == "completed"
    assert any(t["speaker"] == "callee" for t in call["transcript"])
    report = Lab.outs(snap)[-1]
    assert "se baat ho gayi" in report["text"].lower()
    assert [b["title"] for b in report["buttons"]] == [
        "Theek hai",
        "Reminder lagao",
        "Phir call karo",
    ]


def test_a_saved_user_gets_the_whole_call_flow_in_two_taps(lab):
    snap = lab.say(RAHUL, CALL_REQUEST)
    plan = Lab.outs(snap)[-1]
    assert "Mummy" in plan["text"]
    snap = lab.tap(RAHUL, "Approve", snap)
    assert snap["turn"]["calls"][0]["status"] == "completed"
    assert "se baat ho gayi" in Lab.text_of(snap).lower()
    assert snap["turn"]["latency_ms"]["total"] > 0


@pytest.mark.parametrize(
    ("persona", "completed"),
    [
        ("friendly_elder", True),
        ("busy", False),
        ("hostile", False),
        ("wrong_number", False),
        ("voicemail", False),
        ("are_you_a_bot", True),
    ],
)
def test_each_callee_persona_produces_a_report_in_the_chat(lab, persona, completed):
    assert lab.post("/persona", persona=persona).json() == {"persona": persona}
    snap = lab.say(RAHUL, CALL_REQUEST)
    snap = lab.tap(RAHUL, "Approve", snap)
    call = snap["turn"]["calls"][0]
    assert (call["status"] == "completed") is completed, call
    assert Lab.outs(snap)  # the call report (or the retry notice) reached the chat
    assert snap["persona"] == persona


def test_unknown_persona_and_switch_are_refused(lab):
    assert lab.post("/persona", persona="nope").status_code == 422
    assert lab.post("/switch", name="nope", on=True).status_code == 422
    assert lab.post("/switch", name="google", on=True).status_code == 422
    assert lab.post("/llm", mode="real").status_code == 422  # no key in the environment


# ------------------------------------------------------------------ buttons and lists
def test_buttons_map_to_the_right_ids(lab):
    snap = lab.say(RAHUL, CALL_REQUEST)
    msg = Lab.outs(snap)[-1]
    assert len(msg["buttons"]) <= 3
    ids = {b["title"]: b["id"] for b in msg["buttons"]}
    assert re.fullmatch(r"callap:[0-9a-f]+:approve:[0-9a-f]+", ids["Approve"])
    assert re.fullmatch(r"callap:[0-9a-f]+:cancel:[0-9a-f]+", ids["Cancel"])
    assert re.fullmatch(r"callap:[0-9a-f]+:edit:[0-9a-f]+", ids["Edit"])
    snap = lab.post("/tap", phone=RAHUL, message_id=msg["id"], button_id=ids["Cancel"]).json()
    sent = next(e for e in snap["entries"] if e["seq"] == snap["turn"]["input_seq"])
    assert sent["kind"] == "button_reply" and sent["button_id"] == ids["Cancel"]
    assert sent["text"] == "Cancel"
    # a button that is not on that message, or a message that does not exist, is refused
    assert (
        lab.post(
            "/tap", phone=RAHUL, message_id=msg["id"], button_id="callap:x:approve"
        ).status_code
        == 422
    )
    assert (
        lab.post("/tap", phone=RAHUL, message_id="nope", button_id=ids["Approve"]).status_code
        == 422
    )


def test_typing_a_number_taps_the_numbered_button_like_the_simulator(lab):
    snap = lab.say(RAHUL, CALL_REQUEST)
    snap = lab.say(RAHUL, "1")  # "1" = Approve, same as `friday chat`
    assert snap["turn"]["calls"]


def test_list_messages_render_as_a_picker_and_map_to_ids(lab):
    from friday.core.models import Channel, OutboundMessage

    class WithList(OutboundMessage):
        list_message: dict | None = None

    msg = WithList(
        channel=Channel.SIMULATOR,
        to_phone=RAHUL,
        text="Pick one",
        list_message={
            "title": "Options",
            "button": "Choose",
            "sections": [{"title": "A", "items": [{"id": "pick:1", "title": "One"}]}],
        },
    )
    lab.world._on_out(msg)  # noqa: SLF001 - the lab shows whatever the channel sends
    snap = lab.get("/state", phone=RAHUL).json()
    entry = snap["entries"][-1]
    assert entry["list"]["sections"][0]["items"][0]["id"] == "pick:1"
    inbound = lab.world.inbound_button(RAHUL, entry["id"], "pick:1")
    assert inbound.button_id == "pick:1" and inbound.text == "One"


# ------------------------------------------------------------------ attachments
def test_attachments_arrive_as_the_right_message_kinds(lab):
    snap = lab.post("/location", phone=RAHUL, lat=28.4595, lng=77.0266).json()
    e = [x for x in snap["entries"] if x["dir"] == "in"][-1]
    assert e["kind"] == "location"
    assert (e["location"]["lat"], e["location"]["lng"]) == (28.4595, 77.0266)
    snap = lab.post("/contact", phone=RAHUL, name="Neha", number="+919000000010").json()
    e = [x for x in snap["entries"] if x["dir"] == "in"][-1]
    assert e["kind"] == "contact" and e["text"] == "Neha"
    assert e["contact_phone"] == "+91******0010"  # masked in the page
    snap = lab.post("/voice", phone=RAHUL, says="mera din").json()
    e = [x for x in snap["entries"] if x["dir"] == "in"][-1]
    assert e["kind"] == "voice_note" and e["text"] == "mera din"
    assert snap["turn"]["route"]["handler"] in ("consumer._my_day", "consumer._call_turn")
    snap = lab.post("/sample", phone=RAHUL, name="electricity-bill.pdf").json()
    assert [x for x in snap["entries"] if x["dir"] == "in"][-1]["kind"] == "document"
    snap = lab.post("/sample", phone=RAHUL, name="restaurant-receipt.jpg").json()
    assert [x for x in snap["entries"] if x["dir"] == "in"][-1]["kind"] == "image"
    r = lab.client.post(
        lab.url("/file"),
        data={"phone": RAHUL},
        files={"file": ("pic.png", b"\x89PNG fake", "image/png")},
    )
    assert r.status_code == 200
    assert [x for x in r.json()["entries"] if x["dir"] == "in"][-1]["kind"] == "image"
    r = lab.client.post(
        lab.url("/file"),
        data={"phone": RAHUL},
        files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
    )
    assert r.status_code == 422
    assert lab.post("/voice", phone=RAHUL, says="  ").status_code == 422
    assert lab.post("/location", phone=RAHUL, lat=120, lng=0).status_code == 422
    assert lab.post("/sample", phone=RAHUL, name="../../etc/passwd").status_code == 422


# ------------------------------------------------------------------ the clock
def test_next_morning_triggers_the_morning_brief(lab):
    lab.say(RAHUL, "kal 2 baje interview hai")
    before = len(lab.get("/state", phone=RAHUL).json()["entries"])
    snap = lab.post("/advance", phone=RAHUL, how="morning").json()
    new = [e for e in snap["entries"][before:] if e["dir"] == "out"]
    assert len(new) == 1 and "interview" in new[0]["text"].lower()
    assert snap["turn"]["route"]["handler"] == "proactive"
    assert snap["clock"]["label"].endswith("08:10")
    assert any(e["dir"] == "sys" and "next morning" in e["text"] for e in snap["entries"])
    # once a day: another tick adds nothing
    again = lab.post("/advance", phone=RAHUL, how="hour").json()
    assert not [e for e in again["entries"][len(snap["entries"]) :] if e["dir"] == "out"]


def test_a_user_who_did_not_opt_in_gets_no_morning_brief(lab):
    lab.say(PRIYA, "kal 2 baje interview hai")
    snap = lab.post("/advance", phone=PRIYA, how="morning").json()
    assert not any("Suprabhat" in (e.get("text") or "") for e in snap["entries"])


def test_advancing_the_clock_moves_it_and_validates_input(lab):
    t0 = lab.get("/state", phone=RAHUL).json()["clock"]["iso"]
    t1 = lab.post("/advance", phone=RAHUL, how="hour").json()["clock"]["iso"]
    assert t1 > t0
    assert lab.post("/advance", phone=RAHUL, how="week").status_code == 422


# ------------------------------------------------------------------ switches, users, reset
def test_a_session_switch_changes_the_routing_live(lab):
    sw = lab.post("/switch", name="calls", on=False).json()
    assert sw["consumer"]["calls"]["on"] is False
    snap = lab.say(RAHUL, CALL_REQUEST)
    assert snap["turn"]["route"]["handler"] != "consumer._call_turn"
    assert snap["switches"]["consumer"]["calls"]["on"] is False
    lab.post("/switch", name="calls", on=True)
    snap = lab.say(RAHUL, CALL_REQUEST)
    assert snap["turn"]["route"]["handler"] == "consumer._call_turn"


def test_latency_switches_are_toggles_with_env_names(lab):
    sw = lab.post("/switch", name="intent_classifier", on=True).json()
    assert sw["latency"]["intent_classifier"] == {"on": True, "env": "FRIDAY_INTENT_CLASSIFIER"}
    assert lab.world.settings.intent_classifier is True
    sw = lab.post("/switch", name="intent_classifier", on=False).json()
    assert sw["latency"]["intent_classifier"]["on"] is False
    assert set(sw["consumer"]) == {"calls", "savings", "lifestate", "google"}


def test_reset_clears_the_chat_and_pending_state(lab):
    lab.say(RAHUL, CALL_REQUEST)
    snap = lab.post("/reset", phone=RAHUL).json()
    assert snap["entries"] == [] and snap["turn"] is None
    snap = lab.say(RAHUL, "1")  # the old Approve button is gone: "1" is just a message now
    assert not snap["turn"]["calls"]


def test_users_have_separate_chats(lab):
    lab.say(RAHUL, "menu")
    assert lab.get("/state", phone=PRIYA).json()["entries"] == []
    assert lab.get("/state", phone="+919800009999").status_code == 422


# ------------------------------------------------------------------ the side panel data
def test_the_panel_data_for_a_turn(lab):
    snap = lab.say(RAHUL, "kal 2 baje interview hai")
    t = snap["turn"]
    assert t["route"] == {
        "handler": "consumer._capture_turn",
        "label": "life capture (events and commitments)",
    }
    assert t["answered_by"] == "rules (no model call)"
    assert t["slots"]["life_capture"]["events"][0]["kind"] == "interview"
    assert t["guards"] and {g["gate"] for g in t["guards"]} >= {"inbound_throttle"}
    assert set(t["latency_ms"]) == {"total", "stages", "llm"} and t["latency_ms"]["total"] > 0
    assert "lifestate.copy.confirm_event" in t["copy_keys"]
    assert snap["user"]["language"] == "hinglish" and snap["user"]["name"] == "R****"
    assert snap["user"]["life_events"][0]["kind"] == "interview"
    assert "consumer_router" in {s["name"] for s in t["stages"]}
    # a turn the brain (fake model) answers shows intent, confidence and the model call
    snap = lab.say(RAHUL, "mausam kaisa hai")
    t = snap["turn"]
    assert t["interpretation"]["intent"] and "confidence" in t["interpretation"]
    assert t["route"]["handler"] in ("brain", "quotes_flow", "pm_gateway")
    assert t["classifier"].startswith("not used")


def test_tapping_an_old_bubble_returns_its_own_turn(lab):
    first = lab.say(RAHUL, "kal 2 baje interview hai")
    lab.say(RAHUL, "mera din")
    seq = first["turn"]["output_seqs"][0]
    t = lab.get("/turn", phone=RAHUL, seq=seq).json()
    assert t["input_seq"] == first["turn"]["input_seq"]
    assert lab.get("/turn", phone=RAHUL, seq=999999).status_code == 404


# ------------------------------------------------------------------ notes and export
def test_mark_wrong_appends_to_the_notes_file(lab):
    snap = lab.say(RAHUL, "mera din")
    seq = Lab.outs(snap)[0]["seq"]
    assert lab.post(
        "/mark-wrong", phone=RAHUL, seq=seq, note="should list the interview"
    ).json() == {"ok": True}
    lines = (lab.tmp / "notes.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[-1])
    assert rec["note"] == "should list the interview" and rec["input"] == "mera din"
    assert rec["route"]["handler"] and rec["reply"]["text"]
    assert lab.get("/state", phone=RAHUL).json()["entries"][-1]["mark"] == "wrong"
    assert lab.post("/mark-wrong", phone=RAHUL, seq=123456, note="x").status_code == 422


def test_export_is_a_real_download_with_chat_and_panel(lab):
    lab.say(RAHUL, "kal 2 baje interview hai")
    snap = lab.say(RAHUL, CALL_REQUEST)
    lab.tap(RAHUL, "Approve", snap)
    md = lab.get("/export.md", phone=RAHUL)
    assert md.status_code == 200
    assert md.headers["content-disposition"].startswith("attachment;")
    assert md.headers["content-type"].startswith("text/markdown")
    assert "# Friday Chat Lab transcript" in md.text and "Inside each turn" in md.text
    assert "interview" in md.text and "button `callap:" in md.text and "simulated call" in md.text
    js = lab.get("/export.json", phone=RAHUL)
    assert js.headers["content-disposition"].startswith("attachment;")
    data = js.json()
    assert data["user"].startswith("Rahul") and len(data["turns"]) == 3
    assert data["messages"] and data["switches"]["consumer"]["calls"]["on"] is True
    assert lab.get("/export.md", phone="+919800009999").status_code == 422


# ------------------------------------------------------------------ nothing secret, nothing real
def test_no_secret_or_real_phone_number_in_any_response(make_lab, monkeypatch):
    for k, v in SECRET_ENV.items():
        monkeypatch.setenv(k, v)
    lab = make_lab()
    lab.client.get(f"/lab/{lab.token}/")
    snap = lab.say(RAHUL, CALL_REQUEST)
    lab.tap(RAHUL, "Approve", snap)
    lab.say(RAHUL, "Zomato pe 640")
    lab.post("/contact", phone=RAHUL, name="Neha", number="+919000000010")
    lab.post("/advance", phone=RAHUL, how="morning")
    lab.get("/export.md", phone=RAHUL)
    lab.get("/export.json", phone=RAHUL)
    lab.get("/config")
    everything = "\n".join(lab.bodies)
    assert everything
    for v in SECRET_ENV.values():
        assert v not in everything
    assert not re.search(r"sk-[A-Za-z0-9-]{8,}|Bearer\s+\S+|EAAG", everything)
    for m in PHONE_RE.findall(everything):
        digits = re.sub(r"\D", "", m)
        assert re.fullmatch(r"91(9800|9000)\d{6}", digits), f"unexpected number {m!r}"
    assert lab.token not in everything  # responses never echo the access token


def test_the_real_model_toggle_exists_only_with_a_key_and_is_off_by_default(make_lab):
    from friday.brain.fake_llm import FakeLLM
    from friday.core.config import Settings

    env = Settings(_env_file=None, mode="simulator", anthropic_api_key="sk-ant-test-not-real")
    lab = make_lab(env=env)
    cfg = lab.get("/config").json()
    assert cfg["llm"] == {"mode": "fake", "real_available": True}
    brain = lab.world.runtime.pipeline.brain()
    assert isinstance(brain.llm, FakeLLM)
    assert lab.post("/llm", mode="real").json() == {"mode": "real"}  # builds the client only
    assert not isinstance(brain.llm, FakeLLM)
    assert lab.post("/llm", mode="fake").json() == {"mode": "fake"}
    assert isinstance(brain.llm, FakeLLM)
    assert "sk-ant-test-not-real" not in "\n".join(lab.bodies)
