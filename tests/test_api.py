"""FastAPI layer + underwriter actions (milestone 6). In-process world, synchronous runs."""

import pytest
from fastapi.testclient import TestClient

import uw_agent.config  # noqa: F401
from tests.harness_fixtures import World
from uw_agent import orchestrator as orch
from uw_agent.api import create_app
from uw_agent.replysim import simulate_replies


@pytest.fixture()
def env(tmp_path):
    w = World(tmp_path, 42, "hard")
    app = create_app(w.ctx, simulate=lambda ids, mode: simulate_replies(w.mailbox, w.truth, ids, mode), background=False)
    return w, TestClient(app)


def start(client, **kw):
    r = client.post("/api/runs", json={"seed": 42, "difficulty": "hard", **kw})
    assert r.status_code == 200
    return r.json()["run_id"]


def test_ui_page_and_version(env):
    _, c = env
    html = c.get("/").text
    assert "<title>UW Assistant</title>" in html and "Wait-to-quote" in html and "Approve" in html
    v = c.get("/api/version").json()
    assert v["system_version"] and "protocol_engine" in v["components"]
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/api/runs/latest").status_code == 404


def test_run_queue_and_card_fields(env):
    w, c = env
    rid = start(c)
    q = c.get(f"/api/runs/{rid}/queue").json()
    assert q["run"]["status"] == "ready" and q["run"]["processed"] == 10 == len(q["leads"])
    assert [l["priority"] for l in q["leads"]] == sorted(l["priority"] for l in q["leads"])      # quick wins first
    for l in q["leads"]:
        assert l["state"] in ("ready_to_quote", "needs_uw", "awaiting_reply") and l["headline"]
        assert "pending" not in l["headline"]
    assert c.get("/api/runs/latest").json()["run_id"] == rid


def test_lead_detail_has_everything_the_ui_shows(env):
    w, c = env
    rid = start(c)
    lid = c.get(f"/api/runs/{rid}/queue").json()["leads"][0]["lead_id"]
    d = c.get(f"/api/runs/{rid}/leads/{lid}").json()
    rep = d["decision"]["report"]
    for k in ("protocols", "assumptions", "conditions", "asks", "reasons", "fetched", "lookups", "system_version"):
        assert k in rep
    assert d["decision"]["summary"]["headline"] and d["history"] and isinstance(d["emails"], list)
    assert c.get(f"/api/runs/{rid}/leads/NOPE").status_code == 404


def test_approve_moves_lead_to_actioned_and_records_feedback(env):
    w, c = env
    rid = start(c)
    c.post(f"/api/runs/{rid}/simulate_replies", json={"mode": "complete"})   # hard queues need the producer's answers first
    q = c.get(f"/api/runs/{rid}/queue").json()["leads"]
    lead = next(l for l in q if l["decision"] in ("quote", "quote_with_conditions"))
    d = c.post(f"/api/runs/{rid}/leads/{lead['lead_id']}/actions", json={"action": "approve"}).json()
    assert d["card"]["state"] == "actioned" and d["card"]["uw_status"] == "approved_quote"
    assert d["uw_actions"][-1]["action"] == "approve" and d["uw_actions"][-1]["payload"]["agent_decision"] == lead["decision"]
    pending = next((l for l in q if l["decision"] is None), None)
    if pending:                                                          # nothing to approve yet
        r = c.post(f"/api/runs/{rid}/leads/{pending['lead_id']}/actions", json={"action": "approve"})
        assert r.status_code == 409


def test_override_decision_requires_a_note_and_is_stored(env):
    w, c = env
    rid = start(c)
    lid = c.get(f"/api/runs/{rid}/queue").json()["leads"][0]["lead_id"]
    bad = c.post(f"/api/runs/{rid}/leads/{lid}/actions", json={"action": "override_decision", "decision": "decline"})
    assert bad.status_code == 422
    ok = c.post(f"/api/runs/{rid}/leads/{lid}/actions",
                json={"action": "override_decision", "decision": "decline", "note": "roof too risky for us"}).json()
    assert ok["card"]["uw_status"] == "overridden" and ok["card"]["uw_decision"] == "decline" and ok["card"]["state"] == "actioned"
    assert c.post(f"/api/runs/{rid}/leads/{lid}/actions", json={"action": "bogus"}).status_code == 422


def test_provide_value_corrects_an_assumption_and_reprocesses(env):
    w, c = env
    rid = start(c)
    lead = next((l for l in c.get(f"/api/runs/{rid}/queue").json()["leads"] if l["n_assumptions"]), None)
    if lead is None:
        pytest.skip("no assumptions in this queue")
    d = c.get(f"/api/runs/{rid}/leads/{lead['lead_id']}").json()
    a = d["decision"]["report"]["assumptions"][0]
    new = {"pool_type": "Inground", "protection_class": "5"}.get(a["field"])
    if new is None:
        pytest.skip("assumed field not covered here")
    r = c.post(f"/api/runs/{rid}/leads/{lead['lead_id']}/actions", json={"action": "provide_value", "field": a["field"], "value": new})
    assert r.status_code == 200
    d2 = r.json()
    assert d2["answers"][a["field"]] == new and d2["decision"]["round"] > d["decision"]["round"]
    assert all(x["field"] != a["field"] for x in d2["decision"]["report"]["assumptions"])
    assert c.post(f"/api/runs/{rid}/leads/{lead['lead_id']}/actions",
                  json={"action": "provide_value", "field": "pool_type", "value": "Lagoon"}).status_code == 422


def test_draft_email_flow_review_edit_send(tmp_path):
    w = World(tmp_path, 42, "hard", auto_send=False)
    c = TestClient(create_app(w.ctx, simulate=lambda ids, mode: simulate_replies(w.mailbox, w.truth, ids, mode), background=False))
    rid = c.post("/api/runs", json={"seed": 42, "auto_send": False}).json()["run_id"]
    assert not w.mailbox.emails                                           # nothing went out automatically
    q = c.get(f"/api/runs/{rid}/queue").json()["leads"]
    lead = next(l for l in q if l["email_status"] == "draft")
    assert lead["state"] == "needs_uw" and "email_draft" in lead["reasons"]
    d = c.get(f"/api/runs/{rid}/leads/{lead['lead_id']}").json()
    draft = next(e for e in d["emails"] if e["status"] == "draft")
    edited = draft["body"].replace("Hello,", "Hello team,")
    c.post(f"/api/runs/{rid}/leads/{lead['lead_id']}/actions", json={"action": "edit_draft", "email_id": draft["id"], "body": edited})
    d = c.post(f"/api/runs/{rid}/leads/{lead['lead_id']}/actions", json={"action": "send_draft", "email_id": draft["id"]}).json()
    assert len(w.mailbox.emails) == 1 and w.mailbox.emails[0]["body"].startswith("Hello team,")
    assert [e["status"] for e in d["emails"] if e["direction"] == "out"] == ["sent"]
    assert d["card"]["state"] in ("awaiting_reply", "needs_uw") and "email_draft" not in d["card"]["reasons"]
    assert c.post(f"/api/runs/{rid}/leads/{lead['lead_id']}/actions", json={"action": "send_draft", "email_id": draft["id"]}).status_code == 409


def test_simulate_replies_and_poll_close_the_loop_through_the_api(env):
    w, c = env
    rid = start(c)
    before = c.get(f"/api/runs/{rid}/queue").json()["leads"]
    assert any(l["state"] == "awaiting_reply" for l in before)
    r = c.post(f"/api/runs/{rid}/simulate_replies", json={"mode": "complete"}).json()
    assert r["replies"] >= 1 and r["reprocessed"]
    after = c.get(f"/api/runs/{rid}/queue").json()["leads"]
    assert not any(l["state"] == "awaiting_reply" for l in after)
    assert c.post(f"/api/runs/{rid}/poll").json() == {"reprocessed": []}   # nothing new


def test_approve_quick_wins_only_touches_clean_leads(env):
    w, c = env
    rid = start(c)
    q = c.get(f"/api/runs/{rid}/queue").json()["leads"]
    c.post(f"/api/runs/{rid}/simulate_replies", json={"mode": "complete"})
    q = c.get(f"/api/runs/{rid}/queue").json()["leads"]
    quick = [l["lead_id"] for l in q if l["state"] == "ready_to_quote" and l["priority"] == 0 and l["n_low_confidence"] == 0]
    done = c.post(f"/api/runs/{rid}/approve_quick_wins").json()["approved"]
    assert set(done) == set(quick) and done
    after = {l["lead_id"]: l for l in c.get(f"/api/runs/{rid}/queue").json()["leads"]}
    assert all(after[x]["state"] == "actioned" for x in done)
    assert all(l["state"] != "actioned" for k, l in after.items() if k not in done)       # conditions/conflicts untouched
    assert c.post(f"/api/runs/{rid}/approve_quick_wins").json() == {"approved": []}       # idempotent
