# Implementation Plan (working copy)

> Saved from the planning session. **Progress checklist** (update after each milestone; pause after each for a context check):
> - [x] 0. Harness changes (clean_fields) + project skeleton (done; see sim-harness/CHANGES.md)
> - [x] 0b. Versioning + run records (done; D10)
> - [x] 1. Protocols + linter + engine (done; D11) (encoded: pools, general_plumbing, water_heaters, roof_class, siding, trusts_and_llcs_quote; trusts_and_llcs_post_bind disabled; see protocols/manifest.json, D9)
> - [x] 2. Pre-processing + resolution (done; D12)
> - [ ] 3. Tools (world, fetch, lookup)
> - [ ] 4. LLM edges
> - [ ] 5. Orchestrator + state + reply loop
> - [ ] 6. API + web UI
> - [ ] 7. Evals
> - [ ] 8. Docs

# Implementation Plan: UW Agentic Assistant POC

## Context
Take-home: an agent that takes a queue of ~10 messy property leads and drives each to "quote" or "one sharp follow-up email", with the underwriter in control, and an eval loop. Time box 5-6h (per the brief). Decisions already made are in `DECISIONS.md` (D1-D6) and the scope in `BACKLOG.md` (**[core]** items). This plan orders the work and names the files. Everything is committed through `12fe0f6`; nothing below is started.

Key design (from D4/D6): deterministic pipeline `normalize -> resolve values -> walk protocols -> decide/compose`, hand-rolled Python + SQLite, FastAPI thin layer, Anthropic SDK for the LLM edges only (evidence interpretation, email, summary).

## Findings from exploring sim-harness that shape the plan
- Generator: `generate_lead()` in `leadgen/generator.py:269-306` builds `_base_lead` (line 272), applies archetypes (279-282), then `_apply_perturbations` (284). `debug_json` is a free-form blob, so no DB migration.
- `LeadDebug` (`shared/schema.py:39`) and `get_lead_debug` (`leadgen/main.py:155-166`) build fields explicitly, so a new key must be added to both.
- **Gotcha:** a snapshot of the base lead is NOT the right truth: archetypes rewrite fields (`pool_hazard`, `post_and_pier`, etc.) and conditional fields are `None` in the base. Decision: snapshot **after archetype sets, with archetype `_null` calls recording the intended value** (edit `leadgen/archetypes.py` `_null`/`_set` helpers), before perturbation.
- Mailbox has no reply/thread columns. Replies will be stored as normal rows with `metadata {"direction":"inbound","in_reply_to":<id>}`; no schema change to their service.
- Containers lack `httpx`; our agent app runs outside compose and talks to both services over localhost (8081 leadgen, 8025 mailbox). Eval runs need leadgen started with `DEBUG=true`.
- `shared/registry.py` has reusable helpers: `meta`, `is_system_owned`, `required_level`, `derived_map`, `select_options`, `validate_value`. Missing: a `requiredWhen` parser (free-text strings like `pool_type != None`, `x in (a, b)`) - we write one.
- Archetypes exercised by leadgen: electrical, PC 9/10, wildfire (roof/siding), replacement cost, occupancy, trust/LLC, post & pier, plumbing/water heater, pools, KYC. Choose the 3 additional protocols from these.

## Phases (cut order at the bottom)

### 0. Harness changes + skeleton
- `sim-harness/leadgen/archetypes.py`, `generator.py`, `shared/schema.py`, `leadgen/main.py`: add `clean_fields` (truth) to `debug_json`/`LeadDebug`, DEBUG-gated (D5). Keep the diff minimal; document in README "Changes to provided tooling".
- New app at repo root `uw_agent/` with `pyproject.toml` (uv), `.env.example` (`ANTHROPIC_API_KEY`, service URLs), `python-dotenv`, fail-fast on missing key. Run via `uv run` / a `Makefile` (`make up`, `make run`, `make eval`).
- Package layout: `uw_agent/{config,db,normalize,resolution,protocols/{engine,linter},tools/{world,fetch,lookup},llm,composer,orchestrator,replysim,api}.py`, `web/`, `evals/`, `tests/`. Protocol and resolution JSON stay in `sim-harness/protocols/` and `sim-harness/shared/field_resolution.json`.

### 0b. Versioning + run records (built early so every later run is stamped)
Goal: for any run (especially evals) know exactly what code/config produced it.
- **Components** (`uw_agent/versioning.py` holds the registry mapping component name -> the files it owns): `normalizer`, `resolver` (resolution.py + `field_resolution.json`), `protocol_engine` (engine.py), one `protocol:<topic>` per protocol JSON, `lookup_tools`, `evidence_interpreter`, `email_composer`, `summarizer`, `orchestrator`, `grader`, plus `field_registry` and LLM config (model id, prompt files, temperature).
- **Content-driven, human-readable versions:** each component's version is an integer counter starting at 0 that increments whenever the content hash of its owned files changes. Committed manifest `versions/components.json`: `{component: {version, content_hash, files}}`.
- **Pre-commit hook** (`.githooks/pre-commit`, enabled via `git config core.hooksPath .githooks`, set up by `make setup` and documented in README): recompute each component's hash; if it differs from the manifest, bump that component's version by 1, rewrite `versions/components.json`, and `git add` it. A CI/pytest check (`tests/test_versions.py`) fails if the manifest is stale vs. the working tree, covering anyone who skipped the hook.
- **System version** = git short commit hash at run time. If the working tree has uncommitted changes: `<hash>-dirty-<diff hash>`, and component versions for changed components are reported as `<manifest version>+dirty` with their live hash, so un-committed eval runs are still identifiable. Fallback without git: hash of the component manifest.
- **System -> components mapping:** on startup/run, compute the live component versions+hashes and register `(system_version -> components_json)` in a `system_versions` SQLite table (idempotent). Because `versions/components.json` is committed, `git show <commit>:versions/components.json` reconstructs the mapping for any historical commit even if the DB is reset.
- Every row in `runs` stores `system_version`; decisions inherit it via the run. UI lead cards show "decided by v<system_version>".
- **Eval run record:** `evals/results.csv` (committed, append-only). One row per (eval_run_id, seed): `eval_run_id, timestamp, system_version, dirty, seed, difficulty, n_leads, <metric columns: path_accuracy, blocker_recall, blocker_precision, email_minimality, over_escalation_rate, bind_only_chased, ...>`, plus `components_json` (compact) and eval-set descriptors (seed, generator config hash, generator patch version, grader version). The grader itself is a versioned component. A `evals/compare.py` prints the diff between two runs by system version.
- The runs/eval UI and API expose `system_version` (header on lead cards: "decided by v<hash>").

### 1. Protocols + linter
- Re-encode `protocols/swimming_pools.json` to D6 shape using the `encode-protocol` skill (explicit `check`, `on_unexpected`, callout moved out).
- Encode 3 more as the user pastes diagrams (suggest electrical, post & pier, occupancy; they map to archetypes).
- `protocols/linter.py`: fields in registry or flagged NOT IN REGISTRY, branch keys valid via `registry.select_options`/type, leaves reference outcomes, nodes have question/check/on_unexpected.
- `protocols/engine.py`: pure `evaluate(protocol, resolved_values) -> Result{outcome, conditions, blocked_on[], path[]}`; overlay rules; `on_unexpected` handling.

### 2. Pre-processing + resolution
- `sim-harness/shared/field_resolution.json` (one-time, reviewed with UW): per field `on_missing` (fetch tool / lookup + default / ask_producer / defer_to_bind / derive), `on_conflict` plausibility rules; entries for NOT-IN-REGISTRY protocol fields (D3).
- `normalize.py`: type coercion (string coverage), sentinels (`"Unknown"`) to null.
- `resolution.py`: gap classifier using registry metadata + `requiredWhen` parser + `derived_map` ordering -> per-lead `{resolved_values, producer_asks[], deferred[], conflicts[], lookups_pending}`.

### 3. Tools
- `tools/world.py`: the simulated outside world (third-party data providers, replies). It reads leadgen `clean_fields` over HTTP. Boundary rule: only `world`, `replysim`, and `evals` may touch truth; the workflow gets data only through tool interfaces (enforce with an import test).
- `tools/fetch.py` stubs for system-owned fields (protection class, replacement cost, roof classification, p_f, etc.); `tools/lookup.py` stub for "Maps/Zillow" returning found / not found / ambiguous evidence text.

### 4. LLM edges - Anthropic SDK, structured outputs
- `llm.py`: client wrapper; model configurable (default a Sonnet-class model), JSON-schema tool output, retries.
- Evidence interpretation (lookup text -> value + confidence + rationale); `composer.py`: ONE consolidated email per lead from asks + blockers (minimal, ordered, no bind-only fields); per-lead reasoning summary.

### 5. Orchestrator + state + reply loop
- `db.py` SQLite: `runs` (with `system_version`), `system_versions`, `leads`, `decisions` (state, evidence, path), `emails`, `uw_actions`.
- **Clean slate at the start of every run:** `run_queue()` first calls a single `reset_world()` in `tools/world.py` that does `POST mailbox:8025/reset` (clears all emails; the mailbox persists across restarts and is keyed only by `lead_id`, so a same-seed re-run would otherwise see stale emails) and then generates the queue (`POST leadgen:8081/queue?seed=...`, which already replaces the prior queue). Single-loop demo only, so no cross-run email history is kept in the mailbox; our own SQLite keeps the durable record (emails sent/received are copied into our `emails` table, scoped by `run_id`). Reply polling and the "one email per lead" check only consider emails from the current run.
- Blocked derived fields (engine `blocked_on` such as `roof_classification`) are expanded into their root inputs via `resolution.analyze().pending` (roof_material, roof_replacement_year) before asks are built; conditional blockers (D13) and `pending` entries merge into one conditional-ask list.
- `orchestrator.py`: `run_queue()` -> parallel `process_lead()` (asyncio/thread pool); idempotent; states `ready_to_quote | awaiting_reply | needs_uw`; queue ordering; no duplicate emails.
- `replysim.py`: on outbound email, answer from truth (optionally imperfect later), post inbound row to mailbox; `poll_replies()` re-triggers `process_lead()`.

### 6. API + web UI
- `api.py` (FastAPI): `POST /runs`, `GET /leads`, `GET /leads/{id}`, `POST /leads/{id}/approve|edit|override`, `POST /replies/poll`.
- `web/` single static page: 3 groups (Ready to quote / Awaiting reply / Needs your decision), lead card (proposed action, evidence/path, uncertainty, email preview), approve/edit/override, overrides stored as structured feedback. Quote conditions with deadlines/fallbacks ("confirm Class A within 60 days or decline") appear as "wait to quote" items on the card.

### 7. Evals
- `evals/` runner: for seeds [42, ...], call `reset_world()` before EVERY seed (mailbox cleared, queue regenerated) so seeds can't contaminate each other, then generate queue with `DEBUG=true`, run workflow, grade against truth + answer key: correct path, correct blockers, minimal email (no over-asking/missed asks, bind-only not chased), no unnecessary escalation, optional LLM email-quality rubric. Output a table/JSON report and append to `evals/results.csv` stamped with `system_version` (see 0b), one row per (set, seed, slice) so metrics are reported overall and per slice (D18); `evals/compare.py` diffs two runs per slice.
- Harden (D17): fixed eval sets in `evals/sets/` (hand-built leads covering every outcome/boundary in `evals/COVERAGE_GAPS.md`, with ground truth + frozen expected results + tags), seeded sets with a recorded composition, and a per-run coverage table; set identity stamped in `results.csv`.
- Compute the expected outcome by running the SAME engine on `clean_fields` (truth) - so grading isolates resolution/email quality from protocol logic.

### 8. Docs
- README: one-command setup, architecture + trade-offs (D4/D6), "Changes to provided tooling" (D5), skills list + hit list, eval iteration plan. Update `DECISIONS.md` with any new decisions.

## Cut order if time runs short
LLM-judged email rubric -> imperfect replies -> UW override feedback loop -> 4th protocol -> parallelism (run sequentially).

## Verification
1. `docker compose up --build` with `DEBUG=true SEED=42`; `POST /queue?seed=42`; confirm `GET /leads/{id}/debug` returns `clean_fields` and `GET /leads/{id}` does not.
2. `pytest`: linter passes on every protocol; engine unit tests per protocol (leaf coverage); normalize/resolution tests with the example payload; import test that the workflow never imports truth modules.
3. `make run` on seed 42: all 10 leads land in a state; each non-ready lead has exactly one email in the mailbox viewer (http://localhost:8025); reply polling advances awaiting leads.
4. `make eval` on 3 seeds produces the report; spot-check two leads manually against the answer key.
5. Isolation: run the same seed twice back-to-back; the second run starts with an empty mailbox (`GET /emails` is empty right after reset) and ends with exactly one email per non-ready lead, not two. Run two different seeds in one eval invocation and confirm no emails carry over between them.
6. Open the web page, approve/override a lead, confirm it persists in SQLite.
7. Versioning: run an eval, confirm a new row in `evals/results.csv` with `system_version` and that `system_versions`/`manifests.jsonl` maps it to component versions. Edit a prompt and commit -> the hook bumps that component's version in `versions/components.json`; bypass the hook (`--no-verify`) -> `tests/test_versions.py` fails. Make an uncommitted change -> version shows `-dirty` with a different diff hash.

## Open items for the user
- Versioning: confirmed hybrid (content-hash driven, integer counters from 0 bumped by a pre-commit hook; system version = git hash). Eval results are a committed CSV.
- Which diagrams will be added (to pick the 3 extra protocols).
- Confirm the `open_questions` in `swimming_pools.json` before re-encoding.
