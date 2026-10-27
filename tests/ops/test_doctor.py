"""``friday doctor``: every section's OK/WARN/FAIL decision, with fakes and local data only."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, text

from friday import cli
from friday.core.config import Settings
from friday.db import migrate
from friday.ops import doctor as d

PLANTED = {
    "verify": "PLANTED-verify-token-7731",
    "meta": "PLANTED-meta-access-token-5521",
    "app": "PLANTED-app-secret-9917",
    "anthropic": "PLANTED-anthropic-key-4410",
    "sarvam": "PLANTED-sarvam-key-3308",
    "vobiz": "PLANTED-vobiz-token-2204",
    "dbpass": "PLANTED-db-password-1109",
}
BASE = "https://friday.example.com"


def statuses(section: d.Section) -> list[str]:
    return [c.status for c in section.checks]


def messages(section: d.Section) -> str:
    return "\n".join(c.message for c in section.checks)


def mk(tmp_path: Path, **kw) -> Settings:
    kw.setdefault("database_url", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    kw.setdefault("pause_file", str(tmp_path / "var" / "PAUSED"))
    return Settings(_env_file=None, env="test", **kw)


def live(tmp_path: Path, **kw) -> Settings:
    base = dict(
        mode="live", whatsapp_provider="cloud", public_base_url=BASE,
        whatsapp_verify_token=PLANTED["verify"], whatsapp_access_token=PLANTED["meta"],
        whatsapp_phone_number_id="12345", whatsapp_app_secret=PLANTED["app"],
        anthropic_api_key=PLANTED["anthropic"], sarvam_api_key=PLANTED["sarvam"],
        sarvam_telephony_auth_id="AUTHID", sarvam_telephony_auth_token=PLANTED["vobiz"],
    )
    return mk(tmp_path, **(base | kw))


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("tpl") / "tpl.db"
    migrate.upgrade(f"sqlite+aiosqlite:///{p}")
    return p


@pytest.fixture
def db_settings(tmp_path, migrated_db) -> Settings:
    target = tmp_path / "t.db"
    shutil.copy(migrated_db, target)
    return mk(tmp_path)


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------------- settings
def test_settings_simulator_warns_not_fails(tmp_path):
    s = d.check_settings(mk(tmp_path))
    assert d.FAIL not in statuses(s) and d.WARN in statuses(s)


def test_settings_live_lists_missing_and_unsafe_names_only(tmp_path):
    st = mk(tmp_path, mode="live", whatsapp_provider="cloud", whatsapp_app_secret=PLANTED["app"])
    s = d.check_settings(st)
    text_ = messages(s)
    assert d.FAIL in statuses(s)
    assert "missing: WHATSAPP_ACCESS_TOKEN" in text_
    assert "FRIDAY_SECRET_KEY" in text_  # unsafe: still the development default
    assert PLANTED["app"] not in text_


# ------------------------------------------------------------------------- database
def test_database_ok_at_head(db_settings):
    s = run(d.check_database(db_settings))
    assert d.FAIL not in statuses(s), messages(s)
    assert f"at head ({d.code_head()})" in messages(s)
    assert d.code_head() == "0015_urgent_escalation"
    assert "SQLite" in messages(s) and d.SKIP in statuses(s)  # RLS skipped on SQLite


def test_database_wrong_revision_fails(db_settings, tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db")
    with eng.begin() as c:
        c.execute(text("update alembic_version set version_num='0007_consumer_calls'"))
    s = run(d.check_database(db_settings))
    assert d.FAIL in statuses(s)
    assert "database at 0007_consumer_calls, code expects 0015_urgent_escalation" in messages(s)


def test_database_missing_table_fails_and_names_it(db_settings, tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db")
    with eng.begin() as c:
        c.execute(text("drop table life_followups"))
    s = run(d.check_database(db_settings))
    assert any(c.status == d.FAIL and "life_followups" in c.message for c in s.checks)


def test_database_never_migrated_fails(tmp_path):
    s = run(d.check_database(mk(tmp_path)))
    assert any(c.status == d.FAIL and "never been applied" in c.message for c in s.checks)


def test_database_unreachable_fails_without_password(tmp_path):
    url = f"postgresql+asyncpg://friday:{PLANTED['dbpass']}@127.0.0.1:1/friday"
    s = run(d.check_database(mk(tmp_path, database_url=url)))
    assert d.FAIL in statuses(s)
    assert PLANTED["dbpass"] not in messages(s)


def test_rls_evaluation():
    off, absent = d.evaluate_rls(["a", "b", "c"], {"a": True, "b": False})
    assert off == ["b"] and absent == ["c"]
    assert d.evaluate_rls(["a"], {"a": True}) == ([], [])


def test_rls_file_lists_known_tables():
    names = d.rls_table_names()
    assert "jobs" in names and "alembic_version" in names


# ------------------------------------------------------------------------- services
def test_services_unconfigured_skips(tmp_path):
    s = run(d.check_services(mk(tmp_path), False, d.Probes()))
    assert statuses(s) == [d.SKIP, d.SKIP]


def test_services_reachable_and_unreachable(tmp_path):
    async def good(url: str) -> None:
        return None

    async def bad(url: str) -> None:
        raise ConnectionError(url)

    st = mk(tmp_path, redis_url="redis://:secretpw@h:6379/0", object_store_url="s3://bkt/p")
    ok = run(d.check_services(st, False, d.Probes(redis_ping=good, object_store_check=good)))
    assert statuses(ok) == [d.OK, d.OK]
    nope = run(d.check_services(st, False, d.Probes(redis_ping=bad, object_store_check=good)))
    assert statuses(nope) == [d.FAIL, d.OK]
    assert "secretpw" not in messages(nope)
    off = run(d.check_services(st, True, d.Probes(redis_ping=bad, object_store_check=bad)))
    assert statuses(off) == [d.SKIP, d.SKIP]


# ------------------------------------------------------------------------- public URL
def site(*, health=("ok", 200), hsts=True, handshake="echo"):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/health":
            headers = {"strict-transport-security": "max-age=1"} if hsts else {}
            return httpx.Response(health[1], json={"status": health[0]}, headers=headers)
        if req.url.path == "/webhooks/whatsapp":
            if handshake == "echo":
                return httpx.Response(200, text=req.url.params["hub.challenge"])
            if handshake == "wrong":
                return httpx.Response(200, text="not-the-challenge")
            return httpx.Response(403, json={"detail": "verification failed"})
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def test_public_url_all_good(tmp_path):
    transport, seen = site()
    s = run(d.check_public_url(live(tmp_path), False, d.Probes(transport=transport)))
    assert statuses(s) == [d.OK, d.OK, d.OK], messages(s)
    # the token only ever went to the server's own URL
    assert {r.url.host for r in seen} == {"friday.example.com"}
    assert all(r.url.scheme == "https" for r in seen)


def test_public_url_wrong_handshake_answer_fails(tmp_path):
    transport, _ = site(handshake="wrong")
    s = run(d.check_public_url(live(tmp_path), False, d.Probes(transport=transport)))
    assert d.FAIL in statuses(s) and "did not echo" in messages(s)


def test_public_url_refused_handshake_fails(tmp_path):
    transport, _ = site(handshake="403")
    s = run(d.check_public_url(live(tmp_path), False, d.Probes(transport=transport)))
    assert "HTTP 403" in messages(s) and d.FAIL in statuses(s)
    assert PLANTED["verify"] not in messages(s)


def test_public_url_no_hsts_warns(tmp_path):
    transport, _ = site(hsts=False)
    s = run(d.check_public_url(live(tmp_path), False, d.Probes(transport=transport)))
    assert d.WARN in statuses(s) and d.FAIL not in statuses(s)


def test_public_url_unreachable_fails(tmp_path):
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=req)

    probes = d.Probes(transport=httpx.MockTransport(boom))
    s = run(d.check_public_url(live(tmp_path), False, probes))
    assert statuses(s) == [d.FAIL] and "ConnectError" in messages(s)


def test_public_url_health_not_ok_fails(tmp_path):
    transport, _ = site(health=("down", 503))
    s = run(d.check_public_url(live(tmp_path), False, d.Probes(transport=transport)))
    assert d.FAIL in statuses(s)


def test_public_url_dev_verify_token_is_unsafe(tmp_path):
    transport, seen = site()
    st = live(tmp_path, whatsapp_verify_token="friday-dev-verify")
    s = run(d.check_public_url(st, False, d.Probes(transport=transport)))
    assert d.FAIL in statuses(s)
    assert all(r.url.path != "/webhooks/whatsapp" for r in seen)


def test_public_url_http_or_local_is_fail_in_live_warn_in_sim(tmp_path):
    st = live(tmp_path, public_base_url="http://localhost:8000")
    assert d.FAIL in statuses(run(d.check_public_url(st, False, d.Probes())))
    sim = mk(tmp_path, public_base_url="http://localhost:8000")
    assert d.WARN in statuses(run(d.check_public_url(sim, True, d.Probes())))


# ------------------------------------------------------------------------- providers
def graph(status=200, body=None):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json=body if body is not None else {"id": "12345"})

    return httpx.MockTransport(handler), seen


def test_providers_meta_valid(tmp_path):
    transport, seen = graph()
    probes = d.Probes(transport=transport)
    s = run(d.check_providers(live(tmp_path, sarvam_telephony_auth_token=None), False, probes))
    assert any(c.status == d.OK and "Meta token is valid" in c.message for c in s.checks)
    assert seen[0].url.host == "graph.facebook.com" and seen[0].url.path.endswith("/12345")
    assert PLANTED["meta"] not in str(seen[0].url)  # header only, never the URL
    assert PLANTED["meta"] not in messages(s)


def test_providers_meta_rejected(tmp_path):
    transport, _ = graph(401, {"error": {"code": 190, "message": PLANTED["meta"]}})
    s = run(d.check_providers(live(tmp_path, sarvam_telephony_auth_token=None), False,
                              d.Probes(transport=transport)))
    assert any(c.status == d.FAIL and "190" in c.message for c in s.checks)
    assert PLANTED["meta"] not in messages(s)


def test_providers_vobiz_read_and_issues(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/auth/me"):
            return httpx.Response(200, json={"enabled": True, "features": {"call_queue": True}})
        if "balance" in req.url.path:
            return httpx.Response(200, json={"available_balance": 120.5, "currency": "INR"})
        return httpx.Response(200, json={"items": [
            {"e164": "+910000000001", "status": "active", "voice_enabled": True}]})

    meta, _ = graph()
    probes = d.Probes(transport=meta, vobiz_transport=httpx.MockTransport(handler))
    s = run(d.check_providers(live(tmp_path), False, probes))
    text_ = messages(s)
    assert "balance 120.5 INR, 1 number(s)" in text_
    assert any(c.status == d.WARN and "call_queue" in c.message for c in s.checks)
    assert "+910000000001" not in text_ and PLANTED["vobiz"] not in text_


def test_providers_key_presence_only(tmp_path):
    s = run(d.check_providers(mk(tmp_path), True, d.Probes()))
    assert "ANTHROPIC_API_KEY is missing" in messages(s)
    s = run(d.check_providers(live(tmp_path), True, d.Probes()))
    assert "ANTHROPIC_API_KEY is set" in messages(s) and PLANTED["anthropic"] not in messages(s)


def test_providers_offline_makes_no_request(tmp_path):
    def boom(req: httpx.Request) -> httpx.Response:
        raise AssertionError("network used while --offline")

    probes = d.Probes(
        transport=httpx.MockTransport(boom), vobiz_transport=httpx.MockTransport(boom)
    )
    s = run(d.check_providers(live(tmp_path), True, probes))
    assert d.SKIP in statuses(s) and d.FAIL not in statuses(s)


# ------------------------------------------------------------------------- switches
def test_switches_report_state_and_count_only(tmp_path):
    st = mk(tmp_path, consumer_calls_enabled=True, google_enabled=True,
            pilot_allowed_numbers=["+919800000001", "+919800000002"],
            vendor_call_redirect_to="+919800000003")
    s = d.check_switches(st)
    t = messages(s)
    assert "FRIDAY_CONSUMER_CALLS_ENABLED=on" in t and "FRIDAY_SAVINGS_ENABLED=off" in t
    assert "FRIDAY_GOOGLE_ENABLED=on" in t and "FRIDAY_LIFESTATE_ENABLED=off" in t
    assert "2 number(s)" in t and "redirect: SET" in t
    assert "+9198" not in t


def test_switches_warn_on_calls_without_allow_list(tmp_path):
    s = d.check_switches(live(tmp_path, consumer_calls_enabled=True))
    assert d.WARN in statuses(s)


# ------------------------------------------------------------------------- off switch
def test_off_switch_round_trips_and_leaves_real_flag_alone(tmp_path):
    st = mk(tmp_path)
    s = run(d.check_off_switch(st))
    assert statuses(s) == [d.OK, d.OK, d.OK], messages(s)
    assert not Path(st.pause_file).exists()


def test_off_switch_reports_real_pause(tmp_path):
    st = mk(tmp_path)
    Path(st.pause_file).parent.mkdir(parents=True)
    Path(st.pause_file).write_text("paused\n")
    s = run(d.check_off_switch(st))
    assert s.checks[0].status == d.WARN and "PAUSED" in s.checks[0].message
    assert Path(st.pause_file).exists()  # untouched
    assert d.FAIL not in statuses(s)


# ------------------------------------------------------------------------- systemd
def test_systemd_skipped_without_systemctl():
    s = d.check_systemd(d.Probes(systemctl_present=lambda: False))
    assert statuses(s) == [d.SKIP]


def test_systemd_active_with_timestamp_only():
    def fake(cmd):
        if cmd[0] == "systemctl":
            return 0, "active"
        return 0, "2026-10-19T10:00:01+0530 host friday[1]: token=PLANTED-log-secret"

    s = d.check_systemd(d.Probes(systemctl_present=lambda: True, run_command=fake))
    assert statuses(s) == [d.OK, d.OK]
    assert "2026-10-19T10:00:01+0530" in messages(s) and "PLANTED-log-secret" not in messages(s)


def test_systemd_inactive_fails_unknown_skips():
    s = d.check_systemd(d.Probes(systemctl_present=lambda: True,
                                 run_command=lambda c: (3, "failed")))
    assert s.checks[0].status == d.FAIL
    s = d.check_systemd(d.Probes(systemctl_present=lambda: True,
                                 run_command=lambda c: (4, "")))
    assert statuses(s) == [d.SKIP]


# ------------------------------------------------------------------------- whole run
def all_fake_probes() -> d.Probes:
    meta, _ = graph()

    async def ok(url: str) -> None:
        return None

    site_t, _ = site()

    def route(req: httpx.Request) -> httpx.Response:
        return (meta if req.url.host == "graph.facebook.com" else site_t).handle_request(req)

    return d.Probes(
        transport=httpx.MockTransport(route), redis_ping=ok, object_store_check=ok,
        vobiz_transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
            "enabled": True, "available_balance": 50, "items": [
                {"e164": "+910000000001", "status": "active", "voice_enabled": True}]})),
        systemctl_present=lambda: False,
    )


def test_run_doctor_text_pass_exit_zero_and_no_secrets(db_settings, capsys):
    st = db_settings.model_copy(update=dict(
        whatsapp_verify_token=live(Path("/x")).whatsapp_verify_token, public_base_url=BASE,
        whatsapp_provider="cloud", whatsapp_access_token=live(Path("/x")).whatsapp_access_token,
        whatsapp_phone_number_id="12345", anthropic_api_key=live(Path("/x")).anthropic_api_key,
        sarvam_api_key=live(Path("/x")).sarvam_api_key,
        redis_url=f"redis://:{PLANTED['dbpass']}@h:6379/0"))
    rc = d.run_doctor(st, probes=all_fake_probes())
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "DOCTOR PASS" in out and "[ OK ]" in out
    for v in PLANTED.values():
        assert v not in out


def test_run_doctor_fail_exit_one(tmp_path, capsys):
    rc = d.run_doctor(mk(tmp_path), offline=True)  # never migrated -> FAIL
    out = capsys.readouterr().out
    assert rc == 1 and "[FAIL]" in out and "DOCTOR FAIL" in out


def test_json_output_is_clean_and_secret_free(tmp_path, capsys):
    st = live(tmp_path, redis_url=f"redis://:{PLANTED['dbpass']}@h:6379/0")
    rc = d.run_doctor(st, offline=True, as_json=True)
    out = capsys.readouterr().out
    doc = json.loads(out)  # nothing but JSON (no log lines)
    assert rc == 1 and doc["passed"] is False and doc["offline"] is True
    assert [s["name"] for s in doc["sections"]] == list(d.SECTIONS)
    for v in PLANTED.values():
        assert v not in out


def test_scrub_removes_a_leaked_value(tmp_path):
    st = live(tmp_path)
    secrets_ = d._secret_values(st)
    assert PLANTED["meta"] in secrets_
    sec = d.Section("switches")
    sec.add(d.OK, f"oops {PLANTED['meta']}")
    text_, _ = d.render([sec], offline=False, as_json=False, secret_values=secrets_)
    assert PLANTED["meta"] not in text_ and "***" in text_


def test_section_option_runs_one_section(tmp_path, capsys):
    rc = d.run_doctor(mk(tmp_path), section="switches")
    out = capsys.readouterr().out
    assert rc == 0 and "6. switches" in out and "2. database" not in out


def test_unknown_section_is_exit_two(tmp_path, capsys):
    assert d.run_doctor(mk(tmp_path), section="nope") == 2
    assert "unknown section" in capsys.readouterr().out


def test_offline_makes_no_network_call(tmp_path, capsys):
    def boom(req: httpx.Request) -> httpx.Response:
        raise AssertionError("network used while --offline")

    async def boom_async(url: str) -> None:
        raise AssertionError("network used while --offline")

    probes = d.Probes(
        transport=httpx.MockTransport(boom), vobiz_transport=httpx.MockTransport(boom),
        redis_ping=boom_async, object_store_check=boom_async,
    )
    st = live(tmp_path, redis_url="redis://h:6379/0", object_store_url="s3://b/p")
    d.run_doctor(st, offline=True, probes=probes)
    out = capsys.readouterr().out
    assert "[SKIP]" in out and "AssertionError" not in out


def test_cli_wiring(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FRIDAY_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/c.db")
    monkeypatch.setenv("FRIDAY_PAUSE_FILE", str(tmp_path / "PAUSED"))
    rc = cli.main(["doctor", "--offline", "--json", "--section", "switches"])
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0 and [s["name"] for s in doc["sections"]] == ["switches"]
