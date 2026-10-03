"""Builds the fixed eval set `evals/sets/fixed.json` (D17): hand-authored cases, one per protocol leaf and numeric
boundary in evals/COVERAGE_GAPS.md plus lookup / vendor / reply / conflict scenarios.

Every case = a clean base lead + overrides (the truth), then fields hidden or corrupted to make the raw lead.
`focus` is the hand-written expectation (protocol outcomes the case exists to test); the build FAILS if the engine
disagrees with it, then freezes the engine's full result as the case's `expect`.

    uv run python -m evals.build_fixed_set          # rewrite evals/sets/fixed.json
    (tests/test_evals.py checks the committed file equals a fresh build)"""

from __future__ import annotations

import copy
import json
import random
from typing import Any, Optional

import uw_agent.config  # noqa: F401
from leadgen import generator
from shared import registry

from evals import grader, setdefs
from evals.model import EvalCase

RECEIVED = "2026-06-29T08:00:00Z"
BASE = generator._base_lead(random.Random(1))      # quote-clean: every protocol passes with no conditions
BASE["owner_email"] = "owner@example.com"

BOUNDARIES = ["pf=0.15", "pf=0.50", "wh_age=10", "wh_age=11", "plumbing_age=30", "plumbing_age=31",
              "roof_age=20", "roof_age=21"]

CASES: list[dict[str, Any]] = []


def case(cid: str, focus: dict[str, str], truth: dict[str, Any], hide: list[str] = (), raw: Optional[dict[str, Any]] = None,
         tags: Optional[dict[str, list[str]]] = None, vendor: Optional[list[tuple[str, str, str]]] = None,
         reply: str = "complete", conflict: bool = False, state: Optional[str] = None, note: str = "") -> None:
    CASES.append(dict(cid=cid, focus=focus, truth=truth, hide=list(hide), raw=raw or {}, tags=tags or {},
                      vendor=vendor or [], reply=reply, conflict=conflict, state=state, note=note))


# --- swimming pools ------------------------------------------------------------------------------------------
LK = {"failure_mode": ["lookup_field"]}
case("pool-ag-ladder-yes", {"swimming_pools": "OK_TO_QUOTE"}, {"pool_type": "Above Ground", "above_ground_pool_ladder": True},
     hide=["pool_type", "above_ground_pool_ladder"], tags=LK)
case("pool-ag-ladder-no", {"swimming_pools": "REQUIRE_LADDER"}, {"pool_type": "Above Ground", "above_ground_pool_ladder": False},
     hide=["pool_type", "above_ground_pool_ladder"], tags={"failure_mode": ["lookup_field"], "scenario": ["lookup_not_found_assume_no"]})
case("pool-inground-fenced-secure", {"swimming_pools": "OK_TO_QUOTE"},
     {"pool_type": "Inground", "pool_security": "Fenced", "pool_fence_self_locking_or_safety_cover": True},
     hide=["pool_type", "pool_security", "pool_fence_self_locking_or_safety_cover"], tags={"failure_mode": ["lookup_field", "missing_producer_field"]})
case("pool-inground-fenced-not-secure", {"swimming_pools": "REQUIRE_COVER"},
     {"pool_type": "Inground", "pool_security": "Fenced", "pool_fence_self_locking_or_safety_cover": False},
     hide=["pool_security", "pool_fence_self_locking_or_safety_cover"], tags={"failure_mode": ["lookup_field", "missing_producer_field"]})
case("pool-unfenced-gated", {"swimming_pools": "ACCEPT_REC_COVER"},
     {"pool_type": "Inground", "pool_security": "Unfenced", "is_gated_community": True}, hide=["pool_security", "is_gated_community"], tags=LK)
case("pool-unfenced-not-gated", {"swimming_pools": "REQUIRE_COVER"},
     {"pool_type": "Inground", "pool_security": "Unfenced", "is_gated_community": False}, hide=["pool_security", "is_gated_community"], tags=LK)
case("pool-diving-board-overlay", {"swimming_pools": "OK_TO_QUOTE"},
     {"pool_type": "Inground", "pool_security": "Fenced", "pool_fence_self_locking_or_safety_cover": True,
      "pool_has_diving_board_or_slide": True}, hide=["pool_has_diving_board_or_slide", "pool_fence_self_locking_or_safety_cover"],
     tags={"failure_mode": ["lookup_field", "missing_producer_field"], "scenario": ["overlay"]})
case("pool-none-hidden-not-found", {}, {"pool_type": "None"}, hide=["pool_type"],
     tags={"failure_mode": ["lookup_field"], "scenario": ["lookup_not_found_assume_no"]})
# lookups that cannot decide: the honest behaviour is NOT to assume "no pool" when the evidence is unclear
case("pool-ambiguous-imagery", {"swimming_pools": "REQUIRE_LADDER"}, {"pool_type": "Above Ground", "above_ground_pool_ladder": False},
     hide=["pool_type"], vendor=[("listing", "pool_type", "ambiguous")], tags={"failure_mode": ["lookup_field"], "scenario": ["lookup_ambiguous"]})
case("pool-listing-service-down", {"swimming_pools": "REQUIRE_COVER"},
     {"pool_type": "Inground", "pool_security": "Unfenced", "is_gated_community": False},
     hide=["pool_type", "pool_security", "is_gated_community"], vendor=[("listing", "*", "unavailable")],
     tags={"failure_mode": ["lookup_field"], "scenario": ["lookup_unavailable"]})

# --- roof class (derived from material + year; P(F) from the geo vendor) -----------------------------------------
WOOD = {"roof_material": "Wood Shake", "roof_classification": "Class C"}
DER = {"failure_mode": ["derived_value", "missing_system_owned_field"]}
case("roof-pf-015-boundary", {"roof_class": "OK_TO_QUOTE"}, {**WOOD, "p_f": 0.15}, hide=["roof_classification", "p_f"],
     tags={**DER, "boundary": ["pf=0.15"]})
case("roof-pf-016-first-term", {"roof_class": "CONFIRM_CLASS_A_FIRST_TERM"}, {**WOOD, "p_f": 0.16}, hide=["roof_classification"], tags=DER)
case("roof-pf-050-boundary", {"roof_class": "CONFIRM_CLASS_A_FIRST_TERM"}, {**WOOD, "p_f": 0.50}, hide=["roof_classification"],
     tags={**DER, "boundary": ["pf=0.50"]})
case("roof-pf-051-60-days", {"roof_class": "CONFIRM_CLASS_A_60_DAYS_OR_DECLINE"}, {**WOOD, "p_f": 0.51}, hide=["roof_classification"], tags=DER)
case("roof-class-a-tile-high-pf", {"roof_class": "OK_TO_QUOTE"},
     {"roof_material": "Clay Tile", "roof_classification": "Class A", "p_f": 0.8}, hide=["roof_classification"], tags=DER)
case("roof-composition-age-20", {"roof_class": "OK_TO_QUOTE"},
     {"roof_material": "Asphalt Fiberglass Composite", "roof_replacement_year": 2006, "roof_classification": "Class A", "p_f": 0.4},
     hide=["roof_classification"], tags={**DER, "boundary": ["roof_age=20"]})
case("roof-composition-age-21-class-b", {"roof_class": "CONFIRM_CLASS_A_FIRST_TERM"},
     {"roof_material": "Asphalt Fiberglass Composite", "roof_replacement_year": 2005, "roof_classification": "Class B", "p_f": 0.4},
     hide=["roof_classification"], tags={**DER, "boundary": ["roof_age=21"]})
case("roof-inputs-from-producer", {"roof_class": "CONFIRM_CLASS_A_FIRST_TERM"},
     {"roof_material": "Wood Shingle", "roof_replacement_year": 2018, "roof_classification": "Class C", "p_f": 0.3},
     hide=["roof_classification", "roof_material", "roof_replacement_year"],
     tags={"failure_mode": ["derived_value", "missing_producer_field"]})

# --- siding ------------------------------------------------------------------------------------------------------
D = {"siding_material": "Wood", "siding_classification": "D"}
case("siding-d-pf-015-boundary", {"siding": "NO_ACTION"}, {**D, "p_f": 0.15}, hide=["siding_classification"], tags={**DER, "boundary": ["pf=0.15"]})
case("siding-d-pf-016-first-term", {"siding": "CONFIRM_CLASS_A_SIDING_FIRST_TERM"}, {**D, "p_f": 0.16}, hide=["siding_classification"], tags=DER)
case("siding-d-pf-050-boundary", {"siding": "CONFIRM_CLASS_A_SIDING_FIRST_TERM"}, {**D, "p_f": 0.5}, hide=["siding_classification"],
     tags={**DER, "boundary": ["pf=0.50"]})
case("siding-d-pf-051-uw-period", {"siding": "CONFIRM_CLASS_A_SIDING_UW_PERIOD"}, {**D, "p_f": 0.51}, hide=["siding_classification"], tags=DER)

# --- water heaters -----------------------------------------------------------------------------------------------
PROD = {"failure_mode": ["missing_producer_field"]}
case("wh-tankless", {"water_heaters": "OK_TO_QUOTE"}, {"water_heater_type": "Tankless"}, hide=["water_heater_type"], tags=PROD)
case("wh-tank-age-10-boundary", {"water_heaters": "OK_TO_QUOTE"},
     {"water_heater_type": "Tank", "water_heater_age_years": 10, "water_heater_location": "In or Above Finished Space"},
     hide=["water_heater_type", "water_heater_age_years", "water_heater_location"], tags={**PROD, "boundary": ["wh_age=10"]})
case("wh-tank-age-11-unfinished", {"water_heaters": "REQUIRE_PLUMBING_INSPECTION"},
     {"water_heater_type": "Tank", "water_heater_age_years": 11, "water_heater_location": "Unfinished Space"},
     hide=["water_heater_type", "water_heater_age_years", "water_heater_location"], tags={**PROD, "boundary": ["wh_age=11"]})
case("wh-tank-11-finished-tier1", {"water_heaters": "REQUIRE_PLUMBING_INSPECTION"},
     {"water_heater_type": "Tank", "water_heater_age_years": 11, "water_heater_location": "In or Above Finished Space",
      "broker_tier": "Tier 1"}, hide=["water_heater_type", "water_heater_age_years", "water_heater_location", "broker_tier"],
     tags={"failure_mode": ["missing_producer_field", "missing_system_owned_field"]})
case("wh-tank-11-finished-with-policy", {"water_heaters": "REQUIRE_PLUMBING_INSPECTION"},
     {"water_heater_type": "Tank", "water_heater_age_years": 11, "water_heater_location": "In or Above Finished Space",
      "broker_tier": "Tier 2", "has_primary_policy_with_stand": True},
     hide=["water_heater_type", "water_heater_age_years", "water_heater_location", "has_primary_policy_with_stand"],
     tags={"failure_mode": ["missing_producer_field", "missing_system_owned_field"]})
case("wh-tank-11-finished-decline", {"water_heaters": "DECLINE"},
     {"water_heater_type": "Tank", "water_heater_age_years": 11, "water_heater_location": "In or Above Finished Space",
      "broker_tier": "Tier 3", "has_primary_policy_with_stand": False},
     hide=["water_heater_type", "water_heater_age_years", "water_heater_location", "broker_tier"],
     tags={"failure_mode": ["missing_producer_field", "missing_system_owned_field"]})

# --- general plumbing --------------------------------------------------------------------------------------------
case("plumbing-age-30-boundary", {"general_plumbing": "OK_TO_QUOTE"}, {"plumbing_age_years": 30}, hide=["plumbing_age_years"],
     tags={**PROD, "boundary": ["plumbing_age=30"]})
case("plumbing-age-31-tier1", {"general_plumbing": "REQUIRE_PLUMBING_INSPECTION"}, {"plumbing_age_years": 31, "broker_tier": "Tier 1"},
     hide=["plumbing_age_years", "broker_tier"], tags={"failure_mode": ["missing_producer_field", "missing_system_owned_field"],
                                                         "boundary": ["plumbing_age=31"]})
case("plumbing-age-31-decline", {"general_plumbing": "DECLINE"},
     {"plumbing_age_years": 31, "broker_tier": "Tier 2", "has_primary_policy_with_stand": False}, hide=["plumbing_age_years"],
     tags={**PROD, "boundary": ["plumbing_age=31"]})

# --- trusts and LLCs ---------------------------------------------------------------------------------------------
case("trust-with-name", {"trusts_and_llcs_quote": "QUOTE_REQUIRE_QUESTIONNAIRE"},
     {"residence_held_in_trust": True, "trust_name": "Alvarez Family Trust"}, hide=["residence_held_in_trust", "trust_name"], tags=PROD)
case("trust-name-missing", {"trusts_and_llcs_quote": "QUOTE_REQUIRE_QUESTIONNAIRE"},
     {"residence_held_in_trust": True, "trust_name": "Chen Living Trust"}, hide=["trust_name"], tags=PROD)
case("trust-not-a-trust-conditional-na", {}, {"residence_held_in_trust": False}, hide=["residence_held_in_trust"],
     tags={**PROD, "scenario": ["conditional_question_na"]})

# --- conflicts (present but inconsistent: the underwriter decides) -------------------------------------------------
CF = {"failure_mode": ["conflict"]}
case("conflict-short-term-rental-primary", {}, {"is_rental": "No"}, raw={"is_rental": "Short-Term Rentals"}, tags=CF, conflict=True)
case("conflict-owner-occupied-secondary", {}, {"dwelling_use_type": "Primary"}, raw={"dwelling_use_type": "Secondary"}, tags=CF, conflict=True)
case("conflict-roof-year-future", {}, {"roof_replacement_year": 2016}, raw={"roof_replacement_year": 2031}, tags=CF, conflict=True)
case("conflict-implausible-service", {}, {"electrical_panel_size_amps": 200}, raw={"electrical_panel_size_amps": 30}, tags=CF, conflict=True)
case("near-miss-not-a-conflict", {}, {"months_unoccupied": 2, "dwelling_use_type": "Primary"}, tags={"scenario": ["no_false_conflict"]})

# --- imperfect replies ---------------------------------------------------------------------------------------------
MULTI = ["plumbing_age_years", "water_heater_type", "water_heater_age_years", "water_heater_location"]
MT = {"water_heater_type": "Tank", "water_heater_age_years": 5, "water_heater_location": "Unfinished Space", "plumbing_age_years": 22}
case("reply-partial-then-complete", {"water_heaters": "OK_TO_QUOTE", "general_plumbing": "OK_TO_QUOTE"}, MT, hide=MULTI,
     reply="partial", tags={**PROD, "scenario": ["reply_partial"]})
case("reply-none", {"water_heaters": "OK_TO_QUOTE", "general_plumbing": "OK_TO_QUOTE"}, MT, hide=MULTI, reply="none",
     state="awaiting_reply", tags={**PROD, "scenario": ["reply_none"]},
     note="producer never replies: one email, lead stays awaiting, no nagging duplicate")

# --- vendor failures (system-owned data the producer cannot supply) -------------------------------------------------
case("vendor-crm-down", {"general_plumbing": "REQUIRE_PLUMBING_INSPECTION"}, {"plumbing_age_years": 40, "broker_tier": "Tier 1"},
     hide=["broker_tier"], vendor=[("crm", "*", "unavailable")], state="needs_uw",
     tags={"failure_mode": ["missing_system_owned_field"], "scenario": ["vendor_unavailable"]},
     note="broker tier is system-owned: with the CRM down the lead cannot be decided and goes to the underwriter")
case("vendor-geo-no-record", {"roof_class": "CONFIRM_CLASS_A_FIRST_TERM"}, {**WOOD, "p_f": 0.3}, hide=["p_f", "roof_classification"],
     vendor=[("geo", "p_f", "not_found")], state="needs_uw",
     tags={"failure_mode": ["missing_system_owned_field"], "scenario": ["vendor_not_found"]},
     note="P(F) is needed by the roof and siding checks and has no record: escalate rather than guess")


def materialize(spec: dict[str, Any]) -> dict[str, Any]:
    truth = {**copy.deepcopy(BASE), **spec["truth"]}
    known = set(registry.field_names())
    raw = {k: v for k, v in copy.deepcopy(truth).items() if k in known}    # playbook-only fields never appear in a payload
    for f in spec["hide"]:
        if f not in known:
            continue
        raw[f] = None
    raw.update(spec["raw"])
    errs = registry.validate_lead_fields(raw)
    if errs:
        raise SystemExit(f"{spec['cid']}: raw lead fails registry validation: {errs}")
    lead = {"lead_id": "FIX-" + spec["cid"], "received_at": RECEIVED, "source": "agent_portal", "fields": raw}
    c = EvalCase(lead, truth, "fixed", [], [], spec["tags"], spec["conflict"],
                 [{"vendor": v, "key": k, "behavior": b} for v, k, b in spec["vendor"]], spec["reply"], None, spec["cid"])
    o = grader.oracle(c)
    for p, outcome in spec["focus"].items():
        if o.outcomes.get(p) != outcome:
            raise SystemExit(f"{spec['cid']}: hand-written {p}={outcome} but the engine says {o.outcomes.get(p)}")
    state = spec["state"] or o.state
    return {"case_id": spec["cid"], "lead": lead, "truth": truth, "tags": spec["tags"], "conflict_injected": spec["conflict"],
            "vendor_overrides": c.vendor_overrides, "reply_mode": spec["reply"],
            "expect": {"decision": o.decision, "conditions": o.conditions, "outcomes": o.outcomes, "final_state": state,
                       "focus": spec["focus"], "note": spec["note"]}}


def build() -> dict[str, Any]:
    ids = [c["cid"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    return {"_comment": "Generated by `python -m evals.build_fixed_set` from hand-written cases (D17). Do not edit by hand.",
            "name": "fixed", "boundaries": BOUNDARIES, "cases": [materialize(c) for c in CASES]}


if __name__ == "__main__":
    d = build()
    setdefs.FIXED_JSON.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")
    print(f"wrote {len(d['cases'])} cases to {setdefs.FIXED_JSON}")
