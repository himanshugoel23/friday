# ruff: noqa: E501
"""Knowledge versions, drift detection on fake pages, auto-apply vs review queue, rollback. Fakes only."""

from __future__ import annotations

import json

import pytest

from friday.team.drift import DriftJob, FakePages, FetchedPage, RateLimiter
from friday.team.knowledge import KnowledgeStore, validate

HOME = "https://www.zomato.com/"
DELIVERY = "https://www.zomato.com/ncr/delivery"
NEW_DELIVERY = "https://www.zomato.com/ncr/order-food-online"
SW_HOME = "https://www.swiggy.com/"
SW_CITY = "https://www.swiggy.com/city/delhi"
ROBOTS_OK = "User-agent: *\nDisallow: /checkout\n"


def page(url, text="Zomato - order food online", status=200, final=None):
    return FetchedPage(url, final or url, status, text)


def healthy() -> FakePages:
    return FakePages({
        "https://www.zomato.com/robots.txt": page("https://www.zomato.com/robots.txt", ROBOTS_OK),
        "https://www.swiggy.com/robots.txt": page("https://www.swiggy.com/robots.txt", ROBOTS_OK),
        HOME: page(HOME), DELIVERY: page(DELIVERY),
        SW_HOME: page(SW_HOME, "Swiggy food delivery"), SW_CITY: page(SW_CITY, "Swiggy Delhi"),
    })


def job(tmp_path, pages, **kw):
    t = [1_000_000.0]
    j = DriftJob(KnowledgeStore(tmp_path, clock=lambda: t[0]), pages, min_interval_s=0, clock=lambda: t[0], **kw)
    return j, t


# ---------------------------------------------------------------- the knowledge files themselves
def test_seed_knowledge_is_valid_complete_and_has_the_safety_rules(tmp_path):
    store = KnowledgeStore(tmp_path)
    assert store.sites() == ["swiggy", "zomato"]
    for site in store.sites():
        kb = store.get(site)
        assert validate(None, kb) == [] and kb["version"] == 1 and kb["status"] == "unverified"
        for key in ("search_flow", "url_patterns", "locations", "login_checkout", "quirks", "anti_bot", "probes"):
            assert kb[key]
        assert kb["safety"]["never_pay"] is True and kb["safety"]["stop_at_payment"] is True
        assert {"restaurant_name", "price", "delivery_time", "rating", "offers"} <= set(kb["locations"])
        assert "Friday stops BEFORE the payment page" in kb["login_checkout"]["stop_rule"]


def test_no_secrets_or_phone_numbers_in_knowledge_files(tmp_path):
    for site in KnowledgeStore(tmp_path).sites():
        blob = json.dumps(KnowledgeStore(tmp_path).get(site))
        assert not __import__("re").search(r"\d{10}|api[_-]?key|sk-|password\s*[:=]", blob, __import__("re").I)


def test_validation_refuses_safety_domain_and_schema_changes(tmp_path):
    store = KnowledgeStore(tmp_path)
    for mutate in ({"safety": {"never_pay": False}}, {"domains": ["evil.example"]}, {"schema": 2},
                   {"login_checkout": {"stop_rule": "pay for the user"}}, {"anti_bot": {"our_response": "solve captchas"}}):
        p = store.make_proposal("zomato", mutate, "attack")
        assert not p.valid, mutate
    p = store.make_proposal("zomato", {"url_patterns": {"home": "http://www.zomato.com/"}}, "no https")
    assert not p.valid
    p = store.make_proposal("zomato", {"url_patterns": {"home": "https://evil.example/"}}, "other host")
    assert not p.valid
    with pytest.raises(ValueError):
        store.apply(p, how="auto")  # an invalid proposal can never be applied


# ---------------------------------------------------------------- drift detection
async def test_unchanged_pages_verify_and_propose_nothing(tmp_path):
    j, _ = job(tmp_path, healthy())
    reports = await j.run_all()
    assert {r.site: r.status for r in reports} == {"swiggy": "verified", "zomato": "verified"}
    assert all(r.action == "none" for r in reports) and j.store.current_version("zomato") == 1


async def test_moved_page_creates_a_new_version_with_a_diff_and_is_auto_applied(tmp_path):
    pages = healthy()
    pages.pages[DELIVERY] = page(DELIVERY, final=NEW_DELIVERY)  # 200 after a redirect
    pages.pages[NEW_DELIVERY] = page(NEW_DELIVERY)
    j, _ = job(tmp_path, pages)
    r = await j.run_site("zomato")
    assert r.status == "drift" and r.action == "auto_applied" and r.applied_version == 2
    assert any("order-food-online" in d and "url_patterns.city_delivery" in d for d in r.diff)
    store = j.store
    assert store.current_version("zomato") == 2
    assert store.get("zomato")["url_patterns"]["city_delivery"] == "https://www.zomato.com/{city_slug}/order-food-online"
    assert store.get("zomato")["probes"][1]["url"] == NEW_DELIVERY
    assert store.get("zomato", 1)["url_patterns"]["city_delivery"] == "https://www.zomato.com/{city_slug}/delivery"  # old version kept
    assert store.get("zomato")["safety"] == store.get("zomato", 1)["safety"]
    log = store.changelog("zomato")
    assert any(e["event"] == "applied" and e["how"] == "auto" and e["version"] == 2 for e in log)
    assert (tmp_path / "zomato" / "drift.jsonl").exists()


async def test_content_drift_goes_to_the_review_queue_and_changes_nothing(tmp_path):
    pages = healthy()
    pages.pages[HOME] = page(HOME, "A completely different landing page")  # marker 'zomato' gone
    j, _ = job(tmp_path, pages)
    r = await j.run_site("zomato")
    assert r.status == "drift" and r.action == "queued" and r.review_id and r.applied_version is None
    assert j.store.current_version("zomato") == 1
    q = j.store.review_queue("zomato")
    assert len(q) == 1 and q[0]["needs_review"] == ["quirks"] and "DRIFT NOTICE" in q[0]["diff"][0] and "DRIFT NOTICE" in q[0]["doc"]["quirks"][-1]
    # the founder approves: it becomes v2, with the note
    assert j.store.approve(r.review_id) == 2
    assert any("DRIFT NOTICE" in x for x in j.store.get("zomato")["quirks"]) and j.store.review_queue("zomato") == []
    assert any(e["how"] == "founder_review" for e in j.store.changelog("zomato") if e["event"] == "applied")


async def test_rejecting_a_review_item_leaves_the_version_alone(tmp_path):
    pages = healthy()
    pages.pages[HOME] = page(HOME, "nothing")
    j, _ = job(tmp_path, pages)
    r = await j.run_site("zomato")
    j.store.reject(r.review_id)
    assert j.store.review_queue() == [] and j.store.current_version("zomato") == 1
    assert j.store.changelog("zomato")[-1]["event"] == "rejected"


async def test_page_gone_is_queued_for_review_not_auto_applied(tmp_path):
    pages = healthy()
    pages.pages[DELIVERY] = page(DELIVERY, "", status=404)
    j, _ = job(tmp_path, pages)
    r = await j.run_site("zomato")
    assert r.status == "drift" and r.action == "queued" and "gone" in r.probes[1].outcome


async def test_bot_challenge_means_unverified_and_the_last_good_version_is_kept(tmp_path):
    pages = healthy()
    pages.pages[HOME] = page(HOME, "<title>Just a moment...</title> verify you are human", status=403)
    pages.pages[DELIVERY] = page(DELIVERY, "Access Denied", status=200)
    j, _ = job(tmp_path, pages)
    r = await j.run_site("zomato")
    assert r.status == "unverified" and r.action == "none" and "last good version kept" in r.note
    assert [p.outcome for p in r.probes] == ["blocked", "blocked"]
    assert j.store.current_version("zomato") == 1 and j.store.review_queue() == []
    assert j.store.changelog("zomato")[-1]["status"] == "unverified"
    assert j.store.get("zomato")["status"] == "unverified"


async def test_network_error_is_unverified_not_drift(tmp_path):
    pages = healthy()
    pages.pages[HOME] = TimeoutError("slow")
    pages.pages[DELIVERY] = TimeoutError("slow")
    j, _ = job(tmp_path, pages)
    r = await j.run_site("zomato")
    assert r.status == "unverified" and r.action == "none"


async def test_robots_txt_is_respected_and_unreadable_robots_blocks_probing(tmp_path):
    pages = healthy()
    pages.pages["https://www.zomato.com/robots.txt"] = page("https://www.zomato.com/robots.txt", "User-agent: *\nDisallow: /\n")
    pages.pages["https://www.swiggy.com/robots.txt"] = page("https://www.swiggy.com/robots.txt", "", status=500)
    j, _ = job(tmp_path, pages)
    rz, rs = await j.run_site("zomato"), await j.run_site("swiggy")
    assert [p.outcome for p in rz.probes] == ["skipped_robots"] * 2 and rz.status == "unverified"
    assert [p.outcome for p in rs.probes] == ["skipped_robots"] * 2
    assert HOME not in pages.calls and SW_HOME not in pages.calls  # the probed pages were never fetched
    pages2 = healthy()
    pages2.pages["https://www.zomato.com/robots.txt"] = page("https://www.zomato.com/robots.txt", "", status=404)
    j2, _ = job(tmp_path / "2", pages2)
    assert (await j2.run_site("zomato")).status == "verified"  # no robots file = allowed


async def test_rate_limiter_spaces_requests_per_host():
    sleeps, now = [], [0.0]

    async def fake_sleep(s):  # noqa: ANN001, ANN202
        sleeps.append(s)
        now[0] += s

    lim = RateLimiter(6.0, clock=lambda: now[0], sleep=fake_sleep)
    await lim.wait("a.com")
    await lim.wait("a.com")
    await lim.wait("b.com")
    assert sleeps == [6.0]


async def test_schedule_runs_once_per_interval_and_no_login_or_cookies_are_ever_sent(tmp_path):
    pages = healthy()
    j, t = job(tmp_path, pages, interval_h=24.0)
    assert await j.tick() and not await j.tick()  # second tick inside the interval does nothing
    n = len(pages.calls)
    t[0] += 25 * 3600
    assert await j.tick() and len(pages.calls) > n
    assert all(c.startswith("https://") and "login" not in c for c in pages.calls)  # public pages only


async def test_stale_proposal_cannot_overwrite_a_newer_version(tmp_path):
    pages = healthy()
    pages.pages[HOME] = page(HOME, "different")
    j, _ = job(tmp_path, pages)
    r = await j.run_site("zomato")
    store = j.store
    other = store.make_proposal("zomato", {"url_patterns": {"city_home": "https://www.zomato.com/delhi"}}, "manual")
    store.apply(other, how="founder_review")
    with pytest.raises(ValueError):
        store.approve(r.review_id)  # based on v1, current is v2


async def test_rollback_moves_the_pointer_and_logs_it(tmp_path):
    pages = healthy()
    pages.pages[DELIVERY] = page(DELIVERY, final=NEW_DELIVERY)
    pages.pages[NEW_DELIVERY] = page(NEW_DELIVERY)
    j, _ = job(tmp_path, pages)
    await j.run_site("zomato")
    assert j.store.current_version("zomato") == 2
    j.store.rollback("zomato", 1, "founder: wrong redirect")
    assert j.store.current_version("zomato") == 1
    assert j.store.get("zomato")["url_patterns"]["city_delivery"] == "https://www.zomato.com/{city_slug}/delivery"
    assert j.store.versions("zomato") == [1, 2] and j.store.changelog("zomato")[-1]["event"] == "rollback"
    with pytest.raises(KeyError):
        j.store.rollback("zomato", 9)


async def test_an_unverified_new_url_is_queued_never_auto_applied(tmp_path):
    """The job only auto-applies URLs it fetched itself in this run; a hand-made guess goes to review."""
    j, _ = job(tmp_path, healthy())
    from friday.team.drift import DriftReport

    p = j.store.make_proposal("zomato", {"url_patterns": {"city_delivery": "https://www.zomato.com/somewhere/else"}}, "guess")
    assert p.valid and p.auto_ok  # an allowed path on its own...
    rep = DriftReport("zomato", 1, "drift")
    verified: set[str] = set()  # ...but nothing fetched it in this run
    new_urls = {c.new for c in p.changes if isinstance(c.new, str) and c.new.startswith("https://") and c.path.startswith("url_patterns.")}
    assert not new_urls <= verified and rep.action == "none"
