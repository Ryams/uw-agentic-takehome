"""D10: component versioning, system version, run records."""

import csv
import json
import sqlite3
import subprocess

from evals import compare, records
from uw_agent import versioning


def test_committed_manifest_is_current():
    """Fails if component files changed without the pre-commit hook bumping versions
    (e.g. committed with --no-verify). Fix: `python -m uw_agent.versioning bump`."""
    assert versioning.stale_components() == []


def test_bump_semantics(tmp_path):
    (tmp_path / "a.txt").write_text("one")
    reg = {"a": ["a.txt"], "b": ["missing.txt"]}
    m0 = versioning.bumped_manifest({}, versioning.live_components(tmp_path, reg))
    assert m0["a"]["version"] == 0 and m0["b"]["content_hash"] == "empty"
    m1 = versioning.bumped_manifest(m0, versioning.live_components(tmp_path, reg))
    assert m1 == m0                                    # unchanged content -> no bump
    (tmp_path / "a.txt").write_text("two")
    m2 = versioning.bumped_manifest(m1, versioning.live_components(tmp_path, reg))
    assert m2["a"]["version"] == 1 and m2["b"]["version"] == 0
    (tmp_path / "missing.txt").write_text("now exists")
    m3 = versioning.bumped_manifest(m2, versioning.live_components(tmp_path, reg))
    assert m3["b"]["version"] == 1                     # file appearing counts as a change


def test_protocols_are_components_and_system_version_format():
    sv = versioning.system_version()
    assert "protocol:swimming_pools" in sv["components"]
    assert "protocol:trusts_and_llcs_post_bind" in sv["components"]
    assert sv["system_version"].split("+")[0] == sv["git_commit"] or sv["system_version"].startswith("nogit")


def test_dirty_component_reported(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "versions").mkdir()
    (tmp_path / "x.txt").write_text("v1")
    reg = {"x": ["x.txt"]}
    versioning.write_manifest(versioning.bumped_manifest({}, versioning.live_components(tmp_path, reg)), tmp_path)
    (tmp_path / "x.txt").write_text("v2")  # changed after manifest written
    live = versioning.live_components(tmp_path, reg)
    assert versioning.load_manifest(tmp_path)["x"]["content_hash"] != live["x"]["content_hash"]


def test_register_system_version_is_idempotent_and_mapped():
    conn = sqlite3.connect(":memory:")
    sv = versioning.system_version()
    versioning.register_system_version(conn, sv)
    versioning.register_system_version(conn, sv)
    rows = conn.execute("SELECT system_version, components_json FROM system_versions").fetchall()
    assert len(rows) == 1 and rows[0][0] == sv["system_version"]
    assert "normalizer" in json.loads(rows[0][1])


def test_eval_csv_records_version_and_widens_columns(tmp_path):
    p = tmp_path / "results.csv"
    sv = versioning.system_version()
    records.append_eval_row("run1", 42, "mixed", 10, {"path_accuracy": 0.8}, path=p, sv=sv)
    records.append_eval_row("run2", 42, "mixed", 10, {"path_accuracy": 0.9, "blocker_recall": 0.7}, path=p, sv=sv)
    rows = list(csv.DictReader(p.open()))
    assert [r["eval_run_id"] for r in rows] == ["run1", "run2"]
    assert rows[0]["system_version"] == sv["system_version"] and rows[0]["blocker_recall"] == ""
    assert "leadgen_generator" in json.loads(rows[1]["eval_set_json"])
    assert "run1" in compare.compare("run1", "run2", path=p) and "+0.100" in compare.compare("run1", "run2", path=p)
