# Backlog

Legend: **[core]** needed for the core loop, **[next]** if time allows, **[hit list]** document only (not built in the POC).

## Harness / test data
- [core] Modify generator to store clean lead in `debug_json` (D5), gated by `DEBUG=true`
- [core] Reply simulator: answers outbound emails from clean data (`POST /emails/{id}/reply` or poller)
- [next] Imperfect replies: partial, wrong or off-topic answers to test re-triage

## Pre-processing
- [core] Normalizer: type coercion (e.g. string coverage values), sentinel values (`"Unknown"`) to null
- [core] One-time `shared/field_resolution.json`: per-field fetch / lookup (+ default) / ask producer / defer / derive / conflict rules (no skill needed; generate once, review with UW)
- [core] Registry-driven gap classifier: auto-fetch / ask producer / defer to bind / verify
- [core] Conditional-requirement evaluation (`requiredWhen`) and `derivedFrom` dependency ordering
- [next] Conflict/plausibility checks (e.g. future roof year, 11 months unoccupied but "primary")

## Protocol engine
- [core] `protocols/manifest.json` (done; linter checks files <-> manifest); `encode-protocol` skill (done) and re-encode `swimming_pools.json` to the D6 shape
- [core] Protocol linter: fields exist in registry/resolution map, branch keys valid for field type, leaves reference outcomes, nodes have question/check/on_unexpected
- [core] JSON tree evaluator: field lookup, branch, outcome, "blocked on unknown field" result
- [core] Encode 3-4 protocols (pools done; pick others from Occupancy, Roof Class, Post & Pier, Electrical, Plumbing)
- [core] Standard result shape: outcome, conditions, blocking fields, evidence trail
- [hit list] Remaining ~8 protocols, UW-editable protocol authoring

## Tools / integrations (mostly stubbed)
- [core] Data-fetch stubs for system-owned fields (protection class, replacement cost, roof class, etc.), reading from clean data
- [core] Lookup stub for "check Google Maps / Zillow, else assume no" (returns found / not found / ambiguous)
- [hit list] Real integrations: satellite imagery, property data providers, KYC, fire-dept/PC lookup

## Agent / LLM
- [core] Email composer: one consolidated, minimal follow-up per lead, merged across all blocking protocols
- [core] Per-lead reasoning summary for the underwriter
- [core] Parallel per-lead processing in the orchestrator
- [core] Evidence interpretation for lookups (e.g. read a listing description or image caption)
- [next] Recipient routing (homeowner vs agent vs internal team)

## Orchestration / state
- [core] SQLite schema: leads, runs, decisions + evidence, emails, UW actions
- [core] Idempotent `process_lead()`: a reply re-triggers re-evaluation from current state
- [core] Queue ordering: quick wins first, escalations flagged
- [next] Follow-up cadence: no duplicate emails, nudge on no response
- [hit list] Durable workflow engine (Temporal) for multi-day reply cycles

## Human-in-the-loop / UI
- [core] FastAPI: start run, list leads, lead detail, approve / edit / override
- [core] Web page with three groups: Ready to quote / Awaiting reply / Needs your decision
- [core] Lead card: proposed action, evidence, uncertainty, email preview
- [core] Capture UW overrides as structured feedback
- [next] Autonomy settings (which actions are auto-sent vs held for approval)
- [hit list] Batch actions, auth/roles, notifications

## Evals
- [core] Grader using answer key + clean data: path correct, blockers identified
- [core] Follow-up quality: minimal (no over-asking, no missed blockers), bind-only not chased, no unnecessary escalation
- [core] Multi-seed runner with summary report and diffs between runs
- [next] LLM-judged email quality rubric
- [next] End-to-end metrics: replies needed to close, time-to-resolution
- [hit list] Feed UW overrides back into the eval set

## Packaging / docs
- [core] One-command setup (docker compose + run script), `.env.example`, no committed secrets
- [core] README: architecture, trade-offs, "changes to provided tooling" (D5)
- [core] Skills list (implemented) + prioritized hit list
- [core] Iteration plan for evals
