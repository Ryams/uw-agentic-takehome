"""Email composer (LLM edge #2): writes the ONE follow-up email for a lead.

Deterministic code decides WHAT to ask (EmailPlan: unconditional asks + conditional groups, D13).
The model only words the questions. The reply is a set of per-question texts that code assembles
into the body and validates against the plan (every ask exactly once, none added), so the email
asks for exactly the right things. On refusal, error, or invalid output after one retry we fall
back to a deterministic template (also the eval baseline).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

import uw_agent.config  # noqa: F401
from shared import registry
from uw_agent import resolution
from uw_agent.llm import LLMError, StructuredLLM
from uw_agent.protocols.expr import parse

PROMPT = (Path(__file__).parent / "prompts" / "composer.md").read_text()
SIGNOFF = "Thanks,\nStand Underwriting"


@dataclass
class Ask:
    field: str
    label: str
    kind: str                         # select | toggle | integer | decimal | text | date ...
    options: list[Any] = field(default_factory=list)


@dataclass
class CondGroup:
    id: int
    chain: list[dict[str, str]]       # [{node, branch, when}] conditions that must hold
    asks: list[Ask] = field(default_factory=list)

    @property
    def hint(self) -> str:
        return describe_chain(self.chain)


@dataclass
class EmailPlan:
    lead_id: str
    address: str
    to: str
    asks: list[Ask] = field(default_factory=list)          # unconditional (group_id 0)
    groups: list[CondGroup] = field(default_factory=list)  # conditional (group_id >= 1)

    def pairs(self) -> set[tuple[str, int]]:
        return {(a.field, 0) for a in self.asks} | {(a.field, g.id) for g in self.groups for a in g.asks}


@dataclass
class Email:
    lead_id: str
    to: str
    subject: str
    body: str
    used_llm: bool = False
    fallback_reason: Optional[str] = None


class ComposedQuestion(BaseModel):
    field: str
    group_id: int
    question: str


class GroupLeadIn(BaseModel):
    group_id: int
    lead_in: str


class ComposedEmail(BaseModel):
    subject: str
    greeting: str
    intro: str
    questions: list[ComposedQuestion]
    group_lead_ins: list[GroupLeadIn]
    closing: str


def ask_for(name: str) -> Ask:
    meta = registry.fields().get(name) or resolution.load_map()["fields"][name]
    typ = meta["type"]
    opts = list(typ.get("options", [])) if typ["kind"] == "select" else []
    return Ask(name, meta.get("label", name), typ["kind"], opts)


def _label(name: str) -> str:
    return (registry.fields().get(name) or resolution.load_map()["fields"].get(name, {})).get("label", name)


def describe_when(src: str) -> str:
    """Plain-English-ish reading of a simple condition, e.g. `pool_security == "Fenced"` -> 'Pool Security is Fenced'."""
    parts = [f"{_label(f)} {'is' if op in ('==', 'in') else 'is not' if op == '!=' else op} {lit}"
             for f, op, lit in parse(src).literals()]
    return " and ".join(parts) if parts else src


def describe_chain(chain: list[dict[str, str]]) -> str:
    return "; ".join(describe_when(c["when"]) for c in chain)


def _answer_hint(a: Ask) -> str:
    if a.kind == "select" and a.options:
        return " (choose one: " + " / ".join(str(o) for o in a.options) + ")"
    if a.kind == "toggle":
        return " (yes / no)"
    return ""


def assemble(plan: EmailPlan, c: ComposedEmail) -> Email:
    q = {(x.field, x.group_id): x.question.strip() for x in c.questions}
    lead = {g.group_id: g.lead_in.strip().rstrip(":") for g in c.group_lead_ins}
    lines = [c.greeting.strip(), "", c.intro.strip(), ""]
    n = 0
    for a in plan.asks:
        n += 1
        lines.append(f"{n}. {q[(a.field, 0)]}{_answer_hint(a)}")
    for g in plan.groups:
        lines += ["", f"{lead[g.id]}:"]
        for a in g.asks:
            n += 1
            lines.append(f"   {n}. {q[(a.field, g.id)]}{_answer_hint(a)}")
    lines += ["", c.closing.strip(), "", SIGNOFF]
    return Email(plan.lead_id, plan.to, c.subject.strip(), "\n".join(lines).strip() + "\n", used_llm=True)


def template_email(plan: EmailPlan, reason: Optional[str] = None) -> Email:
    """Deterministic email: field labels as questions. Always valid; the baseline the LLM must beat."""
    c = ComposedEmail(
        subject=f"Information needed to quote {plan.address} ({plan.lead_id})",
        greeting="Hello,",
        intro=f"To finish quoting {plan.address}, we need the following information:",
        questions=[ComposedQuestion(field=a.field, group_id=0, question=f"{a.label}?") for a in plan.asks]
        + [ComposedQuestion(field=a.field, group_id=g.id, question=f"{a.label}?") for g in plan.groups for a in g.asks],
        group_lead_ins=[GroupLeadIn(group_id=g.id, lead_in=f"If {g.hint}") for g in plan.groups],
        closing="A single reply covering everything is ideal. Thank you.",
    )
    e = assemble(plan, c)
    e.used_llm, e.fallback_reason = False, reason
    return e


def _validate(plan: EmailPlan, c: ComposedEmail) -> Optional[str]:
    got = [(x.field, x.group_id) for x in c.questions]
    want = plan.pairs()
    if len(got) != len(set(got)):
        return "duplicate questions"
    if set(got) != want:
        return f"questions must cover exactly the given asks; missing={sorted(want - set(got))} extra={sorted(set(got) - want)}"
    if any(not x.question.strip() for x in c.questions):
        return "empty question text"
    if sorted(g.group_id for g in c.group_lead_ins) != sorted(g.id for g in plan.groups):
        return "group_lead_ins must have exactly one entry per conditional group"
    if any(not g.lead_in.strip() for g in c.group_lead_ins) or not c.subject.strip():
        return "empty subject or lead-in"
    return None


def _user_message(plan: EmailPlan) -> str:
    out = [f"Property: {plan.address} (lead {plan.lead_id})", "", "Questions to ask (group_id 0 = unconditional):"]
    for a in plan.asks:
        out.append(f"- field={a.field} group_id=0 | label: {a.label} | type: {a.kind}"
                   + (f" | options: {a.options}" if a.options else ""))
    for g in plan.groups:
        out += ["", f"Conditional group_id={g.id}; applies only if: {g.hint}",
                "  condition chain: " + " -> ".join(f"{c['branch']} [{c['when']}]" for c in g.chain)]
        for a in g.asks:
            out.append(f"- field={a.field} group_id={g.id} | label: {a.label} | type: {a.kind}"
                       + (f" | options: {a.options}" if a.options else ""))
    return "\n".join(out)


def compose_email(llm: StructuredLLM, plan: EmailPlan) -> Email:
    if not plan.pairs():
        raise ValueError("nothing to ask: do not send an email")
    user, problem = _user_message(plan), None
    for attempt in range(2):
        msg = user if problem is None else f"{user}\n\nYour previous reply was rejected: {problem}. Fix it."
        try:
            c = llm.structured(task="composer", system=PROMPT, user=msg, schema=ComposedEmail, effort="low",
                               max_tokens=2500)
        except LLMError as e:
            return template_email(plan, f"llm error: {e}")
        problem = _validate(plan, c)
        if problem is None:
            return assemble(plan, c)
    return template_email(plan, f"invalid composition after retry: {problem}")
