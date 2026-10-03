"""Control of the local harness fixtures (leadgen, mailbox, vendors): clean slate for a run."""

from __future__ import annotations

from typing import Any, Optional

import httpx


def reset_world(leadgen_url: str, mailbox_url: str, seed: Optional[int] = None, count: int = 10,
                difficulty: str = "mixed", client: Optional[httpx.Client] = None) -> dict[str, Any]:
    """Clear the mailbox and regenerate the queue (leadgen also rewrites the vendor tables)."""
    c = client or httpx.Client(timeout=30)
    c.post(f"{mailbox_url}/reset").raise_for_status()
    params: dict[str, Any] = {"count": count, "difficulty": difficulty}
    if seed is not None:
        params["seed"] = seed
    r = c.post(f"{leadgen_url}/queue", params=params)
    r.raise_for_status()
    return r.json()
