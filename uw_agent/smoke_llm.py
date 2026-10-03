"""Live smoke test of the three LLM edges (spends a few thousand tokens). Needs ANTHROPIC_API_KEY.

    uv run python -m uw_agent.smoke_llm
"""

from __future__ import annotations

from uw_agent import summarizer
from uw_agent.composer import CondGroup, EmailPlan, ask_for, compose_email
from uw_agent.interpreter import interpret
from uw_agent.llm import get_llm
from uw_agent.tools.base import LookupResult


def main() -> None:
    llm = get_llm()
    print("== interpreter ==")
    for topic, ev, status in [
        ("pool_type", ["Satellite imagery shows an in-ground swimming pool in the rear yard."], "found"),
        ("pool_security", ["Imagery resolution is too low to tell whether the pool area is fenced."], "ambiguous"),
        ("pool_has_diving_board_or_slide", ["Zillow listing photo shows a diving board at the deep end of the pool."], "found"),
    ]:
        r = interpret(llm, topic, LookupResult("maps_zillow", topic, status, ev, ["Zillow listing (mock)"]))
        print(f"  {topic}: {r.status} value={r.value!r} confidence={r.confidence} | {r.rationale}")

    print("\n== composer ==")
    chain = [{"node": "inground_security", "branch": "Fenced", "when": 'pool_security == "Fenced"'}]
    plan = EmailPlan("LEAD-DEMO", "1240 Ridgecrest Rd, Naples FL", "producer@example.com",
                     asks=[ask_for("roof_material"), ask_for("trust_name")],
                     groups=[CondGroup(1, chain, [ask_for("pool_fence_self_locking_or_safety_cover")])])
    e = compose_email(llm, plan)
    print(f"  used_llm={e.used_llm} fallback={e.fallback_reason}\n  Subject: {e.subject}\n")
    print("\n".join("  " + line for line in e.body.splitlines()))

    print("\n== summarizer ==")
    s, used = summarizer.summarize(llm, {
        "state": "ready_to_quote", "decision": "quote_with_conditions",
        "protocols": [{"protocol": "roof_class", "status": "decided", "outcome": "CONFIRM_CLASS_A_60_DAYS_OR_DECLINE",
                       "path": "Non-Class A -> P(F) 0.62 > .50"}],
        "assumptions": [{"field": "pool_type", "value": "None", "why": "nothing seen on Maps/Zillow"}], "conflicts": []})
    print(f"  used_llm={used} | {s.headline}\n  rationale={s.rationale}\n  uncertainties={s.uncertainties}\n  action={s.suggested_action}")

    print("\ncalls:", [(c.task, c.model, c.input_tokens, c.output_tokens) for c in llm.calls])
    print("runtime_config:", llm.runtime_config())


if __name__ == "__main__":
    main()
