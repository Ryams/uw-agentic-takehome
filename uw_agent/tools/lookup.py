"""Imagery / listing lookup (the playbook's 'check Google Maps and Zillow'): thin client of the mock
vendors service. Returns evidence TEXT for the interpreter."""

from __future__ import annotations

from typing import Optional

import httpx

from uw_agent.config import get_settings
from uw_agent.tools.base import LookupResult


def lookup_topic(lead_id: str, topic: str, tool: str = "maps_zillow", client: Optional[httpx.Client] = None,
                 base_url: Optional[str] = None) -> LookupResult:
    c = client or httpx.Client(timeout=10)
    url = (base_url or get_settings().vendors_url) + f"/listings/{lead_id}"
    try:
        r = c.get(url, params={"topic": topic})
    except httpx.HTTPError:
        return LookupResult(tool, topic, "unavailable")
    if r.status_code == 404:
        return LookupResult(tool, topic, "not_found")
    if r.status_code >= 500:
        return LookupResult(tool, topic, "unavailable")
    r.raise_for_status()
    j = r.json()
    return LookupResult(tool, topic, j["status"], list(j["evidence"]), list(j["sources"]))
