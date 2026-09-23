"""Provide async LLM calls, JSON parsing, fallback chains, and cost logging."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

try:
    import httpx
except ModuleNotFoundError:  # deterministic tests can import this module without live LLM deps.
    httpx = None  # type: ignore[assignment]
    _HTTPX_HTTP_ERROR: type[BaseException] = Exception
else:
    _HTTPX_HTTP_ERROR = httpx.HTTPError

from agent.settings import Settings

__all__ = [
    "LLMError",
    "LLMResponse",
    "CallSpec",
    "CostLedger",
    "chat_json",
    "configured_attempts_for_url",
    "extract_json",
    "build_extract_chain",
    "build_judge_chain",
]

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


# Pricing table — USD per 1K tokens (input, output). Models not listed
# fall back to (0, 0) so cost is recorded as 0 rather than crashing the
# pipeline when a new model is wired up but not yet priced.
_PRICING: Mapping[str, tuple[float, float]] = {
    # GLM standard rates; OpenRouter's returned cost includes discounts/cache.
    "z-ai/glm-5.3-flash": (0.00015, 0.00050),
    "MiniMax-M3": (0.00030, 0.00120),
    "mimo-v2.5-pro": (0.00014, 0.00028),
    # Mistral Small via OpenRouter: ~$0.10/1M in, ~$0.30/1M out
    "mistralai/mistral-small-2603": (0.00010, 0.00030),
    # Gemma 4 31B via OpenRouter — Day 4 judge primary
    "google/gemma-4-31b-it": (0.00010, 0.00030),
}


class LLMError(RuntimeError):
    """Raised when every CallSpec in the chain fails or has no api_key."""


CODEX_WRITER_URL = "codex://chatgpt"


@dataclass(frozen=True, slots=True)
class CallSpec:
    """HTTP needs an API key; codex://chatgpt uses saved subscription auth."""
    base_url: str
    api_key: str
    model: str
    timeout_sec: float = 60.0
    max_attempts: int = 1
    reasoning_effort: str = "high"
    role: str = "writer/extractor"


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Parsed response from a successful chat-completion call."""
    text: str  # Raw assistant content (post <think>/fence strip)
    parsed: Mapping[str, Any]  # Parsed JSON object
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    attempts: tuple[Mapping[str, Any], ...] = ()


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
                    "attempts": list(c.attempts),
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
    """Extract an object from fenced/think-wrapped HTTP output, or raise ValueError."""
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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _configured_attempts(base_url: str) -> int:
    default = _env_int("LLM_CALL_ATTEMPTS", 2)
    if "openrouter" in base_url.lower():
        return max(1, _env_int("OPENROUTER_CALL_ATTEMPTS", default))
    return max(1, default)


def configured_attempts_for_url(base_url: str) -> int:
    return _configured_attempts(base_url)


def _request_headers(spec: CallSpec) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {spec.api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter" in spec.base_url.lower():
        referer = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
        if referer:
            headers["HTTP-Referer"] = referer
        headers["X-Title"] = os.environ.get(
            "OPENROUTER_X_TITLE", "Research Agent Bot",
        )
    return headers


def _err_summary(exc: BaseException) -> str:
    text = str(exc).strip()
    if len(text) > 220:
        text = text[:217] + "..."
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _is_retryable_error(exc: BaseException) -> bool:
    if httpx is not None:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in _RETRYABLE_HTTP_STATUS
        if isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
                httpx.PoolTimeout,
            ),
        ):
            return True
    # Some OpenRouter models occasionally return non-JSON despite
    # response_format=json_object. One retry often recovers; schema checks
    # still own correctness after parsing.
    return isinstance(
        exc,
        (ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError),
    )


async def _call_codex(
    spec: CallSpec, messages: Sequence[Mapping[str, str]], max_tokens: int | None,
) -> LLMResponse:
    """One isolated, bounded subscription call; caller owns fallback policy."""
    binary = os.environ.get("CODEX_WRITER_BIN") or next((
        path for path in (
            "/Applications/ChatGPT.app/Contents/Resources/codex", shutil.which("codex"),
        ) if path and Path(path).is_file()
    ), None)
    if not binary:
        raise LLMError("Codex writer CLI missing; set CODEX_WRITER_BIN")
    # Never inherit provider keys, routing overrides, or the application's secrets.
    env = {key: value for key, value in os.environ.items() if key in {
        "HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "CODEX_HOME",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
    }}
    with tempfile.TemporaryDirectory(prefix="v3-writer-") as directory:
        instructions = Path(directory) / "instructions.md"
        instructions.write_text(
            f"You are the research {spec.role}, not a coding assistant. "
            "Return only the requested JSON object. Use only supplied evidence; "
            "never invent sources, findings, numbers, or verification. No tools.\n"
            + "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            + (f"\nOutput limit: {max_tokens} tokens." if max_tokens else ""),
            encoding="utf-8",
        )
        command = [
            binary, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "--skip-git-repo-check", "--sandbox", "read-only", "--model", spec.model,
            "--config", 'forced_login_method="chatgpt"',
            "--config", 'model_provider="openai"',
            "--config", f"model_reasoning_effort={json.dumps(spec.reasoning_effort)}",
            "--config", 'approval_policy="never"',
            "--config", 'web_search="disabled"',
            "--config", "project_doc_max_bytes=0",
            "--config", f"model_instructions_file={json.dumps(str(instructions))}",
            "--json", "-",
        ]
        for feature in (
            "shell_tool", "unified_exec", "apps", "plugins", "hooks", "memories",
            "multi_agent", "browser_use", "computer_use", "image_generation",
            "view_image", "workspace_dependencies", "goals", "sleep_tool",
            "skill_mcp_dependency_install", "skill_search", "chronicle", "code_mode_host",
        ):
            command[1:1] = ["--config", f"features.{feature}=false"]
        try:
            process = await asyncio.create_subprocess_exec(
                *command, cwd=directory, env=env, start_new_session=True,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise LLMError(f"Codex writer launch failed: {type(exc).__name__}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps([
                dict(m) for m in messages if m["role"] != "system"
            ], ensure_ascii=False).encode()), timeout=spec.timeout_sec)
        except (TimeoutError, asyncio.CancelledError) as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.communicate()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise LLMError(f"Codex writer timed out after {spec.timeout_sec:g}s") from exc
    events = [json.loads(line) for line in stdout.decode().splitlines() if line.strip()]
    if not all(isinstance(event, dict) for event in events):
        raise ValueError("Codex writer returned malformed events")
    failure = next((event for event in events if event.get("type") == "turn.failed"), None)
    if process.returncode or failure:
        detail = json.dumps(failure) if failure else stderr.decode(errors="replace")
        raise LLMError(f"Codex writer failed: {detail[-400:]}")
    completed = [event for event in events if event.get("type") == "turn.completed"]
    lifecycle = [event.get("item") for event in events if str(event.get("type", "")).startswith("item.")]
    if any(not isinstance(item, dict) or item.get("type") not in {"agent_message", "reasoning"} for item in lifecycle):
        raise LLMError("Codex writer malformed item or attempted a tool call")
    items = [event["item"] for event in events if event.get("type") == "item.completed"]
    if len(completed) != 1:
        raise LLMError("Codex writer did not complete exactly one turn")
    text = next((item["text"] for item in reversed(items) if item.get("type") == "agent_message"), "")
    usage = completed[-1]["usage"]
    tokens = (usage["input_tokens"], usage["output_tokens"])
    if any(type(n) is not int or n < 0 for n in tokens):
        raise ValueError("Codex writer returned invalid token usage")
    if max_tokens is not None and tokens[1] > max_tokens:
        raise LLMError("Codex writer exceeded the requested output-token limit")
    parsed = json.loads(text)
    if not isinstance(parsed, dict) or not parsed:
        raise ValueError("Codex writer returned no JSON object")
    return LLMResponse(
        text=text, parsed=parsed, model=spec.model,
        input_tokens=tokens[0], output_tokens=tokens[1],
        # No per-token API charge; this consumes the shared Codex plan allowance.
        estimated_cost_usd=0.0,
    )


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
    if spec.base_url == CODEX_WRITER_URL:
        return await _call_codex(spec, messages, max_tokens)
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
    if spec.model == "z-ai/glm-5.3-flash":
        payload["reasoning"] = {"effort": "low", "exclude": True}
        payload.setdefault("max_tokens", 16384)
    if seed is not None:
        # Provider seed is best-effort, not a deterministic-output guarantee.
        payload["seed"] = int(seed)
    url = spec.base_url.rstrip("/") + "/chat/completions"
    response = await client.post(
        url, json=payload, headers=_request_headers(spec),
        timeout=spec.timeout_sec,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, Mapping):
        raise ValueError("chat response body is not an object")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping) or not isinstance(first.get("message"), Mapping):
        raise ValueError("chat response has no message object")
    choice = first["message"]
    text = choice.get("content")
    if not text and spec.model != "z-ai/glm-5.3-flash":
        text = choice.get("reasoning_content")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("chat response has no assistant text")
    parsed = extract_json(text)
    raw_usage = body.get("usage")
    usage = raw_usage if isinstance(raw_usage, Mapping) else {}
    in_tok = int(usage.get("prompt_tokens", 0) or 0)
    out_tok = int(usage.get("completion_tokens", 0) or 0)
    return LLMResponse(
        text=_strip_response(text),
        parsed=parsed,
        model=spec.model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        estimated_cost_usd=(
            float(usage["cost"]) if usage.get("cost") is not None
            else _estimate_cost(spec.model, in_tok, out_tok)
        ),
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
    validate: Callable[[Mapping[str, Any]], None] = lambda _: None,
) -> LLMResponse:
    """Return the first successful spec; subscription writers never fall back.
    HTTP routes forward seed and temperature (best-effort reproducibility).
    Codex uses the spec's reasoning effort; its CLI has no seed or temperature.
    Its output cap is checked after generation, not a server-side token limit.
    """
    if not chain:
        raise LLMError("chat_json called with empty chain")
    if httpx is None and client is None:
        raise LLMError("httpx is required for live LLM calls")

    own_client = client is None
    c = client or httpx.AsyncClient()
    errors: list[tuple[str, str]] = []
    attempts: list[dict[str, Any]] = []
    try:
        for spec in chain:
            if not spec.api_key and spec.base_url != CODEX_WRITER_URL:
                errors.append((spec.model, "missing api_key"))
                attempts.append({
                    "model": spec.model,
                    "attempt": 0,
                    "ok": False,
                    "error_type": "MissingApiKey",
                    "error": "missing api_key",
                    "retryable": False,
                })
                continue
            max_attempts = 1 if spec.base_url == CODEX_WRITER_URL else max(1, spec.max_attempts)
            for attempt in range(1, max_attempts + 1):
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
                    validate(resp.parsed)
                except (
                    _HTTPX_HTTP_ERROR,
                    ValueError,
                    KeyError,
                    TypeError,
                    IndexError,
                    LLMError,
                ) as exc:
                    retryable = _is_retryable_error(exc)
                    summary = _err_summary(exc)
                    errors.append((spec.model, summary))
                    attempts.append({
                        "model": spec.model,
                        "attempt": attempt,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": summary,
                        "retryable": retryable,
                    })
                    if spec.base_url == CODEX_WRITER_URL and spec.role != "reviewer":
                        raise LLMError(f"Codex writer stopped; no paid fallback: {summary}") from exc
                    if retryable and attempt < max_attempts:
                        logger.warning(
                            "llm_client: %s attempt %s/%s failed (%s); retrying",
                            spec.model, attempt, max_attempts, type(exc).__name__,
                        )
                        await asyncio.sleep(min(2.0, 0.25 * attempt))
                        continue
                    logger.warning(
                        "llm_client: %s failed after %s/%s attempt(s) (%s); "
                        "trying next in chain",
                        spec.model, attempt, max_attempts, type(exc).__name__,
                    )
                    break
                attempts.append({
                    "model": spec.model,
                    "attempt": attempt,
                    "ok": True,
                    "error_type": None,
                    "error": None,
                    "retryable": None,
                    "transport": "codex_cli" if spec.base_url == CODEX_WRITER_URL else "http",
                    "billing": "codex_subscription" if spec.base_url == CODEX_WRITER_URL else "api",
                })
                resp = replace(resp, attempts=tuple(attempts))
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
    return (
        CallSpec(
            base_url=settings.minimax_base_url,
            api_key=settings.minimax_api_key,
            model=settings.minimax_model,
            timeout_sec=settings.minimax_timeout_sec,
            max_attempts=_configured_attempts(settings.minimax_base_url),
        ),
    )


def _model_family(model: str) -> str:
    """Return vendor for vendor/model IDs, otherwise the leading model token."""
    m = model.strip().lower()
    if not m:
        return ""
    return m.split("/", 1)[0] if "/" in m else m.split("-", 1)[0]


def review_call_spec(
    model: str, *, api_key: str, base_url: str, timeout_sec: float,
) -> CallSpec:
    """Terra reviews through subscription auth; other reviewers use HTTP."""
    codex = model == "gpt-5.6-terra"
    return CallSpec(
        base_url=CODEX_WRITER_URL if codex else base_url,
        api_key="" if codex else api_key, model=model, timeout_sec=timeout_sec,
        max_attempts=1 if codex else _configured_attempts(base_url),
        reasoning_effort="medium", role="reviewer",
    )


def build_judge_chain(settings: Settings) -> tuple[CallSpec, ...]:
    """Keep a separate reviewer; Sol/Terra is the approved same-family pair."""
    writer_families = {_model_family(settings.minimax_model)}
    candidates = (
        review_call_spec(
            model, base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key, timeout_sec=settings.minimax_timeout_sec,
        ) for model in (settings.judge_model, settings.fallback_model)
    )
    chain = tuple(
        c for c in candidates if c.model != settings.minimax_model and (
            _model_family(c.model) not in writer_families
            or (settings.minimax_model in {"gpt-5.6-sol", "gpt-6-sol"} and c.model == "gpt-5.6-terra")
        )
    )
    if not chain:
        raise ValueError(
            "build_judge_chain: no judge model outside writer families "
            f"{sorted(writer_families)!r}; set JUDGE_MODEL to a different "
            "family than every writer fallback."
        )
    return chain
