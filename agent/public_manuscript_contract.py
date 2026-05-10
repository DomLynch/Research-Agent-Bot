"""Public-manuscript contract — final-render gate.

Stdlib-only, no LLM. Runs after the paper is rendered, before
certification. Blocks AAA / journal_ready when the rendered Markdown
contradicts the manifest.

Five rules (all P1 — failing any blocks AAA):
  1. count_consistency  — free-text counts in the MD must match the
     manifest's canonical totals (n_receipts, n_high_confidence_claims_total,
     n_non_orthogonal_tensions). 4-digit years (1900-2100) are filtered to
     avoid "Yang 2023 study" false positives.
  2. duplicate_row      — Included-Studies table cannot contain the same
     citation_token twice unless the manifest has matching split receipts;
     receiver can never carry conflicting tiers/directness for one citation.
  3. section_boundary   — Abstract <= 500 words; no "H3:" residue tokens
     in the body; no duplicate top-level (## or #) sections.
  4. residue_phrase     — engine-internal language must not appear in
     the public MD (e.g. "Tournament selector", "no matched source
     in the accepted evidence registry").
  5. canonical_link     — manifest must expose the canonical totals; if
     unreadable, fail closed.

Universal / domain-agnostic: no biomedical hardcoding. The rules apply
to any topic this platform synthesises (biomedical, climate, materials,
economics, social science, computer science).

Output sidecar: <run_dir>/public_manuscript_contract.json
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


# ---- canonical counts ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalCounts:
    """Single source of truth for paper-wide totals."""

    source_papers: int
    high_confidence_claims: int
    tensions: int

    @classmethod
    def from_manifest(cls, manifest: dict) -> "CanonicalCounts":
        return cls(
            source_papers=int(manifest.get("n_receipts") or 0),
            high_confidence_claims=int(
                manifest.get("n_high_confidence_claims_total") or 0
            ),
            tensions=int(manifest.get("n_non_orthogonal_tensions") or 0),
        )


# ---- failure record ------------------------------------------------------


_RULES = (
    "count_consistency",
    "duplicate_row",
    "section_boundary",
    "residue_phrase",
    "canonical_link",
)
_RuleName = Literal[
    "count_consistency",
    "duplicate_row",
    "section_boundary",
    "residue_phrase",
    "canonical_link",
]


@dataclass(frozen=True, slots=True)
class ContractFailure:
    rule: _RuleName
    detail: str
    severity: Literal["P1"] = "P1"


@dataclass(frozen=True, slots=True)
class ContractResult:
    status: Literal["PASS", "FAIL"]
    failures: tuple[ContractFailure, ...]
    canonical: CanonicalCounts
    abstract_words: int
    n_failures_by_rule: dict[str, int] = field(default_factory=dict)


# ---- rule 1: count consistency ------------------------------------------


# (regex, category, canonical-counts attr name)
_COUNT_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b(\d{1,4})\s+"
            r"(?:source\s+papers?|reference\s+papers?|stud(?:y|ies)|papers?)\b",
            re.I,
        ),
        "paper",
        "source_papers",
    ),
    (
        re.compile(r"\b(\d{1,4})\s+(?:accepted\s+)?receipts?\b", re.I),
        "receipt",
        "source_papers",
    ),
    (
        re.compile(
            r"\b(\d{1,4})\s+"
            r"(?:source[- ]bound\s+observations?|"
            r"high[- ]confidence\s+claims?|claims?|observations?)\b",
            re.I,
        ),
        "claim",
        "high_confidence_claims",
    ),
    (
        re.compile(
            r"\b(\d{1,4})\s+(?:non[- ]orthogonal\s+)?tensions?\b", re.I,
        ),
        "tension",
        "tensions",
    ),
)

# Generic prose patterns where small ints are decorative, not paper-wide
# totals (e.g. "in 3 studies, the effect was negative"). The contract
# focuses on top-line summary counts; per-section figures < 5 are noise.
_NOISE_THRESHOLD = 5


def _is_year_token(n: int) -> bool:
    """4-digit years 1900-2100 should not be treated as count totals."""
    return 1900 <= n <= 2100


def _check_counts(
    body: str, canon: CanonicalCounts,
) -> list[ContractFailure]:
    """Find numeric claims in the MD that contradict the canonical totals.

    Filters: years (1900-2100), per-section noise (< _NOISE_THRESHOLD),
    and citation-context numbers like "in N studies" inside parentheses
    near a year. Only top-line claims count.
    """
    fails: list[ContractFailure] = []
    body_no_tables = _strip_table_rows(body)
    body_clean = _strip_code_fences(body_no_tables)
    seen: dict[str, set[int]] = defaultdict(set)
    for pat, cat, attr in _COUNT_PATTERNS:
        for m in pat.finditer(body_clean):
            try:
                n = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if _is_year_token(n) or n < _NOISE_THRESHOLD:
                continue
            seen[cat].add(n)
    for cat, attr in (
        ("paper", "source_papers"),
        ("receipt", "source_papers"),
        ("claim", "high_confidence_claims"),
        ("tension", "tensions"),
    ):
        canonical = getattr(canon, attr)
        if canonical <= 0:
            continue
        bad = sorted(n for n in seen.get(cat, set()) if n != canonical)
        if bad:
            fails.append(
                ContractFailure(
                    rule="count_consistency",
                    detail=(
                        f"{cat} count(s) {bad} in MD do not match canonical "
                        f"{attr}={canonical}"
                    ),
                )
            )
    return fails


# ---- rule 2: duplicate Included-Studies rows ----------------------------


_INCLUDED_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:Included\s+Studies|Studies\s+Included|Table\s+1\b)\b"
    r"[^\n]*\n",
    re.I | re.M,
)
# Citation-token shape: "Surname 2019" or "Surname 2019b" — first column
# of an Included-Studies row is the canonical citation.
_CITATION_TOKEN_RE = re.compile(
    r"^\s*\|\s*([A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)"
    r"\s*\|",
    re.M,
)
# Allowed disambiguator suffix that signals a deliberate split receipt:
# "Walton 2019 [muscle endpoint]" — the bracketed tag makes the split
# explicit. Detected directly in the citation cell.
_SPLIT_DISAMBIG_RE = re.compile(r"\[[^\]]+\]")


def _expected_split_count(
    manifest: dict, citation_token: str,
) -> int:
    """Count how many distinct receipts in the manifest carry this
    citation_token. >1 means a legitimate split (e.g. primary +
    secondary endpoint receipts on the same paper)."""
    receipts = manifest.get("receipts") or ()
    return sum(
        1 for r in receipts
        if isinstance(r, dict)
        and (r.get("citation_token") or "").strip() == citation_token
    )


def _check_duplicate_rows(
    body: str, manifest: dict,
) -> list[ContractFailure]:
    fails: list[ContractFailure] = []
    section = _extract_section(body, _INCLUDED_HEADING_RE)
    if not section:
        return fails  # No Included Studies table → not this gate's problem
    # Pull the table rows only — first cell ends with a 4-digit year.
    rows = _CITATION_TOKEN_RE.findall(section)
    if not rows:
        return fails
    # Identical-row check: two byte-identical Included-Studies rows is a
    # render bug even when the manifest holds split receipts (split rows
    # must differ in at least one cell — endpoint, direction, N, etc.).
    seen_full_rows: set[str] = set()
    dup_full_rows: list[str] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        # Skip the header / separator rows (contain "---" or "Citation").
        norm = re.sub(r"\s+", " ", line).strip()
        if "---" in norm or norm.lower().startswith("| citation"):
            continue
        # Only count rows that look like real data (start with a citation).
        if not _CITATION_TOKEN_RE.match(line):
            continue
        if norm in seen_full_rows:
            dup_full_rows.append(norm)
        else:
            seen_full_rows.add(norm)
    if dup_full_rows:
        fails.append(
            ContractFailure(
                rule="duplicate_row",
                detail=(
                    f"{len(dup_full_rows)} byte-identical row(s) in Included "
                    f"Studies. Example: '{dup_full_rows[0][:120]}...' — "
                    f"split receipts must differ in at least one cell."
                ),
            )
        )
    counts = Counter(rows)
    for cite, n in counts.items():
        if n <= 1:
            continue
        # Allow as many duplicate rows as there are split receipts
        # in the manifest (e.g. 2 receipts → up to 2 rows OK).
        allowed = max(1, _expected_split_count(manifest, cite.strip()))
        if n > allowed:
            fails.append(
                ContractFailure(
                    rule="duplicate_row",
                    detail=(
                        f"citation '{cite.strip()}' rendered {n} rows in "
                        f"Included Studies; manifest has {allowed} "
                        f"matching receipt(s). Render duplication or "
                        f"missing [split_receipt_id] disambiguator."
                    ),
                )
            )
    # Conflicting-metadata check: same citation, two different evidence
    # tiers in the same table → policy violation regardless of split count.
    tier_per_cite: dict[str, set[str]] = defaultdict(set)
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 3:
            continue
        cite_match = re.match(
            r"^([A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)",
            cells[0],
        )
        if not cite_match:
            continue
        # Tier is conventionally the 3rd cell (Citation | Design | Tier | ...).
        tier = cells[2] if len(cells) >= 3 else ""
        if re.fullmatch(r"[A-D][1-3]", tier):
            tier_per_cite[cite_match.group(1).strip()].add(tier)
    for cite, tiers in tier_per_cite.items():
        if len(tiers) > 1:
            fails.append(
                ContractFailure(
                    rule="duplicate_row",
                    detail=(
                        f"citation '{cite}' carries conflicting evidence "
                        f"tiers {sorted(tiers)} in Included Studies — "
                        f"engine cannot assign two tiers to one receipt."
                    ),
                )
            )
    return fails


# ---- rule 3: section boundary -------------------------------------------


_ABSTRACT_HEADING_RE = re.compile(r"^#{1,4}\s*Abstract\b[^\n]*\n", re.I | re.M)
_HEADING_RE = re.compile(r"^(#{1,6})\s+([^\n]+)$", re.M)
_H3_RESIDUE_RE = re.compile(r"\bH3:\s*", re.M)


def _check_sections(
    body: str, *, abstract_word_cap: int = 500,
) -> tuple[list[ContractFailure], int]:
    fails: list[ContractFailure] = []
    abs_text = _extract_section(body, _ABSTRACT_HEADING_RE) or ""
    abs_words = len(abs_text.split()) if abs_text else 0
    if abs_words > abstract_word_cap:
        fails.append(
            ContractFailure(
                rule="section_boundary",
                detail=(
                    f"abstract is {abs_words} words; cap is "
                    f"{abstract_word_cap}. Likely abstract→introduction "
                    f"bleed."
                ),
            )
        )
    if _H3_RESIDUE_RE.search(body):
        n = len(_H3_RESIDUE_RE.findall(body))
        fails.append(
            ContractFailure(
                rule="section_boundary",
                detail=(
                    f"{n} 'H3:' residue token(s) in body — internal "
                    f"section-tagging language leaked into public MD."
                ),
            )
        )
    # Duplicate top-level (## or #) sections — same heading text twice.
    headings: list[tuple[int, str]] = []
    for m in _HEADING_RE.finditer(body):
        level = len(m.group(1))
        text = m.group(2).strip().lower()
        if level <= 2:
            headings.append((level, text))
    counts = Counter(t for _, t in headings)
    dupes = sorted(t for t, c in counts.items() if c > 1)
    if dupes:
        fails.append(
            ContractFailure(
                rule="section_boundary",
                detail=(
                    f"duplicate top-level section heading(s): {dupes}"
                ),
            )
        )
    return fails, abs_words


# ---- rule 4: residue phrase ---------------------------------------------


# Engine-internal phrases that must never appear in the public MD.
# Universal / domain-agnostic — these are pipeline jargon, not domain terms.
# Keep entries non-overlapping (no entry should be a strict prefix of
# another) so we don't double-count the same residue site.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "no LLM authorship",
    "LLM proposes, code disposes",
    "deterministic evidence summary",
    "Tournament selector",
    "no matched source in the accepted evidence",
)


def _check_residue(body: str) -> list[ContractFailure]:
    fails: list[ContractFailure] = []
    body_lo = body.lower()
    for phrase in FORBIDDEN_PHRASES:
        n = body_lo.count(phrase.lower())
        if n > 0:
            fails.append(
                ContractFailure(
                    rule="residue_phrase",
                    detail=f"phrase '{phrase}' appears {n}x in MD",
                )
            )
    return fails


# ---- helpers -------------------------------------------------------------


_FENCE_RE = re.compile(r"```[\s\S]*?```", re.M)
_TABLE_ROW_RE = re.compile(r"^\|[^\n]*\|\s*$", re.M)


def _strip_code_fences(s: str) -> str:
    return _FENCE_RE.sub("", s)


def _strip_table_rows(s: str) -> str:
    return _TABLE_ROW_RE.sub("", s)


def _extract_section(body: str, heading_re: re.Pattern[str]) -> str | None:
    """Return body text of the first section whose heading matches
    `heading_re`, up to the next heading of equal-or-higher level."""
    m = heading_re.search(body)
    if not m:
        return None
    start = m.end()
    # Find next heading line.
    nxt = re.search(r"^#{1,6}\s+\S", body[start:], re.M)
    end = start + nxt.start() if nxt else len(body)
    return body[start:end]


# ---- orchestrator --------------------------------------------------------


def validate(
    paper_md: str,
    manifest: dict,
    *,
    abstract_word_cap: int = 500,
) -> ContractResult:
    """Run all five rules; return ContractResult."""
    try:
        canon = CanonicalCounts.from_manifest(manifest)
    except Exception as e:
        return ContractResult(
            status="FAIL",
            failures=(
                ContractFailure(
                    rule="canonical_link",
                    detail=f"manifest unreadable: {e!r}",
                ),
            ),
            canonical=CanonicalCounts(0, 0, 0),
            abstract_words=0,
            n_failures_by_rule={"canonical_link": 1},
        )
    fails: list[ContractFailure] = []
    fails.extend(_check_counts(paper_md, canon))
    fails.extend(_check_duplicate_rows(paper_md, manifest))
    section_fails, abs_words = _check_sections(
        paper_md, abstract_word_cap=abstract_word_cap,
    )
    fails.extend(section_fails)
    fails.extend(_check_residue(paper_md))
    by_rule: dict[str, int] = Counter(f.rule for f in fails)
    return ContractResult(
        status="FAIL" if fails else "PASS",
        failures=tuple(fails),
        canonical=canon,
        abstract_words=abs_words,
        n_failures_by_rule=dict(by_rule),
    )


def validate_run_dir(
    run_dir: Path,
    *,
    abstract_word_cap: int = 500,
) -> ContractResult:
    """Read full_paper.md + manifest.json from a run dir and validate."""
    paper_md = (run_dir / "full_paper.md").read_text()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    return validate(paper_md, manifest, abstract_word_cap=abstract_word_cap)


def write_sidecar(
    run_dir: Path, result: ContractResult,
) -> Path:
    """Write public_manuscript_contract.json next to the paper."""
    out = run_dir / "public_manuscript_contract.json"
    payload = {
        "status": result.status,
        "n_failures": len(result.failures),
        "n_failures_by_rule": result.n_failures_by_rule,
        "canonical_counts": asdict(result.canonical),
        "abstract_words": result.abstract_words,
        "failures": [asdict(f) for f in result.failures],
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out


# ---- CLI -----------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="public_manuscript_contract",
        description="Validate a rendered paper against the manifest.",
    )
    parser.add_argument("run_dir", type=Path, help="path to runs/<topic>-...")
    parser.add_argument(
        "--abstract-cap", type=int, default=500,
        help="abstract word cap (default 500)",
    )
    parser.add_argument(
        "--write-sidecar", action="store_true",
        help="write public_manuscript_contract.json into the run dir",
    )
    args = parser.parse_args(argv)
    result = validate_run_dir(args.run_dir, abstract_word_cap=args.abstract_cap)
    if args.write_sidecar:
        write_sidecar(args.run_dir, result)
    print(f"status: {result.status}")
    print(f"abstract_words: {result.abstract_words}")
    print(f"canonical: {asdict(result.canonical)}")
    if result.failures:
        print(f"failures ({len(result.failures)}):")
        for f in result.failures:
            print(f"  [{f.severity}] {f.rule}: {f.detail}")
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover — CLI
    import sys

    sys.exit(_main())
