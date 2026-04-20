from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


MARKDOWN_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = THINK_BLOCK_RE.sub("", text).strip()
    fence_match = MARKDOWN_FENCE_RE.search(cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            result, _ = decoder.raw_decode(cleaned[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result
    return {}


def _usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = {
        "input_tokens": int(payload.get("usage", {}).get("prompt_tokens", 0) or 0),
        "output_tokens": int(payload.get("usage", {}).get("completion_tokens", 0) or 0),
    }
    usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


@dataclass(slots=True)
class ChatClient:
    provider_name: str = "minimax"
    model: str = "MiniMax-M2.7-highspeed"
    base_url: str = "https://api.minimax.io/v1"
    api_key_env: str = "MINIMAX_API_KEY"
    prompt_version: str = "research-agent-bot/minimax-v0"
    timeout_sec: float = 45.0
    retries: int = 1
    retry_backoff_sec: float = 1.5
    transport: httpx.BaseTransport | None = None
    client: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        self.client = httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout_sec,
            transport=self.transport,
            headers={"Authorization": f"Bearer {os.getenv(self.api_key_env, '')}", "Content-Type": "application/json"},
        )

    @classmethod
    def minimax(cls) -> ChatClient:
        return cls(
            model=os.getenv("MINIMAX_MODEL", "MiniMax-M2.7-highspeed"),
            base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
        )

    @classmethod
    def mimo(cls) -> ChatClient:
        return cls(
            provider_name="mimo",
            model=os.getenv("MIMO_MODEL", "mimo-v2-pro"),
            base_url=os.getenv("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
            api_key_env="MIMO_API_KEY",
            prompt_version="research-agent-bot/mimo-v0",
        )

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not os.getenv(self.api_key_env, "").strip():
            raise RuntimeError(f"missing {self.api_key_env}")
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.post(
                    "/chat/completions",
                    json={
                        "model": self.model,
                        "temperature": 0.2,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
                response.raise_for_status()
                payload = response.json()
                message = payload["choices"][0]["message"].get("content") or payload["choices"][0]["message"].get("reasoning_content") or "{}"
                content = _extract_json(message)
                content["usage"] = _usage(payload)
                content["estimated_cost_usd"] = 0.0
                content["prompt_version"] = self.prompt_version
                content["provider"] = self.provider_name
                content["model"] = self.model
                return (content, payload)
            except (httpx.TimeoutException, httpx.HTTPStatusError, json.JSONDecodeError, KeyError) as exc:
                last_error = exc
                retryable = isinstance(exc, httpx.TimeoutException)
                if isinstance(exc, httpx.HTTPStatusError):
                    retryable = exc.response.status_code in {408, 429, 500, 502, 503, 504}
                if not retryable or attempt >= self.retries:
                    raise RuntimeError(f"provider_error: {exc}") from exc
                time.sleep(self.retry_backoff_sec * (attempt + 1))
        raise RuntimeError(f"provider_error: {last_error}") from last_error


# backward compat — tests + old code import MiniMaxClient
MiniMaxClient = ChatClient
