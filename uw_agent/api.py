"""FastAPI layer (D4): thin HTTP over the orchestrator and SQLite state, plus the static underwriter UI.

The UI is the underwriter's single place to see what the agent did, what it assumed, what it wants to say,
and to act: approve the agent's proposal, override a value or the decision, edit and dispatch a drafted email.
Every action is stored as structured feedback (`uw_actions`) so overrides can feed the evals later."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from uw_agent import orchestrator as orch
from uw_agent import versioning

WEB = Path(__file__).parent / "web"


class StartRun(BaseModel):
    seed: Optional[int] = 42
    count: int = 10
    difficulty: str = "mixed"
    auto_send: Optional[bool] = None


class Action(BaseModel):
    action: str                         # approve | override_decision | provide_value | send_draft | edit_draft | note | reprocess
    decision: Optional[str] = None
    field: Optional[str] = None
    value: Optional[Any] = None
    note: Optional[str] = None
    email_id: Optional[int] = None
    subject: Optional[str] = None
    body: Optional[str] = None


class Reply(BaseModel):
    mode: str = "complete"


def _effective(row: Any) -> str:
    """The state the underwriter sees: actioned leads leave the work queues."""
    return "actioned" if row["uw_status"] else row["state"]


def create_app(ctx: orch.Context, simulate: Optional[Callable[[list[str], str], int]] = None,
               background: bool = True) -> FastAPI:
    """`simulate(lead_ids, mode) -> n_replies` is the demo-only producer simulator, injected by the server so
    this module never touches ground truth (D19)."""
    app = FastAPI(title="UW assistant", version="1.0.0")
    db = ctx.db

    def lead_or_404(run_id: str, lead_id: str):
        try:
            return db.lead_row(run_id, lead_id)
        except KeyError:
            raise HTTPException(404, "unknown lead")

    def card(row: Any) -> dict[str, Any]:
        d = db.latest_decision(row["run_id"], row["lead_id"])
        rep, summ = (d["report"], d["summary"] or {}) if d else ({}, {})
        low = [a for a in rep.get("assumptions", []) if a.get("low_confidence")]
        return {
            "lead_id": row["lead_id"], "address": rep.get("address", ""), "state": _effective(row),
            "agent_state": row["state"], "decision": row["decision"], "priority": row["priority"],
            "headline": summ.get("headline", ""), "reasons": [r["type"] for r in rep.get("reasons", [])],
            "n_asks": len(rep.get("asks", [])), "conditions": rep.get("conditions", []),
            "n_assumptions": len(rep.get("assumptions", [])), "n_low_confidence": len(low),
            "n_conflicts": len(rep.get("conflicts", [])), "email_status": rep.get("email_status"),
            "provisional": rep.get("provisional", False), "provisional_decision": rep.get("provisional_decision"), "uw_status": row["uw_status"], "uw_decision": row["uw_decision"],
        }

    def run_info(run_id: str) -> dict[str, Any]:
        r = db.run_row(run_id)
        if r is None:
            raise HTTPException(404, "unknown run")
        n = db.one("SELECT COUNT(*) c, SUM(latest_round > 0) p FROM leads WHERE run_id=?", (run_id,))
        return {"run_id": run_id, "status": r["status"], "seed": r["seed"], "difficulty": r["difficulty"],
                "n_leads": r["n_leads"], "processed": n["p"] or 0, "system_version": r["system_version"],
                "auto_send": bool(r["auto_send"]), "started_at": r["started_at"],
                "runtime_config": json.loads(r["runtime_config_json"] or "{}")}

    # --- runs ---------------------------------------------------------------------------------------
    @app.post("/api/runs")
    def start(req: StartRun) -> dict[str, Any]:
        if req.auto_send is not None:
            ctx.auto_send = req.auto_send
        try:
            run_id = orch.start_run(ctx, req.seed, req.count, req.difficulty, reset=ctx.reset is not None)
        except httpx.HTTPError as e:                      # the docker services are not up (or not reachable)
            raise HTTPException(503, "Can't reach the lead generator / mailbox (is `make up` running?). "
                                     f"{type(e).__name__}: {e}") from e

        def work() -> None:
            try:
                orch.run_queue(ctx, run_id)
            finally:
                db.set_run_status(run_id, "ready")
        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()
        return run_info(run_id)

    @app.get("/api/runs/latest")
    def latest() -> dict[str, Any]:
        rid = db.latest_run_id()
        if rid is None:
            raise HTTPException(404, "no runs yet")
        return run_info(rid)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return run_info(run_id)

    @app.get("/api/runs/{run_id}/queue")
    def queue(run_id: str) -> dict[str, Any]:
        rows = db.query("SELECT * FROM leads WHERE run_id=? AND latest_round > 0 ORDER BY priority, idx", (run_id,))
        return {"run": run_info(run_id), "leads": [card(r) for r in rows]}

    @app.post("/api/runs/{run_id}/poll")
    def poll(run_id: str) -> dict[str, Any]:
        out = orch.poll_replies(ctx, run_id)
        return {"reprocessed": [o.lead_id for o in out]}

    @app.post("/api/runs/{run_id}/simulate_replies")
    def sim(run_id: str, req: Reply) -> dict[str, Any]:
        """Demo only: the producer simulator answers every outstanding email from ground truth."""
        if simulate is None:
            raise HTTPException(501, "reply simulation is not configured")
        n = simulate(db.lead_ids(run_id), req.mode)
        out = orch.poll_replies(ctx, run_id) if n else []
        return {"replies": n, "reprocessed": [o.lead_id for o in out]}

    @app.post("/api/runs/{run_id}/leads/{lead_id}/simulate_reply")
    def sim_one(run_id: str, lead_id: str, req: Reply) -> dict[str, Any]:
        """Demo only: the producer simulator answers THIS lead's outstanding email, and the agent processes the reply."""
        lead_or_404(run_id, lead_id)
        if simulate is None:
            raise HTTPException(501, "reply simulation is not configured")
        replied = {e["in_reply_to"] for e in db.emails(run_id, lead_id, "in")}
        if not any(e["status"] == "sent" and e["id"] not in replied for e in db.emails(run_id, lead_id, "out")):
            raise HTTPException(409, "no sent email is waiting for a reply")
        n = simulate([lead_id], req.mode)
        if n:
            orch.poll_replies(ctx, run_id)
        return {"replies": n, **detail(run_id, lead_id)}

    # --- lead detail ----------------------------------------------------------------------------------
    @app.get("/api/runs/{run_id}/leads/{lead_id}")
    def detail(run_id: str, lead_id: str) -> dict[str, Any]:
        row = lead_or_404(run_id, lead_id)
        d = db.latest_decision(run_id, lead_id)
        emails = [{"id": e["id"], "direction": e["direction"], "status": e["status"], "to": e["to_addr"],
                   "subject": e["subject"], "body": e["body"], "used_llm": bool(e["used_llm"]), "created_at": e["created_at"]}
                  for e in db.emails(run_id, lead_id)]
        return {"card": card(row), "decision": d, "emails": emails, "answers": db.answers(run_id, lead_id),
                "history": db.decisions_history(run_id, lead_id), "uw_actions": db.uw_actions(run_id, lead_id),
                "uw_note": row["uw_note"]}

    # --- underwriter actions ----------------------------------------------------------------------------
    @app.post("/api/runs/{run_id}/leads/{lead_id}/actions")
    def act(run_id: str, lead_id: str, a: Action) -> dict[str, Any]:
        row = lead_or_404(run_id, lead_id)
        d = db.latest_decision(run_id, lead_id)
        payload = a.model_dump(exclude_none=True)
        db.add_uw_action(run_id, lead_id, a.action, {**payload, "agent_state": row["state"], "agent_decision": row["decision"]})

        if a.action == "approve":                          # accept the agent's proposal as-is
            if row["decision"] not in ("quote", "quote_with_conditions", "decline"):
                raise HTTPException(409, "the agent has no decision to approve yet")
            status = "approved_decline" if row["decision"] == "decline" else "approved_quote"
            db.set_uw_status(run_id, lead_id, status, row["decision"], a.note)
        elif a.action == "override_decision":
            if a.decision not in ("quote", "quote_with_conditions", "decline") or not (a.note or "").strip():
                raise HTTPException(422, "override_decision needs decision (quote|quote_with_conditions|decline) and a note")
            db.set_uw_status(run_id, lead_id, "overridden", a.decision, a.note)
        elif a.action == "provide_value":
            if not a.field or a.value is None:
                raise HTTPException(422, "provide_value needs field and value")
            from uw_agent.normalize import normalize_lead
            n = normalize_lead({a.field: a.value})
            if n.invalid or n.values.get(a.field) is None:
                raise HTTPException(422, f"invalid value for {a.field}")
            db.set_answer(run_id, lead_id, a.field, n.values[a.field], "uw", None)
            db.set_uw_status(run_id, lead_id, None)         # new information: back to the agent
            orch.process_lead(ctx, run_id, lead_id, "uw_override")
        elif a.action == "send_draft":
            e = next((x for x in db.emails(run_id, lead_id, "out") if x["id"] == a.email_id and x["status"] == "draft"), None)
            if e is None:
                raise HTTPException(409, "no such draft")
            meta = {"direction": "outbound", "run_id": run_id, "asks_hash": e["asks_hash"],
                    "asks": json.loads(e["plan_json"])["asks"]}
            mid = ctx.mailbox.send(lead_id, e["to_addr"], e["subject"], e["body"], meta)
            db.update_email(e["id"], status="sent", mailbox_id=mid)
            orch.process_lead(ctx, run_id, lead_id, "uw_sent_draft")
        elif a.action == "edit_draft":
            e = next((x for x in db.emails(run_id, lead_id, "out") if x["id"] == a.email_id and x["status"] == "draft"), None)
            if e is None:
                raise HTTPException(409, "only drafts can be edited")
            db.update_email(e["id"], subject=a.subject or e["subject"], body=a.body or e["body"])
        elif a.action == "reprocess":
            db.set_uw_status(run_id, lead_id, None)
            orch.process_lead(ctx, run_id, lead_id, "uw_reprocess")
        elif a.action == "note":
            db.set_uw_status(run_id, lead_id, row["uw_status"], row["uw_decision"], a.note)
        else:
            raise HTTPException(422, f"unknown action {a.action!r}")
        return detail(run_id, lead_id)

    @app.post("/api/runs/{run_id}/approve_quick_wins")
    def approve_quick_wins(run_id: str) -> dict[str, Any]:
        """One click for the easy ones: ready to quote, no conditions, nothing assumed with low confidence."""
        done = []
        for r in db.query("SELECT * FROM leads WHERE run_id=? AND state=? AND uw_status IS NULL AND priority=?",
                          (run_id, orch.READY, orch.PRIORITY["quick_win"])):
            c = card(r)
            if c["n_low_confidence"] == 0 and r["decision"] == "quote":
                db.add_uw_action(run_id, r["lead_id"], "approve", {"batch": True, "agent_decision": r["decision"]})
                db.set_uw_status(run_id, r["lead_id"], "approved_quote", r["decision"], "batch approve (quick wins)")
                done.append(r["lead_id"])
        return {"approved": done}

    # --- misc / UI -----------------------------------------------------------------------------------------
    @app.get("/api/version")
    def version() -> dict[str, Any]:
        sv = versioning.system_version()
        return {"system_version": sv["system_version"], "dirty": sv["dirty"],
                "components": {k: v["version"] for k, v in sv["components"].items()}}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    return app
