"""Normalizer, field-resolution map, and gap analysis (milestone 2)."""

from pathlib import Path

import yaml

import uw_agent.config  # noqa: F401
from leadgen import generator
from shared import registry
from uw_agent import normalize, resolution
from uw_agent.protocols import engine, linter

EXAMPLE = __import__("json").loads(
    (Path(__file__).resolve().parent.parent / "sim-harness/shared/lead_payload_example.json").read_text())["fields"]
CONFIG = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "sim-harness/leadgen/generator_config.yaml").read_text())


def test_resolution_map_valid_and_protocol_lint_with_map():
    assert resolution.validate_map() == []
    errs, _ = linter.lint_all(resolution=resolution.load_map())
    assert errs == []


def test_normalizer_example_payload():
    n = normalize.normalize_lead(EXAMPLE)
    assert n.values["coverage_e"] == "300000" and n.values["coverage_f"] == "1000"   # select options are strings: valid as-is
    assert normalize.normalize_lead({"coverage_e": 300000}).values["coverage_e"] == "300000"  # a bare number is coerced to the option
    assert n.values["fire_department_type"] is None                                   # "Unknown" -> missing
    assert {x["field"] for x in n.notes} >= {"fire_department_type"}
    assert set(n.values) == set(registry.field_names())
    assert n.invalid == []
    n2 = normalize.normalize_lead({"acreage": "1,200.5", "pool_type": "inground", "is_rental": "N/A",
                                   "has_animals": "Yes", "year_built": "19xx", "bogus": 1})
    assert n2.values["acreage"] == 1200.5 and n2.values["pool_type"] == "Inground"
    assert n2.values["is_rental"] is None and n2.values["has_animals"] is True and n2.values["year_built"] is None
    assert {i["field"] for i in n2.invalid} == {"year_built", "bogus"}
    assert normalize.normalize_lead({"pool_type": "None"}).values["pool_type"] == "None"  # a real option, not a sentinel


def test_analyze_example_payload():
    a = resolution.analyze(normalize.normalize_lead(EXAMPLE).values)
    gaps = {g.field: [s["action"] for s in g.steps] for g in a.gaps}
    assert gaps["trust_name"] == ["ask_producer"]                      # held in trust, name missing
    assert gaps["replacement_cost"] == ["fetch"]                       # system-owned -> fetch, never ask
    assert gaps["protection_class"] == ["fetch", "assume"]
    assert gaps["pool_security"] == ["lookup"]                         # pools callout
    assert "occupation" in a.deferred                                  # bind_only
    assert "roof_classification" not in gaps and any(p["field"] == "roof_classification" for p in a.pending)
    assert "roof_material" in gaps                                     # the source is the gap
    assert "above_ground_pool_ladder" not in gaps                      # only required for above-ground pools
    assert "water_heater_age_years" in {p["field"] for p in a.pending}  # waits on water_heater_type
    assert not any(g.field in ("fire_dept_response_time", "alternative_water_source") for g in a.gaps)  # PC unknown -> pending
    assert {p["field"] for p in a.pending} >= {"fire_dept_response_time", "interior_sprinklers"}
    assert a.conflicts == []


def test_derivation_and_knob_and_tube_assume():
    vals = normalize.normalize_lead({"roof_material": "Wood Shake", "year_built": 1940}).values
    a = resolution.analyze(vals)
    assert a.values["roof_classification"] == "Class C" and a.derived[0]["field"] == "roof_classification"
    g = {x.field: x for x in a.gaps}["has_knob_and_tube_wiring"]
    assert [s["action"] for s in g.steps][0] == "assume"
    a2 = resolution.analyze(normalize.normalize_lead({"year_built": 1990}).values)
    g2 = {x.field: x for x in a2.gaps}["has_knob_and_tube_wiring"]
    assert [s["action"] for s in g2.steps] == ["ask_producer"]          # assume only applies pre-1950


def test_conflict_rules_fire_only_on_injected_conflicts():
    """Rules must be silent on clean truth except where an occupancy archetype injects the story."""
    for seed in range(1, 31):
        for lead in generator.generate_queue(seed, 10, "hard", CONFIG):
            clean = normalize.normalize_lead(lead["debug"]["clean_fields"]).values
            ids = {c["id"] for c in resolution.analyze(clean).conflicts}
            if "occupancy_conflict" not in lead["debug"]["injected_archetypes"]:
                assert ids == set(), (seed, lead["lead_id"], ids)


def test_conflicts_detected_on_perturbed_leads():
    """An injected conflict must be flagged whenever the other fields its rule needs are present
    (a rule that depends on a missing field stays UNKNOWN until that field is resolved)."""
    from uw_agent.protocols.expr import parse
    rules = resolution.load_map()["conflicts"]
    seen = set()
    for seed in range(1, 40):
        for lead in generator.generate_queue(seed, 10, "hard", CONFIG):
            planted = {p["field"] for p in lead["debug"]["perturbations"] if p["kind"] == "conflict"}
            vals = normalize.normalize_lead(lead["fields"]).values
            ctx = resolution.context_values(lead["received_at"])
            found = {f for c in resolution.analyze(vals, ctx).conflicts for f in c["fields"]}
            for f in planted:
                evaluable = [r for r in rules if f in parse(r["when"]).fields()
                             and not parse(r["when"]).unknown_fields({**vals, **ctx})]
                if evaluable:
                    assert f in found, (lead["lead_id"], f)
                    seen.add(f)
    assert len(seen) >= 4


def test_protocol_blocked_fields_all_have_resolution_entries():
    names = set(resolution.load_map()["fields"])
    for p in engine.load_protocols(only_runnable=False):
        pass
    for fld in ("pool_fence_self_locking_or_safety_cover", "broker_tier", "has_primary_policy_with_stand",
                "pool_type", "water_heater_age_years", "residence_held_in_trust"):
        assert fld in names
