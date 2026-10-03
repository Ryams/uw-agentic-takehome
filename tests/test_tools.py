"""Mock vendors service + the agent's thin tool clients (D19). Everything runs in-process through
Starlette's TestClient (an httpx client): no sockets, no real external systems."""

import ast
import socket
import sqlite3
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import uw_agent.config  # noqa: F401
from leadgen import generator, vendor_data
from uw_agent import resolution
from uw_agent.tools import fetch, lookup
from vendors.main import create_app

ROOT = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load((ROOT / "sim-harness/leadgen/generator_config.yaml").read_text())
BASE = "http://testserver"


@pytest.fixture(scope="module")
def queue():
    return generator.generate_queue(42, 10, "hard", CONFIG)


@pytest.fixture()
def db(tmp_path, queue):
    path = tmp_path / "leadgen.db"
    conn = sqlite3.connect(path)
    vendor_data.create_vendor_tables(conn)
    for ld in queue:
        vendor_data.write_vendor_rows(conn, ld["lead_id"], ld["debug"]["clean_fields"], 42)
    conn.commit()
    conn.close()
    return path


def client(db, profile="demo"):
    return TestClient(create_app(str(db), profile, 7))


def override(db, lead_id, vendor, key, behavior, evidence=None):
    c = sqlite3.connect(db)
    c.execute("INSERT OR REPLACE INTO vendor_overrides VALUES (?,?,?,?,?)", (lead_id, vendor, key, behavior, evidence))
    c.commit()
    c.close()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tools must never open a real socket in these tests."""
    def boom(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", boom)


def test_fetch_returns_vendor_values_for_every_system_owned_field(db, queue):
    c = client(db)
    lead = queue[0]
    truth = lead["debug"]["clean_fields"]
    for f, entry in resolution.load_map()["fields"].items():
        step = next((s for s in entry["on_missing"] if s["action"] == "fetch"), None)
        if not step:
            continue
        r = fetch.fetch_field(lead["lead_id"], f, client=c, base_url=BASE)
        assert r.status == "found" and r.value == truth[f], (f, r)
        assert r.source.endswith("(mock)")


def test_fetch_failure_modes(db, queue):
    c = client(db)
    lid = queue[1]["lead_id"]
    assert fetch.fetch_field("LEAD-unknown", "kyc_score", client=c, base_url=BASE).status == "not_found"
    override(db, lid, "ppc", "*", "unavailable")
    assert fetch.fetch_field(lid, "protection_class", client=c, base_url=BASE).status == "unavailable"
    override(db, lid, "geo", "p_f", "not_found")
    r = fetch.fetch_field(lid, "p_f", client=c, base_url=BASE)
    assert r.status == "not_found"
    assert fetch.fetch_field(lid, "slope_angle_deg", client=c, base_url=BASE).status == "found"  # other fields intact
    with pytest.raises(KeyError):
        fetch.fetch_field(lid, "trust_name", client=c, base_url=BASE)  # not a system-owned field


def test_lookup_evidence_follows_truth_and_is_text_only(db, queue):
    c = client(db)
    seen = set()
    for ld in queue:
        t = ld["debug"]["clean_fields"]
        r = lookup.lookup_topic(ld["lead_id"], "pool_type", client=c, base_url=BASE)
        if t["pool_type"] in ("Inground", "Above Ground"):
            assert r.status == "found" and "pool" in r.evidence[0].lower()
            seen.add("pool")
        else:
            assert r.status == "not_found" and "pool" in r.evidence[0].lower()   # 'nothing seen' text
            seen.add("none")
        assert all(isinstance(e, str) for e in r.evidence) and r.sources
        r2 = lookup.lookup_topic(ld["lead_id"], "pool_security", client=c, base_url=BASE)
        if t["pool_type"] == "None":
            assert r2.status == "not_found"                                       # no pool, no pool details
    assert seen == {"pool", "none"}


def test_lookup_overrides_and_errors(db, queue):
    c = client(db)
    lid = queue[2]["lead_id"]
    override(db, lid, "listing", "pool_type", "ambiguous")
    r = lookup.lookup_topic(lid, "pool_type", client=c, base_url=BASE)
    assert r.status == "ambiguous" and "could be" in r.evidence[0]
    override(db, lid, "listing", "is_gated_community", "unavailable")
    assert lookup.lookup_topic(lid, "is_gated_community", client=c, base_url=BASE).status == "unavailable"
    assert c.get(f"/listings/{lid}", params={"topic": "bogus"}).status_code == 400


def test_noisy_profile_is_deterministic_and_injects_misses(db, queue):
    def run():
        c = client(db, "noisy")
        return [(ld["lead_id"], t, lookup.lookup_topic(ld["lead_id"], t, client=c, base_url=BASE).status)
                for ld in queue for t in ("pool_type", "pool_security", "is_gated_community")]
    a, b = run(), run()
    assert a == b                                           # seeded: reproducible
    clean = client(db, "demo")
    base = [(ld["lead_id"], t, lookup.lookup_topic(ld["lead_id"], t, client=clean, base_url=BASE).status)
            for ld in queue for t in ("pool_type", "pool_security", "is_gated_community")]
    assert a != base or all(s == "not_found" for _, _, s in base)  # noise changed something (when positives exist)


def test_vendor_tables_hold_truth_but_public_lead_payload_does_not(queue):
    assert "clean_fields" not in queue[0]["fields"]
    # the vendor tables are written from truth, in vendor-shaped columns
    conn = sqlite3.connect(":memory:")
    vendor_data.create_vendor_tables(conn)
    ld = queue[0]
    vendor_data.write_vendor_rows(conn, ld["lead_id"], ld["debug"]["clean_fields"], 1)
    assert conn.execute("SELECT broker_tier FROM crm_accounts").fetchone()[0] == ld["debug"]["clean_fields"]["broker_tier"]
    assert conn.execute("SELECT COUNT(*) FROM property_listings").fetchone()[0] == 5


# --- boundary: only the reply simulator and evals may touch ground truth (D5/D19) ---------------------

TRUTH_ALLOWED = {"truth.py", "replysim.py"}


def test_workflow_cannot_reach_ground_truth():
    offenders = []
    for py in (ROOT / "uw_agent").rglob("*.py"):
        if py.name in TRUTH_ALLOWED:
            continue
        src = py.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
            if any(m.split(".")[0] in ("leadgen", "vendors") or m.endswith("uw_agent.truth") or m == "uw_agent.truth"
                   for m in mods):
                offenders.append((str(py.relative_to(ROOT)), mods))
        if "clean_fields" in src or "/debug" in src or "sqlite3" in src and py.name not in ("versioning.py", "db.py"):
            offenders.append((str(py.relative_to(ROOT)), "touches truth/db string"))
    assert offenders == [], offenders
