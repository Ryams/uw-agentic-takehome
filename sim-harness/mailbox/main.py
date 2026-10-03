"""mailbox FastAPI service.

A mock email service: the candidate's agent POSTs outbound follow-up emails
here; we capture them and make them easy to browse/list per lead, both via the
JSON API and a minimal server-rendered HTML inbox at GET /.

Reply simulation (closing the loop) is intentionally out of scope. The store is
keyed by lead_id, leaving a clean seam for a future POST /emails/{id}/reply.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from shared.schema import EmailIn

from . import store

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))

app = FastAPI(title="mailbox", version="1.0.0")


store.init_db()  # idempotent; ensures the table exists regardless of lifespan timing


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- JSON API -------------------------------------------------------------


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/emails")
def post_email(email: EmailIn) -> dict:
    return store.insert_email(
        lead_id=email.lead_id, to=email.to, from_=email.from_,
        subject=email.subject, body=email.body, metadata=email.metadata,
        received_at=_now(),
    )


@app.get("/emails")
def get_emails(
    lead_id: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    return store.list_emails(lead_id=lead_id, limit=limit, offset=offset)


@app.get("/emails/{email_id}")
def get_email(email_id: int) -> dict:
    rec = store.get_email(email_id)
    if rec is None:
        raise HTTPException(404, f"email not found: {email_id}")
    return rec


@app.get("/leads/{lead_id}/emails")
def get_lead_emails(lead_id: str) -> list[dict]:
    return store.emails_for_lead(lead_id)


@app.post("/reset")
def reset() -> dict[str, str]:
    store.clear()
    return {"status": "cleared"}


# --- HTML viewer ----------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def inbox(request: Request) -> HTMLResponse:
    records = store.all_records()
    groups: dict[str, list[dict]] = {}
    for rec in records:
        groups.setdefault(rec["lead_id"], []).append(rec)
    # Sorted by lead_id for a stable left-pane order.
    grouped = sorted(groups.items())
    return TEMPLATES.TemplateResponse(
        "inbox.html",
        {"request": request, "grouped": grouped, "total": len(records)},
    )
