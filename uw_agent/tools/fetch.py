"""System-owned field fetch: thin client of the mock vendors service, routed by field_resolution.json."""

from __future__ import annotations

from typing import Optional

import httpx

from uw_agent import resolution
from uw_agent.config import get_settings
from uw_agent.tools.base import ToolResult

# tool -> (URL path template, {field: key in the vendor response}, display source)
TOOLS: dict[str, tuple[str, dict[str, str], str]] = {
    "crm_account": ("/crm/accounts/{lead_id}",
                    {"broker_tier": "broker_tier", "has_primary_policy_with_stand": "has_primary_policy_with_stand"},
                    "Stand CRM (mock)"),
    "kyc_provider": ("/kyc/scores/{lead_id}", {"kyc_score": "score"}, "KYC provider (mock)"),
    "rce_provider": ("/rce/estimates/{lead_id}", {"replacement_cost": "replacement_cost"},
                     "Replacement-cost estimator (mock)"),
    "ppc_lookup": ("/ppc/{lead_id}", {"protection_class": "ppc"}, "ISO PPC lookup (mock)"),
    "geo_risk": ("/geo/risk/{lead_id}",
                 {f: f for f in ("road_access", "min_distance_to_neighbor_ft", "slope_angle_deg", "p_f",
                                 "vegetation_clearance")},
                 "Geo/fire-risk model (mock)"),
}


def tool_for_field(field: str) -> Optional[str]:
    for step in resolution.load_map()["fields"].get(field, {}).get("on_missing", []):
        if step["action"] == "fetch":
            return step["tool"]
    return None


def fetch_field(lead_id: str, field: str, tool: Optional[str] = None, client: Optional[httpx.Client] = None,
                base_url: Optional[str] = None) -> ToolResult:
    tool = tool or tool_for_field(field)
    if tool not in TOOLS:
        raise KeyError(f"no fetch tool for field {field!r}")
    path, keys, source = TOOLS[tool]
    c = client or httpx.Client(timeout=10)
    url = (base_url or get_settings().vendors_url) + path.format(lead_id=lead_id)
    try:
        r = c.get(url)
    except httpx.HTTPError as e:
        return ToolResult(tool, field, "unavailable", None, source, str(e))
    if r.status_code == 404:
        return ToolResult(tool, field, "not_found", None, source, "vendor has no record")
    if r.status_code >= 500:
        return ToolResult(tool, field, "unavailable", None, source, r.text[:200])
    r.raise_for_status()
    value = r.json().get(keys[field])
    if value is None:
        return ToolResult(tool, field, "not_found", None, source, "vendor has no value")
    return ToolResult(tool, field, "found", value, source)
