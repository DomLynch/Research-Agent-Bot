"""Subscription transport contracts exercised with a real, offline subprocess."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

from agent.llm_client import (
    CODEX_WRITER_URL, CallSpec, CostLedger, LLMError, build_extract_chain,
    build_judge_chain, chat_json,
)
from agent import settings
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import final_reviewer  # noqa: E402


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "codex"
    binary.write_text(f"#!{Path(sys.executable).resolve()}\n" + '''
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
assert "--ignore-user-config" in args and "--ephemeral" in args
assert args[args.index("--sandbox") + 1] == "read-only"
model = args[args.index("--model") + 1]
assert model in ("gpt-5.6-sol", "gpt-6-sol", "gpt-5.6-terra")
assert 'forced_login_method="chatgpt"' in args
effort = "medium" if model == "gpt-5.6-terra" else "high"
assert 'model_reasoning_effort="' + effort + '"' in args
for feature in ("shell_tool", "apps", "plugins", "hooks", "multi_agent", "memories"):
    assert "features." + feature + "=false" in args
assert not any(k in os.environ for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENROUTER_API_KEY", "OPENAI_BASE_URL"))
config = next(a for a in args if a.startswith("model_instructions_file="))
instructions = Path(json.loads(config.split("=", 1)[1])).read_text()
role = "reviewer" if model == "gpt-5.6-terra" else "writer/extractor"
assert "research " + role in instructions
if model in ("gpt-5.6-sol", "gpt-6-sol"):
    assert "Test source-grounding instruction" in instructions
messages = json.load(sys.stdin)
assert all(m["role"] != "system" for m in messages)
try:
    data = json.loads(messages[-1]["content"])
except ValueError:
    content = messages[-1]["content"]
    data = {"case": content.split("CASE:", 1)[1].split()[0] if "CASE:" in content else "ok"}
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
if case == "ok" and model == "gpt-5.6-terra":
    text = json.dumps({"decision":"revise", "patches":[{"patch_type":"claim", "severity":"P1", "before":"Unsupported claim", "after":"", "reason":"No evidence"}]})
if case.startswith("schema_"):
    text = json.dumps({"schema_null":{"patches":None}, "schema_missing":{"verdict":"reject"}, "schema_incomplete":{"patches":[{"patch_type":"claim","severity":"P1"}]}}[case])
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
        task = asyncio.create_task(call(case, timeout=5 if cancel else 2, pid_path=str(pid_path)))
        if cancel:
            for _ in range(100):
                if pid_path.exists():
                    break
                await asyncio.sleep(0.01)
            assert pid_path.exists()
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else LLMError):
            await task

    started = time.monotonic()
    asyncio.run(run())
    assert time.monotonic() - started < 15, "cleanup waited for the child's natural exit"
    # An orphan is reaped by the OS, not by our subprocess wait.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(int(pid_path.read_text()), 0)
        except ProcessLookupError:
            break
        time.sleep(0.01)
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_missing_cli_fails_closed(monkeypatch):
    monkeypatch.setenv("CODEX_WRITER_BIN", "/missing/codex-writer")
    with pytest.raises(LLMError, match="launch failed"):
        asyncio.run(call())


def test_live_route_keeps_independent_reviewers(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_REPO_ROOT", tmp_path)
    monkeypatch.setenv("WRITER_PROVIDER", "codex")
    monkeypatch.setenv("WRITER_MODEL", "gpt-6-sol")
    monkeypatch.setenv("OPENROUTER_API_KEY", "reviewer-key")
    monkeypatch.setenv("JUDGE_MODEL", "google/gemma-4-31b-it")
    monkeypatch.setenv("FALLBACK_MODEL", "mistralai/mistral-small-2603")
    config = settings.load_settings()
    writer, = build_extract_chain(config)
    assert writer.base_url == CODEX_WRITER_URL and writer.api_key == ""
    reviewers = build_judge_chain(config)
    assert [spec.model for spec in reviewers] == ["google/gemma-4-31b-it", "mistralai/mistral-small-2603"]
    assert all(spec.api_key == "reviewer-key" and spec.base_url != CODEX_WRITER_URL for spec in reviewers)


@pytest.mark.parametrize("case", ["ok", "quota", "prose"])
def test_terra_judge_medium_falls_back_only_on_technical_failure(cli, tmp_path, monkeypatch, case):
    monkeypatch.setattr(settings, "_REPO_ROOT", tmp_path)
    monkeypatch.setenv("WRITER_PROVIDER", "codex")
    monkeypatch.setenv("WRITER_MODEL", "gpt-6-sol")
    monkeypatch.setenv("JUDGE_MODEL", "gpt-5.6-terra")
    monkeypatch.setenv("FALLBACK_MODEL", "z-ai/glm-5.3-flash")
    config = settings.load_settings()
    writer, = build_extract_chain(config)
    assert writer.model == "gpt-6-sol" and writer.reasoning_effort == "high"
    chain = build_judge_chain(config)
    assert [s.model for s in chain] == ["gpt-5.6-terra", "z-ai/glm-5.3-flash"]
    calls = []

    def fallback(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["model"] == "z-ai/glm-5.3-flash"
        assert payload["reasoning"] == {"effort": "low", "exclude": True}
        return httpx.Response(200, json={"choices":[{"message":{"content":'{"decision":"reject"}'}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fallback)) as client:
            return await chat_json(messages=[{"role":"user", "content":json.dumps({"case":case})}], chain=chain, client=client)

    response = asyncio.run(run())
    assert response.parsed["decision"] == ("revise" if case == "ok" else "reject")
    assert len(calls) == (0 if case == "ok" else 1)
    assert len(response.attempts) == (1 if case == "ok" else 2)


@pytest.mark.parametrize("case", ["ok", "quota", "prose", "schema_null", "schema_missing", "schema_incomplete"])
def test_terra_final_review_preserves_negative_verdict_and_uses_glm_on_failure(cli, monkeypatch, case):
    monkeypatch.delenv("FINAL_LAYER_LOW_PATCH_FALLBACK_MODEL", raising=False)
    if case == "ok":
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    calls = []

    def fallback(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["model"] == "z-ai/glm-5.3-flash"
        assert payload["reasoning"] == {"effort":"low", "exclude":True}
        return httpx.Response(200, json={"choices":[{"message":{"content":'{"patches":[]}'}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fallback)) as client:
            result = await final_reviewer.review_paper(
                "Unsupported claim CASE:" + case, {}, {}, client=client,
                model="gpt-5.6-terra", fallback_model="z-ai/glm-5.3-flash",
            )
            if case == "ok":
                repaired = await final_reviewer.repair_flagged_patches(
                    [(result[0][0], "requires source support")], "Unsupported claim",
                    model="gpt-5.6-terra", fallback_model="z-ai/glm-5.3-flash", client=client,
                )
                assert repaired[0].severity == "P1"
            return result

    patches, raw, model, _cost = asyncio.run(run())
    assert model == ("gpt-5.6-terra" if case == "ok" else "z-ai/glm-5.3-flash")
    assert len(calls) == (0 if case == "ok" else 1)
    assert len(raw["_review_attempts"]) == (1 if case == "ok" else 2)
    assert raw["_review_usage"]["billing"] == ("codex_subscription" if case == "ok" else "api")
    if case == "ok":
        assert patches[0].severity == "P1"
