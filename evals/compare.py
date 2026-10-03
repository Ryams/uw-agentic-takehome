"""Diff two eval runs: component version changes + metric deltas.  usage: python -m evals.compare RUN_A RUN_B"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from evals.records import BASE_COLUMNS, RESULTS_CSV, TAIL_COLUMNS


def _rows(run_id: str, path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["eval_run_id"] == run_id]
    if not rows:
        raise SystemExit(f"no rows for eval run {run_id!r} in {path}")
    return rows


def compare(a: str, b: str, path: Path = RESULTS_CSV) -> str:
    ra, rb = _rows(a, path), _rows(b, path)
    out = [f"A: {a}  system {ra[0]['system_version']}", f"B: {b}  system {rb[0]['system_version']}", ""]
    ca, cb = json.loads(ra[0]["components_json"]), json.loads(rb[0]["components_json"])
    changed = [f"  {n}: {ca.get(n)} -> {cb.get(n)}" for n in sorted(set(ca) | set(cb)) if ca.get(n) != cb.get(n)]
    out += ["Component changes:"] + (changed or ["  (none)"])
    metric_cols = [c for c in ra[0] if c not in BASE_COLUMNS + TAIL_COLUMNS]

    def mean(rows, col):  # weighted by slice size so a big seed counts more than a small one
        pairs = [(float(r[col]), int(r["n_leads"])) for r in rows if r.get(col, "") != ""]
        w = sum(n for _, n in pairs)
        return sum(v * n for v, n in pairs) / w if w else None
    # compare the pooled (eval_set=ALL) rows so every slice has one row per run
    ra, rb = [r for r in ra if r["eval_set"] == "ALL"] or ra, [r for r in rb if r["eval_set"] == "ALL"] or rb
    slices = sorted({r["slice"] for r in ra} & {r["slice"] for r in rb}, key=lambda x: (x != "overall", x))
    for sl in slices:  # per-slice deltas (mean over seeds/sets); n shows slice size so small slices are visible
        sa, sb = [r for r in ra if r["slice"] == sl], [r for r in rb if r["slice"] == sl]
        na, nb = sum(int(r["n_leads"]) for r in sa), sum(int(r["n_leads"]) for r in sb)
        lines_before = len(out)
        out += ["", f"Slice {sl}  (n={na} -> {nb}):"]
        for col in metric_cols:
            ma, mb = mean(sa, col), mean(sb, col)
            if ma is not None and mb is not None and abs(mb - ma) > 1e-9:   # only what changed
                out.append(f"  {col}: {ma:.3f} -> {mb:.3f} ({mb - ma:+.3f})")
        if len(out) == lines_before + 2:
            del out[lines_before:]                       # nothing changed in this slice
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print(compare(sys.argv[1], sys.argv[2]))
