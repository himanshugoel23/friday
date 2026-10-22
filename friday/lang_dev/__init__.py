"""Devanagari input for the chatbot (docs/VOICE_NOTES_AND_DEVANAGARI.md).

``normalise_text`` turns Hindi typed (or transcribed) in Devanagari into the Roman Hinglish
spellings the existing rule banks already understand; ``detect_script`` tells the reply which
script to mirror. Nothing here sends or stores anything, and it is only wired in behind
``FRIDAY_DEVANAGARI_INPUT`` (default off).
"""

from friday.lang_dev.normalise import Normalised, detect_script, normalise_text
from friday.lang_dev.numbers import parse_number_phrase

__all__ = ["Normalised", "detect_script", "normalise_text", "parse_number_phrase"]
