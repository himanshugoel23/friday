# ruff: noqa: E501
"""T06 alert-flood protection: a per-family daily cap on the child's WhatsApp alerts (WATCH/HIGH) with ONE "many alerts" summary instead
of silence; EMERGENCY and SOS are never rate-limited away. Tested with fakes."""

from __future__ import annotations

from friday.robin.alerts import DAILY_ALERT_CAP, RobinAlert
from friday.robin.models import Tier
from tests.robin.conftest import at
from tests.robin.test_alerts_sos import ready


def alert(parent, n: int, tier=Tier.HIGH, scenario="S1", **kw):
    return RobinAlert(parent_member_id=parent.id, tier=tier, scenario=scenario, why=f"unknown caller case {n}", dedupe_key=f"k{n}-{tier.value}-{scenario}", **kw)


def child_texts(w) -> list[str]:
    return [m.text for m in w.sender.sent]


async def test_high_alerts_are_capped_with_one_summary_not_silence(w):
    fam, parent = await ready(w)
    for n in range(DAILY_ALERT_CAP):
        await w.hub.alerts.raise_alert(alert(parent, n))
    texts = child_texts(w)
    assert sum("unknown caller case" in t for t in texts) == DAILY_ALERT_CAP and not any("Many alerts" in t for t in texts)
    before = len(texts)
    for n in range(DAILY_ALERT_CAP, DAILY_ALERT_CAP + 5):
        res = await w.hub.alerts.raise_alert(alert(parent, n))
        assert res.accepted  # the incident still exists, still audited
    fresh = child_texts(w)[before:]
    summaries = [t for t in fresh if "Many alerts today" in t]
    assert len(summaries) == 1 and f"({DAILY_ALERT_CAP} so far)" in summaries[0]  # exactly one, and it says how many
    assert not any("unknown caller case" in t for t in fresh)  # the extra ones were held back
    audit = [r.data["text"] for r in await w.store.list(fam.id, "audit")]
    assert sum("unknown caller case 12" in t for t in audit) >= 1  # still in 'what Robin did'


async def test_emergency_and_sos_are_never_rate_limited_away(w):
    fam, parent = await ready(w, second=True)
    for n in range(DAILY_ALERT_CAP + 3):
        await w.hub.alerts.raise_alert(alert(parent, n))
    assert any("Many alerts today" in t for t in child_texts(w))  # we are over the cap
    before = len(child_texts(w))
    for n in range(4):
        await w.hub.alerts.raise_alert(alert(parent, 100 + n, tier=Tier.EMERGENCY, scenario="S2"))
    emergencies = [t for t in child_texts(w)[before:] if t.startswith("EMERGENCY:")]
    assert len(emergencies) == 4
    before = len(child_texts(w))
    await w.hub.sos.trigger(parent.id, "app")
    assert any(t.startswith("SOS:") for t in child_texts(w)[before:])


async def test_the_cap_resets_the_next_day_and_is_per_family(w):
    fam, parent = await ready(w)
    for n in range(DAILY_ALERT_CAP + 2):
        await w.hub.alerts.raise_alert(alert(parent, n))
    w.clock.set(at(10, day=6))  # next IST day
    before = len(child_texts(w))
    await w.hub.alerts.raise_alert(alert(parent, 500))
    assert any("unknown caller case 500" in t for t in child_texts(w)[before:])


async def test_watch_alerts_count_toward_the_same_cap(w):
    fam, parent = await ready(w)
    for n in range(DAILY_ALERT_CAP):
        await w.hub.alerts.raise_alert(alert(parent, n, tier=Tier.WATCH, scenario="S4"))
    before = len(child_texts(w))
    await w.hub.alerts.raise_alert(alert(parent, 900))
    fresh = child_texts(w)[before:]
    assert any("Many alerts today" in t for t in fresh) and not any("case 900" in t for t in fresh)
