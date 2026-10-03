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


REASON_TEXT = {"conflict": "data conflict to verify", "decline": "proposed decline", "escalate": "protocol escalation",
               "unresolved_system_data": "system data unavailable", "blocked_no_source": "blocked, no data source",
               "producer_not_applicable": "producer said N/A on a needed value", "too_many_emails": "too many follow-ups",
               "email_draft": "email draft to review", "internal_error": "internal error"}


def fallback_summary(report: dict[str, Any]) -> Summary:
    """Deterministic summary from the report (no model)."""
    state, n_asks = report.get("state", ""), len(report.get("asks", []))
    reasons = [REASON_TEXT.get(r["type"], r["type"]) for r in report.get("reasons", [])]
    if state == "ready_to_quote":
        headline = "Ready to quote" + (" with conditions" if report.get("conditions") else "")
    elif state == "awaiting_reply":
        headline = f"Waiting on the producer: {n_asks} question{'s' if n_asks != 1 else ''} sent"
    elif state == "needs_uw":
        headline = "Needs your decision: " + (reasons[0] if reasons else "review required")
    else:
        headline = "Review this lead"
    rationale = []
    for p in report.get("protocols", []):
        if p.get("outcome"):
            rationale.append(f"{p['protocol']}: {p['outcome']}")
        elif p.get("status") == "blocked":
            rationale.append(f"{p['protocol']}: waiting on {', '.join(p.get('blocked_on', []))}")
    rationale = rationale[:4] or ["no protocol applied yet"]
    unc = [f"assumed {a['field']} = {a['value']} ({a.get('why', 'assumption')})" for a in report.get("assumptions", [])]
    unc += [f"conflict: {c['message']}" for c in report.get("conflicts", [])]
    action = {"ready_to_quote": "Review and approve the quote.", "awaiting_reply": "Wait for the producer's reply.",
              "needs_uw": "Your decision is needed."}.get(state, "Review this lead.")
    return Summary(headline=headline, rationale=rationale, uncertainties=unc, suggested_action=action)


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
