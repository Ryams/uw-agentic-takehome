"""Evidence interpreter: turns Maps/Zillow evidence TEXT into a field value (LLM edge #1).

Deterministic code decides whether to call the model at all, validates what comes back against the
registry, and never lets the model choose the 'assume no' default (that is the resolution map's job).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel

import uw_agent.config  # noqa: F401
from shared import registry
from uw_agent import resolution
from uw_agent.llm import LLMError, StructuredLLM
from uw_agent.protocols import engine
from uw_agent.tools.base import LookupResult

PROMPT = (Path(__file__).parent / "prompts" / "interpreter.md").read_text()


class Interpretation(BaseModel):
    determination: Literal["value", "nothing_seen", "unclear"]
    value: str
    confidence: Literal["high", "medium", "low"]
    rationale: str


@dataclass
class InterpretedValue:
    field: str
    status: str                       # value | nothing_seen | unclear | unavailable
    value: Any = None
    confidence: str = "low"
    rationale: str = ""
    evidence: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    used_llm: bool = False
    error: Optional[str] = None


def playbook_notes_for(name: str) -> list[str]:
    """Sticky notes (D15) from the protocols that mention this field."""
    out = []
    for p in engine.load_protocols(only_runnable=False):
        for n in p.data.get("sticky_notes", []):
            if name in n.get("applies_to", []):
                out.append(n["text"])
    return out


def _field_description(name: str) -> str:
    entry = resolution.load_map()["fields"].get(name, {})
    meta = registry.fields().get(name) or entry
    label, typ = meta.get("label", name), meta.get("type", {})
    kind = typ.get("kind")
    if kind == "select":
        return f"{name} - {label} - select, allowed options: {typ['options']}"
    if kind == "toggle":
        return f"{name} - {label} - toggle (answer \"true\" or \"false\")"
    return f"{name} - {label} - {kind}"


def _coerce(name: str, raw: str) -> Optional[Any]:
    kind = (registry.fields().get(name) or resolution.load_map()["fields"][name])["type"]["kind"]
    if kind == "toggle":
        return {"true": True, "false": False}.get(raw.strip().lower())
    if kind == "select":
        opts = registry.select_options(name) or resolution.load_map()["fields"][name]["type"].get("options", [])
        return next((o for o in opts if str(o) == raw.strip()), None)
    return None


def interpret(llm: StructuredLLM, name: str, result: LookupResult) -> InterpretedValue:
    base = InterpretedValue(name, "nothing_seen", evidence=result.evidence, sources=result.sources)
    if result.status == "unavailable":
        base.status = "unavailable"
        return base
    if result.status == "not_found":          # nothing to read: no model call needed
        base.rationale = result.evidence[0] if result.evidence else "no evidence found"
        return base

    notes = playbook_notes_for(name)
    user = "\n".join([
        f"Field: {_field_description(name)}",
        "Playbook notes: " + (" | ".join(notes) if notes else "(none)"),
        f"Search status: {result.status}",
        "Evidence:", *[f"- {e}" for e in result.evidence],
        "Sources: " + ", ".join(result.sources),
    ])
    try:
        r = llm.structured(task="interpreter", system=PROMPT, user=user, schema=Interpretation, effort="low",
                           max_tokens=600)
    except LLMError as e:                      # includes refusals: degrade, never crash the lead
        base.status, base.error = "unclear", str(e)
        return base
    base.used_llm, base.rationale, base.confidence = True, r.rationale, r.confidence
    if r.determination == "value":
        v = _coerce(name, r.value)
        if v is None:                          # model returned something outside the allowed values
            base.status, base.error = "unclear", f"invalid value {r.value!r} for {name}"
            return base
        base.status, base.value = "value", v
        if result.status == "ambiguous":       # ambiguous imagery can never be a confident reading
            base.confidence = "low"
    else:
        base.status = r.determination
    return base
