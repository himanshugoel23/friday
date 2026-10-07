"""Heuristic AudioClassifier (V-5, C23): human / IVR prompt / hold music / queue
announcement / voicemail / silence.

Two signals, combined by real call legs:
  * acoustics (``classify``): frame energy + zero-crossing statistics. Speech has a
    syllabic envelope (frequent dips, high energy variance); music/tones are sustained
    (few dips, low variance); a short pure tone is a voicemail beep; near-zero energy
    is silence. Speech-like audio is reported as HUMAN - acoustically an IVR prompt is
    speech too, so the text decides.
  * keywords (``classify_text``) on the STT transcript: "your call is important",
    "press 1", "leave a message after the beep", Hindi equivalents.

``combine(audio, text)`` is what ``TwilioCallLeg`` uses. Cheap enough to run on every
chunk during hold-listening mode (no LLM).
"""

from __future__ import annotations

import re
import statistics

from friday.core.container import Container
from friday.core.models import AudioClass, AudioClassification, AudioClip
from friday.voice.audio import clip_to_pcm16, frame_features

_QUEUE = re.compile(
    r"your call is (very )?important|all (of )?our (executives|agents|representatives|"
    r"associates|customer care executives) are (currently )?(busy|assisting)|please (stay|hold)"
    r"( on the line)?|estimated (wait|waiting) time|you are (number|caller|at position) \d+|"
    r"in (the )?queue|will be (answered|attended) (shortly|soon|in)|kripya (line par )?bane rahe|"
    r"intezaar kare|pratiksha kare|कृपया लाइन पर बने रहें|प्रतीक्षा करें|आपकी कॉल हमारे लिए",
    re.I,
)
_IVR = re.compile(
    r"\bpress \d|\bpress (star|hash|zero|one|two|three|four|five|six|seven|eight|nine)\b|"
    r"\bdial \d|\bfor .{1,40}, (press|dial)|\benter your\b|followed by (the )?(hash|pound)|"
    r"main menu|to repeat (this|these) (menu|options)|\d dabaye|dabaye\b|दबाएं|दबाइए|"
    r"\bselect\b.{0,20}\boption",
    re.I,
)
_VOICEMAIL = re.compile(
    r"leave (a|your) message|after the (beep|tone)|voice ?mail|mailbox|not available.{0,30}"
    r"(message|beep)|is (currently )?(switched off|not reachable|out of coverage)|"
    r"सन्देश छोड़|संदेश छोड़|switched off|not reachable",
    re.I,
)
_MUSIC_MARK = re.compile(r"^\s*[\[(♪♫]*\s*(hold music|music|♪|♫)", re.I)


class HeuristicAudioClassifier:
    """Satisfies ``friday.core.interfaces.AudioClassifier``."""

    silence_rms: float = 300.0
    min_speech_s: float = 0.3

    async def classify(self, audio: AudioClip) -> AudioClassification:
        decoded = clip_to_pcm16(audio)
        if decoded is None:  # fake/text clips (simulator, fake TTS)
            try:
                text = audio.data.decode("utf-8")
            except UnicodeDecodeError:
                return AudioClassification(audio_class=AudioClass.UNKNOWN, confidence=0.2)
            return self.classify_text(text) or AudioClassification(
                audio_class=AudioClass.HUMAN if text.strip() else AudioClass.SILENCE,
                confidence=0.5,
            )
        pcm, rate = decoded
        return self.classify_pcm(pcm, rate)

    def classify_pcm(self, pcm16: bytes, sample_rate: int) -> AudioClassification:
        feats = frame_features(pcm16, sample_rate)
        if not feats:
            return AudioClassification(audio_class=AudioClass.SILENCE, confidence=1.0)
        energies = [e for e, _ in feats]
        peak = max(energies)
        if peak < self.silence_rms:
            return AudioClassification(audio_class=AudioClass.SILENCE, confidence=0.95)
        threshold = max(self.silence_rms, 0.15 * peak)
        active = [(e, z) for e, z in feats if e >= threshold]
        frame_s = 0.02
        active_s = len(active) * frame_s
        total_s = len(feats) * frame_s
        active_ratio = len(active) / len(feats)
        a_energy = [e for e, _ in active]
        a_zcr = [z for _, z in active]
        e_cv = statistics.pstdev(a_energy) / (statistics.fmean(a_energy) or 1)
        z_cv = statistics.pstdev(a_zcr) / (statistics.fmean(a_zcr) or 1)
        # transitions active <-> inactive per second: speech ~3-8/s, music/tones ~0
        flags = [e >= threshold for e in energies]
        transitions = sum(1 for a, b in zip(flags, flags[1:], strict=False) if a != b)
        trans_per_s = transitions / max(total_s, frame_s)

        tonal = z_cv < 0.08 and e_cv < 0.12
        if tonal and active_s <= 1.2 and active_ratio < 0.9:
            return AudioClassification(audio_class=AudioClass.VOICEMAIL, confidence=0.6)  # beep
        if active_ratio > 0.85 and e_cv < 0.35 and total_s >= 1.5:
            return AudioClassification(audio_class=AudioClass.HOLD_MUSIC, confidence=0.75)
        if active_s >= self.min_speech_s and trans_per_s >= 1.0 and active_ratio < 0.95:
            return AudioClassification(audio_class=AudioClass.HUMAN, confidence=0.6)
        if tonal:
            return AudioClassification(audio_class=AudioClass.HOLD_MUSIC, confidence=0.5)
        return AudioClassification(audio_class=AudioClass.UNKNOWN, confidence=0.3)

    def classify_text(self, text: str | None) -> AudioClassification | None:
        """Keyword spotting on a transcript; None when the text says nothing special."""
        if not text or not text.strip():
            return None
        if _MUSIC_MARK.search(text):
            return AudioClassification(audio_class=AudioClass.HOLD_MUSIC, confidence=0.9)
        if _VOICEMAIL.search(text):
            return AudioClassification(audio_class=AudioClass.VOICEMAIL, confidence=0.85)
        if _QUEUE.search(text):
            return AudioClassification(audio_class=AudioClass.QUEUE_ANNOUNCEMENT, confidence=0.85)
        if _IVR.search(text):
            return AudioClassification(audio_class=AudioClass.IVR_PROMPT, confidence=0.85)
        return None

    async def combine(self, audio: AudioClip | None, text: str | None) -> AudioClassification:
        by_text = self.classify_text(text)
        if by_text is not None:
            return by_text
        if audio is None:
            return AudioClassification(
                audio_class=AudioClass.HUMAN if (text or "").strip() else AudioClass.SILENCE,
                confidence=0.5,
            )
        by_audio = await self.classify(audio)
        if by_audio.audio_class in (AudioClass.SILENCE, AudioClass.UNKNOWN) and (text or "").strip():
            return AudioClassification(audio_class=AudioClass.HUMAN, confidence=0.5)
        return by_audio


def build_audio_classifier(c: Container) -> HeuristicAudioClassifier:
    return HeuristicAudioClassifier()
