# ruff: noqa: E501
"""The switchable output layer used by the gateways (planner, shopping, intents).

``StyleLayer.fit`` is what a gateway calls on text it OWNS (a template, not model free text): with the
switch off it returns the text untouched (one message, byte for byte); with it on it enforces the
budget by splitting and stripping header markers, and logs what it could not fix.
``StyleLayer.flag`` is for model free text: it logs violations and returns the text unchanged.
"""

from __future__ import annotations

from typing import Any

from friday.style import check as C


class StyleLayer:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.flagged: list[tuple[str, list[C.Violation]]] = []  # kept in memory for tests and the bench

    @classmethod
    def from_pipeline(cls, pipeline: Any) -> StyleLayer:
        return cls(bool(getattr(getattr(pipeline, "settings", None), "style_layer_enabled", False)))

    def fit(self, text: str, *, source: str = "template", kind: str = "text", has_buttons: bool = False) -> list[str]:
        """Messages to send for an owned template."""
        if not self.enabled or not text:
            return [text]
        parts = C.enforce(text, kind=kind)
        left = [v for p in parts for v in C.check(p, kind=kind, has_buttons=has_buttons)]
        if left:
            self.flagged.append((source, left))
            C.log_violations(source, left)
        return parts

    def flag(self, text: str, *, source: str = "model", kind: str = "text", user_text: str | None = None) -> str:
        """Model free text: check and log only. The text is returned exactly as given."""
        if self.enabled and text:
            found = C.check(text, kind=kind, user_text=user_text)
            if found:
                self.flagged.append((source, found))
                C.log_violations(source, found)
        return text
