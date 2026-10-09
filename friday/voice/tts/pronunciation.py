"""Sarvam pronunciation dictionary (bulbul:v3 only): fix how words are spoken.

``pronunciations.json`` (next to this file) maps language -> word -> how to say it, e.g.
``{"pronunciations": {"hi-IN": {"AI": "A I"}, "en-IN": {"Shreya": "Shree-ya"}}}``.
Edit it, then run
``friday tts-dict sync``: the first sync creates the dictionary at Sarvam (POST) and saves its id in
``var/tts/dict_id.json``; later syncs update it in place (PUT, same id). The voice reads the id from
``SARVAM_PRONUNCIATION_DICT_ID`` if set, else from that file, and sends it as ``dict_id`` with every
speech request. Limits (Sarvam): 100 words, 10 dictionaries, 1 MB. Docs:
https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/pronunciation-dictionary
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

DEFAULT_FILE = Path(__file__).with_name("pronunciations.json")
ID_FILE = Path("var/tts/dict_id.json")
MAX_WORDS = 100
BASE = "https://api.sarvam.ai"


def load(path: Path = DEFAULT_FILE) -> dict[str, dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    prons = data.get("pronunciations")
    if not isinstance(prons, dict):
        raise ValueError("pronunciations.json needs a top-level 'pronunciations' object")
    total = 0
    for lang, words in prons.items():
        if not isinstance(words, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
            for k, v in words.items()
        ):
            raise ValueError(f"{lang}: every entry must be 'word': 'how to say it' (non-empty)")
        total += len(words)
    if total == 0:
        raise ValueError("no pronunciations yet: add at least one entry")
    if total > MAX_WORDS:
        raise ValueError(f"{total} words; Sarvam allows {MAX_WORDS} per dictionary")
    return prons


def digest(prons: dict[str, dict[str, str]]) -> str:
    blob = json.dumps(prons, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()[:10]


def saved_state(path: Path = ID_FILE) -> dict[str, str]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def active(env_dict_id: str | None = None, path: Path = ID_FILE) -> tuple[str | None, str]:
    """(dict_id, version) the voice should use. The version feeds the audio cache key, so a changed
    dictionary never replays audio recorded with the old pronunciations."""
    state = saved_state(path)
    dict_id = env_dict_id or state.get("dict_id")
    return (dict_id, state.get("digest", "") if dict_id else "")


def sync(api_key: str, *, file: Path = DEFAULT_FILE, id_file: Path = ID_FILE,
         base_url: str = BASE, client: httpx.Client | None = None) -> dict[str, Any]:
    prons = load(file)
    body = json.dumps({"pronunciations": prons}, ensure_ascii=False).encode("utf-8")
    files = {"file": ("dict.json", body, "application/json")}
    headers = {"api-subscription-key": api_key}
    state = saved_state(id_file)
    own = client is None
    http = client or httpx.Client(timeout=30)
    try:
        if state.get("dict_id"):
            r = http.put(f"{base_url}/text-to-speech/pronunciation-dictionary",
                         params={"dict_id": state["dict_id"]}, files=files, headers=headers)
            action, dict_id = "updated", state["dict_id"]
        else:
            r = http.post(f"{base_url}/text-to-speech/pronunciation-dictionary",
                          files=files, headers=headers)
            action, dict_id = "created", None
        if r.status_code >= 400:
            raise RuntimeError(
                f"Sarvam refused the dictionary (HTTP {r.status_code}): {r.text[:200]}"
            )
        if dict_id is None:
            dict_id = r.json().get("dictionary_id")
            if not dict_id:
                raise RuntimeError("Sarvam did not return a dictionary id")
    finally:
        if own:
            http.close()
    id_file.parent.mkdir(parents=True, exist_ok=True)
    id_file.write_text(json.dumps({"dict_id": dict_id, "digest": digest(prons)}))
    return {"action": action, "dict_id": dict_id, "words": sum(len(w) for w in prons.values())}
