"""Persistent eval run records (D10): one CSV row per (eval_run_id, seed), stamped with the system version."""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from uw_agent import versioning

RESULTS_CSV = versioning.ROOT / "evals" / "results.csv"
BASE_COLUMNS = ["eval_run_id", "timestamp", "system_version", "dirty", "eval_set", "slice", "seed", "difficulty", "n_leads"]
TAIL_COLUMNS = ["components_json", "runtime_config_json", "eval_set_json"]


def new_eval_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]


def append_eval_row(eval_run_id: str, seed: int, difficulty: str, n_leads: int,
                    metrics: dict[str, Any], runtime_config: Optional[dict[str, Any]] = None,
                    path: Path = RESULTS_CSV, sv: Optional[dict[str, Any]] = None,
                    eval_set: str = "", slice: str = "overall") -> dict[str, Any]:
    """Append one row per (run, eval set, seed, slice). `slice` is "overall" or "<dimension>=<value>"
    (e.g. "protocol=roof_class", "failure_mode=conflict", "tier=hard"); `n_leads` is the slice size.
    New metric columns widen the file (existing rows get blanks)."""
    sv = sv or versioning.system_version()
    eval_set_info = {
        "set": eval_set, "seed": seed, "difficulty": difficulty, "n_leads": n_leads,
        "leadgen_generator": sv["components"].get("leadgen_generator"),
        "grader": sv["components"].get("grader"),
    }
    row: dict[str, Any] = {
        "eval_run_id": eval_run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system_version": sv["system_version"], "dirty": int(sv["dirty"]),
        "eval_set": eval_set, "slice": slice, "seed": seed, "difficulty": difficulty, "n_leads": n_leads,
        **metrics,
        "components_json": json.dumps({n: c["version"] for n, c in sv["components"].items()}, sort_keys=True),
        "runtime_config_json": json.dumps(runtime_config or {}, sort_keys=True),
        "eval_set_json": json.dumps(eval_set_info, sort_keys=True),
    }
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="") as f:
            existing = list(csv.DictReader(f))
    metric_cols: list[str] = []
    for r in existing + [row]:
        for k in r:
            if k not in BASE_COLUMNS + TAIL_COLUMNS and k not in metric_cols:
                metric_cols.append(k)
    cols = BASE_COLUMNS + metric_cols + TAIL_COLUMNS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in existing + [row]:
            w.writerow({c: r.get(c, "") for c in cols})
    return row
