"""Per-lead reasoning summary for the underwriter UI (LLM edge #3).

Input is a deterministic report (facts only); the model paraphrases it. Falls back to a
deterministic summary on refusal/error. The model must not add facts: the report is the only source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from uw_agent.llm import LLMError, StructuredLLM

PROMPT = (Path(__file__).parent / "prompts" / "summarizer.md").read_text()


class Summary(BaseModel):
    headline: str
    rationale: list[str]
    uncertainties: list[str]
    suggested_action: str


def fallback_summary(report: dict[str, Any]) -> Summary:
    """Deterministic summary from the report (no model)."""
    rationale = [f"{p['protocol']}: {p.get('outcome') or p['status']}" for p in report.get("protocols", [])][:4]
    unc = [f"assumed {a['field']} = {a['value']} ({a.get('why', 'assumption')})" for a in report.get("assumptions", [])]
    unc += [f"conflict: {c['message']}" for c in report.get("conflicts", [])]
    action = {"ready_to_quote": "Review and approve the quote.", "awaiting_reply": "Wait for the producer's reply.",
              "needs_uw": "Your decision is needed."}.get(report.get("state", ""), "Review this lead.")
    return Summary(headline=f"{report.get('state', 'unknown').replace('_', ' ')}: {report.get('decision') or 'pending'}",
                   rationale=rationale, uncertainties=unc, suggested_action=action)


def summarize(llm: StructuredLLM, report: dict[str, Any]) -> tuple[Summary, bool]:
    """Returns (summary, used_llm)."""
    try:
        s = llm.structured(task="summarizer", system=PROMPT, user=json.dumps(report, indent=1, default=str),
                           schema=Summary, effort="low", max_tokens=900)
        if not s.headline.strip() or not s.rationale:
            return fallback_summary(report), False
        return s, True
    except LLMError:
        return fallback_summary(report), False
