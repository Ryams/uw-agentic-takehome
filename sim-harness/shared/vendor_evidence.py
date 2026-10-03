"""Evidence text for the simulated Maps/Zillow listing search (used by leadgen to write
`property_listings` and by the vendors service to inject noise). Text only: the agent's
interpreter turns it into a value."""

from __future__ import annotations

import hashlib
from typing import Any

TOPICS = ("pool_type", "pool_security", "pool_has_diving_board_or_slide", "above_ground_pool_ladder",
          "is_gated_community")

POSITIVE = {
    "pool_type": lambda v: v in ("Inground", "Above Ground"),
    "pool_security": lambda v: v == "Fenced",
    "pool_has_diving_board_or_slide": lambda v: v is True,
    "above_ground_pool_ladder": lambda v: v is True,
    "is_gated_community": lambda v: v is True,
}

EVIDENCE = {
    "pool_type": {
        "Inground": ["Satellite imagery shows an in-ground swimming pool in the rear yard.",
                     "Zillow listing photos include a backyard swimming pool and patio."],
        "Above Ground": ["Satellite imagery shows a round above-ground pool in the backyard.",
                         "Zillow listing photo shows an above-ground pool with a wooden deck."]},
    "pool_security": {
        "Fenced": ["Satellite imagery shows a fenced perimeter enclosing the pool area.",
                   "Zillow listing photo shows a metal fence with a gate around the pool."]},
    "pool_has_diving_board_or_slide": {
        True: ["Zillow listing photo shows a diving board at the deep end of the pool.",
               "Satellite imagery shows a slide structure beside the pool."]},
    "above_ground_pool_ladder": {
        True: ["Zillow listing photo shows an above-ground pool with a pull-up ladder and locking gate."]},
    "is_gated_community": {
        True: ["Zillow neighborhood details: the property is inside a gated community with controlled entry."]},
}
NOTHING = {
    "pool_type": ["No swimming pool visible in satellite imagery.", "Zillow listing and photos do not mention a pool."],
    "pool_security": ["No perimeter fence or safety cover visible around the pool in imagery or listing photos."],
    "pool_has_diving_board_or_slide": ["No diving board or slide visible in imagery or listing photos."],
    "above_ground_pool_ladder": ["No pull-up or locking ladder visible in imagery or listing photos."],
    "is_gated_community": ["No gated entrance visible; the lot is not marked as a multi-acre property."],
}
AMBIGUOUS = {
    "pool_type": ["Imagery shows a blue rectangular area in the backyard; it could be a pool or a tarp."],
    "pool_security": ["Imagery resolution is too low to tell whether the pool area is fenced."],
    "pool_has_diving_board_or_slide": ["A structure beside the water could be a slide or a pool feature; unclear."],
    "above_ground_pool_ladder": ["A ladder is partly visible but its type cannot be determined."],
    "is_gated_community": ["A barrier is visible at the street entrance; unclear whether it is a gate."],
}
SOURCES = ["Google Maps satellite (simulated)", "Zillow listing (simulated)"]


def rand(seed: int, *key: str) -> float:
    h = hashlib.sha256("|".join([str(seed), *key]).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def pick(options: list[str], seed: int, *key: str) -> str:
    return options[int(rand(seed, *key) * len(options))]


def listing_rows(lead_id: str, truth: dict[str, Any], seed: int = 0) -> list[dict[str, Any]]:
    """One row per topic: status found | not_found plus evidence text, derived from ground truth.

    A feature that exists is `found`; absence reads as 'nothing seen' (`not_found`), which the
    playbook says to treat as no. Pool details cannot exist without a pool."""
    rows = []
    for topic in TOPICS:
        v = truth.get(topic)
        if topic != "pool_type" and topic != "is_gated_community" and truth.get("pool_type") == "None":
            v = None
        if POSITIVE[topic](v):
            rows.append({"topic": topic, "status": "found",
                         "evidence": [pick(EVIDENCE[topic][v], seed, lead_id, topic)]})
        else:
            rows.append({"topic": topic, "status": "not_found",
                         "evidence": [pick(NOTHING[topic], seed, lead_id, topic)]})
    return rows
