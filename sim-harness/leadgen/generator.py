"""Core lead generation: build a clean base lead, assign difficulty, inject
hard archetypes, apply field-level perturbations, validate against the registry.

Everything is driven off a single seeded RNG so the same (seed, config) pair
reproduces an identical queue.
"""

from __future__ import annotations

import copy
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from shared import registry
from . import archetypes

# Reference "morning" the queue is generated against. Fixed (not wall-clock) so
# received_at timestamps are reproducible for a given seed.
REFERENCE = datetime(2026, 6, 29, 8, 0, 0, tzinfo=timezone.utc)


# --- derived-classification maps (used by the clean base lead) ------------

ROOF_CLASS = {
    "Architecture Shingles": "Class A",
    "Asphalt Fiberglass Composite": "Class A",
    "Clay Tile": "Class A",
    "Concrete Tile": "Class A",
    "Metal Shingles / Sheets": "Class A",
    "Slate": "Class A",
    "Standing Seam Metal": "Class A",
    "Wood Shake": "Class C",
    "Wood Shingle": "Class C",
    "Other": "Class B",
}

SIDING_CLASS = {
    "Brick / Masonry Veneer": "A",
    "Fire Resistive": "A",
    "Cement Fiber": "B",
    "Stucco": "B",
    "Aluminum / Steel": "C",
    "Vinyl": "C",
    "Wood": "D",
    "Wood Shake / Shingle": "D",
    "Other": "C",
}

# A few internally-consistent location tuples to draw from.
LOCATIONS = [
    ("Naples", "Collier", "FL", "34102"),
    ("Boulder", "Boulder", "CO", "80302"),
    ("Santa Rosa", "Sonoma", "CA", "95404"),
    ("Bend", "Deschutes", "OR", "97701"),
    ("Asheville", "Buncombe", "NC", "28801"),
    ("Flagstaff", "Coconino", "AZ", "86001"),
]
STREETS = ["Ridgecrest Rd", "Canyon View Dr", "Meadowlark Ln", "Summit Ave",
           "Old Mill Rd", "Pinecrest Way", "Hillside Ct", "Lakeview Blvd"]
FIRST = ["R.", "Dana", "Miguel", "Priya", "Aaron", "Lena", "Tomas", "Grace"]
LAST = ["Calloway", "Nguyen", "Okafor", "Bauer", "Salazar", "Whitfield", "Ahn", "Reyes"]
OCCUPATIONS = ["Architect", "Teacher", "Software Engineer", "Retired", "Physician", "Contractor"]


def _base_lead(rng: random.Random) -> dict[str, Any]:
    """A complete, internally-consistent, *clean* lead (all required fields set)."""
    city, county, state, zip_ = rng.choice(LOCATIONS)
    coverage_a = rng.randrange(400_000, 1_400_000, 25_000)
    roof_material = rng.choice(["Architecture Shingles", "Asphalt Fiberglass Composite",
                                "Clay Tile", "Standing Seam Metal"])
    siding_material = rng.choice(["Stucco", "Cement Fiber", "Brick / Masonry Veneer"])
    year_built = rng.randint(1965, 2018)

    return {
        # Location
        "street_address": f"{rng.randint(100, 9999)} {rng.choice(STREETS)}",
        "city": city, "county": county, "state": state, "zip": zip_,
        # Account (system-owned)
        "broker_tier": rng.choice(["Tier 1", "Tier 2"]),
        "has_primary_policy_with_stand": False,
        "listed_for_sale": False,
        # Insured
        "first_name": rng.choice(FIRST),
        "last_name": rng.choice(LAST),
        "residence_held_in_trust": False,
        "trust_name": None,  # conditional: only when held in trust
        "owner_email": "owner@example.com",
        "owner_phone_number": f"+1-555-0{rng.randint(100, 199)}",
        "insured_dob": f"{rng.randint(1955, 1995)}-0{rng.randint(1, 9)}-{rng.randint(10, 28)}",
        "occupation": rng.choice(OCCUPATIONS),
        "number_of_residents": rng.randint(1, 5),
        "kyc_score": rng.randint(1, 4),
        # Primary coverages
        "effective_date": (REFERENCE + timedelta(days=rng.randint(7, 45))).strftime("%Y-%m-%d"),
        "coverage_a": coverage_a,
        "coverage_e": rng.choice(["100000", "300000", "500000"]),
        "coverage_f": rng.choice(["1000", "3000", "5000"]),
        "replacement_cost": int(coverage_a * rng.uniform(0.95, 1.1)),
        # Property
        "dwelling_type": "Owner Occupied Single Family Residence",
        "dwelling_use_type": "Primary",
        "is_rental": "No",
        "months_unoccupied": 0,
        "year_built": year_built,
        "property_purchase_date": f"{rng.randint(2005, 2024)}-0{rng.randint(1, 9)}-15",
        "pool_type": "None",
        "pool_security": "None",
        "pool_has_diving_board_or_slide": False,
        "above_ground_pool_ladder": None,  # only when Above Ground
        "is_gated_community": False,
        "acreage": round(rng.uniform(0.1, 2.5), 2),
        "has_animals": rng.random() < 0.3,
        # Construction
        "structure_type": "Single Family",
        "construction_type": "Frame",
        "siding_material": siding_material,
        "foundation_type": "Slab",
        "post_pier_supports_living_area": None,  # only for pier/stilt/piling foundations
        "deck_height_ft": None,
        "square_feet": rng.randrange(1200, 4200, 100),
        "num_stories": rng.randint(1, 2),
        "roof_replacement_year": rng.randint(2010, 2023),
        "roof_material": roof_material,
        "roof_shape": rng.choice(["Gable", "Hip"]),
        "heating_source": "Central Gas",
        "has_knob_and_tube_wiring": False,
        "electrical_panel_brand": rng.choice(["Square D", "Eaton", "Siemens", "GE"]),
        "electrical_panel_size_amps": rng.choice([150, 200]),
        # Plumbing (Tankless -> age/location not required)
        "plumbing_age_years": rng.randint(3, 20),
        "water_heater_type": "Tankless",
        "water_heater_age_years": None,
        "water_heater_location": None,
        # Protection
        "fire_alarm": rng.choice(["Local Alarm", "Central Alarm"]),
        "distance_to_fire_department": round(rng.uniform(0.5, 5.0), 1),
        "fire_department_type": rng.choice(["Career", "Mostly Career"]),
        "dist_to_nearest_fire_hydrant": rng.randint(50, 600),
        "opening_protection": None,  # conditional, no active condition in base
        "road_access": "Multiple Access Points",
        "protection_class": rng.choice(["3", "4", "5"]),
        "fire_dept_response_time": None,   # only when PC 9/10
        "alternative_water_source": None,  # only when PC 9/10
        "interior_sprinklers": None,       # only when PC 9/10
        "physical_barriers": None,         # only when PC 9/10
        # Wildfire (mostly system-owned)
        "min_distance_to_neighbor_ft": rng.randint(20, 120),
        "is_7a_compliant": True,
        "slope_angle_deg": round(rng.uniform(1.0, 12.0), 1),
        "roof_classification": ROOF_CLASS[roof_material],
        "p_f": round(rng.uniform(0.02, 0.2), 2),
        "siding_classification": SIDING_CLASS[siding_material],
        "vegetation_clearance": "Adequate",
    }


# --- archetype selection --------------------------------------------------


def _weighted_pick(rng: random.Random, weights: dict[str, float], k: int,
                   exclude: set[str]) -> list[str]:
    """Pick up to k distinct archetype names by relative weight."""
    pool = {n: w for n, w in weights.items() if n not in exclude and n in archetypes.ARCHETYPES}
    chosen: list[str] = []
    for _ in range(k):
        if not pool:
            break
        names = list(pool.keys())
        ws = [pool[n] for n in names]
        pick = rng.choices(names, weights=ws, k=1)[0]
        chosen.append(pick)
        pool.pop(pick)
    return chosen


def _archetypes_for_tier(rng: random.Random, tier: str, weights: dict[str, float]) -> list[str]:
    if tier == "hard":
        k = rng.choice([1, 2])
    elif tier == "medium":
        k = 1 if rng.random() < 0.6 else 0
    else:  # easy
        k = 0
    return _weighted_pick(rng, weights, k, exclude=set())


# --- perturbation ---------------------------------------------------------

CONFLICT_INJECTORS = [
    ("months_unoccupied", lambda f, r: 11,
     "unoccupied 11 months but claims primary occupancy"),
    ("roof_replacement_year", lambda f, r: 2031,
     "roof replacement year in the future"),
    ("electrical_panel_size_amps", lambda f, r: 30,
     "implausibly small electrical service"),
    ("number_of_residents", lambda f, r: 0,
     "zero residents for an owner-occupied home"),
    ("acreage", lambda f, r: 0.0,
     "zero acreage"),
]


def _apply_perturbations(fields: dict[str, Any], rng: random.Random, tier: str,
                         rates: dict[str, float], owned: set[str]) -> list[dict[str, str]]:
    """Null out / conflict fields by tier rates. Returns perturbation records."""
    touches: list[dict[str, str]] = []
    rev_derived: dict[str, str] = {}  # source -> derived
    for derived, source in registry.derived_map().items():
        rev_derived[source] = derived

    for name in list(fields.keys()):
        if name in owned or fields.get(name) is None:
            continue
        level = registry.required_level(name)

        if registry.is_system_owned(name):
            rate, kind = rates.get("missing_system_owned", 0.0), "missing_system_owned"
        elif level == "always":
            rate, kind = rates.get("missing_required", 0.0), "missing_required"
        elif level == "conditional":
            rate, kind = rates.get("missing_required", 0.0) * 0.7, "missing_required_conditional"
        elif level == "bind_only":
            rate, kind = 0.25, "missing_bind_only"  # tier-independent: tests over-asking
        else:  # "no"
            rate, kind = 0.10, "missing_optional"

        if rng.random() < rate:
            fields[name] = None
            touches.append({"field": name, "kind": kind, "detail": f"{level} field nulled"})
            # Cascade: nulling a derivation source invalidates its derived field.
            dep = rev_derived.get(name)
            if dep and fields.get(dep) is not None:
                fields[dep] = None
                touches.append({"field": dep, "kind": "missing_derived",
                                "detail": f"derivedFrom {name}; nulled with source"})

    # Conflict: a present-but-inconsistent value (stays type-valid -> "verify").
    if rng.random() < rates.get("conflict", 0.0):
        field, fn, detail = rng.choice(CONFLICT_INJECTORS)
        if field not in owned:
            fields[field] = fn(fields, rng)
            touches.append({"field": field, "kind": "conflict", "detail": detail})

    return touches


# --- public API -----------------------------------------------------------


def _tier_sequence(rng: random.Random, count: int, difficulty: str,
                   tier_mix: dict[str, int]) -> list[str]:
    """Build a shuffled list of `count` tiers per the requested difficulty."""
    if difficulty == "easy":
        seq = ["easy"] * count
    elif difficulty == "hard":
        seq = ["hard"] * count
    else:  # mixed -> scale the configured mix to `count`
        total = sum(tier_mix.values()) or 1
        seq = []
        for tier in ("easy", "medium", "hard"):
            seq += [tier] * round(count * tier_mix.get(tier, 0) / total)
        # Fix rounding drift.
        while len(seq) < count:
            seq.append("medium")
        seq = seq[:count]
    rng.shuffle(seq)
    return seq


def _fold_truth(clean: dict[str, Any], touches: list[dict[str, Any]]) -> None:
    """Fold archetype touches into the ground-truth fields, then strip `truth`
    from the touch records (the answer key's perturbation schema has no such key).

    archetype_set -> truth is the value the archetype set (already in `clean` if
    `clean` was snapshotted after the set; applied here for the retrofit path);
    archetype_null -> truth is the intended hidden value.
    """
    for t in touches:
        if t["kind"] == "archetype_null":
            clean[t["field"]] = t.pop("truth", None)
        else:
            t.pop("truth", None)


def generate_lead(rng: random.Random, seed: int, index: int, tier: str,
                  config: dict[str, Any]) -> dict[str, Any]:
    """Generate one lead. Returns {lead_id, received_at, source, fields, debug}."""
    fields = _base_lead(rng)
    weights = {n: d.get("weight", 1) for n, d in config.get("archetypes", {}).items()}
    rates = config.get("perturbation_rates", {}).get(tier, {})

    injected = _archetypes_for_tier(rng, tier, weights)
    perturbations: list[dict[str, str]] = []
    owned: set[str] = set()
    for name in injected:
        touches = archetypes.ARCHETYPES[name](fields, rng)
        perturbations.extend(touches)
        owned.update(t["field"] for t in touches)

    # Ground truth (eval/grader only, DEBUG-gated): the archetype-consistent lead
    # BEFORE random nulling/conflicts. Taken after archetypes so hazard fields keep
    # their intended values; archetype-nulled fields get their `truth` value.
    clean = copy.deepcopy(fields)
    _fold_truth(clean, perturbations)

    perturbations.extend(_apply_perturbations(fields, rng, tier, rates, owned))

    # Validate against the registry; a fixture that emits invalid leads is a bug.
    errors = registry.validate_lead_fields(fields)
    if errors:
        raise ValueError(f"generated lead failed registry validation: {errors}")

    received_at = (REFERENCE - timedelta(minutes=rng.randint(0, 180))).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    lead_id = f"LEAD-{seed:08d}-{index:03d}"
    source = rng.choice(["agent_portal", "broker_email", "direct_web"])

    return {
        "lead_id": lead_id,
        "received_at": received_at,
        "source": source,
        "fields": fields,
        "debug": {
            "difficulty": tier,
            "injected_archetypes": injected,
            "perturbations": perturbations,
            "clean_fields": clean,
        },
    }


def generate_queue(seed: int, count: int, difficulty: str,
                   config: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate a full queue, honoring the hard-archetype guarantee."""
    rng = random.Random(seed)
    tier_mix = config.get("queue", {}).get("tier_mix", {"easy": 2, "medium": 4, "hard": 4})
    guarantee = config.get("queue", {}).get("guarantee_hard_archetypes", 0)

    tiers = _tier_sequence(rng, count, difficulty, tier_mix)
    leads = [generate_lead(rng, seed, i, tier, config) for i, tier in enumerate(tiers)]

    # Guarantee: ensure at least N leads carry a hard archetype.
    weights = {n: d.get("weight", 1) for n, d in config.get("archetypes", {}).items()}
    with_arch = [ld for ld in leads if ld["debug"]["injected_archetypes"]]
    if difficulty != "easy" and len(with_arch) < guarantee:
        needed = guarantee - len(with_arch)
        candidates = [ld for ld in leads if not ld["debug"]["injected_archetypes"]]
        for ld in candidates[:needed]:
            name = _weighted_pick(rng, weights, 1, exclude=set())
            if not name:
                break
            touches = archetypes.ARCHETYPES[name[0]](ld["fields"], rng)
            # Retrofit: archetype_set values go into truth too (nulled fields get `truth`).
            for t in touches:
                if t["kind"] == "archetype_set":
                    ld["debug"]["clean_fields"][t["field"]] = ld["fields"][t["field"]]
            _fold_truth(ld["debug"]["clean_fields"], touches)
            ld["debug"]["injected_archetypes"] = name
            ld["debug"]["perturbations"].extend(touches)
            errors = registry.validate_lead_fields(ld["fields"])
            if errors:
                raise ValueError(f"guaranteed archetype produced invalid lead: {errors}")

    return leads
