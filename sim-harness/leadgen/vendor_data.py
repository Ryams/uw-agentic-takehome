"""Vendor-shaped SQLite tables written at queue generation (D19), read by the `vendors` service.

The agent never sees these tables or `clean_fields`: it only calls the vendors service."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from shared.vendor_evidence import listing_rows

DDL = """
CREATE TABLE IF NOT EXISTS crm_accounts (lead_id TEXT PRIMARY KEY, broker_tier TEXT, has_primary_policy_with_stand INTEGER);
CREATE TABLE IF NOT EXISTS kyc_scores (lead_id TEXT PRIMARY KEY, score INTEGER);
CREATE TABLE IF NOT EXISTS rce_estimates (lead_id TEXT PRIMARY KEY, replacement_cost INTEGER);
CREATE TABLE IF NOT EXISTS ppc_records (lead_id TEXT PRIMARY KEY, ppc TEXT);
CREATE TABLE IF NOT EXISTS geo_risk (lead_id TEXT PRIMARY KEY, road_access TEXT, min_distance_to_neighbor_ft INTEGER,
    slope_angle_deg REAL, p_f REAL, vegetation_clearance TEXT);
CREATE TABLE IF NOT EXISTS property_listings (lead_id TEXT, topic TEXT, status TEXT, evidence_json TEXT,
    PRIMARY KEY (lead_id, topic));
-- Per-lead behaviour overrides for hand-built eval cases: vendor in (crm,kyc,rce,ppc,geo,listing),
-- key = field/topic ('*' = whole vendor), behavior = 'unavailable' | 'not_found' | 'ambiguous'.
CREATE TABLE IF NOT EXISTS vendor_overrides (lead_id TEXT, vendor TEXT, key TEXT, behavior TEXT, evidence_json TEXT,
    PRIMARY KEY (lead_id, vendor, key));
"""
TABLES = ["crm_accounts", "kyc_scores", "rce_estimates", "ppc_records", "geo_risk", "property_listings"]


def create_vendor_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)


def _b(v: Any) -> Any:
    return None if v is None else int(v)


def write_vendor_rows(conn: sqlite3.Connection, lead_id: str, truth: dict[str, Any], seed: int = 0) -> None:
    t = truth
    conn.execute("INSERT OR REPLACE INTO crm_accounts VALUES (?,?,?)",
                 (lead_id, t.get("broker_tier"), _b(t.get("has_primary_policy_with_stand"))))
    conn.execute("INSERT OR REPLACE INTO kyc_scores VALUES (?,?)", (lead_id, t.get("kyc_score")))
    conn.execute("INSERT OR REPLACE INTO rce_estimates VALUES (?,?)", (lead_id, t.get("replacement_cost")))
    conn.execute("INSERT OR REPLACE INTO ppc_records VALUES (?,?)", (lead_id, t.get("protection_class")))
    conn.execute("INSERT OR REPLACE INTO geo_risk VALUES (?,?,?,?,?,?)",
                 (lead_id, t.get("road_access"), t.get("min_distance_to_neighbor_ft"), t.get("slope_angle_deg"),
                  t.get("p_f"), t.get("vegetation_clearance")))
    for row in listing_rows(lead_id, t, seed):
        conn.execute("INSERT OR REPLACE INTO property_listings VALUES (?,?,?,?)",
                     (lead_id, row["topic"], row["status"], json.dumps(row["evidence"])))


def clear_vendor_rows(conn: sqlite3.Connection) -> None:
    for t in TABLES:
        conn.execute(f"DELETE FROM {t}")
