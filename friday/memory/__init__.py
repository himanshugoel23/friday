"""Friday's memory layer (docs/MEMORY_ONE_PAGER.md): aliases learned from corrections, a one-line
record of each finished task, a single list of what Friday remembers, and relevance ranking."""

from __future__ import annotations

from friday.memory.rank import rank_facts
from friday.memory.service import MemoryItem, MemoryService

__all__ = ["MemoryItem", "MemoryService", "rank_facts"]
