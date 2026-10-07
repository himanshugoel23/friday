"""Runs last in this package: every transition in the state table must have been
exercised by the scenario tests above (skips when run in isolation)."""

import pytest

from friday.tasks import states
from tests.tasks.conftest import ALL_TRANSITIONS


def test_every_allowed_transition_exercised():
    if len(ALL_TRANSITIONS) < 10:
        pytest.skip("run the whole tests/tasks package to check transition coverage")
    missing = states.all_transitions() - ALL_TRANSITIONS
    assert not missing, sorted((a.value, b.value) for a, b in missing)
