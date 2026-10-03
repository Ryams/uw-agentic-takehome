# Judgement calls in protocol encodings

Every place the diagram was ambiguous, silent, or needed interpretation to encode. One section per protocol. Each call must be justifiable for the demo; the underwriter can overturn any of them (then update the protocol JSON and mark the call **overruled**).

Status: **assumed** (our call) | **confirmed** (UW agreed) | **overruled** (UW changed it).

Cross-protocol calls are under "Global".

## Global
- **G-1 Combining results (assumed):** when several protocols apply to a lead, the final result is the most restrictive decision (decline > escalate > quote_with_conditions > quote), conditions merged and de-duplicated. *Why:* the diagrams never say; most-restrictive is the conservative reading. Lives in engine config, not in protocol files.
- **G-2 One image, several protocols (assumed):** when a diagram's root splits into independent branches (e.g. plumbing), each branch is its own protocol file.
- **G-3 Lifecycle stage (assumed):** each protocol component has a `stage` (`quote` by default, or `post_bind`). The engine only evaluates `stage: quote`. Post-bind components are encoded for completeness but not run in the POC.
- **G-4 Post-bind fields not asked at quote time (assumed, extends D3):** fields that do not exist until after bind are never requested from the producer during quote (see DECISIONS.md D7).
- **G-5 New decision type `cancel` (assumed):** for post-bind cancellation outcomes.
- **G-6 Encoding conventions:** shared diagram nodes duplicated per path (D2); typos read as: "UWing Period" = underwriting period, "orher" = other.

## swimming_pools (SP)
- **SP-1 (assumed):** The Fenced branch is a yes/no question: yes (self-locking gate or safety cover) -> OK to quote; no -> Require secured cover.
- **SP-2 (assumed):** Slides/diving boards are an overlay (Limitation of Liability endorsement) applied on top of the inground/above-ground result, not an exclusive branch.
- **SP-3 (assumed):** "Accept w/ Recommendation for Secure Cover" is a quote with a non-binding recommendation, not a UW-review flag.
- **SP-4 (assumed, D3):** `pool_fence_self_locking_or_safety_cover` is not in the registry -> asked of the producer.
- **SP-5 (assumed):** "Gated community or multi-acre" maps to the registry field `is_gated_community` (its label already says "gated community or multi-acre property").

## general_plumbing (GP)
- **GP-1 (assumed):** "Rounded account" = the insured has a primary policy with Stand (`has_primary_policy_with_stand == true`). "Tier one broker" = `broker_tier == "Tier 1"`. Either one satisfies the question. *Why:* "rounded" most plausibly means a bundled account; both fields are system-owned so no producer ask is needed.
- **GP-2 (assumed):** Boundary: "older than 30" is `> 30`; "newer than 30" is `<= 30`, so exactly 30 counts as newer and no value is uncovered.
- **GP-3 (assumed):** Missing broker tier / primary-policy values are fetched (system-owned); if unresolved the protocol is blocked, not defaulted.

## water_heaters (WH)
- **WH-1 (assumed):** Tank heater "Newer than 10 years" has no outgoing arrow in the diagram; treated as OK to quote (mirrors "Newer than 30 years").
- **WH-2 (assumed):** Boundary: "older than 10" is `> 10`; "newer than 10" is `<= 10`.
- **WH-3 (assumed):** The water-heater "Require Inspection within First Term" is the same condition as the general-plumbing inspection (one `REQUIRE_PLUMBING_INSPECTION`); if both trigger, the condition appears once.
- **WH-4 (assumed):** Same "Tier one broker or rounded account" mapping as GP-1.
- **WH-5 (confirmed by registry):** Tankless heaters skip age/location (those fields are only required when `water_heater_type = Tank`).

## trusts_and_llcs (TL)
- **TL-1 (assumed):** The diagram is mostly a post-bind process, split into `trusts_and_llcs_quote` (enabled) and `trusts_and_llcs_post_bind` (disabled), see manifest. Only the first step is evaluated at quote time: a trust-owned property gets the condition "require Trust & LLC questionnaire within 30 days of bind". The rest is encoded as a `post_bind` component and not run.
- **TL-2 (assumed):** The protocol is triggered by `residence_held_in_trust == true`. The registry has no LLC field; the toggle ("owned by a trust") is treated as covering LLC ownership. *Why:* avoids asking every producer a new question; revisit if LLC cases are missed.
- **TL-3 (assumed):** The double-headed arrow between "Unacceptable Exposures Found" and "Cancel w/in UWing Period" means Found -> Cancel.
- **TL-4 (assumed):** The "Ensure only assets owned by the Trust/LLC are covered / Exclude Cov C / Premises Liability Only" box is a post-bind outcome of "No Unacceptable Exposures".
- **TL-5 (open):** "Change to Premises Liability Only" and "THO policy" are unclear; copied verbatim into the condition text.
- **TL-6 (assumed):** Post-bind fields `trust_llc_questionnaire_status`, `trust_llc_unacceptable_exposure_found` (derived from Income, Sales, non-household employees, commercial properties, aviation, watercraft) are not in the registry and are not asked at quote time (G-4).

## Engine (G-7+)
- **G-7 (assumed):** "No pool" (`pool_type == "None"`) means the pools protocol does not apply (no outcome), rather than an explicit "OK to quote" branch.
- **G-9 (assumed):** Conditional asks are collected for every non-ruled-out path (D13), including deep paths (e.g. pool type unknown -> security -> fence detail). The email may therefore contain several "if ..." questions; the composer should keep them short and grouped.
- **G-8 (assumed):** A decline short-circuits other protocols and suppresses further asks (D11). *Why:* matches the "one crisp message" goal; a declined lead has nothing to gain from more questions. Risk: if the decline was driven by a wrong/assumed value the underwriter sees only that protocol's evidence.

## Field resolution (R-*)
- **R-1 (assumed):** The pools callout ("if missing check Google Maps and Zillow, else assume no") applies to the five pool-protocol fields: `pool_type`, `pool_security`, `pool_has_diving_board_or_slide`, `above_ground_pool_ladder`, `is_gated_community`. This overrides the registry's default "ask the producer" for those fields. Assumed values when nothing is found: no pool (`None`), `Unfenced` (conservative: "no fence seen"), no slide/board, no ladder, not gated. *Risk:* assuming Unfenced leads to a "require secured cover" condition without asking the producer; the evidence and assumption are surfaced to the underwriter.
- **R-2 (assumed):** `pool_fence_self_locking_or_safety_cover` (not in registry) is asked of the producer (D3), but only when a fence is actually present.
- **R-3 (assumed):** Derivation tables for `roof_classification` and `siding_classification` are taken from the generator's own consistency tables (the Roof Class and Siding diagrams are not encoded yet). Replace when those protocols are encoded.
- **R-4 (assumed):** System-owned fields are grouped under stub tools by data source: `crm_account` (broker_tier, has_primary_policy_with_stand), `kyc_provider` (kyc_score), `rce_provider` (replacement_cost), `ppc_lookup` (protection_class, falls back to assuming PC 9 per registry missingDefault), `geo_risk` (road_access, min_distance_to_neighbor_ft, slope_angle_deg, p_f, vegetation_clearance).
- **R-5 (assumed):** "Unknown" is treated as missing for every field, including fields where it is a registered option (road_access, vegetation_clearance, fire_department_type, fire_dept_response_time).
- **R-6 (assumed):** Knob-and-tube: assume present if `year_built < 1950` (registry missingDefault), otherwise ask the producer.
- **R-7 (assumed):** Cross-field conflict rules: unoccupied 3+ months but Primary; short-term rental but Primary; owner-occupied type but Secondary use; zero residents on an owner-occupied dwelling; roof year in the future (year taken from the lead's received_at); service under 60 amps; zero acreage. Derived from the failure modes the generator injects; thresholds are ours.

## roof_class (RC)
- **RC-1 (assumed):** The diagram's "Unknown Class" branch is modelled as a derivation of `roof_classification` when it is not provided, not as a third protocol branch. *Why:* it is equivalent: Unknown + (noncombustible / metal / composition shingles installed within 20 years) = "Assume Class A, Okay to Quote" = Class A; Unknown + combustible material has exactly the Non-Class A outcomes at every P(F) range (<= .15 OK; .15-.50 confirm within first term; > .50 confirm within 60 days or decline). Keeping the protocol pure (D6) and putting the "assume" logic in `field_resolution.json` also means the dashboard shows it as an explained assumption ("assumed Class A: noncombustible roofing"). Derivation rules: Clay/Concrete Tile, Slate, Metal Shingles/Sheets, Standing Seam Metal -> Class A; Architecture Shingles / Asphalt Fiberglass Composite replaced within 20 years -> Class A; Wood Shake/Shingle -> Class C; anything else -> Class B (Non-Class A). Replaces R-3 for roofs.
- **RC-2 (assumed):** The Non-Class A band is drawn "> .15 < .50" and "> .50", leaving exactly .50 undefined. Encoded as `> .15 and <= .50` (matches the Unknown-class band), `> .50`.
- **RC-3 (assumed):** Composition shingles older than 20 years are not covered by either list in the diagram; treated as not assumable, i.e. Class B / Non-Class A (conservative). "Other" material (flat membrane, tar & gravel, unknown) also -> Class B.
- **RC-4 (assumed):** "Within the past 20 years" is inclusive (`roof_replacement_year >= current_year - 20`); `current_year` comes from the lead's received_at.
- **RC-5 (assumed):** "Require confirmation of Class A or replacement within first 60 days **or Decline**" is a `quote_with_conditions` outcome whose condition says "otherwise decline"; it is not an immediate decline, and not an underwriter-discretion fork. Enforcing the deadline is out of scope (conditions tracker is on the hit list).
- **RC-6 (assumed):** "Acceptable evidence" (roofing permits, contractor invoices, manufacturer documentation, inspection findings, other) is captured as a sticky note and as `acceptable_evidence` on the two confirmation outcomes, so the dashboard/composer can cite it.
- **RC-7 (assumed):** "Non-Class A" = registry values Class B or Class C.
- **RC-8 (assumed):** The Non-Class A confirmation boxes lack the evidence list that the Unknown-class boxes show; the same list is attached to both (same outcome text).

## siding (SD)
- **SD-1 (assumed):** Branch on the registry's `siding_classification` (A-D, derived from material): A/B/C = "Non-combustible", D = "Wood Shake or Shingle" (class D covers `Wood Shake / Shingle` and plain `Wood`). The diagram names materials, not classes; Vinyl and Aluminum/Steel/Other (class C) are therefore treated as non-combustible. Alternative: branch on `siding_material` directly and send Vinyl/Wood/Other to UW review.
- **SD-2 (assumed):** The siding_classification derivation table is still borrowed from the generator's consistency tables (R-3 now covers siding only; the diagram does not define classes).
- **SD-3 (assumed):** "Class A" in "Require confirmation of Class A or replacement" means Class A siding.
- **SD-4 (assumed):** "UWing period" = underwriting period; the P(F) > .50 outcome is the stricter (earlier) deadline vs "first term".
- **SD-5 (assumed):** Siding P(F) band edges: `<= .15`, `> .15 and <= .50`, `> .50` (exactly as drawn).

## Global additions
- **G-10 (assumed):** Sticky notes and callouts are captured verbatim in the protocol's `sticky_notes` (with `applies_to` and, where they became machine rules, `handled_in`), so an LLM reasoning over a missing/ambiguous value can read the playbook text (D15).

## LLM edges (L-*)
- **L-1 (assumed):** Ambiguous or unclear imagery does not set a value. The playbook default ("assume no") applies, and the assumption is flagged low-confidence for the underwriter instead of asking the producer. *Why:* the callout says assume no when nothing conclusive is seen; asking would add emails the playbook does not call for. Revisit if wrong assumptions are costly.
- **L-2 (assumed):** The default model for all three LLM tasks is `claude-sonnet-5-5` at `low` effort (cost-conscious, tasks are short and constrained); override per task via env. The eval milestone should compare models/efforts on the same fixed sets.
- **L-3 (assumed):** The composer addresses the producer generically ("Hello,"); quote conditions (e.g. "confirm Class A within 60 days") appear on the dashboard and quote, not in the follow-up email, which asks only for missing information.

## Orchestration (O-*)
- **O-1 / R-8 (assumed):** A producer-editable field marked "conditional" in the registry but with no `requiredWhen` is not required to quote (the registry gives no condition and the generator's ground truth leaves it empty, e.g. `opening_protection`, `listed_for_sale`); a protocol can still ask for it. System-owned conditional fields without a condition (e.g. `replacement_cost`) are still auto-fetched.
- **O-2 (assumed):** Conflicts go to the underwriter ("verify"), not into the producer email. Alternative: also ask the producer to confirm the conflicting values in the same email.
- **O-3 (assumed):** An email still goes out for missing producer info when a lead is also flagged for the underwriter (conflict/escalation); the underwriter sees both. Alternative: hold the email until the underwriter acts.
- **O-4 (assumed):** Assuming a value changes what is required: assuming PC 9 (PPC lookup failed) makes the four PC 9/10 conditional fields required, so the producer is asked for them.
- **O-5 (assumed):** Default recipient for follow-ups is the lead's `owner_email` when present, else a generic producer address; routing to agent vs homeowner vs internal team is on the backlog.
- **O-6 (assumed):** A conditional ask that is only relevant on a deeper path gets its own group with the full chain ("If Water Heater Type is Tank and Water Heater Age > 10").

## Lookup outcomes (L-4, eval-driven)

| id | call | status |
|---|---|---|
| L-4 | The pools sticky note says "if missing check google maps and zillow, if you don't see anything assume no". Only a lookup that *looked and saw nothing* (`not_found` / `nothing_seen`) takes the assume-no default. **Ambiguous imagery, a listing-service outage, or a low-confidence reading is not "seeing nothing"**: the field is asked of the producer instead of assumed. Found by the fixed eval set (`pool-ambiguous-imagery`, `pool-listing-service-down`): the old behaviour auto-quoted an above-ground pool as no pool. | assumed (D24) |
