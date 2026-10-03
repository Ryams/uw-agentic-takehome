"""Value-resolution analysis (D6): what is missing, how to get it, and what conflicts.

Pure function of (normalized values, field_resolution.json, registry): no tools are called
here (the orchestrator runs the fetch/lookup steps). Output drives the pipeline:
  * derivations applied (e.g. roof_classification from roof_material)
  * gaps: fields that must be resolved now, each with its ordered step chain
  * pending: conditional fields whose requirement depends on a still-missing field
  * deferred: bind-only fields (never chased)
  * conflicts: present-but-inconsistent values -> underwriter verification
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import uw_agent.config  # noqa: F401
from shared import registry
from uw_agent.protocols.expr import UNKNOWN, Expr, parse, parse_required_when

MAP_PATH = Path(__file__).resolve().parents[1] / "sim-harness" / "shared" / "field_resolution.json"
ACTIONS = {"fetch", "lookup", "derive", "assume", "ask_producer", "defer_to_bind", "post_bind_only"}


@lru_cache(maxsize=1)
def load_map() -> dict[str, Any]:
    return json.loads(MAP_PATH.read_text())


@dataclass
class Gap:
    field: str
    reason: str                                   # e.g. "required: always", "required when pool_type != None"
    steps: list[dict[str, Any]]                   # remaining step chain, in order
    pending_on: list[str] = field(default_factory=list)  # steps whose `when` is not yet decidable


@dataclass
class Analysis:
    values: dict[str, Any]
    derived: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)   # {field, waiting_on}
    deferred: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)


@lru_cache(maxsize=None)
def _required_when(name: str) -> Optional[Expr]:
    rw = registry.meta(name).get("requiredWhen")
    return parse_required_when(rw, set(registry.field_names())) if rw else None


def context_values(received_at: Optional[str] = None) -> dict[str, Any]:
    year = int(received_at[:4]) if received_at else 2026
    return {"current_year": year}


def steps_for(name: str, values: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The field's step chain with steps whose `when` is False removed.
    Returns (steps, fields the remaining `when`s are still waiting on)."""
    entry = load_map()["fields"].get(name)
    if entry is None:
        raise KeyError(f"no resolution entry for field {name!r}")
    steps, waiting = [], []
    for s in entry["on_missing"]:
        if "when" in s:
            v = parse(s["when"]).evaluate(values)
            if v is False:
                continue
            if v is UNKNOWN:
                waiting += sorted(parse(s["when"]).unknown_fields(values))
        steps.append(s)
    return steps, waiting


def gap_for(name: str, values: dict[str, Any], reason: str) -> Gap:
    steps, waiting = steps_for(name, values)
    return Gap(name, reason, steps, waiting)


def derive_value(step: dict[str, Any], values: dict[str, Any]) -> Optional[Any]:
    src = values.get(step["from"])
    return None if src is None else step["table"].get(src)


def analyze(values: dict[str, Any], context: Optional[dict[str, Any]] = None) -> Analysis:
    """Classify every registry field. `values` must come from `normalize_lead`."""
    ctx = context or context_values()
    vals = dict(values)
    a = Analysis(values=vals)

    # 1) derivations (pure table lookups)
    for name, src in registry.derived_map().items():
        if vals.get(name) is None and vals.get(src) is not None:
            step = next(s for s in load_map()["fields"][name]["on_missing"] if s["action"] == "derive")
            v = derive_value(step, vals)
            if v is not None:
                vals[name] = v
                a.derived.append({"field": name, "from": src, "value": v})

    # 2) gaps / pending / deferred
    for name in registry.field_names():
        if vals.get(name) is not None:
            continue
        meta = registry.meta(name)
        level = meta["required"]
        if level == "bind_only":
            a.deferred.append(name)
            continue
        if level == "no":
            continue
        reason = "required: always"
        if level == "conditional":
            rw = _required_when(name)
            if rw is not None:
                v = rw.evaluate(vals)
                if v is False:
                    continue
                if v is UNKNOWN:
                    a.pending.append({"field": name, "waiting_on": sorted(rw.unknown_fields(vals))})
                    continue
                reason = f"required when {meta['requiredWhen']}"
            else:
                reason = "required: conditional"
        src = registry.derived_from(name)
        if src and vals.get(src) is None:
            # can't derive until the source is known; the source is its own gap
            a.pending.append({"field": name, "waiting_on": [src]})
            continue
        a.gaps.append(gap_for(name, vals, reason))

    # 3) conflicts (present but inconsistent -> verify)
    scope = {**vals, **ctx}
    for rule in load_map().get("conflicts", []):
        e = parse(rule["when"])
        if e.evaluate(scope) is True:
            a.conflicts.append({"id": rule["id"], "message": rule["message"],
                                "fields": sorted(f for f in e.fields() if f in vals)})
    return a


def validate_map() -> list[str]:
    """Consistency checks for field_resolution.json (used by tests)."""
    errs: list[str] = []
    m = load_map()
    names = set(registry.field_names())
    for n in sorted(names - set(m["fields"])):
        errs.append(f"registry field {n} has no resolution entry")
    for n, entry in m["fields"].items():
        steps = entry.get("on_missing") or []
        if not steps:
            errs.append(f"{n}: empty on_missing")
        for s in steps:
            if s.get("action") not in ACTIONS:
                errs.append(f"{n}: bad action {s.get('action')!r}")
            if "when" in s:
                try:
                    parse(s["when"])
                except Exception as ex:  # noqa: BLE001
                    errs.append(f"{n}: bad `when`: {ex}")
            if s["action"] in ("assume", "lookup"):
                val = s.get("value", s.get("default"))
                if n in names and not registry.validate_value(n, val):
                    errs.append(f"{n}: {s['action']} value {val!r} invalid for field type")
            if s["action"] == "derive":
                src = s["from"]
                opts = registry.select_options(n) or []
                for k, v in s["table"].items():
                    if k not in (registry.select_options(src) or []) or v not in opts:
                        errs.append(f"{n}: derive table entry {k!r}->{v!r} invalid")
        if n not in names and not (entry.get("label") and entry.get("type")):
            errs.append(f"{n}: non-registry field needs label and type")
    for r in m.get("conflicts", []):
        try:
            e = parse(r["when"])
            for f in e.fields():
                if f not in names and f not in m.get("context_values", {}):
                    errs.append(f"conflict {r['id']}: unknown field {f}")
        except Exception as ex:  # noqa: BLE001
            errs.append(f"conflict {r['id']}: {ex}")
    return errs
