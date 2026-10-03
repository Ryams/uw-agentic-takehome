"""Pydantic models shared across services: the lead envelope and email records.

The lead envelope mirrors lead_payload_example.json exactly:
    { lead_id, received_at, source, fields: { <field_name>: value | null } }
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# --- leadgen --------------------------------------------------------------


class Lead(BaseModel):
    """Candidate-facing lead envelope. `fields` holds registry-shaped values."""

    lead_id: str
    received_at: str
    source: str
    fields: dict[str, Any]


class LeadSummary(BaseModel):
    lead_id: str
    source: str
    received_at: str
    missing_field_count: int


class Perturbation(BaseModel):
    field: str
    kind: str  # e.g. missing_required | missing_system_owned | conflict
    detail: Optional[str] = None


class LeadDebug(BaseModel):
    """Interviewer-only answer key (gated behind DEBUG=true)."""

    lead_id: str
    difficulty: str
    injected_archetypes: list[str]
    perturbations: list[Perturbation]


class QueueResponse(BaseModel):
    seed: int
    count: int
    difficulty: str
    lead_ids: list[str]


# --- mailbox --------------------------------------------------------------


class EmailIn(BaseModel):
    """An outbound follow-up email the candidate's agent 'sends'."""

    lead_id: str
    to: str
    from_: str = Field(alias="from")
    subject: str
    body: str
    metadata: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class EmailSummary(BaseModel):
    id: int
    lead_id: str
    to: str
    subject: str
    received_at: str


class EmailRecord(BaseModel):
    id: int
    lead_id: str
    to: str
    from_: str = Field(serialization_alias="from")
    subject: str
    body: str
    metadata: Optional[dict[str, Any]] = None
    received_at: str

    model_config = {"populate_by_name": True}
