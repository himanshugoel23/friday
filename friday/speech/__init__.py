"""Speech Understander: a small LLM between speech-to-text and the rest of Friday.

Founder spec (docs/SPEECH_UNDERSTANDING.md, decisions of 2026-10-26): like a voice-dictation product
(Wispr Flow style), the user's spoken words are cleaned before anything else reads them: fillers and
false starts go, self-corrections keep the final version ("kal nahi, parso" -> "parso"), obvious
mis-hearings are fixed using the user's own memory (people, places, shops), and the user's Hinglish is
kept. Fixes are applied SILENTLY (no confirmation of names or amounts); the approval cards that already
exist for calls and bookings show the final values.

Rules enforced in CODE (``ground.py``), not by the model: no invented number, day, time, or name; the
original text is always kept; OTP/PIN/card talk is never touched; any failure or timeout falls back to a
deterministic clean-up (``rules.py``) and then to the raw text, so a speech problem never blocks a user.

Applies to: the user's own voice notes and the user's own turns on a call with Friday. It is NEVER applied to
a vendor's speech on an outbound call (a silent correction there could change a quoted price).
"""

from friday.speech.schema import Repair, UnderstoodUtterance
from friday.speech.understander import SpeechUnderstander

__all__ = ["Repair", "SpeechUnderstander", "UnderstoodUtterance"]
