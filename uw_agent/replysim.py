"""Producer reply simulator (eval/demo only; one of the few modules allowed to read ground truth, D5/D19).

For each outbound email still unanswered, it answers each numbered question from the lead's ground truth
(conditional questions only when their condition holds in truth, else "N/A") and posts the reply to the
mailbox as an inbound email. It uses the ask numbering the agent stored in the outbound email's metadata
(a harness convenience; the agent parses the reply TEXT).

Modes: complete (answer everything) | partial (leave the last unconditional question unanswered)."""

from __future__ import annotations

from typing import Any

from uw_agent.mailbox import Mailbox
from uw_agent.normalize import normalize_lead
from uw_agent.protocols.expr import parse
from uw_agent.truth import TruthStore

REPLY_FROM = "producer@broker.example"


def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return str(v)


def simulate_replies(mailbox: Mailbox, truth: TruthStore, lead_ids: list[str], mode: str = "complete") -> int:
    sent = 0
    for lead_id in lead_ids:
        emails = mailbox.list_for_lead(lead_id)
        answered = {(e.get("metadata") or {}).get("in_reply_to") for e in emails
                    if (e.get("metadata") or {}).get("direction") == "inbound"}
        t = normalize_lead(truth.get(lead_id)).values
        for e in emails:
            md = e.get("metadata") or {}
            if md.get("direction") != "outbound" or e["id"] in answered:
                continue
            asks = md["asks"]
            skip = max((a["n"] for a in asks if a["group_id"] == 0), default=None) if mode == "partial" else None
            lines = ["Hi,", "", "Thanks for reaching out. Answers below:", ""]
            for a in asks:
                relevant = all(parse(w).evaluate(t) is True for w in a["whens"])
                lines.append(f"{a['n']}. " + ("N/A" if not relevant else "" if a["n"] == skip else _fmt(t.get(a["field"]))))
            lines += ["", "Best,", "Producer"]
            mailbox.send(lead_id, e["from"], f"Re: {e['subject']}", "\n".join(lines),
                         {"direction": "inbound", "in_reply_to": e["id"], "simulated": True, "mode": mode},
                         sender=REPLY_FROM)
            sent += 1
    return sent
