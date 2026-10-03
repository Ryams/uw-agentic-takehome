"""Mock third-party vendors (CRM, KYC, replacement cost, PPC, geo/fire risk, Maps/Zillow listings).

A thin, read-only service over the vendor-shaped tables leadgen writes (D19). No real external
system is involved. 404 = vendor has no record; 503 = vendor unavailable (per-lead override or the
`noisy` profile). Maps/Zillow returns evidence TEXT; the agent's interpreter reads it.

env: VENDORS_DB (default /data/leadgen.db), VENDOR_PROFILE=demo|noisy, VENDOR_SEED
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query

from shared import vendor_evidence as ve


def create_app(db_path: Optional[str] = None, profile: Optional[str] = None, seed: Optional[int] = None) -> FastAPI:
    app = FastAPI(title="vendors", version="1.0.0")
    path = Path(db_path or os.environ.get("VENDORS_DB", "/data/leadgen.db"))
    prof = profile or os.environ.get("VENDOR_PROFILE", "demo")
    sd = seed if seed is not None else int(os.environ.get("VENDOR_SEED", "0") or 0)

    def conn() -> sqlite3.Connection:
        if not path.exists():
            raise HTTPException(503, "vendor database not available (generate a queue first)")
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c

    def override(c: sqlite3.Connection, lead_id: str, vendor: str, key: str) -> Optional[sqlite3.Row]:
        try:
            return c.execute("SELECT * FROM vendor_overrides WHERE lead_id=? AND vendor=? AND key IN (?, '*') "
                             "ORDER BY key = '*' LIMIT 1", (lead_id, vendor, key)).fetchone()
        except sqlite3.OperationalError:
            return None

    def record(table: str, vendor: str, lead_id: str, keys: list[str]) -> dict[str, Any]:
        c = conn()
        try:
            for k in keys:
                o = override(c, lead_id, vendor, k)
                if o and o["behavior"] == "unavailable":
                    raise HTTPException(503, f"{vendor} unavailable (simulated)")
            if prof == "noisy" and ve.rand(sd, "down", lead_id, vendor) < 0.08:
                raise HTTPException(503, f"{vendor} unavailable (simulated, noisy profile)")
            row = c.execute(f"SELECT * FROM {table} WHERE lead_id=?", (lead_id,)).fetchone()
        finally:
            c.close()
        if row is None:
            raise HTTPException(404, f"{vendor}: no record for {lead_id}")
        out = {k: row[k] for k in row.keys() if k != "lead_id"}
        for k in keys:  # per-field 'not_found' overrides blank that field
            c = conn()
            try:
                o = override(c, lead_id, vendor, k)
            finally:
                c.close()
            if o and o["behavior"] == "not_found":
                out[k] = None
        return out

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/crm/accounts/{lead_id}")
    def crm(lead_id: str) -> dict[str, Any]:
        r = record("crm_accounts", "crm", lead_id, ["broker_tier", "has_primary_policy_with_stand"])
        if r.get("has_primary_policy_with_stand") is not None:
            r["has_primary_policy_with_stand"] = bool(r["has_primary_policy_with_stand"])
        return r

    @app.get("/kyc/scores/{lead_id}")
    def kyc(lead_id: str) -> dict[str, Any]:
        return record("kyc_scores", "kyc", lead_id, ["score"])

    @app.get("/rce/estimates/{lead_id}")
    def rce(lead_id: str) -> dict[str, Any]:
        return record("rce_estimates", "rce", lead_id, ["replacement_cost"])

    @app.get("/ppc/{lead_id}")
    def ppc(lead_id: str) -> dict[str, Any]:
        return record("ppc_records", "ppc", lead_id, ["ppc"])

    @app.get("/geo/risk/{lead_id}")
    def geo(lead_id: str) -> dict[str, Any]:
        return record("geo_risk", "geo", lead_id,
                      ["road_access", "min_distance_to_neighbor_ft", "slope_angle_deg", "p_f", "vegetation_clearance"])

    @app.get("/listings/{lead_id}")
    def listings(lead_id: str, topic: str = Query(...)) -> dict[str, Any]:
        if topic not in ve.TOPICS:
            raise HTTPException(400, f"unknown topic {topic!r}; one of {list(ve.TOPICS)}")
        c = conn()
        try:
            o = override(c, lead_id, "listing", topic)
            if o and o["behavior"] == "unavailable":
                raise HTTPException(503, "listing service unavailable (simulated)")
            if prof == "noisy" and ve.rand(sd, "down", lead_id, "listing") < 0.05:
                raise HTTPException(503, "listing service unavailable (simulated, noisy profile)")
            row = c.execute("SELECT * FROM property_listings WHERE lead_id=? AND topic=?", (lead_id, topic)).fetchone()
        finally:
            c.close()
        if row is None:
            raise HTTPException(404, f"no listing data for {lead_id}")
        status, evidence = row["status"], json.loads(row["evidence_json"])
        if o and o["behavior"] in ("not_found", "ambiguous"):
            status = o["behavior"]
            evidence = json.loads(o["evidence_json"]) if o["evidence_json"] else (
                ve.AMBIGUOUS[topic] if status == "ambiguous" else ve.NOTHING[topic])
        elif prof == "noisy" and status == "found":
            r = ve.rand(sd, "noise", lead_id, topic)
            if r < 0.20:
                status, evidence = "ambiguous", ve.AMBIGUOUS[topic]
            elif r < 0.30:
                status, evidence = "not_found", ve.NOTHING[topic]
        return {"topic": topic, "status": status, "evidence": evidence, "sources": ve.SOURCES}

    return app


app = create_app()
