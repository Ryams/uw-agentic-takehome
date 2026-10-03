"""Ground truth access. ONLY the reply simulator and the evals may import this module (D5/D19);
the workflow gets data through the mock vendors service. Loads `clean_fields` from the LOCAL
leadgen fixture (needs DEBUG=true)."""

from __future__ import annotations

from typing import Any, Optional

import httpx


class TruthStore:
    def __init__(self, truth: dict[str, dict[str, Any]]):
        self._truth = truth

    def get(self, lead_id: str) -> dict[str, Any]:
        return self._truth[lead_id]

    @classmethod
    def from_leadgen(cls, leadgen_url: str, lead_ids: list[str], client: Optional[httpx.Client] = None) -> "TruthStore":
        c = client or httpx.Client(timeout=10)
        truth = {}
        for lid in lead_ids:
            r = c.get(f"{leadgen_url}/leads/{lid}/debug")
            if r.status_code == 403:
                raise RuntimeError("leadgen answer key is disabled; start it with DEBUG=true (`make up`)")
            r.raise_for_status()
            truth[lid] = r.json()["clean_fields"]
        return cls(truth)
