"""Tool definitions and a small JSON-schema validator (no extra dependency)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Level(StrEnum):
    read = "read"  # L0: automatic
    reversible = "reversible"  # L1: automatic inside user limits, logged
    irreversible = "irreversible"  # L2: needs a fresh approval the user gave for this exact call


@dataclass(frozen=True)
class ToolDef:
    name: str  # "browser.read_page"
    version: int
    description: str
    level: Level
    input: dict[str, Any]
    output: dict[str, Any]
    tags: tuple[str, ...] = field(default=())
    # (argument name, values) -> the call is irreversible when args[name] is one of the values
    escalate: tuple[str, tuple[str, ...]] | None = None

    def level_for(self, args: dict[str, Any]) -> Level:
        if self.escalate and args.get(self.escalate[0]) in self.escalate[1]:
            return Level.irreversible
        return self.level

    @property
    def versioned(self) -> str:
        return f"{self.name}@{self.version}"

    def to_mcp(self) -> dict[str, Any]:
        """The shape an MCP ``tools/list`` entry has (plus our level)."""
        return {"name": self.versioned, "description": self.description,
                "inputSchema": self.input, "outputSchema": self.output,
                "annotations": {"level": self.level.value}}


_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,), "integer": (int,), "number": (int, float), "boolean": (bool,),
    "object": (dict,), "array": (list,),
}


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Return a list of problems (empty = valid). Supports type, enum, required, properties,
    additionalProperties=false, items, pattern, minLength/maxLength, minimum/maximum, maxItems."""
    errs: list[str] = []
    t = schema.get("type")
    if t:
        ok = isinstance(value, _TYPES[t]) and not (t in ("integer", "number") and isinstance(value, bool))
        if not ok:
            return [f"{path}: expected {t}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: not one of the allowed values")
    if isinstance(value, str):
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: too long")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: too short")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: wrong format")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: too large")
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: too small")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: too many items")
        if "items" in schema:
            for i, v in enumerate(value):
                errs += validate(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for r in schema.get("required", []):
            if r not in value:
                errs.append(f"{path}.{r}: required")
        if schema.get("additionalProperties") is False:
            errs += [f"{path}.{k}: not allowed" for k in value if k not in props]
        for k, sub in props.items():
            if k in value:
                errs += validate(value[k], sub, f"{path}.{k}")
    return errs
