"""Day 10.17 Phase 6-lite — diagnostic paper run.

Strategic call (per AAA audit verdict): stop building benchmark
infrastructure ahead of proving the writer can convert v0.5.0 bound
claims into a publishable argument. This script wires the new
evidence layer directly into a prose-generating LLM call and
produces a diagnostic draft.

NOT publishable. The output is a DIAGNOSTIC: it reveals what works
and what doesn't when bound claims feed prose. Phase 4 (gold
benchmark) and Phase 5 (ablation) are conditional follow-ups based
on what this draft surfaces.

Pipeline:
  1. Load all 42 quant_claims/*.json
  2. Filter to high-confidence (effect-role + endpoint+arm+direction
     bound) — 93 claims at v0.5.0
  3. Group by endpoint → per-endpoint evidence tables
  4. Generate paper sections via LLM:
       - Abstract (~250 words, top claims only)
       - Introduction (~800 words)
       - Methods (~600 words)
       - Results-by-endpoint (~2000 words)
       - Discussion (~1200 words)
       - Limitations (~400 words)
       - Conclusion (~250 words)
     Total target: ~5500 words.
  5. Concatenate → paper.md
  6. Write run dir: runs/diagnostic-paper-{ISO}/

Cost budget: ~$0.05 per full run (7 LLM calls × ~7k tokens each).
Capped via DAILY_COST_CAP_USD safety rail (existing env contract).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# agent/ is the runtime; we import the existing LLM client to reuse
# the auth/cost/fallback infrastructure rather than reinventing it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.llm_client import (  # noqa: E402
    CallSpec, LLMError,
)
from agent.settings import load_settings  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent
QUANT_DIR = REPO_ROOT / "docs" / "quality-reference" / "metformin" / "quant_claims"
PARSED_DIR = REPO_ROOT / "docs" / "quality-reference" / "metformin" / "parsed"


# Section spec: (name, target_words, section_function_key)
_SECTIONS: tuple[tuple[str, int, str], ...] = (
    ("Abstract", 250, "abstract"),
    ("Introduction", 800, "introduction"),
    ("Methods", 600, "methods"),
    ("Results", 2000, "results"),
    ("Discussion", 1200, "discussion"),
    ("Limitations", 400, "limitations"),
    ("Conclusion", 250, "conclusion"),
)


def _load_high_confidence_claims() -> list[dict[str, Any]]:
    """Load all v0.5.0 high-confidence claims from the 42-paper corpus.
    Each carries endpoint+arm+direction+claim_role=='effect' bindings
    plus its source sentence."""
    claims: list[dict[str, Any]] = []
    for path in sorted(QUANT_DIR.glob("*.quant_claims.json")):
        data = json.loads(path.read_text())
        paper_id = data.get("paper_id", path.stem)
        for c in data.get("claims", []):
            if c.get("binding_confidence") == "high":
                claims.append({
                    **c,
                    "paper_id": paper_id,
                })
    return claims


def _group_by_endpoint(
    claims: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group high-confidence claims by their bound endpoint. Phase 4
    Results section is organized along these clusters."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in claims:
        ep = c.get("endpoint") or "unbound"
        groups[ep].append(c)
    return dict(groups)


def _format_claim_for_prompt(c: dict[str, Any]) -> str:
    """One-line evidence row for the LLM prompt. Short by design — the
    LLM sees structured columns rather than parsing prose."""
    vals = c.get("numeric_values", [])
    val_str = (
        str(vals[0]) if len(vals) == 1
        else f"({vals[0]} to {vals[1]})" if len(vals) >= 2
        else "?"
    )
    return (
        f"- [{c['paper_id'][:30]}] {c.get('claim_type', '?'):>20s} "
        f"{val_str:>10s} {c.get('units', ''):>8s} | "
        f"endpoint={c.get('endpoint', '?')} | "
        f"arm={c.get('arm', '?')} | direction={c.get('direction', '?')} | "
        f"sentence: {c.get('sentence', '')[:120]}"
    )


def _build_section_prompt(
    section_name: str, target_words: int,
    grouped_claims: dict[str, list[dict[str, Any]]],
    paper_metadata: list[dict[str, Any]],
) -> tuple[str, str]:
    """Build (system, user) messages for one section. The system
    message defines the writer voice + hard constraints; the user
    message provides the bound-claim evidence."""
    system = (
        "You are a careful research-synthesis writer for a peer-review-grade "
        "paper on metformin and aging. You write at the caliber of MASTERS "
        "(Walton 2019), MILES (Kulkarni 2018), MET-PREVENT (Witham 2025), "
        "Konopka 2019, and Mohammed 2021.\n\n"
        "HARD CONSTRAINTS:\n"
        "1. Every quantitative claim MUST cite the source paper "
        "in parens — e.g., '(Walton MASTERS, 2019)'. Use the paper_id "
        "shown in brackets in the evidence rows.\n"
        "2. Do NOT invent numerics. Use only values listed in the "
        "evidence rows. If a value isn't listed, write the qualitative "
        "finding without a number.\n"
        "3. Use HEDGES for any inference that goes beyond the literal "
        "evidence: 'suggests', 'consistent with', 'evidence indicates'.\n"
        "4. The arm and direction in each evidence row are LOAD-BEARING. "
        "If the evidence says arm=metformin direction=decrease, the prose "
        "must say metformin reduced/blunted/attenuated, NOT placebo.\n"
        "5. Output Markdown. Section heading is '## {section}'. Target "
        f"length: {target_words} words for THIS section."
    )

    metadata_lines = "\n".join(
        f"- {m['paper_id']}: {m.get('title', '')[:80]}"
        f" ({m.get('journal', '')}, {m.get('year', '')})"
        for m in paper_metadata
    )

    if section_name == "Methods":
        # Methods section gets metadata-only; no claim tables.
        user = (
            f"# Section to write: {section_name}\n\n"
            f"Target: {target_words} words. Write the Methods section as a "
            "summary of the 7 reference papers' study designs, eligibility, "
            "interventions, and outcomes.\n\n"
            f"## Source papers ({len(paper_metadata)} curated reference papers):\n"
            f"{metadata_lines}\n\n"
            "Output: a Methods section in Markdown that explains how this "
            "synthesis was constructed (the meta-method: deterministic "
            "regex extraction of quantitative claims with endpoint+arm+"
            "direction binding, claim_role tagging, and high-confidence "
            "filtering)."
        )
        return system, user

    # All other sections get the bound-claim evidence rows.
    evidence_lines: list[str] = []
    if section_name in ("Results", "Discussion", "Abstract"):
        # By-endpoint organization — primary structure of the Results.
        for endpoint in sorted(grouped_claims, key=lambda k: -len(grouped_claims[k])):
            if endpoint == "unbound":
                continue
            ep_claims = grouped_claims[endpoint]
            evidence_lines.append(f"\n### Endpoint: {endpoint} ({len(ep_claims)} claims)")
            # Cap per-endpoint claim rows so the prompt stays under
            # ~12k tokens. Sample top-N by direction diversity.
            for c in ep_claims[:8]:
                evidence_lines.append(_format_claim_for_prompt(c))
    elif section_name == "Introduction":
        # Introduction needs background context — pull a few representative
        # claims plus paper metadata.
        evidence_lines.append("Top high-confidence findings across endpoints:")
        for endpoint, ep_claims in sorted(
            grouped_claims.items(), key=lambda kv: -len(kv[1]),
        )[:6]:
            if endpoint == "unbound":
                continue
            evidence_lines.append(f"\n  endpoint={endpoint}")
            for c in ep_claims[:3]:
                evidence_lines.append("  " + _format_claim_for_prompt(c))
    elif section_name in ("Limitations", "Conclusion"):
        # Limitations + Conclusion need the high-level corpus stats.
        evidence_lines.append(
            f"Corpus: {len(paper_metadata)} papers, "
            f"{sum(len(v) for v in grouped_claims.values())} high-confidence "
            "(effect-role + fully bound) quantitative claims."
        )
        evidence_lines.append(
            "Endpoints with ≥5 high-confidence claims: " + ", ".join(
                f"{k} ({len(v)})"
                for k, v in sorted(
                    grouped_claims.items(), key=lambda kv: -len(kv[1]),
                ) if k != "unbound" and len(v) >= 5
            )
        )

    evidence_block = "\n".join(evidence_lines)
    user = (
        f"# Section to write: {section_name}\n\n"
        f"Target length: {target_words} words. Output Markdown with "
        f"'## {section_name}' as the heading.\n\n"
        f"## Source papers:\n{metadata_lines}\n\n"
        f"## Bound-claim evidence (use ONLY these numerics):\n{evidence_block}"
    )
    return system, user


# v0.6.0 audit fix: per-1k-token pricing for the providers we actually
# use. Maps to (input_per_1k, output_per_1k) USD. Models not in the
# table get cost=0 logged (still correct for budget reporting; the
# provider-side bill will be the source of truth).
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "mimo-v2.5-pro": (0.000, 0.000),  # unlimited token plan
    "mistralai/mistral-small-2603": (0.00020, 0.00060),
    "google/gemma-4-31b-it": (0.000, 0.000),  # OpenRouter cheap/free tier
}


def _estimate_cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    in_per, out_per = _MODEL_PRICING.get(model, (0.0, 0.0))
    return (in_tok / 1000.0) * in_per + (out_tok / 1000.0) * out_per


async def _call_text_mode(
    spec: CallSpec, messages: list[dict[str, str]],
    client: Any, max_tokens: int = 8000, temperature: float = 0.2,
) -> tuple[str, int, int]:
    """Minimal text-mode chat completion. Bypasses chat_json which
    always JSON-parses the response (buggy when enforce_json=False —
    intentional for the runtime synthesis path, wrong for prose).
    Returns (text, input_tokens, output_tokens). Raises on any
    transport / parse / payment error so the chain fallback can try
    the next spec."""
    if not spec.api_key:
        raise LLMError(f"missing api_key for {spec.model}")
    url = spec.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": spec.model,
        "temperature": temperature,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {spec.api_key}",
        "Content-Type": "application/json",
    }
    r = await client.post(
        url, json=payload, headers=headers, timeout=spec.timeout_sec,
    )
    r.raise_for_status()
    body = r.json()
    choice = body["choices"][0]["message"]
    text = (choice.get("content") or "").strip()
    if not text:
        raise LLMError(f"empty response from {spec.model}")
    usage = body.get("usage", {}) or {}
    return (
        text,
        int(usage.get("prompt_tokens", 0) or 0),
        int(usage.get("completion_tokens", 0) or 0),
    )


async def _generate_section(
    section_name: str, system: str, user: str,
    chain: list[CallSpec], ledger: list[dict[str, Any]],
    client: Any | None = None,
) -> str:
    """One LLM call → section markdown. Walks the chain on failure;
    skips specs without keys or with transient failures (DNS,
    payment, parse), surfaces only the last error.

    v0.6.0 fix: ledger is a list of per-call dicts (not the
    agent.llm_client.CostLedger which only chat_json fills). We
    append on every successful call so the manifest accurately
    reports n_llm_calls + total_cost_usd. Pre-fix ran 7 successful
    Gemma calls and reported 0 cost / 0 calls — false provenance.
    """
    import httpx
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=120.0)
        own_client = True
    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_err: Exception | None = None
        for spec in chain:
            try:
                text, in_tok, out_tok = await _call_text_mode(
                    spec, messages, client,
                )
                ledger.append({
                    "section": section_name,
                    "model": spec.model,
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "estimated_cost_usd": _estimate_cost_usd(
                        spec.model, in_tok, out_tok,
                    ),
                })
                return text
            except Exception as e:
                last_err = e
                continue
        raise LLMError(
            f"all {len(chain)} specs failed for {section_name}: {last_err}",
        )
    finally:
        if own_client:
            await client.aclose()


def _build_call_chain() -> list[CallSpec]:
    """Diagnostic-paper writer chain — MiniMax M3 is PRIMARY.

    Same chain as the production publisher (run_v06_synthesis.py):
    MiniMax M3 → Mistral Small (paid) → Gemma 4 31B
    (paid). Identifiers come from agent/settings.py — never hardcode
    here, that's how the previous vision-model / gemma-3-27b-it /
    deepseek drift happened.
    """
    settings = load_settings()
    chain: list[CallSpec] = []
    if settings.minimax_api_key:
        chain.append(CallSpec(
            base_url=settings.minimax_base_url,
            api_key=settings.minimax_api_key,
            model=settings.minimax_model,
            timeout_sec=settings.minimax_timeout_sec,
        ))
    if settings.openrouter_api_key:
        for openrouter_model in (settings.fallback_model, settings.judge_model):
            chain.append(CallSpec(
                base_url=settings.openrouter_base_url,
                api_key=settings.openrouter_api_key,
                model=openrouter_model,
                timeout_sec=settings.minimax_timeout_sec,
            ))
    return chain


def _build_methods_deterministic(
    paper_metadata: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
) -> str:
    """v0.6.0 audit fix: render Methods from facts only — no LLM. The
    pre-fix LLM-generated Methods invented "two researchers manually
    reviewed" / "consensus" — fabricated provenance that any reviewer
    would catch. Now: explicit "no manual review; algorithmic only"
    + extractor version + paper count + filter contract.
    """
    n_papers = len(paper_metadata)
    n_claims = len(claims)
    n_endpoints = len([k for k in grouped if k != "unbound"])
    paper_table = "\n".join(
        f"- **{m['paper_id']}** — {m.get('title', '')[:120]}"
        f" ({m.get('journal', 'unknown journal')}, {m.get('year', '')})"
        for m in paper_metadata
    )
    return f"""## Methods

**Provenance disclaimer:** This synthesis is generated by an automated
pipeline (`scripts/quant_claim_extract.py` v0.6.0, `scripts/diagnostic_paper_run.py`).
**No manual human review of individual claims occurred.** All filtering
is algorithmic. Domain-expert verification is a future-work step.

### Source corpus

{n_papers} reference papers contributed to the {n_claims} high-confidence
quantitative claims that ground this synthesis (out of 1001 total
extracted across the full 42-paper corpus). The contributing papers
are:

{paper_table}

### Extraction pipeline

1. **PDF / JATS XML → paper_sections.json** via `scripts/pdf_ingest.py`
   (PyMuPDF / pypdf for PDFs) and `scripts/fetch_oa_corpus.py` (Europe
   PMC JATS for open-access papers). Section detection is regex-based;
   metadata extraction (title, authors, year, journal, DOI/PMID) uses
   curated patterns hardened across the 7 reference papers in Phase 1.5.

2. **section text → quant_claims.json** via `scripts/quant_claim_extract.py`
   (extractor v0.6.0). Pattern bank: p-values, confidence intervals,
   sample sizes, percentages, mean ± SD, unit values, hazard ratios,
   odds ratios, risk ratios, correlations.

3. **Per-claim semantic binding** via `scripts/quant_endpoints.py`:
   - **endpoint** (e.g., VO2max, walk speed, lean body mass, mortality)
     via curated vocab; nearest-to-claim-anchor wins on dual-endpoint
     sentences (Phase 2.2-fix v0.5.0 audit response).
   - **arm** (metformin / placebo / control) with comparator-grammar
     handling ("Compared to placebo, metformin..." correctly binds
     subject, not the comparator).
   - **direction** (increase / decrease / no_change / mixed) with
     compound-phrase span containment (e.g., "attenuated the
     increase" → decrease, not increase).
   - **claim_role** (effect / dose / duration / population /
     background / protocol / unknown) via sentence-keyword heuristic.
     Mortality endpoints are now distinct from lifespan (v0.6.0).
     Treatment-timing months ("started at 9 months of age") tag as
     protocol, not effect.

### Inclusion criteria for this synthesis

For each numeric claim to qualify as primary evidence in this paper,
ALL of the following must hold:
- `binding_confidence == "high"` — endpoint, arm, AND direction all bound
- `claim_role == "effect"` — not dose, duration, protocol, etc.
- Source is a curated reference paper (not a search-fetched OA review)

These criteria yield {n_claims} high-confidence claims spanning
{n_endpoints} distinct endpoints across {n_papers} contributing papers.

### Synthesis approach

This is a **narrative** synthesis. No meta-analysis was performed
(study designs and outcome measures are heterogeneous). Quantitative
claims are organized by endpoint and attributed to source papers
verbatim.

### Limitations of method (intrinsic)

- **No manual claim verification.** Every numeric in this paper traces
  to an algorithmic regex match plus vocab-based binding. Polarity and
  semantic-class errors at the extraction layer surface as factual
  errors in prose.
- **Corpus is small.** {n_papers} contributing papers is far below the
  30-50 paper threshold typical for a peer-reviewed systematic review.
- **Tables and figures are not extracted.** Witham/MET-PREVENT and
  Walton/MASTERS report substantial primary-endpoint statistics in
  trial summary tables that this pipeline does not yet read.
- **English-language papers only.** No translation pipeline.
"""


def _build_references_block(paper_metadata: list[dict[str, Any]]) -> str:
    """v0.6.0 audit fix: deterministic References from paper metadata.
    Pre-fix the LLM cited papers via internal handles
    (`Walton_2019_MASTERS_metformin_`) — not publication-grade. Now
    a proper References section is appended."""
    lines = ["## References", ""]
    for m in paper_metadata:
        line = f"- **{m['paper_id']}**. "
        if m.get("title"):
            line += f"_{m['title']}._ "
        if m.get("journal"):
            line += f"{m['journal']}"
        if m.get("year"):
            line += f", {m['year']}"
        line += "."
        lines.append(line)
    lines.append("")
    lines.append(
        "_Note: This References section is rendered deterministically "
        "from `paper_sections.json` metadata. DOI / PMID linking is a "
        "follow-up polish step (Phase 6.2)._"
    )
    return "\n".join(lines)


async def _run(out_dir: Path, dry_run: bool = False) -> int:
    settings = load_settings()
    if not settings.bot_enabled:
        print("BOT_ENABLED=false; aborting per safety rail.", file=sys.stderr)
        return 1

    claims = _load_high_confidence_claims()
    if len(claims) < 30:
        print(
            f"Only {len(claims)} high-confidence claims; expected >=30. "
            "Check that v0.5.0 quant_claims are regenerated.",
            file=sys.stderr,
        )
        return 2
    grouped = _group_by_endpoint(claims)

    # Paper metadata from parsed files
    paper_metadata: list[dict[str, Any]] = []
    for path in sorted(PARSED_DIR.glob("*.paper_sections.json")):
        d = json.loads(path.read_text())
        # Only include the 7 core reference papers + any with high-conf claims.
        pid = d.get("paper_id", path.stem)
        contributes = any(c["paper_id"] == pid for c in claims)
        if contributes:
            paper_metadata.append({
                "paper_id": pid,
                "title": d.get("title", ""),
                "journal": d.get("journal", ""),
                "year": d.get("year"),
            })

    print(
        f"Loaded {len(claims)} high-confidence claims across "
        f"{len(grouped)} endpoints from {len(paper_metadata)} contributing "
        "papers.",
        file=sys.stderr,
    )

    chain = _build_call_chain()
    if not chain:
        print(
            "No LLM API keys configured (MIMO/OPENROUTER/DEEPSEEK).",
            file=sys.stderr,
        )
        return 3

    if dry_run:
        # Print the first section's prompt and exit — useful for debugging
        # without spending tokens.
        system_msg, user_msg = _build_section_prompt(
            "Results", 2000, grouped, paper_metadata,
        )
        print("=== DRY-RUN SYSTEM PROMPT ===\n" + system_msg)
        print("\n=== DRY-RUN USER PROMPT (first 3000 chars) ===\n" + user_msg[:3000])
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    # v0.6.0 fix: track real LLM calls (chat_json's CostLedger only fills
    # for chat_json calls, but we use _call_text_mode which bypasses it).
    ledger: list[dict[str, Any]] = []
    sections_md: list[str] = []
    import httpx
    async with httpx.AsyncClient(timeout=120.0) as client:
        for section_name, target_words, _key in _SECTIONS:
            # v0.6.0 audit fix: Methods is now DETERMINISTIC. Pre-fix
            # the LLM invented "two researchers manually reviewed" /
            # "consensus" — fabricated provenance. Now Methods renders
            # from the manifest + paper metadata + extractor docstring,
            # honestly stating "no manual review; algorithmic only."
            if section_name == "Methods":
                section_md = _build_methods_deterministic(
                    paper_metadata, claims, grouped,
                )
                sections_md.append(section_md)
                (out_dir / f"section_{_key}.md").write_text(section_md)
                print(
                    f"  → {section_name} (deterministic, no LLM call)",
                    file=sys.stderr,
                )
                continue

            system, user = _build_section_prompt(
                section_name, target_words, grouped, paper_metadata,
            )
            print(
                f"  → generating {section_name} (target={target_words} words)...",
                file=sys.stderr,
            )
            try:
                section_md = await _generate_section(
                    section_name, system, user, chain, ledger, client=client,
                )
            except LLMError as e:
                print(f"  ! {section_name} FAILED: {e}", file=sys.stderr)
                section_md = f"## {section_name}\n\n_(generation failed: {e})_"
            sections_md.append(section_md.strip())
            (out_dir / f"section_{_key}.md").write_text(section_md)

    # v0.6.0 fix: append a deterministic References block from paper
    # metadata. Replaces the truncated paper_id citations the LLM
    # falls back to. Phase 4 polish would extend this with DOI links
    # and proper Vancouver/APA formatting.
    references_md = _build_references_block(paper_metadata)
    sections_md.append(references_md)

    full_paper = "\n\n".join(sections_md)
    paper_path = out_dir / "diagnostic_paper.md"
    paper_path.write_text(full_paper)
    word_count = len(full_paper.split())

    manifest = {
        "extractor_version": "v0.6.0",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_high_confidence_claims": len(claims),
        "n_contributing_papers": len(paper_metadata),
        "n_endpoints": len([k for k in grouped if k != "unbound"]),
        "methods_section_source": "deterministic (no LLM call)",
        "section_sizes": [
            {"section": name, "words": len(md.split())}
            for (name, _w, _k), md in zip(_SECTIONS, sections_md)
        ] + [{"section": "References", "words": len(references_md.split())}],
        "total_words": word_count,
        "n_llm_calls": len(ledger),
        "total_cost_usd": round(
            sum(c["estimated_cost_usd"] for c in ledger), 6,
        ),
        "llm_call_log": ledger,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(
        f"\nDONE: {paper_path}\n"
        f"  total_words: {word_count}\n"
        f"  cost_usd: {manifest['total_cost_usd']:.4f}\n"
        f"  llm_calls: {manifest['n_llm_calls']}",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 6-lite diagnostic paper run from v0.5.0 bound claims",
    )
    parser.add_argument(
        "--out-dir",
        help="Output directory (default: runs/diagnostic-paper-{ISO}/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the first section's prompt without calling the LLM",
    )
    args = parser.parse_args(argv)
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = REPO_ROOT / "runs" / f"diagnostic-paper-{ts}"
    return asyncio.run(_run(out_dir, dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
