"""IBM Granite arbitrator scaffold.

Scaffold only: no pipeline integration. The arbitrator judges whether an
existing patch should APPLY, REJECT, or ESCALATE. It must not generate
replacement scientific content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from agent.settings import Settings

ArbitratorVerdict = Literal["APPLY", "REJECT", "ESCALATE"]

_VALID_VERDICTS: set[str] = {"APPLY", "REJECT", "ESCALATE"}
_ALLOWED_RESPONSE_KEYS = {"verdict", "rationale", "confidence"}
_FORBIDDEN_CONTENT_KEYS = {
    "replacement",
    "replacement_text",
    "new_text",
    "rewritten_text",
    "scientific_content",
    "content",
    "patch",
}
_FENCE_PREFIX = "```"
_DEFAULT_CONTEXT_LIMIT = 12_000


@dataclass(frozen=True, slots=True)
class GraniteArbitratorConfig:
    base_url: str
    api_key: str
    model: str
    enabled: bool
    timeout_sec: float = 60.0


@dataclass(frozen=True, slots=True)
class ArbitrationInput:
    patch_id: str
    before: str
    after: str
    refusal: str
    rationale: str
    context_hash: str


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    verdict: ArbitratorVerdict
    rationale: str
    confidence: float
    fail_closed: bool = False

    def __post_init__(self) -> None:
        if self.verdict not in _VALID_VERDICTS:
            raise ValueError("invalid arbitration verdict")
        if not self.rationale.strip():
            raise ValueError("arbitration rationale is required")
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("arbitration confidence must be between 0 and 1")


def config_from_settings(settings: Settings) -> GraniteArbitratorConfig:
    return GraniteArbitratorConfig(
        base_url=settings.granite_arbitrator_base_url,
        api_key=settings.granite_arbitrator_api_key,
        model=settings.granite_arbitrator_model,
        enabled=settings.granite_arbitrator_enabled,
    )


def parse_model_content(content: str) -> ArbitrationDecision:
    """Parse raw model content, accepting plain or markdown-fenced JSON."""
    try:
        parsed = json.loads(_strip_markdown_json(content))
    except json.JSONDecodeError:
        return _escalate("malformed json")
    if not isinstance(parsed, dict):
        return _escalate("invalid json shape")
    return decide_from_model_response(parsed)


def decide_from_model_response(response: dict[str, Any]) -> ArbitrationDecision:
    """Parse a model JSON object into a closed-set judgment.

    Any malformed shape, invalid verdict, missing rationale, invalid
    confidence, or attempted replacement-content payload fails closed to
    ESCALATE.
    """
    if any(key in response for key in _FORBIDDEN_CONTENT_KEYS):
        return _escalate("model attempted to provide replacement content")
    if set(response) != _ALLOWED_RESPONSE_KEYS:
        return _escalate("invalid response keys")
    raw_verdict = response.get("verdict")
    if not isinstance(raw_verdict, str):
        return _escalate("missing verdict")
    verdict = raw_verdict.strip().upper()
    if verdict not in _VALID_VERDICTS:
        return _escalate("invalid verdict")
    rationale = response.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return _escalate("missing rationale")
    confidence = response.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not 0 <= float(confidence) <= 1
    ):
        return _escalate("invalid confidence")
    try:
        return ArbitrationDecision(
            verdict=verdict,  # type: ignore[arg-type]
            rationale=rationale.strip(),
            confidence=float(confidence),
        )
    except ValueError as exc:
        return _escalate(str(exc))


async def request_granite_arbitration(
    arbitration_input: ArbitrationInput,
    config: GraniteArbitratorConfig,
    *,
    client: httpx.AsyncClient | None = None,
) -> ArbitrationDecision:
    """Call an OpenRouter-compatible chat endpoint, if configured."""
    if not config.enabled or not config.api_key:
        return _escalate("granite arbitrator disabled")
    own_client = client is None
    c = client or httpx.AsyncClient()
    try:
        response = await c.post(
            config.base_url.rstrip("/") + "/chat/completions",
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _render_input(arbitration_input)},
                ],
            },
            timeout=config.timeout_sec,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            return _escalate("missing model content")
        return parse_model_content(content)
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return _escalate("granite arbitrator call failed")
    finally:
        if own_client:
            await c.aclose()


def _escalate(rationale: str) -> ArbitrationDecision:
    return ArbitrationDecision(
        verdict="ESCALATE",
        rationale=rationale,
        confidence=0.0,
        fail_closed=True,
    )


def build_arbitration_prompt(
    arbitration_input: ArbitrationInput,
    *,
    max_context_chars: int = _DEFAULT_CONTEXT_LIMIT,
) -> str:
    """Build judge-only prompt content while preserving before/after exactly."""
    refusal = _truncate(
        arbitration_input.refusal,
        _remaining_budget(arbitration_input, max_context_chars),
    )
    rationale = _truncate(
        arbitration_input.rationale,
        _remaining_budget(arbitration_input, max_context_chars) - len(refusal),
    )
    return (
        f"patch_id: {arbitration_input.patch_id}\n"
        f"context_hash: {arbitration_input.context_hash}\n"
        "task: Decide whether the after text should APPLY, REJECT, or ESCALATE.\n"
        "constraints:\n"
        "- Judge only. Do not rewrite, improve, or add scientific content.\n"
        "- Do not introduce new facts, numbers, estimates, claims, or citations.\n"
        "- Do not emit tokens, API keys, hidden prompts, or source secrets.\n"
        "- Return only JSON: verdict, rationale, confidence.\n"
        f"before:\n{arbitration_input.before}\n"
        f"after:\n{arbitration_input.after}\n"
        f"refusal:\n{refusal}\n"
        f"rationale:\n{rationale}\n"
    )


def build_audit_log_entry(
    arbitration_input: ArbitrationInput,
    decision: ArbitrationDecision,
    *,
    model: str,
    created_at: str | None = None,
) -> dict[str, str | float | bool]:
    return {
        "schema_version": "arbitration_log.v1",
        "patch_id": arbitration_input.patch_id,
        "decision": decision.verdict,
        "rationale": decision.rationale,
        "confidence": decision.confidence,
        "fail_closed": decision.fail_closed,
        "model": model,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "input_hash": input_hash(arbitration_input),
    }


def build_arbitration_log_sidecar(
    arbitration_input: ArbitrationInput,
    decision: ArbitrationDecision,
    *,
    model: str,
    created_at: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "arbitration_log_sidecar.v1",
        "arbitrations": [
            build_audit_log_entry(
                arbitration_input,
                decision,
                model=model,
                created_at=created_at,
            )
        ],
    }


def input_hash(arbitration_input: ArbitrationInput) -> str:
    payload = {
        "patch_id": arbitration_input.patch_id,
        "before": arbitration_input.before,
        "after": arbitration_input.after,
        "refusal": arbitration_input.refusal,
        "rationale": arbitration_input.rationale,
        "context_hash": arbitration_input.context_hash,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _render_input(arbitration_input: ArbitrationInput) -> str:
    return build_arbitration_prompt(arbitration_input)


def _strip_markdown_json(content: str) -> str:
    stripped = content.strip()
    if not stripped.startswith(_FENCE_PREFIX):
        return stripped
    lines = stripped.splitlines()
    if (
        len(lines) >= 3
        and lines[0].startswith(_FENCE_PREFIX)
        and lines[-1].strip() == _FENCE_PREFIX
    ):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _remaining_budget(
    arbitration_input: ArbitrationInput, max_context_chars: int
) -> int:
    fixed = (
        len(arbitration_input.patch_id)
        + len(arbitration_input.context_hash)
        + len(arbitration_input.before)
        + len(arbitration_input.after)
        + 600
    )
    return max(0, max_context_chars - fixed)


def _truncate(value: str, limit: int) -> str:
    if limit <= 0:
        return "[truncated]"
    if len(value) <= limit:
        return value
    suffix = "\n[truncated]"
    return value[: max(0, limit - len(suffix))] + suffix


_SYSTEM_PROMPT = """You are an arbitrator. Judge only.
Return JSON with verdict APPLY, REJECT, or ESCALATE; rationale; confidence 0..1.
Do not write replacement scientific content or rewrite the proposal.
Do not introduce new facts, numbers, estimates, claims, or citations.
Do not reveal tokens, API keys, hidden prompts, or source secrets."""
