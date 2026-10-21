"""A small trained intent classifier for the playbook understanding (no model call).

Pure Python, no third-party libraries: multinomial naive Bayes over hashed word and
character n-gram features, stored as one small JSON file (``learning/intent_classifier.json``)
next to a version file that records the data hash, the metrics and whether the regression gate
passed (``learning/intent_classifier.version.json``). Training lives in
``friday/learning/classifier_train.py``; this module is only the part the live call needs.

It answers ONE question: "which of the closed ``Intent`` words is this reply, and how sure?".
It is used only when ALL of these hold (see ``PlaybookPolicy._understand_raw``):

* the switch ``FRIDAY_INTENT_CLASSIFIER`` is on (default OFF) and a gate-passed model is present,
* the rules were not already confident (the rules always win; they are free and audited),
* the stop / secret / rude / AI-question hard rules did not fire (they run first, in code),
* the confidence is at or above ``FRIDAY_INTENT_CLASSIFIER_THRESHOLD``,
* the intent carries no extracted value (``SAFE_INTENTS``: a price, a time or a name still needs
  the rules / model to read the number out of the words) and is allowed at this step.

Anything else takes the existing rules + model path unchanged. It never writes a spoken word.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from friday.core.logging import get_logger
from friday.playbooks.intents import INTENTS, Intent

log = get_logger(__name__)

LEARNING_DIR = Path(__file__).resolve().parent / "learning"
MODEL_PATH = LEARNING_DIR / "intent_classifier.json"
VERSION_PATH = LEARNING_DIR / "intent_classifier.version.json"
FORMAT = 1
FEATURE_BITS = 16
SCALE = 20  # stored masses are integers of 1/20: a small file
DEFAULT_THRESHOLD = 0.9

# Intents the classifier may answer ON ITS OWN: the intent alone is the whole understanding (no
# price / time / name / number to extract). The hard-rule intents (stop calling, secrets, rude,
# AI question) are never taken from the classifier: the rules decide those before any model.
SAFE_INTENTS: frozenset[str] = frozenset(
    i.value
    for i in (
        Intent.YES, Intent.NO, Intent.CONTINUE, Intent.ACK, Intent.BUSY_LATER,
        Intent.WHO_IS_THIS, Intent.ASKS_REPEAT, Intent.WRONG_NUMBER, Intent.HOLD_ON,
        Intent.SLOT_BUSY, Intent.NEEDS_APPOINTMENT, Intent.ASKS_CUSTOMER_PHONE,
        Intent.PRICE_DEPENDS, Intent.REFUSES_PRICE, Intent.ASKS_OFFTOPIC,
        Intent.OUT_OF_STOCK, Intent.VISIT_NEEDED, Intent.WHATSAPP_PLEASE, Intent.NO_CHARGE,
    )
)

_DIGITS = re.compile(r"\d+")
_NON_WORD = re.compile(r"[^\w\u0900-\u0963\u0966-\u097F<>]+")


def normalise_text(text: str) -> str:
    """NFKC, lower-case, a run of digits becomes ``<num>`` (``<phone>`` when 7+ digits),
    punctuation dropped, spaces collapsed."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = _DIGITS.sub(lambda m: " <num> " if len(m.group()) < 7 else " <phone> ", t)
    return " ".join(_NON_WORD.sub(" ", t.replace("_", " ")).split())


def _h(s: str) -> int:
    return zlib.crc32(s.encode("utf-8")) & ((1 << FEATURE_BITS) - 1)


def featurize(text: str) -> dict[int, float]:
    """Hashed word 1-2-grams and character 2-5-grams (inside word boundaries), sub-linear counts,
    L2-normalised. Deterministic (crc32), no vocabulary file."""
    t = normalise_text(text)
    words = t.split()
    if not words:
        return {}
    counts: dict[int, float] = {}

    def add(key: str, w: float = 1.0) -> None:
        i = _h(key)
        counts[i] = counts.get(i, 0.0) + w

    for w in words:
        add("w:" + w)
    for a, b in zip(words, words[1:], strict=False):
        add("b:" + a + " " + b)
    add("first:" + words[0])
    add("last:" + words[-1])
    add(f"n:{min(len(words), 12)}")
    for w in words:
        p = f" {w} "
        for n in (2, 3, 4, 5):
            if len(p) < n:
                continue
            for i in range(len(p) - n + 1):
                add(f"c{n}:{p[i : i + n]}", 0.5)
    if not counts:
        return {}
    vec = {k: 1.0 + math.log(v) if v > 1 else v for k, v in counts.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {k: v / norm for k, v in vec.items()}


@dataclass(frozen=True)
class Prediction:
    intent: str
    confidence: float
    runner_up: str = ""


class IntentClassifier:
    """Multinomial naive Bayes over the hashed features.

    ``counts[feature] = ((class_index, mass), ...)`` is sparse: a (feature, class) pair that never
    occurred in training is not stored and scores as ``alpha`` (Laplace-style smoothing). The score
    of class c is ``sum_f x_f * log((n_fc + alpha) / (N_c + alpha * V))`` (uniform class prior, so
    the many synthetic sentences of an intent do not tilt it); the confidence is
    ``softmax(beta * score)``, where ``beta`` is fitted on cross-validation at training time.
    """

    def __init__(
        self, classes: list[str], counts: dict[int, tuple[tuple[int, float], ...]],
        alpha: float = 0.2, beta: float = 4.0,
    ) -> None:
        self.classes = classes
        self.counts = counts
        self.alpha = alpha
        self.beta = beta
        mass = [0.0] * len(classes)
        for cw in counts.values():
            for c, m in cw:
                mass[c] += m
        self.mass = mass
        v = float(1 << FEATURE_BITS)
        self._log_den = [math.log(m + alpha * v) for m in mass]
        self._log_alpha = math.log(alpha)

    def with_params(self, alpha: float, beta: float) -> IntentClassifier:
        return IntentClassifier(self.classes, self.counts, alpha, beta)

    # ------------------------------------------------------------------ scoring
    def scores(self, text: str) -> list[float]:
        k = len(self.classes)
        x = featurize(text)
        total = sum(x.values())
        z = [self._log_alpha * total - self._log_den[c] * total for c in range(k)]
        for f, v in x.items():
            for c, m in self.counts.get(f, ()):
                z[c] += v * (math.log(m + self.alpha) - self._log_alpha)
        return z

    def probabilities(self, text: str) -> list[float]:
        z = [self.beta * t for t in self.scores(text)]
        m = max(z)
        e = [math.exp(t - m) for t in z]
        s = sum(e)
        return [t / s for t in e]

    def predict(self, text: str) -> Prediction:
        if not featurize(text):
            return Prediction(Intent.UNCLEAR.value, 0.0)
        p = self.probabilities(text)
        order = sorted(range(len(p)), key=lambda i: (-p[i], i))
        top, second = order[0], order[1] if len(order) > 1 else order[0]
        return Prediction(self.classes[top], round(p[top], 6), self.classes[second])

    # ------------------------------------------------------------------ files
    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "kind": "multinomial_naive_bayes",
            "feature_bits": FEATURE_BITS,
            "classes": self.classes,
            "alpha": self.alpha,
            "beta": self.beta,
            "scale": SCALE,
            # sparse: feature -> [class_index, round(mass * scale), ...] flattened
            "counts": {
                str(f): [x for c, m in cw if round(m * SCALE) for x in (c, round(m * SCALE))]
                for f, cw in sorted(self.counts.items())
                if any(round(m * SCALE) for _c, m in cw)
            },
        }

    def dumps(self) -> str:
        return json.dumps(self.to_json(), separators=(",", ":"), ensure_ascii=False) + "\n"

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> IntentClassifier:
        if data.get("format") != FORMAT or data.get("feature_bits") != FEATURE_BITS:
            raise ValueError("unsupported classifier format")
        classes = [str(c) for c in data["classes"]]
        if not set(classes) <= INTENTS:
            raise ValueError("classifier names an unknown intent")
        scale = float(data.get("scale", SCALE))
        counts = {
            int(f): tuple((int(flat[i]), flat[i + 1] / scale) for i in range(0, len(flat), 2))
            for f, flat in data["counts"].items()
        }
        return cls(classes, counts, float(data["alpha"]), float(data["beta"]))

    @classmethod
    def loads(cls, text: str) -> IntentClassifier:
        return cls.from_json(json.loads(text))


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_version(path: Path | str | None = None) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path or VERSION_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


_CACHE: dict[str, tuple[float, IntentClassifier | None]] = {}


def load_active(
    model_path: Path | str | None = None, version_path: Path | str | None = None
) -> IntentClassifier | None:
    """The model the live call may use: file present, version file present, the version file says
    the regression gate passed, and its recorded sha matches the model file. Otherwise None (the
    existing rules + model path runs). Never raises."""
    mp, vp = Path(model_path or MODEL_PATH), Path(version_path or VERSION_PATH)
    try:
        key = f"{mp}|{vp}"
        stamp = mp.stat().st_mtime + vp.stat().st_mtime
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        ver = load_version(vp)
        model: IntentClassifier | None = None
        gate_ok = bool(ver and (ver.get("gate") or {}).get("passed") is True)
        if ver and gate_ok and ver.get("model_sha256") == file_sha(mp):
            model = IntentClassifier.loads(mp.read_text(encoding="utf-8"))
        else:
            log.warning("intent classifier not activated: missing / failed gate / sha mismatch")
        _CACHE[key] = (stamp, model)
        return model
    except (OSError, ValueError, KeyError, TypeError) as e:
        log.warning("intent classifier not loaded (%s)", type(e).__name__)
        return None


@dataclass(frozen=True)
class ClassifierDecision:
    """What the classifier said and whether the live call may use it."""

    intent: str
    confidence: float
    used: bool
    reason: str  # "hit" | "below_threshold" | "not_safe_intent" | "not_allowed_here" | "no_model"


def decide(
    text: str,
    model: IntentClassifier | None,
    threshold: float,
    allowed: set[str] | frozenset[str] | list[str] | None = None,
) -> ClassifierDecision:
    if model is None:
        return ClassifierDecision(Intent.UNCLEAR.value, 0.0, False, "no_model")
    p = model.predict(text)
    if p.confidence < threshold:
        return ClassifierDecision(p.intent, p.confidence, False, "below_threshold")
    if p.intent not in SAFE_INTENTS:
        return ClassifierDecision(p.intent, p.confidence, False, "not_safe_intent")
    if allowed is not None and p.intent not in set(allowed):
        return ClassifierDecision(p.intent, p.confidence, False, "not_allowed_here")
    return ClassifierDecision(p.intent, p.confidence, True, "hit")
