# Skills, tools and hit list

## Implemented

Only capabilities an agent can be given are listed. The model does not choose among them: the pipeline invokes each one under a fixed condition (D20, D25), so "when it fires" is a pipeline condition, not a model decision. The deterministic stages (normalizer, gap classifier, playbook engine, derivation and conflict rules, orchestrator, eval harness) are architecture, not skills; they are described in [ARCHITECTURE.md](ARCHITECTURE.md).

| Skill / tool | What it does | When it fires |
|---|---|---|
| **Field fetch** (mock CRM, KYC, replacement cost, PPC, geo/fire risk) | Fills system-owned fields | when a field is missing and the map says fetch |
| **Imagery / listing lookup + interpreter** (Claude) | Reads Maps/Zillow evidence text into a value; "nothing seen" applies the playbook default, anything unclear is asked | pool and gate fields |
| **Email composer** (Claude) | One merged, minimal follow-up with conditional questions; validated, retried, template fallback | when asks remain |
| **Reply parser** (Claude for free text) | Maps a reply to fields; "N/A" is remembered so nothing is re-asked | on each inbound reply |
| **Summarizer** (Claude) | Plain-language "what passes, what is outstanding, what I need from you" per lead | every decision round |
| **`encode-protocol`** (Agent Skill, build-time; `.claude/skills/encode-protocol/SKILL.md`) | Turns a playbook diagram image into a validated JSON decision tree: maps labels to registry fields, duplicates shared nodes, logs judgement calls, updates the manifest | when a coding agent is given a new diagram. This is the only skill in the formal Agent Skills sense; it is used to build the playbook, not at run time |

Playbooks encoded: swimming pools, general plumbing, water heaters, roof class, siding, trusts and LLCs (quote stage; the post-bind half is encoded but disabled).

## Hit list (prioritised)

1. **Run it with Claude and an email-quality rubric.** Everything model-facing is unmeasured. This is cheapest, and every later item depends on trusting the edges.
2. **The remaining playbooks, in order of how often the lead generator and real queues hit them:** electrical, PC 9 and 10, fire simulation (feeds roof class, so it needs `depends_on` ordering in the manifest), replacement cost, occupancy, profile/KYC, post and pier. This is the largest coverage gain; the encode-protocol skill makes each one much cheaper. Coverage matters more than polish because a lead outside the encoded set cannot be quoted.
3. **Real integrations with dynamic query construction** (D25): address normalisation and geocoding, entity matching, per-vendor adapters, model-assisted source selection with code validation. Without this the "fetch" skills are demos.
4. **Underwriter feedback loop:** overrides into the eval set, and underwriter-editable protocols and judgement calls (today they are JSON files). This is what lets the underwriter tackle "the next layer of complexity" without an engineer.
5. **Ask prioritisation and cap.** A 20-question email is correct and unpleasant. Ranking asks, or splitting by who can answer (homeowner vs agent vs internal team), is a product decision worth user research first.
6. **Follow-up cadence and durable workflow:** nudges on silence, escalation after N days, Temporal for multi-day waits, recipient routing. The POC models the wait; it does not model time.
7. **Conditions tracker:** quote conditions carry deadlines and fallbacks ("confirm Class A within 60 days or decline"). Track and enforce after the quote.
8. **Auth and roles, notifications, batch actions, audit export.**

Back to [README](../README.md).
