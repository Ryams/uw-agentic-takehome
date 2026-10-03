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
