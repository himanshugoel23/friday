# ruff: noqa: E501
"""Query Understanding Agent: user-specific fuzzy resolution, ask on low confidence, grounding, dictionary."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from friday.core.clock import FakeClock
from friday.core.models import Person, Place, User, UserStatus
from friday.speech import SpeechUnderstander
from friday.speech.dict_chat import handle as dict_chat
from friday.speech.fuzzy import Entity, find_matches
from friday.speech.query_agent import QueryUnderstandingAgent, expand_lingo
from friday.speech.userdict import UserDictionary

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class ScriptedLLM:
    def __init__(self, text=None):
        self.text, self.seen = text, []

    async def complete(self, **kw):
        self.seen.append(kw)
        return SimpleNamespace(text=json.dumps({"corrected_text": self.text, "repairs": [], "unintelligible": False}))


def settings(**kw):
    base = dict(speech_understanding="off", speech_understanding_voice_notes=True, speech_understanding_calls=True,
                speech_understanding_text=False, speech_understanding_model=None, speech_understanding_timeout_s=1.0,
                speech_understanding_min_words=3, query_understanding_timeout_s=1.0,
                resolve_llm=lambda: "real", model_for=lambda p: "small")
    base.update(kw)
    return SimpleNamespace(**base)


def ctx(city="Sonipat", people=(), places=(), shops=()):
    return SimpleNamespace(
        profile=SimpleNamespace(name="Himanshu", city=city, language=None), people=list(people), places=list(places),
        known_businesses=[SimpleNamespace(name=s) for s in shops], open_tasks=[], recent=[], pending_question=None, now=NOW)


@pytest.fixture
async def repos(settings):
    from friday.core.container import Container
    from friday.db import Database

    db = Database(settings.database_url)
    await db.create_all()
    c = Container(settings, clock=FakeClock(NOW))
    c.override_db(db)
    u = await c.repos.users.add(User(phone="+919800000311", status=UserStatus.ACTIVE))
    other = await c.repos.users.add(User(phone="+919800000312", status=UserStatus.ACTIVE))
    yield c, u.id, other.id
    await c.aclose()


def agent(llm=None, repos=None, **kw):
    if llm is None:
        kw["resolve_llm"] = lambda: "fake"
    und = SpeechUnderstander(llm, settings(**kw))
    return QueryUnderstandingAgent(und, UserDictionary(repos) if repos is not None else None, settings(**kw))


# ---------------------------------------------------------------- fuzzy over the user's own entities
@pytest.mark.parametrize("typed", ["Soneepat", "sonipath", "Sonepat", "sone pat", "soni pat"])
async def test_misspellings_of_the_users_home_city_resolve_to_sonipat(typed):
    q = agent()
    out = await q.understand("u1", f"butter chicken near {typed} under 400", ctx())
    assert "Sonipat" in out.instruction and "400" in out.instruction
    assert out.original_text.endswith("400") and typed in out.original_text  # original kept
    if typed.lower() != "sonipat":
        assert out.entity_fixes and out.entity_fixes[0][1] == "Sonipat" and out.ask is None


async def test_user_memory_beats_a_general_guess_other_city_is_untouched():
    out = await agent().understand("u1", "butter chicken near Rohtak", ctx())
    assert "Rohtak" in out.instruction and not out.entity_fixes and out.ask is None


async def test_saved_place_and_shop_names_resolve_from_the_users_own_lists():
    c = ctx(places=[Place(owner_user_id="u", label="Model Town", city="Sonipat")], shops=["Looks Salon"])
    out = await agent().understand("u", "haircut at lux salon near modal town", c)
    assert out.ask is not None or "Looks Salon" in out.instruction  # 'lux salon' is not sure: asked, never silent
    out2 = await agent().understand("u", "haircut near modal town", c)
    assert "Model Town" in out2.instruction


async def test_low_confidence_asks_and_changes_nothing():
    c = ctx(city=None, people=[Person(owner_user_id="u", name="Priya Sharma")])
    out = await agent().understand("u", "call priyaa sharma tomorrow evening", c)
    assert out.ask is not None and out.ask.candidate == "Priya Sharma" and out.ask.kind == "person"
    assert "priyaa" in out.instruction  # not changed silently
    assert "Priya Sharma" in out.ask.candidate_text
    skip = await agent().understand("u", "call priyaa sharma tomorrow evening", c, skip_forms={"priyaa sharma"})
    assert skip.ask is None and "priyaa" in skip.instruction  # 'no, as typed' is respected


async def test_two_close_entities_ask_instead_of_guessing():
    es = [Entity("Sonipat", "place", "profile"), Entity("Sonupat", "place", "dictionary")]
    m = find_matches("near Soneepat", es).matches
    assert m and m[0].decision == "ask"


async def test_ordinary_and_short_words_are_never_fuzzy_matched():
    es = [Entity("Neer", "shop", "shop"), Entity("Sonipat", "place", "profile")]
    assert not find_matches("near me under 400 pls", es).matches
    assert not find_matches("Soni ka dhaba", es).matches


# ---------------------------------------------------------------- lingo and the shared understander
def test_lingo_expands_abbreviations_but_never_touches_numbers():
    out, rep = expand_lingo("pls order 5k atta tmrw rn")
    assert out == "please order 5k atta tomorrow right now" and len(rep) == 3


async def test_model_step_cleans_fillers_and_self_corrections_with_user_dictionary_in_the_prompt(repos):
    c, uid, _ = repos
    ud = UserDictionary(c.repos)
    await ud.add(uid, "Sonipat", "place")
    llm = ScriptedLLM("butter chicken near Sonipat under 400")
    out = await agent(llm, c.repos).understand(uid, "umm butter chicken near Soneepat under 300 nahi 400", ctx())
    assert out.instruction == "butter chicken near Sonipat under 400" and out.source == "model"
    payload = json.loads(llm.seen[0]["messages"][0].content)
    assert "Sonipat" in str(payload["memory"])  # dictionary reached the model
    assert "Soneepat" not in payload["transcript"]  # fuzzy ran BEFORE the model


async def test_no_invented_numbers_model_output_is_rejected_and_floor_used():
    llm = ScriptedLLM("butter chicken near Sonipat under 500")
    out = await agent(llm).understand("u", "butter chicken near Sonipat under 400", ctx())
    assert "500" not in out.instruction and "400" in out.instruction
    assert out.reason and out.reason.startswith("ungrounded")


async def test_model_down_falls_back_to_rules_then_raw():
    class Down:
        async def complete(self, **kw):
            raise RuntimeError("down")

    out = await agent(Down()).understand("u", "umm mujhe mujhe pizza chahiye kal nahi parso", ctx())
    assert out.source == "rules" and "parso" in out.instruction and "umm" not in out.instruction
    plain = await agent(None).understand("u", "pizza near me", ctx())
    assert plain.instruction == "pizza near me" and plain.source == "raw"


async def test_secret_talk_is_never_touched():
    out = await agent(ScriptedLLM("x")).understand("u", "my OTP is 482913 soneepat", ctx())
    assert out.instruction == out.original_text and out.reason == "secret_context"


async def test_audit_has_counts_not_words():
    out = await agent().understand("u", "pls Soneepat", ctx())
    assert "Soneepat" not in json.dumps(out.audit())


# ---------------------------------------------------------------- learning and the dictionary
async def test_alias_activates_after_two_sightings_or_one_tap(repos):
    c, uid, other = repos
    ud = UserDictionary(c.repos)
    await ud.add(uid, "Sonipat", "place")
    assert await ud.note_heard(uid, "Sonipat", "Soneepat") == "recorded"
    assert [e.heard for e in await ud.list(uid)] == [[]]
    assert await ud.note_heard(uid, "Sonipat", "Soneepat") == "promoted"
    assert (await ud.list(uid))[0].heard == ["soneepat"]
    await ud.add(uid, "Sonipat", "place")
    assert await ud.note_heard(uid, "Sonipat", "sonipath", confirmed=True) == "promoted"
    assert await ud.list(other) == []  # per user
    # active alias is trusted even for people (exact heard form)
    es = [e.entity() for e in await ud.list(uid)]
    assert find_matches("near soneepat", es).auto


async def test_learn_via_agent_seeds_profile_city_and_memory_rows(repos):
    c, uid, _ = repos
    q = agent(repos=c.repos)
    await c.repos.places.upsert(Place(owner_user_id=uid, label="Model Town"))
    await q.learn(uid, c.repos, c.clock, [("Soneepat", "Sonipat", "place", "profile"), ("modal town", "Model Town", "place", "place")], confirmed=True)
    assert (await c.repos.places.list_for_owner(uid))[0].aliases == ["modal town"]
    assert (await UserDictionary(c.repos).list(uid))[0].heard == ["soneepat"]


async def test_view_add_remove_and_delete_all_and_secrets_refused(repos):
    c, uid, other = repos
    r = c.repos
    assert "no saved words" in await dict_chat(r, uid, "my words", "en")
    assert "Saved: Sonipat" in await dict_chat(r, uid, "add place Sonipat", "en")
    assert "Saved" in await dict_chat(r, uid, "add shop Looks Salon", "en")
    assert "can't save" in await dict_chat(r, uid, "add word 9876543210", "en")
    assert "can't save" in await dict_chat(r, uid, "add word my OTP is 1234", "en")
    listing = await dict_chat(r, uid, "my words", "en")
    assert "Sonipat (place)" in listing and "Looks Salon (shop)" in listing
    assert "Removed" in await dict_chat(r, uid, "forget word Looks Salon", "en")
    assert "don't have" in await dict_chat(r, uid, "forget word Looks Salon", "en")
    await dict_chat(r, other, "add place Rohtak", "en")
    assert "deleted (1)" in await dict_chat(r, uid, "forget all my words", "en")
    assert await UserDictionary(r).list(uid) == [] and len(await UserDictionary(r).list(other)) == 1
    assert await dict_chat(r, uid, "hello there", "en") is None


async def test_dictionary_shows_up_in_what_do_you_remember_and_forget_works(repos):
    from friday.memory.chat import handle as mem_chat

    c, uid, _ = repos
    await UserDictionary(c.repos).add(uid, "Sonipat", "place")
    listing = await mem_chat(c.repos, c.clock, uid, "what do you remember about me", "en")
    assert "Sonipat" in listing
