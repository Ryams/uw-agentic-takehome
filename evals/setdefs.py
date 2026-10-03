"""Eval set loading (D17): seeded generator sets with a recorded composition, and the fixed hand-built set."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import yaml

import uw_agent.config  # noqa: F401
from leadgen import generator
from uw_agent.config import ROOT

from evals import grader
from evals.model import EvalCase, case_from_generated

SETS_DIR = ROOT / "evals" / "sets"
SEEDED_JSON = SETS_DIR / "seeded.json"
FIXED_JSON = SETS_DIR / "fixed.json"
GEN_CONFIG = ROOT / "sim-harness" / "leadgen" / "generator_config.yaml"

# the seeded sets: name -> generator parameters (composition is recorded in seeded.json)
SEEDED_SPECS = {
    "s42-mixed": {"seed": 42, "count": 10, "difficulty": "mixed"},
    "s7-hard": {"seed": 7, "count": 10, "difficulty": "hard"},
    "s101-hard": {"seed": 101, "count": 10, "difficulty": "hard"},
    "s13-medium": {"seed": 13, "count": 10, "difficulty": "medium"},
}


def seeded_cases(spec: dict[str, Any]) -> list[EvalCase]:
    cfg = yaml.safe_load(GEN_CONFIG.read_text())
    return [case_from_generated(l) for l in generator.generate_queue(spec["seed"], spec["count"], spec["difficulty"], cfg)]


def composition(cases: list[EvalCase]) -> dict[str, Any]:
    """What a set contains, from the answer key: used to detect generator drift and to show the breakdown."""
    c: dict[str, Counter] = {k: Counter() for k in ("tier", "archetype", "outcome", "failure_mode", "expected_state")}
    for case in cases:
        o = grader.oracle(case)
        tags = grader.slice_tags(case, o)
        for dim in ("tier", "archetype", "outcome", "failure_mode"):
            c[dim].update(tags[dim])
        c["expected_state"][grader.expected(case, o)["state"]] += 1
    return {"n": len(cases), **{k: dict(sorted(v.items())) for k, v in c.items()}}


def load_recorded() -> dict[str, Any]:
    return json.loads(SEEDED_JSON.read_text()) if SEEDED_JSON.exists() else {"sets": {}}


def record_seeded() -> dict[str, Any]:
    out: dict[str, Any] = {
        "_comment": "Seeded eval sets: generator parameters and the composition they produced (D17). A run compares "
                    "the live composition to this and flags drift (generator or protocol change). Regenerate with "
                    "`python -m evals.runner --record-composition`.", "sets": {}}
    for name, spec in SEEDED_SPECS.items():
        out["sets"][name] = {**spec, "composition": composition(seeded_cases(spec))}
    SEEDED_JSON.write_text(json.dumps(out, indent=2) + "\n")
    return out


def composition_drift(name: str, cases: list[EvalCase]) -> list[str]:
    rec = load_recorded()["sets"].get(name, {}).get("composition")
    if rec is None:
        return [f"{name}: no recorded composition"]
    now = composition(cases)
    return [f"{name}: {k} changed {rec.get(k)} -> {now[k]}" for k in now if now[k] != rec.get(k)]


def load_fixed() -> list[EvalCase]:
    d = json.loads(FIXED_JSON.read_text())
    return [EvalCase(c["lead"], c["truth"], "fixed", [], [], c["tags"], c.get("conflict_injected", False),
                     c.get("vendor_overrides", []), c.get("reply_mode", "complete"), c["expect"], c["case_id"])
            for c in d["cases"]]
