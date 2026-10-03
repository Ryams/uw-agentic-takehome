# Changes to provided tooling

Documented per the take-home guidance (mention during project review). Decision record: `DECISIONS.md` D5.

## Ground-truth `clean_fields` in the answer key
**What:** `GET /leads/{id}/debug` (still gated by `DEBUG=true`) now also returns `clean_fields`: the archetype-consistent lead before any random nulling/conflicts, with archetype-nulled fields restored to their intended hidden value.

**Why:** The reply simulator and eval grader need ground truth (what the homeowner would actually answer; what the correct path is). The stock debug key only said *which* fields were touched.

**Files:**
- `leadgen/archetypes.py`: `_null()` takes an optional `truth` value (defaults to the pre-null value) and records it on the touch record. Truth values are constants, not RNG draws.
- `leadgen/generator.py`: `generate_lead()` snapshots the lead after archetypes, folds in the `truth` values (`_fold_truth`), strips `truth` from the perturbation records, and stores `debug["clean_fields"]`. The guarantee/retrofit path in `generate_queue()` does the same.
- `shared/schema.py`: `LeadDebug.clean_fields`.
- `leadgen/main.py`: passes `clean_fields` through the debug endpoint. `debug_json` is a free-form blob, so no DB migration.

**Invariants (tested in `tests/test_generator_truth.py`):**
- Seeded queues are unchanged: seed 42 produces a byte-identical queue to the original generator (verified).
- The public `GET /leads/{id}` payload is unchanged and has no truth.
- `clean_fields` validates against the field registry.
- Every always-required field that was nulled has a non-null truth.
- The clean data must only be read by the reply simulator and the eval harness, never by the agent workflow.

## Mock vendors service + vendor tables (D19)
**What:** A new `vendors` service (port 8082 in `docker-compose.yml`) simulates the third parties the agent would call: CRM, KYC, replacement-cost estimator, PPC, geo/fire-risk model, and Maps/Zillow listing search. It is a thin, read-only FastAPI app over vendor-shaped SQLite tables that **leadgen writes whenever it generates a queue** (`crm_accounts`, `kyc_scores`, `rce_estimates`, `ppc_records`, `geo_risk`, `property_listings`, plus a `vendor_overrides` table for per-lead eval scenarios). No real external system is ever called.

**Why:** Gives the agent realistic fetch/lookup tools without exposing the ground truth: the agent only sees vendor responses (404 = no record, 503 = unavailable, listing search returns evidence TEXT for an interpreter to read), while the answer key (`clean_fields`) stays DEBUG-gated and eval-only.

**Files:** `vendors/` (service, Dockerfile, requirements), `leadgen/vendor_data.py` (tables + writers), `shared/vendor_evidence.py` (evidence templates), `leadgen/main.py` (creates tables, writes rows on `POST /queue`, clears them on `/reset`), `docker-compose.yml` (new service, `./data` mounted read-only), `.env.example` (`VENDOR_PROFILE=demo|noisy`, `VENDOR_SEED`).

**Profiles:** `demo` is reliable (a feature that exists is found; absence reads as "nothing seen"); `noisy` adds seeded unavailable / ambiguous / missed results. Per-lead overrides (unavailable | not_found | ambiguous, per vendor or field) come from `vendor_overrides` for hand-built eval cases.
