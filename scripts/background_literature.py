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
) -> dict[str, BackgroundLitEntry]:
    """Load registry from seed JSON. Returns {key: entry}. Empty
    when the seed file doesn't exist (caller falls back to corpus-
    only behaviour)."""
    p = path or _DEFAULT_SEED_PATH
    if not p.exists():
        return {}
    raw = json.loads(p.read_text())
    out: dict[str, BackgroundLitEntry] = {}
    for k, v in raw.items():
        out[k] = BackgroundLitEntry(
            key=k,
            numeric=v["numeric"],
            context=v.get("context", ""),
            citation_token=v["citation_token"],
            canonical_reference=v.get("canonical_reference", ""),
            doi=v.get("doi"),
            pmid=v.get("pmid"),
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
    paper_md: str, registry: dict[str, BackgroundLitEntry],
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
    for entry in registry.values():
        # Use word-boundary-ish substring match (numeric strings often
        # contain non-word chars like `%`, `/`, `.` so simple `\b`
        # doesn't always work — use literal substring).
        for sent in sentences:
            if entry.numeric not in sent:
                continue
            if entry.citation_token in sent:
                continue  # cited — admitted
            # Skip markdown table content — see docstring.
            if _is_table_dominated(sent):
                continue
            # Found numeric without citation in same sentence
            snippet = sent.strip()[:160]
            unsourced.append(
                (entry.numeric, entry.citation_token, snippet)
            )
    return unsourced


def _is_table_dominated(text: str) -> bool:
    """True if at least half of the non-blank lines in `text` start
    with `|` (markdown table rows). Used to skip table content from
    background-literature unsourced detection."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    n_table = sum(1 for ln in lines if ln.lstrip().startswith("|"))
    return n_table / len(lines) >= 0.5
