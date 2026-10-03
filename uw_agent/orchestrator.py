"""Queue orchestration (D4, D11-D13, D19-D21): the per-lead pipeline

    normalize -> [analyze -> resolve (fetch / lookup / assume) -> evaluate protocols]* -> decide -> email -> persist

`process_lead` is idempotent: it re-evaluates from the raw lead plus the answers received so far, so a reply
simply re-triggers it. States: ready_to_quote | awaiting_reply | needs_uw. Plain Python plus SQLite; the model
only reads evidence, parses replies and words emails. Everything that decides is deterministic.
"""

from __future__ import annotations

import hashlib
import json
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

import uw_agent.config  # noqa: F401
from shared import registry
from uw_agent import composer, resolution, summarizer, versioning
from uw_agent.composer import Ask, CondGroup, EmailPlan, ask_for, compose_email, numbered_asks
from uw_agent.config import Settings, get_settings
from uw_agent.db import Database
from uw_agent.executor import FieldResolution, ToolKit, resolve_field
from uw_agent.llm import StructuredLLM
from uw_agent.mailbox import Mailbox
from uw_agent.normalize import normalize_lead
from uw_agent.protocols import engine
from uw_agent.protocols.expr import parse
from uw_agent.replies import parse_reply

READY, AWAITING, NEEDS_UW = "ready_to_quote", "awaiting_reply", "needs_uw"
PRIORITY = {"quick_win": 0, "ready": 1, "decline": 2, "uw_decision": 3, "system": 4, "awaiting": 5}


class TaggedLLM:
    """Per-lead view of the shared LLM: records only this lead's calls (safe under parallel workers)."""

    def __init__(self, inner: StructuredLLM):
        self.inner, self.calls = inner, []

    def structured(self, **kw):
        try:
            return self.inner.structured(**kw)
        finally:
            rec = getattr(self.inner, "last_call", None)
            if rec is not None:
                self.calls.append(rec)

    def runtime_config(self):
        return self.inner.runtime_config()


@dataclass
class Context:
    db: Database
    source: Any                                  # list_leads(), get_lead(id)
    mailbox: Mailbox
    tools: ToolKit
    llm: StructuredLLM
    protocols: list[engine.Protocol] = field(default_factory=engine.load_protocols)
    settings: Settings = field(default_factory=get_settings)
    auto_send: bool = True                       # False: emails are drafted for the underwriter to approve
    max_emails: int = 3                          # per lead, then escalate to the underwriter
    default_recipient: str = "producer@broker.example"
    reset: Optional[Callable[..., dict[str, Any]]] = None   # reset_world(seed=, count=, difficulty=) -> queue info


@dataclass
class LeadOutcome:
    lead_id: str
    state: str
    decision: Optional[str]
    priority: int
    round: int
    n_asks: int = 0
    email_sent: bool = False
    reasons: list[dict[str, Any]] = field(default_factory=list)


# --- helpers ---------------------------------------------------------------------------------------

def _order(fields: list[str]) -> list[str]:
    idx = {n: i for i, n in enumerate(registry.field_names())}
    return sorted(dict.fromkeys(fields), key=lambda f: (idx.get(f, 10_000), f))


def _terminal(name: str, scope: dict[str, Any]) -> Optional[str]:
    """Action that finally decides the field's source: 'ask_producer' only if nothing can be fetched/looked up first."""
    steps, _ = resolution.steps_for(name, scope)
    acts = [s["action"] for s in steps if s["action"] != "assume"]
    return acts[0] if acts else None


def _conditional_ask_ok(name: str, uncond: list[str], values: dict[str, Any], scope: dict[str, Any]) -> bool:
    """A downstream field becomes a conditional ask only if it must come from the producer (no fetch/lookup
    that could fill it once its path goes live) and is not bind-only."""
    if name in uncond or values.get(name) is not None or name not in resolution.load_map()["fields"]:
        return False
    if name in registry.field_names() and registry.required_level(name) == "bind_only":
        return False
    return _terminal(name, scope) == "ask_producer"


def _plan_hash(plan: EmailPlan) -> str:
    return hashlib.sha1(json.dumps(sorted(plan.pairs())).encode()).hexdigest()[:12]


def _plan_json(plan: EmailPlan) -> dict[str, Any]:
    return {"asks": numbered_asks(plan), "address": plan.address, "to": plan.to}


def _path(r: engine.ProtocolResult) -> list[dict[str, Any]]:
    return [asdict(s) for s in r.path]


def _build_plan(lead_id: str, address: str, to: str, uncond: list[str],
                cond: list[tuple[str, list[dict[str, str]]]]) -> EmailPlan:
    plan = EmailPlan(lead_id, address, to, asks=[ask_for(f) for f in uncond])
    groups: dict[tuple[str, ...], CondGroup] = {}
    for f, chain in cond:
        if f in uncond:
            continue                                  # needed regardless: ask once, unconditionally
        key = tuple(c["when"] for c in chain)
        g = groups.get(key)
        if g is None:
            g = groups[key] = CondGroup(len(groups) + 1, chain, [])
        if all(a.field != f for a in g.asks):
            g.asks.append(ask_for(f))
    plan.groups = list(groups.values())
    return plan


# --- the per-lead pipeline -----------------------------------------------------------------------------

def process_lead(ctx: Context, run_id: str, lead_id: str, trigger: str = "initial") -> LeadOutcome:
    llm = TaggedLLM(ctx.llm)
    try:
        return _process(ctx, run_id, lead_id, trigger, llm)
    except Exception as e:  # noqa: BLE001  one bad lead must never sink the queue
        reasons = [{"type": "internal_error", "detail": f"{type(e).__name__}: {e}"}]
        rnd = ctx.db.save_decision(run_id, lead_id, trigger, NEEDS_UW, None, PRIORITY["system"],
                                   {"lead_id": lead_id, "state": NEEDS_UW, "reasons": reasons,
                                    "traceback": traceback.format_exc()[-1500:]}, None)
        return LeadOutcome(lead_id, NEEDS_UW, None, PRIORITY["system"], rnd, reasons=reasons)
    finally:
        ctx.db.log_llm_calls(run_id, lead_id, llm.calls)


def _process(ctx: Context, run_id: str, lead_id: str, trigger: str, llm: TaggedLLM) -> LeadOutcome:
    lead = json.loads(ctx.db.lead_row(run_id, lead_id)["raw_json"])
    answers = ctx.db.answers(run_id, lead_id)
    norm = normalize_lead({**lead["fields"], **answers})
    values = dict(norm.values)
    ctxv = resolution.context_values(lead.get("received_at"))

    attempted: dict[str, FieldResolution] = {}
    evidence: list[dict[str, Any]] = []
    derived_fields = {f for f, e in resolution.load_map()["fields"].items()
                      if any(s["action"] == "derive" for s in e["on_missing"])}
    derived_seen: dict[str, dict[str, Any]] = {}         # a derived value is set on the first pass; keep its record
    for _ in range(8):                                   # resolve -> re-evaluate until nothing new is learned
        a = resolution.analyze(values, ctxv)
        values = a.values
        derived_seen.update({d["field"]: d for d in a.derived})
        ev = engine.evaluate_all(values, ctx.protocols)
        todo = [f for f in dict.fromkeys([g.field for g in a.gaps] + list(ev.blocked_on))
                if f not in derived_fields and (f not in attempted or attempted[f].outcome == "pending")]
        progressed = False
        for f in todo:
            r = resolve_field(f, values, ctxv, lead_id, ctx.tools, llm)
            attempted[f] = r
            evidence += r.log
            if r.outcome in ("resolved", "assumed"):
                values[f], progressed = r.value, True
        if not progressed:
            break
    a = resolution.analyze(values, ctxv)
    values = a.values
    derived_seen.update({d["field"]: d for d in a.derived})
    ev = engine.evaluate_all(values, ctx.protocols)

    needed = [g.field for g in a.gaps] + [f for f in ev.blocked_on if f not in derived_fields]
    needed = list(dict.fromkeys(needed))
    na = ctx.db.na_fields(run_id, lead_id)
    uncond = _order([f for f in needed if attempted.get(f) and attempted[f].outcome == "ask_producer"
                     and attempted[f].ask_when is None and values.get(f) is None and f not in na])
    unresolved = _order([f for f in needed if attempted.get(f) and attempted[f].outcome in ("unresolved", "pending")
                         and values.get(f) is None])

    # conditional asks (D13): engine paths, registry requiredWhen, and 'assume only if' fields
    scope = {**values, **ctxv}
    cond: list[tuple[str, list[dict[str, str]]]] = []
    for cb in ev.conditional_blockers:
        if _conditional_ask_ok(cb.field, uncond, values, scope):
            cond.append((cb.field, cb.only_if))
    seen_cond = {f for f, _ in cond}
    for p in a.pending:
        f = p["field"]
        meta = registry.fields().get(f, {})
        if f in seen_cond or f in uncond or not meta.get("requiredWhen") or f in derived_fields:
            continue
        if set(p["waiting_on"]) & set(uncond) and _terminal(f, scope) == "ask_producer":
            rw = resolution._required_when(f)
            cond.append((f, [{"node": "requiredWhen", "branch": f"{meta['label']} is required", "when": rw.source}]))
    for f in needed:
        r = attempted.get(f)
        if r and r.outcome == "ask_producer" and r.ask_when and values.get(f) is None:
            cond.append((f, [{"node": "assumption", "branch": "default assumption does not apply", "when": r.ask_when}]))

    address = ", ".join(str(values.get(k)) for k in ("street_address", "city", "state") if values.get(k))
    to = values.get("owner_email") or ctx.default_recipient
    cond = [(f, c) for f, c in cond if f not in na]
    plan = _build_plan(lead_id, address, to, uncond, cond)

    # --- decide -------------------------------------------------------------------------------------
    reasons: list[dict[str, Any]] = []
    declined = ev.decision == "decline" and ev.status == "decided"
    if declined:
        plan = EmailPlan(lead_id, address, to)           # a decline suppresses further asks (D11)
        reasons.append({"type": "decline", "detail": f"declined by {ev.short_circuited_by}"})
    if a.conflicts:
        reasons.append({"type": "conflict", "conflicts": a.conflicts})
    if ev.status == "decided" and ev.decision == "escalate":
        reasons.append({"type": "escalate", "detail": "a protocol routed this lead to underwriter review"})
    if unresolved:
        reasons.append({"type": "unresolved_system_data", "fields": unresolved})
    na_blocking = [f for f in ev.blocked_on if f in na and values.get(f) is None]
    if na_blocking and not declined:
        reasons.append({"type": "producer_not_applicable", "fields": na_blocking,
                        "detail": "producer answered N/A but a protocol needs a value"})
    elif ev.status == "blocked" and not plan.pairs() and not unresolved and not declined:
        reasons.append({"type": "blocked_no_source", "fields": ev.blocked_on})

    email_sent, email_status = False, None
    if plan.pairs():
        h = _plan_hash(plan)
        prior = [e for e in ctx.db.emails(run_id, lead_id, "out") if e["asks_hash"] == h and e["status"] in ("sent", "draft")]
        outs = ctx.db.emails(run_id, lead_id, "out")
        if prior:
            email_status = prior[-1]["status"]           # same ask set already out: never duplicate
        elif len(outs) >= ctx.max_emails:
            reasons.append({"type": "too_many_emails", "detail": f"{len(outs)} emails already sent; needs a human"})
        else:
            e = compose_email(llm, plan)
            meta = {"direction": "outbound", "run_id": run_id, "asks_hash": h, "asks": numbered_asks(plan)}
            if ctx.auto_send:
                mid = ctx.mailbox.send(lead_id, e.to, e.subject, e.body, meta)
                ctx.db.add_email(run_id, lead_id, "out", "sent", e.to, e.subject, e.body, mid, None, h,
                                 _plan_json(plan), e.used_llm)
                email_sent, email_status = True, "sent"
            else:
                ctx.db.add_email(run_id, lead_id, "out", "draft", e.to, e.subject, e.body, None, None, h,
                                 _plan_json(plan), e.used_llm)
                email_status = "draft"
                reasons.append({"type": "email_draft", "detail": "email drafted; approve to send"})

    # state & priority
    if email_status == "draft" or any(r["type"] != "email_draft" for r in reasons):
        state = NEEDS_UW
    elif plan.pairs():
        state = AWAITING
    else:
        state = READY
    kinds = {r["type"] for r in reasons}
    if state == NEEDS_UW:
        prio = PRIORITY["decline"] if "decline" in kinds else PRIORITY["system"] if kinds & {"unresolved_system_data", "blocked_no_source", "internal_error", "too_many_emails"} else PRIORITY["uw_decision"]
    elif state == AWAITING:
        prio = PRIORITY["awaiting"]
    else:
        prio = PRIORITY["quick_win"] if not ev.conditions else PRIORITY["ready"]
    decision = ev.decision if ev.status == "decided" else None

    needed_for: dict[str, list[str]] = {}
    pending_inputs = {p["field"]: p["waiting_on"] for p in a.pending}
    for r in ev.results:
        for f in r.blocked_on:
            # a blocked derived field (roof_classification) is really waiting on its inputs (roof_material, year)
            for root in (pending_inputs.get(f, [f]) if f in derived_fields else [f]):
                needed_for.setdefault(root, []).append(r.protocol)
        for cb in r.conditional_blockers:
            needed_for.setdefault(cb.field, []).append(cb.protocol)
    assumptions = [r.assumption for r in attempted.values() if r.assumption and values.get(r.field) is not None]
    report = {
        "lead_id": lead_id, "address": address, "state": state, "decision": decision, "trigger": trigger,
        "provisional": bool(plan.pairs()),            # asks outstanding: the decision may still change
        "reasons": reasons, "conditions": ev.conditions if ev.status == "decided" else [],
        "recommendations": ev.recommendations,
        "protocols": [{"protocol": r.protocol, "status": r.status, "outcome": r.outcome, "decision": r.decision,
                       "conditions": r.conditions, "blocked_on": r.blocked_on, "overlays": r.overlays, "path": _path(r)}
                      for r in ev.results],
        "skipped_protocols": ev.skipped, "blocked_on": ev.blocked_on,
        "assumptions": assumptions, "derived": list(derived_seen.values()), "conflicts": a.conflicts,
        "fetched": [e for e in evidence if e.get("step") == "fetch" and e.get("status") == "found"],
        "lookups": [e for e in evidence if e.get("step") == "lookup"],
        "tool_failures": [e for e in evidence if e.get("step") == "fetch" and e.get("status") != "found"],
        "provisional_decision": ev.decision,            # most restrictive among protocols decided so far
        "asks": [{"field": x.field, "label": x.label, "conditional": False,
                  "needed_for": list(dict.fromkeys(needed_for.get(x.field, [])))} for x in plan.asks]
                + [{"field": x.field, "label": x.label, "conditional": True, "if": g.hint,
                    "needed_for": list(dict.fromkeys(needed_for.get(x.field, [])))}
                   for g in plan.groups for x in g.asks],
        "deferred": a.deferred, "normalization_notes": norm.notes, "invalid_inputs": norm.invalid,
        "answers_received": answers, "email_status": email_status,
        "system_version": versioning.system_version()["system_version"],
    }
    summary, used = summarizer.summarize(llm, report)
    rnd = ctx.db.save_decision(run_id, lead_id, trigger, state, decision, prio, report,
                               {**summary.model_dump(), "used_llm": used})
    return LeadOutcome(lead_id, state, decision, prio, rnd, len(plan.pairs()), email_sent, reasons)


# --- run lifecycle -----------------------------------------------------------------------------------------

def start_run(ctx: Context, seed: Optional[int] = None, count: int = 10, difficulty: str = "mixed",
              reset: bool = True, lead_ids: Optional[list[str]] = None) -> str:
    """Clean slate (mailbox cleared, queue regenerated when `reset`), then ingest the queue."""
    if reset and ctx.reset is not None:
        info = ctx.reset(seed=seed, count=count, difficulty=difficulty)
        lead_ids, seed = info["lead_ids"], info.get("seed", seed)
    lead_ids = lead_ids or [x["lead_id"] for x in ctx.source.list_leads()]
    run_id = "run-" + uuid.uuid4().hex[:8]
    sv = versioning.system_version()
    ctx.db.create_run(run_id, seed, difficulty, len(lead_ids), sv, ctx.llm.runtime_config(), ctx.auto_send)
    for i, lid in enumerate(lead_ids):
        ctx.db.add_lead(run_id, i, ctx.source.get_lead(lid))
    return run_id


def run_queue(ctx: Context, run_id: str, workers: int = 4) -> list[LeadOutcome]:
    ids = ctx.db.lead_ids(run_id)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(lambda lid: process_lead(ctx, run_id, lid, "initial"), ids))


def poll_replies(ctx: Context, run_id: str, workers: int = 4) -> list[LeadOutcome]:
    """Ingest new inbound replies from the mailbox, store the parsed answers, and re-process those leads."""
    changed: list[str] = []
    for lead_id in ctx.db.lead_ids(run_id):
        outs = {e["mailbox_id"]: e for e in ctx.db.emails(run_id, lead_id, "out") if e["status"] == "sent"}
        known = {e["mailbox_id"] for e in ctx.db.emails(run_id, lead_id, "in")}
        for m in ctx.mailbox.list_for_lead(lead_id):
            md = m.get("metadata") or {}
            out = outs.get(md.get("in_reply_to"))
            if md.get("direction") != "inbound" or m["id"] in known or out is None:
                continue
            eid = ctx.db.add_email(run_id, lead_id, "in", "received", m["to"], m["subject"], m["body"], m["id"], out["id"])
            tagged = TaggedLLM(ctx.llm)
            parsed = parse_reply(tagged, json.loads(out["plan_json"])["asks"], m["body"])
            ctx.db.log_llm_calls(run_id, lead_id, tagged.calls)
            for f, v in parsed.answers.items():
                ctx.db.set_answer(run_id, lead_id, f, v, "reply", eid)
            for f in parsed.not_applicable:
                if f not in parsed.answers:
                    ctx.db.set_answer(run_id, lead_id, f, None, "reply_na", eid)
            ctx.db.execute("UPDATE emails SET parsed=1 WHERE id=?", (eid,))
            changed.append(lead_id)
    changed = list(dict.fromkeys(changed))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(lambda lid: process_lead(ctx, run_id, lid, "reply"), changed))
