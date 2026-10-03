"""Run the morning queue end to end against the local harness.

    uv run python -m uw_agent.cli run --seed 42 [--offline] [--no-replies] [--reply-mode complete|partial]

Needs `make up` (leadgen with DEBUG=true, mailbox, vendors). `--offline` uses the rule-based stand-in instead of
Claude (no API key); otherwise ANTHROPIC_API_KEY is required."""

from __future__ import annotations

import argparse
import os
from functools import partial
from pathlib import Path

import httpx

from uw_agent import harness, orchestrator as orch
from uw_agent.config import ROOT, get_settings
from uw_agent.db import Database
from uw_agent.executor import ToolKit
from uw_agent.intake import HttpLeadSource
from uw_agent.mailbox import HttpMailbox
from uw_agent.replysim import simulate_replies
from uw_agent.tools.fetch import fetch_field
from uw_agent.tools.lookup import lookup_topic
from uw_agent.truth import TruthStore


def build_context(offline: bool, auto_send: bool = True, db_path: str | Path = ROOT / "var" / "uw_agent.db") -> orch.Context:
    s = get_settings()
    from uw_agent.llm import get_llm
    llm = get_llm("offline" if offline else None)          # None: UW_LLM, else the API when a key is set
    http = httpx.Client(timeout=30)
    return orch.Context(
        db=Database(db_path), source=HttpLeadSource(s.leadgen_url, http), mailbox=HttpMailbox(s.mailbox_url, http),
        tools=ToolKit(fetch=partial(fetch_field, client=http, base_url=s.vendors_url),
                      lookup=partial(lookup_topic, client=http, base_url=s.vendors_url)),
        llm=llm, settings=s, auto_send=auto_send,
        reset=partial(harness.reset_world, s.leadgen_url, s.mailbox_url, client=http))


def print_table(ctx: orch.Context, run_id: str) -> None:
    print(f"\n{'lead':<20}{'state':<16}{'decision':<24}{'pri'}  top reason / asks")
    for row in ctx.db.queue_view(run_id):
        d = ctx.db.latest_decision(run_id, row["lead_id"])
        rep = d["report"]
        why = (rep["reasons"][0]["type"] if rep["reasons"] else "") or ""
        asks = ", ".join(a["field"] for a in rep["asks"][:3])
        print(f"{row['lead_id']:<20}{row['state']:<16}{str(row['decision'] or '-'):<24}{row['priority']:<5}{why} {asks}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--count", type=int, default=10)
    r.add_argument("--difficulty", default="mixed")
    r.add_argument("--offline", action="store_true")
    r.add_argument("--llm", choices=["anthropic", "claude-code", "offline"], help="backend (default: UW_LLM or API key)")
    r.add_argument("--no-replies", action="store_true")
    r.add_argument("--reply-mode", default="complete", choices=["complete", "partial"])
    r.add_argument("--rounds", type=int, default=2)
    a = ap.parse_args()

    if a.llm:
        os.environ["UW_LLM"] = a.llm
    ctx = build_context(a.offline or a.llm == "offline")
    run_id = orch.start_run(ctx, a.seed, a.count, a.difficulty)
    print(f"run {run_id}  system {ctx.db.one('SELECT system_version FROM runs WHERE run_id=?', (run_id,))[0]}")
    orch.run_queue(ctx, run_id)
    print_table(ctx, run_id)
    if not a.no_replies:
        truth = TruthStore.from_leadgen(ctx.settings.leadgen_url, ctx.db.lead_ids(run_id))
        for i in range(a.rounds):
            n = simulate_replies(ctx.mailbox, truth, ctx.db.lead_ids(run_id), a.reply_mode)
            if not n:
                break
            out = orch.poll_replies(ctx, run_id)
            print(f"\nafter reply round {i + 1}: {n} replies, {len(out)} leads re-processed")
            print_table(ctx, run_id)


if __name__ == "__main__":
    main()
