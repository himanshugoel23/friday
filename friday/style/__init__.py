# ruff: noqa: E501
"""Instinct-style reply layer (docs/STYLE_GUIDE.md). Off unless ``FRIDAY_STYLE_LAYER_ENABLED``.
All wording is PENDING founder approval (friday/style/wording.py)."""

from friday.style import builders, check
from friday.style.layer import StyleLayer
from friday.style.prompt import STYLE_BLOCK, style_suffix

__all__ = ["STYLE_BLOCK", "StyleLayer", "builders", "check", "style_suffix"]
