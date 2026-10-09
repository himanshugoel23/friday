"""Vobiz application sync / restore with mocked HTTP only (never a real account)."""

from __future__ import annotations

import json

import httpx
import pytest

from friday.core.interfaces import ProviderError
from friday.voice.telephony.sarvam import SarvamTelephony, sarvam_token
from friday.voice.telephony.vobiz_app import (
    APP_NAME,
    FakeVobizAccount,
    VobizAppManager,
    inbound_urls,
)

NUMBER = "+918065354620"
SECRET = "s" * 32
URL = "https://abc-def.trycloudflare.com"
OLD_APP = {"app_id": "777", "app_name": "sarvam-hosted-agent", "answer_url": "https://sarvam/x"}


def account(**kw):
    return FakeVobizAccount("MA_T", numbers={NUMBER: "777"}, applications=[OLD_APP], **kw)


def manager(fake, tmp_path):
    return VobizAppManager("MA_T", "tok", transport=fake.transport, state_path=tmp_path / "s.json")


async def test_creates_the_application_links_the_number_and_remembers_the_previous_link(tmp_path):
    fake = account()
    mgr = manager(fake, tmp_path)
    link = await mgr.sync(URL, NUMBER, SECRET)
    assert link.created_app and link.attached and link.previous_app_id == "777"
    app = fake.apps[link.app_id]
    answer, hangup = inbound_urls(URL, SECRET)
    assert app["app_name"] == APP_NAME
    assert app["answer_url"] == answer and app["hangup_url"] == hangup
    assert app["answer_method"] == "POST" and app["hangup_method"] == "POST"
    assert answer.startswith(f"{URL}/voice/sarvam/inbound?token=")
    assert hangup.startswith(f"{URL}/voice/sarvam/hangup?token=")
    assert fake.numbers[NUMBER] == link.app_id
    saved = json.loads((tmp_path / "s.json").read_text())
    assert saved["previous_app_id"] == "777" and "token" not in json.dumps(saved)
    assert "token" not in json.dumps(link.public())  # nothing secret is ever printed
    await mgr.aclose()


async def test_restore_puts_the_previous_link_back(tmp_path):
    fake = account()
    mgr = manager(fake, tmp_path)
    link = await mgr.sync(URL, NUMBER, SECRET)
    res = await mgr.restore(link)
    assert res.ok and res.action == "reattached" and fake.numbers[NUMBER] == "777"
    assert not (tmp_path / "s.json").exists()
    assert (await mgr.restore()).action == "nothing to restore"  # idempotent


async def test_a_number_with_no_previous_application_is_detached_on_restore(tmp_path):
    fake = FakeVobizAccount("MA_T", numbers={NUMBER: None})
    mgr = manager(fake, tmp_path)
    link = await mgr.sync(URL, NUMBER, SECRET)
    assert link.previous_app_id is None and link.previous_known
    res = await mgr.restore(link)
    assert res.action == "detached" and fake.numbers[NUMBER] is None
    assert ("DELETE", f"/api/v1/Account/MA_T/numbers/{NUMBER}/application", None) in fake.requests


async def test_sync_is_idempotent_no_writes_the_second_time(tmp_path):
    fake = account()
    mgr = manager(fake, tmp_path)
    first = await mgr.sync(URL, NUMBER, SECRET)
    writes = len(fake.writes)
    second = await mgr.sync(URL, NUMBER, SECRET)
    assert len(fake.writes) == writes  # GETs only
    assert second.app_id == first.app_id and not second.attached and not second.created_app
    assert second.previous_app_id == "777"  # still remembers the ORIGINAL link
    assert sum(1 for a in fake.apps.values() if a["app_name"] == APP_NAME) == 1
    assert (await mgr.restore(second)).action == "reattached" and fake.numbers[NUMBER] == "777"


async def test_a_new_tunnel_address_updates_the_application_not_the_link(tmp_path):
    fake = account()
    mgr = manager(fake, tmp_path)
    first = await mgr.sync(URL, NUMBER, SECRET)
    before = len(fake.writes)
    second = await mgr.sync("https://new-address.trycloudflare.com", NUMBER, SECRET)
    new_writes = fake.writes[before:]
    assert second.updated_app and not second.attached
    assert [(m, p.split("/")[-2]) for m, p, _ in new_writes] == [("POST", first.app_id)]
    assert fake.apps[first.app_id]["answer_url"].startswith("https://new-address")


async def test_a_crashed_run_can_be_undone_and_a_rerun_keeps_the_original_link(tmp_path):
    fake = account()
    await manager(fake, tmp_path).sync(URL, NUMBER, SECRET)  # ... then the process dies
    mgr = manager(fake, tmp_path)  # a new process
    pending = mgr.pending_restore()
    assert pending is not None and pending.previous_app_id == "777"
    rerun = await mgr.sync("https://other.trycloudflare.com", NUMBER, SECRET)
    assert rerun.previous_app_id == "777"  # not "our own application"
    res = await manager(fake, tmp_path).restore()  # `friday listen --restore`
    assert res.ok and fake.numbers[NUMBER] == "777"


async def test_restore_never_overwrites_someone_elses_later_change(tmp_path):
    fake = account()
    fake.apps["888"] = {"app_id": "888", "app_name": "mine"}
    mgr = manager(fake, tmp_path)
    link = await mgr.sync(URL, NUMBER, SECRET)
    fake.numbers[NUMBER] = "888"  # the founder re-linked it by hand meanwhile
    res = await mgr.restore(link)
    assert res.action == "left as is" and fake.numbers[NUMBER] == "888"


async def test_restore_failure_is_reported_and_keeps_the_state_for_a_retry(tmp_path):
    fake = account()
    mgr = manager(fake, tmp_path)
    link = await mgr.sync(URL, NUMBER, SECRET)
    fake.fail[("POST", "/application")] = 500
    res = await mgr.restore(link)
    assert not res.ok and "friday listen --restore" in res.detail
    assert (tmp_path / "s.json").exists()
    fake.fail.clear()
    assert (await mgr.restore()).action == "reattached"


async def test_unknown_number_or_insecure_url_changes_nothing(tmp_path):
    fake = account()
    mgr = manager(fake, tmp_path)
    with pytest.raises(ProviderError):
        await mgr.sync(URL, "+919999999999", SECRET)
    with pytest.raises(ProviderError):
        await mgr.sync("http://insecure.example.com", NUMBER, SECRET)
    assert fake.writes == [] and fake.numbers[NUMBER] == "777"


async def test_dry_run_writes_nothing(tmp_path):
    fake = account()
    mgr = manager(fake, tmp_path)
    link = await mgr.sync(URL, NUMBER, SECRET, dry_run=True)
    assert link.created_app and fake.writes == [] and not (tmp_path / "s.json").exists()


async def test_wrong_credentials_are_an_error_not_a_silent_success(tmp_path):
    fake = account()
    mgr = VobizAppManager("MA_WRONG", "tok", transport=fake.transport)
    with pytest.raises(ProviderError):
        await mgr.sync(URL, NUMBER, SECRET)


async def test_application_list_is_paginated():
    apps = [{"app_id": str(i), "app_name": f"app{i}"} for i in range(150)]
    apps.append({"app_id": "999", "app_name": APP_NAME, "answer_url": "x"})
    fake = FakeVobizAccount("MA_T", numbers={NUMBER: None}, applications=apps)
    mgr = VobizAppManager("MA_T", "tok", transport=fake.transport)
    link = await mgr.sync(URL, NUMBER, SECRET)
    assert link.app_id == "999" and not link.created_app and link.updated_app


async def test_urls_match_what_the_webhook_routes_accept():
    answer, hangup = inbound_urls(URL, SECRET)
    tel = SarvamTelephony(
        auth_id="MA_T", auth_token="tok", caller_ids=[NUMBER], public_base_url=URL, secret=SECRET,
        stt=None, tts=None, transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    assert answer == tel.url("inbound")
    assert hangup == tel.url("hangup")  # the same token scope, "inbound", for both routes
    assert answer.endswith(sarvam_token(SECRET, "inbound"))
    await tel.aclose()


async def test_the_number_is_url_encoded_in_the_attach_path(tmp_path):
    fake = account()
    raw: list[str] = []

    def spy(request: httpx.Request) -> httpx.Response:
        raw.append(request.url.raw_path.decode())
        return fake._handle(request)

    mgr = VobizAppManager("MA_T", "tok", transport=httpx.MockTransport(spy))
    await mgr.sync(URL, NUMBER, SECRET)
    assert any(p.endswith("/numbers/%2B918065354620/application") for p in raw)
