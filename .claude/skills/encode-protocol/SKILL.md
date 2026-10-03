---
name: encode-protocol
description: Encode a UW protocol decision-flow diagram (PNG in sim-harness/protocols/img/) into a validated JSON decision tree in sim-harness/protocols/. Use when the user adds a new protocol screenshot or asks to encode/re-encode a protocol.
---

# Encode a protocol diagram

Input: `sim-harness/protocols/img/<topic>.png`. Output: `sim-harness/protocols/<topic>.json`. Reference example: `swimming_pools.json`. Read `DECISIONS.md` first (D1-D3, D6).

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
   - `field` (canonical)
   - `check`: explicit expression (e.g. `pool_type == "Inground"`)
   - `branches`
   - `on_unexpected`: where to go for a value no branch covers (e.g. conflicting data) - normally an underwriter-review outcome, never a silent default
8. **Outcomes** are defined once in an `outcomes` table; leaves reference them by name. Each has a `decision` (quote / quote_with_conditions / escalate / decline) plus any conditions.
9. **Overlays** (rules that apply on top of the main tree, e.g. endorsements) go in `overlay_rules`.
10. **Ambiguity:** never silently guess. Record every ambiguous reading, typo, or assumption in `open_questions` for the underwriter to confirm.

## Process
1. Read image -> list nodes/edges/callouts.
2. Look up candidate fields in the registry (grep the field names/labels/`requiredWhen`).
3. Draft the JSON per the rules above.
4. Run the protocol linter if it exists (every `field` is in the registry or flagged; branch keys valid for field type; leaves reference defined outcomes; every node has `question`/`check`/`on_unexpected`).
5. Add/update field-resolution map entries for the fields and callouts involved.
6. Report to the user: fields used, new non-registry fields (D3), and `open_questions`.
