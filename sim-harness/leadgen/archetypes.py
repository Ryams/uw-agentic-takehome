"""Hard failure-mode scenarios, drawn from the FigJam decision flow.

Each archetype takes a *complete* base lead (dict of field -> value) plus an
RNG, mutates it in place to send the lead down a hard branch, and nulls
whatever input that branch needs the agent to resolve. Each returns a list of
`Perturbation`-shaped dicts describing what it did (for the answer key) and the
set of field names it "owns" so the generic perturbation pass leaves them alone.

The values here are deliberately chosen to match the registry's allowed select
options and the FigJam's hard branches.
"""

from __future__ import annotations

import random
from typing import Any, Callable

# A touch record: {"field": str, "kind": str, "detail": str}
Touch = dict[str, str]


def _set(fields: dict[str, Any], touches: list[Touch], field: str, value: Any, detail: str) -> None:
    fields[field] = value
    touches.append({"field": field, "kind": "archetype_set", "detail": detail})


_UNSET: Any = object()


def _null(fields: dict[str, Any], touches: list[Touch], field: str, detail: str,
          truth: Any = _UNSET) -> None:
    """Null a field the agent must resolve.

    `truth` is what the homeowner/third party would actually answer; it is the
    ground truth consumed by the eval harness and reply simulator (never shown to
    the agent). Defaults to the pre-null value. Truth values are constants, NOT RNG
    draws, so adding them does not change any seeded queue.
    """
    old = fields.get(field)
    fields[field] = None
    touches.append({"field": field, "kind": "archetype_null", "detail": detail,
                    "truth": old if truth is _UNSET else truth})


# --- archetypes -----------------------------------------------------------


def electrical_hazard(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """knob & tube, Federal Pacific panel, undersized service, pre-1950 build."""
    t: list[Touch] = []
    _set(fields, t, "has_knob_and_tube_wiring", True, "knob & tube present")
    _set(fields, t, "electrical_panel_brand", "Federal Pacific", "hazardous panel brand")
    _set(fields, t, "year_built", rng.randint(1900, 1949), "pre-1950 construction")
    if rng.random() < 0.5:
        _set(fields, t, "electrical_panel_size_amps", rng.choice([60, 100]), "undersized service")
    else:
        # Producer-editable always-required -> forces a clear email.
        _null(fields, t, "electrical_panel_size_amps", "panel size unknown; ask producer", truth=100)
    return t


def pc_9_10_rural(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Remote property: far FD, volunteer staffing, no hydrant, PC unknown -> assume 9."""
    t: list[Touch] = []
    _set(fields, t, "distance_to_fire_department", round(rng.uniform(8.0, 20.0), 1), "far from fire dept")
    _set(fields, t, "fire_department_type", "Volunteer", "volunteer department")
    _set(fields, t, "dist_to_nearest_fire_hydrant", rng.randint(2000, 9000), "no nearby hydrant")
    # System-owned -> agent must derive/assume (missingDefault 9), NOT email.
    _null(fields, t, "protection_class", "PPC unknown; assume 9 (system-owned)", truth="9")
    _set(fields, t, "road_access", "Limited / Dead-end / No Turnaround", "poor road access")
    # PC 9/10 makes these conditional fields required; leave one unanswered.
    _null(fields, t, "fire_dept_response_time", "required when PC 9/10; ask producer", truth="Greater than 30 Minutes")
    return t


def wildfire_severe(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Severe WUI exposure with the roof-material -> roof-class dependency chain."""
    t: list[Touch] = []
    # Dependency chain: can't derive class until upstream material is resolved.
    _null(fields, t, "roof_material", "roof material unknown; ask producer (blocks roof class)", truth="Wood Shake")
    _null(fields, t, "roof_classification", "derivedFrom roof_material; can't derive yet", truth="Class C")
    _set(fields, t, "siding_material", "Wood Shake / Shingle", "combustible siding")
    _set(fields, t, "siding_classification", "D", "worst siding fire class")
    _set(fields, t, "p_f", round(rng.uniform(0.55, 0.9), 2), "high probability of failure")
    _set(fields, t, "min_distance_to_neighbor_ft", rng.randint(6, 14), "homes very close together")
    _set(fields, t, "is_7a_compliant", False, "not Chapter 7A compliant")
    _set(fields, t, "slope_angle_deg", round(rng.uniform(25.0, 40.0), 1), "steep slope")
    _set(fields, t, "vegetation_clearance", "Too Close", "inadequate defensible space")
    return t


def replacement_cost_gap(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Coverage A far from replacement cost; RC must be auto-fetched. Sometimes fraud-suspect."""
    t: list[Touch] = []
    _null(fields, t, "replacement_cost", "RC unknown; auto-fetch (system-owned)")
    base = fields.get("coverage_a") or 600000
    if rng.random() < 0.4:
        # >150% of a plausible RCE -> over-insurance / fraud-suspect branch.
        _set(fields, t, "coverage_a", int(base * rng.uniform(1.6, 2.4)), "Coverage A >150% of likely RCE")
    else:
        # Well below RCE -> under-insurance branch.
        _set(fields, t, "coverage_a", int(base * rng.uniform(0.4, 0.6)), "Coverage A well below likely RCE")
    return t


def occupancy_conflict(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Owner-occupied story that conflicts with vacancy / rental signals."""
    t: list[Touch] = []
    variant = rng.choice(["vacant", "short_term", "owner_distant"])
    if variant == "vacant":
        _set(fields, t, "dwelling_type", "Owner Occupied Single Family Residence", "claims owner-occupied")
        _set(fields, t, "dwelling_use_type", "Primary", "claims primary residence")
        _set(fields, t, "months_unoccupied", rng.randint(3, 9), "but unoccupied for months")
    elif variant == "short_term":
        _set(fields, t, "dwelling_use_type", "Primary", "claims primary residence")
        _set(fields, t, "is_rental", "Short-Term Rentals", "but running short-term rentals")
    else:
        _set(fields, t, "dwelling_type", "Owner Occupied Single Family Residence", "claims owner-occupied")
        _set(fields, t, "dwelling_use_type", "Secondary", "but occupancy type says secondary")
    return t


def trust_llc(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Property held in a trust; trust name sometimes missing -> exposure screening."""
    t: list[Touch] = []
    _set(fields, t, "residence_held_in_trust", True, "property held in trust")
    if rng.random() < 0.6:
        _null(fields, t, "trust_name", "trust name required when held in trust; ask producer", truth="Redwood Holdings Trust")
    else:
        _set(fields, t, "trust_name", rng.choice(
            ["The Calloway Family Trust", "Redwood Holdings Trust", "Marin Living Trust"]),
            "named trust; screen for unacceptable exposure")
    return t


def post_and_pier(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Pier foundation supporting living area, or a tall deck."""
    t: list[Touch] = []
    _set(fields, t, "foundation_type", "Piers", "post & pier foundation")
    if rng.random() < 0.5:
        _set(fields, t, "post_pier_supports_living_area", True, "piers support living area")
        _null(fields, t, "deck_height_ft", "deck height unknown; ask producer", truth=4)
    else:
        _set(fields, t, "deck_height_ft", rng.randint(13, 28), "tall deck above grade")
        _null(fields, t, "post_pier_supports_living_area", "support detail unknown; ask producer", truth=False)
    return t


def plumbing_water_heater(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Old tank water heater in finished space + aged plumbing."""
    t: list[Touch] = []
    _set(fields, t, "water_heater_type", "Tank", "tank water heater")
    _set(fields, t, "water_heater_location", "In or Above Finished Space", "in finished space (leak exposure)")
    _set(fields, t, "plumbing_age_years", rng.randint(35, 65), "aged plumbing")
    if rng.random() < 0.5:
        _set(fields, t, "water_heater_age_years", rng.randint(11, 22), "old water heater")
    else:
        _null(fields, t, "water_heater_age_years", "WH age required for tank; ask producer", truth=12)
    return t


def pool_hazard(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Inground pool without adequate security."""
    t: list[Touch] = []
    _set(fields, t, "pool_type", "Inground", "inground pool")
    if rng.random() < 0.5:
        _set(fields, t, "pool_security", "Unfenced", "pool not fenced")
    else:
        _null(fields, t, "pool_security", "pool security required when pool present; ask producer", truth="Unfenced")
    _set(fields, t, "pool_has_diving_board_or_slide", True, "diving board / slide present")
    return t


def profile_kyc(fields: dict[str, Any], rng: random.Random) -> list[Touch]:
    """Elevated or unknown KYC score -> reputational review / lookup."""
    t: list[Touch] = []
    if rng.random() < 0.5:
        _set(fields, t, "kyc_score", rng.randint(6, 10), "elevated KYC score ('in spotlight')")
    else:
        _null(fields, t, "kyc_score", "KYC score unknown; system lookup (system-owned)", truth=4)
    return t


# name -> function. Weights live in generator_config.yaml.
ARCHETYPES: dict[str, Callable[[dict[str, Any], random.Random], list[Touch]]] = {
    "electrical_hazard": electrical_hazard,
    "pc_9_10_rural": pc_9_10_rural,
    "wildfire_severe": wildfire_severe,
    "replacement_cost_gap": replacement_cost_gap,
    "occupancy_conflict": occupancy_conflict,
    "trust_llc": trust_llc,
    "post_and_pier": post_and_pier,
    "plumbing_water_heater": plumbing_water_heater,
    "pool_hazard": pool_hazard,
    "profile_kyc": profile_kyc,
}
