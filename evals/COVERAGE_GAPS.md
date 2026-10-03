# Known coverage gaps in generated test data

Found by running the encoded protocols over the ground truth (`clean_fields`) of 400 leads (seeds 1-40, `mixed`, 10 leads each). Generated queues alone leave these protocol outcomes/branches unexercised, so the eval milestone adds hand-built and fixed eval sets (D17) to cover them.

| Area | Never produced by the generator |
|---|---|
| swimming_pools | Above-ground pools (no `REQUIRE_LADDER`, no `OK_TO_QUOTE` via ladder); fenced inground pools (fence detail question never reached); unfenced + gated (`ACCEPT_REC_COVER`). Only unfenced, non-gated -> `REQUIRE_COVER` appears. |
| roof_class | P(F) in (.15, .50] (`CONFIRM_CLASS_A_FIRST_TERM`); Class B roofs; composition shingles older than 20 years; non-wildfire Class C. Only Class A -> OK and Class C with P(F) > .50 appear. |
| siding | P(F) in (.15, .50] (`CONFIRM_CLASS_A_SIDING_FIRST_TERM`); only the > .50 (`UW_PERIOD`) and non-combustible outcomes appear. |
| water_heaters | `DECLINE` (finished-space tank heater, non-Tier-1, no primary policy); tankless rarely matters. Only OK and inspection appear. |
| general_plumbing | Exact boundaries (plumbing age 30/31). |
| all numeric bands | Exact edges: P(F) = .15 and .50, water heater age 10/11, roof year exactly 20 years back. |
| trusts_and_llcs_quote | Trust-owned leads appear, but the "trust name given" vs missing-name asks are only lightly exercised. |
| conflicts | Only the five failure modes the generator injects; none of the other conflict rules (short-term rental vs primary, owner-occupied vs secondary) outside the occupancy archetype. |
| normalizer | Dirty input (numeric strings for select fields, "N/A", mixed case): the generator emits clean types, so these are unit-tested only. |
| lookups / replies | Generator has no notion of lookup outcomes (found / not found / ambiguous) or imperfect replies (partial, wrong, off-topic). |

**Mitigation (eval milestone, D17):** fixed eval sets with a known breakdown, one hand-built lead per protocol leaf and per boundary, plus seeded generator sets with a recorded archetype/outcome breakdown and a coverage report per eval run.
