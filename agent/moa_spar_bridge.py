"""MoA + Spar provider bridge adapted from Hermes' bounded review pattern."""

from __future__ import annotations

import json
import os
import re
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
        "Approve only if it fully completes the user's request.",
        "Reject for missing work, unsupported claims, regressions, or unmet requirements.",
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
        content["model"] = self.model
        return content, payload


@dataclass(slots=True)
class SparReview:
    approved: bool
    summary: str
    issues: list[str]
    fix: str | None


def _route_label(provider: JsonProvider) -> str:
    return str(getattr(provider, "model", provider.__class__.__name__))


def _is_non_material(text: str) -> bool:
    return any(pattern.search(str(text or "")) for pattern in NON_MATERIAL_PATTERNS)


def _parse_review(payload: dict[str, Any]) -> SparReview:
    approved = payload.get("approved")
    summary = str(payload.get("summary") or "").strip()
    raw_issues = payload.get("issues", [])
    if isinstance(raw_issues, str):
        raw_issues = [raw_issues]
    issues = [str(item).strip() for item in raw_issues if str(item).strip()]
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
    prompt_version: str = "research-agent-bot/moa-spar-bridge-v1"
    model: str = "moa-spar-bridge"

    @classmethod
    def from_env(cls, *, builder: JsonProvider | None = None) -> "MoaSparBridgeClient":
        return cls(
            builder=builder or MimoClient.from_env(),
            reviewer=OpenAICompatJsonClient(
                model=os.getenv("MINIMAX_MODEL", "MiniMax-M2.7-highspeed"),
                base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
                api_key_env="MINIMAX_API_KEY",
                prompt_version="research-agent-bot/minimax-review-v1",
            ),
            judge=OpenAICompatJsonClient(
                model=os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner"),
                base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                api_key_env="DEEPSEEK_API_KEY",
                prompt_version="research-agent-bot/deepseek-judge-v1",
            ),
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
                "reference_models": [_route_label(self.builder), _route_label(self.reviewer), _route_label(self.judge)],
                "aggregator_model": _route_label(self.builder),
            },
            "spar": {
                "approved": False,
                "summary": "Bridge degraded after external model failure.",
                "issues": [f"bridge_provider_error:{exc}"],
                "fix": None,
                "judge": None,
            },
        }
        return result, {"degraded": True, "error": str(exc), "builder_raw": raw}

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
        self_draft, self_raw = self.builder.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        try:
            reviewer_draft, reviewer_raw = self.reviewer.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
            judge_draft, judge_raw = self.judge.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as exc:
            return self._degraded_result(self_draft, self_raw, exc)
        proposals = [
            (_route_label(self.builder), self_draft),
            (_route_label(self.reviewer), reviewer_draft),
            (_route_label(self.judge), judge_draft),
        ]
        candidate, synth_raw = self.builder.complete_json(
            system_prompt=_build_moa_synth_system(system_prompt, proposals),
            user_prompt=user_prompt,
        )
        review_raw_result, review_raw = self.reviewer.complete_json(
            system_prompt=REVIEW_SYSTEM_PROMPT,
            user_prompt=json.dumps({"user_prompt": user_prompt, "candidate": candidate}, ensure_ascii=False, indent=2),
        )
        review = _safe_parse_review(review_raw_result)
        judge_raw_result, spar_judge_raw = self.judge.complete_json(
            system_prompt=REVIEW_SYSTEM_PROMPT,
            user_prompt=json.dumps({"user_prompt": user_prompt, "candidate": candidate}, ensure_ascii=False, indent=2),
        )
        judge_review = _safe_parse_review(judge_raw_result)
        payloads = [self_draft, reviewer_draft, judge_draft, candidate, review_raw_result, judge_raw_result]
        if not review.approved:
            for _ in range(max(0, min(self.max_fix_rounds, 1))):
                candidate, fix_raw = self.builder.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=_build_fix_prompt(user_prompt, candidate, review),
                )
                review_raw_result, review_raw = self.reviewer.complete_json(
                    system_prompt=REVIEW_SYSTEM_PROMPT,
                    user_prompt=json.dumps({"user_prompt": user_prompt, "candidate": candidate}, ensure_ascii=False, indent=2),
                )
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
                "reference_models": [_route_label(self.builder), _route_label(self.reviewer), _route_label(self.judge)],
                "aggregator_model": _route_label(self.builder),
            },
            "spar": {
                "approved": review.approved,
                "summary": review.summary,
                "issues": review.issues,
                "fix": review.fix,
                "judge": {
                    "approved": judge_review.approved,
                    "summary": judge_review.summary,
                    "issues": judge_review.issues,
                    "fix": judge_review.fix,
                },
            },
        }
        raw_payload = {
            "moa": {"candidate": candidate, "reference_payloads": dict(proposals), "raw": {"self": self_raw, "reviewer": reviewer_raw, "judge": judge_raw, "synth": synth_raw}},
            "spar": {"review_raw": review_raw, "judge_raw": spar_judge_raw},
        }
        if "fix_raw" in locals():
            raw_payload["spar"]["fix_raw"] = fix_raw
        return result, raw_payload
