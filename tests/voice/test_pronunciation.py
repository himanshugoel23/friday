"""Sarvam pronunciation dictionary: validation, sync (create then update), payload, cache key."""

from __future__ import annotations

import json

import httpx
import pytest

from friday.core.models import Language
from friday.voice.tts import pronunciation as pron
from friday.voice.tts.cache import CachedTTS
from friday.voice.tts.sarvam import SarvamTTS


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_shipped_file_is_valid():
    assert sum(len(w) for w in pron.load().values()) >= 1


def test_validation_rejects_bad_files(tmp_path):
    for bad in ({}, {"pronunciations": {}}, {"pronunciations": {"hi-IN": {"a": ""}}},
                {"pronunciations": {"hi-IN": {f"w{i}": "x" for i in range(101)}}}):
        with pytest.raises(ValueError):
            pron.load(_write(tmp_path / "d.json", bad))


def test_sync_creates_then_updates_in_place(tmp_path):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.params.get("dict_id")))
        assert req.headers["api-subscription-key"] == "k"
        assert b"application/json" in req.content[:400]
        return httpx.Response(200, json={"dictionary_id": "p_abc"})

    f = _write(tmp_path / "d.json", {"pronunciations": {"hi-IN": {"AI": "A I"}}})
    idf = tmp_path / "id.json"
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        first = pron.sync("k", file=f, id_file=idf, client=c)
        second = pron.sync("k", file=f, id_file=idf, client=c)
    assert first["action"] == "created" and second["action"] == "updated"
    assert calls == [("POST", None), ("PUT", "p_abc")]
    assert pron.active(None, idf)[0] == "p_abc"
    assert pron.active("p_env", idf)[0] == "p_env"  # the environment setting wins


def test_a_refused_dictionary_raises(tmp_path):
    f = _write(tmp_path / "d.json", {"pronunciations": {"hi-IN": {"AI": "A I"}}})
    transport = httpx.MockTransport(lambda r: httpx.Response(400, text="no"))
    with httpx.Client(transport=transport) as c, pytest.raises(RuntimeError):
        pron.sync("k", file=f, id_file=tmp_path / "i.json", client=c)


def _tts(**kw):
    from friday.core.config import Settings
    from friday.voice.langs import VoiceCatalog
    from friday.voice.tts.sarvam import DEFAULT_FEMALE_SPEAKER

    return SarvamTTS("k", VoiceCatalog("sarvam", Settings(), {}, DEFAULT_FEMALE_SPEAKER), **kw)


def test_dict_id_is_sent_only_for_v3():
    tts = _tts(dict_id="p_1", dict_version="v1")
    body = tts.payload("hello", Language.HINGLISH, tts.voice_for(Language.HINGLISH))
    assert body["dict_id"] == "p_1"
    assert "dict_id" not in _tts().payload("hello", Language.HINGLISH,
                                           _tts().voice_for(Language.HINGLISH))


def test_changed_dictionary_changes_the_cache_key():
    a, b = CachedTTS(_tts(dict_version="one")), CachedTTS(_tts(dict_version="two"))
    voice = a.voice_for(Language.HINGLISH)
    assert a._key("hi", Language.HINGLISH, voice) != b._key("hi", Language.HINGLISH, voice)
