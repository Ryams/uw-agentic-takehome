"""Deterministic protocol evaluator (D6): resolved values in, outcome or "blocked on X" out.

A protocol never fetches, asks or calls an LLM. Missing (None) values make a branch
UNKNOWN; the walker then stops and reports the blocking fields instead of guessing.
Results of several protocols are combined most-restrictive-first (JUDGEMENT_CALLS G-1);
a decline short-circuits the rest so a doomed lead is never asked more questions (D9).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from uw_agent.protocols.expr import UNKNOWN, Expr, parse

PROTOCOLS_DIR = Path(__file__).resolve().parents[2] / "sim-harness" / "protocols"
SEVERITY = ["decline", "escalate", "quote_with_conditions", "quote"]  # most -> least restrictive


@dataclass
class PathStep:
    node: str
    question: str
    inputs: dict[str, Any]
    branch: str  # branch label, "on_unexpected", or "BLOCKED"


@dataclass
class ConditionalBlocker:
    """A field we will need only if the lead turns out to take a particular path.

    `only_if` is the ordered list of branch conditions that must hold for the field to
    matter, e.g. [{"node": "inground_security", "branch": "Fenced ...", "when": 'pool_security == "Fenced"'}].
    Collected so ALL asks can go out in one message (D13); branches already ruled out are never explored.
    """
    field: str
    only_if: list[dict[str, str]]
    protocol: str = ""


@dataclass
class ProtocolResult:
    protocol: str
    status: str  # decided | blocked | not_applicable
    outcome: Optional[str] = None
    decision: Optional[str] = None
    conditions: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    blocked_on: list[str] = field(default_factory=list)
    conditional_blockers: list[ConditionalBlocker] = field(default_factory=list)
    path: list[PathStep] = field(default_factory=list)
    overlays: list[str] = field(default_factory=list)


@dataclass
class LeadEvaluation:
    status: str  # decided | blocked
    decision: Optional[str]  # final decision when decided; most restrictive so far when blocked
    conditions: list[str]
    recommendations: list[str]
    blocked_on: list[str]
    results: list[ProtocolResult]
    conditional_blockers: list[ConditionalBlocker] = field(default_factory=list)
    short_circuited_by: Optional[str] = None
    skipped: list[str] = field(default_factory=list)


class Protocol:
    def __init__(self, data: dict[str, Any], manifest_entry: Optional[dict[str, Any]] = None):
        self.data = data
        self.name: str = data["protocol"]
        self.entry = manifest_entry or {}
        self.outcomes: dict[str, dict[str, Any]] = data["outcomes"]
        self.applies_when: Expr = parse("true" if data.get("applies_when", "always") == "always" else data["applies_when"])
        self.trees: list[dict[str, Any]] = (
            [data["tree"]] if "tree" in data
            else [c["tree"] for c in data.get("components", []) if c.get("stage", "quote") == "quote"]
        )
        self.overlays = [(o, parse(o["when"])) for o in data.get("overlay_rules", [])]
        self._exprs: dict[int, Expr] = {}

    def expr(self, src: str) -> Expr:
        e = self._exprs.get(id(src))
        if e is None or e.source != src:
            e = self._exprs[id(src)] = parse(src)
        return e


def load_protocols(directory: Path = PROTOCOLS_DIR, only_runnable: bool = True) -> list[Protocol]:
    """Protocols from manifest.json, ordered by `order`. Runnable = enabled and stage == quote."""
    manifest = json.loads((directory / "manifest.json").read_text())["protocols"]
    out = []
    for e in sorted(manifest, key=lambda e: e["order"]):
        if only_runnable and not (e["enabled"] and e["stage"] == "quote"):
            continue
        out.append(Protocol(json.loads((directory / e["file"]).read_text()), e))
    return out


def _find_node(tree: dict[str, Any], node_id: str) -> dict[str, Any]:
    if tree["id"] == node_id:
        return tree
    for b in tree["branches"]:
        if "outcome" not in b["then"]:
            try:
                return _find_node(b["then"], node_id)
            except KeyError:
                pass
    raise KeyError(node_id)


def _apply_outcome(proto: Protocol, res: ProtocolResult, outcome_id: str) -> None:
    o = proto.outcomes[outcome_id]
    res.outcome, res.decision = outcome_id, o["decision"]
    if o.get("condition"):
        res.conditions.append(o["condition"])
    if o.get("recommendation"):
        res.recommendations.append(o["recommendation"])


def _walk(proto: Protocol, node: dict[str, Any], values: dict[str, Any], res: ProtocolResult) -> None:
    """Walk one tree. Sets res.outcome/decision, or res.blocked_on (and stops)."""
    while True:
        inputs = {f: values.get(f) for f in node["fields"]}
        chosen = None
        for br in node["branches"]:
            e = proto.expr(br["when"])
            v = e.evaluate(values)
            if v is True:
                chosen = br
                break
            if v is UNKNOWN:  # first branch that is not False decides: it might be true
                res.blocked_on = sorted(e.unknown_fields(values))
                res.path.append(PathStep(node["id"], node["question"], inputs, "BLOCKED"))
                return
        if chosen is None:
            res.path.append(PathStep(node["id"], node["question"], inputs, "on_unexpected"))
            _apply_outcome(proto, res, node["on_unexpected"]["outcome"])
            return
        res.path.append(PathStep(node["id"], node["question"], inputs, chosen["label"]))
        nxt = chosen["then"]
        if "outcome" in nxt:
            _apply_outcome(proto, res, nxt["outcome"])
            return
        node = nxt


def _explore(proto: Protocol, node: dict[str, Any], values: dict[str, Any], conds: list[dict[str, str]],
             out: list[ConditionalBlocker], record_here: bool) -> None:
    """Collect blockers on every path not already ruled out (D13).

    Mirrors the walker: the first branch that is not False decides. If it is True the path
    is determined (follow only it); if UNKNOWN, every non-False branch is a potential path.
    `record_here=False` is used for the node that is already blocked (its fields are
    unconditional blockers, reported separately).
    """
    first = None
    for br in node["branches"]:
        v = proto.expr(br["when"]).evaluate(values)
        if v is not False:
            first = (br, v)
            break
    if first is None:
        return
    if first[1] is True:
        nxt = first[0]["then"]
        if "outcome" not in nxt:
            _explore(proto, nxt, values, conds, out, True)
        return
    if record_here:
        for f in sorted(proto.expr(first[0]["when"]).unknown_fields(values)):
            out.append(ConditionalBlocker(f, list(conds), proto.name))
    for br in node["branches"]:
        e = proto.expr(br["when"])
        v = e.evaluate(values)
        if v is False or "outcome" in br["then"]:
            continue
        step = {"node": node["id"], "branch": br["label"], "when": br["when"]} if v is UNKNOWN else None
        _explore(proto, br["then"], values, conds + ([step] if step else []), out, True)


def _dedupe_conditional(items: list[ConditionalBlocker]) -> list[ConditionalBlocker]:
    seen, out = set(), []
    for c in items:
        key = (c.protocol, c.field, tuple(x["when"] for x in c.only_if))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def evaluate_protocol(proto: Protocol, values: dict[str, Any]) -> ProtocolResult:
    res = ProtocolResult(proto.name, "decided")
    gate = proto.applies_when.evaluate(values)
    if gate is False:
        res.status = "not_applicable"
        return res
    if gate is UNKNOWN:
        res.status = "blocked"
        res.blocked_on = sorted(proto.applies_when.unknown_fields(values))
        gate_cond = [{"node": "applies_when", "branch": "protocol applies", "when": proto.applies_when.source}]
        cond: list[ConditionalBlocker] = []
        for tree in proto.trees:
            _explore(proto, {"id": "applies_when", "branches": [{"label": "protocol applies", "when": "true", "then": tree}]},
                     values, [], cond, False)
        for _, e in proto.overlays:
            cond += [ConditionalBlocker(f, [], proto.name) for f in sorted(e.unknown_fields(values))]
        res.conditional_blockers = _dedupe_conditional([
            ConditionalBlocker(c.field, gate_cond + c.only_if, proto.name) for c in cond])
        return res

    blocked: set[str] = set()
    for tree in proto.trees:
        sub = ProtocolResult(proto.name, "decided")
        _walk(proto, tree, values, sub)
        res.path += sub.path
        if sub.blocked_on:
            blocked |= set(sub.blocked_on)
            blocked_node = _find_node(tree, sub.path[-1].node)
            _explore(proto, blocked_node, values, [], res.conditional_blockers, False)
        elif sub.decision:
            res.outcome, res.decision = sub.outcome, sub.decision
            res.conditions += sub.conditions
            res.recommendations += sub.recommendations

    for ov, e in proto.overlays:  # overlays may add conditions on top of the decided tree
        v = e.evaluate(values)
        if v is UNKNOWN:
            blocked |= e.unknown_fields(values)
        elif v is True:
            res.overlays.append(ov["id"])
            o = proto.outcomes[ov["outcome"]]
            if o.get("condition"):
                res.conditions.append(o["condition"])
            if o.get("recommendation"):
                res.recommendations.append(o["recommendation"])
            if res.decision and SEVERITY.index(o["decision"]) < SEVERITY.index(res.decision):
                res.decision = o["decision"]

    res.conditional_blockers = _dedupe_conditional(res.conditional_blockers)
    if blocked:
        res.status, res.blocked_on = "blocked", sorted(blocked)
        res.outcome = res.decision = None
        res.conditions, res.recommendations, res.overlays = [], [], []
    return res


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def evaluate_all(values: dict[str, Any], protocols: Optional[list[Protocol]] = None) -> LeadEvaluation:
    """Run all runnable protocols in manifest order and combine (G-1, D9)."""
    protocols = protocols if protocols is not None else load_protocols()
    results: list[ProtocolResult] = []
    skipped: list[str] = []
    short: Optional[str] = None
    for p in protocols:
        if short:
            skipped.append(p.name)
            continue
        r = evaluate_protocol(p, values)
        results.append(r)
        if r.decision == "decline":
            short = r.protocol

    decided = [r for r in results if r.decision]
    decision = min((r.decision for r in decided), key=SEVERITY.index) if decided else ("quote" if not any(
        r.status == "blocked" for r in results) else None)
    blocked_on = sorted({f for r in results if r.status == "blocked" for f in r.blocked_on})
    if short:
        # A decline stands regardless of what else is unknown; do not ask for more.
        return LeadEvaluation("decided", "decline", _dedupe([c for r in decided for c in r.conditions]), [],
                              [], results, [], short, skipped)
    status = "blocked" if blocked_on else "decided"
    conditional = [c for r in results if r.status == "blocked" for c in r.conditional_blockers
                   if c.field not in blocked_on]
    return LeadEvaluation(
        status, decision,
        _dedupe([c for r in decided for c in r.conditions]),
        _dedupe([c for r in decided for c in r.recommendations]),
        blocked_on, results, _dedupe_conditional(conditional), None, skipped,
    )
