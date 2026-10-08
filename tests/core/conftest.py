import pytest


@pytest.fixture(autouse=True)
def _no_llm_keys_in_env(monkeypatch):
    """Config tests must not see a developer's exported OpenAI key (auto -> fake)."""
    for k in ("OPENAI_API_KEY", "FRIDAY_OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
