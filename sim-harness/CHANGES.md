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
