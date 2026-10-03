"""In-process eval world: leads -> vendor tables -> vendors service (TestClient), in-memory mailbox, truth reply
simulator. Hermetic (no docker, no network); the live stack is used by `--live` instead."""

from __future__ import annotations

import sqlite3
import tempfile
from functools import partial
from pathlib import Path
from typing import Optional

from fastapi.testclient import TestClient

import uw_agent.config  # noqa: F401  (puts sim-harness on sys.path)
from leadgen import vendor_data
from uw_agent import orchestrator as orch
from uw_agent.db import Database
from uw_agent.executor import ToolKit
from uw_agent.intake import DictLeadSource
from uw_agent.mailbox import InMemoryMailbox
from uw_agent.tools.fetch import fetch_field
from uw_agent.tools.lookup import lookup_topic
from uw_agent.truth import TruthStore
from vendors.main import create_app

from evals.model import EvalCase


class InProcessWorld:
    def __init__(self, cases: list[EvalCase], llm, seed: int = 0, profile: str = "demo", auto_send: bool = True,
                 workdir: Optional[Path] = None):
        self.cases = cases
        self.truth = TruthStore({c.lead_id: c.truth for c in cases})
        self._tmp = None if workdir else tempfile.TemporaryDirectory()
        db_path = Path(workdir or self._tmp.name) / "vendors.db"
        conn = sqlite3.connect(db_path)
        vendor_data.create_vendor_tables(conn)
        for c in cases:
            vendor_data.write_vendor_rows(conn, c.lead_id, c.truth, seed)
            for o in c.vendor_overrides:
                conn.execute("INSERT OR REPLACE INTO vendor_overrides VALUES (?,?,?,?,?)",
                             (c.lead_id, o["vendor"], o["key"], o["behavior"], None))
        conn.commit()
        conn.close()
        client = TestClient(create_app(str(db_path), profile, 7))
        self.mailbox = InMemoryMailbox()
        base = "http://testserver"
        self.ctx = orch.Context(
            db=Database(), source=DictLeadSource([c.lead for c in cases]), mailbox=self.mailbox,
            tools=ToolKit(fetch=partial(fetch_field, client=client, base_url=base),
                          lookup=partial(lookup_topic, client=client, base_url=base)),
            llm=llm, auto_send=auto_send)

    def close(self) -> None:
        if self._tmp:
            self._tmp.cleanup()
