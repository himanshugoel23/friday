from datetime import datetime, timedelta

import pytest

from friday.core.clock import UTC, FakeClock
from friday.core.container import Container
from friday.core.interfaces import NumberVerifier, OfficialNumberDirectory
from friday.core.models import Business, BusinessCandidate, NumberVerdict
from friday.discovery.official_numbers import OfficialNumbers
from friday.discovery.simulator import SimulatedDirectory
from friday.discovery.verify import NumberVerifierImpl, load_scam_list, warning_text
from friday.simworld import load_world

NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


class Biz:
    """Minimal in-memory BusinessRepository for history signals."""

    def __init__(self, *items: Business):
        self.items = {b.phone: b for b in items}

    async def get_by_phone(self, phone):
        return self.items.get(phone)


@pytest.fixture
def official() -> OfficialNumbers:
    return OfficialNumbers.from_file(sim=load_world())


async def test_official_lookup_sim_precedence(official):
    nums = await official.lookup("Airtel")
    assert [n.phone for n in nums] == ["+911800000121"]
    live = OfficialNumbers.from_file()
    assert {n.phone for n in await live.lookup("airtel broadband")} == {"121", "198"}
    jio = await live.lookup("Jio", purpose="broadband")
    assert jio[0].purpose == "broadband"
    assert (await live.lookup("HDFC"))[0].company == "HDFC Bank"
    assert await live.lookup("Vivek Clinic") == []
    assert (await live.find_by_phone("+91 1800 202 6161")).company == "HDFC Bank"
    assert await live.find_by_phone("+918040000001") is None
    assert "SBI" in await live.companies()


def test_container_factories(settings):
    c = Container(settings)
    assert isinstance(c.official_numbers, OfficialNumberDirectory)
    assert isinstance(c.number_verifier, NumberVerifier)


async def test_scam_number_from_simworld(container):
    check = await container.number_verifier.verify("+919000011111", company="Airtel")
    assert check.verdict == NumberVerdict.SCAM and check.warn_user and check.score == 0
    assert "won't call" in warning_text(check, "Airtel")


async def test_official_care_line_trusted(official):
    v = NumberVerifierImpl(official=official, clock=FakeClock(NOW))
    check = await v.verify("+911800000121", company="Airtel")
    assert check.verdict == NumberVerdict.TRUSTED and not check.warn_user
    assert warning_text(check) is None


async def test_mobile_claiming_brand_care_is_suspicious(official):
    v = NumberVerifierImpl(official=official, clock=FakeClock(NOW))
    check = await v.verify("+919812345678", company="Airtel")
    assert check.verdict == NumberVerdict.SUSPICIOUS and check.warn_user
    assert any("personal mobile" in s for s in check.signals)
    assert "Still call?" in warning_text(check, "Airtel")


async def test_listing_cross_check_consistent_vs_conflicting():
    d = SimulatedDirectory()
    v = NumberVerifierImpl(directory=d, clock=FakeClock(NOW))
    ok = await v.verify("+918040000001", claimed_name="Looks Unisex Salon")
    assert "matches the directory listing" in ok.signals and ok.score > 0.5
    bad = await v.verify("+918049999999", claimed_name="Looks Unisex Salon")
    assert any("different number" in s for s in bad.signals) and bad.score < 0.5


async def test_fraud_reviews_and_few_reviews_signal():
    world = load_world()
    d = SimulatedDirectory(world)
    v = NumberVerifierImpl(directory=d, clock=FakeClock(NOW))  # no scam list given
    check = await v.verify("+919000011111", claimed_name="Airtel Helpline (unofficial)")
    assert "reviews report fraud or OTP requests" in check.signals
    assert "listing has very few reviews" in check.signals
    assert check.verdict == NumberVerdict.SUSPICIOUS


async def test_call_history_weighting():
    recent = Business(
        name="Raju",
        phone="+918040000012",
        last_called_at=NOW - timedelta(days=10),
        verification=NumberVerdict.TRUSTED,
    )
    old = Business(name="Old", phone="+918040000099", last_called_at=NOW - timedelta(days=400))
    flagged = Business(name="Bad", phone="+918040000098", verification=NumberVerdict.SCAM)
    v = NumberVerifierImpl(businesses=Biz(recent, old, flagged), clock=FakeClock(NOW))
    r = await v.verify(recent.phone)
    o = await v.verify(old.phone)
    f = await v.verify(flagged.phone)
    assert r.score > o.score > 0.5 and r.verdict == NumberVerdict.TRUSTED
    assert f.verdict == NumberVerdict.SUSPICIOUS
    unknown = await v.verify("+918040000555")
    assert unknown.verdict == NumberVerdict.UNKNOWN and unknown.signals == []


async def test_failing_directory_does_not_break(official):
    class Broken:
        async def search(self, *a, **k):
            from friday.core.interfaces import ProviderError

            raise ProviderError("x", "down")

        async def details(self, place_id):
            return None

    v = NumberVerifierImpl(directory=Broken(), clock=FakeClock(NOW))
    assert (await v.verify("+918040000001", claimed_name="Looks")).verdict == NumberVerdict.UNKNOWN


async def test_details_used_when_search_lacks_phone():
    class Dir:
        async def search(self, *a, **k):
            return [BusinessCandidate(provider="t", place_id="p1", name="Looks Salon")]

        async def details(self, place_id):
            return BusinessCandidate(
                provider="t",
                place_id="p1",
                name="Looks Salon",
                phone="+918040000001",
                review_count=100,
            )

    v = NumberVerifierImpl(directory=Dir(), clock=FakeClock(NOW))
    assert (
        "matches the directory listing"
        in (await v.verify("+918040000001", claimed_name="Looks")).signals
    )


def test_scam_list_loader(tmp_path):
    p = tmp_path / "scam.txt"
    p.write_text("# comment\n+91 90000 11111\n\n0123456789 # inline\n")
    assert load_scam_list(p, None, tmp_path / "missing.txt") == {"9000011111", "123456789"}
