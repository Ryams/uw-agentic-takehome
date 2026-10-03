"""Shapes returned by tools. Every tool is a thin client of a MOCK vendor service (D19): no real
external system is ever called, and the workflow never touches the ground truth behind the mocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    tool: str
    field: str
    status: str                      # found | not_found | unavailable
    value: Any = None
    source: str = ""
    detail: str = ""


@dataclass
class LookupResult:
    """Raw evidence from an imagery/listing search. It is TEXT: an interpreter turns it into a value."""
    tool: str
    topic: str
    status: str                      # found | not_found | ambiguous | unavailable
    evidence: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
