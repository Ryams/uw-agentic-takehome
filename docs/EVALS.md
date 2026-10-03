# Eval loop and iteration plan

`make eval` runs every set through the **real orchestrator** and grades each lead against ground truth.

- **Expected result** = the same protocol engine run on the lead's clean truth (`clean_fields`). That holds protocol logic constant, so a score isolates resolution, asking, escalation and email behaviour. Frozen hand-written expectations on fixed cases are cross-checked against it (a mismatch is reported as *stale*).
- **Sets (D17).** *Seeded:* `s42-mixed`, `s7-hard`, `s101-hard`, `s13-medium` (40 leads), with their composition recorded so generator drift is flagged. *Fixed:* 43 hand-built cases, one per protocol leaf and numeric boundary, plus lookup scenarios (not found / ambiguous / service down), vendor failures, conflicts and a near-miss, partial and no replies. Generated queues alone leave many branches untouched (`evals/COVERAGE_GAPS.md` lists what, and what is still open).
- **Metrics.** `unsafe_quote_rate` (auto-quoted something wrong; the one that matters most), state and decision accuracy, over- and under-escalation, conflict recall and false conflicts, `blocker_recall`, `unneeded_ask_rate`, one-email-first-round, emails per lead, rounds to close, accuracy of auto-resolved values by method, LLM calls and tokens per lead.
- **Slices (D18).** Every metric overall and per protocol, outcome, failure mode, archetype, tier, scenario and boundary, with `n`, so a number on 2 leads is not mistaken for one on 40.
- **Provenance (D10).** Each row of `evals/results.csv` carries the git hash (with a dirty marker and diff hash), every component's content-driven version, the model config, and the run's own settings (reply rounds, world, vendor profile, auto-send, SDK versions). `python -m evals.compare RUN_A RUN_B` prints component changes, run-setting changes, and only the metrics that moved.
- **Regression gate.** `tests/test_evals.py` fails if any fixed case regresses, if a frozen expectation goes stale, or if a seeded set drifts.

**The loop has already paid off.** The first fixed-set run (`f937702`) exposed an unsafe-quote failure: ambiguous imagery or a down listing service was treated as "no pool". It was fixed (D24) and the compare run shows the effect:

```
unsafe_quote_rate  0.024 -> 0.000     decision_correct 0.966 -> 1.000
emails_per_lead    0.699 -> 0.747     (the cost: two leads now need a reply round)
```

Building the set also found a normalizer bug that would have re-asked a pool-fence question forever, and a report bug (D23). The generated data never reached either.

**Caveat on current numbers.** They come from the offline rule-based stand-in for the model edges: they measure the deterministic pipeline, saturate on the seeded sets, and say nothing about Claude. Rows are marked `offline` in the CSV.

## Iteration plan

1. **Baseline Claude** (needs a key): `make eval`, then `compare` against the offline row. Expect movement in lookup accuracy, derive accuracy, one-email-first-round and the model-written summaries. Any new `unsafe_quote` is fixed before anything else.
2. **Add an email-quality rubric**, LLM-judged and calibrated on a few underwriter-labelled emails. Today the eval grades email *structure* (what was asked, how many), not wording or tone.
3. **Close the coverage gaps**: wrong-value, free-text and off-topic replies, the `noisy` vendor profile as a set, longer reply chains.
4. **Grow the fixed set from real underwriter overrides.** Every override and its note is already stored. Each becomes a candidate fixed case ("the agent proposed X, the underwriter did Y, because Z"), reviewed with the underwriter before it enters the set.
5. **Change one thing at a time**, with the compare output pasted into the decision log. Prompt, model, map and protocol edits all bump component versions automatically (pre-commit hook), so a regression points at one component.
6. **Track cost and latency** next to quality (tokens per lead are already recorded) before changing models or effort.

Back to [README](../README.md). Coverage gaps: [evals/COVERAGE_GAPS.md](../evals/COVERAGE_GAPS.md).
