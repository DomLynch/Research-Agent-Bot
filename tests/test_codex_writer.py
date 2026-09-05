"""Subscription transport contracts exercised with a real, offline subprocess."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

from agent.llm_client import (
    CODEX_WRITER_URL, CallSpec, CostLedger, LLMError, build_extract_chain,
    build_judge_chain, chat_json,
)
from agent import settings


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "codex"
    binary.write_text(f"#!{Path(sys.executable).resolve()}\n" + '''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
assert "--ignore-user-config" in args and "--ephemeral" in args
assert args[args.index("--sandbox") + 1] == "read-only"
assert args[args.index("--model") + 1] == "gpt-5.6-sol"
assert 'forced_login_method="chatgpt"' in args
assert 'model_reasoning_effort="high"' in args
for feature in ("shell_tool", "apps", "plugins", "hooks", "multi_agent", "memories"):
    assert "features." + feature + "=false" in args
assert not any(k in os.environ for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL"))
config = next(a for a in args if a.startswith("model_instructions_file="))
assert "Test source-grounding instruction" in Path(json.loads(config.split("=", 1)[1])).read_text()
messages = json.load(sys.stdin)
assert all(m["role"] != "system" for m in messages)
data = json.loads(messages[-1]["content"])
case = data.get("case", "ok")
if case == "hang":
    Path(data["pid_path"]).write_text(str(os.getpid()))
    time.sleep(60)
if case == "orphan":
    if os.fork():
        sys.exit(0)
    Path(data["pid_path"]).write_text(str(os.getpid()))
    time.sleep(60)
if case == "quota":
    print(json.dumps({"type":"turn.failed", "error":{"message":"usage limit reached"}}))
    sys.exit(1)
if case == "malformed_events":
    print("not json")
    sys.exit(0)
text = "[]" if case == "array" else ("not JSON" if case == "prose" else '{"claim":"source-grounded","receipt_ids":["R1"]}')
print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":text}}))
if case == "tool":
    print(json.dumps({"type":"item.completed","item":{"type":"command_execution","command":"id"}}))
if case == "started_tool":
    print(json.dumps({"type":"item.started","item":{"type":"command_execution","command":"id"}}))
if case == "null_item":
    print(json.dumps({"type":"item.completed","item":None}))
if case != "incomplete":
    print(json.dumps({"type":"turn.completed","usage":{"input_tokens":-1 if case == "negative_usage" else 1234,"output_tokens":56}}))
''')
    binary.chmod(0o700)
    monkeypatch.setenv("CODEX_WRITER_BIN", str(binary))
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.setenv(key, "must-not-reach-child")
    return binary


async def call(case: str = "ok", *, timeout: float = 5, ledger: CostLedger | None = None, **data):
    def reject_http(request):
        pytest.fail(f"writer attempted paid HTTP: {request.url}")
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject_http)) as client:
        return await chat_json(
            messages=[
                {"role": "system", "content": "Test source-grounding instruction"},
                {"role": "user", "content": json.dumps({"case": case, **data})},
            ],
            chain=(
                CallSpec(CODEX_WRITER_URL, "", "gpt-5.6-sol", timeout, 5),
                CallSpec("https://openrouter.ai/api/v1", "paid-key", "fallback"),
            ),
            client=client, ledger=ledger,
        )


def test_subscription_writer_returns_json_and_records_usage_without_api_key(cli):
    ledger = CostLedger()
    response = asyncio.run(call(ledger=ledger))
    assert response.parsed == {"claim": "source-grounded", "receipt_ids": ["R1"]}
    assert (response.input_tokens, response.output_tokens) == (1234, 56)
    assert response.model == "gpt-5.6-sol"
    record = ledger.to_dict()["calls"][0]
    assert record["cost_usd"] == 0
    assert len(record["attempts"]) == 1
    assert record["attempts"][0]["billing"] == "codex_subscription"


@pytest.mark.parametrize("case", ["quota", "malformed_events", "array", "prose", "tool", "incomplete", "started_tool", "null_item", "negative_usage"])
def test_failed_writer_never_retries_or_falls_back(cli, case):
    ledger = CostLedger()
    with pytest.raises(LLMError, match="no paid fallback"):
        asyncio.run(call(case, ledger=ledger))
    assert ledger.calls == []


@pytest.mark.parametrize("case,cancel", [("hang", False), ("hang", True), ("orphan", False)])
def test_timeout_and_cancellation_reap_process(cli, tmp_path, case, cancel):
    pid_path = tmp_path / "child.pid"

    async def run():
        task = asyncio.create_task(call(case, timeout=5 if cancel else 0.5, pid_path=str(pid_path)))
        if cancel:
            for _ in range(100):
                if pid_path.exists():
                    break
                await asyncio.sleep(0.01)
            assert pid_path.exists()
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else LLMError):
            await task

    asyncio.run(run())
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_missing_cli_fails_closed(monkeypatch):
    monkeypatch.setenv("CODEX_WRITER_BIN", "/missing/codex-writer")
    with pytest.raises(LLMError, match="launch failed"):
        asyncio.run(call())


def test_live_route_keeps_independent_reviewers(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_REPO_ROOT", tmp_path)
    monkeypatch.setenv("WRITER_PROVIDER", "codex")
    monkeypatch.setenv("WRITER_MODEL", "gpt-5.6-sol")
    monkeypatch.setenv("OPENROUTER_API_KEY", "reviewer-key")
    monkeypatch.setenv("JUDGE_MODEL", "google/gemma-4-31b-it")
    monkeypatch.setenv("FALLBACK_MODEL", "mistralai/mistral-small-2603")
    config = settings.load_settings()
    writer, = build_extract_chain(config)
    assert writer.base_url == CODEX_WRITER_URL and writer.api_key == ""
    reviewers = build_judge_chain(config)
    assert [spec.model for spec in reviewers] == ["google/gemma-4-31b-it", "mistralai/mistral-small-2603"]
    assert all(spec.api_key == "reviewer-key" and spec.base_url != CODEX_WRITER_URL for spec in reviewers)
