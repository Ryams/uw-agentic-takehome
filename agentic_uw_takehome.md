# Stand UW Agentic Assistant

#### **Goals**

This project is designed to evaluate your ability to:

* Leverage agents and LLMs to transform a real underwriting (UW) workflow from a slow, manual process into an efficient, semi-automated one.
* Convert an ambiguous, messy stakeholder problem into a working agentic system—deciding what to automate, what to escalate, and where to keep a human in the loop.
* Design a human-in-the-loop experience that is genuinely *ergonomic* for underwriters: it should simplify their work, not add another tool to babysit.
* Go from zero to a working proof of concept quickly, and make clear, explainable architecture choices along the way.
* Build an eval loop so you can measure and iterate on the quality of the agent's output instead of eyeballing it.

We would like you to **time-box this project to 5-6 hours**. We know you could easily spend 10x that—part of what we're evaluating is how you decide what to cut and what to hand-wave. We are more interested in how you think about the problem than in raw feature count.

Feel free to use any tools, libraries, frameworks, agent SDKs, or LLMs during this exercise. You are also welcome to reach out to us at any time with questions.

# Overview

This take-home simulates the **start of an underwriter's day**. We will hand the agent a queue of ~10 inbound property leads that need to be actioned. Each lead arrives with a varying amount of information—**some of it is missing, stale, ambiguous, or internally contradictory**, mirroring the failure modes underwriters hit every morning.

We provide a **FigJam diagram of the UW decision process** that documents what an underwriter is supposed to do when data is missing or when a case requires advanced escalation. Think of it as the playbook the agent (and you) should encode.

Your job is to build an assistant that helps underwriters **close the loop on every item in the queue and drive it to action**. By the end of a run, every property should land in one of two clean states:

1. **A quote goes out** — the agent gathered/derived everything it needed and the property is ready to be priced/issued, or
2. **A single, clear follow-up message is sent** — the agent could not close the loop on its own, so it produces *one* well-scoped outbound message that drives the next step (asking the homeowner, agent, or an internal team for exactly what is missing).

We will provide a **mock email service** so that outbound follow-ups can be "sent" and responses tracked, letting you simulate and test the full request → response → resolution cycle. We will also provide a **property generator service** that produces the 10 leads with the various missing-data and failure modes baked in.

As you build, you are making five core product decisions. We want to see your reasoning on each:

1. **Human-in-the-loop:** When does the agent act autonomously vs. stop and ask an underwriter to decide?
2. **Queue orchestration:** How do you drive the UW flow so the whole queue gets actioned efficiently (ordering, batching, parallelism, prioritization)?
3. **Outbound comms:** When is an email warranted, and what should it actually say? One crisp message beats five vague ones.
4. **Visualization:** How do you surface the agent's asks of the underwriter—what does the UW *see* and act on?
5. **Integrations:** What third-party tools/data sources would you wire in to make the underwriter's life easier (and which would you stub for now)?

## Key Considerations

* Choose any stack, agent framework, or model that best suits the project—be ready to justify it.
* Focus on demonstrating what's possible with agents and pressure-testing your design, not on exhaustive coverage of every rule.
* Prioritize the core loop (queue in → action out) while clearly identifying what still needs development.
* Ask questions when necessary, but don't hesitate to make reasonable assumptions—just explain your rationale.
* Keep the underwriter at the center, and make sure you can continue to factor in UW judgment. The provided FigJam represents just the *first layer* of complexity—underwriters need a way to keep giving input so we can tackle the next layer once this one is resolved. A technically impressive agent that an underwriter wouldn't trust or enjoy using is not a success.

# Problem Statement

At Stand, we provide tailored insurance solutions for individual properties. This customization has led to detailed underwriting guidelines and a collaborative mitigation approach—we work *with* homeowners to make properties safer rather than simply imposing requirements. The upside is robust, defensible underwriting. The downside is that the process is **slow, manual, and full of back-and-forth**: an underwriter spends much of their morning triaging leads, chasing missing data, and deciding which cases need escalation before any real underwriting can happen.

Most of that early triage is repetitive and rules-driven, but not trivial—it requires interpreting incomplete inputs against our playbook and knowing when a human judgment call is required. This is exactly the kind of work agents should be able to accelerate, **if** they are designed around how underwriters actually work.

We want to explore: **can an agentic assistant take a morning's queue of messy leads and drive every one of them to a clean next action—either ready-to-quote or a single sharp follow-up—while keeping the underwriter in control of the decisions that matter?**

# Assignment: UW Agentic Assistant Proof of Concept (POC)

Build a **proof of concept** for an agent-driven UW assistant that:

1. **Ingests the queue** — Pulls the ~10 generated property leads, each with its own missing-data / failure-mode profile.
2. **Triages and reasons** — Evaluates each property against the UW decision playbook (the provided FigJam), identifies what is missing or blocking, and decides the path: auto-resolve, gather data, escalate, or ask a human.
3. **Drives each property to action** — For every property, either prepares it to quote or composes exactly **one** clear, well-targeted follow-up message via the mock email service.
4. **Closes the loop** — Tracks responses to outbound messages and advances properties toward resolution as new information comes back.
5. **Keeps the underwriter in the loop where it counts** — Surfaces its asks, its uncertainty, and its escalations in a way an underwriter can quickly review and action.

## What's Included in the Prompt Folder

Everything below ships in the prompt folder and is runnable locally while you build the rest of the app:

* **FigJam: UW decision process** — The underwriting playbook. A top-level decision-points map plus per-decision drill-down pages (Occupancy, Profile, Fire Simulation, Roof Class, Siding, Post & Pier, Plumbing, Electrical, Swimming Pools, Trusts & LLCs, Replacement Cost, PC 9 & 10), including explicit notes on what to do when a field is missing or a case needs escalation.
* **Example request** — A sample lead payload (`lead_payload_example.json`) showing the exact shape of an inbound lead, with several fields intentionally missing/ambiguous so you can see the failure modes.
* **Data dictionary** — The field registry (`field_registry.json`): every field the system understands, with its `required` level, `editableByProducer` flag, type, and consumers. This is what you triage each lead against (join the lead's values to the registry to decide: auto-fetch, request via email, defer to bind, or verify).
* **`docker-compose.yml`** — Spins up two local services:
  * a **lead generator** that produces the ~10 morning-queue leads with their missing-data / failure-mode profiles, and
  * a **mock email service** so you can "send" outbound follow-ups and track responses, letting you simulate and test the full request → response → resolution cycle.

  Both run locally and are accessible to your agent while you develop.

# Deliverables

1. **A simple way to spin it up** — A command, script, and/or README that lets us run your system on one of our machines. It does not need to be bulletproof cross-platform, but follow good package-management practices so setup is painless. To the extent certain API keys are needed, feel free to explain to us how to obtain them or share them with us in a reasonable manner.
2. **Architecture overview** — A clear description of the systems, agent framework(s), models, and libraries you used to make this real, and *why*. Show the data/control flow and call out the key trade-offs you weighed against alternative approaches.
3. **A working eval loop + iteration plan** — A functioning evaluation harness that measures the quality of the agent's actions (e.g., did it pick the right path, is the follow-up message correct and minimal, did it avoid unnecessary escalation), plus a written plan for how you would iterate on the output over time. We care a lot about this—agents without evals don't improve.
4. **Skills: implemented + hit list** — A list of the skills/tools your agents currently have (what each does and when it fires), and a prioritized "hit list" of the next skills you'd build to make the assistant genuinely useful in production, with rationale for the ordering.

# Follow-Up Session

Once you complete the take-home, we'll schedule a **15-minute review session**. Please get your submission to us **at least 12-24 hours beforehand** so we can review it async in prep. The session will include:

1. A walkthrough of your README, architecture, and eval approach.
2. A live demo: run the morning queue end-to-end and show how the assistant drives each property to action.
3. A Q&A exploring your design decisions, your trade-offs, and where you'd take this next.

This project is an opportunity to showcase your **problem-solving, product judgment, and technical range**—especially how you think about building agents that real people will rely on. We're excited to see what you build. Good luck!
