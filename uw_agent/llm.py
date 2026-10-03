"""Thin Claude client for the three LLM edges (evidence interpreter, email composer, summarizer).

One method, `structured()`: a single Messages call whose reply is constrained to a JSON schema
(`output_config.format`) and validated into a pydantic model. No tools, no agent loop (D4):
the LLM only reads evidence and writes words; deterministic code decides everything else.
Refusals / truncation raise typed errors so every caller can degrade to a deterministic fallback.
Every call is recorded (tokens, model, effort, request id) for cost and evidence.

Model notes (claude-sonnet-5-5): thinking stays on by default (cannot be disabled; effort is the
control, so we set it per task), no sampling params, no forced tool use (hence structured outputs).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from uw_agent.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


class LLMRefusal(LLMError):
    """The model declined (stop_reason == 'refusal')."""


@dataclass
class CallRecord:
    task: str
    model: str
    effort: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    request_id: Optional[str] = None
    latency_s: float = 0.0
    stop_reason: Optional[str] = None


class StructuredLLM(Protocol):
    calls: list[CallRecord]

    def structured(self, *, task: str, system: str, user: str, schema: type[T], effort: str = "low",
                   max_tokens: int = 2000) -> T: ...

    def runtime_config(self) -> dict[str, Any]: ...


@dataclass
class AnthropicLLM:
    settings: Settings = field(default_factory=get_settings)
    client: Any = None
    calls: list[CallRecord] = field(default_factory=list)
    efforts: dict[str, str] = field(default_factory=dict)
    _tl: Any = field(default_factory=threading.local, repr=False)

    @property
    def last_call(self) -> Optional[CallRecord]:
        """The calling thread's most recent call (lets parallel workers attribute usage to their lead)."""
        return getattr(self._tl, "rec", None)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)  # fails fast if unset

    def structured(self, *, task: str, system: str, user: str, schema: type[T], effort: str = "low",
                   max_tokens: int = 2000) -> T:
        model = self.settings.model_for(task)
        self.efforts[task] = effort
        t0 = time.time()
        try:
            resp = self.client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort,
                               "format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)}},
            )
        except anthropic.APIError as e:  # SDK already retried 408/409/429/5xx
            raise LLMError(f"{task}: API error: {e}") from e
        usage = getattr(resp, "usage", None)
        rec = CallRecord(
            task, model, effort,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            request_id=getattr(resp, "_request_id", None), latency_s=round(time.time() - t0, 3),
            stop_reason=resp.stop_reason)
        self.calls.append(rec)
        self._tl.rec = rec
        if resp.stop_reason == "refusal":
            raise LLMRefusal(f"{task}: model declined ({getattr(resp, 'stop_details', None)})")
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"{task}: response truncated at max_tokens={max_tokens}")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise LLMError(f"{task}: no text block in response")
        try:
            return schema.model_validate_json(text)
        except ValueError as e:
            raise LLMError(f"{task}: response did not match schema: {e}") from e

    def runtime_config(self) -> dict[str, Any]:
        """Recorded with every run/eval (D10): models and efforts are env/config, not file hashes."""
        tasks = ("interpreter", "composer", "summarizer")
        return {"models": {t: self.settings.model_for(t) for t in tasks},
                "efforts": {t: self.efforts.get(t, DEFAULT_EFFORT[t]) for t in tasks}}


DEFAULT_EFFORT = {"interpreter": "low", "composer": "low", "summarizer": "low"}


def get_llm(kind: Optional[str] = None) -> StructuredLLM:
    """Backend by `kind` or UW_LLM: `anthropic` (API key), `claude-code` (local Claude Code login, D26), or
    `offline` (rule-based stand-in). Unset: the API when ANTHROPIC_API_KEY is present, else a helpful error."""
    import os
    kind = (kind or os.environ.get("UW_LLM", "")).strip().lower()
    if not kind:
        kind = "anthropic" if os.environ.get("ANTHROPIC_API_KEY", "").strip() else ""
    if kind == "claude-code":
        from uw_agent.claude_code_llm import ClaudeCodeLLM
        return ClaudeCodeLLM()
    if kind == "offline":
        from uw_agent.offline_llm import OfflineLLM
        return OfflineLLM()
    if kind == "anthropic":
        return AnthropicLLM()
    raise RuntimeError("No LLM backend configured. Set ANTHROPIC_API_KEY (API), or UW_LLM=claude-code to use your "
                       "local Claude Code login (no API key), or UW_LLM=offline for the rule-based stand-in.")


if __name__ == "__main__":  # python -m uw_agent.llm : tiny connectivity check (spends a few tokens)
    class Ping(BaseModel):
        ok: bool

    llm = get_llm()
    r = llm.structured(task="interpreter", system="Reply with JSON.", user="Set ok to true.", schema=Ping)
    c = llm.calls[-1]
    print(f"ok={r.ok} model={c.model} in={c.input_tokens} out={c.output_tokens} request_id={c.request_id}")
