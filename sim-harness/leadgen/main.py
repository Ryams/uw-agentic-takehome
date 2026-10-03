"""leadgen FastAPI service.

Generates a deterministic, difficulty-skewed "morning queue" of property leads
and stores them in SQLite so they survive restarts and stay viewable after a run.
The candidate-facing payload never contains answer-key hints; those live behind
GET /leads/{id}/debug, gated by DEBUG=true.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from shared import registry
from shared.schema import LeadDebug, LeadSummary, Perturbation, QueueResponse

from . import generator

CONFIG_PATH = Path(__file__).with_name("generator_config.yaml")
DB_PATH = Path(os.environ.get("LEADGEN_DB", "/data/leadgen.db"))
DEBUG = os.environ.get("DEBUG", "false").lower() in ("1", "true", "yes")

app = FastAPI(title="leadgen", version="1.0.0")


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                lead_id      TEXT PRIMARY KEY,
                seed         INTEGER NOT NULL,
                idx          INTEGER NOT NULL,
                received_at  TEXT NOT NULL,
                source       TEXT NOT NULL,
                difficulty   TEXT NOT NULL,
                fields_json  TEXT NOT NULL,
                debug_json   TEXT NOT NULL
            )
            """
        )


_init_db()  # idempotent; ensures the table exists regardless of lifespan timing


# --- endpoints ------------------------------------------------------------


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/registry")
def get_registry() -> JSONResponse:
    return JSONResponse(registry.load_registry())


@app.post("/queue", response_model=QueueResponse)
def post_queue(
    count: int = Query(default=int(os.environ.get("COUNT", 10)), ge=1, le=100),
    seed: Optional[int] = Query(default=None),
    difficulty: str = Query(default=os.environ.get("DIFFICULTY", "mixed")),
) -> QueueResponse:
    if difficulty not in ("easy", "mixed", "hard"):
        raise HTTPException(400, "difficulty must be easy | mixed | hard")
    if seed is None:
        env_seed = os.environ.get("SEED")
        seed = int(env_seed) if env_seed not in (None, "") else random.randrange(1, 2**31)

    config = load_config()
    leads = generator.generate_queue(seed, count, difficulty, config)

    # Replace any prior queue so GET /leads reflects exactly this run.
    with _connect() as conn:
        conn.execute("DELETE FROM leads")
        conn.executemany(
            """INSERT INTO leads
               (lead_id, seed, idx, received_at, source, difficulty, fields_json, debug_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    ld["lead_id"], seed, i, ld["received_at"], ld["source"],
                    ld["debug"]["difficulty"], json.dumps(ld["fields"]),
                    json.dumps(ld["debug"]),
                )
                for i, ld in enumerate(leads)
            ],
        )

    return QueueResponse(
        seed=seed, count=len(leads), difficulty=difficulty,
        lead_ids=[ld["lead_id"] for ld in leads],
    )


@app.get("/leads", response_model=list[LeadSummary])
def get_leads() -> list[LeadSummary]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT lead_id, source, received_at, fields_json FROM leads ORDER BY idx"
        ).fetchall()
    out = []
    for r in rows:
        fields = json.loads(r["fields_json"])
        missing = sum(1 for v in fields.values() if v is None)
        out.append(LeadSummary(
            lead_id=r["lead_id"], source=r["source"],
            received_at=r["received_at"], missing_field_count=missing,
        ))
    return out


def _get_row(lead_id: str) -> sqlite3.Row:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"lead not found: {lead_id}")
    return row


@app.get("/leads/{lead_id}")
def get_lead(lead_id: str) -> dict[str, Any]:
    row = _get_row(lead_id)
    # Candidate-facing payload: registry-shaped, NO answer-key hints.
    return {
        "lead_id": row["lead_id"],
        "received_at": row["received_at"],
        "source": row["source"],
        "fields": json.loads(row["fields_json"]),
    }


@app.get("/leads/{lead_id}/debug", response_model=LeadDebug)
def get_lead_debug(lead_id: str) -> LeadDebug:
    if not DEBUG:
        raise HTTPException(403, "debug answer key disabled; start leadgen with DEBUG=true")
    row = _get_row(lead_id)
    debug = json.loads(row["debug_json"])
    return LeadDebug(
        lead_id=row["lead_id"],
        difficulty=debug["difficulty"],
        injected_archetypes=debug["injected_archetypes"],
        perturbations=[Perturbation(**p) for p in debug["perturbations"]],
    )


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    """Queue composition summary (counts per tier / archetype)."""
    with _connect() as conn:
        rows = conn.execute("SELECT difficulty, debug_json FROM leads").fetchall()
    tiers: dict[str, int] = {}
    arches: dict[str, int] = {}
    leads_with_archetype = 0
    for r in rows:
        tiers[r["difficulty"]] = tiers.get(r["difficulty"], 0) + 1
        names = json.loads(r["debug_json"]).get("injected_archetypes", [])
        if names:
            leads_with_archetype += 1
        for n in names:
            arches[n] = arches.get(n, 0) + 1
    return {
        "total_leads": len(rows),
        "leads_with_archetype": leads_with_archetype,
        "tier_counts": tiers,
        "archetype_counts": arches,
    }


@app.post("/reset")
def reset() -> dict[str, str]:
    with _connect() as conn:
        conn.execute("DELETE FROM leads")
    return {"status": "cleared"}
