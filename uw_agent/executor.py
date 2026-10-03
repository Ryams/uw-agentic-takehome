"""Runs a field's resolution step chain (fetch / lookup / assume) against the tools and the LLM
interpreter. The only place that turns the resolution map's *plan* into *actions* (D12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from shared import registry
from uw_agent import resolution
from uw_agent.interpreter import interpret
from uw_agent.llm import StructuredLLM
from uw_agent.protocols.expr import UNKNOWN, parse
from uw_agent.tools.base import LookupResult, ToolResult


@dataclass
class ToolKit:
    fetch: Callable[[str, str], ToolResult]            # (lead_id, field)
    lookup: Callable[[str, str], LookupResult]         # (lead_id, topic)


@dataclass
class FieldResolution:
    field: str
    outcome: str        # resolved | assumed | ask_producer | deferred | post_bind | unresolved | pending
    value: Any = None
    log: list[dict[str, Any]] = field(default_factory=list)
    assumption: Optional[dict[str, Any]] = None
    ask_when: Optional[str] = None                      # set => conditional ask: only if this expression holds
    waiting_on: list[str] = field(default_factory=list)


def resolve_field(name: str, values: dict[str, Any], ctx_values: dict[str, Any], lead_id: str, tools: ToolKit,
                  llm: StructuredLLM) -> FieldResolution:
    scope = {**values, **ctx_values}
    steps, _ = resolution.steps_for(name, scope)
    out = FieldResolution(name, "unresolved")
    for i, s in enumerate(steps):
        a = s["action"]
        if a == "fetch":
            r = tools.fetch(lead_id, name)
            out.log.append({"field": name, "step": "fetch", "tool": r.tool, "status": r.status, "value": r.value,
                            "source": r.source, "detail": r.detail})
            if r.status == "found":
                out.outcome, out.value = "resolved", r.value
                return out
        elif a == "lookup":
            lr = tools.lookup(lead_id, s["topic"])
            iv = interpret(llm, name, lr)
            out.log.append({"field": name, "step": "lookup", "tool": lr.tool, "status": lr.status,
                            "interpretation": iv.status, "value": iv.value, "confidence": iv.confidence,
                            "rationale": iv.rationale, "evidence": lr.evidence, "sources": lr.sources,
                            "error": iv.error})
            if iv.status == "value" and iv.confidence != "low":
                out.outcome, out.value = "resolved", iv.value
                return out
            low = iv.status in ("unclear", "unavailable") or (iv.status == "value")   # low-confidence reading
            out.outcome, out.value = "assumed", s["default"]
            out.assumption = {"field": name, "value": s["default"], "why": s.get("rationale", "playbook default"),
                              "basis": "low-confidence reading" if iv.status == "value" else iv.status,
                              "low_confidence": low, "evidence": lr.evidence}
            return out
        elif a == "assume":
            w = s.get("when")
            if w:
                e = parse(w)
                v = e.evaluate(scope)
                if v is False:
                    continue
                if v is UNKNOWN:
                    later_ask = any(x["action"] == "ask_producer" for x in steps[i + 1:])
                    out.outcome = "ask_producer" if later_ask else "pending"
                    out.ask_when = f"not ({w})" if later_ask else None
                    out.waiting_on = sorted(e.unknown_fields(scope))
                    return out
            out.outcome, out.value = "assumed", s["value"]
            out.assumption = {"field": name, "value": s["value"], "why": s.get("rationale", "playbook default"),
                              "basis": "registry default", "low_confidence": False}
            return out
        elif a == "ask_producer":
            out.outcome = "ask_producer"
            return out
        elif a == "defer_to_bind":
            out.outcome = "deferred"
            return out
        elif a == "post_bind_only":
            out.outcome = "post_bind"
            return out
        # derive steps are applied by resolution.analyze()
    meta = registry.fields().get(name)
    out.outcome = "unresolved" if (meta is None or not meta["editableByProducer"]) else "ask_producer"
    return out
