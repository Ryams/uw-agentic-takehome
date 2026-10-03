"""Reply parsing (LLM edge #4, D21): turns the producer's reply text into validated field values.

Deterministic first pass: numbered lines ("3. Yes") matched to the questions we numbered in the email.
LLM second pass only for answers the first pass could not read (free-text replies). Every value is
validated/coerced against the registry or resolution map; nothing unvalidated is ever stored."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel

import uw_agent.config  # noqa: F401
from shared import registry
from uw_agent import resolution
from uw_agent.llm import LLMError, StructuredLLM

PROMPT = (Path(__file__).parent / "prompts" / "reply_parser.md").read_text()
NA = {"n/a", "na", "not applicable", "-", "--", "skip"}
_LINE = re.compile(r"^\s*(\d+)\s*[.)]\s*(.*?)\s*$")


class ParsedAnswer(BaseModel):
    field: str
    value: str
    confidence: Literal["high", "medium", "low"]


class ReplyExtraction(BaseModel):
    answers: list[ParsedAnswer]


@dataclass
class ParsedReply:
    answers: dict[str, Any] = field(default_factory=dict)
    not_applicable: list[str] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)
    used_llm: bool = False


def _meta(name: str) -> dict[str, Any]:
    return registry.fields().get(name) or resolution.load_map()["fields"][name]


def coerce_answer(name: str, text: str) -> tuple[str, Any]:
    """('value', v) | ('na', None) | ('unparsed', None)."""
    t = text.strip().strip(".")
    if t.lower() in NA:
        return "na", None
    typ = _meta(name)["type"]
    kind = typ["kind"]
    if kind == "select":
        opts = [str(o) for o in typ.get("options", [])]
        for o in opts:
            if o.lower() == t.lower():
                return "value", o
        hits = [o for o in opts if re.search(rf"\b{re.escape(o.lower())}\b", t.lower())]
        hits = [h for h in hits if not any(h != o and h in o for o in hits)]   # prefer the longest match
        return ("value", hits[0]) if len(hits) == 1 else ("unparsed", None)
    if kind == "toggle":
        low = t.lower()
        if re.match(r"^(yes|y|true)\b", low):
            return "value", True
        if re.match(r"^(no|n|false)\b", low):
            return "value", False
        return "unparsed", None
    if kind in ("integer", "decimal"):
        m = re.search(r"-?\d[\d,]*\.?\d*", t)
        if not m:
            return "unparsed", None
        num = float(m.group().replace(",", ""))
        return ("value", int(num)) if kind == "integer" and num == int(num) else (("value", num) if kind == "decimal" else ("unparsed", None))
    if kind == "date":
        m = re.search(r"\d{4}-\d{2}-\d{2}", t)
        return ("value", m.group()) if m else ("unparsed", None)
    return ("value", t) if t else ("unparsed", None)


def parse_reply(llm: Optional[StructuredLLM], asks: list[dict[str, Any]], body: str) -> ParsedReply:
    """`asks` = numbered_asks(plan) saved with the sent email: [{n, field, group_id, whens}]."""
    out = ParsedReply()
    by_n = {a["n"]: a["field"] for a in asks}
    seen: dict[str, str] = {}
    for line in body.splitlines():
        m = _LINE.match(line)
        if m and int(m.group(1)) in by_n:
            seen[by_n[int(m.group(1))]] = m.group(2)
    leftover: list[str] = []
    for a in asks:
        f = a["field"]
        if f not in seen:
            leftover.append(f)
            continue
        status, v = coerce_answer(f, seen[f])
        if status == "value":
            out.answers[f] = v
        elif status == "na":
            out.not_applicable.append(f)
        else:
            leftover.append(f)
    if leftover and llm is not None:
        qs = []
        for f in leftover:
            m = _meta(f)
            opts = m["type"].get("options") if m["type"]["kind"] == "select" else None
            qs.append(f"- field={f} | label: {m.get('label', f)} | type: {m['type']['kind']}" + (f" | options: {opts}" if opts else ""))
        user = "Questions asked:\n" + "\n".join(qs) + "\n\nReply text:\n" + body
        try:
            r = llm.structured(task="reply_parser", system=PROMPT, user=user, schema=ReplyExtraction, effort="low",
                               max_tokens=800)
            out.used_llm = True
            for pa in r.answers:
                if pa.field in leftover and pa.confidence != "low":
                    status, v = coerce_answer(pa.field, pa.value)
                    if status == "value":
                        out.answers[pa.field] = v
        except LLMError:
            pass
    out.unanswered = [f for f in leftover if f not in out.answers and f not in out.not_applicable]
    return out
