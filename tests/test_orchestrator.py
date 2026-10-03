"""Orchestrator, reply loop, and reply parsing (milestone 5). In-process world; offline rule-based interpreter."""

import json
import sqlite3
from collections import Counter

import pytest

import uw_agent.config  # noqa: F401
from tests.fakes import FakeLLM
from tests.harness_fixtures import World, public
from uw_agent import orchestrator as orch
from uw_agent.composer import EmailPlan, ask_for, numbered_asks, CondGroup
from uw_agent.llm import LLMError
from uw_agent.replies import ParsedAnswer, ReplyExtraction, coerce_answer, parse_reply
from uw_agent.replysim import simulate_replies


def full_cycle(w, rounds=2, mode="complete"):
    rid = w.start()
    orch.run_queue(w.ctx, rid)
    for _ in range(rounds):
        if not simulate_replies(w.mailbox, w.truth, w.ctx.db.lead_ids(rid), mode):
            break
        orch.poll_replies(w.ctx, rid)
    return rid


# --- end to end ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed,difficulty", [(42, "mixed"), (7, "hard"), (101, "hard")])
def test_every_lead_lands_in_a_state_and_matches_truth(tmp_path, seed, difficulty):
    w = World(tmp_path, seed, difficulty)
    rid = w.start()
    first = orch.run_queue(w.ctx, rid)
    assert {o.state for o in first} <= {orch.READY, orch.AWAITING, orch.NEEDS_UW}
    for lead in w.queue:                                 # at most ONE email per lead in the first round
        assert len(w.ctx.db.emails(rid, lead["lead_id"], "out")) <= 1
    for _ in range(2):
        if simulate_replies(w.mailbox, w.truth, w.ctx.db.lead_ids(rid)):
            orch.poll_replies(w.ctx, rid)
    for lid in w.ctx.db.lead_ids(rid):
        d, t = w.ctx.db.latest_decision(rid, lid), w.truth_decision(lid)
        assert d["state"] != orch.AWAITING, lid          # nothing left waiting after complete replies
        assert d["decision"] == t.decision and set(d["report"]["conditions"]) == set(t.conditions), (lid, d["decision"], t.decision)
        assert len(w.ctx.db.emails(rid, lid, "out")) <= 2


def test_state_priority_and_queue_view(tmp_path):
    w = World(tmp_path, 42, "hard")
    rid = full_cycle(w)
    states = [r["state"] for r in w.ctx.db.queue_view(rid)]
    assert states == sorted(states, key=lambda s: {"ready_to_quote": 0, "needs_uw": 1, "awaiting_reply": 2}[s])
    d = w.ctx.db.latest_decision(rid, w.ctx.db.lead_ids(rid)[0])
    assert d["report"]["system_version"] and d["summary"]["headline"] and d["summary"]["used_llm"] is False  # fallback summary offline
    run = w.ctx.db.one("SELECT * FROM runs WHERE run_id=?", (rid,))
    assert run["system_version"] and json.loads(run["runtime_config_json"])["offline"] is True
    assert w.ctx.db.one("SELECT COUNT(*) FROM system_versions")[0] == 1       # version registered (D10)


def test_process_lead_is_idempotent_and_never_duplicates_an_email(tmp_path):
    w = World(tmp_path, 42, "hard")
    rid = w.start()
    first = {o.lead_id: o for o in orch.run_queue(w.ctx, rid)}
    n_sent = len(w.mailbox.emails)
    again = {lid: orch.process_lead(w.ctx, rid, lid, "recheck") for lid in first}
    assert len(w.mailbox.emails) == n_sent
    assert {k: v.state for k, v in again.items()} == {k: v.state for k, v in first.items()}


def test_conflicts_go_to_the_underwriter_not_the_producer_decision(tmp_path):
    w = World(tmp_path, 42, "hard")
    rid = full_cycle(w)
    kinds = Counter(r["type"] for lid in w.ctx.db.lead_ids(rid)
                    for r in w.ctx.db.latest_decision(rid, lid)["report"]["reasons"])
    assert kinds["conflict"] >= 1
    for lid in w.ctx.db.lead_ids(rid):
        d = w.ctx.db.latest_decision(rid, lid)
        if any(r["type"] == "conflict" for r in d["report"]["reasons"]):
            assert d["state"] == orch.NEEDS_UW


# --- targeted scenarios ----------------------------------------------------------------------------------------

def one_lead_world(tmp_path, mutate, **kw):
    """A clean, complete lead (from the generator's truth) with `mutate(fields)` applied to what the producer sent."""
    from tests.harness_fixtures import generator, CONFIG
    base = next(l for l in generator.generate_queue(42, 10, "easy", CONFIG)
                if not l["debug"]["perturbations"] or True)
    truth = dict(base["debug"]["clean_fields"])
    fields = dict(truth)
    mutate(fields)
    lead = {"lead_id": base["lead_id"], "received_at": base["received_at"], "source": base["source"], "fields": fields}
    return World(tmp_path, leads=[{**lead, "debug": {"clean_fields": truth}}], truth={lead["lead_id"]: truth}, **kw), lead["lead_id"]


def test_complete_lead_goes_straight_to_ready_with_no_email(tmp_path):
    w, lid = one_lead_world(tmp_path, lambda f: None)
    rid = w.start()
    o = orch.process_lead(w.ctx, rid, lid)
    assert o.state == orch.READY and not w.mailbox.emails and o.n_asks == 0


def test_system_owned_fields_are_fetched_never_asked(tmp_path):
    def m(f):
        for k in ("protection_class", "replacement_cost", "kyc_score", "p_f", "broker_tier"):
            f[k] = None
    w, lid = one_lead_world(tmp_path, m)
    rid = w.start()
    o = orch.process_lead(w.ctx, rid, lid)
    d = w.ctx.db.latest_decision(rid, lid)
    assert o.state == orch.READY and not w.mailbox.emails
    assert {x["field"] for x in d["report"]["fetched"]} >= {"protection_class", "replacement_cost", "kyc_score", "p_f"}


def test_vendor_outage_falls_back_to_assume_or_escalates_never_asks_human(tmp_path):
    def m(f):
        f["protection_class"] = None
        f["kyc_score"] = None
    w, lid = one_lead_world(tmp_path, m)
    c = sqlite3.connect(w.db_path)
    for v in ("ppc", "kyc"):
        c.execute("INSERT INTO vendor_overrides VALUES (?,?,?,?,?)", (lid, v, "*", "unavailable", None))
    c.commit(); c.close()
    rid = w.start()
    orch.process_lead(w.ctx, rid, lid)
    d = w.ctx.db.latest_decision(rid, lid)
    assert any(a["field"] == "protection_class" and a["value"] == "9" for a in d["report"]["assumptions"])  # PC 9 default
    unresolved = [r for r in d["report"]["reasons"] if r["type"] == "unresolved_system_data"]
    assert unresolved and "kyc_score" in unresolved[0]["fields"]            # no default for KYC -> human, not the producer
    assert d["state"] == orch.NEEDS_UW
    asked = {a["field"] for a in d["report"]["asks"]}
    assert asked == {"fire_dept_response_time", "alternative_water_source", "interior_sprinklers", "physical_barriers"} \
        or asked == {"fire_dept_response_time", "alternative_water_source", "interior_sprinklers"}   # PC 9 assumed -> PC 9/10 fields
    assert "kyc_score" not in asked and "protection_class" not in asked                              # system-owned: never asked
    assert d["report"]["tool_failures"]


def test_conditional_asks_are_grouped_into_the_single_email(tmp_path):
    def m(f):
        f["water_heater_type"] = None
        f["water_heater_age_years"] = None
        f["water_heater_location"] = None
    w, lid = one_lead_world(tmp_path, m)
    rid = w.start()
    orch.process_lead(w.ctx, rid, lid)
    assert len(w.mailbox.emails) == 1
    body = w.mailbox.emails[0]["body"]
    assert "Water Heater Type" in body and "If Water Heater Type is Tank:" in body
    assert "Water Heater Age" in body and "Water Heater Location" in body.split("If Water Heater Type is Tank:")[1]
    asks = w.mailbox.emails[0]["metadata"]["asks"]
    assert [a["group_id"] for a in asks] == [0, 1, 2]                           # age needs Tank; location needs Tank AND age > 10
    assert asks[1]["whens"] == ['water_heater_type == "Tank"']
    assert asks[2]["whens"] == ['water_heater_type == "Tank"', "water_heater_age_years > 10"]
    # the producer's single reply (tankless) answers the parent; the conditional ones are N/A -> done
    simulate_replies(w.mailbox, w.truth, [lid])
    out = orch.poll_replies(w.ctx, rid)
    assert out[0].state == orch.READY and len(w.mailbox.emails) == 2        # reply is the 2nd mailbox row; no 2nd ask


def test_decline_suppresses_all_asks(tmp_path):
    def m(f):
        f["plumbing_age_years"] = 55
        f["broker_tier"] = "Tier 3"
        f["has_primary_policy_with_stand"] = False
        f["first_name"] = None                                       # would normally be asked
    w, lid = one_lead_world(tmp_path, m, )
    # make truth tier match so vendors return the same
    rid = w.start()
    o = orch.process_lead(w.ctx, rid, lid)
    d = w.ctx.db.latest_decision(rid, lid)
    if d["decision"] == "decline":
        assert o.state == orch.NEEDS_UW and not w.mailbox.emails and d["report"]["reasons"][0]["type"] == "decline"


def test_auto_send_off_drafts_the_email_for_the_underwriter(tmp_path):
    w, lid = one_lead_world(tmp_path, lambda f: f.update(first_name=None), auto_send=False)
    rid = w.start()
    o = orch.process_lead(w.ctx, rid, lid)
    assert o.state == orch.NEEDS_UW and not w.mailbox.emails
    assert [e["status"] for e in w.ctx.db.emails(rid, lid, "out")] == ["draft"]
    assert any(r["type"] == "email_draft" for r in o.reasons)


def test_partial_reply_triggers_one_followup_for_the_rest_then_escalates_at_the_cap(tmp_path):
    w, lid = one_lead_world(tmp_path, lambda f: f.update(first_name=None, last_name=None, city=None))
    rid = w.start()
    orch.process_lead(w.ctx, rid, lid)
    simulate_replies(w.mailbox, w.truth, [lid], "partial")           # leaves the last question unanswered
    o = orch.poll_replies(w.ctx, rid)[0]
    outs = w.ctx.db.emails(rid, lid, "out")
    assert o.state == orch.AWAITING and len(outs) == 2 and outs[1]["asks_hash"] != outs[0]["asks_hash"]
    assert "Insured Last Name" in outs[1]["body"] and "First Name" not in outs[1]["body"] and "City" not in outs[1]["body"]
    w.ctx.max_emails = 2
    simulate_replies(w.mailbox, w.truth, [lid], "partial")           # still never answers the last question
    o = orch.poll_replies(w.ctx, rid)
    d = w.ctx.db.latest_decision(rid, lid)
    assert len(w.ctx.db.emails(rid, lid, "out")) == 2 and d["state"] in (orch.AWAITING, orch.NEEDS_UW)


def test_na_answer_is_recorded_and_not_asked_again(tmp_path):
    w, lid = one_lead_world(tmp_path, lambda f: f.update(deck_height_ft=None, foundation_type="Piers",
                                                         post_pier_supports_living_area=None))
    # truth: piers but producer says N/A for a conditional field -> never re-asked
    rid = w.start()
    orch.process_lead(w.ctx, rid, lid)
    out = w.mailbox.emails[0]
    w.mailbox.send(lid, out["from"], "Re: x", "\n".join(f"{a['n']}. N/A" for a in out["metadata"]["asks"]),
                   {"direction": "inbound", "in_reply_to": out["id"]}, sender="producer@broker.example")
    orch.poll_replies(w.ctx, rid)
    assert w.ctx.db.na_fields(rid, lid)
    n = len(w.ctx.db.emails(rid, lid, "out"))
    orch.process_lead(w.ctx, rid, lid, "recheck")
    assert len(w.ctx.db.emails(rid, lid, "out")) == n                 # no repeated question


def test_unexpected_exception_becomes_a_needs_uw_decision(tmp_path):
    w, lid = one_lead_world(tmp_path, lambda f: None)
    rid = w.start()
    w.ctx.tools.fetch = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    w.ctx.db.execute("UPDATE leads SET raw_json=? WHERE lead_id=?", (json.dumps({**public(w.queue[0]),
                     "fields": {**w.queue[0]["fields"], "protection_class": None}}), lid))
    o = orch.process_lead(w.ctx, rid, lid)
    assert o.state == orch.NEEDS_UW and o.reasons[0]["type"] == "internal_error" and "boom" in o.reasons[0]["detail"]


def test_noisy_vendors_still_close_the_loop(tmp_path):
    w = World(tmp_path, 42, "hard", profile="noisy")
    rid = full_cycle(w)
    states = Counter(w.ctx.db.latest_decision(rid, l)["state"] for l in w.ctx.db.lead_ids(rid))
    assert sum(states.values()) == 10 and states[orch.AWAITING] <= 2


# --- reply parsing -------------------------------------------------------------------------------------------------

ASKS = [{"n": 1, "field": "roof_material", "group_id": 0, "whens": []},
        {"n": 2, "field": "has_animals", "group_id": 0, "whens": []},
        {"n": 3, "field": "electrical_panel_size_amps", "group_id": 0, "whens": []},
        {"n": 4, "field": "deck_height_ft", "group_id": 1, "whens": ["x"]}]


def test_coerce_answer():
    assert coerce_answer("roof_material", "Slate") == ("value", "Slate")
    assert coerce_answer("roof_material", "it's a wood shake roof") == ("value", "Wood Shake")
    assert coerce_answer("roof_material", "wood shingle") == ("value", "Wood Shingle")     # longest/exact, not 'Wood Shake'
    assert coerce_answer("roof_material", "tiles") == ("unparsed", None)
    assert coerce_answer("has_animals", "Yes, two dogs") == ("value", True)
    assert coerce_answer("has_animals", "no") == ("value", False)
    assert coerce_answer("electrical_panel_size_amps", "about 200 amps") == ("value", 200)
    assert coerce_answer("deck_height_ft", "N/A") == ("na", None)


def test_parse_reply_numbered_then_llm_for_free_text():
    body = "Hi\n1. Slate\n2. Yes\n3. not sure\n4. N/A\nthanks"
    r = parse_reply(None, ASKS, body)
    assert r.answers == {"roof_material": "Slate", "has_animals": True} and r.not_applicable == ["deck_height_ft"]
    assert r.unanswered == ["electrical_panel_size_amps"] and not r.used_llm
    llm = FakeLLM({"reply_parser": ReplyExtraction(answers=[
        ParsedAnswer(field="electrical_panel_size_amps", value="200", confidence="high"),
        ParsedAnswer(field="roof_material", value="Slate", confidence="high"),            # already answered: ignored
        ParsedAnswer(field="has_animals", value="maybe", confidence="low")])})
    r2 = parse_reply(llm, ASKS, body)
    assert r2.answers["electrical_panel_size_amps"] == 200 and r2.used_llm and r2.unanswered == []
    assert "Questions asked" in llm.prompts[0]["user"] and "electrical_panel_size_amps" in llm.prompts[0]["user"]
    free = parse_reply(FakeLLM({"reply_parser": ReplyExtraction(answers=[
        ParsedAnswer(field="roof_material", value="Lagoon", confidence="high")])}), ASKS, "The roof is something")
    assert "roof_material" not in free.answers                                            # invalid value never stored
    assert parse_reply(FakeLLM({"reply_parser": LLMError("down")}), ASKS, "free text").answers == {}


def test_numbering_in_metadata_matches_the_email_body():
    chain = [{"node": "n", "branch": "b", "when": 'water_heater_type == "Tank"'}]
    plan = EmailPlan("L", "addr", "t", asks=[ask_for("roof_material")],
                     groups=[CondGroup(1, chain, [ask_for("water_heater_age_years")])])
    from uw_agent.composer import template_email
    body = template_email(plan).body
    for a in numbered_asks(plan):
        assert f"{a['n']}. " in body
    assert [a["field"] for a in numbered_asks(plan)] == ["roof_material", "water_heater_age_years"]


def test_waiting_lead_explains_what_passes_and_what_blocks_each_check(tmp_path):
    def m(f):
        f["water_heater_type"] = None
        f["water_heater_age_years"] = None
        f["water_heater_location"] = None
        f["roof_material"] = None
        f["roof_classification"] = None
    w, lid = one_lead_world(tmp_path, m)
    rid = w.start()
    orch.process_lead(w.ctx, rid, lid)
    d = w.ctx.db.latest_decision(rid, lid)
    asks = {a["label"]: a for a in d["report"]["asks"]}
    assert asks["Water Heater Type"]["needed_for"] == ["water_heaters"]
    assert asks["Water Heater Age (years)"]["conditional"] is True
    assert "roof_class" in asks["Roof Surface Material"]["needed_for"]        # derived blocker mapped to its real input
    assert d["report"]["provisional_decision"] in ("quote", "quote_with_conditions")
    text = " ".join(d["summary"]["rationale"])
    assert "Pass with the data so far" in text and "general plumbing" in text   # what already passes, in plain words
    assert "water heaters (needs Water Heater Type" in text and "roof class (needs Roof Surface Material" in text
    assert "roof_classification" not in text and "OK_TO_QUOTE" not in text    # no raw ids or codes
    assert d["summary"]["headline"].startswith("Waiting on the producer")
