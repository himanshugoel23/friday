"""Device API: auth, pairing, isolation, limits, schema rejection of free text, consent, SOS/stop/voice, erase."""

from __future__ import annotations

import logging

import pytest

from friday.robindevice.api import LIMITS, MAX_BODY, RateLimiter
from friday.robindevice.schemas import SIGNAL_CONSENT, validate_event
from friday.robindevice.store import sha256_hex

from .conftest import MIN, ev

B = "/robin/device"


async def post(rig, token, path, body, **kw):
    return await rig.client.post(f"{B}{path}", headers=rig.h(token) if token else {}, json=body, **kw)


# ----------------------------------------------------------------------------- auth and pairing


@pytest.mark.parametrize("method,path", [
    ("post", "/heartbeat"), ("post", "/signals"), ("post", "/share"), ("post", "/ack"), ("post", "/sos"),
    ("post", "/voice"), ("get", "/prompts"), ("get", "/consent"), ("put", "/consent"), ("post", "/pause"),
    ("post", "/stop"), ("post", "/resume"), ("get", "/transparency"), ("delete", "/erase"),
])
async def test_bad_token_is_404_everywhere(rig, method, path):
    await rig.pair()
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic abc"}):
        r = await rig.client.request(method.upper(), f"{B}{path}", headers=headers, json={} if method != "get" else None)
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


async def test_pairing_code_single_use_expires_and_token_is_hashed(rig):
    rig.parents.add("p1", "en")
    code = await rig.service.create_pairing_code("p1")
    body = {"code": code, "app_version": "1.0.0", "os_sdk": 34}
    r = await rig.client.post(f"{B}/pair", json=body)
    assert r.status_code == 200
    token = r.json()["device_token"]
    assert token.startswith("rbn_") and len(token) > 40 and r.json()["brand"] == "Robin"
    assert (await rig.client.post(f"{B}/pair", json=body)).status_code == 404  # used
    st = rig.service.store.peek("p1")
    assert st.device.token_hash == sha256_hex(token) and token not in repr(st)
    code2 = await rig.service.create_pairing_code("p1")
    rig.clock.advance(minutes=16)
    r = await rig.client.post(f"{B}/pair", json={**body, "code": code2})
    assert r.status_code == 404  # expired


async def test_unknown_parent_cannot_get_a_code_and_bad_code_is_404(rig):
    with pytest.raises(KeyError):
        await rig.service.create_pairing_code("ghost")
    r = await rig.client.post(f"{B}/pair", json={"code": "ABCDEFGH", "app_version": "1.0", "os_sdk": 34})
    assert r.status_code == 404


async def test_one_device_per_parent_new_pairing_revokes_old(rig):
    t1 = await rig.pair()
    code = await rig.service.create_pairing_code("p1")
    r = await rig.client.post(f"{B}/pair", json={"code": code, "app_version": "1.0.1", "os_sdk": 34})
    t2 = r.json()["device_token"]
    assert (await rig.client.get(f"{B}/prompts", headers=rig.h(t1))).status_code == 404
    assert (await rig.client.get(f"{B}/prompts", headers=rig.h(t2))).status_code == 200


async def test_revoke(rig):
    t = await rig.pair()
    assert await rig.service.revoke("p1")
    assert (await rig.client.get(f"{B}/prompts", headers=rig.h(t))).status_code == 404


async def test_pair_rate_limited(rig):
    statuses = []
    for _ in range(LIMITS["pair"][0] + 2):
        r = await rig.client.post(f"{B}/pair", json={"code": "ABCDEFGH", "app_version": "1.0", "os_sdk": 34})
        statuses.append(r.status_code)
    assert statuses[-1] == 429 and statuses[0] == 404


# ----------------------------------------------------------------------------- heartbeat


async def test_heartbeat_records_roles_and_battery(rig):
    t = await rig.pair()
    r = await post(rig, t, "/heartbeat", {"app_version": "1.2.3", "os_sdk": 34, "battery_low": True, "ts_ms": rig.clock.ms,
                                          "roles": {"call_screening": True, "notification_access": True}})
    assert r.status_code == 200
    j = r.json()
    assert j["paused"] is False and j["consent"]["calls"] is True and j["prompts"] == []
    dev = rig.service.store.peek("p1").device
    assert dev.roles["call_screening"] and dev.battery_low and dev.app_version == "1.2.3"


async def test_heartbeat_rejects_extra_fields(rig):
    t = await rig.pair()
    r = await post(rig, t, "/heartbeat", {"app_version": "1.0", "os_sdk": 34, "ts_ms": rig.clock.ms, "roles": {},
                                          "device_name": "Ramesh's phone"})
    assert r.status_code == 422 and "Ramesh" not in r.text


# ----------------------------------------------------------------------------- schemas: no free text


FREE_TEXT = [
    ("payment_notification", dict(app="gpay", direction="debit", amount_paise=100, payee_kind="new", text="Rs 100 paid to Ramesh")),
    ("payment_notification", dict(app="gpay", direction="debit", amount_paise=100, payee_kind="new", payee="Ramesh Kumar")),
    ("payment_notification", dict(app="gpay", direction="debit", amount_paise=100, payee_kind="Ramesh")),
    ("payment_notification", dict(app="my own bank text", direction="debit", amount_paise=100, payee_kind="new")),
    ("payment_notification", dict(app="gpay", direction="debit", amount_paise="100", payee_kind="new")),
    ("unknown_call_started", dict(call_id="c1", number_class="mobile", number="+919876543210")),
    ("unknown_call_started", dict(call_id="c1", number_class="mobile", contact_name="Mom")),
    ("unknown_call_started", dict(call_id="c1", number_class="9876543210")),
    ("unknown_call_started", dict(call_id="c1", number_class="mobile", number_hash="+919876543210")),
    ("remote_access_app_opened", dict(app="com.anydesk.anydeskandroid")),
    ("remote_access_app_opened", dict(app="anydesk", title="AnyDesk - session with Rajan")),
    ("payment_app_foreground", dict(app="gpay", screen_text="Enter PIN")),
    ("camera_in_use_start", dict(app="whatsapp")),
    ("call_state_offhook", dict(duration_s=10, ongoing=True, transcript="hello")),
    ("app_installed_unknown_source", dict(source_class="browser", package="com.evil")),
    ("phone_heartbeat_missing", dict(gap_s=3600, note="phone off")),
]


@pytest.mark.parametrize("type_,fields", FREE_TEXT, ids=[f"{i}-{t}" for i, (t, _) in enumerate(FREE_TEXT)])
async def test_free_text_and_unknown_fields_are_rejected_not_stored(rig, type_, fields):
    t = await rig.pair()
    r = await post(rig, t, "/signals", {"events": [ev(type_, rig.clock.ms, **fields)]})
    assert r.status_code == 200
    j = r.json()
    assert j["accepted"] == 0 and j["invalid"] == 1
    assert j["invalid_detail"][0]["reason"] in {"extra_field", "bad_value"}
    for leaked in ("Ramesh", "Rajan", "Mom", "9876543210", "hello", "whatsapp", "com.evil"):
        assert leaked not in r.text
    assert rig.service.store.peek("p1").events == []


def test_every_signal_type_has_a_consent_item_and_a_schema():
    assert len(SIGNAL_CONSENT) == 11
    ok = {
        "unknown_call_started": dict(call_id="c1", number_class="international"),
        "unknown_call_ended": dict(call_id="c1", duration_s=5, answered=False),
        "call_state_offhook": dict(duration_s=5, ongoing=True),
        "camera_in_use_start": {}, "camera_in_use_stop": {},
        "remote_access_app_opened": dict(app="anydesk"), "remote_access_app_installed": dict(app="other_remote"),
        "payment_app_foreground": dict(app="phonepe"),
        "payment_notification": dict(app="gpay", direction="credit", amount_paise=1, payee_kind="merchant"),
        "app_installed_unknown_source": dict(source_class="unknown"),
        "phone_heartbeat_missing": dict(gap_s=600),
    }
    for t, fields in ok.items():
        e, reason = validate_event({"id": "abcdefgh1", "type": t, "ts_ms": 1_800_000_000_000, **fields})
        assert reason is None, (t, reason)


async def test_bad_event_does_not_block_the_batch(rig):
    t = await rig.pair()
    good = ev("camera_in_use_start", rig.clock.ms)
    bad = ev("payment_notification", rig.clock.ms, app="gpay", direction="debit", amount_paise=5, payee_kind="new", text="x")
    unknown = ev("sms_received", rig.clock.ms)
    r = await post(rig, t, "/signals", {"events": [bad, good, unknown, "oops"]})
    j = r.json()
    assert j["accepted"] == 1 and j["invalid"] == 3
    assert [d["reason"] for d in j["invalid_detail"]] == ["extra_field", "unknown_type", "not_an_object"]


async def test_dedupe_stale_and_future_timestamps(rig):
    t = await rig.pair()
    e = ev("camera_in_use_start", rig.clock.ms)
    await post(rig, t, "/signals", {"events": [e]})
    j = (await post(rig, t, "/signals", {"events": [e]})).json()
    assert j["duplicates"] == 1 and j["accepted"] == 0
    old = ev("camera_in_use_stop", rig.clock.ms - 72 * 60 * MIN)
    future = ev("camera_in_use_stop", rig.clock.ms + 30 * MIN)
    j = (await post(rig, t, "/signals", {"events": [old, future]})).json()
    assert j["stale"] == 2


# ----------------------------------------------------------------------------- limits


async def test_body_too_large_is_413_and_batch_too_long_is_422(rig):
    t = await rig.pair()
    r = await rig.client.post(f"{B}/signals", headers={**rig.h(t), "content-type": "application/json"},
                              content=b'{"events": [' + b"{}," * (MAX_BODY // 3 + 10) + b"{}]}")
    assert r.status_code == 413
    r = await post(rig, t, "/signals", {"events": [{}] * 101})
    assert r.status_code == 422


async def test_rate_limit_per_device(rig):
    t = await rig.pair()
    codes = [(await rig.client.get(f"{B}/prompts", headers=rig.h(t))).status_code for _ in range(LIMITS["prompts"][0] + 3)]
    assert codes[0] == 200 and codes[-1] == 429
    t2 = await rig.pair("p2")  # another parent is not affected
    assert (await rig.client.get(f"{B}/prompts", headers=rig.h(t2))).status_code == 200


def test_rate_limiter_window():
    now = [0.0]
    rl = RateLimiter(lambda: now[0])
    assert all(rl.allow("k", "erase") for _ in range(3)) and not rl.allow("k", "erase")
    now[0] = 61
    assert rl.allow("k", "erase")


# ----------------------------------------------------------------------------- consent


async def test_signal_without_consent_is_dropped_and_counted(rig):
    t = await rig.pair(grant=False)
    rig.consent.granted["p1"] = {"camera"}
    batch = [ev("camera_in_use_start", rig.clock.ms), ev("remote_access_app_opened", rig.clock.ms, app="anydesk"),
             ev("payment_notification", rig.clock.ms, app="gpay", direction="debit", amount_paise=9_000_000, payee_kind="new")]
    j = (await post(rig, t, "/signals", {"events": batch})).json()
    assert j["accepted"] == 1 and j["dropped_no_consent"] == 2
    st = rig.service.store.peek("p1")
    assert st.counters["dropped_no_consent:remote_access_app_opened"] == 1
    assert [e.type for e in st.events] == ["camera_in_use_start"]
    assert rig.alerts.calls == [] and st.prompts == {}  # a dropped payment never raised anything


async def test_phone_can_only_withdraw_consent_and_withdrawal_erases(rig):
    t = await rig.pair()
    await post(rig, t, "/signals", {"events": [ev("camera_in_use_start", rig.clock.ms)]})
    assert len(rig.service.store.peek("p1").events) == 1
    r = await rig.client.put(f"{B}/consent", headers=rig.h(t), json={"items": {"camera": True}})
    assert r.status_code == 403 and r.json()["error"] == "consent_given_by_family_admin"
    r = await rig.client.put(f"{B}/consent", headers=rig.h(t), json={"items": {"camera": False}})
    assert r.status_code == 200 and r.json()["items"]["camera"] is False and r.json()["consent_basis"] == "admin_on_behalf"
    assert rig.service.store.peek("p1").events == []
    r = await rig.client.put(f"{B}/consent", headers=rig.h(t), json={"items": {"nonsense": False}})
    assert r.status_code == 422
    j = (await post(rig, t, "/signals", {"events": [ev("camera_in_use_start", rig.clock.ms)]})).json()
    assert j["dropped_no_consent"] == 1


async def test_admin_grants_consent_on_parents_behalf(rig):
    t = await rig.pair(grant=False)
    assert (await rig.client.get(f"{B}/consent", headers=rig.h(t))).json()["items"]["camera"] is False
    await rig.service.admin_set_consent("p1", {"camera": True})
    assert (await rig.client.get(f"{B}/consent", headers=rig.h(t))).json()["items"]["camera"] is True


# ----------------------------------------------------------------------------- isolation


async def test_parents_are_isolated(rig):
    ta = await rig.pair("pa")
    tb = await rig.pair("pb")
    await post(rig, ta, "/signals", {"events": [ev("remote_access_app_opened", rig.clock.ms, app="anydesk")]})
    assert [a["parent_id"] for a in rig.alerts.calls] == ["pa"]
    assert rig.service.store.peek("pb").events == []
    assert (await rig.client.get(f"{B}/transparency", headers=rig.h(tb))).json()["told_child"] == []
    assert (await rig.client.get(f"{B}/prompts", headers=rig.h(tb))).json()["prompts"] == []
    pid = (await rig.client.get(f"{B}/prompts", headers=rig.h(ta))).json()["prompts"][0]["prompt_id"]
    r = await post(rig, tb, "/ack", {"kind": "this_was_fine", "prompt_id": pid})
    assert r.status_code == 404  # parent B cannot touch parent A's prompt
    await rig.client.delete(f"{B}/erase", headers=rig.h(tb))
    assert rig.service.store.peek("pa") is not None and rig.service.store.peek("pb") is None
    st_a = rig.service.store.peek("pa")
    assert st_a.prompts[pid].state == "open"


# ----------------------------------------------------------------------------- SOS, stop, voice, pause, erase


async def test_sos_always_works_even_stopped_and_in_shadow_week(rig):
    t = await rig.pair(shadow_days=7, grant=False)
    await post(rig, t, "/stop", {})
    r = await post(rig, t, "/sos", {})
    assert r.status_code == 200 and "112" in r.json()["message"]
    (a,) = [x for x in rig.alerts.calls if x["scenario"] == "SOS"]
    assert a["tier"] == "EMERGENCY" and a["details"] == {}
    r = await post(rig, t, "/ack", {"kind": "sos", "location": {"lat": 28.6, "lon": 77.2}})
    assert r.status_code == 200
    last = [x for x in rig.alerts.calls if x["scenario"] == "SOS"][-1]
    assert "location" not in last["details"]  # no location consent: dropped
    await rig.service.admin_set_consent("p1", {"location": True})
    await post(rig, t, "/sos", {"lat": 28.6, "lon": 77.2})
    last = [x for x in rig.alerts.calls if x["scenario"] == "SOS"][-1]
    assert last["details"]["location"] == {"lat": 28.6, "lon": 77.2}
    assert (await post(rig, t, "/sos", {"lat": 999, "lon": 0})).status_code == 422


async def test_parent_stop_drops_signals_until_the_parent_resumes(rig):
    t = await rig.pair()
    r = await post(rig, t, "/stop", {})
    assert r.json() == {"stopped": True, "paused": True}
    assert any(a["scenario"] == "STOP" and a["tier"] == "WATCH" for a in rig.alerts.calls)
    j = (await post(rig, t, "/signals", {"events": [ev("remote_access_app_opened", rig.clock.ms, app="anydesk")]})).json()
    assert j["dropped_paused"] == 1 and j["accepted"] == 0
    rig.clock.advance(hours=30)  # a pause never times out by itself
    hb = await post(rig, t, "/heartbeat", {"app_version": "1", "os_sdk": 34, "ts_ms": rig.clock.ms, "roles": {}})
    assert hb.json()["paused"] is True
    assert not hasattr(rig.service, "admin_resume")  # there is no family-side resume
    assert (await post(rig, t, "/resume", {})).json() == {"paused": False}
    j = (await post(rig, t, "/signals", {"events": [ev("camera_in_use_start", rig.clock.ms)]})).json()
    assert j["accepted"] == 1


async def test_timed_pause_and_resume(rig):
    t = await rig.pair()
    assert (await post(rig, t, "/pause", {"minutes": 30})).json()["paused"] is True
    assert (await post(rig, t, "/pause", {"minutes": 1})).status_code == 422
    rig.clock.advance(minutes=31)
    j = (await post(rig, t, "/signals", {"events": [ev("camera_in_use_start", rig.clock.ms)]})).json()
    assert j["accepted"] == 1


async def test_voice_upload_limits_and_not_stored(rig):
    t = await rig.pair()
    h = {**rig.h(t), "content-type": "audio/ogg", "x-duration-s": "12"}
    r = await rig.client.post(f"{B}/voice", headers=h, content=b"OggS" + b"\0" * 2000)
    assert r.status_code == 200 and r.json()["accepted"] is True
    assert rig.voice.received == [{"parent_id": "p1", "bytes": 2004, "mime": "audio/ogg", "duration_s": 12}]
    for bad in ({"content-type": "text/plain"}, {"x-duration-s": "61"}, {"x-duration-s": "0"}, {"x-duration-s": "abc"}):
        r = await rig.client.post(f"{B}/voice", headers={**h, **bad}, content=b"x" * 10)
        assert r.status_code == 422
    r = await rig.client.post(f"{B}/voice", headers=h, content=b"x" * (1_048_576 + 5))
    assert r.status_code == 413
    r = await rig.client.post(f"{B}/voice", headers=h, content=b"")
    assert r.status_code == 422
    assert "audio" not in repr(rig.service.store.peek("p1").__dict__).lower().replace("audio/", "")


async def test_voice_needs_consent_but_works_while_paused(rig):
    t = await rig.pair(grant=False)
    h = {**rig.h(t), "content-type": "audio/mp4", "x-duration-s": "5"}
    assert (await rig.client.post(f"{B}/voice", headers=h, content=b"abc")).status_code == 403
    await rig.service.admin_set_consent("p1", {"voice_messages": True})
    await post(rig, t, "/stop", {})
    assert (await rig.client.post(f"{B}/voice", headers=h, content=b"abc")).status_code == 200


async def test_share_intake_scam_check_and_child_alert(rig):
    t = await rig.pair(language="hinglish")
    r = await post(rig, t, "/share", {"kind": "text", "value": "Sir apna OTP bata dijiye abhi, warna khata band"})
    j = r.json()
    assert r.status_code == 200 and j["verdict"] == "SCAM_LIKELY" and j["child_told"] is True
    assert j["reason"].startswith("Ismein")
    (a,) = [x for x in rig.alerts.calls if x["scenario"] == "SHARE"]
    assert a["tier"] == "HIGH" and "OTP" not in str(a) and "bata" not in str(a)
    again = (await post(rig, t, "/share", {"kind": "text", "value": "Sir apna OTP bata dijiye abhi"})).json()
    assert again["child_told"] is False  # same category within 10 minutes: no second alert
    st = rig.service.store.peek("p1")
    assert "OTP" not in repr(st.__dict__)  # shared text is not stored


async def test_share_requires_consent_and_validates(rig):
    t = await rig.pair(grant=False)
    assert (await post(rig, t, "/share", {"kind": "text", "value": "hello"})).status_code == 403
    await rig.service.admin_set_consent("p1", {"share_check": True})
    assert (await post(rig, t, "/share", {"kind": "sms", "value": "x"})).status_code == 422
    assert (await post(rig, t, "/share", {"kind": "text", "value": "x" * 2001})).status_code == 422
    assert (await post(rig, t, "/share", {"kind": "screenshot_ref", "value": "not a ref!"})).status_code == 422
    r = await post(rig, t, "/share", {"kind": "screenshot_ref", "value": "shot_abc12345"})
    assert r.json()["verdict"] == "UNSURE" and r.json()["child_told"] is False
    r = await post(rig, t, "/share", {"kind": "text", "value": "Share your OTP now"})
    assert r.json()["verdict"] == "SCAM_LIKELY" and r.json()["child_told"] is False  # no share_alert_child consent


async def test_erase_deletes_everything_and_revokes(rig):
    t = await rig.pair()
    await post(rig, t, "/signals", {"events": [ev("camera_in_use_start", rig.clock.ms)]})
    r = await rig.client.delete(f"{B}/erase", headers=rig.h(t))
    assert r.json() == {"erased": True, "events_deleted": 1}
    assert rig.service.store.peek("p1") is None
    assert (await rig.client.get(f"{B}/prompts", headers=rig.h(t))).status_code == 404
    assert any(a["scenario"] == "ERASE" for a in rig.alerts.calls)


async def test_transparency_shows_what_child_was_told(rig):
    t = await rig.pair()
    await post(rig, t, "/signals", {"events": [ev("remote_access_app_opened", rig.clock.ms, app="rustdesk")]})
    j = (await rig.client.get(f"{B}/transparency", headers=rig.h(t))).json()
    assert j["told_child"][0]["scenario"] == "S2" and "rustdesk" in j["told_child"][0]["why"]
    assert j["counters"]["accepted:remote_access_app_opened"] == 1
    assert "messages or SMS" in j["never_collected"] and j["learning_mode"]["active"] is False


async def test_no_token_or_secret_in_logs(rig, caplog):
    caplog.set_level(logging.DEBUG)
    t = await rig.pair()
    await post(rig, t, "/signals", {"events": [ev("camera_in_use_start", rig.clock.ms)]})
    await rig.client.get(f"{B}/prompts", headers=rig.h("rbn_wrongtoken1234567890"))
    assert t not in caplog.text and "wrongtoken" not in caplog.text
