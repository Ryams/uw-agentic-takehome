"""Claude Code backend for the structured-LLM interface (D26): same `structured()` contract as `AnthropicLLM`,
but each call runs the locally installed `claude` CLI in print mode, authenticated by the user's own Claude Code
login (a Pro/Max subscription) instead of an API key.

What this module does NOT do: read, store, log or forward any credential. Authentication is entirely inside the
`claude` binary (its own keychain/login). We strip `ANTHROPIC_API_KEY` from the child's environment so a stray
key can never silently switch a "subscription" run to metered API billing, and we run in an empty temp directory
with no tools, no skills and no session persistence so the CLI behaves as a plain structured-output call.

Trade-offs vs the API backend: each call starts a process (a few seconds), calls count against subscription usage
limits, and concurrency is capped (UW_CLAUDE_CODE_CONCURRENCY, default 3).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from uw_agent.config import Settings, get_settings
from uw_agent.llm import DEFAULT_EFFORT, CallRecord, LLMError, LLMRefusal, T


@dataclass
class ClaudeCodeLLM:
    settings: Settings = field(default_factory=get_settings)
    binary: str = field(default_factory=lambda: os.environ.get("CLAUDE_BIN", "claude"))
    timeout_s: float = 180.0
    retries: int = 1
    calls: list[CallRecord] = field(default_factory=list)
    efforts: dict[str, str] = field(default_factory=dict)
    _tl: Any = field(default_factory=threading.local, repr=False)
    _sem: Any = field(default=None, repr=False)
    _version: Optional[str] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._sem = threading.BoundedSemaphore(max(1, int(os.environ.get("UW_CLAUDE_CODE_CONCURRENCY", "3"))))
        try:                                                  # fail fast and clearly if the CLI is not installed
            self._version = self._run_plain(["--version"]).strip()
        except (OSError, subprocess.SubprocessError) as e:
            raise RuntimeError(
                f"Claude Code CLI not found or not working ({self.binary!r}): {e}. Install Claude Code and run "
                "`claude` once to log in with your subscription (see README), or set UW_LLM=anthropic with an API key."
            ) from e

    @property
    def last_call(self) -> Optional[CallRecord]:
        return getattr(self._tl, "rec", None)

    @staticmethod
    def _env() -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        env.setdefault("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1")
        return env

    def _run_plain(self, args: list[str]) -> str:
        return subprocess.run([self.binary, *args], capture_output=True, text=True, timeout=30, env=self._env(),
                              check=True).stdout

    def structured(self, *, task: str, system: str, user: str, schema: type[T], effort: str = "low",
                   max_tokens: int = 2000) -> T:
        model = self.settings.model_for(task)
        self.efforts[task] = effort
        cmd = [self.binary, "-p", "--output-format", "json", "--json-schema", json.dumps(schema.model_json_schema()),
               "--system-prompt", system, "--model", model, "--effort", effort,
               "--tools", "", "--disable-slash-commands", "--no-session-persistence"]
        last: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                with self._sem, tempfile.TemporaryDirectory(prefix="uw-cc-") as cwd:
                    p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=self.timeout_s,
                                       cwd=cwd, env=self._env())
                return self._parse(task, model, effort, schema, p, time.time() - t0)
            except LLMRefusal:
                raise
            except (LLMError, subprocess.TimeoutExpired) as e:
                last = e
        raise LLMError(f"{task}: claude CLI failed after {self.retries + 1} attempt(s): {last}") from last

    def _parse(self, task: str, model: str, effort: str, schema: type[T], p: subprocess.CompletedProcess,
               latency: float) -> T:
        try:
            out = json.loads(p.stdout)
        except ValueError:
            raise LLMError(f"{task}: claude CLI exit {p.returncode}, unparseable output: {(p.stderr or p.stdout)[:200]!r}")
        usage = out.get("usage") or {}
        rec = CallRecord(task, model, effort,
                         input_tokens=(usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0),
                         output_tokens=usage.get("output_tokens") or 0,
                         cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
                         request_id=out.get("session_id"), latency_s=round(latency, 3), stop_reason=out.get("stop_reason"))
        self.calls.append(rec)
        self._tl.rec = rec
        if out.get("is_error") or p.returncode != 0:
            raise LLMError(f"{task}: claude CLI error ({out.get('subtype')}): {str(out.get('result'))[:200]}")
        if out.get("stop_reason") == "refusal":
            raise LLMRefusal(f"{task}: model declined")
        payload = out.get("structured_output")
        try:
            if payload is not None:
                return schema.model_validate(payload)
            return schema.model_validate_json(out.get("result") or "")
        except ValueError as e:
            raise LLMError(f"{task}: response did not match schema: {e}") from e

    def runtime_config(self) -> dict[str, Any]:
        tasks = ("interpreter", "composer", "summarizer")
        return {"backend": "claude-code", "claude_cli": self._version,
                "models": {t: self.settings.model_for(t) for t in tasks},
                "efforts": {t: self.efforts.get(t, DEFAULT_EFFORT[t]) for t in tasks}}
