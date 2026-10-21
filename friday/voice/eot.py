# ruff: noqa: E501
"""Semantic end-of-turn: has the caller FINISHED, judged from the words (default OFF).

Silence alone cannot tell "Haan, kal shaam ko..." (unfinished, they will carry on after a breath)
from "Haan ji, 500 rupaye" (finished). This module reads the early / partial transcript that is
available while the pause is being timed out and answers ``complete`` / ``incomplete`` /
``unsure`` with a confidence. Pure Python, no third-party libraries, no network, no randomness.

Two layers (same style as ``friday/playbooks/classifier.py``):

1. deterministic RULES (Roman + Devanagari Hindi / Hinglish / English): a trailing postposition or
   connector (ko se ka ke ki mein par aur lekin toh matlab so and but because ...), a trailing filler
   (umm hmm acha), an ellipsis, a dangling numeral without its unit, a half-dictated phone number,
   an hour that has not been said yet, ``ke liye``; and the finished shapes: closed short answers
   ("haan ji", "nahi", "ji bataiye"), verb-final sentences, a price after a price question, a clock
   time with ``baje``.
2. a small trained MODEL (naive Bayes over hashed word and character n-grams, one JSON file plus a
   version file with the metrics and the regression-gate verdict), used only where no hard rule fired.

Used by ``SarvamCallLeg`` (see ``docs/LATENCY.md``, 2026-10-21 second section):
* incomplete (confidence >= threshold): the silence wait of THIS pause is extended (default +700 ms,
  capped); nothing is said, nothing is cut;
* complete (confidence >= threshold) and the answer is short: the utterance is committed at the early
  point instead of waiting out the pause;
* unsure: nothing changes.
It never changes a spoken word.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
import zlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger

log = get_logger(__name__)

LEARNING_DIR = Path(__file__).resolve().parent / "learning"
MODEL_PATH = LEARNING_DIR / "eot_model.json"
VERSION_PATH = LEARNING_DIR / "eot_model.version.json"
FORMAT = 1
FEATURE_BITS = 16
SCALE = 20
DEFAULT_THRESHOLD = 0.9
HARD_RULE = 0.9  # a rule at or above this confidence is final; weaker rules defer to the model

# what the step expects the caller to say (passed in by the caller of the detector)
ANSWER_TYPES = ("", "price", "time", "yesno", "name", "phone")


class Verdict(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNSURE = "unsure"


@dataclass(frozen=True)
class EotDecision:
    verdict: Verdict
    confidence: float
    source: str  # "rule:<name>" | "model" | "rule+model" | "none"
    detail: str = ""

    @property
    def complete(self) -> bool:
        return self.verdict is Verdict.COMPLETE

    @property
    def incomplete(self) -> bool:
        return self.verdict is Verdict.INCOMPLETE


UNSURE = EotDecision(Verdict.UNSURE, 0.0, "none")

# ----------------------------------------------------------------------------------- text
_TOKEN = re.compile(r"[\wऀ-ॣ०-ॿ]+(?::\d+)?", re.UNICODE)
_DIGIT_RE = re.compile(r"[0-9०-९]")
_ELLIPSIS_END = ("...", "…", "..", "—", "--", "–")
_TERMINAL = ".?!।"


def tokens_of(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text or "").lower().replace("₹", " rs ")
    return _TOKEN.findall(t.replace("_", " "))


def _end_mark(text: str) -> str:
    t = (text or "").rstrip()
    if t.endswith(_ELLIPSIS_END):
        return "ellipsis"
    if t.endswith(","):
        return "comma"
    if t and t[-1] in _TERMINAL:
        return "stop"
    return "none"


def _digit_count(text: str) -> int:
    return len(_DIGIT_RE.findall(text or ""))


# ----------------------------------------------------------------------------------- lexicons
# trailing words after which a speaker is almost always about to say more
_TAIL_STRONG = frozenset({
    # postpositions / particles
    "ko", "se", "ka", "ke", "ki", "kaa", "ne", "liye", "lie", "wala", "wali", "waale", "vaala",
    # connectors
    "aur", "lekin", "magar", "toh", "to", "matlab", "so", "and", "but", "because", "kyunki",
    "kyuki", "ya", "or", "agar", "if", "jab", "tab", "phir", "fir", "jo", "jisme", "isliye",
    "that", "which", "when", "while", "then", "also", "as", "of", "for", "with", "the", "a",
    "an", "my", "your", "our", "is", "are", "was", "will", "i", "we", "about", "around",
    "nearly", "roughly", "approximately", "lagbhag", "takreeban", "kareeb", "kareeban",
    # fillers / hedges
    "umm", "ummm", "um", "uh", "uhh", "uhm", "hmm", "hmmm", "hm", "err", "er", "aaa", "aa",
    "wo", "woh", "yeh", "ye", "dekhiye", "suno", "actually", "basically", "waise",
    "yaar", "jaise", "like", "well", "isme", "isse", "usme", "usse", "kuch", "koi",
    # Devanagari
    "को", "से", "का", "के", "की", "ने", "लिए", "वाला", "वाली", "वाले", "और", "लेकिन", "मगर",
    "तो", "मतलब", "क्योंकि", "या", "अगर", "जब", "तब", "फिर", "जो", "इसलिए", "कि", "उम्म",
    "उम्", "हम्म", "वो", "यह", "ये", "देखिए", "सुनो", "यार", "जैसे", "इसमें", "उसमें",
    "कुछ", "कोई",
})
# weaker: also end complete answers ("WhatsApp pe", "ghar par", "kal tak", "achha")
_TAIL_MEDIUM = frozenset({
    "mein", "me", "mai", "par", "pe", "tak", "per", "in", "on", "at", "by", "acha",
    "achha", "accha", "achcha", "में", "पर", "पे", "तक", "अच्छा",
    "bhi", "भी",
})

_CLOSED = frozenset({
    "haan", "han", "haa", "ha", "haanji", "ji", "jee", "nahi", "nahin", "nai", "nahee", "na",
    "yes", "no", "yeah", "yep", "nope", "ok", "okay", "theek", "thik", "hai", "bilkul", "sahi",
    "correct", "boliye", "bolie", "boliyega", "bataiye", "bataye", "bolo", "batao", "kahiye",
    "sunaiye", "sir", "madam", "mam", "please", "sure", "right", "go", "ahead", "tell", "me",
    "speaking", "hello", "hallo", "namaste", "namaskar", "hanji",
    "हाँ", "हां", "हा", "जी", "नहीं", "नही", "ना", "बिल्कुल", "ठीक", "है", "सही", "बोलिए",
    "बताइए", "बोलो", "बताओ", "कहिए", "सर", "मैडम", "हैलो", "नमस्ते",
})
_VERB_FINAL = frozenset({
    "hai", "hain", "hoga", "hogi", "honge", "tha", "thi", "the", "hoon", "hu", "ho", "gaya",
    "gayi", "gaye", "diya", "di", "liya", "li", "kiya", "karunga", "karungi", "karenge",
    "karega", "karegi", "karta", "karti", "karte", "denge", "dunga", "dungi", "dega", "degi",
    "milega", "milegi", "milenge", "chalega", "chalegi", "chahiye", "sakta", "sakti", "sakte",
    "lagega", "lagegi", "lagenge", "raha", "rahi", "rahe", "jayega", "jayegi", "jaunga",
    "jaungi", "aaunga", "aaungi", "aayega", "aayegi", "padega", "padegi", "padta", "nahi",
    "nahin", "milta", "milti", "hota", "hoti", "hote", "kijiye", "kariye", "jaiye", "dijiye",
    "bhejiye", "bataunga", "bataungi", "batata", "batati", "dekhte", "dekhenge", "pata",
    "fine", "possible", "available", "ready", "done",
    "है", "हैं", "होगा", "होगी", "होंगे", "था", "थी", "थे", "हूँ", "हूं", "गया", "दिया",
    "किया", "करूँगा", "करेंगे", "देंगे", "मिलेगा", "चलेगा", "चाहिए", "सकता", "सकते",
    "लगेगा", "लगेंगे", "रहा", "रही", "जाएगा", "आऊँगा", "पड़ेगा", "नहीं", "जाइए", "कीजिए",
    "दीजिए", "बताऊँगा", "मिलता", "होता", "पता", "मिल", "ठीक", "सही",
})
_POLITE_END = frozenset({
    "ji", "jee", "sir", "madam", "mam", "please", "thanks", "thank", "you", "dhanyavad",
    "dhanyavaad", "shukriya", "bye", "welcome", "जी", "सर", "मैडम", "धन्यवाद", "शुक्रिया",
    "okay", "ok", "sure",
})
_UNITS = frozenset({
    "rupaye", "rupay", "rupaya", "rupees", "rupee", "rs", "inr", "baje", "bje", "pm", "am",
    "minute", "minutes", "min", "ghante", "ghanta", "ghantey", "din", "log", "people", "percent",
    "रुपये", "रुपया", "बजे", "मिनट", "घंटे", "दिन", "लोग",
})
_MAGNITUDE = frozenset({
    "sau", "hazaar", "hazar", "lakh", "hundred", "thousand", "सौ", "हज़ार", "हजार", "लाख",
})
_NUMBER_WORDS = frozenset({
    "ek", "do", "teen", "char", "chaar", "paanch", "panch", "chhe", "chhah", "cheh", "saat",
    "aath", "nau", "das", "gyarah", "barah", "terah", "chaudah", "pandrah", "solah", "satrah",
    "atharah", "unnis", "bees", "tees", "chalis", "pachas", "saath", "sattar", "assi", "nabbe",
    "dedh", "dhai", "dhaai", "saadhe", "sade", "shunya", "zero", "one", "two", "three", "four",
    "five", "six", "seven", "eight", "nine", "ten", "twenty", "thirty", "forty", "fifty",
    "एक", "दो", "तीन", "चार", "पाँच", "पांच", "छह", "छः", "सात", "आठ", "नौ", "दस", "बीस",
    "तीस", "चालीस", "पचास", "डेढ़", "ढाई", "साढ़े",
}) | _MAGNITUDE
_DAYPART = frozenset({
    "kal", "aaj", "parso", "parson", "subah", "subha", "savere", "dopahar", "shaam", "sham",
    "raat", "tomorrow", "today", "tonight", "morning", "evening", "afternoon", "night",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "somvar", "mangalvar", "budhvar", "guruvar", "shukravar", "shanivar", "ravivar",
    "कल", "आज", "परसों", "सुबह", "दोपहर", "शाम", "रात",
})


def _is_number_token(t: str) -> bool:
    return bool(_DIGIT_RE.search(t)) or t in _NUMBER_WORDS


# ----------------------------------------------------------------------------------- rules
@dataclass(frozen=True)
class RuleHit:
    verdict: Verdict
    confidence: float
    name: str


def apply_rules(text: str, answer_type: str = "") -> RuleHit | None:
    """The deterministic layer. None = no rule has anything to say (the model may)."""
    toks = tokens_of(text)
    if not toks:
        return None
    mark = _end_mark(text)
    last = toks[-1]
    last2 = " ".join(toks[-2:])
    digits = _digit_count(text)
    stop_penalty = 0.08 if mark == "stop" else 0.0

    if mark == "ellipsis":
        return RuleHit(Verdict.INCOMPLETE, 0.97, "ellipsis")

    # --- a phone number may be dictated in pieces: fewer than 10 digits so far = more to come
    if answer_type == "phone" or (digits >= 3 and any(t in ("number", "नंबर") for t in toks)):
        n = digits or sum(1 for t in toks if t in _NUMBER_WORDS)
        if n >= 10:
            return RuleHit(Verdict.COMPLETE, 0.95, "phone_full")
        if n >= 1 and not (last in _VERB_FINAL or last in _POLITE_END):
            return RuleHit(Verdict.INCOMPLETE, 0.95, "phone_partial")
        if n == 0 and answer_type == "phone" and last in ("number", "नंबर", "hai", "है"):
            return RuleHit(Verdict.INCOMPLETE, 0.9, "phone_not_started")

    # --- "mera naam hai ..." / "mera number hai ..." : the name or number is still to come
    mine = any(t in ("mera", "my", "meri", "मेरा", "मेरी") for t in toks[:-1])
    pending = last in ("naam", "name", "नाम") or (last in ("number", "नंबर") and mine)
    if not pending and len(toks) >= 2 and last in ("hai", "है", "is"):
        pending = toks[-2] in ("naam", "name", "नाम") or (toks[-2] in ("number", "नंबर") and mine)
    if pending:
        return RuleHit(Verdict.INCOMPLETE, 0.93 - stop_penalty, "name_or_number_pending")

    # --- a unit finishes a number ("500 rupaye", "6 baje")
    if last in _UNITS and any(_is_number_token(t) for t in toks):
        return RuleHit(Verdict.COMPLETE, 0.93, "number_unit")

    # --- trailing postposition / connector / filler (the text may still end in "." from the STT)
    if last in _TAIL_STRONG:
        return RuleHit(Verdict.INCOMPLETE, 0.95 - stop_penalty, f"tail:{last}")
    if last2 in ("ke liye", "ke baad", "ke saath", "ke pass", "ke bare", "ki wajah", "ki tarah",
                 "के लिए", "के बाद", "के साथ"):
        if last2 in ("ke baad", "के बाद") and answer_type == "time":
            return RuleHit(Verdict.COMPLETE, 0.9, "time_baad")
        return RuleHit(Verdict.INCOMPLETE, 0.93 - stop_penalty, f"tail:{last2}")
    if mark == "comma":
        return RuleHit(Verdict.INCOMPLETE, 0.88, "trailing_comma")

    # --- a dangling numeral
    if _is_number_token(last) and last not in _MAGNITUDE:
        if answer_type == "price":
            if _DIGIT_RE.search(last) and len(re.sub(r"\D", "", last)) >= 2:
                return RuleHit(Verdict.COMPLETE, 0.93, "price_digits")
            return RuleHit(Verdict.INCOMPLETE, 0.82, "number_word_dangling")
        if answer_type == "time":
            if ":" in last:
                return RuleHit(Verdict.COMPLETE, 0.93, "clock_time")
            return RuleHit(Verdict.INCOMPLETE, 0.85, "hour_without_baje")
        if answer_type == "phone":
            return None
        if digits and digits < 10 and len(toks) > 1:
            return RuleHit(Verdict.INCOMPLETE, 0.7, "digits_dangling")
        return None
    if last in _MAGNITUDE and any(_is_number_token(t) for t in toks[:-1]):
        if answer_type == "price":
            return RuleHit(Verdict.COMPLETE, 0.9, "price_magnitude")
        return None

    # --- a day word with no hour where an hour is expected ("kal shaam")
    if answer_type == "time" and last in _DAYPART and not any(_is_number_token(t) for t in toks):
        return RuleHit(Verdict.INCOMPLETE, 0.8, "daypart_without_hour")

    if last in _TAIL_MEDIUM:
        return RuleHit(Verdict.INCOMPLETE, 0.86 - stop_penalty, f"tail_weak:{last}")

    # --- finished shapes
    if len(toks) <= 5 and all(t in _CLOSED for t in toks):
        return RuleHit(Verdict.COMPLETE, 0.96, "closed_answer")
    if last in _POLITE_END and len(toks) >= 2 and toks[-2] not in _TAIL_STRONG:
        return RuleHit(Verdict.COMPLETE, 0.91, "polite_end")
    if last in _VERB_FINAL:
        return RuleHit(Verdict.COMPLETE, 0.9, "verb_final")
    if mark == "stop":
        return RuleHit(Verdict.COMPLETE, 0.6, "terminal_punctuation")
    return None


# ----------------------------------------------------------------------------------- the model
def _h(s: str) -> int:
    return zlib.crc32(s.encode("utf-8")) & ((1 << FEATURE_BITS) - 1)


def featurize(text: str, answer_type: str = "") -> dict[int, float]:
    """Hashed features: words, word bigrams, the last one and two words (alone and with the
    expected answer type), the end punctuation, the length, character n-grams of every word and
    of the last 12 characters. Deterministic (crc32), L2-normalised."""
    toks = tokens_of(text)
    if not toks:
        return {}
    mark = _end_mark(text)
    counts: dict[int, float] = {}

    def add(key: str, w: float = 1.0) -> None:
        i = _h(key)
        counts[i] = counts.get(i, 0.0) + w

    norm = [("<num>" if _DIGIT_RE.search(t) else t) for t in toks]
    for w in norm:
        add("w:" + w)
    for a, b in zip(norm, norm[1:], strict=False):
        add("b:" + a + " " + b)
    last = norm[-1]
    add("last:" + last, 2.0)
    add("lastmark:" + last + "|" + mark)
    if len(norm) > 1:
        add("last2:" + " ".join(norm[-2:]), 1.5)
    add("first:" + norm[0])
    add("end:" + mark)
    add(f"n:{min(len(norm), 10)}")
    add(f"digits:{min(_digit_count(text), 12)}")
    if answer_type:
        add("ctx:" + answer_type)
        add("ctx_last:" + answer_type + "|" + last, 1.5)
        add("ctx_n:" + answer_type + f"|{min(len(norm), 6)}")
    for w in norm:
        p = f" {w} "
        for n in (2, 3, 4):
            for i in range(max(0, len(p) - n + 1)):
                add(f"c{n}:{p[i : i + n]}", 0.4)
    tail = " ".join(norm)[-12:]
    for n in (2, 3, 4, 5):
        for i in range(max(0, len(tail) - n + 1)):
            add(f"t{n}:{tail[i : i + n]}", 0.8)
    vec = {k: 1.0 + math.log(v) if v > 1 else v for k, v in counts.items()}
    norm2 = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm2 for k, v in vec.items()}


CLASSES = ("complete", "incomplete")


class EotModel:
    """Two-class multinomial naive Bayes (uniform prior) over the hashed features.

    ``counts[feature] = ((class_index, mass), ...)`` is sparse; a pair never seen scores ``alpha``.
    ``p_complete = sigmoid(beta * (score_complete - score_incomplete))``, ``beta`` fitted on
    cross-validation at training time.
    """

    def __init__(
        self, counts: dict[int, tuple[tuple[int, float], ...]], alpha: float = 0.2,
        beta: float = 1.0,
    ) -> None:
        self.counts = counts
        self.alpha = alpha
        self.beta = beta
        mass = [0.0, 0.0]
        for cw in counts.values():
            for c, m in cw:
                mass[c] += m
        self.mass = mass

    def p_complete(self, text: str, answer_type: str = "") -> float:
        feats = featurize(text, answer_type)
        if not feats:
            return 0.5
        v = 1 << FEATURE_BITS
        denom = [self.mass[c] + self.alpha * v for c in (0, 1)]
        score = [0.0, 0.0]
        for f, x in feats.items():
            cw = dict(self.counts.get(f, ()))
            for c in (0, 1):
                score[c] += x * math.log((cw.get(c, 0.0) + self.alpha) / denom[c])
        z = self.beta * (score[0] - score[1])
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-min(z, 50.0)))
        e = math.exp(max(z, -50.0))
        return e / (1.0 + e)

    # ---- file format: integers of 1/SCALE, sorted keys: the same data gives the same bytes
    def dumps(self) -> str:
        feats = {
            str(f): [[c, round(m * SCALE)] for c, m in cw if round(m * SCALE) > 0]
            for f, cw in sorted(self.counts.items())
        }
        feats = {f: cw for f, cw in feats.items() if cw}
        return json.dumps(
            {"format": FORMAT, "classes": list(CLASSES), "feature_bits": FEATURE_BITS,
             "scale": SCALE, "alpha": self.alpha, "beta": self.beta, "features": feats},
            separators=(",", ":"), sort_keys=True, ensure_ascii=True,
        )

    @classmethod
    def loads(cls, raw: str) -> EotModel:
        d = json.loads(raw)
        if d.get("format") != FORMAT or d.get("feature_bits") != FEATURE_BITS:
            raise ValueError("unsupported end-of-turn model format")
        if d.get("classes") != list(CLASSES):
            raise ValueError("end-of-turn model has other classes")
        scale = float(d.get("scale", SCALE))
        counts = {
            int(f): tuple((int(c), m / scale) for c, m in cw) for f, cw in d["features"].items()
        }
        return cls(counts, alpha=float(d["alpha"]), beta=float(d["beta"]))


def load_version(path: Path | None = None) -> dict[str, Any] | None:
    try:
        v = json.loads((path or VERSION_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return v if isinstance(v, dict) else None


def load_active(
    model_path: Path | None = None, version_path: Path | None = None
) -> tuple[EotModel, dict[str, Any]] | None:
    """The shipped model, only if its version file says the regression gate passed."""
    mp = model_path or MODEL_PATH
    ver = load_version(version_path or (mp.with_name(mp.stem + ".version.json")
                                         if model_path else VERSION_PATH))
    if not ver or not (ver.get("gate") or {}).get("passed"):
        return None
    try:
        return EotModel.loads(mp.read_text(encoding="utf-8")), ver
    except (OSError, ValueError, KeyError):
        return None


# ----------------------------------------------------------------------------------- detector
@dataclass(frozen=True)
class EotConfig:
    """Settings of the semantic end-of-turn feature (FRIDAY_VOICE_SEMANTIC_EOT*)."""

    enabled: bool = False
    extend_ms: int = 700  # extra silence wait when the caller is confidently unfinished
    max_extend_ms: int = 1500  # hard cap on the extension, whatever the setting says
    threshold: float | None = None  # None = the trained model's chosen threshold, else 0.9
    commit_max_words: int = 6  # a complete answer this short may be committed early

    @property
    def extend(self) -> int:
        return max(0, min(self.extend_ms, self.max_extend_ms))


class SemanticEot:
    """``assess(text, answer_type)`` -> ``EotDecision``. Never raises."""

    def __init__(
        self, model: EotModel | None = None, threshold: float = DEFAULT_THRESHOLD,
        rules_only: bool = False,
    ) -> None:
        self.model = None if rules_only else model
        self.threshold = threshold

    def assess(self, text: str, answer_type: str = "") -> EotDecision:
        try:
            return self._assess(text, answer_type if answer_type in ANSWER_TYPES else "")
        except Exception as e:  # noqa: BLE001 - an extra must never break a call
            log.warning("semantic eot failed (%s); unsure", type(e).__name__)
            return UNSURE

    def _assess(self, text: str, answer_type: str) -> EotDecision:
        thr = self.threshold
        hit = apply_rules(text, answer_type)
        if hit is not None and hit.confidence >= max(HARD_RULE, thr):
            return EotDecision(hit.verdict, hit.confidence, "rule:" + hit.name)
        if self.model is None:
            if hit is not None and hit.confidence >= thr:
                return EotDecision(hit.verdict, hit.confidence, "rule:" + hit.name)
            return UNSURE
        if not tokens_of(text):
            return UNSURE
        p = self.model.p_complete(text, answer_type)
        if p >= thr:
            verdict, conf = Verdict.COMPLETE, p
        elif 1.0 - p >= thr:
            verdict, conf = Verdict.INCOMPLETE, 1.0 - p
        else:
            if hit is not None and hit.confidence >= thr:  # model unsure, a rule is fairly sure
                return EotDecision(hit.verdict, hit.confidence, "rule:" + hit.name)
            return UNSURE
        if hit is not None and hit.verdict is not verdict and hit.confidence >= 0.7:
            return UNSURE  # a softer rule and the model disagree: change nothing
        src = "rule+model" if hit is not None and hit.verdict is verdict else "model"
        return EotDecision(verdict, conf, src)


def build_semantic_eot(cfg: EotConfig) -> SemanticEot | None:
    """None when the switch is off. With the switch on and no gate-passed model: rules only."""
    if not cfg.enabled:
        return None
    active = load_active()
    model = active[0] if active else None
    threshold = cfg.threshold
    if threshold is None:
        threshold = float((active[1] if active else {}).get("threshold", DEFAULT_THRESHOLD))
    if model is None:
        log.info("semantic eot: no gate-passed model, using the rules only")
    return SemanticEot(model, threshold)
