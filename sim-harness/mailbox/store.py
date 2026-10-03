"""SQLite persistence for the mailbox service.

One table `emails`. The file lives on a mounted volume so captured emails
survive `docker compose down && up` and stay browsable after a run.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(os.environ.get("MAILBOX_DB", "/data/mailbox.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id      TEXT NOT NULL,
                to_addr      TEXT NOT NULL,
                from_addr    TEXT NOT NULL,
                subject      TEXT NOT NULL,
                body         TEXT NOT NULL,
                metadata_json TEXT,
                received_at  TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_emails_lead ON emails(lead_id)")


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "lead_id": row["lead_id"],
        "to": row["to_addr"],
        "from": row["from_addr"],
        "subject": row["subject"],
        "body": row["body"],
        "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else None,
        "received_at": row["received_at"],
    }


def insert_email(lead_id: str, to: str, from_: str, subject: str, body: str,
                 metadata: Optional[dict[str, Any]], received_at: str) -> dict[str, Any]:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO emails
               (lead_id, to_addr, from_addr, subject, body, metadata_json, received_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (lead_id, to, from_, subject, body,
             json.dumps(metadata) if metadata is not None else None, received_at),
        )
        new_id = cur.lastrowid
    return {"id": new_id, "lead_id": lead_id, "received_at": received_at}


def list_emails(lead_id: Optional[str] = None, limit: int = 100,
                offset: int = 0) -> list[dict[str, Any]]:
    """Summaries, newest first."""
    q = "SELECT id, lead_id, to_addr, subject, received_at FROM emails"
    params: list[Any] = []
    if lead_id is not None:
        q += " WHERE lead_id = ?"
        params.append(lead_id)
    q += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _connect() as conn:
        rows = conn.execute(q, params).fetchall()
    return [
        {"id": r["id"], "lead_id": r["lead_id"], "to": r["to_addr"],
         "subject": r["subject"], "received_at": r["received_at"]}
        for r in rows
    ]


def get_email(email_id: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    return _row_to_record(row) if row else None


def emails_for_lead(lead_id: str) -> list[dict[str, Any]]:
    """Full records for one lead, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM emails WHERE lead_id = ? ORDER BY id DESC", (lead_id,)
        ).fetchall()
    return [_row_to_record(r) for r in rows]


def all_records() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM emails ORDER BY id DESC").fetchall()
    return [_row_to_record(r) for r in rows]


def clear() -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM emails")
