"""SQLite state (D4): runs, leads, per-round decisions with full reports, answers, emails, UW actions,
LLM and tool calls. One connection guarded by a lock (the queue run is I/O-bound; writes are tiny)."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from uw_agent import versioning

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started_at TEXT, seed INTEGER, difficulty TEXT, n_leads INTEGER,
    system_version TEXT, runtime_config_json TEXT, auto_send INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS leads (
    run_id TEXT, lead_id TEXT, idx INTEGER, received_at TEXT, source TEXT, raw_json TEXT,
    state TEXT, decision TEXT, priority INTEGER, latest_round INTEGER DEFAULT 0, updated_at TEXT,
    PRIMARY KEY (run_id, lead_id));
CREATE TABLE IF NOT EXISTS decisions (
    run_id TEXT, lead_id TEXT, round INTEGER, created_at TEXT, trigger TEXT, state TEXT, decision TEXT,
    report_json TEXT, summary_json TEXT, PRIMARY KEY (run_id, lead_id, round));
CREATE TABLE IF NOT EXISTS answers (
    run_id TEXT, lead_id TEXT, field TEXT, value_json TEXT, source TEXT, email_id INTEGER, created_at TEXT,
    PRIMARY KEY (run_id, lead_id, field));
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, lead_id TEXT, direction TEXT, status TEXT,
    to_addr TEXT, subject TEXT, body TEXT, mailbox_id INTEGER, in_reply_to INTEGER, asks_hash TEXT,
    plan_json TEXT, parsed INTEGER DEFAULT 0, used_llm INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS uw_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, lead_id TEXT, action TEXT, payload_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, lead_id TEXT, task TEXT, model TEXT, effort TEXT,
    input_tokens INTEGER, output_tokens INTEGER, request_id TEXT, latency_s REAL, stop_reason TEXT, created_at TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.execute(versioning.SCHEMA)

    def execute(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple = ()) -> Optional[sqlite3.Row]:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    # --- runs / leads -------------------------------------------------------------------------
    def create_run(self, run_id: str, seed: Optional[int], difficulty: str, n: int, sv: dict[str, Any],
                   runtime_config: dict[str, Any], auto_send: bool) -> None:
        with self.lock:
            versioning.register_system_version(self.conn, sv)
        self.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                     (run_id, now(), seed, difficulty, n, sv["system_version"], json.dumps(runtime_config),
                      int(auto_send), "running"))

    def add_lead(self, run_id: str, idx: int, lead: dict[str, Any]) -> None:
        self.execute("INSERT OR REPLACE INTO leads (run_id, lead_id, idx, received_at, source, raw_json, state, updated_at)"
                     " VALUES (?,?,?,?,?,?,?,?)",
                     (run_id, lead["lead_id"], idx, lead.get("received_at"), lead.get("source"),
                      json.dumps(lead), "new", now()))

    def lead_row(self, run_id: str, lead_id: str) -> sqlite3.Row:
        r = self.one("SELECT * FROM leads WHERE run_id=? AND lead_id=?", (run_id, lead_id))
        if r is None:
            raise KeyError(f"unknown lead {lead_id} in run {run_id}")
        return r

    def lead_ids(self, run_id: str) -> list[str]:
        return [r["lead_id"] for r in self.query("SELECT lead_id FROM leads WHERE run_id=? ORDER BY idx", (run_id,))]

    # --- answers / emails ---------------------------------------------------------------------
    def answers(self, run_id: str, lead_id: str) -> dict[str, Any]:
        """Real answers received from the producer (N/A markers excluded)."""
        return {r["field"]: json.loads(r["value_json"])
                for r in self.query("SELECT field, value_json FROM answers WHERE run_id=? AND lead_id=? "
                                    "AND source != 'reply_na'", (run_id, lead_id))}

    def na_fields(self, run_id: str, lead_id: str) -> set[str]:
        """Fields the producer answered 'N/A' / not applicable: never ask again."""
        return {r["field"] for r in self.query("SELECT field FROM answers WHERE run_id=? AND lead_id=? "
                                               "AND source='reply_na'", (run_id, lead_id))}

    def set_answer(self, run_id: str, lead_id: str, field: str, value: Any, source: str, email_id: Optional[int]) -> None:
        self.execute("INSERT OR REPLACE INTO answers VALUES (?,?,?,?,?,?,?)",
                     (run_id, lead_id, field, json.dumps(value), source, email_id, now()))

    def add_email(self, run_id: str, lead_id: str, direction: str, status: str, to: str, subject: str, body: str,
                  mailbox_id: Optional[int], in_reply_to: Optional[int] = None, asks_hash: Optional[str] = None,
                  plan: Optional[dict[str, Any]] = None, used_llm: bool = False) -> int:
        return self.execute(
            "INSERT INTO emails (run_id, lead_id, direction, status, to_addr, subject, body, mailbox_id, in_reply_to,"
            " asks_hash, plan_json, used_llm, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, lead_id, direction, status, to, subject, body, mailbox_id, in_reply_to, asks_hash,
             json.dumps(plan) if plan else None, int(used_llm), now())).lastrowid

    def emails(self, run_id: str, lead_id: str, direction: Optional[str] = None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM emails WHERE run_id=? AND lead_id=?", [run_id, lead_id]
        if direction:
            sql, args = sql + " AND direction=?", args + [direction]
        return self.query(sql + " ORDER BY id", tuple(args))

    # --- decisions ----------------------------------------------------------------------------
    def save_decision(self, run_id: str, lead_id: str, trigger: str, state: str, decision: Optional[str], priority: int,
                      report: dict[str, Any], summary: Optional[dict[str, Any]]) -> int:
        with self.lock:
            rnd = (self.lead_row(run_id, lead_id)["latest_round"] or 0) + 1
            self.conn.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)",
                              (run_id, lead_id, rnd, now(), trigger, state, decision, json.dumps(report, default=str),
                               json.dumps(summary, default=str) if summary else None))
            self.conn.execute("UPDATE leads SET state=?, decision=?, priority=?, latest_round=?, updated_at=? "
                              "WHERE run_id=? AND lead_id=?", (state, decision, priority, rnd, now(), run_id, lead_id))
            self.conn.commit()
        return rnd

    def latest_decision(self, run_id: str, lead_id: str) -> Optional[dict[str, Any]]:
        r = self.one("SELECT d.* FROM decisions d JOIN leads l ON l.run_id=d.run_id AND l.lead_id=d.lead_id "
                     "AND l.latest_round=d.round WHERE d.run_id=? AND d.lead_id=?", (run_id, lead_id))
        if r is None:
            return None
        return {"round": r["round"], "state": r["state"], "decision": r["decision"], "trigger": r["trigger"],
                "report": json.loads(r["report_json"]), "summary": json.loads(r["summary_json"]) if r["summary_json"] else None}

    def log_llm_calls(self, run_id: str, lead_id: str, calls: list[Any]) -> None:
        for c in calls:
            self.execute("INSERT INTO llm_calls (run_id, lead_id, task, model, effort, input_tokens, output_tokens, request_id,"
                         " latency_s, stop_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (run_id, lead_id, c.task, c.model, c.effort, c.input_tokens, c.output_tokens, c.request_id,
                          c.latency_s, c.stop_reason, now()))

    def queue_view(self, run_id: str) -> list[dict[str, Any]]:
        """Leads ordered for the underwriter: quick wins first, then decisions needed, then waiting."""
        rows = self.query("SELECT lead_id, state, decision, priority, idx FROM leads WHERE run_id=? "
                          "ORDER BY priority, idx", (run_id,))
        return [dict(r) for r in rows]
