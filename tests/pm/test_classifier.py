# ruff: noqa: E501
import json
from pathlib import Path

import pytest

from friday.core.interfaces import LLMResponse, ProviderError
from friday.pm.classifier import (
    CHANNELS,
    Classification,
    ClassifierOutputError,
    KeywordClassifier,
    LLMClassifier,
    classification_schema,
    parse_classification,
)
from friday.pm.taxonomy import bucket_keys, category_keys

FIX = json.loads((Path(__file__).parent / "fixtures" / "classifier_examples.json").read_text())


def test_fixture_shape():
    assert len(FIX) >= 60
    assert sum(e["channel"] == "call" for e in FIX) >= 20
    assert {e["lang"] for e in FIX} >= {"en", "hi", "hinglish"}
    assert {e["channel"] for e in FIX} <= set(CHANNELS)
    assert {e["bucket"] for e in FIX} <= set(bucket_keys())
    assert {e["category"] for e in FIX} - {None} <= set(category_keys())
    assert set(category_keys()) <= {e["category"] for e in FIX}  # all 22 covered
    assert set(bucket_keys()) <= {e["bucket"] for e in FIX}      # all 10 covered


def test_keyword_baseline_accuracy_report(capsys):
    clf = KeywordClassifier()
    stats = {}
    for e in FIX:
        r = clf.classify_sync(e["text"])
        for k, ok in (("bucket", r.bucket == e["bucket"]), ("category", r.category == e["category"]),
                      ("both", r.bucket == e["bucket"] and r.category == e["category"])):
            stats.setdefault((e["channel"], k), []).append(ok)
    with capsys.disabled():
        for (ch, k), v in sorted(stats.items()):
            print(f"\nbaseline {ch:14s} {k:8s} {sum(v)}/{len(v)} = {sum(v) / len(v):.0%}", end="")
    # NOTE: the baseline keywords were written alongside this fixture, so this is optimistic.
    assert sum(stats[("whatsapp_text", "both")]) / len(stats[("whatsapp_text", "both")]) >= 0.85
    assert sum(stats[("call", "both")]) / len(stats[("call", "both")]) >= 0.8


def test_parse_valid_and_none_category():
    c = parse_classification('{"bucket":"quote","category":"salon","confidence":0.9}')
    assert c == Classification(bucket="quote", category="salon", confidence=0.9)
    assert parse_classification('{"bucket":"other","category":"none","confidence":0.2}').category is None


@pytest.mark.parametrize("raw", [
    "not json", "[]", '{"bucket":"quote","category":"salon"}',
    '{"bucket":"quote","category":"salon","confidence":0.9,"x":1}',
    '{"bucket":"haircut","category":"salon","confidence":0.9}',
    '{"bucket":"quote","category":"spaceship","confidence":0.9}',
    '{"bucket":"quote","category":"salon","confidence":1.5}',
    '{"bucket":"quote","category":"salon","confidence":"high"}',
    '{"bucket":"quote","category":"salon","confidence":true}',
])
def test_parse_rejects_anything_off(raw):
    with pytest.raises(ClassifierOutputError):
        parse_classification(raw)


def test_schema_is_closed():
    s = classification_schema()
    assert s["additionalProperties"] is False
    assert set(s["properties"]["bucket"]["enum"]) == set(bucket_keys())
    assert len(s["properties"]["category"]["enum"]) == 23


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def complete(self, **kw):
        self.calls.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResponse(text=r, model="fake")


GOOD = '{"bucket":"quote","category":"salon","confidence":0.93}'


async def test_llm_classifier_ok_and_channel_note():
    llm = FakeLLM([GOOD, GOOD])
    c = LLMClassifier(llm)
    assert (await c.classify("haircut kitna")).category == "salon"
    await c.classify("haircut kitna", "call")
    assert "speech-to-text" not in llm.calls[0]["messages"][0].content
    assert "speech-to-text" in llm.calls[1]["messages"][0].content
    assert llm.calls[0]["json_schema"] == classification_schema()
    assert llm.calls[0]["model"] == "gpt-5.4-mini"


async def test_llm_classifier_repairs_once_then_unsure():
    c = LLMClassifier(FakeLLM(["garbage", GOOD]))
    assert (await c.classify("x")).bucket == "quote" and c.repairs == 1
    c2 = LLMClassifier(FakeLLM(["garbage", '{"bucket":"zzz"}']))
    assert await c2.classify("x") == Classification.unsure()
    c3 = LLMClassifier(FakeLLM([ProviderError("openai", "boom")]))
    assert (await c3.classify("x")).confidence == 0.0
