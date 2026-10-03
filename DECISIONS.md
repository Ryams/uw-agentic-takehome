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

## D7 - Protocol lifecycle stage: only `quote`-stage components run; post-bind fields are not asked at quote time (2026-10-03)

**Decision:** Each protocol (or component within one) has a `stage`: `quote` (default) or `post_bind`. The engine evaluates only `quote`. Post-bind stages are still encoded (documentation, hit list) with `evaluated_in_poc: false`. Fields that only exist after bind (e.g. trust/LLC questionnaire results) are never requested from the producer at quote time; this is a scoped exception to D3. Triggered by `trusts_and_llcs`.

**Why:** The Trusts & LLCs diagram is mostly post-bind (30-day questionnaire, exposure screen, cancel). Simulating bind events is out of scope for the demo, but the stage concept costs almost nothing and shows the design.

## D8 - All encoding judgement calls live in one log, organized by protocol (2026-10-03)

**Decision:** Every ambiguity, dead end, boundary, mapping or assumption made while encoding is recorded in `sim-harness/protocols/JUDGEMENT_CALLS.md` (per-protocol sections, ids like GP-1, status assumed/confirmed/overruled), not in per-file `open_questions`. Independent root branches of one diagram become separate protocol files; combining results across protocols (most restrictive, conditions merged) is engine config (G-1), not per-file.

**Why:** One place for the underwriter to review and overturn; protocol files stay pure; supports the review conversation about trade-offs.

## D9 - Protocol manifest with stage/enabled/order/tags and split provenance (2026-10-03)

**Decision:** `sim-harness/protocols/manifest.json` lists every protocol with `stage` (`quote`|`post_bind`), `enabled`, `order`, `tags`, and `origin` (`source_image`, `diagram`, `split_from`, `split_note`). The engine runs only `enabled && stage == quote`. Whenever a diagram is split, each piece keeps its origin so we can find and update sibling encodings later. Maintained through the `encode-protocol` skill; the linter checks files <-> manifest consistency.

**Why:** Makes "encoded but not run" explicit (trusts post-bind), enables short-circuiting by `order` (don't email about a pool if plumbing already declines), and keeps traceability from JSON back to the source diagram.

**Applied:** `trusts_and_llcs` split into `trusts_and_llcs_quote` (enabled) and `trusts_and_llcs_post_bind` (disabled); plumbing split into `general_plumbing` and `water_heaters`.

## D10 - Component/system versioning and eval run records (2026-10-03)

**Decision:**
- Components (normalizer, resolver, protocol_engine, protocol_manifest, one `protocol:<name>` per protocol, field_registry, lookup_tools, llm_client, evidence_interpreter, email_composer, summarizer, orchestrator, grader, and `leadgen_generator`) each own a set of file globs (`uw_agent/versioning.py`). A component's version is an integer starting at 0 that increments when the content hash of its files changes. Not-yet-written components hash as `empty` (v0) and bump when their files first appear.
- `versions/components.json` is the committed manifest. The pre-commit hook (`.githooks/pre-commit`, enabled by `make setup`) bumps changed components and stages the manifest; `tests/test_versions.py::test_committed_manifest_is_current` catches `--no-verify` commits.
- System version = git short hash; `+dirty-<fingerprint>` when tracked files under `uw_agent/ sim-harness/ evals/ versions/` differ from HEAD or any component hash differs from the manifest (fingerprint = hash of all live component hashes). Dirty components show as `<version>+dirty`.
- `system_versions` SQLite table (system version -> components JSON; `register_system_version()` is idempotent; `db.py` will call it) plus `git show <commit>:versions/components.json` for history.
- Eval results: `evals/results.csv` (committed, append-only), one row per (eval_run_id, seed): system version, dirty flag, seed, difficulty, n_leads, metric columns (new metrics widen the file; old rows get blanks), component versions, runtime config (model id etc., kept out of file hashes because it comes from env), and eval-set descriptors (generator + grader versions). `python -m evals.compare RUN_A RUN_B` prints component changes and metric deltas.
- The generator is a tracked component because a seed only means the same queue for the same generator code/config (we modified it, D5).

**Trade-offs (accepted):** any content change (even whitespace/comments) bumps the version (content-driven by design). The hook hashes the working tree, not the staged snapshot, so partial staging can mismatch (the test catches it). Model id and other env runtime settings are recorded per run, not versioned as files.

## D11 - Protocol engine semantics (2026-10-03)

**Decision:**
- Expressions (`when`, `applies_when`, registry `requiredWhen`, conflict rules) use one tiny safe language (`uw_agent/protocols/expr.py`, no `eval`) with **three-valued (Kleene) logic**: a comparison on a missing field is UNKNOWN; `UNKNOWN and False` is False, `UNKNOWN or True` is True. The registry's free-text `requiredWhen` strings are converted into the same language.
- Walker: at each node the first branch that is not False decides. True -> take it; UNKNOWN -> stop and return `blocked_on` (the missing fields in that branch), never guess; none true -> the node's `on_unexpected` outcome (normally UW review).
- Overlays are evaluated after the tree. An overlay that is True adds its conditions (and can only make the decision more restrictive); an UNKNOWN overlay adds its missing fields to `blocked_on` so asks are consolidated into one message. A blocked protocol has no outcome/conditions.
- `applies_when` gates a protocol: False -> `not_applicable` (e.g. no pool); UNKNOWN -> blocked.
- Across protocols (G-1/D9): run enabled `quote`-stage protocols in manifest `order`; final decision = most restrictive (decline > escalate > quote_with_conditions > quote); conditions merged and de-duplicated; `blocked_on` is the union. **A decline short-circuits**: remaining protocols are skipped and the decision stands even if other fields are unknown (no more asks for a doomed lead). Any blocked protocol makes the lead `blocked` (asks come before escalation/quote) unless a decline short-circuited.
- Outcomes can carry a non-binding `recommendation` (separate from binding `condition`s).
- The linter (`python -m uw_agent.protocols.linter`; runs in pytest) checks manifest consistency, fields in registry or flagged NOT IN REGISTRY (and present in the resolution map once it exists), `when` expressions parse and use only the node's fields, literals valid for the field type/options, outcomes defined, unique node ids, `on_unexpected` present; it warns on uncovered options and unused outcomes. A reachability test brute-forces each protocol over its field domains and asserts every defined outcome is reachable.

## D12 - Pre-processing and field-resolution design (2026-10-03)

**Decision:**
- `sim-harness/shared/field_resolution.json` is the one-time, reviewable map of how every field is obtained: an ordered step chain per field (`fetch{tool}`, `lookup{tool,default}`, `derive{from,table}`, `assume{value,when?}`, `ask_producer`, `defer_to_bind`, `post_bind_only`), generated from registry metadata and then hand-edited with playbook overrides (pools callout, PC 9 default, knob-and-tube default). It also holds cross-field `conflicts` rules (same expression language as protocols). Non-registry protocol fields have entries with a `label` and `type` (D3/D7).
- `uw_agent/normalize.py`: coerces types by registry kind, treats sentinels (`""`, `Unknown`, `N/A`, ...) as missing even where "Unknown" is a registered option (road_access, fire_department_type, ...), accepts a real select option "None", and records notes and `invalid` values (unusable values become missing, never silently kept).
- `uw_agent/resolution.py::analyze()` is a pure function (no tool calls): applies derivations, classifies each missing registry field as a **gap** (needed now, with its step chain), **pending** (conditional requirement depends on a still-missing field, e.g. water_heater_age_years waits on water_heater_type), or **deferred** (bind-only, never chased), and evaluates **conflicts** (present but inconsistent -> underwriter verification). A conflict rule whose inputs are missing stays UNKNOWN and fires once those fields are resolved. Protocol `blocked_on` fields reuse the same step chains via `gap_for()`.
- The orchestrator (milestone 5) executes steps; only `ask_producer` steps become email asks, and only after fetch/lookup/derive/assume steps fail to produce a value.

**Why:** keeps "how do we get this value" in one reviewable file instead of scattered across protocols and prompts, and keeps the analysis deterministic and testable.

## D13 - Collect downstream blockers on all live paths so one email carries every ask (2026-10-03)

**Decision:** When the walker is blocked at a node, the engine also explores every branch under it that has not been ruled out (`when` evaluates False -> skipped) and returns `conditional_blockers`: each downstream field we would need, with the ordered `only_if` branch conditions under which it matters. Rules:
- Mirrors the walker: at a node, the first non-False branch decides. If it is True the path is determined (follow only it, no extra condition); if UNKNOWN, every non-False branch is a potential path, tagged with its `when`.
- If `applies_when` is UNKNOWN, the whole tree (and unknown overlay fields) is explored under the gate condition (e.g. the pool questions only matter if a pool exists).
- Overlays/independent fields remain unconditional blockers. Fields that are unconditional for any protocol are dropped from the lead-level conditional list; the lead-level list is de-duplicated per (protocol, field, conditions). Decided, not-applicable and declined (short-circuited) protocols contribute nothing.
- The composer (milestone 4) renders conditional asks only for fields that must be asked of the producer, phrased conditionally ("If the pool is fenced: does it have a self-locking gate or a safety cover?"), so the producer answers everything in one reply. Fetch/lookup/derive steps for conditional fields may run speculatively or lazily (orchestrator's choice). The registry-level `pending` list from `resolution.analyze()` (conditional fields waiting on a parent) is merged into the same conditional-ask list.
- Evals count a conditional ask as correct when its condition matches the true value; it is not "over-asking" (it is the mechanism that avoids a second email).

**Why:** The spec asks for a single follow-up message containing everything missing, not a drip of rounds. Previously asks for fields behind an unanswered question surfaced only after the reply.

## D14 - Playbook supersedes the registry's generic rules (2026-10-03)

**Decision:** The **registry** (`shared/field_registry.json`) is the generic data dictionary: required levels, `editableByProducer`, `requiredWhen`, and a generic triage rule (missing + producer-editable + required -> email). The **playbook** is the underwriters' decision flows (the FigJam diagrams we encode). When a playbook instruction is specific to a field/situation and conflicts with the registry's generic instruction, the playbook wins. First applied to the pools callout ("check Google Maps and Zillow, else assume no"), which overrides "ask the producer" for the five pool fields (R-1). The registry itself defers to the FigJam for `missingDefault` values.

## D15 - Capture sticky notes and callouts as additional info in protocol JSON (2026-10-03)

**Decision:** Every sticky note, callout, and explanatory bullet box in a diagram is stored verbatim in the protocol's `sticky_notes: [{text, applies_to, handled_in?}]` (and, where tied to an outcome, e.g. acceptable evidence, on that outcome). Where a note became a machine rule (resolution map, derive rules) `handled_in` points to it. *Why:* an LLM that reasons about missing/ambiguous values (evidence interpretation, composer, reviewer) can read the original playbook text, not only our encoding. Linter checks the structure; the `encode-protocol` skill requires it. Retrofitted on pools; first used on roof_class.

## D16 - Derived values: rules + arithmetic; "Unknown" branches become derivations (2026-10-03)

**Decision:**
- The expression language gained `+` / `-` on numeric operands (e.g. `roof_replacement_year >= current_year - 20`).
- `derive` steps in the resolution map can use ordered `rules [{when, value, why}]` over any fields (first non-False rule decides; UNKNOWN -> the field is **pending** on the missing inputs, which become their own gaps), in addition to the single-field `table` form. Derived values are returned in `Analysis.derived` with their `why`, so the UI/email can show them as explained assumptions.
- A diagram branch such as Roof Class's "Unknown Class" (class not provided -> assume from material) is modelled as the derivation of the underlying field, not as a protocol branch, when it is equivalent to the known-value branches (RC-1). Protocols stay pure and branch only on resolved values.

## D17 - Fixed, reproducible eval sets with a known breakdown (2026-10-03)

**Decision:** The eval milestone includes a "harden the tests" step. Evals run on (a) **fixed eval sets** committed under `evals/sets/`: hand-built leads (raw fields + ground-truth `clean_fields` + tags + frozen expected result) covering every protocol outcome and numeric boundary listed in `evals/COVERAGE_GAPS.md`, plus lookup-outcome and imperfect-reply scenarios; and (b) **seeded generator sets** (e.g. seeds 42/7/101 at stated difficulty) whose composition (archetypes, expected outcome per protocol) is recorded alongside the set, so results are deterministic and comparable across versions. Every eval run reports a **coverage table** (which protocol outcomes/branches the set exercised) so gaps are visible. Eval-set identity (set name, generator version, seed) is stamped in `evals/results.csv` (D10).

**Why:** generated queues skew toward a few outcomes (see COVERAGE_GAPS.md); metrics on them alone would hide untested branches.

## D18 - Eval metrics are reported per slice of test-case categories (2026-10-03)

**Decision:** Every eval lead carries tags, and metrics are computed overall AND per slice so we can see where a system version is strong or weak. Slice dimensions (all derived from tags/answer key, so seeded sets get them automatically): `protocol` (which protocol the lead exercises), `outcome` (expected outcome per protocol), `failure_mode` (missing producer field, missing system-owned field, derived value, conflict, bind-only, boundary, lookup scenario, imperfect reply), `archetype`, `tier`/difficulty, and `eval_set`. `evals/results.csv` has one row per (run, eval set, seed, slice) with `slice` = `overall` or `<dimension>=<value>` and `n_leads` = slice size; `evals/compare.py` prints per-slice deltas with n so small, noisy slices are visible. Fixed eval sets (D17) are designed with a known tag breakdown so each slice has enough cases.

## D19 - Third-party tools are a mock vendors service over leadgen-written SQLite tables (2026-10-03)

**Decision:** No tool ever calls a real external system. The simulated vendors (CRM, KYC, replacement cost, PPC, geo risk, Maps/Zillow listings) are a small read-only FastAPI service (`sim-harness/vendors`, docker-compose, port 8082) over vendor-shaped SQLite tables that leadgen writes from its ground truth when it generates a queue. The agent's `tools/fetch.py` and `tools/lookup.py` are thin httpx clients of that service (URL from `VENDORS_URL`), returning `found | not_found | unavailable` (and `ambiguous` for listings); listing search returns evidence text, not values. The workflow cannot reach ground truth: only `uw_agent/truth.py` (loads `clean_fields` from leadgen's DEBUG endpoint) and the reply simulator/evals may touch it; `tests/test_tools.py` enforces this with an import/string scan. `uw_agent/harness.py::reset_world` clears the mailbox and regenerates the queue (leadgen rewrites the vendor tables). Per-lead failure scenarios (vendor down, no record, ambiguous imagery) are rows in `vendor_overrides`; `VENDOR_PROFILE=noisy` adds seeded unreliability. Supersedes the earlier in-process idea.

**Why:** Mirrors real integrations (network boundary, failure modes, evidence-as-text) and keeps the answer key isolated, while staying free, offline and deterministic. The harness change is documented in `sim-harness/CHANGES.md`.

## D20 - LLM edges: thin structured-output client, deterministic guards, fallbacks (2026-10-03)

**Decision:**
- `uw_agent/llm.py` is the only Claude client: one `structured()` call per task (Messages API, reply constrained by `output_config.format` JSON schema from a pydantic model, `effort` set per task, all three tasks at `low`). No tools, no agent loop, no forced tool use (rejected by Sonnet 5.5), no sampling params. Every call is recorded (tokens, model, effort, request id); models and efforts go into the run record (`runtime_config()`, D10). The default model is `claude-sonnet-5-5` with per-task overrides (`ANTHROPIC_MODEL_INTERPRETER|COMPOSER|SUMMARIZER`). A missing key fails fast. Refusals/truncation/API errors raise typed errors; every caller degrades instead of crashing the lead.
- **Interpreter:** deterministic code decides whether to call the model at all (`not_found`/`unavailable` lookups never reach it), the model returns `value | nothing_seen | unclear` + confidence + rationale, code validates the value against the registry options (anything outside is `unclear`), ambiguous imagery caps confidence at `low`. The model never chooses the "assume no" default; the resolution map does.
- **Composer:** code builds the `EmailPlan` (unconditional asks + conditional groups, D13) and decides WHAT to ask; the model only words each question and the lead-ins; code assembles the body, appends answer options, and validates that the reply covers exactly the planned (field, group) pairs (one retry with feedback, then a deterministic template, which is also the eval baseline). Refusals fall back to the template. Never sends an email with nothing to ask.
- **Summarizer:** paraphrases a deterministic report (facts only; falls back to a deterministic summary on error/empty output).
- Server-side refusal fallbacks (beta) are NOT enabled: the inputs are ordinary insurance text, and refusals already degrade to deterministic fallbacks. Tests use a scripted fake model; real model quality is measured by the evals. `make smoke-llm` runs a live check (needs a key).

**Why:** keeps decisions deterministic and measurable (the model reads and words; code decides and validates), and keeps the system usable (and testable) when the model is unavailable.

## D21 - Orchestration semantics, reply loop, and the reply parser (2026-10-03)

**Decision:**
- **Pipeline (`uw_agent/orchestrator.py`):** per lead: normalize -> loop {analyze -> resolve each needed field via its step chain (`executor.resolve_field`: fetch / lookup+interpret / assume) -> evaluate protocols} until nothing new is learned -> decide -> compose and send at most one email -> persist a decision round with the full report and summary. `process_lead` is idempotent: it re-evaluates from the raw lead plus all stored answers, so a reply simply re-triggers it. Leads run in parallel (thread pool); an unexpected exception becomes a `needs_uw` decision (`internal_error`), never a crashed queue.
- **States:** `ready_to_quote` (everything resolved, protocols decided); `awaiting_reply` (producer asks outstanding, email sent); `needs_uw` (a human decision is needed: conflicts, protocol escalation, a proposed decline, system data that could not be fetched and has no default, a producer N/A that blocks a protocol, too many emails, or a drafted email awaiting approval). `needs_uw` wins over `awaiting_reply`: an email still goes out for missing producer info even when the lead is also flagged. Priority for the underwriter queue: quick wins (ready, no conditions) -> ready with conditions -> declines -> decisions needed -> system problems -> awaiting. The decision on an `awaiting_reply` lead is marked `provisional`.
- **Asks:** unconditional asks = needed fields whose chain ends in `ask_producer` after fetch/lookup/assume steps fail; conditional asks (D13) from engine paths, registry `requiredWhen` (when the parent is being asked), and "assume only if" fields (e.g. knob-and-tube: asked only if year_built is not < 1950); a field needed anywhere is asked once, unconditionally. **System-owned fields are never asked of a human**: failed fetch -> assume if the map has a default, else `needs_uw`. Conflicts (present but inconsistent) go to the underwriter, not into the producer email. A decline suppresses all asks (D11).
- **Emails:** one per distinct ask set (hash); the same ask set is never re-sent; a reply that leaves some asks unanswered triggers one follow-up for just the remainder; at most `max_emails` (3) per lead, then `needs_uw`. `auto_send=False` stores drafts and routes the lead to the underwriter. Outbound mailbox metadata carries the ask numbering (`direction`, `asks`), which the reply simulator uses.
- **Reply loop:** `poll_replies` ingests inbound mailbox rows linked by `in_reply_to`, parses them, stores answers, and re-processes those leads. **Reply parser (LLM edge #4, `replies.py`):** deterministic first pass over numbered lines ("3. Yes") coerced against registry types/options (exact or longest option match; yes/no; numbers); an LLM second pass only for answers the first pass could not read; every value is validated and nothing unvalidated is stored. "N/A" answers are recorded as not-applicable and never re-asked (if a protocol needs the value it escalates).
- **State:** SQLite (`uw_agent/db.py`): runs, leads, per-round decisions (full report + summary), answers, emails, uw_actions, llm_calls, and the D10 `system_versions` registry. LLM calls are attributed per lead under parallel workers (thread-local last-call + a per-lead tagged view).
- **Offline mode:** `OfflineLLM` (rule-based evidence reading; composer/summarizer use their deterministic fallbacks) lets the whole loop run with no API key (`make demo-offline`); it is a demo/test stand-in, not a quality baseline.
- **Reply simulator** (`replysim.py`) answers from ground truth (conditional questions only if their condition holds in truth, else N/A); modes `complete` and `partial`.

**Verified:** on seeds 42/7/101 (mixed and hard), in-process with the offline interpreter and complete replies, all 60 leads reach the same decision and conditions as the engine on ground truth after at most two email rounds; and live against the docker stack (seed 42): 6 ready, 4 needs-UW for genuine injected conflicts, after one reply round.

## D22 - FastAPI layer and underwriter UI (2026-10-03)

**Decision:**
- `uw_agent/api.py` is a thin HTTP layer over the orchestrator and SQLite; `uw_agent/web/index.html` is a single static page (no build step, light/dark, responsive) served at `/`. `make ui` / `make ui-offline` start it on :8090 (`uw_agent/server.py` factory; `UW_OFFLINE=1` for the rule-based stand-in, `AUTO_SEND=0` for review-first emails).
- **What the underwriter sees:** a queue grouped as *Ready to quote* (quick wins first), *Needs your decision* (conflict, proposed decline, protocol escalation, system data unavailable, email draft to review), *Awaiting reply*, and a collapsed *Actioned*. Each card shows the agent's one-line headline, proposed decision (marked *provisional* while questions are outstanding), and chips for conditions to wait on, assumptions (low-confidence ones highlighted), conflicts, and outstanding questions. The detail panel shows: why it needs you, wait-to-quote conditions (D-plan item 4) and non-binding recommendations, the follow-up email(s) and replies, assumptions and derived values (each with a "correct this value" action), the playbook path per protocol, the data gathered (fetches, lookup evidence, tool failures), history, and your previous actions.
- **What the underwriter can do (each stored as a structured `uw_actions` row with the agent's state/decision at the time, so overrides can feed the evals):** approve the proposal (quote or decline), override the decision (requires a note), provide/correct a field value (stored as a `uw` answer, then the lead is re-evaluated: a correction of an assumption removes it), review/edit/send a drafted email, re-run, add a note, and one-click *approve quick wins* (ready, decision `quote`, no conditions, no low-confidence assumptions).
- **Autonomy is a switch, not a code change:** *auto-send follow-ups* on (default) sends routine producer asks immediately; off drafts them and routes the lead to *Needs your decision* so the underwriter reviews and dispatches. Quotes and declines are always proposals the underwriter approves.
- **Demo controls:** "Run morning queue" (seed/difficulty), "Simulate replies" (the ground-truth producer simulator) and "Check replies".
- API tested in-process (`tests/test_api.py`); the page's JavaScript is parse-checked and its render functions are exercised against live API data with a stub DOM, but it has NOT been visually verified in a browser (the browser extension was unavailable).

**Addendum (D22): the email cycle is closed on demand, per lead.** "Run morning queue" processes the queue and sends the follow-ups, then stops: real replies take hours or days, so *Awaiting reply* is a real state the underwriter should see. For demos, the lead detail panel shows a **Simulate producer reply** button (with a mode: answers everything / leaves one unanswered) for any lead with an unanswered sent email; it runs the ground-truth producer simulator for just that lead and the agent processes the reply, moving it on. A bulk "Simulate replies" button remains in the header. Both are demo-only (the server injects the simulator; the API module never touches ground truth). An automatic "auto-reply after the run" option was considered and rejected as less representative of production.

**Addendum (D22): waiting leads must say what passes and what is outstanding.** A lead waiting on the producer can have most playbook checks already passing, and the first UI/summary version hid that (raw protocol ids and outcome codes, a truncated list, no list of the questions). Now: the report carries `provisional_decision` (most restrictive result among checks decided so far) and, for every ask, `needed_for` (the playbook checks it unblocks; a blocked derived field such as roof class maps to its real inputs, roof material and year). The summary (deterministic fallback and the model prompt) must separate "pass with the data so far" from "still waiting on ... (needs ...)" in plain language, never truncated. The UI shows a "What we're waiting on" block with each question and what it unblocks, "so far: Quote (questions outstanding)" instead of "no decision yet", and plain check labels (passes / passes with condition / waiting / n/a).


## D23 - Eval harness: oracle = same engine on truth, slice-first reporting, fixed + seeded sets (2026-10-03)

**Decision:** `evals/` runs a set through the real orchestrator and grades each lead against ground truth (`clean_fields`), never against the system's own output. The **expected result is the same protocol engine run on the lead's clean truth**, so protocol logic is held constant and the grade isolates resolution, asking, escalation and email behaviour. Frozen hand-written expectations on fixed cases are cross-checked against that oracle (a mismatch is reported as a *stale* expectation, never silently re-baselined).
- **Sets:** four seeded generator sets (`s42-mixed`, `s7-hard`, `s101-hard`, `s13-medium`, 40 leads) with their composition recorded in `evals/sets/seeded.json` (a run flags drift), plus the `fixed` set (`evals/sets/fixed.json`, built by `python -m evals.build_fixed_set` from hand-written cases): one case per protocol leaf and numeric boundary in `COVERAGE_GAPS.md`, lookup scenarios (not found / ambiguous / service down), vendor failures, conflicts, a near-miss, and imperfect replies (partial, none). The build fails if the engine disagrees with the hand-written outcome, then freezes the engine's full result.
- **Expected state:** `needs_uw` when the truth is a decline/escalate or is itself inconsistent (occupancy archetype) or a conflict was injected; else `ready_to_quote`. Fixed cases may override (vendor outage -> `needs_uw`; no reply -> `awaiting_reply`).
- **Metrics (per lead, micro-averaged per slice):** `state_correct`, `decision_correct` (decision + conditions, only where gradable), `unsafe_quote_rate` (auto-quoted something wrong: the metric that matters most), over/under-escalation, conflict recall / false conflicts, `blocker_recall` (producer-askable fields the truth path needs and nothing supplied, that were asked), `unneeded_ask_rate`, `cond_ask_na_rate` (cost of the one-email design), `repeat_ask_rate`, bind-only chased, one-email-first-round, emails per lead, rounds to close, per-method accuracy of auto-resolved values (fetch / lookup / assume / derive), LLM calls and tokens per lead.
- **Slices (D18):** protocol, outcome, failure_mode, archetype, tier, scenario, boundary. Fixed cases slice by their *focus* protocol (what the case is about); seeded leads by every protocol that decided. Every run also pools all sets under `eval_set=ALL`. Rows go to `evals/results.csv` (one per run, set, seed, slice) stamped with the system version; per-lead detail to the git-ignored `evals/runs/<id>.json`.
- **Worlds:** in-process by default (generator -> vendor tables -> vendors service via TestClient -> in-memory mailbox -> truth reply simulator): hermetic, a fresh mailbox and DB per set. `--live` runs the seeded sets against the docker stack with `reset_world` before each seed. Fixed cases are in-process only (hand-built leads cannot be injected into leadgen).
- **Replies:** every lead with an unanswered email gets a reply each round (even leads already with the underwriter); up to 3 rounds. `partial` leaves the last question unanswered in round 1 only; `none` never replies.

**Found while building it (fixed in the same milestone):** (1) playbook-only fields such as `pool_fence_self_locking_or_safety_cover` were dropped by the normalizer as "unknown field", so a producer's answer never reached the engine and a fenced inground pool would be re-asked forever (the generator never produces that path; D3 extension fields are now first-class in `normalize`); (2) the final report lost its `derived` list (a derived value is already set on the second analysis pass); (3) `records.append_eval_row` shadowed its `eval_set` argument.

**Limits:** offline runs use the rule-based stand-in for the three LLM edges, so they test the deterministic pipeline and saturate on the seeded sets; they say nothing about Claude. Rows are marked `offline` in `runtime_config_json`. A run with the real model is one command once `ANTHROPIC_API_KEY` is set (`make eval`).

## D24 - Inconclusive lookups are asked, not assumed (2026-10-03)

**Decision:** In `executor.resolve_field`, a lookup that is ambiguous, unavailable or read with low confidence no longer falls back to the playbook default; the producer is asked (when the field is producer-answerable, which every lookup field is). Only a definitive "nothing seen" takes the assume-no default (JUDGEMENT_CALLS L-4). The assumption record no longer carries `low_confidence`; the inconclusive lookup is kept in the evidence log (`inconclusive: true`).

**Why:** the first fixed-set eval run (system `f937702`, 53 leads) had two **unsafe quotes**: `pool-ambiguous-imagery` and `pool-listing-service-down` both auto-quoted a real above-ground / unfenced pool as "no pool". Wrong assumptions that hide a hazard are the costliest error this system can make; an extra question is cheap.

**Measured effect (offline stand-in, fixed set):** unsafe quotes 2 -> 0, decision accuracy 0.95 -> 1.00; emails per lead 0.44 -> 0.53 (the two leads now need a reply round). Seeded sets unchanged (their pool leads never hit an inconclusive lookup). Comparison: `uv run python -m evals.compare <baseline_run_id> <new_run_id>`.

**D23 addendum - run settings are recorded.** Every results row's `runtime_config_json` (and `evals/runs/<id>.json`, key `run_config`) holds the LLM config (models, efforts or `offline`) plus an `eval_run` block: sets run, world (in-process or live), `--llm` flag, max reply rounds, auto-send, max emails per lead, reply-simulator modes, vendor profile and seed, Python and Anthropic SDK versions, and the slice dimensions. `evals/compare.py` prints "Run config changes" next to component changes, so two runs of the same commit with different settings are distinguishable. Rows written before this change carry only the LLM config.
