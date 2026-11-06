# ruff: noqa: E501
"""Landing page variants for the A/B test (docs/ROBIN_LANDING_BRIEF.md). Each variant is a module ``s1``, ``s2``, ``s3`` ... with a
``PAGE`` string. The page must post the join form to ``join`` with the JSON field ``v`` set to the literal token
``{{VARIANT}}`` (the router replaces it with the variant id) and keep: name + WhatsApp number only, the honest footer line,
the privacy link, the news links (if used), and the form field ids ``name``, ``phone``, ``website`` (honeypot)."""

from __future__ import annotations

import importlib
import re

_ID = re.compile(r"^[a-z][a-z0-9]?$")


def available() -> list[str]:
    out = []
    for i in ("s1", "s2", "s3"):
        try:
            importlib.import_module(f"friday.robinwaitlist.variants.{i}")
            out.append(i)
        except ModuleNotFoundError:
            continue
    return out


def load(v: str | None) -> str | None:
    """The page HTML for variant ``v`` with the variant token filled in, or None if there is no such variant."""
    if not v or not _ID.match(v):
        return None
    try:
        mod = importlib.import_module(f"friday.robinwaitlist.variants.{v}")
    except ModuleNotFoundError:
        return None
    return str(mod.PAGE).replace("{{VARIANT}}", v)
