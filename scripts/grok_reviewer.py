"""Day 10.17 Phase 6.2 Layer 2 — Grok 4.3 patch proposer.

Per the converged reviewer plan (and the user's "Grok can edit, with
guardrails" call): Grok proposes typed patches with provenance. Every
patch is then validated and applied by `scripts/apply_patches.py` per
per-type gate rules:

  formatting   — auto-apply (typos, spacing, header tier)
  numeric      — must trace to v0.6 quant_claims; else flag-only
  citation     — must map to a real receipt_id; else flag-only
  claim        — flag-only (no silent claim edits)
  structure    — flag-only (no silent restructuring)

The Grok prompt explicitly enumerates these rules so the model
proposes appropriately-typed patches; the applicator independently
verifies each patch against the trust spine.

Inputs:
  - full_paper.md
  - manifest.json
  - <paper>.audit.json
  - <paper>.consistency.json (Layer 1 output)

Output:
  - <paper>.review_patches.json — list of TypedPatch records
  - <paper>.review_summary.md   — human-readable review notes

Cost budget: ~$0.05-0.15 per paper (Grok 4.3 via OpenRouter).
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
from agent.settings import load_settings  # noqa: E402  loads .env

__all__ = ["TypedPatch", "review_with_grok", "main"]


PATCH_TYPES = (
    "formatting",   # auto-apply
    "numeric",      # must trace to corpus
    "citation",     # must map to receipt
    "claim",        # flag-only
    "structure",    # flag-only
)


@dataclass(frozen=True, slots=True)
class TypedPatch:
    """One Grok-proposed edit with provenance metadata."""
    id: str
    patch_type: str       # one of PATCH_TYPES
    severity: str         # P1 | P2 | P3
    location: str         # section name or line marker
    before: str           # exact paper substring to replace
    after: str            # replacement text
    reason: str           # one-sentence why
    auto_applicable: bool # only formatting; others go through gates
    requires_trace: bool  # numeric / citation must verify against corpus


def _build_grok_prompt(
    paper_md: str, manifest: dict, audit: dict,
) -> tuple[str, str]:
    """System + user messages for Grok. The system prompt enumerates
    the patch type contract so Grok produces correctly-typed output."""
    system = (
        "You are a careful research-synthesis reviewer. Your job is to "
        "find issues in the paper and propose TYPED patches with "
        "provenance. You are NOT writing prose; you are emitting a "
        "structured patch list.\n\n"
        "PATCH TYPE CONTRACT (you MUST tag every patch with one):\n"
        "  formatting — typos, header tier, spacing, list markers. "
        "Auto-applies; safe to be specific.\n"
        "  numeric    — any change touching a number, percentage, "
        "p-value, CI, or sample size. Will be VERIFIED against the "
        "v0.6 quant_claims corpus before applying. If the new "
        "number isn't in the corpus, the patch is rejected.\n"
        "  citation   — any change to a paper citation (Author Year, "
        "DOI, etc.). Verified against the receipt list.\n"
        "  claim      — any change to a substantive claim (effect "
        "direction, magnitude, mechanism). FLAG ONLY — will not be "
        "auto-applied; surfaces for human review.\n"
        "  structure  — moving sentences, adding/removing sections, "
        "restructuring an argument. FLAG ONLY — same as claim.\n\n"
        "Output ONLY a JSON object: {\"patches\": [<TypedPatch>...]}\n"
        "Each TypedPatch:\n"
        "  {\n"
        "    \"id\": \"P01\", \"P02\", ...,\n"
        "    \"patch_type\": one of formatting | numeric | citation | claim | structure,\n"
        "    \"severity\": \"P1\" (ship-blocker) | \"P2\" (quality) | \"P3\" (polish),\n"
        "    \"location\": section name (e.g. \"Abstract\", \"Discussion\"),\n"
        "    \"before\": exact paper substring to replace (≤160 chars),\n"
        "    \"after\":  replacement text (or empty string for deletion),\n"
        "    \"reason\": one sentence,\n"
        "  }\n\n"
        "RULES:\n"
        "1. Do not invent numerics. If you flag a numeric as wrong, set "
        "patch_type=numeric and let the verifier check.\n"
        "2. Prefer minimal diffs. Don't restructure unless absolutely necessary.\n"
        "3. If unsure, lean toward FLAG (claim/structure) — easier for "
        "humans to override than to undo a silent edit.\n"
        "4. Look for: contradictions between sections, awkward phrasing, "
        "missing hedges on overclaims, broken citations, factual errors, "
        "stale boilerplate, dead links/references.\n"
        "5. Output AT MOST 25 patches. Triage to highest-severity first.\n"
    )
    n_receipts = len(manifest.get("receipts", []))
    audit_p1 = audit.get("p1_pass", False)
    audit_score = audit.get("score_out_of_10", 0)
    user = (
        f"# Paper to review ({len(paper_md.split())} words)\n\n"
        f"## Pipeline metadata\n"
        f"- Extractor version: {manifest.get('extractor_version', 'unknown')}\n"
        f"- Writer path: {manifest.get('writer_path', 'unknown')}\n"
        f"- Receipts: {n_receipts}\n"
        f"- Local audit: score={audit_score}/10, P1={'PASS' if audit_p1 else 'FAIL'}\n\n"
        f"## Receipt list (use ONLY these for citations)\n"
        + "\n".join(
            f"- {r.get('receipt_id', '?')}: outcome={r.get('outcome_class', '?')} "
            f"effect={r.get('effect_direction', '?')} tier={r.get('evidence_tier', '?')}"
            for r in manifest.get("receipts", [])
        )
        + "\n\n## Paper full text\n\n```markdown\n"
        + paper_md
        + "\n```\n\nNow produce the JSON patch list."
    )
    return system, user


async def _call_grok(
    system: str, user: str, model: str, api_key: str,
    base_url: str, client: Any,
) -> dict[str, Any]:
    """Single Grok call. Returns the parsed JSON object."""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 12000,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = await client.post(url, json=payload, headers=headers, timeout=300.0)
    r.raise_for_status()
    body = r.json()
    text = body["choices"][0]["message"].get("content", "{}")
    # Strip JSON fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _normalize_patch(p_raw: dict, idx: int) -> TypedPatch | None:
    """Coerce a raw Grok-emitted dict into a TypedPatch. Returns None
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
        before=before[:300],   # cap to avoid runaway
        after=after[:600],
        reason=(p_raw.get("reason") or "").strip()[:400],
        auto_applicable=auto,
        requires_trace=requires_trace,
    )


async def review_with_grok(
    paper_md: str, manifest: dict, audit: dict,
    *, model: str = "x-ai/grok-4.3",
    api_key: str | None = None,
    base_url: str = "https://openrouter.ai/api/v1",
) -> tuple[list[TypedPatch], dict]:
    """Run the Grok review. Returns (patches, raw_response)."""
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set; cannot run Grok review")
    system, user = _build_grok_prompt(paper_md, manifest, audit)
    import httpx
    async with httpx.AsyncClient(timeout=300.0) as client:
        raw = await _call_grok(
            system, user, model, api_key, base_url, client,
        )
    patches: list[TypedPatch] = []
    for i, p in enumerate(raw.get("patches", []), start=1):
        norm = _normalize_patch(p, i)
        if norm is not None:
            patches.append(norm)
    return patches, raw


def _format_summary(
    patches: list[TypedPatch], cost_estimate: float = 0.0,
) -> str:
    if not patches:
        return (
            "# Grok 4.3 Review\n\n"
            "**No patches proposed.** Paper looks clean to the LLM "
            "reviewer.\n"
        )
    by_type: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for p in patches:
        by_type[p.patch_type] = by_type.get(p.patch_type, 0) + 1
        by_sev[p.severity] = by_sev.get(p.severity, 0) + 1
    lines = [
        "# Grok 4.3 Review",
        "",
        f"**{len(patches)} patches proposed.**",
        f"- By type: {by_type}",
        f"- By severity: {by_sev}",
        f"- Estimated cost: ${cost_estimate:.4f}",
        "",
        "## Patches",
        "",
        "| # | Type | Sev | Auto? | Trace? | Location | Reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in patches:
        lines.append(
            f"| {p.id} | {p.patch_type} | {p.severity} | "
            f"{'✓' if p.auto_applicable else '✗'} | "
            f"{'✓' if p.requires_trace else '—'} | "
            f"{p.location} | {p.reason[:80]} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 6.2 Layer 2 — Grok 4.3 patch proposer",
    )
    parser.add_argument("paper_md", help="full_paper.md")
    parser.add_argument(
        "--model", default=os.environ.get("GROK_MODEL", "x-ai/grok-4.3"),
        help="OpenRouter model id (default: x-ai/grok-4.3)",
    )
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

    patches, raw = asyncio.run(
        review_with_grok(paper, manifest, audit, model=args.model),
    )
    out_json = paper_path.with_suffix(".review_patches.json")
    out_md = paper_path.with_suffix(".review_summary.md")
    out_json.write_text(json.dumps({
        "model": args.model,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_patches": len(patches),
        "patches": [asdict(p) for p in patches],
        "raw_response_keys": sorted((raw or {}).keys()),
    }, indent=2))
    out_md.write_text(_format_summary(patches))
    print(_format_summary(patches))
    print(f"\nPatches: {out_json}\nSummary: {out_md}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
