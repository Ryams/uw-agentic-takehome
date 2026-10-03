"""Claude Code backend (D26): contract, error handling, and credential hygiene, against a fake `claude` executable."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

import uw_agent.config  # noqa: F401
from uw_agent import llm as llm_mod
from uw_agent.claude_code_llm import ClaudeCodeLLM
from uw_agent.llm import LLMError, LLMRefusal


class Ping(BaseModel):
    ok: bool


FAKE = r'''#!{py}
import json, os, sys
if "--version" in sys.argv:
    print("9.9.9 (Claude Code)"); sys.exit(0)
stdin = sys.stdin.read()
json.dump({{"argv": sys.argv[1:], "stdin": stdin, "cwd": os.getcwd(), "env_keys": sorted(os.environ)}},
          open(os.environ["FAKE_LOG"], "w"))
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "ok":
    print(json.dumps({{"type": "result", "is_error": False, "result": "{{}}", "structured_output": {{"ok": True}},
        "stop_reason": "tool_use", "session_id": "sess-1",
        "usage": {{"input_tokens": 6, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 7}}}}))
elif mode == "text":
    print(json.dumps({{"is_error": False, "result": json.dumps({{"ok": False}}), "usage": {{}}}}))
elif mode == "error":
    print(json.dumps({{"is_error": True, "subtype": "error_during_execution", "result": "boom"}})); sys.exit(1)
elif mode == "refusal":
    print(json.dumps({{"is_error": False, "stop_reason": "refusal", "result": "", "usage": {{}}}}))
elif mode == "garbage":
    print("not json"); sys.exit(2)
elif mode == "wrong":
    print(json.dumps({{"is_error": False, "structured_output": {{"nope": 1}}, "usage": {{}}}}))
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    exe = tmp_path / "claude"
    exe.write_text(FAKE.format(py=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "log.json"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-reach-the-child")
    return exe, log


def call(fake, mode="ok", monkeypatch=None, **kw):
    exe, log = fake
    os.environ["FAKE_MODE"] = mode
    c = ClaudeCodeLLM(binary=str(exe), retries=kw.pop("retries", 0), **kw)
    return c, c.structured(task="composer", system="SYS", user="USER TEXT", schema=Ping, effort="low")


def test_structured_parses_output_and_records_usage(fake):
    c, r = call(fake)
    assert r == Ping(ok=True)
    rec = c.calls[0]
    assert (rec.input_tokens, rec.output_tokens, rec.cache_read_tokens, rec.request_id) == (106, 7, 50, "sess-1")
    cfg = c.runtime_config()
    assert cfg["backend"] == "claude-code" and cfg["claude_cli"].startswith("9.9.9") and "composer" in cfg["models"]


def test_falls_back_to_result_text_when_no_structured_output(fake):
    assert call(fake, "text")[1] == Ping(ok=False)


def test_command_is_a_plain_structured_call_and_leaks_no_credentials(fake):
    call(fake)
    seen = json.loads(fake[1].read_text())
    argv = seen["argv"]
    assert argv[0] == "-p" and "--json-schema" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--tools") + 1] == "" and "--disable-slash-commands" in argv
    assert argv[argv.index("--system-prompt") + 1] == "SYS"
    assert "USER TEXT" not in argv and seen["stdin"] == "USER TEXT"          # prompt on stdin, not in the process list
    assert "ANTHROPIC_API_KEY" not in seen["env_keys"]                       # never silently switch to metered API billing
    assert "sk-ant" not in json.dumps(seen)
    assert Path(seen["cwd"]).resolve() != uw_agent.config.ROOT              # empty temp dir: no repo CLAUDE.md or skills
    assert "--bare" not in argv                                              # --bare would ignore the subscription login


@pytest.mark.parametrize("mode", ["error", "garbage", "wrong"])
def test_failures_raise_llm_error_so_callers_fall_back(fake, mode):
    with pytest.raises(LLMError):
        call(fake, mode)


def test_refusal_is_not_retried(fake):
    with pytest.raises(LLMRefusal):
        call(fake, "refusal", retries=3)


def test_one_retry_on_transient_failure(fake, tmp_path):
    exe, log = fake
    counter = tmp_path / "n"
    wrapper = tmp_path / "claude2"
    wrapper.write_text(f"""#!{sys.executable}
import os, subprocess, sys
if "--version" in sys.argv: print("9.9.9"); sys.exit(0)
n = int(open({str(counter)!r}).read()) if os.path.exists({str(counter)!r}) else 0
open({str(counter)!r}, "w").write(str(n + 1))
os.environ["FAKE_MODE"] = "error" if n == 0 else "ok"
sys.exit(subprocess.run([{str(exe)!r}] + sys.argv[1:], stdin=sys.stdin).returncode)
""")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    c = ClaudeCodeLLM(binary=str(wrapper), retries=1)
    assert c.structured(task="composer", system="s", user="u", schema=Ping) == Ping(ok=True)
    assert int(counter.read_text()) == 2


def test_missing_cli_fails_fast_with_instructions():
    with pytest.raises(RuntimeError, match="Claude Code CLI not found"):
        ClaudeCodeLLM(binary="definitely-not-a-real-binary-xyz")


def test_backend_selection(monkeypatch, fake):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("UW_LLM", raising=False)
    with pytest.raises(RuntimeError, match="UW_LLM=claude-code"):
        llm_mod.get_llm()
    monkeypatch.setenv("UW_LLM", "offline")
    assert type(llm_mod.get_llm()).__name__ == "OfflineLLM"
    monkeypatch.setenv("CLAUDE_BIN", str(fake[0]))
    assert type(llm_mod.get_llm("claude-code")).__name__ == "ClaudeCodeLLM"


def test_repository_contains_no_secrets_or_auth_material():
    """Tracked files never contain API keys or tokens, and local secret files are ignored."""
    root = uw_agent.config.ROOT
    files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split("\n")
    assert ".env" not in files
    ignored = (root / ".gitignore").read_text()
    assert ".env" in ignored and "var/" in ignored
    bad = []
    for f in files:
        p = root / f
        if not f or not p.is_file() or p.suffix in (".png", ".jpg", ".zip", ".db"):
            continue
        text = p.read_text(errors="ignore")
        for needle in ("sk-ant-api", "sk-ant-oat", "sk-ant-ort", "sk-ant-sid", "ANTHROPIC_AUTH_TOKEN=",
                       "CLAUDE_CODE_OAUTH_TOKEN="):
            if needle in text and not f.endswith("test_claude_code_llm.py"):
                bad.append((f, needle))
        for line in text.splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY=") and line.split("=", 1)[1].split("#")[0].strip():
                bad.append((f, "ANTHROPIC_API_KEY has a value"))
    assert bad == []
