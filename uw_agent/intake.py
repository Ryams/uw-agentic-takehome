"""Ingest the morning queue from the (local) lead generator's public API. No ground truth here."""

from __future__ import annotations

from typing import Any, Optional

import httpx


def list_leads(leadgen_url: str, client: Optional[httpx.Client] = None) -> list[dict[str, Any]]:
    c = client or httpx.Client(timeout=10)
    r = c.get(f"{leadgen_url}/leads")
    r.raise_for_status()
    return r.json()


def get_lead(leadgen_url: str, lead_id: str, client: Optional[httpx.Client] = None) -> dict[str, Any]:
    c = client or httpx.Client(timeout=10)
    r = c.get(f"{leadgen_url}/leads/{lead_id}")
    r.raise_for_status()
    return r.json()
