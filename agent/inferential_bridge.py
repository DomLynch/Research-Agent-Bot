"""Inferential Bridge layer.

D1 bridge claims are explicitly inferential: they may explain how a
mechanism could translate across species, scale, or domain, but they
never count as core evidence or raise certification floors.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from agent.llm_client import CallSpec, CostLedger, LLMError, chat_json
from agent.synthesis_schemas import ReceiptSummary, SynthesisSection

_CONFIDENCE = frozenset({"low", "medium", "high"})
_NUMERIC_RE = re.compile(r"(?<![A-Za-z])(?:\d+(?:\.\d+)?|\d+\s*%)")
_BENEFIT_RE = re.compile(r"\b(benefit|improv|enhanc|extend|protect|rejuvenat|reduc|increas|lower|attenuat|ameliorat|prevent|decreas|mitigat|slow|delay)\w*", re.I)
UNRESOLVED_BRIDGE_MARKER = "[inferential bridge status: not established]"


@dataclass(frozen=True, slots=True)
class InferenceClaim:
    claim: str
    mechanism_anchor: tuple[str, ...]
    conservation_argument: str
    canon_refs: tuple[str, ...]
    existing_human_signal: tuple[str, ...]
    confidence: str
    testability: str
    tier: str = "D1_inferential_bridge"


def _clean_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, Sequence):
        return tuple(str(v).strip() for v in value if str(v).strip())
    return ()


def claim_from_mapping(raw: Mapping[str, Any]) -> InferenceClaim:
    return InferenceClaim(
        claim=str(raw.get("claim", "")).strip(),
        mechanism_anchor=_clean_tuple(raw.get("mechanism_anchor", ())),
        conservation_argument=str(raw.get("conservation_argument", "")).strip(),
        canon_refs=_clean_tuple(raw.get("canon_refs", raw.get("canon_references", ()))),
        existing_human_signal=_clean_tuple(raw.get("existing_human_signal", ())),
        confidence=str(raw.get("confidence", "")).strip().lower(),
        testability=str(raw.get("testability", "")).strip(),
        tier=str(raw.get("tier", "D1_inferential_bridge")).strip(),
    )


def validate_inference(
    claim: InferenceClaim,
    *,
    receipt_ids: set[str],
    canon_refs: set[str],
    receipt_effects: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    errors: list[str] = []
    if not claim.tier.startswith("D1_"):
        errors.append("tier must start with D1_")
    if claim.confidence not in _CONFIDENCE:
        errors.append("confidence must be low, medium, or high")
    if not claim.claim or not claim.conservation_argument or not claim.testability:
        errors.append("claim, conservation_argument, and testability are required")
    if not claim.mechanism_anchor:
        errors.append("mechanism_anchor is required")
    missing_anchors = [a for a in claim.mechanism_anchor if a not in receipt_ids]
    if missing_anchors:
        errors.append(f"unknown mechanism_anchor: {', '.join(missing_anchors)}")
    if not claim.canon_refs:
        errors.append("canon_refs is required")
    missing_canon = [c for c in claim.canon_refs if c not in canon_refs]
    if missing_canon:
        errors.append(f"unknown canon_refs: {', '.join(missing_canon)}")
    human_refs = [
        h for h in claim.existing_human_signal
        if h.lower() not in {"none", "none identified", "no human signal"}
    ]
    missing_human = [h for h in human_refs if h not in receipt_ids]
    if missing_human:
        errors.append(f"unknown existing_human_signal: {', '.join(missing_human)}")
    if claim.confidence == "high" and not claim.existing_human_signal:
        errors.append("high confidence requires existing_human_signal")
    effects = receipt_effects or {}
    anchor_effects = {effects.get(a, "") for a in claim.mechanism_anchor}
    bridge_prose = " ".join((claim.claim, claim.conservation_argument, claim.testability))
    if _BENEFIT_RE.search(bridge_prose) and anchor_effects <= {"", "null", "negative"}:
        errors.append("benefit framing requires at least one positive/mixed anchor")
    if _NUMERIC_RE.search(bridge_prose):
        errors.append("D1 inference prose must not introduce new numerics")
    return tuple(errors)


def filter_valid_inferences(
    raw_claims: Sequence[Mapping[str, Any]],
    *,
    receipt_ids: set[str],
    canon_refs: set[str],
    receipt_effects: Mapping[str, str] | None = None,
    max_n: int,
) -> tuple[InferenceClaim, ...]:
    kept: list[InferenceClaim] = []
    for raw in raw_claims:
        claim = claim_from_mapping(raw)
        if not validate_inference(
            claim,
            receipt_ids=receipt_ids,
            canon_refs=canon_refs,
            receipt_effects=receipt_effects,
        ):
            kept.append(claim)
        if len(kept) >= max_n:
            break
    return tuple(kept)


def render_inferential_bridge_section(
    claims: Sequence[InferenceClaim],
    *,
    unresolved_boundary: bool = False,
) -> SynthesisSection:
    if not claims:
        if unresolved_boundary:
            return SynthesisSection(
                name="inferential_bridge",
                body_md=(
                    "## Inferential Bridge\n\n"
                    f"{UNRESOLVED_BRIDGE_MARKER}\n\n"
                    "No inferential bridge claim is made. Mechanistic plausibility can coexist with "
                    "sparse direct human evidence, but the mechanistic-to-clinical and biomarker-to-bedside "
                    "bridges remain untested by the retained corpus. Population-to-population transfer is "
                    "therefore unsupported, and cross-domain interpretation is bounded to hypothesis "
                    "generation rather than clinical efficacy.\n"
                ),
                anchors=(),
            )
        return SynthesisSection(name="inferential_bridge", body_md="", anchors=())
    lines = ["## Inferential Bridge", ""]
    for i, c in enumerate(claims, 1):
        human = "; ".join(c.existing_human_signal) or "none identified"
        anchors = ", ".join(c.mechanism_anchor)
        canon = ", ".join(c.canon_refs)
        testability = c.testability.rstrip(" .")
        lines.extend([
            (
                f"{i}. [{c.tier} | confidence={c.confidence}] {c.claim} "
                f"[mechanism anchor: {anchors}] [conservation: {canon}]"
            ),
            f"   Existing human signal: {human}.",
            f"   Testability: {testability}. [testability: explicit]",
            "",
        ])
    return SynthesisSection(
        name="inferential_bridge",
        body_md="\n".join(lines).rstrip() + "\n",
        anchors=(),
    )


async def build_inferential_bridge_section(
    receipts: Sequence[ReceiptSummary],
    *,
    topic: str,
    chain: Sequence[CallSpec],
    spec: Any,
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    seed: int | None = None,
    unresolved_boundary: bool = False,
) -> SynthesisSection:
    claims = await request_inference_claims(
        receipts,
        topic=topic,
        chain=chain,
        spec=spec,
        client=client,
        ledger=ledger,
        seed=seed,
    )
    return render_inferential_bridge_section(claims, unresolved_boundary=unresolved_boundary)


def _receipt_context(receipts: Sequence[ReceiptSummary]) -> str:
    rows = []
    for r in receipts[:80]:
        title = r.source_title or r.thesis_text[:120]
        rows.append(
            f"- id={r.receipt_id}; tier={r.evidence_tier}; "
            f"directness={r.directness}; outcome={r.outcome_class}; title={title}"
        )
    return "\n".join(rows)


def _derive_canon_refs(receipts: Sequence[ReceiptSummary], configured: set[str]) -> set[str]:
    if configured:
        return configured
    derived = {
        r.receipt_id for r in receipts
        if r.directness in {"indirect", "mechanistic"} or r.evidence_tier[:1] in {"B", "C"}
    }
    return derived or {r.receipt_id for r in receipts}


async def request_inference_claims(
    receipts: Sequence[ReceiptSummary],
    *,
    topic: str,
    chain: Sequence[CallSpec],
    spec: Any,
    client: httpx.AsyncClient | None = None,
    ledger: CostLedger | None = None,
    seed: int | None = None,
) -> tuple[InferenceClaim, ...]:
    max_n = max(0, int(getattr(spec, "max_inferences_per_paper", 0) or 0))
    configured_canon = set(getattr(spec, "canon_references", ()) or ())
    receipt_ids = {r.receipt_id for r in receipts}
    canon = _derive_canon_refs(receipts, configured_canon)
    if not receipts or not chain or max_n <= 0 or not canon:
        return ()
    schema = (
        '{"inferences":[{"claim":"directional bridge claim without new numerics",'
        '"mechanism_anchor":["receipt_id"],"conservation_argument":"named logic",'
        '"canon_refs":["allowed ref"],"existing_human_signal":["receipt_id or none"],'
        '"confidence":"low|medium|high","testability":"specific future test",'
        '"tier":"D1_inferential_bridge"}]}'
    )
    messages = [
        {"role": "system", "content": (
            "Emit JSON only. Create D1 inferential bridge claims. "
            "Do not add numerics. Use only listed receipt ids and canon refs."
        )},
        {"role": "user", "content": (
            f"Topic: {topic}\nAllowed canon refs: {sorted(canon)}\n"
            f"Receipts:\n{_receipt_context(receipts)}\n\n"
            f"JSON shape:\n{schema}"
        )},
    ]
    try:
        resp = await chat_json(
            messages=messages,
            chain=chain,
            client=client,
            ledger=ledger,
            temperature=0.0,
            max_tokens=1400,
            seed=seed,
        )
    except LLMError:
        return ()
    raw = resp.parsed.get("inferences", ())
    if not isinstance(raw, Sequence):
        return ()
    return filter_valid_inferences(
        [x for x in raw if isinstance(x, Mapping)],
        receipt_ids=receipt_ids,
        canon_refs=canon,
        receipt_effects={r.receipt_id: r.effect_direction for r in receipts},
        max_n=max_n,
    )
