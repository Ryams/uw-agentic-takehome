"""Eval cases: a public lead + the answer key (ground truth, perturbations, tags) + scenario settings (D17/D18).

Only evals (and the reply simulator) may hold ground truth; the workflow under test never sees an EvalCase."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

PUBLIC_KEYS = ("lead_id", "received_at", "source", "fields")


@dataclass
class EvalCase:
    lead: dict[str, Any]                                   # candidate-facing envelope
    truth: dict[str, Any]                                  # clean_fields: the lead with nothing missing/conflicting
    tier: str = "fixed"
    archetypes: list[str] = field(default_factory=list)
    perturbations: list[dict[str, Any]] = field(default_factory=list)
    tags: dict[str, list[str]] = field(default_factory=dict)       # explicit slice tags (fixed sets)
    conflict_injected: bool = False
    vendor_overrides: list[dict[str, str]] = field(default_factory=list)   # {vendor, key, behavior}
    reply_mode: str = "complete"                           # first-round reply: complete | partial | none
    expect: Optional[dict[str, Any]] = None                # frozen expectation (fixed sets)
    case_id: str = ""

    @property
    def lead_id(self) -> str:
        return self.lead["lead_id"]


def public(lead: dict[str, Any]) -> dict[str, Any]:
    return {k: lead[k] for k in PUBLIC_KEYS}


def case_from_generated(lead: dict[str, Any]) -> EvalCase:
    """From `generator.generate_lead` output (has `debug`)."""
    d = lead["debug"]
    return EvalCase(public(lead), d["clean_fields"], d["difficulty"], d["injected_archetypes"], d["perturbations"],
                    conflict_injected=any(p["kind"] == "conflict" for p in d["perturbations"]), case_id=lead["lead_id"])


def case_from_debug(lead: dict[str, Any], debug: dict[str, Any]) -> EvalCase:
    """From leadgen's public lead + `/leads/{id}/debug` (live harness)."""
    return EvalCase(public(lead), debug["clean_fields"], debug["difficulty"], debug["injected_archetypes"],
                    debug["perturbations"], conflict_injected=any(p["kind"] == "conflict" for p in debug["perturbations"]),
                    case_id=lead["lead_id"])
