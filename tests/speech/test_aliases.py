from friday.core.models import Person, Place
from friday.speech.memory import MemoryView, build_memory
from friday.speech.understander import _apply_aliases


def test_alias_replaces_only_whole_words_longest_first():
    out, rep = _apply_aliases("Shriya salon mein jana hai", {"shriya salon": "Shreya Salon",
                                                           "shriya": "Shreya"})
    assert out == "Shreya Salon mein jana hai" and rep[0].kind == "mishearing"
    assert _apply_aliases("shriyaji ko bolo", {"shriya": "Shreya"})[0] == "shriyaji ko bolo"


def test_relation_aliases_are_not_treated_as_mishearings():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    ctx = SimpleNamespace(
        profile=None, people=[Person(owner_user_id="u", name="Ramesh Sharma",
                                    aliases=["papa", "ramesh sharmaa"])],
        places=[Place(owner_user_id="u", label="Shreya Salon", aliases=["shriya salon"])],
        known_businesses=[], open_tasks=[], recent=[], pending_question=None, now=datetime.now(UTC),
    )
    mv = build_memory(ctx)
    assert "papa" not in mv.aliases
    assert mv.aliases["ramesh sharmaa"] == "Ramesh Sharma"
    assert mv.aliases["shriya salon"] == "Shreya Salon"
    assert isinstance(MemoryView().aliases, dict)
