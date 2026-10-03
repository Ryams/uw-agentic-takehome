"""Server entry point:  make ui   (uvicorn --factory uw_agent.server:make_app --port 8090)

Env: UW_OFFLINE=1 uses the rule-based stand-in instead of Claude; AUTO_SEND=0 drafts emails for the
underwriter to approve (default: routine producer asks are sent automatically)."""

from __future__ import annotations

import os

from fastapi import FastAPI

from uw_agent.api import create_app
from uw_agent.cli import build_context
from uw_agent.replysim import simulate_replies
from uw_agent.truth import TruthStore


def make_app() -> FastAPI:
    ctx = build_context(offline=os.environ.get("UW_OFFLINE", "") in ("1", "true", "yes"),
                        auto_send=os.environ.get("AUTO_SEND", "1") not in ("0", "false", "no"))

    def simulate(lead_ids: list[str], mode: str) -> int:   # demo only: producer answers from ground truth
        return simulate_replies(ctx.mailbox, TruthStore.from_leadgen(ctx.settings.leadgen_url, lead_ids), lead_ids, mode)

    return create_app(ctx, simulate=simulate)
