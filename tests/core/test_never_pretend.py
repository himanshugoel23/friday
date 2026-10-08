"""Never pretend: in live mode no simulator may fabricate hotel rates, SMS sends or listings
unless it is pinned explicitly (or it is the founder-only pilot profile)."""

from __future__ import annotations

import pytest

from friday.core.config import Settings
from friday.core.container import (
    PIN_FIELDS,
    ComponentDisabled,
    Container,
    SimulatorInLive,
)

LEGAL = dict(
    terms_url="https://friday.example.in/terms",
    privacy_url="https://friday.example.in/privacy",
    grievance_email="grievance@friday.example.in",
)


def live(profile="beta", **kw) -> Settings:
    base = dict(
        _env_file=None, mode="live", profile=profile, anthropic_api_key="a",
        public_base_url="https://friday.example.in",
        database_url="postgresql+asyncpg://u:p@db/friday",
        sarvam_telephony_auth_id="id", sarvam_telephony_auth_token="tok",
        sarvam_caller_ids=["+918065354620"], sarvam_api_key="k", google_places_api_key="g",
        whatsapp_access_token="t", whatsapp_phone_number_id="1", whatsapp_app_secret="s",
        whatsapp_verify_token="a-random-verify-token", secret_key="s" * 32,
        pin_pepper="p", field_key="f", index_key="i", admin_token="adm", **LEGAL,
    )
    base.update(kw)
    return Settings(**base)


@pytest.mark.parametrize("profile", ["beta", "default"])
@pytest.mark.parametrize("component", sorted(PIN_FIELDS))
def test_live_never_selects_a_simulator_without_an_explicit_choice(profile, component):
    c = Container(live(profile))
    assert c.provider_for(component) not in ("simulator", "fake")
    assert not c.simulator_in_live(component)


def test_beta_without_keys_disables_instead_of_simulating():
    s = live("beta")
    assert (s.resolve_hotels(), s.resolve_sms()) == ("off", "off")
    c = Container(s)
    for comp in ("hotels", "sms"):
        with pytest.raises(ComponentDisabled):
            c.get(comp)
        assert not c.is_available(comp)
    assert set(c.disabled_components()) == {"hotels", "sms"}
    assert c.missing_role_components() == [] or "hotels" not in c.missing_role_components()
    notes = " ".join(s.optional_feature_notes())
    assert "hotel live rates: OFF" in notes and "SMS: OFF" in notes


def test_a_simulator_chosen_by_auto_in_live_is_refused(monkeypatch):
    s = live("beta")
    c = Container(s)
    for resolver, comp in (
        ("resolve_hotels", "hotels"), ("resolve_sms", "sms"), ("resolve_directory", "directory"),
        ("resolve_whatsapp", "messaging"),
    ):
        monkeypatch.setattr(
            Settings, resolver, lambda self, comp=comp: "fake" if comp == "sms" else "simulator"
        )
        assert c.simulator_in_live(comp)
        with pytest.raises(SimulatorInLive):
            c.factory_path(comp)
        assert not c.is_available(comp)
    with pytest.raises(RuntimeError, match="simulators"):
        c.check_live_config()


def test_explicit_pin_and_pilot_profile_may_simulate():
    pinned = Container(live("default", hotel_provider="simulator"))
    assert not pinned.simulator_in_live("hotels")
    assert pinned.factory_path("hotels").endswith("build_simulated_hotels")
    pilot = Container(live("pilot", pilot_allowed_numbers=["+919812345678"]))
    assert pilot.factory_path("hotels").endswith("build_simulated_hotels")
    assert pilot.factory_path("sms").endswith("build_fake_sms")


def test_beta_rejects_pinned_simulators_for_every_feature():
    for kw in (dict(hotel_provider="simulator"), dict(sms_provider="fake"),
               dict(directory_provider="simulator"), dict(geocoder_provider="simulator")):
        assert any("simulator" in p for p in live("beta", **kw).live_problems()), kw


def test_pilot_simulated_results_are_marked():
    from friday.discovery.hotels.simulator import SimulatedHotels
    from friday.discovery.simulator import SimulatedDirectory

    c = Container(
        live("pilot", pilot_allowed_numbers=["+919812345678"], google_places_api_key=None)
    )
    assert c.get("hotels").name_prefix == "[SIMULATED] "
    assert c.get("directory").name_prefix == "[SIMULATED] "
    assert SimulatedHotels().name_prefix == "" and SimulatedDirectory().name_prefix == ""
    notes = " ".join(c.settings.optional_feature_notes())
    assert "SIMULATED" in notes


def test_legal_settings_required_beta_and_nonpilot_live_only():
    bare = dict(terms_url=None, privacy_url=None, grievance_email=None)
    for profile in ("beta", "default"):
        text = " ".join(live(profile, **bare).live_problems())
        for name in ("FRIDAY_TERMS_URL", "FRIDAY_PRIVACY_URL", "FRIDAY_GRIEVANCE_EMAIL"):
            assert name in text
    pilot = live("pilot", pilot_allowed_numbers=["+919812345678"], **bare)
    assert "FRIDAY_TERMS_URL" not in " ".join(pilot.live_problems())
    assert any("https" in p for p in live("beta", terms_url="http://x.in/t").live_problems())
