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

**With Claude** (the intended mode): `cp .env.example .env`, put your key in `ANTHROPIC_API_KEY` (create one at https://console.anthropic.com/settings/keys; the file is gitignored, nothing is ever committed), then `make smoke-llm` (live check of the three model edges) and `make ui` instead of `make ui-offline`. Default model is `claude-sonnet-5-5`, overridable per task (see `.env.example`). If you would rather not create a key, ask the author for a temporary one.

| Command | What it does |
|---|---|
| `make ui` / `make ui-offline` | underwriter UI (Claude / rule-based stand-in) |
| `make run` / `make demo-offline` | the whole queue in the terminal: process, simulate producer replies, re-process |
| `make eval` / `make eval-offline` | all eval sets; `eval-live` runs the seeded sets against the docker stack |
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

Everything else in `sim-harness/` is as provided (the mailbox is untouched; replies are ordinary stored rows with metadata). Added alongside: `sim-harness/protocols/` (the encoded playbook) and the shared field-resolution map.

## Limits and what is not verified

- **No live Claude run.** Prompts, structured-output schemas and fallbacks are tested with scripted fakes and an offline stand-in; real model behaviour is unmeasured.
- **UI not seen in a browser by me.** It is exercised through the API, render checks and a script, not eyes.
- **Playbook coverage is partial** (5 of the 12 drill-down diagrams, encoded as 6 protocols), by design for the time box; the rest are on the hit list.
- **Judgement calls in the diagrams** are assumptions the underwriter should confirm; each is listed with a status.
- **Mock vendors are simple** (D25), the reply simulator is cooperative, and conflicts the generator injects are a small family.
- **Time-box:** cut, in order, were the LLM-judged email rubric, imperfect free-text replies in the eval, UW-editable protocols, durable workflow, and real integrations.

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
