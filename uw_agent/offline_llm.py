"""Offline stand-in for the LLM (no API key): rule-based evidence interpretation only.

For demos/tests when no key is available. The composer and summarizer raise LLMError so they use their
deterministic fallbacks (template email, fallback summary). NOT a quality baseline for the real model:
the rules only know the mock vendors' evidence phrasing."""

from __future__ import annotations

import re
from typing import Any, Optional

from uw_agent.llm import CallRecord, LLMError


def _interpret(field: str, ev: str) -> tuple[str, str]:
    e = ev.lower()
    rules = {
        "pool_type": [("above-ground", "Above Ground"), ("in-ground", "Inground"), ("swimming pool", "Inground")],
        "pool_security": [("fenced perimeter", "Fenced"), ("metal fence", "Fenced")],
        "pool_has_diving_board_or_slide": [("diving board", "true"), ("slide structure", "true")],
        "above_ground_pool_ladder": [("pull-up ladder", "true")],
        "is_gated_community": [("gated community", "true")],
    }
    if any(w in e for w in ("could be", "too low", "unclear", "cannot be determined", "partly visible")):
        return "unclear", ""
    for needle, value in rules.get(field, []):
        if needle in e and not re.search(r"\bno\b.*" + re.escape(needle), e):
            return "value", value
    return "nothing_seen", ""


class OfflineLLM:
    def __init__(self) -> None:
        self.calls: list[CallRecord] = []
        self.last_call: Optional[CallRecord] = None

    def structured(self, *, task: str, system: str, user: str, schema: Any, effort: str = "low", max_tokens: int = 2000):
        if task == "interpreter":
            field = re.search(r"Field: (\w+)", user).group(1)
            ev = user.split("Evidence:")[1].split("Sources:")[0]
            det, val = _interpret(field, ev)
            self.last_call = CallRecord(task, "offline-rules", effort)
            self.calls.append(self.last_call)
            return schema(determination=det, value=val, confidence="high" if det == "value" else "low",
                          rationale="offline rule match on evidence text")
        raise LLMError(f"offline mode: no model for task {task!r} (deterministic fallback used)")

    def runtime_config(self) -> dict[str, Any]:
        return {"offline": True, "models": {"interpreter": "offline-rules"}}
