"""Grader (D17/D18): scores a finished run of one lead against ground truth.

Expected result = the SAME protocol engine run on the lead's clean truth, so protocol logic is held constant and
the grade isolates resolution (fetch / lookup / assume / derive), asking, escalation and email behaviour.
Fixed-set cases carry a frozen hand-written expectation that is cross-checked against this oracle.

Per-lead records hold raw counts; `aggregate` turns a group of records into ratios (micro-averaged where a
denominator matters, e.g. asks)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from shared import registry
from uw_agent import orchestrator as orch, resolution
from uw_agent.db import Database
from uw_agent.normalize import normalize_lead
from uw_agent.protocols import engine

from evals.model import EvalCase

SEVERITY_ESCALATE = ("decline", "escalate")


@dataclass
class Oracle:
    decision: Optional[str]
    conditions: list[str]
    outcomes: dict[str, str]                    # protocol -> outcome (only protocols that decided)
    overlays: list[str]                         # "<protocol>:<overlay outcome>" that fired on top of the tree
    state: str                                  # expected final state
    conflict: bool                              # truth itself is internally inconsistent, or a conflict was injected
    relevant: set[str]                          # fields a correct run may need to know
    values: dict[str, Any]


def oracle(case: EvalCase, protocols: Optional[list[engine.Protocol]] = None) -> Oracle:
    v = normalize_lead(case.truth).values
    a = resolution.analyze(v, resolution.context_values(case.lead.get("received_at")))
    ev = engine.evaluate_all(a.values, protocols)
    outcomes = {r.protocol: r.outcome for r in ev.results if r.status == "decided" and r.outcome}
    ov_outcome = {(p.name, o["id"]): o["outcome"] for p in (protocols or engine.load_protocols()) for o in p.data.get("overlay_rules", [])}
    overlays = sorted({f"{r.protocol}:{ov_outcome.get((r.protocol, x), x)}" for r in ev.results for x in r.overlays})
    rel: set[str] = set()
    for r in ev.results:
        for s in r.path:
            rel |= set(s.inputs)
    fmap = resolution.load_map()["fields"]
    for f in list(rel):                         # a derived field is "known" via its inputs
        for step in fmap.get(f, {}).get("on_missing", []):
            if step["action"] == "derive":
                rel |= set(step["from"] if isinstance(step["from"], list) else [step["from"]])
    for name in registry.field_names():         # fields the registry requires for this particular lead
        meta = registry.meta(name)
        if meta["required"] == "always":
            rel.add(name)
        elif meta["required"] == "conditional":
            rw = resolution._required_when(name)
            if rw is not None and rw.evaluate(a.values) is True:
                rel.add(name)
    # archetypes such as occupancy_conflict are inconsistent in the clean truth too; injected conflicts are raw-only
    conflict = case.conflict_injected or bool(a.conflicts)
    state = orch.NEEDS_UW if (conflict or ev.decision in SEVERITY_ESCALATE) else orch.READY
    return Oracle(ev.decision, list(ev.conditions), outcomes, overlays, state, conflict, rel, a.values)


def expected(case: EvalCase, o: Oracle) -> dict[str, Any]:
    """Frozen expectation when the case has one, else the oracle's."""
    if case.expect:
        return {"decision": case.expect["decision"], "conditions": case.expect["conditions"],
                "outcomes": case.expect["outcomes"], "state": case.expect["final_state"]}
    return {"decision": o.decision, "conditions": o.conditions, "outcomes": o.outcomes, "state": o.state}


def expectation_stale(case: EvalCase, o: Oracle) -> Optional[str]:
    """Fixed sets only: the frozen expectation disagrees with the engine run on the case's truth."""
    if not case.expect:
        return None
    e = case.expect
    if (e["decision"], sorted(e["conditions"]), e["outcomes"]) != (o.decision, sorted(o.conditions), o.outcomes):
        return f"frozen {e['decision']}/{e['outcomes']} vs engine {o.decision}/{o.outcomes}"
    return None


# --- slices ------------------------------------------------------------------------------------------------

def slice_tags(case: EvalCase, o: Oracle) -> dict[str, list[str]]:
    """Slice dimension -> values for this case (a lead can sit in several slices of a dimension)."""
    raw = case.lead["fields"]
    t: dict[str, list[str]] = {
        "protocol": sorted(o.outcomes), "outcome": [f"{p}:{x}" for p, x in sorted(o.outcomes.items())],
        "archetype": list(case.archetypes) or (["none"] if case.tier != "fixed" else []),
        "tier": [case.tier], "failure_mode": [],
    }
    fm = t["failure_mode"]
    kinds = {p["kind"] for p in case.perturbations}
    if o.conflict:
        fm.append("conflict")
    if kinds & {"missing_required", "missing_required_conditional"}:
        fm.append("missing_producer_field")
    if "missing_system_owned" in kinds:
        fm.append("missing_system_owned_field")
    if "missing_bind_only" in kinds:
        fm.append("bind_only_missing")
    if "archetype_null" in kinds:
        fm.append("hidden_hazard_field")
    fmap = resolution.load_map()["fields"]
    missing = [f for f, v in raw.items() if (v is None or v == "Unknown") and case.truth.get(f) is not None]
    for f in missing:
        steps = [s["action"] for s in fmap.get(f, {}).get("on_missing", [])]
        if "derive" in steps and "derived_value" not in fm:
            fm.append("derived_value")
        if "lookup" in steps and "lookup_field" not in fm:
            fm.append("lookup_field")
    if "bind_only" in {registry.meta(f)["required"] for f in missing if f in registry.field_names()} and "bind_only_missing" not in fm:
        fm.append("bind_only_missing")
    if not fm:
        fm.append("clean")
    if case.expect is not None:                  # fixed case: slice by what the case is ABOUT, not every protocol that passed
        focus = case.expect.get("focus", {})
        t["protocol"], t["outcome"] = sorted(focus), [f"{p}:{x}" for p, x in sorted(focus.items())]
    for dim, vals in case.tags.items():          # explicit tags (fixed sets) add to / extend the derived ones
        t[dim] = list(dict.fromkeys(t.get(dim, []) + vals))
    t["failure_mode"] = [x for x in t["failure_mode"] if not (x == "clean" and len(t["failure_mode"]) > 1)]
    return t


# --- per-lead grading --------------------------------------------------------------------------------------

def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(float(a) - float(b)) < 1e-9
    return a == b


def grade_lead(case: EvalCase, o: Oracle, db: Database, run_id: str, rounds_to_close: Optional[int],
               out_emails_after_round1: int) -> dict[str, Any]:
    exp = expected(case, o)
    d = db.latest_decision(run_id, case.lead_id)
    rep = d["report"]
    state = d["state"]
    reasons = {r["type"] for r in rep.get("reasons", [])}
    truth_v = normalize_lead(case.truth).values
    raw_v = normalize_lead(case.lead["fields"]).values
    answers = db.answers(run_id, case.lead_id)

    rec: dict[str, Any] = {"lead_id": case.lead_id, "final_state": state, "final_decision": d["decision"],
                           "expected_state": exp["state"], "expected_decision": exp["decision"]}
    rec["state_correct"] = int(state == exp["state"])
    unsafe_expected = exp["state"] != orch.READY
    rec["unsafe_quote"] = int(state == orch.READY and (unsafe_expected or d["decision"] != exp["decision"]
                                                       or set(rep["conditions"]) != set(exp["conditions"])))
    rec["over_escalation"] = int(state == orch.NEEDS_UW and exp["state"] == orch.READY)
    rec["under_escalation"] = int(exp["state"] == orch.NEEDS_UW and state != orch.NEEDS_UW)
    # decision correctness: graded only when a final decision is expected to be reachable (not conflict/stuck cases)
    gradable = not o.conflict and exp["state"] == o.state and exp["state"] != orch.AWAITING
    rec["decision_correct"] = (int(d["decision"] == exp["decision"] and set(rep["conditions"]) == set(exp["conditions"]))
                               if gradable else None)
    conflicts = any(r["type"] == "conflict" for r in rep.get("reasons", []))
    rec["conflict_detected"] = int(conflicts) if o.conflict else None
    rec["false_conflict"] = int(conflicts) if not o.conflict else None
    rec["internal_error"] = int("internal_error" in reasons)

    # asks across all emails sent for this lead
    outs = [e for e in db.emails(run_id, case.lead_id, "out") if e["status"] == "sent"]
    uncond, cond, asked_all = [], [], []
    repeat = 0
    seen_answered: set[str] = set()
    for i, e in enumerate(outs):
        asks = json.loads(e["plan_json"])["asks"]
        for a in asks:
            asked_all.append(a["field"])
            (uncond if a["group_id"] == 0 else cond).append(a["field"])
            if a["field"] in seen_answered:
                repeat += 1
        seen_answered |= {f for f, src in _answered_by_email(db, run_id, case.lead_id, e["id"])}
    rec["emails_sent"] = len(outs)
    rec["email_after_round1"] = out_emails_after_round1
    rec["asked_uncond"] = len(uncond)
    rec["unneeded_asks"] = sum(1 for f in uncond if f not in o.relevant)
    rec["cond_asks"] = len(cond)
    cond_na = {f for f, src in db_answers_na(db, run_id, case.lead_id)}
    rec["cond_asks_na"] = sum(1 for f in cond if f in cond_na)
    rec["repeat_asks"] = repeat
    fmap = resolution.load_map()["fields"]
    rec["bind_only_chased"] = int(any(
        (f in registry.field_names() and registry.meta(f)["required"] == "bind_only")
        or any(s["action"] == "post_bind_only" for s in fmap.get(f, {}).get("on_missing", [])) for f in asked_all))

    # blocker recall: fields the truth path needs, missing in the raw lead, that no tool/assumption supplied
    auto = _auto_resolved(rep)
    needed = [f for f in o.relevant if raw_v.get(f) is None and truth_v.get(f) is not None
              and f not in auto and f not in _derived_fields(rep) and _askable(f)]
    if "decline" in reasons:                     # a decline legitimately stops the asking (D11)
        needed = []
    rec["needed_fields"] = len(needed)
    rec["needed_asked"] = sum(1 for f in needed if f in asked_all or f in answers)

    # auto-resolved value accuracy by method
    for how, items in auto_by_method(rep).items():
        ok = sum(1 for f, v in items if _same(v, truth_v.get(f)))
        rec[f"{how}_n"], rec[f"{how}_ok"] = len(items), ok
    rec["rounds_to_close"] = rounds_to_close
    calls = db.query("SELECT COUNT(*) AS n, COALESCE(SUM(input_tokens),0) AS i, COALESCE(SUM(output_tokens),0) AS o "
                   "FROM llm_calls WHERE run_id=? AND lead_id=?", (run_id, case.lead_id))[0]
    rec["llm_calls"], rec["input_tokens"], rec["output_tokens"] = calls["n"], calls["i"], calls["o"]
    return rec


def _askable(name: str) -> bool:
    """The producer can supply it (registry says editable, or a playbook-only field asked of the producer, D3).
    System-owned fields no tool could fetch are escalations, not asks: they do not count against recall."""
    return registry.meta(name)["editableByProducer"] if name in registry.field_names() else True


def _answered_by_email(db: Database, run_id: str, lead_id: str, out_email_id: int):
    rows = db.query("SELECT a.field, a.source FROM answers a JOIN emails e ON e.id = a.email_id "
                  "WHERE a.run_id=? AND a.lead_id=? AND e.in_reply_to=? AND a.source='reply'",
                  (run_id, lead_id, out_email_id))
    return [(r["field"], r["source"]) for r in rows]


def db_answers_na(db: Database, run_id: str, lead_id: str):
    return [(r["field"], r["source"]) for r in db.query(
        "SELECT field, source FROM answers WHERE run_id=? AND lead_id=? AND source='reply_na'", (run_id, lead_id))]


def auto_by_method(rep: dict[str, Any]) -> dict[str, list[tuple[str, Any]]]:
    out: dict[str, list[tuple[str, Any]]] = {"fetch": [], "lookup": [], "assume": [], "derive": []}
    got = {x["field"] for x in rep.get("lookups", []) if x.get("interpretation") == "value" and x.get("confidence") != "low"}
    for x in rep.get("fetched", []):
        out["fetch"].append((x["field"], x["value"]))
    for x in rep.get("lookups", []):
        if x["field"] in got and x.get("interpretation") == "value":
            out["lookup"].append((x["field"], x["value"]))
    looked = {f for f, _ in out["lookup"]}
    for x in rep.get("assumptions", []):
        if x["field"] not in looked:
            out["assume"].append((x["field"], x["value"]))
    for x in rep.get("derived", []):
        out["derive"].append((x["field"], x["value"]))
    return out


def _auto_resolved(rep: dict[str, Any]) -> set[str]:
    return {f for items in auto_by_method(rep).values() for f, _ in items}


def _derived_fields(rep: dict[str, Any]) -> set[str]:
    return {x["field"] for x in rep.get("derived", [])}


# --- aggregation -------------------------------------------------------------------------------------------

def _mean(recs: list[dict[str, Any]], k: str) -> Optional[float]:
    v = [r[k] for r in recs if r.get(k) is not None]
    return sum(v) / len(v) if v else None


def _ratio(recs: list[dict[str, Any]], num: str, den: str) -> Optional[float]:
    d = sum(r.get(den) or 0 for r in recs)
    return sum(r.get(num) or 0 for r in recs) / d if d else None


def aggregate(recs: list[dict[str, Any]]) -> dict[str, Optional[float]]:
    """Metric columns for a group of per-lead records. Higher is better unless the name says otherwise."""
    m: dict[str, Optional[float]] = {
        "state_correct": _mean(recs, "state_correct"),
        "decision_correct": _mean(recs, "decision_correct"),
        "unsafe_quote_rate": _mean(recs, "unsafe_quote"),            # lower is better: wrong auto-quote
        "over_escalation_rate": _mean(recs, "over_escalation"),      # lower is better
        "under_escalation_rate": _mean(recs, "under_escalation"),    # lower is better
        "conflict_recall": _mean(recs, "conflict_detected"),
        "false_conflict_rate": _mean(recs, "false_conflict"),        # lower is better
        "blocker_recall": _ratio(recs, "needed_asked", "needed_fields"),
        "unneeded_ask_rate": _ratio(recs, "unneeded_asks", "asked_uncond"),   # lower is better
        "cond_ask_na_rate": _ratio(recs, "cond_asks_na", "cond_asks"),        # cost of the one-email design
        "repeat_ask_rate": _ratio(recs, "repeat_asks", "emails_sent"),        # lower is better (re-asking answered qs)
        "bind_only_chased_rate": _mean(recs, "bind_only_chased"),             # lower is better
        "one_email_first_round": _mean([{"v": int(r["email_after_round1"] <= 1)} for r in recs], "v"),
        "emails_per_lead": _mean(recs, "emails_sent"),
        "rounds_to_close": _mean(recs, "rounds_to_close"),
        "fetch_accuracy": _ratio(recs, "fetch_ok", "fetch_n"),
        "lookup_accuracy": _ratio(recs, "lookup_ok", "lookup_n"),
        "assume_accuracy": _ratio(recs, "assume_ok", "assume_n"),
        "derive_accuracy": _ratio(recs, "derive_ok", "derive_n"),
        "internal_error_rate": _mean(recs, "internal_error"),
        "llm_calls_per_lead": _mean(recs, "llm_calls"),
        "tokens_per_lead": (_mean(recs, "input_tokens") or 0) + (_mean(recs, "output_tokens") or 0),
    }
    return {k: (round(v, 4) if v is not None else None) for k, v in m.items()}
