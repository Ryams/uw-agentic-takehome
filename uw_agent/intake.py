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


class HttpLeadSource:
    """Production lead source: the local leadgen public API."""

    def __init__(self, leadgen_url: str, client: Optional[httpx.Client] = None):
        self.url, self.client = leadgen_url, client

    def list_leads(self) -> list[dict[str, Any]]:
        return list_leads(self.url, self.client)

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        return get_lead(self.url, lead_id, self.client)


class DictLeadSource:
    """In-memory lead source (tests / fixed eval sets)."""

    def __init__(self, leads: list[dict[str, Any]]):
        self._leads = {ld["lead_id"]: ld for ld in leads}

    def list_leads(self) -> list[dict[str, Any]]:
        return [{"lead_id": k} for k in self._leads]

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        return self._leads[lead_id]
