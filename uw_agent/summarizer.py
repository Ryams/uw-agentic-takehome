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


def _name(protocol: str) -> str:
    return protocol.replace("_", " ")


def _rationale(report: dict[str, Any]) -> list[str]:
    """Plain statements that separate what already passes from what is still outstanding (never truncated)."""
    passing, conditions, waiting, not_applicable = [], [], [], []
    for p in report.get("protocols", []):
        if p["status"] == "not_applicable":
            not_applicable.append(_name(p["protocol"]))
        elif p["status"] == "blocked":
            waiting.append(p)
        elif p.get("decision") == "quote":
            passing.append(_name(p["protocol"]))
        elif p.get("decision") in ("quote_with_conditions", "decline", "escalate"):
            conditions.append(f"{_name(p['protocol'])} ({p.get('outcome', '').lower().replace('_', ' ')})")
    out = []
    if passing:
        out.append("Pass with the data so far: " + ", ".join(passing) + ".")
    if conditions:
        out.append("Pass with a condition or need attention: " + "; ".join(conditions) + ".")
    asks = report.get("asks", [])
    if waiting or asks:
        why = {}
        for a in asks:
            for proto in a.get("needed_for", []):
                why.setdefault(_name(proto), []).append(a["label"].rstrip("?"))
        if waiting:
            out.append("Still waiting on the producer for: " + "; ".join(
                f"{_name(p['protocol'])} (needs {', '.join(why.get(_name(p['protocol']), p.get('blocked_on', [])))})"
                for p in waiting) + ".")
        other = [a["label"].rstrip("?") for a in asks if not a.get("needed_for")]
        if other:
            out.append("Also required to quote: " + ", ".join(other) + ".")
    if not_applicable:
        out.append("Not applicable: " + ", ".join(not_applicable) + ".")
    return out or ["No playbook check has applied yet."]


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
    rationale = _rationale(report)
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
