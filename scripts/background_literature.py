"""Fix #16: Background-literature registry — the 'external context lane.'

Pre-fix: any numeric not in the run's quant_claims corpus failed Q2,
even when the LLM was correctly pulling well-established clinical
thresholds from training data (e.g. 0.8 m/s frailty cutoff →
Studenski et al. 2011, JAMA). The strict-Q2 gate blocked ship.

Architectural fix per converged reviewer recommendation:

    LLM proposes external context  →  registry verifies  →
    deterministic gate admits with citation  →  paper labels as background

This module is the registry. It loads a curated JSON of pre-vetted
clinical thresholds (each tied to a canonical citation), exposes
their numeric values to Q2's trace check, and provides a check that
verifies the citation appears in the same sentence as the numeric.

Architecture: pure deterministic, no LLM, no I/O beyond reading
the seed JSON. Future expansion: a separate retrieval agent could
auto-add new entries, but every entry MUST carry a canonical
citation before it admits a numeric to publication."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


# Canonical seed lives next to the docs so it's curatable like
# corpus data; per-domain overrides can land in topic packs later.
_DEFAULT_SEED_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs" / "background_literature.json"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class BackgroundLitEntry:
    """One pre-vetted clinical/scientific threshold + its canonical
    citation. Cross-stage object → frozen+slots+kw_only per project
    rule.

    `numeric` is the canonical string form (e.g. '0.8 m/s', '7%') —
    matched as a substring against the paper text. `citation_token`
    is the Author-Year body-citation form the paper must include in
    the same sentence to be admitted (e.g. 'Studenski 2011')."""
    key: str                  # stable lookup key
    numeric: str              # canonical numeric string
    context: str              # one-line context ('frailty walk-speed cutoff')
    citation_token: str       # Author-Year form ('Studenski 2011')
    canonical_reference: str  # full reference (Author. Year. Title. Journal)
    doi: str | None = None
    pmid: str | None = None


def load_registry(
    path: Path | None = None,
    *,
    topic: str | None = None,
) -> dict[str, BackgroundLitEntry]:
    """Load registry from seed JSON. Returns {key: entry}. Empty
    when the seed file doesn't exist (caller falls back to corpus-
    only behaviour).

    Refactor 2026-05-04: when `topic` is set OR
    audit_v06_paper._ACTIVE_TOPIC has been set by the orchestrator,
    merge in the topic pack's background_literature entries. This
    means topic-specific canonical numerics (e.g. PEARL '80',
    Harrison '14%/9%') live in topic_packs/<topic>.toml instead of
    polluting the global JSON.

    Topic resolution order: explicit `topic=` arg → audit module's
    _ACTIVE_TOPIC (set by orchestrator) → no topic merge.
    """
    if topic is None:
        # Best-effort read of the orchestrator's active topic so
        # call sites that don't pass topic= still get topic-pack
        # entries.
        try:
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(
                0, str(_P(__file__).resolve().parent),
            )
            import audit_v06_paper as _av
            topic = getattr(_av, "_ACTIVE_TOPIC", None)
        except (ImportError, AttributeError):
            topic = None
    p = path or _DEFAULT_SEED_PATH
    out: dict[str, BackgroundLitEntry] = {}
    if p.exists():
        raw = json.loads(p.read_text())
        for k, v in raw.items():
            out[k] = BackgroundLitEntry(
                key=k,
                numeric=v["numeric"],
                context=v.get("context", ""),
                citation_token=v["citation_token"],
                canonical_reference=v.get(
                    "canonical_reference", "",
                ),
                doi=v.get("doi"),
                pmid=v.get("pmid"),
            )
    # Merge topic pack entries (override globals on key clash;
    # topic packs are more specific so they win).
    if topic:
        try:
            import sys as _sys
            _sys.path.insert(
                0, str(Path(__file__).resolve().parent.parent),
            )
            from agent.topic_pack import load_topic_pack
            tp_path = (
                Path(__file__).resolve().parent.parent
                / "topic_packs" / f"{topic}.toml"
            )
            if tp_path.exists():
                pack = load_topic_pack(tp_path)
                for entry in pack.background_literature:
                    out[entry.key] = BackgroundLitEntry(
                        key=entry.key,
                        numeric=entry.numeric,
                        context=entry.context,
                        citation_token=entry.citation_token,
                        canonical_reference=(
                            entry.canonical_reference
                        ),
                        doi=entry.doi,
                        pmid=entry.pmid,
                    )
        except (ImportError, OSError, ValueError) as e:
            print(
                f"  ! topic-pack bg-lit merge failed: {e}",
                file=__import__("sys").stderr,
            )
    return out


def numeric_values(registry: dict[str, BackgroundLitEntry]) -> set[str]:
    """Set of canonical numeric strings (for Q2 trace lookup).
    Includes both the raw numeric and a digit-only normalized form
    so '0.8 m/s' matches paper text containing just '0.8'."""
    out: set[str] = set()
    for e in registry.values():
        out.add(e.numeric)
        # Extract pure number for tolerant matching
        m = re.match(r"^\s*(-?\d+\.?\d*)", e.numeric)
        if m:
            out.add(m.group(1))
    return out


def find_unsourced_background_uses(
    paper_md: str,
    registry: dict[str, BackgroundLitEntry],
    *,
    manifest: dict | None = None,
    quant_claims_dir: Path | None = None,
) -> list[tuple[str, str, str]]:
    """For each background-literature numeric that appears in the
    paper, check the citation_token also appears in the same sentence.

    Returns [(numeric, citation_token, evidence_snippet)] for every
    unsourced use. Empty list = clean.

    Fix #21 follow-up: SKIPS markdown table rows. Table cells surface
    corpus numerics (some of which match background_literature
    entries like '7%' or '0.8 m/s'). Those numerics are authorised:
    they come from the corpus's quant_claims, NOT from the LLM's
    training-data world knowledge. Flagging them as "unsourced
    background" would force a strip of structured evidence the
    paper LEGITIMATELY surfaces."""
    if not registry:
        return []
    # Split paper into sentences (rough — period followed by whitespace
    # + capital, OR newline). Same heuristic as final_consistency_audit.
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|\n\n+")
    sentences = sent_split.split(paper_md)
    unsourced: list[tuple[str, str, str]] = []
    # Build a digit-boundary-aware regex per entry. The numeric string
    # may contain non-word chars ('%', '/', '.') so `\b` doesn't always
    # work. We use a NEGATIVE LOOKBEHIND that forbids a leading digit
    # to prevent '5%' from matching inside '95%' (CI notation).
    # Refactor 2026-05-04: fixes a false positive where '5%' bg-lit
    # entry was triggering on every '95% CI:' in the paper.
    receipt_numeric_tokens = _receipt_numeric_tokens_by_citation(
        manifest,
        quant_claims_dir,
    )
    entry_patterns: dict[str, re.Pattern] = {}
    for entry in registry.values():
        # Anchor: not preceded by a digit, then literal numeric.
        pat = (
            r"(?<![\d.])"
            + re.escape(entry.numeric)
        )
        entry_patterns[entry.key] = re.compile(pat)
    for entry in registry.values():
        pat = entry_patterns[entry.key]
        for sent in sentences:
            if not pat.search(sent):
                continue
            if entry.citation_token in sent:
                continue  # cited — admitted
            if _supported_by_receipt_numeric(
                sent,
                entry.numeric,
                receipt_numeric_tokens,
            ):
                continue
            # Skip markdown table content — see docstring.
            if _is_table_dominated(sent):
                continue
            # Found numeric without citation in same sentence
            snippet = sent.strip()[:160]
            unsourced.append(
                (entry.numeric, entry.citation_token, snippet)
            )
    return unsourced


def _receipt_numeric_tokens_by_citation(
    manifest: dict | None,
    quant_claims_dir: Path | None,
) -> dict[str, set[str]]:
    if not isinstance(manifest, dict) or quant_claims_dir is None:
        return {}
    out: dict[str, set[str]] = {}
    for receipt in manifest.get("receipts") or ():
        token = str(receipt.get("citation_token") or "").strip()
        rid = str(receipt.get("receipt_id") or "").strip()
        if not token or not rid:
            continue
        path = quant_claims_dir / f"{rid}.quant_claims.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        numerics: set[str] = set()
        for claim in data.get("claims") or ():
            if claim.get("binding_confidence") != "high":
                continue
            raw = str(claim.get("raw_text") or "").strip()
            if raw:
                numerics.add(raw)
            for value in claim.get("numeric_values") or ():
                numerics |= _numeric_variants(value)
        if numerics:
            out[token] = numerics
    return out


def _numeric_variants(value: object) -> set[str]:
    text = str(value).strip()
    out = {text} if text else set()
    try:
        num = float(text)
    except ValueError:
        return out
    if num.is_integer():
        out.add(str(int(num)))
        out.add(f"{int(num)}%")
    out.add(f"{num:g}")
    out.add(f"{num:g}%")
    return out


def _supported_by_receipt_numeric(
    sentence: str,
    numeric: str,
    receipt_numeric_tokens: dict[str, set[str]],
) -> bool:
    for citation_token, tokens in receipt_numeric_tokens.items():
        if citation_token not in sentence:
            continue
        if numeric in tokens:
            return True
    return False


def _is_table_dominated(text: str) -> bool:
    """True if at least half of the non-blank lines in `text` start
    with `|` (markdown table rows). Used to skip table content from
    background-literature unsourced detection."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    n_table = sum(1 for ln in lines if ln.lstrip().startswith("|"))
    return n_table / len(lines) >= 0.5
