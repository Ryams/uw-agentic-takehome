"""Protocol engine + expression language + linter (D6, D9)."""

import itertools
import json

import pytest

import uw_agent.config  # noqa: F401
from shared import registry
from uw_agent.protocols import engine, linter
from uw_agent.protocols.expr import UNKNOWN, parse, parse_required_when

PROTOS = {p.name: p for p in engine.load_protocols(only_runnable=False)}


def run(name, **values):
    return engine.evaluate_protocol(PROTOS[name], values)


# --- expressions -------------------------------------------------------------

def test_kleene_logic():
    e = parse('a == "x" or b == true')
    assert e.evaluate({"a": "x"}) is True
    assert e.evaluate({"a": "y"}) is UNKNOWN
    assert e.evaluate({"a": "y", "b": False}) is False
    assert parse('a == 1 and b == 2').evaluate({"a": 2}) is False  # False beats UNKNOWN
    assert parse("not a == 1").evaluate({}) is UNKNOWN
    assert parse('a in (9, 10)').evaluate({"a": "9"}) is True       # select option "9" vs literal 9
    assert parse("a > 30").evaluate({"a": 31}) is True and parse("a > 30").evaluate({"a": 30}) is False


def test_all_registry_required_when_parse():
    names = set(registry.field_names())
    for k, m in registry.fields().items():
        if "requiredWhen" in m:
            e = parse_required_when(m["requiredWhen"], names)
            assert e.fields() & names, k
    assert parse_required_when("pool_type = Above Ground", names).evaluate({"pool_type": "Above Ground"}) is True


# --- linter ------------------------------------------------------------------

def test_protocols_lint_clean():
    errs, _ = linter.lint_all()
    assert errs == []


def test_linter_catches_problems():
    bad = json.loads((engine.PROTOCOLS_DIR / "water_heaters.json").read_text())
    bad["tree"]["branches"][0]["when"] = 'water_heater_type == "Gas"'          # not an option
    bad["tree"]["branches"][1]["then"]["then"] = {"outcome": "NOPE"} if False else bad["tree"]["branches"][1]["then"]
    bad["tree"]["branches"][0]["then"] = {"outcome": "MISSING_OUTCOME"}
    bad["tree"]["fields"] = ["not_a_field"]
    errs, _ = linter.lint_protocol(bad)
    text = "\n".join(errs)
    assert "not one of" in text and "MISSING_OUTCOME" in text and "not_a_field" in text


# --- pools --------------------------------------------------------------------

def test_pools():
    assert run("swimming_pools", pool_type="None").status == "not_applicable"
    assert run("swimming_pools", pool_type=None).blocked_on == ["pool_type"]
    r = run("swimming_pools", pool_type="Inground", pool_security="Unfenced", is_gated_community=True,
            pool_has_diving_board_or_slide=False)
    assert r.decision == "quote" and r.recommendations and not r.conditions
    r = run("swimming_pools", pool_type="Inground", pool_security="Unfenced", is_gated_community=False,
            pool_has_diving_board_or_slide=False)
    assert r.outcome == "REQUIRE_COVER" and r.decision == "quote_with_conditions"
    r = run("swimming_pools", pool_type="Inground", pool_security="Fenced", pool_has_diving_board_or_slide=False)
    assert r.status == "blocked" and r.blocked_on == ["pool_fence_self_locking_or_safety_cover"]
    r = run("swimming_pools", pool_type="Inground", pool_security="Fenced", pool_fence_self_locking_or_safety_cover=True,
            pool_has_diving_board_or_slide=True)
    assert r.decision == "quote_with_conditions" and r.overlays == ["slide_or_diving_board"]  # overlay on a plain quote
    r = run("swimming_pools", pool_type="Above Ground", above_ground_pool_ladder=False, pool_has_diving_board_or_slide=False)
    assert r.outcome == "REQUIRE_LADDER"
    # tree decided, but overlay field missing -> blocked on the overlay field (consolidated asks)
    r = run("swimming_pools", pool_type="Above Ground", above_ground_pool_ladder=True)
    assert r.status == "blocked" and r.blocked_on == ["pool_has_diving_board_or_slide"]
    # inground pool with pool_security 'None' is a data conflict -> UW review
    r = run("swimming_pools", pool_type="Inground", pool_security="None", pool_has_diving_board_or_slide=False)
    assert r.outcome == "UW_REVIEW"


# --- plumbing -------------------------------------------------------------------

def test_general_plumbing():
    base = dict(plumbing_age_years=40)
    assert run("general_plumbing", **base, broker_tier="Tier 1").outcome == "REQUIRE_PLUMBING_INSPECTION"
    assert run("general_plumbing", **base, broker_tier="Tier 2", has_primary_policy_with_stand=True).decision == "quote_with_conditions"
    assert run("general_plumbing", **base, broker_tier="Tier 3", has_primary_policy_with_stand=False).decision == "decline"
    r = run("general_plumbing", **base, broker_tier="Tier 2")
    assert r.status == "blocked" and r.blocked_on == ["has_primary_policy_with_stand"]
    assert run("general_plumbing", **base).blocked_on == ["broker_tier", "has_primary_policy_with_stand"]
    assert run("general_plumbing", plumbing_age_years=30).decision == "quote"   # boundary: 30 is newer (GP-2)
    assert run("general_plumbing", plumbing_age_years=31, broker_tier="Tier 1").decision == "quote_with_conditions"


def test_water_heaters():
    assert run("water_heaters", water_heater_type="Tankless").decision == "quote"
    assert run("water_heaters", water_heater_type="Tank", water_heater_age_years=10).decision == "quote"
    assert run("water_heaters", water_heater_type="Tank", water_heater_age_years=11,
               water_heater_location="Unfinished Space").outcome == "REQUIRE_PLUMBING_INSPECTION"
    r = run("water_heaters", water_heater_type="Tank", water_heater_age_years=15,
            water_heater_location="In or Above Finished Space", broker_tier="Tier 2", has_primary_policy_with_stand=False)
    assert r.decision == "decline"
    r = run("water_heaters", water_heater_type="Tank")
    assert r.blocked_on == ["water_heater_age_years"]


def test_trusts_quote_stage_only():
    assert run("trusts_and_llcs_quote", residence_held_in_trust=False).status == "not_applicable"
    r = run("trusts_and_llcs_quote", residence_held_in_trust=True)
    assert r.decision == "quote_with_conditions" and "30 days of bind" in r.conditions[0]
    assert run("trusts_and_llcs_quote").blocked_on == ["residence_held_in_trust"]
    runnable = {p.name for p in engine.load_protocols()}
    assert "trusts_and_llcs_post_bind" not in runnable and "trusts_and_llcs_quote" in runnable


# --- combining ---------------------------------------------------------------------

LEAD = dict(
    plumbing_age_years=20, water_heater_type="Tankless", residence_held_in_trust=False, pool_type="None",
    broker_tier="Tier 2", has_primary_policy_with_stand=False,
)


def test_combine_most_restrictive_and_dedupe():
    ev = engine.evaluate_all({**LEAD, "plumbing_age_years": 40, "broker_tier": "Tier 1",
                              "water_heater_type": "Tank", "water_heater_age_years": 12,
                              "water_heater_location": "Unfinished Space"})
    assert ev.status == "decided" and ev.decision == "quote_with_conditions"
    assert ev.conditions == ["require plumbing inspection within first term"]  # one condition, not two (WH-3)


def test_decline_short_circuits_and_ignores_unknowns():
    ev = engine.evaluate_all({"plumbing_age_years": 40, "broker_tier": "Tier 3", "has_primary_policy_with_stand": False})
    assert ev.decision == "decline" and ev.status == "decided" and ev.blocked_on == []
    assert ev.short_circuited_by == "general_plumbing" and "swimming_pools" in ev.skipped


def test_blocked_unions_asks_across_protocols():
    ev = engine.evaluate_all({"plumbing_age_years": 20, "water_heater_type": "Tank", "pool_type": "Above Ground"})
    assert ev.status == "blocked"
    assert set(ev.blocked_on) >= {"water_heater_age_years", "residence_held_in_trust", "above_ground_pool_ladder"}


def test_all_clear_quotes():
    ev = engine.evaluate_all(LEAD)
    assert ev.status == "decided" and ev.decision == "quote" and not ev.conditions


# --- every defined outcome is reachable (leaf coverage) ------------------------------------

def _candidates(field, literals):
    if field not in registry.field_names():
        return [True, False]
    kind = registry.meta(field)["type"]["kind"]
    if kind == "select":
        return list(registry.select_options(field))
    if kind == "toggle":
        return [True, False]
    nums = {0}
    for v in literals:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            nums |= {v - 1, v, v + 1}
    return sorted(nums)


@pytest.mark.parametrize("name", [n for n, p in PROTOS.items() if p.entry.get("stage") == "quote"])
def test_every_outcome_reachable(name):
    p = PROTOS[name]
    exprs = [p.applies_when] + [e for _, e in p.overlays]

    def collect(n):
        for b in n["branches"]:
            exprs.append(parse(b["when"]))
            if "outcome" not in b["then"]:
                collect(b["then"])
    for t in p.trees:
        collect(t)
    fields = sorted({f for e in exprs for f in e.fields()})
    lits = {f: [l for e in exprs for fld, _, l in e.literals() if fld == f] for f in fields}
    reached = set()
    for combo in itertools.product(*[_candidates(f, lits[f]) for f in fields]):
        r = engine.evaluate_protocol(p, dict(zip(fields, combo)))
        if r.outcome:
            reached.add(r.outcome)
        for ov in r.overlays:
            reached.add(next(o["outcome"] for o in p.data["overlay_rules"] if o["id"] == ov))
    unreachable = set(p.outcomes) - reached - {"UW_REVIEW"}
    assert not unreachable, f"{name}: outcomes never reached: {unreachable}"
