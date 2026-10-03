"""Shared in-process test world: generated queue -> vendor tables -> TestClient vendors, in-memory mailbox,
ground-truth reply simulator. No network, no model."""

import sqlite3
from functools import partial
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

import uw_agent.config  # noqa: F401
from leadgen import generator, vendor_data
from uw_agent import orchestrator as orch
from uw_agent import resolution
from uw_agent.db import Database
from uw_agent.executor import ToolKit
from uw_agent.intake import DictLeadSource
from uw_agent.mailbox import InMemoryMailbox
from uw_agent.normalize import normalize_lead
from uw_agent.offline_llm import OfflineLLM
from uw_agent.protocols import engine
from uw_agent.tools.fetch import fetch_field
from uw_agent.tools.lookup import lookup_topic
from uw_agent.truth import TruthStore
from vendors.main import create_app

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "sim-harness/leadgen/generator_config.yaml").read_text())


def public(lead):
    return {k: lead[k] for k in ("lead_id", "received_at", "source", "fields")}


class World:
    def __init__(self, tmp_path, seed=42, difficulty="mixed", count=10, llm=None, auto_send=True, leads=None,
                 truth=None, profile="demo"):
        self.queue = leads or generator.generate_queue(seed, count, difficulty, CONFIG)
        self.truth = TruthStore(truth or {l["lead_id"]: l["debug"]["clean_fields"] for l in self.queue})
        db_path = tmp_path / "leadgen.db"
        conn = sqlite3.connect(db_path)
        vendor_data.create_vendor_tables(conn)
        for lid in self.truth._truth:
            vendor_data.write_vendor_rows(conn, lid, self.truth.get(lid), seed)
        conn.commit()
        conn.close()
        self.db_path = db_path
        self.vendor_client = TestClient(create_app(str(db_path), profile, 7))
        self.mailbox = InMemoryMailbox()
        base = "http://testserver"
        self.ctx = orch.Context(
            db=Database(), source=DictLeadSource([public(l) for l in self.queue]), mailbox=self.mailbox,
            tools=ToolKit(fetch=partial(fetch_field, client=self.vendor_client, base_url=base),
                          lookup=partial(lookup_topic, client=self.vendor_client, base_url=base)),
            llm=llm or OfflineLLM(), auto_send=auto_send)

    def start(self):
        self.run_id = orch.start_run(self.ctx, reset=False)
        return self.run_id

    def truth_decision(self, lead_id):
        v = normalize_lead(self.truth.get(lead_id)).values
        a = resolution.analyze(v, resolution.context_values("2026-06-29T08:00:00Z"))
        return engine.evaluate_all(a.values, self.ctx.protocols)
