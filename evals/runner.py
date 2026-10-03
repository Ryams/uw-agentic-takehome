"""Eval runner (D17/D18): run eval sets through the real orchestrator, grade against ground truth, report per slice,
append to evals/results.csv stamped with the system version.

    uv run python -m evals.runner                       # all sets, in-process world, Claude if a key is set else offline
    uv run python -m evals.runner --sets s42-mixed,fixed --llm offline
    uv run python -m evals.runner --live                # seeded sets against the docker stack (leadgen DEBUG=true)
    uv run python -m evals.runner --record-composition  # re-record seeded set composition after a deliberate change

Every set starts from a clean world: in-process that is a fresh mailbox and DB; live, `reset_world` clears the mailbox
and regenerates the queue before each seed."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import httpx

import uw_agent.config  # noqa: F401
from uw_agent import orchestrator as orch, versioning
from uw_agent.config import ROOT
from uw_agent.protocols import engine
from uw_agent.replysim import simulate_replies
from uw_agent.truth import TruthStore

from evals import grader, records, setdefs
from evals.model import EvalCase, case_from_debug
from evals.world import InProcessWorld

RUNS_DIR = ROOT / "evals" / "runs"
MAX_ROUNDS = 3
DIMENSIONS = ("protocol", "outcome", "failure_mode", "archetype", "tier", "scenario", "boundary")


def make_llm(kind: str):
    if kind == "auto":
        kind = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "offline"
    if kind == "offline":
        from uw_agent.offline_llm import OfflineLLM
        return OfflineLLM()
    from uw_agent.llm import get_llm
    return get_llm()


def _mode(case: EvalCase, rnd: int) -> str:
    """Reply behaviour: `none` never replies; `partial` is the first reply only, later rounds answer fully."""
    return "none" if case.reply_mode == "none" else (case.reply_mode if rnd == 1 else "complete")


def play(ctx: orch.Context, truth: TruthStore, cases: list[EvalCase], run_id: str) -> dict[str, dict[str, int]]:
    """Run the queue, then simulate producer replies round by round. Returns per-lead round bookkeeping."""
    by_id = {c.lead_id: c for c in cases}
    first = {o.lead_id: o for o in orch.run_queue(ctx, run_id)}
    info = {lid: {"after1": len(ctx.db.emails(run_id, lid, "out")),
                  "closed": 0 if o.state != orch.AWAITING else None} for lid, o in first.items()}
    for rnd in range(1, MAX_ROUNDS + 1):
        # every lead with an unanswered email gets a reply, including leads already with the underwriter
        # (the producer still answers; the lead's final state is read after replies)
        waiting = list(info)
        sent = 0
        for mode in ("complete", "partial", "none"):
            ids = [lid for lid in waiting if _mode(by_id[lid], rnd) == mode]
            if ids and mode != "none":
                sent += simulate_replies(ctx.mailbox, truth, ids, mode)
        if not sent:
            break
        for o in orch.poll_replies(ctx, run_id):
            if o.state != orch.AWAITING and info[o.lead_id]["closed"] is None:
                info[o.lead_id]["closed"] = rnd
    return info


def grade_run(ctx: orch.Context, cases: list[EvalCase], run_id: str, info: dict[str, dict[str, int]]):
    recs, tags, stale = [], {}, []
    for c in cases:
        o = grader.oracle(c, ctx.protocols)
        s = grader.expectation_stale(c, o)
        if s:
            stale.append(f"{c.case_id or c.lead_id}: {s}")
        recs.append(grader.grade_lead(c, o, ctx.db, run_id, info[c.lead_id]["closed"], info[c.lead_id]["after1"]))
        tags[c.lead_id] = grader.slice_tags(c, o)
    return recs, tags, stale


def slices(recs: list[dict[str, Any]], tags: dict[str, dict[str, list[str]]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"overall": recs}
    for r in recs:
        for dim in DIMENSIONS:
            for v in tags[r["lead_id"]].get(dim, []):
                out.setdefault(f"{dim}={v}", []).append(r)
    return out


def coverage(all_cases: list[tuple[str, EvalCase]], protocols: list[engine.Protocol]) -> dict[str, Any]:
    """Which protocol outcomes (and named boundary cases) the evaluated leads exercised."""
    hit: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    boundaries: dict[str, int] = defaultdict(int)
    for _, c in all_cases:
        o = grader.oracle(c, protocols)
        for p, x in o.outcomes.items():
            hit[p][x] += 1
        for ov in o.overlays:
            p, x = ov.split(":")
            hit[p][x] += 1
        for b in c.tags.get("boundary", []):
            boundaries[b] += 1
    table = {}
    for p in protocols:
        table[p.name] = {x: hit[p.name].get(x, 0) for x in p.outcomes}
    return {"outcomes": table, "uncovered": [f"{p}:{x}" for p, d in table.items() for x, n in d.items() if n == 0],
            "boundaries": dict(boundaries)}


def run_set(name: str, cases: list[EvalCase], llm, seed: int, difficulty: str, live: bool = False,
            auto_send: bool = True):
    """Execute one eval set from a clean world; returns (recs, tags, stale, run_id, runtime_config)."""
    if live:
        from uw_agent.cli import build_context
        ctx = build_context(offline=True, auto_send=auto_send, db_path=":memory:")   # llm replaced below
        ctx.llm = llm
        run_id = orch.start_run(ctx, seed, len(cases), difficulty)          # reset_world: mailbox cleared, queue regenerated
        truth = TruthStore({c.lead_id: c.truth for c in cases})
        world = None
    else:
        world = InProcessWorld(cases, llm, seed, auto_send=auto_send)
        ctx, truth = world.ctx, world.truth
        run_id = orch.start_run(ctx, seed, len(cases), difficulty, reset=False)
    try:
        info = play(ctx, truth, cases, run_id)
        recs, tags, stale = grade_run(ctx, cases, run_id, info)
    finally:
        if world:
            world.close()
    return recs, tags, stale, run_id, llm.runtime_config(), ctx


def live_cases(spec: dict[str, Any], leadgen_url: str) -> list[EvalCase]:
    from uw_agent.harness import reset_world
    from uw_agent.config import get_settings
    s = get_settings()
    c = httpx.Client(timeout=30)
    info = reset_world(s.leadgen_url, s.mailbox_url, spec["seed"], spec["count"], spec["difficulty"], c)
    out = []
    for lid in info["lead_ids"]:
        lead = c.get(f"{leadgen_url}/leads/{lid}").json()
        dbg = c.get(f"{leadgen_url}/leads/{lid}/debug")
        if dbg.status_code == 403:
            raise SystemExit("leadgen answer key is disabled; start it with DEBUG=true (`make up`)")
        out.append(case_from_debug(lead, dbg.json()))
    return out


def run_config(a: argparse.Namespace, names: list[str], llm_cfg: dict[str, Any]) -> dict[str, Any]:
    """Everything about HOW this eval ran (beyond the code version), recorded with every row and in the run JSON."""
    import platform
    from importlib import metadata
    ctx_defaults = orch.Context.__dataclass_fields__
    return {**llm_cfg, "eval_run": {
        "sets": names, "world": "live" if a.live else "in-process", "llm_flag": a.llm,
        "max_reply_rounds": MAX_ROUNDS, "auto_send": True,
        "max_emails_per_lead": ctx_defaults["max_emails"].default,
        "reply_simulator_modes": {"seeded": "complete", "fixed": "per case (complete|partial|none)"},
        "vendor_profile": "per docker env (VENDOR_PROFILE)" if a.live else "demo", "vendor_seed": 7,
        "python": platform.python_version(), "anthropic_sdk": _pkg("anthropic"), "slice_dimensions": list(DIMENSIONS)}}


def _pkg(name: str) -> Optional[str]:
    from importlib import metadata
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def fmt(v: Optional[float]) -> str:
    return "  -  " if v is None else f"{v:5.2f}"


def print_report(eval_run_id: str, sv: dict[str, Any], per_set: dict[str, dict[str, Any]], all_slices, cov,
                 drift: list[str], stale: list[str], failures: list[dict[str, Any]]) -> None:
    print(f"\neval run {eval_run_id}   system {sv['system_version']}{' (dirty)' if sv['dirty'] else ''}")
    cols = ["state_correct", "decision_correct", "unsafe_quote_rate", "over_escalation_rate", "under_escalation_rate",
            "blocker_recall", "unneeded_ask_rate", "one_email_first_round", "emails_per_lead", "rounds_to_close"]
    print(f"\n{'set':<14}{'n':>4}  " + " ".join(f"{c[:11]:>11}" for c in cols))
    for name, d in per_set.items():
        print(f"{name:<14}{d['n']:>4}  " + " ".join(f"{fmt(d['metrics'][c]):>11}" for c in cols))
    print("\nSlices (all sets pooled; n = leads; a lead can be in several slices):")
    sl_cols = ["state_correct", "decision_correct", "unsafe_quote_rate", "blocker_recall", "unneeded_ask_rate",
               "lookup_accuracy", "assume_accuracy"]
    print(f"{'slice':<48}{'n':>4}  " + " ".join(f"{c[:11]:>11}" for c in sl_cols))
    for sl, (n, m) in all_slices.items():
        if sl == "overall":
            continue
        print(f"{sl:<48}{n:>4}  " + " ".join(f"{fmt(m[c]):>11}" for c in sl_cols))
    print("\nCoverage (leads exercising each protocol outcome):")
    for p, d in cov["outcomes"].items():
        print(f"  {p:<24}" + "  ".join(f"{x}={n}" for x, n in d.items()))
    if cov["uncovered"]:
        print("  NOT EXERCISED: " + ", ".join(cov["uncovered"]))
    if cov["boundaries"]:
        print("  boundary cases: " + ", ".join(f"{b}={n}" for b, n in sorted(cov["boundaries"].items())))
    for title, items in (("COMPOSITION DRIFT (seeded set differs from its recording)", drift),
                         ("STALE FIXED EXPECTATIONS (engine disagrees with the frozen answer)", stale)):
        if items:
            print(f"\n!! {title}")
            for x in items:
                print("   " + x)
    bad = [f for f in failures]
    print(f"\nFailing leads ({len(bad)}):")
    for f in bad[:25]:
        print(f"  {f['set']:<12} {f['lead_id']:<34}expected {f['expected_state']}/{f['expected_decision']}  "
              f"got {f['final_state']}/{f['final_decision']}  {'UNSAFE-QUOTE ' if f['unsafe_quote'] else ''}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sets", default=",".join([*setdefs.SEEDED_SPECS, "fixed"]))
    ap.add_argument("--llm", default="auto", choices=["auto", "offline", "claude"])
    ap.add_argument("--live", action="store_true", help="seeded sets against the docker stack (needs `make up`)")
    ap.add_argument("--no-csv", action="store_true")
    ap.add_argument("--csv", default=str(records.RESULTS_CSV), help="results file to append to")
    ap.add_argument("--strict", action="store_true", help="non-zero exit on drift/stale sets/unsafe quotes")
    ap.add_argument("--record-composition", action="store_true")
    a = ap.parse_args(argv)

    if a.record_composition:
        setdefs.record_seeded()
        print(f"recorded composition of {len(setdefs.SEEDED_SPECS)} seeded sets in {setdefs.SEEDED_JSON}")
        return 0

    from uw_agent.config import get_settings
    llm = make_llm(a.llm)
    sv = versioning.system_version()
    eval_run_id = records.new_eval_run_id()
    names = [n for n in a.sets.split(",") if n]
    per_set: dict[str, dict[str, Any]] = {}
    pooled_recs: list[dict[str, Any]] = []
    pooled_tags: dict[str, dict[str, list[str]]] = {}
    all_cases: list[tuple[str, EvalCase]] = []
    drift: list[str] = []
    stale: list[str] = []
    failures: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}
    runtime: dict[str, Any] = {}
    protocols = engine.load_protocols()
    cfg = run_config(a, names, llm.runtime_config())

    for name in names:
        if name == "fixed":
            if a.live:
                print("skipping fixed set in --live mode (hand-built leads cannot be injected into leadgen)")
                continue
            cases, spec = setdefs.load_fixed(), {"seed": 0, "difficulty": "fixed", "count": 0}
        else:
            spec = setdefs.SEEDED_SPECS[name]
            cases = live_cases(spec, get_settings().leadgen_url) if a.live else setdefs.seeded_cases(spec)
            drift += setdefs.composition_drift(name, cases)
        recs, tags, st, run_id, runtime, _ctx = run_set(name, cases, llm, spec["seed"], spec["difficulty"], a.live)
        stale += st
        for r in recs:
            r["set"] = name
        pooled_recs += recs
        pooled_tags.update({f"{name}/{k}": v for k, v in tags.items()})
        sl = slices(recs, tags)
        per_set[name] = {"n": len(recs), "metrics": grader.aggregate(recs), "run_id": run_id}
        all_cases += [(name, c) for c in cases]
        failures += [r for r in recs if not r["state_correct"] or r["unsafe_quote"]
                     or (r["decision_correct"] == 0)]
        detail[name] = {"run_id": run_id, "leads": recs, "slices": {k: len(v) for k, v in sl.items()}}
        if not a.no_csv:
            for sname, srecs in sl.items():
                records.append_eval_row(eval_run_id, spec["seed"], spec["difficulty"], len(srecs),
                                        grader.aggregate(srecs), cfg, path=Path(a.csv), sv=sv, eval_set=name, slice=sname)

    # pooled slices across sets (re-key tags so lead ids don't collide across sets)
    for r in pooled_recs:
        r["_key"] = f"{r['set']}/{r['lead_id']}"
    pooled = defaultdict(list)
    pooled["overall"] = pooled_recs
    for r in pooled_recs:
        for dim in DIMENSIONS:
            for v in pooled_tags[r["_key"]].get(dim, []):
                pooled[f"{dim}={v}"].append(r)
    all_slices = {k: (len(v), grader.aggregate(v)) for k, v in sorted(pooled.items(), key=lambda kv: (kv[0] != "overall", kv[0]))}
    if not a.no_csv:
        for sname, srecs in pooled.items():
            records.append_eval_row(eval_run_id, 0, "pooled", len(srecs), grader.aggregate(srecs), cfg, path=Path(a.csv),
                                    sv=sv, eval_set="ALL", slice=sname)
    cov = coverage(all_cases, protocols)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / f"{eval_run_id}.json").write_text(json.dumps(
        {"eval_run_id": eval_run_id, "system_version": sv["system_version"], "dirty": sv["dirty"],
         "run_config": cfg, "sets": detail, "coverage": cov, "composition_drift": drift,
         "stale_expectations": stale}, indent=1, default=str))
    print_report(eval_run_id, sv, per_set, all_slices, cov, drift, stale, failures)
    print(f"\nper-lead detail: evals/runs/{eval_run_id}.json" + ("" if a.no_csv else "   summary row(s) appended to evals/results.csv"))
    unsafe = sum(r["unsafe_quote"] for r in pooled_recs)
    return 1 if a.strict and (drift or stale or unsafe) else 0


if __name__ == "__main__":
    sys.exit(main())
