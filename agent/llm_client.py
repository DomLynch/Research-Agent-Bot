"""LLM client — single dependency surface for every LLM call.

Hard rule: LLM PROPOSES. CODE DISPOSES. This module proposes only — every
caller (fact extractor in 3.2c, judge + writer in Day 4) must validate the
returned dict against schema invariants before trusting it.

Three things this module does:
  1. Generic OpenAI-compatible chat-completion calls via httpx — no provider
     SDKs (openai, anthropic, google) so the runtime stays single-dep.
  2. Robust JSON extraction from prose / fence / <think>-wrapped output that
     real models actually emit, even with `response_format=json_object`.
  3. Fallback chains: try `CallSpec`s in order; on transport / parse failure,
     fall through to the next spec. If a spec has no api_key configured,
     skip it (don't fail) — partial-config environments still work.
     Only when every spec fails does `LLMError` fire.

Cost ledger is opt-in: pass a `CostLedger` to `chat_json()` and the response
is appended for later serialization to `cost_log.json`. Without one, the
per-call cost lives on the `LLMResponse` but no aggregation happens.

Async-only. Sync callers wrap with `asyncio.run`. Fact-extraction in Day
3.2c will run N abstract calls concurrently; that concurrency gain is
the whole reason this layer is async.

Day 3.2b ships `chat_json` + `CostLedger` + `build_extract_chain`. Day 4
adds `build_judge_chain` and `build_write_chain` when SPAR / writer land.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

try:
    import httpx
except ModuleNotFoundError:  # deterministic tests can import this module without live LLM deps.
    httpx = None  # type: ignore[assignment]
    _HTTPX_HTTP_ERROR = Exception
else:
    _HTTPX_HTTP_ERROR = httpx.HTTPError

from agent.settings import Settings

__all__ = [
    "LLMError",
    "LLMResponse",
    "CallSpec",
    "CostLedger",
    "chat_json",
    "extract_json",
    "build_extract_chain",
    "build_judge_chain",
]

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


# Pricing table — USD per 1K tokens (input, output). Models not listed
# fall back to (0, 0) so cost is recorded as 0 rather than crashing the
# pipeline when a new model is wired up but not yet priced.
_PRICING: Mapping[str, tuple[float, float]] = {
    # MiMo V2.5 Pro (Xiaomi-hosted): $0.14/1M in, $0.28/1M out
    "mimo-v2.5-pro": (0.00014, 0.00028),
    # Mistral Small via OpenRouter: ~$0.10/1M in, ~$0.30/1M out
    "mistralai/mistral-small-2603": (0.00010, 0.00030),
    # Gemma 4 31B via OpenRouter — Day 4 judge primary
    "google/gemma-4-31b-it": (0.00010, 0.00030),
}


class LLMError(RuntimeError):
    """Raised when every CallSpec in the chain fails or has no api_key."""


@dataclass(frozen=True, slots=True)
class CallSpec:
    """A single (provider, model) call attempt.

    `api_key` may be empty — `chat_json` skips empty-keyed specs and tries
    the next one, which is how the chain degrades when an env var is unset.
    """
    base_url: str
    api_key: str
    model: str
    timeout_sec: float = 60.0


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Parsed response from a successful chat-completion call."""
    text: str  # Raw assistant content (post <think>/fence strip)
    parsed: Mapping[str, Any]  # Parsed JSON object
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


@dataclass(slots=True)
class CostLedger:
    """In-process tally — append per-call, serialize at end of run."""
    calls: list[LLMResponse] = field(default_factory=list)

    def add(self, resp: LLMResponse) -> None:
        self.calls.append(resp)

    def total_usd(self) -> float:
        return sum(c.estimated_cost_usd for c in self.calls)

    def by_model(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for c in self.calls:
            out[c.model] = out.get(c.model, 0.0) + c.estimated_cost_usd
        return out

    def to_dict(self) -> dict[str, Any]:
        """Shape that lands in `runs/<topic>/cost_log.json`."""
        return {
            "total_usd": round(self.total_usd(), 6),
            "by_model": {m: round(v, 6) for m, v in self.by_model().items()},
            "calls": [
                {
                    "model": c.model,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "cost_usd": round(c.estimated_cost_usd, 6),
                }
                for c in self.calls
            ],
        }


# ----- JSON extraction ----------------------------------------------------


def _strip_response(text: str) -> str:
    cleaned = _THINK_RE.sub("", text).strip()
    fence = _FENCE_RE.search(cleaned)
    return fence.group(1).strip() if fence else cleaned


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first valid JSON object out of an LLM response.

    Real LLMs emit `<think>...</think>` blocks, ```json fences, or prose
    around the JSON even with `response_format=json_object` set. This
    handles all three. Raises ValueError when no JSON object is found —
    the caller's schema layer turns that into a structured rejection.
    """
    cleaned = _strip_response(text)
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", cleaned):
        try:
            obj, _ = decoder.raw_decode(cleaned[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("LLM response contained no JSON object")


# ----- Single-spec call ---------------------------------------------------


def _estimate_cost(model: str, input_tok: int, output_tok: int) -> float:
    in_price, out_price = _PRICING.get(model, (0.0, 0.0))
    return input_tok / 1000 * in_price + output_tok / 1000 * out_price


async def _call_one(
    *,
    client: httpx.AsyncClient,
    spec: CallSpec,
    messages: Sequence[Mapping[str, str]],
    enforce_json: bool,
    temperature: float,
    max_tokens: int | None,
    seed: int | None,
) -> LLMResponse:
    """Single OpenAI-compatible chat call. Caller catches errors for fallback."""
    if not spec.api_key:
        raise LLMError(f"missing api_key for model={spec.model}")
    payload: dict[str, Any] = {
        "model": spec.model,
        "temperature": temperature,
        "messages": [dict(m) for m in messages],
    }
    if enforce_json:
        payload["response_format"] = {"type": "json_object"}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if seed is not None:
        # OpenAI-compatible seed: same seed + same prompt + temperature 0
        # → byte-identical response (best-effort; some providers honor
        # this exactly, others approximately). MiMo + OpenRouter both
        # support the field. Day 9.4 ships zero-variance receipts.
        payload["seed"] = int(seed)
    headers = {
        "Authorization": f"Bearer {spec.api_key}",
        "Content-Type": "application/json",
    }
    url = spec.base_url.rstrip("/") + "/chat/completions"
    response = await client.post(
        url, json=payload, headers=headers, timeout=spec.timeout_sec,
    )
    response.raise_for_status()
    body = response.json()
    choice = body["choices"][0]["message"]
    text = choice.get("content") or choice.get("reasoning_content") or "{}"
    parsed = extract_json(text)
    usage = body.get("usage", {}) or {}
    in_tok = int(usage.get("prompt_tokens", 0) or 0)
    out_tok = int(usage.get("completion_tokens", 0) or 0)
    return LLMResponse(
        text=_strip_response(text),
        parsed=parsed,
        model=spec.model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=_estimate_cost(spec.model, in_tok, out_tok),
    )


# ----- Chain orchestration ------------------------------------------------


async def chat_json(
    *,
    messages: Sequence[Mapping[str, str]],
    chain: Sequence[CallSpec],
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    enforce_json: bool = True,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    seed: int | None = None,
) -> LLMResponse:
    """Call CallSpecs in order; return on first success; raise LLMError on all-fail.

    A spec is treated as a failure on:
      - missing `api_key` (skip silently — partial config is normal)
      - `httpx.HTTPError` (transport error or 4xx/5xx response)
      - `ValueError` (JSON extraction failed — model emitted unparseable text)
      - `KeyError` (response shape didn't have `choices[0].message`)

    Day 9.4: when `seed` is set, it's forwarded to every CallSpec in
    the chain. Combined with temperature 0.0 this makes the chat call
    deterministic (same prompt + same seed → same response). Both MiMo
    and OpenRouter (Gemma / Mistral) support the OpenAI-compatible
    seed parameter. None preserves prior stochastic behavior.
    """
    if not chain:
        raise LLMError("chat_json called with empty chain")
    if httpx is None and client is None:
        raise LLMError("httpx is required for live LLM calls")

    own_client = client is None
    c = client or httpx.AsyncClient()
    errors: list[tuple[str, str]] = []
    try:
        for spec in chain:
            if not spec.api_key:
                errors.append((spec.model, "missing api_key"))
                continue
            try:
                resp = await _call_one(
                    client=c,
                    spec=spec,
                    messages=messages,
                    enforce_json=enforce_json,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    seed=seed,
                )
            except (_HTTPX_HTTP_ERROR, ValueError, KeyError, LLMError) as exc:
                errors.append((spec.model, f"{type(exc).__name__}: {exc}"))
                logger.warning(
                    "llm_client: %s failed (%s); trying next in chain",
                    spec.model, type(exc).__name__,
                )
                continue
            if ledger is not None:
                ledger.add(resp)
            return resp
        raise LLMError(
            "every spec in chain failed: "
            + "; ".join(f"{m}: {e}" for m, e in errors)
        )
    finally:
        if own_client:
            await c.aclose()


# ----- Chain builders -----------------------------------------------------


def build_extract_chain(settings: Settings) -> tuple[CallSpec, ...]:
    """Fact-extraction default chain: MiMo (primary) → Mistral (fallback).

    Specs with empty api_keys remain in the chain — `chat_json` skips them.
    A partially-configured environment (only Mistral set, MiMo missing)
    still produces useful work without crashing the pipeline.
    """
    return (
        CallSpec(
            base_url=settings.mimo_base_url,
            api_key=settings.mimo_api_key,
            model=settings.mimo_model,
            timeout_sec=settings.mimo_timeout_sec,
        ),
        CallSpec(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            model=settings.fallback_model,
            timeout_sec=settings.mimo_timeout_sec,
        ),
    )


def build_judge_chain(settings: Settings) -> tuple[CallSpec, ...]:
    """SPAR judge chain: Gemma 4 (primary) → MiMo (fallback) → Mistral.

    Different cognitive style than `build_extract_chain` — judges
    benefit from a stronger reasoning model. Empty-api_key specs are
    skipped at call time so a partial-config env still produces output.
    """
    return (
        CallSpec(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            model=settings.judge_model,
            timeout_sec=settings.mimo_timeout_sec,
        ),
        CallSpec(
            base_url=settings.mimo_base_url,
            api_key=settings.mimo_api_key,
            model=settings.mimo_model,
            timeout_sec=settings.mimo_timeout_sec,
        ),
        CallSpec(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key,
            model=settings.fallback_model,
            timeout_sec=settings.mimo_timeout_sec,
        ),
    )
