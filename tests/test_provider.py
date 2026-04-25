from __future__ import annotations


import httpx

from agent.provider import MimoClient, _extract_json


def test_clean_json():
    result = _extract_json('{"question": "test", "findings": "ok"}')
    assert result == {"question": "test", "findings": "ok"}


def test_prose_before_json():
    raw = 'Here is your JSON:\n{"question": "test", "findings": "ok"}'
    result = _extract_json(raw)
    assert result == {"question": "test", "findings": "ok"}


def test_markdown_fence():
    raw = '```json\n{"question": "test", "findings": "ok"}\n```'
    result = _extract_json(raw)
    assert result == {"question": "test", "findings": "ok"}


def test_think_block_then_prose_then_json():
    raw = "<think>Let me think about this...</think>\nSure, here is the result:\n{\"question\": \"test\"}"
    result = _extract_json(raw)
    assert result == {"question": "test"}


def test_no_json_returns_empty():
    result = _extract_json("I cannot complete this request.")
    assert result == {}


def test_trailing_commentary_after_json():
    raw = '{"question": "test", "findings": "ok"}\nI hope this helps!'
    result = _extract_json(raw)
    assert result == {"question": "test", "findings": "ok"}


def test_brace_noise_before_real_json():
    raw = 'Scratch note {not real json}\n{"question": "test", "findings": "ok"}'
    result = _extract_json(raw)
    assert result == {"question": "test", "findings": "ok"}


def test_client_complete_json_handles_prose_and_sets_usage(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": 'Scratch note {not real json}\n{"question":"ok","findings":"stable"}\nDone.'
                        }
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        )

    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    client = MimoClient(transport=httpx.MockTransport(handler))
    result, raw = client.complete_json(system_prompt="system", user_prompt="user")

    assert result["question"] == "ok"
    assert result["findings"] == "stable"
    assert result["usage"] == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    assert result["model"] == "mimo-v2.5-pro"
    assert round(result["estimated_cost_usd"], 8) == 0.000032
    assert raw["choices"][0]["message"]["content"] is not None


def test_mimo_client_from_env(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"question":"ok","conclusion":"done"}'}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    client = MimoClient.from_env()
    client.transport = httpx.MockTransport(handler)
    client.__post_init__()
    result, _ = client.complete_json(system_prompt="system", user_prompt="user")

    assert result["model"] == "mimo-v2.5-pro"
