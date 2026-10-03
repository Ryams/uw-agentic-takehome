"""Test doubles for the LLM layer (no network, no key)."""

from types import SimpleNamespace
from typing import Any, Callable

from uw_agent.llm import CallRecord, LLMError


class FakeLLM:
    """Scripted StructuredLLM: `script[task]` is a model instance, an exception, or a callable(user, system) -> either.
    A list means 'first call, second call, ...' (last one repeats)."""

    def __init__(self, script: dict[str, Any]):
        self.script, self.prompts, self.calls = script, [], []
        self.last_call = None

    def structured(self, *, task, system, user, schema, effort="low", max_tokens=2000):
        self.prompts.append({"task": task, "system": system, "user": user, "schema": schema, "effort": effort})
        s = self.script[task]
        if isinstance(s, list):
            s = s[min(sum(1 for p in self.prompts if p["task"] == task) - 1, len(s) - 1)]
        if callable(s):
            s = s(user, system)
        if isinstance(s, Exception):
            raise s
        self.last_call = CallRecord(task, "fake", effort)
        self.calls.append(self.last_call)
        return s

    def runtime_config(self):
        return {"models": {}, "efforts": {}}

    def n_calls(self, task):
        return sum(1 for p in self.prompts if p["task"] == task)


def fake_anthropic_client(text=None, stop_reason="end_turn", content=None, capture=None):
    """Stub of anthropic.Anthropic with messages.create returning a canned response."""
    def create(**kw):
        if capture is not None:
            capture.append(kw)
        blocks = content if content is not None else [SimpleNamespace(type="text", text=text)]
        return SimpleNamespace(stop_reason=stop_reason, content=blocks, stop_details=None, _request_id="req_test",
                               usage=SimpleNamespace(input_tokens=11, output_tokens=7, cache_read_input_tokens=0))
    return SimpleNamespace(messages=SimpleNamespace(create=create))
