# Stand UW Agentic Assistant (proof of concept)

An assistant for the start of an underwriter's day.

![Architecture diagram](Architecture%20Diagram.png)

Details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).


---

## Run it

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/) (Python 3.11+ is fetched by uv), `make`.

```bash
make setup            # uv sync + enable the version-bump pre-commit hook
make up               # leadgen :8081 (DEBUG=true answer key), mailbox :8025, mock vendors :8082
make ui-offline       # underwriter UI on http://localhost:8090, no API key needed
```

Open http://localhost:8090, click **Run morning queue**. The mock inbox is at http://localhost:8025.

### Using Claude (pick one)

The model edges (evidence interpreter, email composer, reply parser, summarizer) can run three ways. All three are exercised by the same tests and eval sets.

**A. Your Claude Code subscription, no API key** (Pro / Max; recommended if you already use Claude Code)
1. Install [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) and log in once by running `claude` and following the prompt. Check with `claude --version`.
2. `make smoke-cc` checks the three edges live (about 25 seconds), then `make ui-cc` starts the UI with Claude, `make run-cc` runs the queue in the terminal, and `make eval-cc` runs the evals. Equivalent: set `UW_LLM=claude-code` in front of any command.

How it works: each model call runs `claude -p` (print mode) with the prompt on stdin, a JSON schema for the answer, no tools, no skills, no session saved, from an empty temp directory. **Nothing here reads, stores or forwards a credential:** authentication stays inside the `claude` binary (your own login), and `ANTHROPIC_API_KEY` is deliberately removed from the child process so a stray key can never switch a subscription run to metered billing. Calls count against your subscription's usage limits, take a few seconds each (a 10-lead queue is about 80 seconds), and run at most 3 at a time (`UW_CLAUDE_CODE_CONCURRENCY`).

**B. Anthropic API key.** `cp .env.example .env`, put your key in `ANTHROPIC_API_KEY` (create one at https://console.anthropic.com/settings/keys; a Pro/Max subscription does not include API access, which is billed separately). `.env` is gitignored and nothing is ever committed. Then `make smoke-llm`, `make ui`, `make run`, `make eval`.

**C. No model at all.** `make ui-offline`, `make demo-offline`, `make eval-offline` use a deterministic rule-based stand-in. Good for trying the flow and for fast regression runs; it says nothing about Claude.

Every run and eval records which backend and model it used.

| Command | What it does |
|---|---|
| `make ui` / `make ui-cc` / `make ui-offline` | underwriter UI (API key / Claude Code login / rule-based stand-in) |
| `make run` / `make run-cc` / `make demo-offline` | the whole queue in the terminal: process, simulate producer replies, re-process |
| `make eval` / `make eval-cc` / `make eval-offline` | all eval sets; `eval-live` runs the seeded sets against the docker stack |
| `make test` | 109 tests, no network and no model needed |
| `make down` | stop the docker services |

**Suggested 3-minute demo path**
1. *Run morning queue* (seed 42). Leads sort into **Ready to quote**, **Needs your decision**, **Awaiting reply**. Each card says what the agent proposes and why.
2. Open an *awaiting reply* lead: the "What we're waiting on" block lists each question and which playbook check it unblocks. The one email it sent is visible, and in the mock inbox.
3. Click **Simulate producer reply** on one lead (demo only: the "producer" answers from the generator's ground truth). The lead re-evaluates and moves to ready or needs-you.
4. Open a *needs your decision* lead: conflicts and escalations, with the evidence. Try **override** (a note is required) or **provide a value**.
5. Untick *auto-send follow-ups* and re-run: emails are drafted for you to review, edit and send instead.
6. **Approve N quick wins** (button above the queue) approves all clean, no-condition quotes at once.

## Read more

| Doc | What is in it |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | components, data and control flow, stack, key trade-offs against alternatives |
| [docs/PRODUCT_DECISIONS.md](docs/PRODUCT_DECISIONS.md) | the five product decisions: human in the loop, orchestration, comms, visualization, integrations |
| [docs/EVALS.md](docs/EVALS.md) | the eval loop, metrics and slices, results ledger, and the iteration plan |
| [docs/SKILLS.md](docs/SKILLS.md) | skills and tools implemented, and the prioritised hit list |
| [sim-harness/CHANGES.md](sim-harness/CHANGES.md) | changes made to the provided tooling |
| [DECISIONS.md](DECISIONS.md) | decision log D1 to D25 |
| [sim-harness/protocols/JUDGEMENT_CALLS.md](sim-harness/protocols/JUDGEMENT_CALLS.md) | every ambiguous reading in the playbook diagrams |
| [BACKLOG.md](BACKLOG.md), [PLAN.md](PLAN.md) | backlog and implementation plan |

## Changes to provided tooling

Documented in full, with files and invariants, in [`sim-harness/CHANGES.md`](sim-harness/CHANGES.md) (decision D5 and D19). In short:

1. **Ground truth in the answer key.** `GET /leads/{id}/debug` (still `DEBUG=true` only) now also returns `clean_fields`: the lead before any random nulling or conflicts. Seed 42 still produces a byte-identical queue, the public lead payload is unchanged, and a test pins both. Only the reply simulator and the evals read it.
2. **Mock vendors service** (new, port 8082, in `docker-compose.yml`) over vendor-shaped SQLite tables that leadgen writes when it generates a queue. Nothing real is ever called.


## Limits and what is not verified

- **Playbook coverage is partial** (5 of the 12 drill-down diagrams, encoded as 6 protocols), by design for the time box; the rest are on the hit list.
- **Judgement calls in the diagrams** are assumptions the underwriter should confirm; each is listed with a status.
- **Mock vendors are simple** (D25), the reply simulator is cooperative, and conflicts the generator injects are a small family.
- **Cut / future work:** the LLM-judged email rubric, imperfect free-text replies in the eval, UW-editable protocols, durable workflow, and real integrations.

## Repo map

```
uw_agent/          the app: normalize, resolution, executor, protocols/{expr,engine,linter}, tools/, orchestrator,
                   composer, interpreter, replies, summarizer, db, api, server, web/index.html, prompts/
sim-harness/       provided services (leadgen, mailbox) + vendors service, protocols/*.json, shared/ (registry, resolution map)
docs/              architecture, product decisions, evals, skills and hit list
evals/             grader, runner, compare, sets/ (fixed + seeded), results.csv, COVERAGE_GAPS.md
tests/             109 tests (engine, resolution, tools, LLM edges, orchestrator, API, evals, versions)
versions/          component version manifest (bumped by the pre-commit hook; system version = git hash)
DECISIONS.md       D1-D25      PLAN.md  BACKLOG.md
```
