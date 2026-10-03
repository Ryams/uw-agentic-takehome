"""Eval harness (milestone 7): fixed sets are reproducible and consistent with the engine, seeded sets match their
recorded composition, the grader scores what it claims to, and the runner writes version-stamped results."""

import csv
import json

import pytest

import uw_agent.config  # noqa: F401
from evals import build_fixed_set, grader, records, runner, setdefs
from evals.model import EvalCase
from uw_agent import orchestrator as orch


def test_fixed_set_file_is_a_fresh_build():
    """The committed fixed set equals what the hand-written cases build now (nothing edited by hand, no drift)."""
    assert json.loads(setdefs.FIXED_JSON.read_text()) == json.loads(json.dumps(build_fixed_set.build(), sort_keys=True))


def test_fixed_expectations_match_the_engine():
    for c in setdefs.load_fixed():
        assert grader.expectation_stale(c, grader.oracle(c)) is None, c.case_id


def test_fixed_set_covers_every_protocol_leaf_it_claims_to_and_all_boundaries():
    cases = setdefs.load_fixed()
    cov = runner.coverage([("fixed", c) for c in cases], runner.engine.load_protocols())
    # UW_REVIEW (on_unexpected) leaves are not reachable with valid data
    assert set(cov["uncovered"]) <= {f"{p}:UW_REVIEW" for p in cov["outcomes"]}
    assert cov["outcomes"]["swimming_pools"]["LOL_ENDORSEMENT"] == 1       # overlays count as exercised
    declared = set(json.loads(setdefs.FIXED_JSON.read_text())["boundaries"])
    assert declared == set(cov["boundaries"]), "every declared boundary has at least one case"


@pytest.mark.parametrize("name", list(setdefs.SEEDED_SPECS))
def test_seeded_sets_match_recorded_composition(name):
    cases = setdefs.seeded_cases(setdefs.SEEDED_SPECS[name])
    assert setdefs.composition_drift(name, cases) == [], "re-record with `python -m evals.runner --record-composition`"


def test_oracle_expects_escalation_for_declines_and_conflicts():
    by = {c.case_id: c for c in setdefs.load_fixed()}
    assert grader.oracle(by["wh-tank-11-finished-decline"]).state == orch.NEEDS_UW
    assert grader.oracle(by["conflict-roof-year-future"]).state == orch.NEEDS_UW
    o = grader.oracle(by["roof-pf-016-first-term"])
    assert o.state == orch.READY and o.outcomes["roof_class"] == "CONFIRM_CLASS_A_FIRST_TERM" and not o.conflict


def test_slice_tags_use_focus_for_fixed_and_all_decided_protocols_for_seeded():
    by = {c.case_id: c for c in setdefs.load_fixed()}
    c = by["roof-pf-051-60-days"]
    t = grader.slice_tags(c, grader.oracle(c))
    assert t["protocol"] == ["roof_class"] and t["outcome"] == ["roof_class:CONFIRM_CLASS_A_60_DAYS_OR_DECLINE"]
    seeded = setdefs.seeded_cases(setdefs.SEEDED_SPECS["s7-hard"])[0]
    assert len(grader.slice_tags(seeded, grader.oracle(seeded))["protocol"]) >= 3


def test_aggregate_micro_averages_and_skips_ungraded():
    recs = [dict(state_correct=1, decision_correct=1, asked_uncond=4, unneeded_asks=1, needed_fields=2, needed_asked=2,
                 email_after_round1=1, emails_sent=1, unsafe_quote=0),
            dict(state_correct=0, decision_correct=None, asked_uncond=0, unneeded_asks=0, needed_fields=2, needed_asked=1,
                 email_after_round1=2, emails_sent=2, unsafe_quote=1)]
    m = grader.aggregate(recs)
    assert m["state_correct"] == 0.5 and m["decision_correct"] == 1.0          # None = not graded, excluded
    assert m["unneeded_ask_rate"] == 0.25 and m["blocker_recall"] == 0.75      # ratio of sums, not mean of ratios
    assert m["one_email_first_round"] == 0.5 and m["unsafe_quote_rate"] == 0.5


def test_runner_writes_version_stamped_slice_rows_and_clears_state_between_sets(tmp_path, capsys):
    out = tmp_path / "results.csv"
    rc = runner.main(["--sets", "s42-mixed,fixed", "--llm", "offline", "--csv", str(out)])
    assert rc == 0
    rows = list(csv.DictReader(out.open()))
    assert {r["eval_set"] for r in rows} == {"s42-mixed", "fixed", "ALL"}
    assert all(r["system_version"] and r["eval_run_id"] == rows[0]["eval_run_id"] for r in rows)
    overall = {r["eval_set"]: r for r in rows if r["slice"] == "overall"}
    assert overall["s42-mixed"]["n_leads"] == "10" and overall["fixed"]["n_leads"] == str(len(setdefs.load_fixed()))
    assert overall["ALL"]["n_leads"] == str(10 + len(setdefs.load_fixed()))
    assert any(r["slice"].startswith("protocol=") for r in rows) and any(r["slice"].startswith("boundary=") for r in rows)
    assert json.loads(overall["fixed"]["runtime_config_json"])["offline"] is True    # offline runs are identifiable
    assert "Coverage" in capsys.readouterr().out
