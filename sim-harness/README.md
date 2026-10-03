# UW Take-Home — Simulation Harness

A small, self-contained **simulation harness** for the underwriting agentic
take-home. It provides the two fixture services your agent builds against — it
is **not** the agent itself.

1. **`leadgen`** — generates a deterministic "morning queue" of ~10 inbound
   property leads, weighted so the queue reliably skews toward hard, instructive
   cases (missing data, conflicts, hazardous archetypes).
2. **`mailbox`** — a mock email service. Your agent POSTs outbound follow-up
   emails; the mailbox captures them and makes them easy to browse and list per
   lead, both via JSON and a minimal HTML inbox.

Both run under `docker compose up`. The two services are independent; your agent
talks to each over HTTP.

> Reply simulation (injecting responses to outbound emails) is **out of scope**.
> The store is keyed by `lead_id`, leaving a clean seam for a future
> `POST /emails/{id}/reply`.

---

## Quick start

```bash
docker compose up --build            # leadgen on :8081, mailbox on :8025

# generate a morning queue (seeded for reproducibility)
curl -X POST "http://localhost:8081/queue?count=10&seed=42"

# list / inspect leads
curl "http://localhost:8081/leads"
curl "http://localhost:8081/leads/<lead_id>"

# the agent sends a follow-up
curl -X POST "http://localhost:8025/emails" -H 'content-type: application/json' \
  -d '{"lead_id":"<lead_id>","to":"broker@example.com","from":"uw@stand.com",
       "subject":"Roof class confirmation needed","body":"..."}'

# review everything the agent sent, per lead
open http://localhost:8025/          # inbox viewer
curl "http://localhost:8025/leads/<lead_id>/emails"
```

### Configuration (env knobs)

Copy `.env.example` to `.env` (read automatically by `docker compose`) or pass
inline. All are optional:

| Var | Default | Meaning |
|-----|---------|---------|
| `SEED` | random | Fixed seed for a reproducible queue. The seed is always echoed in the `POST /queue` response. |
| `COUNT` | `10` | Default leads per queue (overridable per request). |
| `DIFFICULTY` | `mixed` | `easy` \| `mixed` \| `hard` (overridable per request). |
| `DEBUG` | `false` | When `true`, exposes `GET /leads/{id}/debug` (the per-lead answer key). |

```bash
SEED=42 DEBUG=true docker compose up --build   # reproducible + answer key on
```

Difficulty weighting (tier mix, perturbation rates, archetype weights) lives in
[`leadgen/generator_config.yaml`](leadgen/generator_config.yaml) — tune it
without touching code.

---

## Service 1 — `leadgen` (port 8081)

Generates leads that validate against [`shared/field_registry.json`](shared/field_registry.json)
and match the envelope in [`shared/lead_payload_example.json`](shared/lead_payload_example.json):
`{ lead_id, received_at, source, fields: { <field_name>: value | null } }`
(`null` = missing).

| Method & path | Description |
|---|---|
| `POST /queue?count=10&seed=<int>&difficulty=<easy\|mixed\|hard>` | Generate + store a queue. Returns `{ seed, count, difficulty, lead_ids }`. Replaces any prior queue. |
| `GET /leads` | Summaries: `{ lead_id, source, received_at, missing_field_count }`. |
| `GET /leads/{id}` | Candidate-facing, registry-shaped payload. **No answer-key hints.** |
| `GET /leads/{id}/debug` | Interviewer-only answer key (`difficulty`, `injected_archetypes`, `perturbations`). Gated by `DEBUG=true` (else 403). |
| `GET /metrics` | Queue composition: counts per tier and per archetype. |
| `GET /registry` | Serves `field_registry.json`. |
| `POST /reset` | Clears the stored queue. |
| `GET /healthz` | `{ status: "ok" }`. |

### How leads are made hard

Each lead is built clean, assigned a difficulty tier, then pushed down hard
branches:

- **System-owned fields** (`editableByProducer: false` — `protection_class`,
  `replacement_cost`, `p_f`, `roof_classification`, `slope_angle_deg`,
  `min_distance_to_neighbor_ft`, `vegetation_clearance`, `road_access`,
  `kyc_score`, …) are nulled *often* → the agent must **auto-fetch / derive**,
  not email a human.
- **Producer `always`-required fields** (`roof_material`, `siding_material`,
  `trust_name` when held in trust, …) are nulled selectively → the agent should
  send a **single clear email** to the producer/applicant.
- **`bind_only` fields** are left missing sometimes → the agent should **defer**
  them, not chase them (tests over-asking).
- **Dependency chains** are respected: e.g. `roof_material` and its
  `derivedFrom` child `roof_classification` are nulled together, so the class
  can't be derived until the upstream material is resolved.
- **Conflicts**: present-but-inconsistent values (e.g. unoccupied 11 months but
  "owner-occupied / primary") → the agent should **verify** with a human.

**Hard archetypes** (drawn by weight from `generator_config.yaml`; hard leads get
1–2, medium ≤1, easy none): `electrical_hazard`, `pc_9_10_rural`,
`wildfire_severe`, `replacement_cost_gap`, `occupancy_conflict`, `trust_llc`,
`post_and_pier`, `plumbing_water_heater`, `pool_hazard`, `profile_kyc`. See
[`leadgen/archetypes.py`](leadgen/archetypes.py) for exactly what each sets and
nulls.

### Determinism

Same `seed` + same config ⇒ **identical queue**. The seed is echoed in
`POST /queue` (and defaults to `SEED`, or a random seed that is still returned).
Reproduce a grading queue with `POST /queue?seed=42`.

---

## Service 2 — `mailbox` (port 8025)

Captures outbound follow-up emails and makes them browsable per lead.

| Method & path | Description |
|---|---|
| `POST /emails` | Body `{ lead_id, to, from, subject, body, metadata? }`. Returns `{ id, lead_id, received_at }`. |
| `GET /emails?lead_id=&limit=&offset=` | Summaries, newest first. |
| `GET /emails/{id}` | Full record. |
| `GET /leads/{lead_id}/emails` | All full records for one lead. |
| `POST /reset` | Clears the store. |
| `GET /healthz` | `{ status: "ok" }`. |
| `GET /` | **HTML inbox viewer** — leads on the left, emails grouped per lead on the right; click any email to expand the full body + metadata. |

Persistence: SQLite at `./data/mailbox.db` (bind-mounted volume) — survives
`docker compose down && up`. Table:
`emails(id, lead_id, to_addr, from_addr, subject, body, metadata_json, received_at)`.

---

## Repo layout

```
sim-harness/
  docker-compose.yml
  README.md
  shared/
    registry.py            # loads field_registry.json, field metadata + validation
    schema.py              # Pydantic models: Lead, LeadSummary, EmailIn, EmailRecord, ...
    field_registry.json    # the data dictionary (the contract)
    lead_payload_example.json
  leadgen/
    Dockerfile  main.py  generator.py  archetypes.py  generator_config.yaml  requirements.txt
  mailbox/
    Dockerfile  main.py  store.py  templates/inbox.html  requirements.txt
  data/                    # SQLite volume (gitignored)
```

`field_registry.json` and `lead_payload_example.json` are the contract — leads
conform to them; field names are never invented.

---

## Acceptance checklist

- [x] `docker compose up` brings up both services with passing healthchecks.
- [x] A single `POST /queue` produces a registry-valid, reproducible queue skewed
      toward hard cases (**≥4/10 leads carry a hard archetype** by default; every
      tier represented).
- [x] System-owned fields are missing far more often than producer
      `always`-required fields.
- [x] `GET /leads/{id}/debug` reveals the answer key under `DEBUG=true`; the
      candidate-facing payload does not.
- [x] Re-running with the same seed reproduces the identical queue.
- [x] POSTed emails are retrievable individually, in a flat list, and grouped
      per lead; the `/` viewer lists everything; data persists across restarts;
      `POST /reset` clears it.

## Out of scope / future seams

- **Reply simulation** (`POST /emails/{id}/reply` + canned auto-responders) — the
  store is already keyed by `lead_id` to make this a drop-in later.
- Real SMTP, auth, multi-tenant, and any candidate-agent logic.
