"""LLM edges (milestone 4): client wrapper, evidence interpreter, email composer, summarizer.
All offline: a scripted fake model and a stub Anthropic client. Model QUALITY is measured in the evals."""

import json

import pytest

import uw_agent.config  # noqa: F401
from tests.fakes import FakeLLM, fake_anthropic_client
from uw_agent import composer, interpreter, summarizer
from uw_agent.composer import (Ask, ComposedEmail, ComposedQuestion, CondGroup, EmailPlan, GroupLeadIn, ask_for,
                               compose_email, describe_chain, template_email)
from uw_agent.config import get_settings
from uw_agent.interpreter import Interpretation, interpret
from uw_agent.llm import AnthropicLLM, LLMError, LLMRefusal
from uw_agent.summarizer import Summary, summarize
from uw_agent.tools.base import LookupResult


# --- client wrapper -------------------------------------------------------------------------------

def test_structured_call_shape_and_parsing():
    seen = []
    out = Interpretation(determination="value", value="Inground", confidence="high", rationale="r")
    llm = AnthropicLLM(client=fake_anthropic_client(out.model_dump_json(), capture=seen))
    r = llm.structured(task="interpreter", system="S", user="U", schema=Interpretation, effort="low", max_tokens=300)
    assert r == out
    kw = seen[0]
    assert kw["model"] == get_settings().model_for("interpreter") and kw["max_tokens"] == 300
    assert kw["output_config"]["effort"] == "low" and kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "temperature" not in kw and "thinking" not in kw and "tool_choice" not in kw   # not allowed on Sonnet 5.5
    c = llm.calls[0]
    assert (c.input_tokens, c.output_tokens, c.request_id) == (11, 7, "req_test")
    assert llm.runtime_config()["models"]["composer"] == get_settings().model_for("composer")


def test_structured_error_paths():
    for kwargs, exc in [({"stop_reason": "refusal", "text": "{}"}, LLMRefusal),
                        ({"stop_reason": "max_tokens", "text": "{"}, LLMError),
                        ({"text": "not json"}, LLMError),
                        ({"content": []}, LLMError)]:
        with pytest.raises(exc):
            AnthropicLLM(client=fake_anthropic_client(**kwargs)).structured(
                task="composer", system="S", user="U", schema=Interpretation)


def test_missing_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicLLM()


# --- evidence interpreter ---------------------------------------------------------------------------

def found(topic, *ev, status="found"):
    return LookupResult("maps_zillow", topic, status, list(ev), ["Zillow listing (mock)"])


def test_no_model_call_when_nothing_to_read():
    llm = FakeLLM({})
    r = interpret(llm, "pool_type", found("pool_type", "No swimming pool visible in satellite imagery.", status="not_found"))
    assert r.status == "nothing_seen" and not r.used_llm and llm.prompts == []
    assert interpret(llm, "pool_type", LookupResult("maps_zillow", "pool_type", "unavailable")).status == "unavailable"


def test_interpreter_values_validated_and_coerced():
    ev = found("pool_type", "Satellite imagery shows an in-ground swimming pool.")
    ok = FakeLLM({"interpreter": Interpretation(determination="value", value="Inground", confidence="high", rationale="explicit")})
    r = interpret(ok, "pool_type", ev)
    assert (r.status, r.value, r.used_llm) == ("value", "Inground", True)
    assert "allowed options" in ok.prompts[0]["user"] and "Inground" in ok.prompts[0]["user"]
    assert "Playbook notes" in ok.prompts[0]["user"] and "google maps" in ok.prompts[0]["user"].lower()   # sticky note passed in
    toggle = FakeLLM({"interpreter": Interpretation(determination="value", value="true", confidence="medium", rationale="x")})
    assert interpret(toggle, "pool_has_diving_board_or_slide", found("pool_has_diving_board_or_slide", "diving board")).value is True
    bad = FakeLLM({"interpreter": Interpretation(determination="value", value="Lagoon", confidence="high", rationale="x")})
    r = interpret(bad, "pool_type", ev)
    assert r.status == "unclear" and r.value is None and "invalid value" in r.error      # never an out-of-registry value


def test_interpreter_ambiguous_caps_confidence_and_errors_degrade():
    amb = found("pool_type", "A blue rectangle; could be a pool or a tarp.", status="ambiguous")
    sure = FakeLLM({"interpreter": Interpretation(determination="value", value="Inground", confidence="high", rationale="x")})
    assert interpret(sure, "pool_type", amb).confidence == "low"
    unclear = FakeLLM({"interpreter": Interpretation(determination="unclear", value="", confidence="low", rationale="blurry")})
    assert interpret(unclear, "pool_type", amb).status == "unclear"
    refuse = FakeLLM({"interpreter": LLMRefusal("declined")})
    r = interpret(refuse, "pool_type", found("pool_type", "pool"))
    assert r.status == "unclear" and "declined" in r.error                                # degrade, never crash


# --- email composer ------------------------------------------------------------------------------------

def plan():
    chain = [{"node": "pool_type", "branch": "Inground", "when": 'pool_type == "Inground"'},
             {"node": "inground_security", "branch": "Fenced", "when": 'pool_security == "Fenced"'}]
    return EmailPlan(
        "LEAD-1", "1240 Ridgecrest Rd, Naples FL", "producer@example.com",
        asks=[ask_for("roof_material"), ask_for("trust_name")],
        groups=[CondGroup(1, chain, [ask_for("pool_fence_self_locking_or_safety_cover")])])


def good_email(p, **override):
    qs = [ComposedQuestion(field=a.field, group_id=0, question=f"What is the {a.label.lower()}?") for a in p.asks]
    qs += [ComposedQuestion(field=a.field, group_id=g.id, question=f"{a.label}?") for g in p.groups for a in g.asks]
    d = dict(subject=f"Quick questions on {p.address}", greeting="Hello,", intro="To finish quoting we need three details.",
             questions=qs, group_lead_ins=[GroupLeadIn(group_id=g.id, lead_in="If the pool is fenced:") for g in p.groups],
             closing="One reply covering everything is ideal.")
    d.update(override)
    return ComposedEmail(**d)


def test_ask_for_uses_registry_and_non_registry_metadata():
    a = ask_for("roof_material")
    assert a.kind == "select" and "Slate" in a.options
    f = ask_for("pool_fence_self_locking_or_safety_cover")
    assert f.kind == "toggle" and "self-locking" in f.label


def test_describe_chain_is_readable():
    assert describe_chain(plan().groups[0].chain) == "Pool Type is Inground; Pool Security is Fenced"


def test_compose_assembles_exactly_the_planned_asks():
    p = plan()
    llm = FakeLLM({"composer": good_email(p)})
    e = compose_email(llm, p)
    assert e.used_llm and e.fallback_reason is None and e.to == "producer@example.com"
    body = e.body
    assert body.index("1. What is the roof surface material?") < body.index("2. What is the name of trust?") < body.index("If the pool is fenced:")
    assert "(choose one: Architecture Shingles | " in body and "(yes / no)" in body       # options appended by code
    assert body.count("?") >= 3 and body.rstrip().endswith("Stand Underwriting")
    assert "condition chain" in llm.prompts[0]["user"] and "group_id=1" in llm.prompts[0]["user"]


def test_compose_retries_once_then_falls_back_to_template():
    p = plan()
    missing = good_email(p, questions=good_email(p).questions[:-1])               # drops the conditional ask
    extra = good_email(p, questions=good_email(p).questions + [ComposedQuestion(field="owner_email", group_id=0, question="?")])
    llm = FakeLLM({"composer": [missing, good_email(p)]})                         # bad then good
    e = compose_email(llm, p)
    assert e.used_llm and llm.n_calls("composer") == 2 and "rejected" in llm.prompts[1]["user"]
    llm2 = FakeLLM({"composer": [missing, extra]})                                # bad twice -> template
    e2 = compose_email(llm2, p)
    assert not e2.used_llm and "invalid composition after retry" in e2.fallback_reason and llm2.n_calls("composer") == 2
    for field in ("Roof Surface Material", "Name of trust", "self-locking"):
        assert field in e2.body                                                    # template still asks everything
    refuse = compose_email(FakeLLM({"composer": LLMRefusal("declined")}), p)
    assert not refuse.used_llm and "llm error" in refuse.fallback_reason


def test_template_email_is_valid_and_complete():
    e = template_email(plan())
    assert "LEAD-1" in e.subject and "If Pool Type is Inground; Pool Security is Fenced:" in e.body
    assert e.body.count("\n   ") == 1                                              # conditional ask indented under its group
    with pytest.raises(ValueError):
        compose_email(FakeLLM({}), EmailPlan("L", "a", "t"))                       # never email with nothing to ask


# --- summarizer ---------------------------------------------------------------------------------------------

REPORT = {"state": "ready_to_quote", "decision": "quote_with_conditions",
          "protocols": [{"protocol": "roof_class", "status": "decided", "outcome": "CONFIRM_CLASS_A_60_DAYS_OR_DECLINE"}],
          "assumptions": [{"field": "pool_type", "value": "None", "why": "nothing seen on Maps/Zillow"}],
          "conflicts": [{"message": "zero acreage"}]}


def test_summarizer_uses_model_and_falls_back():
    s = Summary(headline="Ready to quote with a roof condition", rationale=["roof_class: confirm Class A in 60 days"],
                uncertainties=["assumed no pool"], suggested_action="Approve.")
    got, used = summarize(FakeLLM({"summarizer": s}), REPORT)
    assert used and got == s
    got, used = summarize(FakeLLM({"summarizer": LLMError("down")}), REPORT)
    assert not used and "ready to quote" in got.headline and any("assumed pool_type" in u for u in got.uncertainties)
    assert "conflict: zero acreage" in got.uncertainties
    empty = Summary(headline="", rationale=[], uncertainties=[], suggested_action="")
    assert summarize(FakeLLM({"summarizer": empty}), REPORT)[1] is False          # empty model output -> fallback


def test_prompts_are_loaded_and_versioned():
    from uw_agent import versioning
    live = versioning.live_components()
    for comp in ("evidence_interpreter", "email_composer", "summarizer"):
        assert any(f.endswith(".md") for f in live[comp]["files"]), comp          # prompt text is part of the component hash
