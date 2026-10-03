# Decision Log

Running log of project decisions. Newest last. Each entry: what we decided, why, and how to apply it.

## D1 - Protocol diagrams are encoded as JSON trees (2026-10-03)

**Decision:** Each FigJam screenshot in `sim-harness/protocols/img/<topic>.png` is encoded as `sim-harness/protocols/<topic>.json`. Reference example: `protocols/swimming_pools.json`.

**Why:** A field-keyed JSON tree can be walked deterministically by code and diffed/reviewed by underwriters. The LLM is used for fuzzy parts (lookups, drafting emails), not for the quote/reject logic.

**How to apply:**
- Each decision node names a registry `field` (from `shared/field_registry.json`) and has `branches` keyed by value.
- Named `outcomes` are defined once in an `outcomes` table; leaves reference them by name.
- Callouts/notes on the diagram (e.g. "if missing, check Google Maps and Zillow, else assume no") go in a `missing_data_policy` block.
- Anything ambiguous in the drawing goes in `open_questions` for the underwriter to confirm. Do not silently guess.
- If a node needs a field that is not in the registry, mark it with `field_status: "NOT IN REGISTRY ..."` and list it in `open_questions`.

## D2 - Duplicate shared diagram nodes; protocols are pure trees (2026-10-03)

**Decision:** When a diagram has a node that multiple paths converge on (merged arrows, a shared "Yes"/"No" box), duplicate that node under each path that reaches it. No merging paths, no cross-references between branches.

**Why:** Crossed/merged paths are confusing to read and to evaluate. Per-path duplication makes every leaf a standalone chain of conditions, which is easier to eval, explain to underwriters, and trace in the agent's reasoning. (Technically this makes it a tree, a special case of a DAG.)

**Cost:** Some repetition of leaf references. Mitigated because outcome content lives once in the `outcomes` table.

**How to apply:** Applied to `swimming_pools.json` (the Fenced branch got its own yes/no children instead of pointing at the shared "Yes" and bottom "No" boxes). Apply the same to every diagram added later. When duplicating, note it in `open_questions` if the original drawing was ambiguous about which paths merge.

## D3 - Decision-relevant data missing from the registry is asked of the producer (2026-10-03)

**Decision:** If a protocol node needs a field that is not in `field_registry.json`, treat it as a producer-supplied field and ask the producer for it, unless there is an obvious default (expected to be rare). Do not silently assume a value.

**Why:** The registry is the contract for leads, but the underwriting playbook can need facts it doesn't capture. Guessing risks wrong quote decisions; asking is cheap and fits the single-clear-follow-up model.

**How to apply:**
- In the protocol JSON, mark the node `field_status: "NOT IN REGISTRY - ask producer"` (or `"NOT IN REGISTRY - default: <value>"` with a stated rationale in the rare default case).
- The agent includes these questions in the one consolidated follow-up email for that lead, alongside any other missing producer fields.
- Remove the corresponding entry from `open_questions` once decided; keep a list of such extra fields so we can propose registry additions later.

Applied to: `pool_fence_self_locking_or_safety_cover` in `swimming_pools.json`.

## D4 - Orchestration is hand-rolled plain Python, not LangGraph/Temporal (2026-10-03)

**Decision:** The workflow is a plain Python orchestrator (`run_queue()` -> `process_lead()` -> deterministic pipeline steps) with state in SQLite; FastAPI is a thin layer for the UI/underwriter actions, not an endpoint per step. LangGraph (framework weight for a small graph) and Temporal (right for production long-running reply cycles, too heavy for a POC) were considered and rejected. LLM calls use the plain Anthropic SDK; the API key comes from a gitignored `.env` / env vars, never committed.

## D5 - Generator modified to store the clean lead for evals (2026-10-03)

**Decision:** `sim-harness/leadgen` is modified (permitted, but MUST be documented and mentioned in the project review) so the pre-perturbation clean fields are stored in `debug_json` alongside the existing answer key. Rejected: re-deriving from the seed (fragile coupling to generator internals) and LLM-invented replies (no ground truth).

**Why:** The reply simulator and the eval grader need ground truth (what the homeowner would actually answer; what the correct path is). The stock debug key only records which fields were perturbed, not their original values.

**Constraint:** The clean data is eval/grader-only. It must stay behind the existing `DEBUG=true` gate and must never be visible to the agent workflow; only the reply simulator and eval harness may read it.

**How to apply:** Keep the diff minimal and note it in the README ("Changes to provided tooling") for the review.

## D6 - Protocols are pure; English labels mapped at encoding time; resolution is a separate field-level map (2026-10-03)

**Decision:**
- Diagram node labels (English) are mapped to canonical registry fields **once, at encoding time** (LLM + human review), not at run time. Each node keeps the original `question` plus an explicit `check` and an `on_unexpected` branch.
- Protocol JSON is a **pure function over resolved values**: no fetch/lookup/ask/LLM hints inside nodes. The runtime walker is deterministic.
- How a value is obtained or validated (fetch, lookup with default, ask producer, defer to bind, derive, conflict/plausibility) lives in a separate **field-resolution map** (`shared/field_resolution.json`), keyed by field, since one field can feed many protocols. Diagram callouts like "check Maps/Zillow, else assume no" go there.
- A **protocol linter** checks every protocol against the registry and the resolution map.
- Pipeline order: normalize -> resolve values -> walk protocols -> decide/compose. LLM use at runtime is limited to interpreting lookup evidence / fuzzy values (resolution step) and writing emails.

**Why:** Auditable, evaluable (a wrong outcome is a wrong value or a wrong tree, never ambiguous which), and avoids repeating/contradicting resolution logic per node.

**How to apply:** Use the `encode-protocol` skill (`.claude/skills/encode-protocol/SKILL.md`). `swimming_pools.json` predates this and needs re-encoding to the new shape (explicit `check`/`on_unexpected`, callout moved to the resolution map).
