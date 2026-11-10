# ruff: noqa: E501
"""T17 founder review page: /ops-status/<token>/review and review.csv. Counts only; family labels F1, F2...; fakes only."""

from __future__ import annotations

import re
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from friday.api.opsstatus import ops_status_router
from friday.robin.alerts import RobinAlert
from friday.robin.models import ConsentSource, Tier
from friday.robin.store import Record
from friday.robindevice.ports import FakeAlertPort, InMemoryConsent, InMemoryParents
from friday.robindevice.service import DeviceService
from tests.robin.conftest import CHILD_PHONE, PARENT_PHONE

TOKEN = "t" * 20
NOW_MS = 1_800_000_000_000
# Personal strings seeded into the data; none may reach the page.
PERSONAL = ("Asha", "Papa", "Metformin", "SECRET-TEXT", "12 Rose Lane", "Ramesh")


def leaks(text: str) -> list[str]:
    """Digit runs of 7+, any seeded personal word, any + phone shape."""
    bad = re.findall(r"\d{7,}", text)
    bad += [w for w in PERSONAL if w.lower() in text.lower()]
    bad += re.findall(r"\+\d", text)
    return bad


def make_service() -> DeviceService:
    return DeviceService(
        alerts=FakeAlertPort(),
        consent=InMemoryConsent(),
        parents=InMemoryParents(),
        now_ms=lambda: NOW_MS,
        brand="Robin",
    )


def client(w, monkeypatch, svc, *, robin_on=True):
    monkeypatch.setenv("FRIDAY_OPS_STATUS_TOKEN", TOKEN)
    monkeypatch.chdir("/")
    w.hub.device_service = svc
    c = SimpleNamespace(settings=SimpleNamespace(robin_enabled=robin_on), get=lambda name: w.hub)
    app = FastAPI()
    app.include_router(ops_status_router(), prefix="/ops-status")
    app.state.container = c
    return TestClient(app)


async def seed(w, svc):
    fam, parent = await w.family()
    await w.hub.fam.give_consent(parent.id, "device_signals", ConsentSource.ADMIN_CHAT)
    st = svc.store.state(parent.id)
    st.shadow_start_ms = NOW_MS - 9 * 86_400_000  # day 10 -> week 2
    st.shadow_days = 14
    st.counters.update(
        {
            "accepted:call_pattern": 5,
            "accepted:motion": 3,
            "shadow:would_alert_child": 2,
            "shadow:would_nudge": 4,
            "shadow:would_nudge_ceiling_blocked": 1,
            "nudge_skipped:ceiling": 2,
            "fine:S1": 3,
            "sos": 1,
        }
    )
    await w.hub.alerts.raise_alert(
        RobinAlert(parent.id, Tier.EMERGENCY, "sos", "pressed the SOS button", dedupe_key="c")
    )
    await w.hub.alerts.raise_alert(
        RobinAlert(parent.id, Tier.EMERGENCY, "fall", "a fall was detected", dedupe_key="d")
    )
    for i, status in enumerate(("done", "done", "done", "unanswered")):
        await w.store.put(
            Record(
                family_id=fam.id,
                user_id=fam.owner_user_id,
                kind="checkin",
                key=f"2026-01-0{i + 1}",
                status=status,
                at=w.clock.now(),
                data={},
            )
        )
    await w.store.put(
        Record(
            family_id=fam.id,
            user_id=fam.owner_user_id,
            kind="pending",
            status="queued",
            at=w.clock.now(),
            data={"text": "SECRET-TEXT Metformin", "member_id": parent.id},
        )
    )
    await w.ctx.audit(
        fam,
        "authority",
        "DRY RUN: Script: Ramesh at 12 Rose Lane call " + CHILD_PHONE,
        kind="112",
        dry_run=True,
        incident_id="x",
    )
    return fam, parent


async def test_wrong_token_is_404_everywhere(w, monkeypatch):
    cl = client(w, monkeypatch, make_service())
    for path in ("review", "review.csv"):
        assert cl.get(f"/ops-status/wrong-token-wrong-token/{path}").status_code == 404
        assert cl.get(f"/ops-status/{TOKEN}/{path}").status_code == 200


async def test_off_when_robin_off(w, monkeypatch):
    r = client(w, monkeypatch, make_service(), robin_on=False).get(f"/ops-status/{TOKEN}/review")
    assert r.status_code == 200 and r.text.strip() == "status=off"


async def test_page_renders_seeded_counts_with_no_personal_data(w, monkeypatch):
    svc = make_service()
    await seed(w, svc)
    cl = client(w, monkeypatch, svc)
    t = cl.get(f"/ops-status/{TOKEN}/review").text
    line = next(ln for ln in t.splitlines() if ln.startswith("F1:"))
    assert (
        "week 2 (shadow)" in line
        and "signals seen 8" in line
        and "would alert child 2" in line
        and "would nudge 4" in line
    )
    assert (
        "ceilings hit 3" in line
        and "this was fine 3" in line
        and "check-in answered 75% (3/4)" in line
    )
    assert (
        "SOS taps 1, SOS incidents 1" in line
        and "falls 1" in line
        and "authority dry-runs 1" in line
    )
    assert "<name>" in t and "Daily review" in t  # template with placeholders, plus the checklist
    assert leaks(t) == [], leaks(t)
    csv = cl.get(f"/ops-status/{TOKEN}/review.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    head, row = csv.text.strip().splitlines()
    assert head.startswith("label,week,") and row.startswith("F1,2,1,8,2,4,3,3,3,1,75,1,1,1,1")
    assert leaks(csv.text) == [], leaks(csv.text)
    assert PARENT_PHONE not in t + csv.text


async def test_negative_control_the_leak_scan_catches_planted_data():
    assert leaks("F1 week 2") == []
    assert (
        leaks("call +919800000102")
        and leaks("for Asha")
        and leaks("Metformin 500")
        and leaks("1234567890")
    )
