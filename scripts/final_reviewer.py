"""Day 10.17 Phase 6.2 Layer 2 — final-layer patch proposer.

The reviewer proposes typed patches with provenance. Every patch is
then validated and applied by `scripts/apply_patches.py` per per-type
gate rules:

  formatting   — auto-apply (typos, spacing, header tier)
  numeric      — must trace to v0.6 quant_claims; else flag-only
  citation     — must map to a real receipt_id; else flag-only
  claim        — flag-only (no silent claim edits)
  structure    — flag-only (no silent restructuring)

The prompt explicitly enumerates these rules so the model proposes
appropriately-typed patches; the applicator independently verifies each
patch against the trust spine.

Inputs:
  - full_paper.md
  - manifest.json
  - <paper>.audit.json
  - <paper>.consistency.json (Layer 1 output)

Output:
  - <paper>.review_patches.json — list of TypedPatch records
  - <paper>.review_summary.md   — human-readable review notes

Default primary: Terra Medium via Codex; GLM Flash is the HTTP fallback.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from agent.llm_client import LLMError, _call_codex, extract_json, review_call_spec  # noqa: E402
from agent.settings import load_settings  # noqa: E402  loads .env
from agent.paper_writer_prompts import PUBLICATION_REQUIREMENTS  # noqa: E402

__all__ = ["TypedPatch", "review_paper", "main"]


PATCH_TYPES = (
    "formatting",   # auto-apply
    "numeric",      # must trace to corpus
    "citation",     # must map to receipt
    "claim",        # flag-only
    "structure",    # flag-only
)
_PATCH_OUTPUT_CONTRACT = (
    "Output ONLY a JSON object, using this valid example shape:\n"
    '{"patches": [{"id": "P01", "patch_type": "claim", "severity": "P1", '
    '"location": "Abstract", "before": "Unsupported claim.", "after": "", '
    '"reason": "The cited source does not support this claim."}]}\n'
    "Every patch must contain all seven fields as JSON strings, never null or omitted.\n"
    f"patch_type must be exactly one of: {', '.join(PATCH_TYPES)}.\n"
    "severity must be exactly P1 (ship-blocker), P2 (quality), or P3 (polish).\n"
    "id identifies the patch; location is a section name; before is a nonempty exact paper substring (at most 160 chars).\n"
    'after is replacement text; use "" for deletion. reason is a one-sentence explanation.\n'
    'When there are no issues, return {"patches": []}.\n\n'
)


@dataclass(frozen=True, slots=True)
class TypedPatch:
    """One reviewer-proposed edit with provenance metadata."""
    id: str
    patch_type: str       # one of PATCH_TYPES
    severity: str         # P1 | P2 | P3
    location: str         # section name or line marker
    before: str           # exact paper substring to replace
    after: str            # replacement text
    reason: str           # one-sentence why
    auto_applicable: bool # only formatting; others go through gates
    requires_trace: bool  # numeric / citation must verify against corpus


def _build_reviewer_prompt(
    paper_md: str, manifest: dict, audit: dict,
    citation_registry: dict | None = None,
) -> tuple[str, str]:
    """Build typed-patch instructions and source-aware citation guidance."""
    system = (
        PUBLICATION_REQUIREMENTS + "\n"
        "You are a careful research-synthesis reviewer. Your job is to "
        "find issues in the paper and propose TYPED patches with "
        "provenance. You are NOT writing prose; you are emitting a "
        "structured patch list.\n\n"
        "PATCH TYPE CONTRACT (you MUST tag every patch with one):\n"
        "  formatting — typos, header tier, spacing, list markers. "
        "Auto-applies; safe to be specific.\n"
        "  numeric    — any change touching a number, percentage, "
        "p-value, CI, or sample size. Auto-applies ONLY when the "
        "patch is a STRICT DELETION/SIMPLIFICATION (Fix #39 smart "
        "gate: AFTER's words ⊆ BEFORE's words; AFTER ≤ BEFORE in "
        "word count; no new numerics/citations/identifiers).\n"
        "  citation   — any change to a paper citation. Body citations "
        "use human-readable Author-Year tokens (e.g. \"Walton 2019\", "
        "\"Smith et al. 2025\"). NEVER use receipt_id strings or "
        "internal handles like `PMC12978362_...` or "
        "`Author_YYYY_TRIAL_...` in body prose — those are internal "
        "identifiers, not citations. PMC IDs and DOIs belong only in "
        "the References section.\n"
        "Prepared manuscripts also use [bundle:N] source-bundle links, checked by deterministic "
        "citation gates. Preserve these links; their syntax alone is not a defect. "
        "Still flag incorrect source attribution or claims unsupported by their cited evidence.\n"
        "  claim      — any change to a substantive claim (effect "
        "direction, magnitude, mechanism). Auto-applies ONLY under "
        "the same strict-deletion smart-gate as numeric. Otherwise "
        "FLAGGED for human review.\n"
        "  structure  — moving sentences, adding/removing sections, "
        "restructuring an argument. FLAG ONLY (the gate cannot "
        "verify structural changes).\n\n"
        + _PATCH_OUTPUT_CONTRACT
        + "RULES:\n"
        "1. Do not invent numerics. If you flag a numeric as wrong, set "
        "patch_type=numeric and let the verifier check.\n"
        "2. Prefer minimal diffs. Don't restructure unless absolutely necessary.\n"
        "3. STRONGLY PREFER DELETION-STYLE PATCHES for claim/numeric "
        "issues. The smart-gate auto-applies a claim/numeric patch "
        "ONLY when AFTER is shorter-or-equal AND AFTER's words are "
        "a subset of BEFORE's. If you propose adding new clarifying "
        "wording (e.g. 'change in 0.13 m/s' instead of just deleting "
        "the wrong word), the gate will REFUSE to apply it. Prefer: "
        "  GOOD: BEFORE='walk speed (0.13 m/s improvement)' → "
        "        AFTER='walk speed (0.13 m/s)'   (auto-applies)\n"
        "  GOOD: BEFORE=', consistent with X (Anisimov 2008).' → "
        "        AFTER=' .'   (auto-applies — pure deletion)\n"
        "  BAD:  BEFORE='walk speed of 0.13 m/s' → "
        "        AFTER='change in walk speed of 0.13 m/s'   (FLAGGED — adds 'change in')\n"
        "4. If unsure, lean toward DELETION (auto-applies as long "
        "as the gate accepts it). Adding clarifying words goes to "
        "human review.\n"
        "5. Look for: contradictions between sections, awkward phrasing, "
        "missing hedges on overclaims, broken citations, factual errors, "
        "stale boilerplate, dead links/references.\n"
        "6. Output AT MOST 25 patches. Triage to highest-severity first.\n"
    )
    n_receipts = len(manifest.get("receipts", []))
    audit_p1 = audit.get("p1_pass", False)
    audit_score = audit.get("score_out_of_10", 0)
    # Fix #11: derive (body_citation, outcome, effect, tier) per receipt.
    # When citation_registry present, body_citation is the clean
    # Author-Year token (Walton 2019, Shadyab 2025). When absent (legacy
    # callers), fall back to receipt_id but warn the reviewer in the heading.
    receipts = manifest.get("receipts", [])
    if citation_registry:
        receipt_lines = []
        for r in receipts:
            rid = r.get("receipt_id", "?")
            entry = citation_registry.get(rid)
            body_cite = entry.body_citation if entry else rid
            receipt_lines.append(
                f"- {body_cite}: outcome={r.get('outcome_class', '?')} "
                f"effect={r.get('effect_direction', '?')} "
                f"tier={r.get('evidence_tier', '?')}\n  source_excerpt={r.get('thesis_text', '')}"
            )
        receipt_header = "## Allowed body citations — primary evidence (receipts)"
    else:
        receipt_lines = [
            f"- {r.get('receipt_id', '?')}: outcome={r.get('outcome_class', '?')} "
            f"effect={r.get('effect_direction', '?')} tier={r.get('evidence_tier', '?')}"
            f"\n  source_excerpt={r.get('thesis_text', '')}"
            for r in receipts
        ]
        receipt_header = "## Receipt list (use ONLY these for citations)"

    # Reviewer wave 10 (2026-05-05) — background-literature awareness fix:
    # The pipeline allows TWO citation pools in body prose:
    #   1. Receipts (above) — primary corpus evidence
    #   2. Background-literature registry — pre-vetted clinical
    #      thresholds (Studenski 2011, Cesari 2009, Cruz-Jentoft 2019,
    #      Bohannon 1997, Anisimov 2008, Owen 2000, etc.) admissible
    #      ONLY when the citation_token appears in the same sentence
    #      as the threshold value.
    # Pre-fix reviewer only saw pool #1 and flagged every bg-lit citation
    # as 'unauthorized', generating dozens of false-positive P1 patches
    # (rapamycin publication run had 19 unresolved). Now the reviewer sees
    # both pools and only flags citations not in EITHER.
    bglit_lines: list[str] = []
    seen_background_entries: set[tuple[str, str]] = set()
    try:
        from pathlib import Path
        import json as _json
        # Pool 1: global docs/background_literature.json (canon
        # citations shared across all topics: gait-speed thresholds,
        # BMI cutoffs, ADA targets, Cochrane standards).
        bg_path = (
            Path(__file__).resolve().parent.parent
            / "docs" / "background_literature.json"
        )
        if bg_path.exists():
            bg_data = _json.loads(bg_path.read_text())
            for entry in bg_data.values():
                if not isinstance(entry, dict):
                    continue
                token = (entry.get("citation_token") or "").strip()
                numeric = (entry.get("numeric") or "").strip()
                if not token:
                    continue
                entry_key = (token, numeric)
                if entry_key in seen_background_entries:
                    continue
                seen_background_entries.add(entry_key)
                bglit_lines.append(
                    f"- {token}: {numeric} ({entry.get('context', '')[:60]})"
                )
        # Pool 2 (Slice 7 step 3 fix): topic-pack [[background_literature]]
        # entries (rapamycin pack has Harrison 2009 / Lamming 2012 /
        # Mannick 2014 / Kahan 2000 / Kennedy 2014 / López-Otín 2013).
        # Without this, the reviewer flagged every legitimate canon citation
        # as 'unauthorized' on calibrated rapamycin runs.
        topic = (manifest.get("topic")
                 if isinstance(manifest, dict) else None)
        if topic:
            tp_path = (
                Path(__file__).resolve().parent.parent
                / "topic_packs" / f"{topic}.toml"
            )
            if tp_path.exists():
                import sys as _sys
                _sys.path.insert(
                    0, str(Path(__file__).resolve().parent.parent),
                )
                from agent.topic_pack import (  # noqa: E402
                    load_topic_pack as _ltp,
                )
                pack = _ltp(tp_path)
                for entry in pack.background_literature:
                    token = (entry.citation_token or "").strip()
                    numeric = (entry.numeric or "").strip()
                    if not token:
                        continue
                    entry_key = (token, numeric)
                    if entry_key in seen_background_entries:
                        continue
                    seen_background_entries.add(entry_key)
                    bglit_lines.append(
                        f"- {token}: {numeric} ({entry.context[:60]})"
                    )
    except (OSError, ValueError, ImportError):
        bglit_lines = bglit_lines or []
    bglit_header = (
        "## Allowed body citations — background literature\n\n"
        "These canonical citations are ALSO permitted in body prose, "
        "alongside the receipt list above. They cite pre-vetted "
        "clinical thresholds (gait-speed cutoffs, BMI thresholds, "
        "etc.) and must NOT be flagged as 'unauthorized citations'."
    )

    bglit_section = (
        f"\n\n{bglit_header}\n" + "\n".join(bglit_lines)
        if bglit_lines else ""
    )
    user = (
        f"# Paper to review ({len(paper_md.split())} words)\n\n"
        f"## Pipeline metadata\n"
        f"- Extractor version: {manifest.get('extractor_version', 'unknown')}\n"
        f"- Writer path: {manifest.get('writer_path', 'unknown')}\n"
        f"- Receipts: {n_receipts}\n"
        f"- Local audit: score={audit_score}/10, "
        f"P1={'PASS' if audit_p1 else 'FAIL'}\n\n"
        f"{receipt_header}\n"
        + "\n".join(receipt_lines)
        + bglit_section
        + "\n\n## Paper full text\n\n```markdown\n"
        + paper_md
        + "\n```\n\nNow produce the JSON patch list."
    )
    return system, user


# Per-1M-token pricing (input, output) in USD. Unpriced models are rejected
# before any provider call so cost reporting cannot silently become zero.
_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-5.6-terra": (0.0, 0.0),  # Codex allowance, not API billing.
    "z-ai/glm-5.3-flash": (0.075, 0.25),
    "x-ai/grok-4.3": (3.00, 15.00),
    "google/gemini-3.1-flash-lite:exacto": (0.25, 1.50),
    # JUDGE_MODEL default (agent/settings.py). Absent here, _estimate_cost raised
    # "no pricing configured for reviewer model 'google/gemma-4-31b-it'", the local
    # gate exited 7 (local_gate_execution_failed), and every synthesis died after
    # rendering a full paper. Rates match agent/llm_client.py:53 (per-1k there,
    # per-Mtok here).
    "google/gemma-4-31b-it": (0.10, 0.34),
    "mistralai/mistral-small-2603": (0.15, 0.60),
}

_PRIMARY_ATTEMPTS = 3
_FALLBACK_ATTEMPTS = 1
_MAX_OUTPUT_TOKENS = 12_000
_DEFAULT_REVIEWER_MODEL = "gpt-5.6-terra"
_DEFAULT_FALLBACK_MODEL = "z-ai/glm-5.3-flash"
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MAX_COST_USD = 1.0
_RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


async def _call_one(
    system: str, user: str, model: str, api_key: str,
    base_url: str, client: Any,
) -> tuple[dict[str, Any], int, int]:
    """Single chat call. Returns (parsed_json, in_tokens, out_tokens)."""
    if model == "gpt-5.6-terra":
        response = await _call_codex(
            review_call_spec(model, api_key=api_key, base_url=base_url,
                             timeout_sec=_review_call_timeout_sec()),
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            _MAX_OUTPUT_TOKENS,
        )
        return dict(response.parsed), response.input_tokens, response.output_tokens
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set for review fallback")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        # Fix #50: 0.1 → 0.5. Reviewer needs variance to catch
        # nuanced issues. Trust-spine gates
        # (smart-gate Fix #39, post-apply audit guard, Fix #46
        # auto-strip) catch unsafe patches downstream — the reviewer
        # should think freely.
        "temperature": 0.5,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": _MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
    }
    if model.startswith("google/gemini-3.1"):
        payload["reasoning"] = {"effort": "high", "exclude": True}
    if model == "z-ai/glm-5.3-flash":
        payload["reasoning"] = {"effort": "low", "exclude": True}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if os.environ.get("OPENROUTER_HTTP_REFERER"):
        headers["HTTP-Referer"] = os.environ["OPENROUTER_HTTP_REFERER"]
    headers["X-Title"] = os.environ.get("OPENROUTER_X_TITLE", "Research Agent Bot")
    r = await client.post(url, json=payload, headers=headers, timeout=300.0)
    r.raise_for_status()
    body = r.json()
    # Fix #48: defensive against `{"content": null}` — `.get(k, default)`
    # returns None when the key is PRESENT but its value is None,
    # which then crashed `text.strip()`. Empty string fallback lets
    # the JSON parser report "Expecting value" cleanly so the
    # fallback chain in _call_with_fallback kicks in.
    text = body["choices"][0]["message"].get("content") or "{}"
    parsed = extract_json(text)
    usage = body.get("usage") or {}
    in_tok = int(usage.get("prompt_tokens", 0))
    out_tok = int(usage.get("completion_tokens", 0))
    return parsed, in_tok, out_tok


def _estimate_cost(model: str, in_tok: int, out_tok: int) -> float:
    try:
        in_per, out_per = _PRICING_PER_MTOK[model]
    except KeyError as exc:
        raise ValueError(f"no pricing configured for reviewer model {model!r}") from exc
    return (in_tok / 1_000_000.0) * in_per + (out_tok / 1_000_000.0) * out_per


def _positive_int_setting(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _attempt_count(model: str, primary_model: str) -> int:
    if model == "gpt-5.6-terra":
        return 1
    if model == primary_model:
        return _positive_int_setting("FINAL_LAYER_PRIMARY_ATTEMPTS", _PRIMARY_ATTEMPTS)
    return _positive_int_setting("FINAL_LAYER_FALLBACK_ATTEMPTS", _FALLBACK_ATTEMPTS)


def _configured_value(explicit: str | None, env_name: str, default: str) -> str:
    return (explicit or os.environ.get(env_name, "").strip() or default).strip()


def _review_cost_cap(explicit: float | None) -> float | None:
    raw = str(explicit) if explicit is not None else os.environ.get(
        "FINAL_LAYER_MAX_COST_USD", "",
    ).strip()
    if not raw:
        return _DEFAULT_MAX_COST_USD
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("FINAL_LAYER_MAX_COST_USD must be a non-negative number") from exc
    if value < 0:
        raise RuntimeError("FINAL_LAYER_MAX_COST_USD must be a non-negative number")
    return value


def _request_cost_ceiling(model: str, system: str, user: str) -> float:
    # UTF-8 bytes are a conservative tokenizer-independent input-token ceiling.
    return _estimate_cost(
        model, len((system + user).encode("utf-8")), _MAX_OUTPUT_TOKENS,
    )


def _enforce_cost_cap(
    system: str, user: str, primary_model: str, fallback_model: str,
    escalation_model: str | None, max_cost_usd: float | None,
) -> None:
    cap = _review_cost_cap(max_cost_usd)
    models = (
        [(primary_model, _attempt_count(primary_model, primary_model))]
        + [(fallback_model, _attempt_count(fallback_model, primary_model))]
        + ([(escalation_model, 1)] if escalation_model else [])
    )
    ceiling = sum(
        _request_cost_ceiling(model, system, user) * attempts
        for model, attempts in models
    )
    if cap is not None and ceiling > cap:
        raise RuntimeError(
            f"review cost ceiling ${ceiling:.4f} exceeds "
            f"FINAL_LAYER_MAX_COST_USD=${cap:.4f}"
        )


def _err_summary(exc: BaseException) -> str:
    text = str(exc).strip()
    if len(text) > 220:
        text = text[:217] + "..."
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _is_retryable_error(exc: BaseException) -> bool:
    try:
        import httpx
    except ModuleNotFoundError:
        httpx = None  # type: ignore[assignment]
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
    return isinstance(
        exc, (TimeoutError, ValueError, KeyError, json.JSONDecodeError),
    )


def _review_call_timeout_sec() -> float:
    raw = os.environ.get("FINAL_LAYER_REVIEW_TIMEOUT_SEC", "120")
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError("FINAL_LAYER_REVIEW_TIMEOUT_SEC must be positive") from exc
    if value <= 0:
        raise RuntimeError("FINAL_LAYER_REVIEW_TIMEOUT_SEC must be positive")
    return value


async def _call_one_bounded(
    system: str, user: str, model: str, api_key: str,
    base_url: str, client: Any,
) -> tuple[dict[str, Any], int, int]:
    timeout = _review_call_timeout_sec()
    raw, in_tok, out_tok = await asyncio.wait_for(
        _call_one(system, user, model, api_key, base_url, client),
        timeout=timeout,
    )
    patches = raw.get("patches")
    patches = [patches] if isinstance(patches, dict) else patches
    if not isinstance(patches, list):
        raise ValueError("review response requires an explicit patches list")
    for patch in patches:
        if not isinstance(patch, dict):
            raise ValueError("review patch must be an object")
        if patch.get("patch_type") == "unfixable":
            continue
        invalid = [field for field, valid in {
            "patch_type": patch.get("patch_type") in PATCH_TYPES,
            "severity": patch.get("severity") in ("P1", "P2", "P3"),
            "before": isinstance(patch.get("before"), str) and bool(patch["before"].strip()),
            "after": isinstance(patch.get("after"), str),
            "reason": isinstance(patch.get("reason"), str),
        }.items() if not valid]
        if invalid:
            raise ValueError("review patch has missing or invalid fields: " + ", ".join(invalid))
    return raw, in_tok, out_tok


async def _call_with_fallback(
    system: str, user: str, primary_model: str,
    fallback_model: str, api_key: str, base_url: str, client: Any,
) -> tuple[dict[str, Any], str, float]:
    """Try primary first; on any HTTP/parse failure, fall back. Returns
    (parsed_json, model_used, cost_usd_estimate). The fallback only
    fires on primary-model outage or invalid JSON."""
    try:
        import httpx
        transport_errors: tuple[type[BaseException], ...] = (httpx.HTTPError,)
    except ModuleNotFoundError:
        transport_errors = ()
    retry_errors = transport_errors + (
        TimeoutError, ValueError, KeyError, TypeError, LLMError, json.JSONDecodeError,
    )
    attempts: list[dict[str, Any]] = []
    for model in (primary_model, fallback_model):
        _estimate_cost(model, 0, 0)
    for model in (primary_model, fallback_model):
        max_attempts = _attempt_count(model, primary_model)
        for attempt in range(1, max_attempts + 1):
            try:
                parsed, in_tok, out_tok = await _call_one_bounded(
                    system, user, model, api_key, base_url, client,
                )
                cost = _estimate_cost(model, in_tok, out_tok)
                attempts.append({
                    "model": model,
                    "attempt": attempt,
                    "ok": True,
                    "error_type": None,
                    "error": None,
                })
                parsed["_review_attempts"] = attempts
                parsed["_review_usage"] = {
                    "input_tokens": in_tok, "output_tokens": out_tok,
                    "billing": "codex_subscription" if model == "gpt-5.6-terra" else "api",
                }
                return parsed, model, cost
            except retry_errors as exc:
                retryable = _is_retryable_error(exc)
                attempts.append({
                    "model": model,
                    "attempt": attempt,
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": _err_summary(exc),
                    "retryable": retryable,
                })
                if retryable and attempt < max_attempts:
                    print(
                        f"final_layer_reviewer: {model} attempt "
                        f"{attempt}/{max_attempts} failed "
                        f"({type(exc).__name__}); retrying same model",
                        file=sys.stderr,
                    )
                    await asyncio.sleep(min(2.0, 0.25 * attempt))
                    continue
                next_label = (
                    "trying fallback"
                    if model == primary_model and fallback_model else
                    "no fallback remaining"
                )
                print(
                    f"final_layer_reviewer: {model} failed after "
                    f"{attempt}/{max_attempts} attempt(s) "
                    f"({type(exc).__name__}); {next_label}",
                    file=sys.stderr,
                )
                break
    raise RuntimeError(
        f"both {primary_model} and {fallback_model} failed for review call; "
        f"attempts={attempts}"
    )


def _normalize_patch(p_raw: dict, idx: int) -> TypedPatch | None:
    """Coerce a raw reviewer-emitted dict into a TypedPatch. Returns None
    if the dict can't be salvaged (missing required fields)."""
    pt = (p_raw.get("patch_type") or "").strip().lower()
    if pt not in PATCH_TYPES:
        return None
    severity = (p_raw.get("severity") or "P3").strip()
    if severity not in ("P1", "P2", "P3"):
        severity = "P3"
    before = p_raw.get("before") or ""
    after = p_raw.get("after") or ""
    if not before:
        return None
    auto = pt == "formatting"
    requires_trace = pt in ("numeric", "citation")
    return TypedPatch(
        id=p_raw.get("id") or f"P{idx:02d}",
        patch_type=pt,
        severity=severity,
        location=(p_raw.get("location") or "").strip(),
        before=before,
        after=after,
        reason=(p_raw.get("reason") or "").strip()[:400],
        auto_applicable=auto,
        requires_trace=requires_trace,
    )


def _patch_dicts(raw: dict) -> list[dict]:
    patches = raw.get("patches", [])
    if isinstance(patches, list):
        return [p for p in patches if isinstance(p, dict)]
    if isinstance(patches, dict):
        return [patches]
    raw["patches_parse_warning"] = type(patches).__name__
    return []


def _typed_patches(raw: dict) -> list[TypedPatch]:
    out: list[TypedPatch] = []
    for idx, patch in enumerate(_patch_dicts(raw), start=1):
        if str(patch.get("patch_type") or "").lower() == "unfixable":
            continue
        normalised = _normalize_patch(patch, idx)
        if normalised is not None:
            out.append(normalised)
    return out


def _build_repair_prompt(
    flagged: list[tuple[Any, str]],
    paper_md: str,
) -> tuple[str, str]:
    """Fix #49: build a focused repair-prompt for the reviewer. Each entry in
    `flagged` is (rejected_patch, rejection_reason). The reviewer is asked
    to propose a SHORTER alternative that passes the smart-gate, OR
    explicitly state 'no safe fix possible' so the pipeline can
    auto-strip the offending region."""
    system = (
        PUBLICATION_REQUIREMENTS + "\n"
        "You are repairing patches you previously proposed that the "
        "deterministic smart-gate REJECTED. The gate auto-applies "
        "claim/numeric patches ONLY when AFTER:\n"
        "  - has no new numerics, citations, or capitalized "
        "identifiers\n"
        "  - has word count ≤ BEFORE\n"
        "  - words are a strict subset of BEFORE\n"
        "  - does not regress Q2 trace or Stage-2 audit\n\n"
        "For each rejected patch below, propose ONE of:\n"
        "  (a) A shorter/safer alternative that passes the gate "
        "(prefer pure deletions — drop wrong words, keep clean ones)\n"
        "  (b) An empty 'after' (delete the whole BEFORE)\n"
        "  (c) JSON with `patch_type='unfixable'` if you cannot "
        "propose a safe edit\n\n"
        + _PATCH_OUTPUT_CONTRACT
        + "Use the SAME `id` field as the rejected patch. New "
        "patch_type uses the enum above; ONLY for this repair response, "
        "'unfixable' is also permitted and means no edit will be applied.\n"
        "Output AT MOST one patch per rejected input.\n"
    )
    rejected_block = []
    for p, reason in flagged:
        # Fix #51: accept both TypedPatch (`.id`) AND
        # apply_patches.PatchResult (`.patch_id`). The repair loop
        # passes PatchResults; pre-Fix-#51 this path crashed with
        # `'PatchResult' object has no attribute 'id'`.
        pid = getattr(p, "id", None) or getattr(p, "patch_id", "P-?")
        rejected_block.append(
            f"REJECTED PATCH {pid}\n"
            f"  patch_type: {p.patch_type}\n"
            f"  severity: {p.severity}\n"
            f"  before: {p.before!r}\n"
            f"  after:  {p.after!r}\n"
            f"  rejection_reason: {reason}\n"
        )
    user = (
        "Repair the following patches. The full paper is below for "
        "context.\n\n"
        + "\n".join(rejected_block)
        + "\n\n--- FULL PAPER ---\n\n" + paper_md
    )
    return system, user


async def repair_flagged_patches(
    flagged: list[tuple[Any, str]],
    paper_md: str,
    *,
    model: str | None = None,
    fallback_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    client: Any | None = None,
    max_cost_usd: float | None = None,
) -> list[TypedPatch]:
    """Fix #49: agent-to-agent repair pass. Re-prompts the reviewer with the
    rejection reasons; returns repaired TypedPatch list (or empty
    list if the reviewer returns 'unfixable' for every entry).

    Caller threads these through the SAME apply_patches gate; the reviewer's
    proposals here have no special privilege — they pass or fail the
    smart-gate the same way the original proposals did."""
    if not flagged:
        return []
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    model = _configured_value(model, "FINAL_LAYER_REVIEWER_MODEL", _DEFAULT_REVIEWER_MODEL)
    fallback_model = _configured_value(
        fallback_model, "FINAL_LAYER_FALLBACK_MODEL", _DEFAULT_FALLBACK_MODEL,
    )
    base_url = _configured_value(base_url, "OPENROUTER_BASE_URL", _DEFAULT_BASE_URL)
    system, user = _build_repair_prompt(flagged, paper_md)
    _enforce_cost_cap(
        system, user, model, fallback_model, None, max_cost_usd,
    )
    own_client = client is None
    if own_client:
        import httpx
        c: Any = httpx.AsyncClient(timeout=_review_call_timeout_sec())
    else:
        c = client
    try:
        raw, _model_used, _cost = await _call_with_fallback(
            system, user, model, fallback_model, api_key, base_url, c,
        )
    finally:
        if own_client:
            await c.aclose()
    return _typed_patches(raw)


async def review_paper(
    paper_md: str, manifest: dict, audit: dict,
    *, model: str | None = None,
    fallback_model: str | None = None,
    escalation_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    client: Any | None = None,
    citation_registry: dict | None = None,
    max_cost_usd: float | None = None,
) -> tuple[list[TypedPatch], dict, str, float]:
    """Run the final-layer review. Returns (patches, raw_response,
    model_used, successful-call cost estimate). Fallback fires only on technical
    failure, never on a valid negative review."""
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    model = _configured_value(model, "FINAL_LAYER_REVIEWER_MODEL", _DEFAULT_REVIEWER_MODEL)
    fallback_model = _configured_value(
        fallback_model, "FINAL_LAYER_FALLBACK_MODEL", _DEFAULT_FALLBACK_MODEL,
    )
    base_url = _configured_value(base_url, "OPENROUTER_BASE_URL", _DEFAULT_BASE_URL)
    escalation_model = (
        escalation_model
        or os.environ.get("FINAL_LAYER_LOW_PATCH_FALLBACK_MODEL", "").strip()
        or None
    )
    system, user = _build_reviewer_prompt(
        paper_md, manifest, audit, citation_registry=citation_registry,
    )
    _enforce_cost_cap(
        system, user, model, fallback_model, escalation_model, max_cost_usd,
    )
    own_client = client is None
    if own_client:
        import httpx
        c: Any = httpx.AsyncClient(timeout=_review_call_timeout_sec())
    else:
        c = client
    try:
        raw, model_used, cost = await _call_with_fallback(
            system, user, model, fallback_model, api_key, base_url, c,
        )
        patches = _typed_patches(raw)
        if escalation_model and _needs_low_patch_escalation(paper_md, patches):
            try:
                esc_raw, in_tok, out_tok = await _call_one_bounded(
                    system, user, escalation_model, api_key, base_url, c,
                )
                esc_patches = _typed_patches(esc_raw)
                raw = esc_raw
                patches = esc_patches
                model_used = f"{model_used}→{escalation_model}"
                cost += _estimate_cost(escalation_model, in_tok, out_tok)
            except Exception as exc:
                raw.setdefault("low_patch_escalation_error", type(exc).__name__)
    finally:
        if own_client:
            await c.aclose()
    return patches, raw, model_used, cost


def _needs_low_patch_escalation(
    paper_md: str,
    patches: list[TypedPatch],
    *,
    word_threshold: int = 10_000,
    patch_threshold: int = 2,
) -> bool:
    if len(patches) >= patch_threshold:
        return False
    return len(re.findall(r"\b\w+\b", paper_md)) > word_threshold


def _format_summary(
    patches: list[TypedPatch],
    cost_usd: float = 0.0,
    model_used: str = _DEFAULT_REVIEWER_MODEL,
) -> str:
    if not patches:
        return (
            f"# Final-Layer Review ({model_used})\n\n"
            f"**No patches proposed.** Paper looks clean to the LLM "
            f"reviewer.\n\nEstimated successful-call cost: ${cost_usd:.4f}\n"
        )
    by_type: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for p in patches:
        by_type[p.patch_type] = by_type.get(p.patch_type, 0) + 1
        by_sev[p.severity] = by_sev.get(p.severity, 0) + 1
    lines = [
        f"# Final-Layer Review ({model_used})",
        "",
        f"**{len(patches)} patches proposed.**",
        f"- By type: {by_type}",
        f"- By severity: {by_sev}",
        f"- Estimated successful-call cost: ${cost_usd:.4f}",
        "",
        "## Patches",
        "",
        "| # | Type | Sev | Location | Reason |",
        "|---|---|---|---|---|",
    ]
    for p in patches:
        lines.append(
            f"| {p.id} | {p.patch_type} | {p.severity} | "
            f"{p.location} | {p.reason[:80]} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 6.2 Layer 2 — final-layer patch proposer",
    )
    parser.add_argument("paper_md", help="full_paper.md")
    parser.add_argument(
        "--model",
        default=None,
        help="Primary reviewer model id (or FINAL_LAYER_REVIEWER_MODEL)",
    )
    parser.add_argument("--fallback-model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--max-cost-usd", type=float, default=None)
    args = parser.parse_args(argv)
    paper_path = Path(args.paper_md).resolve()
    if not paper_path.exists():
        print(f"not found: {paper_path}", file=sys.stderr)
        return 2
    load_settings()  # populates OPENROUTER_API_KEY etc. from .env
    paper = paper_path.read_text()
    manifest_path = paper_path.parent / "manifest.json"
    audit_path = paper_path.with_suffix(".audit.json")
    manifest = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    )
    audit = (
        json.loads(audit_path.read_text()) if audit_path.exists() else {}
    )

    patches, raw, model_used, cost_usd = asyncio.run(
        review_paper(
            paper, manifest, audit,
            model=args.model,
            fallback_model=args.fallback_model,
            base_url=args.base_url,
            max_cost_usd=args.max_cost_usd,
        ),
    )
    out_json = paper_path.with_suffix(".review_patches.json")
    out_md = paper_path.with_suffix(".review_summary.md")
    out_json.write_text(json.dumps({
        "model_requested": _configured_value(
            args.model, "FINAL_LAYER_REVIEWER_MODEL", _DEFAULT_REVIEWER_MODEL,
        ),
        "model_used": model_used,
        "cost_usd": cost_usd,
        "cost_usd_estimate": cost_usd,
        "cost_basis": "provider-reported usage for successful calls only",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_patches": len(patches),
        "patches": [asdict(p) for p in patches],
        "raw_response_keys": sorted((raw or {}).keys()),
    }, indent=2))
    out_md.write_text(_format_summary(patches, cost_usd, model_used))
    print(_format_summary(patches, cost_usd, model_used))
    print(f"\nPatches: {out_json}\nSummary: {out_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
