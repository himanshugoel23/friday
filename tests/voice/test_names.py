"""Names as variables: spoken forms (Devanagari), glossary, overrides, cache, offline fallback."""

# ruff: noqa: E501

from __future__ import annotations

import json

import httpx
import pytest

from friday.voice import names
from friday.voice.names import (
    NameSpeller,
    join_services,
    normalise,
    parse_services,
    sanitise,
    sarvam_transliterator,
)

DEV = {"Shreya": "श्रेया", "Looks": "लुक्स", "Himanshu": "हिमांशु", "Ravi Kumar": "रवि कुमार",
       "Glow": "ग्लो", "Meena": "मीना"}


class Fake:
    """A transliteration client that records its calls (no network)."""

    def __init__(self, table=None, fail=False):
        self.table = DEV if table is None else table
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, text):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("down")
        return self.table.get(text)


def speller(client=None, tmp_path=None, **kw):
    return NameSpeller(client, cache_path=(tmp_path / "cache.json") if tmp_path else None,
                       overrides=kw.pop("overrides", {}), **kw)


def test_salon_is_the_approved_saloon_not_a_transliteration():
    c = Fake()
    assert speller(c).spoken("Shreya Salon") == "श्रेया saloon"
    assert c.calls == ["Shreya"]  # the glossary word never went to the API
    assert speller(c).spoken("Looks Unisex Salon") == "लुक्स unisex saloon"
    assert speller(c).spoken("SALOON") == "saloon" and speller().spoken("Salon") == "saloon"


@pytest.mark.parametrize("word,spoken", [
    ("Parlour", "parlour"), ("Spa", "spa"), ("Beauty", "beauty"), ("Hair", "hair"),
    ("Studio", "studio"), ("Clinic", "clinic"), ("Unisex", "unisex"),
])
def test_glossary_words_keep_their_approved_form(word, spoken):
    assert speller(Fake()).spoken(word) == spoken


def test_multi_word_names_are_transliterated_as_one_run_and_joined():
    c = Fake()
    assert speller(c).spoken("Ravi Kumar Hair Studio") == "रवि कुमार hair studio"
    assert c.calls == ["Ravi Kumar"]  # one call for the run, not one per word
    c2 = Fake({"Glow": "ग्लो", "Meena": "मीना"})
    assert speller(c2).spoken("Glow Beauty Meena") == "ग्लो beauty मीना"  # runs split by glossary
    assert c2.calls == ["Glow", "Meena"]


def test_a_person_name_goes_through_the_same_pipeline():
    assert speller(Fake()).spoken("Himanshu") == "हिमांशु"


def test_ampersand_and_junk_are_sanitised():
    sp = speller(Fake({"Ravi": "रवि", "Sons": "सन्स"}))
    assert sp.spoken("Ravi & Sons Hair Studio") == "रवि aur सन्स hair studio"
    assert sanitise("Glow 24/7 <b>Spa</b>!") == "Glow b Spa b"
    assert sanitise("Shreya & Co. - Spa") == "Shreya & Co. - Spa"
    assert sanitise("12345") == ""  # digits-only is not a name
    assert len(sanitise("a" * 200)) <= 60
    assert sanitise("x " * 100).count(" ") < 40


def test_digits_never_survive_into_the_spoken_form():
    assert not any(ch.isdigit() for ch in speller(Fake()).spoken("Studio 11 Spa 24"))


def test_overrides_win_over_everything(tmp_path):
    c = Fake()
    sp = speller(c, overrides={"shreya": "श्री-या", "looks unisex salon": "लुक्स यूनिसेक्स सैलून",
                               "salon": "सैलून"})
    assert sp.spoken("Shreya Salon") == "श्री-या सैलून"  # word overrides beat glossary + API
    assert sp.spoken("Looks Unisex Salon") == "लुक्स यूनिसेक्स सैलून"  # a full name beats all
    assert c.calls == []
    # the shipped file is valid and loads
    ov = names.load_overrides()
    assert ov["looks"] == "लुक्स" and all(isinstance(v, str) for v in ov.values())
    assert names.load_overrides(tmp_path / "missing.json") == {}


def test_the_disk_cache_means_a_known_name_never_calls_the_api_again(tmp_path):
    c = Fake()
    assert speller(c, tmp_path).spoken("Shreya Salon") == "श्रेया saloon"
    assert c.calls == ["Shreya"]
    data = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert data == {"shreya": "श्रेया"}  # keyed by the normalised name
    c2 = Fake(fail=True)  # a brand new speller (a new process) with a broken API
    assert speller(c2, tmp_path).spoken("SHREYA salon") == "श्रेया saloon"
    assert c2.calls == []
    # the same name in the same process: also one call only
    c3 = Fake()
    sp = speller(c3)
    sp.spoken("Looks")
    sp.spoken("looks")
    assert c3.calls == ["Looks"]


@pytest.mark.parametrize("client", [
    None, Fake(fail=True), Fake({}), Fake({"Shreya": ""}), Fake({"Shreya": "12345"}),
    lambda t: None, lambda t: 5,
])
def test_when_the_api_fails_or_is_missing_the_roman_name_stays(client, tmp_path):
    sp = speller(client, tmp_path)
    assert sp.spoken("Shreya Salon") == "Shreya saloon"  # the call never fails because of a name
    assert not (tmp_path / "cache.json").exists()  # failures are not cached


def test_a_failing_api_is_not_hammered_within_a_process():
    c = Fake(fail=True)
    sp = speller(c)
    for _ in range(3):
        sp.spoken("Shreya")
    assert c.calls == ["Shreya"]


def test_an_empty_or_symbol_only_name_is_empty_not_a_crash():
    assert speller(Fake()).spoken("") == "" and speller(Fake()).spoken("@@@") == ""


def test_normalise_is_the_cache_key():
    assert normalise("  Shreya   SALON! ") == "shreya salon" and normalise("A & B") == "a and b"


# ------------------------------------------------------------------ the real client (mock transport)
def test_the_sarvam_client_posts_the_documented_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["api-subscription-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"transliterated_text": "श्रेया"})

    call = sarvam_transliterator("k-123", transport=httpx.MockTransport(handler))
    assert call("Shreya") == "श्रेया"
    assert seen["url"] == "https://api.sarvam.ai/transliterate" and seen["key"] == "k-123"
    assert seen["body"] == {"input": "Shreya", "source_language_code": "en-IN",
                            "target_language_code": "hi-IN"}


@pytest.mark.parametrize("response", [
    httpx.Response(402, json={"error": "no credits"}), httpx.Response(500, text="boom"),
    httpx.Response(200, text="not json"), httpx.Response(200, json={"other": 1}),
])
def test_the_sarvam_client_returns_none_on_any_failure(response):
    call = sarvam_transliterator("k", transport=httpx.MockTransport(lambda r: response))
    assert call("Shreya") is None
    boom = sarvam_transliterator("k", transport=httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))))
    assert boom("Shreya") is None


def test_speller_from_settings_is_offline_without_a_key_or_in_the_simulator():
    from pydantic import SecretStr

    class S:
        sarvam_api_key = None
        mode = "live"

    assert names.speller_from_settings(S()).client is None
    S.sarvam_api_key = SecretStr("k")
    S.mode = "simulator"
    assert names.speller_from_settings(S()).client is None  # tests/simulator never call out
    S.mode = "live"
    assert names.speller_from_settings(S()).client is not None


# ------------------------------------------------------------------ services
@pytest.mark.parametrize("text,items,joined", [
    ("haircut", ["haircut"], "haircut"),
    ("haircut, beard trim", ["haircut", "beard trim"], "haircut aur beard trim"),
    ("Haircut and Beard Trim", ["haircut", "beard trim"], "haircut aur beard trim"),
    ("haircut, beard trim aur facial", ["haircut", "beard trim", "facial"], "haircut, beard trim aur facial"),
    ("haircut + beard trim & facial", ["haircut", "beard trim", "facial"], "haircut, beard trim aur facial"),
    ("", [], ""),
])
def test_services_join_naturally_in_the_owners_words(text, items, joined):
    assert parse_services(text) == items and join_services(items) == joined


def test_services_are_not_transliterated_unless_an_override_says_so():
    sp = speller(Fake(), overrides={"beard trim": "बियर्ड ट्रिम"})
    assert sp.spoken_service("haircut") == "haircut" and sp.spoken_service("facial") == "facial"
    assert sp.spoken_service("beard trim") == "बियर्ड ट्रिम"


def test_the_engine_builds_services_spoken_and_stays_backward_compatible():
    from friday.playbooks.engine import resolve_inputs
    from friday.playbooks.model import get_playbook
    from tests.playbooks.conftest import make_brief

    pb = get_playbook("salon_booking")
    old = resolve_inputs(pb, make_brief(inputs={"services": ""}))  # only the older `service` input
    assert old["services_spoken"] == "haircut" and old["service"] == "haircut"
    three = resolve_inputs(pb, make_brief(inputs={"services": "haircut, beard trim and facial"}))
    assert three["services_spoken"] == "haircut, beard trim aur facial"
    assert three["services"] == "haircut, beard trim, facial"
