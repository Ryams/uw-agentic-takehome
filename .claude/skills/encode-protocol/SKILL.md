---
name: encode-protocol
description: Encode a UW protocol decision-flow diagram (PNG in sim-harness/protocols/img/) into a validated JSON decision tree in sim-harness/protocols/. Use when the user adds a new protocol screenshot or asks to encode/re-encode a protocol.
---

# Encode a protocol diagram

Input: `sim-harness/protocols/img/<topic>.png`. Output: `sim-harness/protocols/<topic>.json`. Reference example: `swimming_pools.json`. Read `DECISIONS.md` first (D1-D3, D6-D8) and `sim-harness/protocols/JUDGEMENT_CALLS.md`.

## Rules
1. **Read the image** (Read tool). List every box, arrow, and callout before writing JSON.
2. **Duplicate shared nodes** per path; the result is a pure tree, no merging or cross-references (D2).
3. **Map English labels to canonical registry fields** (`sim-harness/shared/field_registry.json`) at encoding time. Never invent field names. Use the registry's types/options for branch keys (select options verbatim, `true`/`false` for toggles).
4. **Keep the protocol pure:** nodes describe the decision only. No fetch/lookup/ask/LLM hints. Value resolution (fetch, lookup, ask producer, defer to bind, derive, conflict checks) belongs to the separate field-resolution map (`shared/field_resolution.json`), not here (D6).
5. **Fields not in the registry** that the diagram needs: mark `field_status: "NOT IN REGISTRY - ask producer (DECISIONS.md D3)"` (or state a default and rationale if obvious). Add an entry for it to the field-resolution map.
6. **Diagram callouts** (e.g. "if missing check Google Maps/Zillow, else assume no") are resolution rules: move them to the field-resolution map for the affected fields; leave only a short `notes` reference in the protocol.
7. **Every decision node has:**
   - `id`
   - `question` (the diagram's original English wording)
   - `fields`: list of canonical registry fields the node reads (always a list)
   - `branches`: ordered list of `{label, when, then}`; `when` is an explicit expression (grammar: `==, !=, >, >=, <, <=, in (...), and, or, not`, true/false, quoted strings, field names), `then` is a child node or `{outcome}`. Use the same list form for selects, toggles, numeric thresholds, and compound conditions.
   - `on_unexpected`: `{outcome}` for a value no branch covers (e.g. conflicting data) - normally an underwriter-review outcome, never a silent default
   - Numeric thresholds: diagrams say "older/newer than N" and leave exactly-N undefined; encode one side inclusive and record the boundary in JUDGEMENT_CALLS.md.
   - Dead-end boxes (no outgoing arrow/outcome): encode the most likely outcome, add `diagram_gap` on the branch, and record it in JUDGEMENT_CALLS.md.
8. **Outcomes** are defined once in an `outcomes` table; leaves reference them by name. Each has a `decision` (quote / quote_with_conditions / escalate / decline / cancel) plus any conditions; add `stage: "post_bind"` for outcomes that only occur after bind.
8b. **Structure:** top level has `applies_when`, `outcomes`, and either a single `tree` (stage `quote`) or `components: [{id, stage, tree}]` when lifecycle stages differ. Post-bind components are marked `stage: "post_bind"`, `evaluated_in_poc: false`, and their non-registry fields are NOT asked at quote time.
9. **Overlays** (rules that apply on top of the main tree, e.g. endorsements) go in `overlay_rules`.
10. **Judgement calls:** never silently guess. Record every ambiguous reading, dead end, boundary choice, typo, or assumption in ONE place: `sim-harness/protocols/JUDGEMENT_CALLS.md`, in a section for the protocol (id prefix per protocol, e.g. GP-1), with status assumed/confirmed/overruled and a one-line justification. Do NOT use per-file `open_questions`; a protocol file's `status` just points to the log. Calls must be justifiable for the demo, not necessarily confirmed first.
11. **One image, several protocols:** if the diagram root splits into independent branches (e.g. plumbing: General Plumbing / Water Heaters), write one protocol file per branch (all with the same `source_image`). Do not use per-file `components`/`combine`; combining results across protocols is engine config (JUDGEMENT_CALLS.md G-1). Within a file, use `components` only to separate lifecycle stages (`quote` vs `post_bind`; the engine only runs `quote`).

## Process
1. Read image -> list nodes/edges/callouts.
2. Look up candidate fields in the registry (grep the field names/labels/`requiredWhen`).
3. Draft the JSON per the rules above.
4. Run the protocol linter if it exists (every `field` is in the registry or flagged; branch keys valid for field type; leaves reference defined outcomes; every node has `question`/`check`/`on_unexpected`).
5. Add/update field-resolution map entries for the fields and callouts involved.
6. Report to the user: fields used, new non-registry fields (D3), and the judgement calls added to JUDGEMENT_CALLS.md.
