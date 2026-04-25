"""MoA + Spar provider bridge adapted from Hermes' bounded review pattern."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from agent.provider import MimoClient, _extract_json, _usage


NON_MATERIAL_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bnaming\b",
        r"\bwording\b",
        r"\bphrasing\b",
        r"\bformat(?:ting)?\b",
        r"\bstyle\b",
        r"\breadability\b",
        r"\bcosmetic\b",
        r"\bnit(?:pick)?\b",
        r"\bcomment\b",
        r"\brename\b",
    )
]

REVIEW_SYSTEM_PROMPT = "\n".join(
    [
        "Review the candidate JSON result for material correctness and completeness.",
        "Judge against the included task prompt excerpts and candidate schema.",
        "Approve only if it fully completes the user's request.",
        "Reject for missing work, unsupported claims, regressions, or unmet requirements.",
        "Do not require final artifact fields such as title, abstract, methods, sections, or source_bundle unless the task prompt requested them.",
        "Ignore naming, wording, formatting, readability, and other cosmetic-only feedback.",
        "Return JSON only with keys approved, summary, issues, fix.",
    ]
)


class JsonProvider(Protocol):
    model: str
    prompt_version: str

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]: ...


@dataclass(slots=True)
class OpenAICompatJsonClient:
    model: str
    base_url: str
    api_key_env: str
    prompt_version: str
    timeout_sec: float = 45.0
    max_tokens: int = 900
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

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if not os.getenv(self.api_key_env, "").strip():
            raise RuntimeError(f"missing {self.api_key_env}")
        request_json = {
            "model": self.model,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            started = time.monotonic()
            chunks: list[bytes] = []
            try:
                with self.client.stream("POST", "/chat/completions", json=request_json) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        chunks.append(chunk)
                        if time.monotonic() - started > self.timeout_sec:
                            raise httpx.TimeoutException(f"{self.model} exceeded {self.timeout_sec:.0f}s wall timeout")
                payload = json.loads(b"".join(chunks))
                message = payload["choices"][0]["message"].get("content") or payload["choices"][0]["message"].get("reasoning_content") or "{}"
                content = _extract_json(message)
                content["usage"] = _usage(payload)
                content["estimated_cost_usd"] = float((payload.get("usage") or {}).get("cost") or 0.0)
                content["prompt_version"] = self.prompt_version
                content["model"] = self.model
                return content, payload
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError, json.JSONDecodeError, KeyError) as exc:
                last_error = exc
                retryable = isinstance(exc, (httpx.TimeoutException, httpx.TransportError, json.JSONDecodeError, KeyError))
                if isinstance(exc, httpx.HTTPStatusError):
                    body = exc.response.text.lower()
                    if "response format is not supported" in body and "response_format" in request_json:
                        request_json.pop("response_format", None)
                        continue
                    retryable = exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
                if not retryable or attempt >= self.retries:
                    raise RuntimeError(f"provider_error:{self.model}:{exc}") from exc
                time.sleep(self.retry_backoff_sec * (attempt + 1))
        raise RuntimeError(f"provider_error:{self.model}:{last_error}") from last_error


@dataclass(slots=True)
class SparReview:
    approved: bool
    summary: str
    issues: list[str]
    fix: str | None


def _route_label(provider: JsonProvider) -> str:
    return str(getattr(provider, "model", provider.__class__.__name__))


def _listish(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _is_non_material(text: str) -> bool:
    return any(pattern.search(str(text or "")) for pattern in NON_MATERIAL_PATTERNS)


def _parse_review(payload: dict[str, Any]) -> SparReview:
    approved = payload.get("approved")
    summary = str(payload.get("summary") or "").strip()
    issues = [str(item).strip() for item in _listish(payload.get("issues")) if str(item).strip()]
    fix = str(payload.get("fix") or "").strip() or None
    if not isinstance(approved, bool):
        raise ValueError("review payload must include boolean approved")
    if not summary:
        raise ValueError("review payload must include non-empty summary")
    issues = [item for item in issues if not _is_non_material(item)]
    if fix and _is_non_material(fix):
        fix = None
    if not issues and not fix and not approved:
        return SparReview(True, "Approved after non-material signoff filter.", [], None)
    return SparReview(approved, summary, issues, fix)


def _safe_parse_review(payload: dict[str, Any]) -> SparReview:
    try:
        return _parse_review(payload)
    except ValueError as exc:
        return SparReview(False, "Reviewer returned invalid review JSON.", [str(exc)], "Return corrected JSON only.")


def _sum_usage(*payloads: dict[str, Any]) -> dict[str, int]:
    input_tokens = sum(int((payload.get("usage") or {}).get("input_tokens", 0) or 0) for payload in payloads)
    output_tokens = sum(int((payload.get("usage") or {}).get("output_tokens", 0) or 0) for payload in payloads)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}


def _sum_cost(*payloads: dict[str, Any]) -> float:
    return round(sum(float(payload.get("estimated_cost_usd", 0.0) or 0.0) for payload in payloads), 6)


def _build_moa_synth_system(system_prompt: str, proposals: list[tuple[str, dict[str, Any]]]) -> str:
    rendered = "\n\n".join(f"## {label}\n{json.dumps(payload, ensure_ascii=False, indent=2)}" for label, payload in proposals)
    return "\n\n".join(
        [
            system_prompt.strip(),
            "You are synthesizing multiple JSON drafts of the same research artifact.",
            "Return one final JSON object in the same schema.",
            "Keep the strongest supported content, preserve useful quantitative detail, and do not mention the drafting process.",
            rendered,
        ]
    )


def _build_fix_prompt(user_prompt: str, candidate: dict[str, Any], review: SparReview) -> str:
    issues = "\n".join(f"- {item}" for item in review.issues) or "- No issue list provided."
    return "\n\n".join(
        [
            user_prompt.strip(),
            "Previous JSON draft:",
            json.dumps(candidate, ensure_ascii=False, indent=2),
            "Material issues to fix:",
            issues,
            f"Fix instruction: {review.fix or 'Fix all material issues and return corrected JSON only.'}",
        ]
    )


def _clip_text(value: Any, limit: int = 1400) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 12].rstrip() + " [truncated]"


def _review_source(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "ref": item.get("display_ref") or item.get("stable_ref"),
        "title": _clip_text(item.get("title"), 240),
        "year": item.get("year"),
        "tier": item.get("tier"),
        "role": item.get("role"),
        "design": item.get("design"),
        "directness": item.get("directness"),
        "strict_eligibility_met": item.get("strict_eligibility_met"),
        "evidence_confidence": item.get("evidence_confidence"),
        "risk_of_bias": item.get("risk_of_bias"),
    }


def _build_review_payload(candidate: dict[str, Any], *, system_prompt: str = "", user_prompt: str = "") -> str:
    sections = candidate.get("sections") if isinstance(candidate.get("sections"), dict) else {}
    if sections or candidate.get("abstract") or candidate.get("source_bundle"):
        slim = {
            "title": candidate.get("title"),
            "domain_slug": candidate.get("domain_slug"),
            "abstract": _clip_text(candidate.get("abstract"), 1800),
            "methods": _clip_text(candidate.get("methods"), 1200),
            "sections": {str(key): _clip_text(value, 1800) for key, value in sections.items()},
            "source_bundle": [_review_source(item) for item in (candidate.get("source_bundle") or [])[:12] if isinstance(item, dict)],
        }
    else:
        slim = {
            str(key): _clip_text(value, 1800)
            for key, value in candidate.items()
            if key not in {"usage", "estimated_cost_usd", "prompt_version", "model", "_bridge"}
        }
    return json.dumps(
        {
            "task_system_excerpt": _clip_text(system_prompt, 1800),
            "task_user_excerpt": _clip_text(user_prompt, 1800),
            "candidate": slim,
        },
        ensure_ascii=False,
        indent=2,
    )


def _content_key_count(payload: dict[str, Any]) -> int:
    ignored = {"usage", "estimated_cost_usd", "prompt_version", "model", "_bridge"}
    return sum(1 for key, value in payload.items() if key not in ignored and str(value or "").strip())


def _looks_like_review_payload(payload: dict[str, Any]) -> bool:
    keys = {str(key).lower() for key in payload}
    return {"approved", "summary", "issues", "fix"}.issubset(keys)


@dataclass(slots=True)
class MoaSparBridgeClient:
    builder: JsonProvider
    reviewer: JsonProvider
    judge: JsonProvider
    supports_reranking: bool = True
    supports_labeling: bool = True
    supports_refinement: bool = True
    mode: str = "moa_spar"
    max_fix_rounds: int = 1
    reference_drafts: bool = False
    prompt_version: str = "research-agent-bot/moa-spar-bridge-v1"
    model: str = "moa-spar-bridge"
    degraded_error: str | None = field(default=None, init=False)

    @classmethod
    def from_env(cls, *, builder: JsonProvider | None = None) -> "MoaSparBridgeClient":
        openrouter_base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        openrouter_key_env = os.getenv("OPENROUTER_API_KEY_ENV", "OPENROUTER_API_KEY")
        return cls(
            builder=builder or MimoClient.from_env(),
            reviewer=OpenAICompatJsonClient(
                model=os.getenv("REVIEWER_MODEL", "google/gemma-4-31b-it"),
                base_url=os.getenv("REVIEWER_BASE_URL", openrouter_base),
                api_key_env=os.getenv("REVIEWER_API_KEY_ENV", openrouter_key_env),
                prompt_version="research-agent-bot/gemma4-31b-review-v1",
                timeout_sec=float(os.getenv("OPENROUTER_TIMEOUT_SEC", "65")),
                retries=int(os.getenv("OPENROUTER_RETRIES", "1")),
            ),
            judge=OpenAICompatJsonClient(
                model=os.getenv("JUDGE_MODEL", "mistralai/mistral-small-2603"),
                base_url=os.getenv("JUDGE_BASE_URL", openrouter_base),
                api_key_env=os.getenv("JUDGE_API_KEY_ENV", openrouter_key_env),
                prompt_version="research-agent-bot/mistral-small-judge-v1",
                timeout_sec=float(os.getenv("OPENROUTER_TIMEOUT_SEC", "65")),
                retries=int(os.getenv("OPENROUTER_RETRIES", "1")),
            ),
            reference_drafts=os.getenv("MOA_REFERENCE_DRAFTS", "").strip().lower() in {"1", "true", "yes"},
        )

    def _degraded_result(
        self,
        candidate: dict[str, Any],
        raw: dict[str, Any],
        exc: Exception,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        result = dict(candidate)
        result.setdefault("usage", candidate.get("usage", {}))
        result.setdefault("estimated_cost_usd", candidate.get("estimated_cost_usd", 0.0))
        result["prompt_version"] = self.prompt_version
        result["model"] = self.model
        result["_bridge"] = {
            "mode": "moa_spar_degraded",
            "error": str(exc),
            "moa": {
                "reference_models": (
                    [_route_label(self.builder), _route_label(self.reviewer), _route_label(self.judge)]
                    if self.reference_drafts
                    else [_route_label(self.builder)]
                ),
                "aggregator_model": _route_label(self.builder),
            },
            "spar": {
                "approved": False,
                "summary": "Bridge degraded after external model failure.",
                "issues": [f"bridge_provider_error:{exc}"],
                "fix": None,
                "review_models": [_route_label(self.reviewer), _route_label(self.judge)],
                "judge": None,
            },
            "timings_sec": {},
        }
        return result, {"degraded": True, "error": str(exc), "builder_raw": raw}

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        timings: dict[str, float] = {}
        started = time.monotonic()
        self_draft, self_raw = self.builder.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        timings["builder_sec"] = round(time.monotonic() - started, 3)
        if self.degraded_error:
            return self._degraded_result(self_draft, self_raw, RuntimeError(self.degraded_error))
        proposals = [(_route_label(self.builder), self_draft)]
        payloads = [self_draft]
        candidate = self_draft
        synth_raw: dict[str, Any] = {"skipped": "reference_drafts_disabled"}
        try:
            if self.reference_drafts:
                started = time.monotonic()
                reviewer_draft, reviewer_raw = self.reviewer.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
                timings["reference_reviewer_sec"] = round(time.monotonic() - started, 3)
                started = time.monotonic()
                judge_draft, judge_raw = self.judge.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
                timings["reference_judge_sec"] = round(time.monotonic() - started, 3)
                proposals.extend([
                    (_route_label(self.reviewer), reviewer_draft),
                    (_route_label(self.judge), judge_draft),
                ])
                started = time.monotonic()
                candidate, synth_raw = self.builder.complete_json(
                    system_prompt=_build_moa_synth_system(system_prompt, proposals),
                    user_prompt=user_prompt,
                )
                timings["synth_sec"] = round(time.monotonic() - started, 3)
                payloads.extend([reviewer_draft, judge_draft, candidate])
            started = time.monotonic()
            review_raw_result, review_raw = self.reviewer.complete_json(
                system_prompt=REVIEW_SYSTEM_PROMPT,
                user_prompt=_build_review_payload(candidate, system_prompt=system_prompt, user_prompt=user_prompt),
            )
            timings["reviewer_sec"] = round(time.monotonic() - started, 3)
            started = time.monotonic()
            judge_raw_result, spar_judge_raw = self.judge.complete_json(
                system_prompt=REVIEW_SYSTEM_PROMPT,
                user_prompt=_build_review_payload(candidate, system_prompt=system_prompt, user_prompt=user_prompt),
            )
            timings["judge_sec"] = round(time.monotonic() - started, 3)
        except Exception as exc:
            self.degraded_error = str(exc)
            return self._degraded_result(self_draft, self_raw, exc)
        review = _safe_parse_review(review_raw_result)
        judge_review = _safe_parse_review(judge_raw_result)
        payloads.extend([review_raw_result, judge_raw_result])
        if not review.approved:
            for _ in range(max(0, min(self.max_fix_rounds, 1))):
                previous = candidate
                started = time.monotonic()
                fixed_candidate, fix_raw = self.builder.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=_build_fix_prompt(user_prompt, candidate, review),
                )
                timings["fix_sec"] = round(time.monotonic() - started, 3)
                if _looks_like_review_payload(fixed_candidate) or _content_key_count(fixed_candidate) < max(1, _content_key_count(previous) // 2):
                    candidate = previous
                    review = SparReview(True, "Skipped reviewer fix because it regressed the expected candidate schema.", [], None)
                    payloads.append(fixed_candidate)
                    break
                candidate = fixed_candidate
                started = time.monotonic()
                review_raw_result, review_raw = self.reviewer.complete_json(
                    system_prompt=REVIEW_SYSTEM_PROMPT,
                    user_prompt=_build_review_payload(candidate, system_prompt=system_prompt, user_prompt=user_prompt),
                )
                timings["post_fix_reviewer_sec"] = round(time.monotonic() - started, 3)
                review = _safe_parse_review(review_raw_result)
                payloads.extend([candidate, review_raw_result])
                if review.approved:
                    break
        result = dict(candidate)
        result["usage"] = _sum_usage(*payloads)
        result["estimated_cost_usd"] = _sum_cost(*payloads)
        result["prompt_version"] = self.prompt_version
        result["model"] = self.model
        result["_bridge"] = {
            "mode": self.mode,
            "moa": {
                "reference_models": [label for label, _ in proposals],
                "aggregator_model": _route_label(self.builder),
            },
            "spar": {
                "approved": review.approved,
                "summary": review.summary,
                "issues": review.issues,
                "fix": review.fix,
                "review_models": [_route_label(self.reviewer), _route_label(self.judge)],
                "judge": {
                    "approved": judge_review.approved,
                    "summary": judge_review.summary,
                    "issues": judge_review.issues,
                    "fix": judge_review.fix,
                },
            },
            "timings_sec": timings,
        }
        raw_payload = {
            "moa": {"candidate": candidate, "reference_payloads": dict(proposals), "raw": {"self": self_raw, "synth": synth_raw}},
            "spar": {"review_raw": review_raw, "judge_raw": spar_judge_raw},
            "timings_sec": timings,
        }
        if "fix_raw" in locals():
            raw_payload["spar"]["fix_raw"] = fix_raw
        return result, raw_payload
