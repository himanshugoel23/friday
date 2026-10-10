"""How business and person names are SPOKEN (Devanagari where that helps the voice).

``spoken_name("Shreya Salon") -> "श्रेया saloon"``. The pipeline, per name:

1. a human override (``name_overrides.json``: a full name or a single word -> its exact spoken
   form) always wins;
2. generic business words come from the GLOSSARY with an approved spoken form that is NOT
   transliterated (``salon`` -> ``saloon``, chosen by ear by the founder);
3. the remaining words (runs of consecutive words, so a multi-word name stays coherent) are
   transliterated with Sarvam (``POST /transliterate``, en-IN -> hi-IN) through an injectable
   client, and every answer is cached on disk (``var/names/cache.json``, keyed by the normalised
   text) so a known name never calls the API again;
4. anything that fails (no key, no network, empty or odd answer) keeps the ROMAN word: a call must
   never fail because of a name.

The result is sanitised (letters, combining marks, space, ``&``, ``-``, ``.`` only; length cap).
Names are worked out when a task/call is set up, never mid-call; the spoken text then goes through
the normal TTS pre-render cache like every other line.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from friday.core.logging import get_logger

log = get_logger(__name__)

OVERRIDES_FILE = Path(__file__).with_name("name_overrides.json")
CACHE_FILE = Path("var/names/cache.json")
TRANSLITERATE_URL = "https://api.sarvam.ai/transliterate"
MAX_SPOKEN_CHARS = 60

# generic business words -> the approved spoken form (kept as written, NOT transliterated)
GLOSSARY: dict[str, str] = {
    "salon": "saloon",
    "saloon": "saloon",
    "salons": "saloons",
    "parlour": "parlour",
    "parlor": "parlour",
    "spa": "spa",
    "unisex": "unisex",
    "beauty": "beauty",
    "hair": "hair",
    "studio": "studio",
    "clinic": "clinic",
    "boutique": "boutique",
    "barber": "barber",
    "barbers": "barbers",
    "shop": "shop",
    "care": "care",
    "wellness": "wellness",
    "makeover": "makeover",
    "makeup": "makeup",
    "nails": "nails",
    "nail": "nail",
    "lounge": "lounge",
    "academy": "academy",
    "and": "aur",
    "the": "the",
    "co": "company",
    "pvt": "",  # dropped: nobody says "private limited" aloud
    "ltd": "",
    "private": "",
    "limited": "",
}

# a client turns Roman text into Devanagari; None/exception = could not
Transliterator = Callable[[str], "str | None"]

_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*|[^\W\d_]+", re.U)
_KEEP_PUNCT = " &-."


def normalise(text: str) -> str:
    """Cache / lookup key: lower case, letters and digits only, single spaces."""
    t = re.sub(r"[^\w\s]", " ", (text or "").lower().replace("&", " and "), flags=re.U)
    return re.sub(r"\s+", " ", t).strip()


def sanitise(text: str, limit: int = MAX_SPOKEN_CHARS) -> str:
    """Keep letters (any script), combining marks, spaces and ``& - .``; drop the rest (digits
    included); collapse spaces; cap the length at a word boundary."""
    out = []
    for ch in text or "":
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "M") or ch in _KEEP_PUNCT:
            out.append(ch)
        else:
            out.append(" ")
    s = re.sub(r"\s+", " ", "".join(out)).strip(" -.")
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0] if " " in s[:limit] else s[:limit]
    return s.strip()


def _has_letters(s: str) -> bool:
    return any(unicodedata.category(c)[0] == "L" for c in s)


def load_overrides(path: Path = OVERRIDES_FILE) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = data.get("overrides", data) if isinstance(data, dict) else {}
    return {
        normalise(k): v.strip()
        for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, str) and v.strip() and not k.startswith("_")
    }


def sarvam_transliterator(
    api_key: str, *, timeout_s: float = 4.0, transport: httpx.BaseTransport | None = None
) -> Transliterator:
    """The real client: ``POST https://api.sarvam.ai/transliterate`` (en-IN -> hi-IN)."""

    def call(text: str) -> str | None:
        try:
            with httpx.Client(timeout=timeout_s, transport=transport) as http:
                r = http.post(
                    TRANSLITERATE_URL,
                    headers={"api-subscription-key": api_key},
                    json={
                        "input": text,
                        "source_language_code": "en-IN",
                        "target_language_code": "hi-IN",
                    },
                )
            if r.status_code >= 400:
                return None
            out = r.json().get("transliterated_text")
            return out if isinstance(out, str) else None
        except (httpx.HTTPError, ValueError):
            return None

    return call


class NameSpeller:
    """Turns names into their spoken form. Offline-safe: without a client it still applies the
    overrides and the glossary and keeps every other word Roman."""

    def __init__(
        self,
        client: Transliterator | None = None,
        *,
        cache_path: Path | None = CACHE_FILE,
        overrides: dict[str, str] | None = None,
        glossary: dict[str, str] | None = None,
    ) -> None:
        self.client = client
        self.cache_path = cache_path
        self.overrides = overrides if overrides is not None else load_overrides()
        self.glossary = {**GLOSSARY, **(glossary or {})}
        self._cache: dict[str, str] | None = None
        self._failed: set[str] = set()  # this process only: do not hammer a down API
        self.api_calls = 0

    # ---------------------------------------------------------------- cache
    def _load(self) -> dict[str, str]:
        if self._cache is None:
            self._cache = {}
            if self.cache_path is not None:
                try:
                    data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        self._cache = {k: v for k, v in data.items() if isinstance(v, str)}
                except (OSError, ValueError):
                    pass
        return self._cache

    def _save(self) -> None:
        if self.cache_path is None or self._cache is None:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tmp.replace(self.cache_path)
        except OSError:
            log.warning("could not save the names cache")

    # ---------------------------------------------------------------- pieces
    def _transliterate(self, run: str) -> str:
        """One run of consecutive words -> Devanagari, or the Roman run if anything goes wrong."""
        key = normalise(run)
        cache = self._load()
        if key in cache:
            return cache[key]
        if self.client is None or key in self._failed:
            return run
        try:
            self.api_calls += 1
            got = self.client(run)
        except Exception as e:  # noqa: BLE001 - a name never fails a call
            log.warning("name transliteration failed (%s); keeping the Roman name", type(e).__name__)  # noqa: E501
            self._failed.add(key)
            return run
        clean = sanitise(got) if isinstance(got, str) else ""
        if not clean or not _has_letters(clean):
            self._failed.add(key)
            return run
        cache[key] = clean
        self._save()
        return clean

    def spoken(self, text: str) -> str:
        """The spoken form of one business or person name (never raises, never empty for a
        non-empty name)."""
        roman = sanitise(text)
        if not roman:
            return ""
        full = self.overrides.get(normalise(text))
        if full:
            return sanitise(full) or roman
        words = roman.replace("&", " & ").split()
        out: list[str] = []
        run: list[str] = []

        def flush() -> None:
            if run:
                out.append(self._transliterate(" ".join(run)))
                run.clear()

        for w in words:
            key = normalise(w)
            fixed = self.overrides.get(key, self.glossary.get(key))
            if w == "&":
                flush()
                out.append("aur")
            elif fixed is not None:
                flush()
                if fixed:
                    out.append(fixed)
            elif not key:
                continue
            elif re.fullmatch(r"[^\W\d_]+", w) and w.isascii():
                run.append(w)
            else:
                flush()
                out.append(w)  # already Devanagari / other script: leave it
        flush()
        return sanitise(" ".join(out)) or roman

    def spoken_service(self, text: str) -> str:
        """Services keep the owner's words; only an explicit override changes them."""
        s = sanitise(text)
        return sanitise(self.overrides.get(normalise(text), s)) or s


_DEFAULT: NameSpeller | None = None


def default_speller() -> NameSpeller:
    """Offline speller (overrides + glossary + disk cache, no API client)."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = NameSpeller()
    return _DEFAULT


def speller_from_settings(settings: Any) -> NameSpeller:
    """A speller that uses the Sarvam key when the app is running live; otherwise offline."""
    key = getattr(settings, "sarvam_api_key", None)
    live = getattr(settings, "mode", "simulator") != "simulator"
    if key and live:
        return NameSpeller(sarvam_transliterator(key.get_secret_value()))
    return default_speller()


def spoken_name(text: str, *, speller: NameSpeller | None = None) -> str:
    return (speller or default_speller()).spoken(text)


# ------------------------------------------------------------------ services
_SERVICE_SPLIT = re.compile(r"\s*(?:,|;|/|\+|&|\band\b|\baur\b)\s*", re.I)


def parse_services(text: str | list[str] | None) -> list[str]:
    """"haircut, beard trim aur facial" -> ["haircut", "beard trim", "facial"] (the owner's words)."""  # noqa: E501
    if text is None:
        return []
    items = [text] if isinstance(text, str) else list(text)
    out: list[str] = []
    for item in items:
        for part in _SERVICE_SPLIT.split(str(item)):
            p = sanitise(part, 30).lower()
            if p and p not in out:
                out.append(p)
    return out[:4]


def join_services(services: list[str]) -> str:
    """'haircut' | 'haircut aur beard trim' | 'haircut, beard trim aur facial'."""
    if len(services) <= 1:
        return services[0] if services else ""
    if len(services) == 2:
        return f"{services[0]} aur {services[1]}"
    return ", ".join(services[:-1]) + " aur " + services[-1]
