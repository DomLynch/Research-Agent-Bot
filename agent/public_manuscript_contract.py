"""Public-manuscript contract — final-render gate; stdlib-only."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Mapping

from agent.public_manuscript_table_contract import (
    conclusion_faults,
    metadata_conflicts,
    section_outcome_failures,
    table_set_failures,
    tension_fault_counts,
)


# ---- canonical counts ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalCounts:
    source_papers: int           # n_receipts (total screened)
    accepted_papers: int         # n_accepted_receipts (post-SPAR)
    rejected_papers: int         # n_quarantined_receipts / SPAR rejects
    high_confidence_claims: int
    tensions: int
    accepted_publications: int   # unique accepted citation_tokens

    @classmethod
    def from_manifest(
        cls,
        manifest: dict,
        rejected_verdicts: Mapping[str, str] | None = None,
    ) -> "CanonicalCounts":
        n_total = int(manifest.get("n_receipts") or 0)
        # Fall back to total if dual-count fields missing (legacy runs).
        n_acc = int(
            manifest.get("n_accepted_receipts")
            or manifest.get("n_receipts")
            or 0
        )
        n_rej = int(
            manifest.get("n_quarantined_receipts")
            or max(n_total - n_acc, 0)
        )
        receipts = [
            r for r in (manifest.get("receipts") or ())
            if isinstance(r, dict)
        ]
        if rejected_verdicts is not None:
            accepted_receipts = [
                r for r in receipts
                if str(r.get("receipt_id") or "") not in rejected_verdicts
            ]
            n_rej = len(rejected_verdicts)
            n_acc = len(accepted_receipts) or n_acc
        else:
            accepted_receipts = receipts
        accepted_cites = {
            str(r.get("citation_token") or "").strip()
            for r in accepted_receipts
            if str(r.get("citation_token") or "").strip()
        }
        return cls(
            source_papers=n_total,
            accepted_papers=n_acc,
            rejected_papers=n_rej,
            high_confidence_claims=int(
                manifest.get("n_high_confidence_claims_total") or 0
            ),
            tensions=int(manifest.get("n_non_orthogonal_tensions") or 0),
            accepted_publications=len(accepted_cites) or n_acc,
        )


# ---- failure record ------------------------------------------------------


_RULES = (
    "count_consistency",
    "duplicate_row",
    "section_boundary",
    "residue_phrase",
    "canonical_link",
    "broken_prose",
    "repeated_boilerplate",
    "spar_reject_leakage",
    "rejected_appendix_required",
    "qei_title_row_mismatch",
    "reference_duplicates",
    "malformed_table_row",
    "table_count_consistency",
    "evidence_role_count_consistency",
    "section_outcome_integrity",
    "table_set_consistency",
    "cross_table_metadata_conflict",
    "tension_table_integrity",
    "conclusion_hygiene",
)
_RuleName = Literal[
    "count_consistency",
    "duplicate_row",
    "section_boundary",
    "residue_phrase",
    "canonical_link",
    "broken_prose",
    "repeated_boilerplate",
    "spar_reject_leakage",
    "rejected_appendix_required",
    "qei_title_row_mismatch",
    "reference_duplicates",
    "malformed_table_row",
    "table_count_consistency",
    "evidence_role_count_consistency",
    "section_outcome_integrity",
    "table_set_consistency",
    "cross_table_metadata_conflict",
    "tension_table_integrity",
    "conclusion_hygiene",
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


_COUNT_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b(\d{1,4})\s+(?:candidate|source|screened|parsed)\s+"
            r"(?:receipt\s+)?(?:papers?|stud(?:y|ies)|receipts?)\b",
            re.I,
        ),
        "source paper",
        "source_papers",
    ),
    (
        re.compile(
            r"\b(\d{1,4})\s+source\s+papers?\s+screened\b",
            re.I,
        ),
        "source paper",
        "source_papers",
    ),
    (
        re.compile(
            r"\b(\d{1,4})\s+(?:accepted|curated|included|contributing)"
            r"(?:\s*/\s*(?:accepted|curated|included|contributing))*\s+"
            r"(?:high[- ]confidence\s+)?(?:receipt\s+)?"
            r"(?:papers?|stud(?:y|ies)|receipts?|reference\s+papers?)\b",
            re.I,
        ),
        "accepted paper",
        "accepted_papers",
    ),
    (
        re.compile(
            r"\b(\d{1,4})\s+(?:papers?|receipts?|stud(?:y|ies))\s+"
            r"(?:entered|entering|included\s+in)\s+(?:the\s+)?synthesis\b",
            re.I,
        ),
        "accepted paper",
        "accepted_papers",
    ),
    (
        re.compile(
            r"\b(\d{1,4})\s+(?:rejected|quarantined|contested)\s+"
            r"(?:receipt\s+)?(?:papers?|stud(?:y|ies)|receipts?)\b",
            re.I,
        ),
        "rejected paper",
        "rejected_papers",
    ),
    (
        re.compile(
            r"\b(\d{1,4})\s+"
            r"(?:reference\s+papers?|stud(?:y|ies)|papers?)\b",
            re.I,
        ),
        "generic paper",
        "source_or_accepted",
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
_COUNT_NOISE_PREFIX_RE = re.compile(
    r"(?:severity|priority|score|grade|tier)[-\s]*$|(?:\b[kn]\s*=\s*)$",
    re.I,
)


def _is_year_token(n: int) -> bool:
    return 1900 <= n <= 2100


def _check_counts(
    body: str, canon: CanonicalCounts,
) -> list[ContractFailure]:
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
            prefix = body_clean[max(0, m.start() - 24):m.start()]
            if (
                _is_year_token(n)
                or n < _NOISE_THRESHOLD
                or _COUNT_NOISE_PREFIX_RE.search(prefix)
            ):
                continue
            seen[cat].add(n)
    for cat, attrs in (
        ("source paper", ("source_papers",)),
        ("accepted paper", ("accepted_papers",)),
        ("rejected paper", ("rejected_papers",)),
        ("generic paper", ("source_papers", "accepted_papers")),
        ("claim", ("high_confidence_claims",)),
        ("tension", ("tensions",)),
    ):
        valid_canonicals = {
            getattr(canon, a) for a in attrs if getattr(canon, a) > 0
        }
        if not valid_canonicals:
            continue
        bad = sorted(
            n for n in seen.get(cat, set()) if n not in valid_canonicals
        )
        if bad:
            fails.append(
                ContractFailure(
                    rule="count_consistency",
                    detail=(
                        f"{cat} count(s) {bad} in MD match neither total "
                        f"({sorted(valid_canonicals)}) — likely stale or "
                        f"hallucinated count."
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
    r"^\s*\|\s*([A-Za-z0-9][A-Za-z0-9\-']*(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)"
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
            r"^([A-Za-z0-9][A-Za-z0-9\-']*(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)",
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


def _check_table_row_counts(
    body: str,
    canon: CanonicalCounts,
) -> list[ContractFailure]:
    expected = canon.accepted_publications or canon.accepted_papers
    if expected <= 0:
        return []
    section = _extract_section(body, _INCLUDED_HEADING_RE)
    if not section:
        return []
    rows = _CITATION_TOKEN_RE.findall(section)
    if not rows or len(rows) == expected:
        return []
    return [
        ContractFailure(
            rule="table_count_consistency",
            detail=(
                f"Table 1 renders {len(rows)} included-study row(s), "
                f"but post-SPAR evidence state expects {expected} unique "
                f"accepted citation token(s). Public tables must derive "
                f"from accepted evidence only."
            ),
        )
    ]


def _check_table_set_consistency(body: str) -> list[ContractFailure]:
    missing = table_set_failures(body)
    if not missing:
        return []
    return [ContractFailure(
        rule="table_set_consistency",
        detail=f"{len(missing)} citation(s) appear in evidence tables but are absent from Table 1: {missing[:8]}.",
    )]


def _check_cross_table_metadata_conflict(body: str) -> list[ContractFailure]:
    conflicts = metadata_conflicts(body)
    if not conflicts:
        return []
    return [ContractFailure(
        rule="cross_table_metadata_conflict",
        detail=(
            f"{len(conflicts)} cross-table metadata conflict(s): "
            f"{conflicts[:5]}. A citation cannot carry different "
            f"tier/directness labels across public tables."
        ),
    )]


def _check_tension_table_integrity(body: str) -> list[ContractFailure]:
    self_pairs, dupes = tension_fault_counts(body)
    if not self_pairs and not dupes:
        return []
    return [ContractFailure(
        rule="tension_table_integrity",
        detail=f"Table 3 contains {self_pairs} self-pair(s) and {dupes} duplicate pair(s).",
    )]


_ROLE_COUNT_RE = re.compile(
    r"\b(\d{1,4})\s+direct\s+clinical\s+receipt\(s\),\s*"
    r"(\d{1,4})\s+indirect\s+clinical\s+receipt\(s\),\s*and\s*"
    r"(\d{1,4})\s+mechanistic\s+or\s+model-system\s+receipt\(s\)",
    re.I,
)


def _accepted_receipts_from_manifest(
    manifest: dict,
    rejected_verdicts: Mapping[str, str] | None = None,
) -> list[dict]:
    receipts = [
        r for r in (manifest.get("receipts") or ())
        if isinstance(r, dict)
    ]
    if rejected_verdicts is not None:
        return [
            r for r in receipts
            if str(r.get("receipt_id") or "") not in rejected_verdicts
        ]
    return [
        r for r in receipts
        if str(r.get("spar_verdict") or "accept_clean").startswith("accept")
    ]


def _check_evidence_role_counts(
    body: str,
    manifest: dict,
    rejected_verdicts: Mapping[str, str] | None = None,
) -> list[ContractFailure]:
    accepted = _accepted_receipts_from_manifest(manifest, rejected_verdicts)
    if not accepted:
        return []
    expected = Counter(
        str(r.get("directness") or "").lower() for r in accepted
    )
    failures: list[ContractFailure] = []
    for m in _ROLE_COUNT_RE.finditer(body):
        observed = {
            "direct": int(m.group(1)),
            "indirect": int(m.group(2)),
            "mechanistic": int(m.group(3)),
        }
        wanted = {
            "direct": expected.get("direct", 0),
            "indirect": expected.get("indirect", 0),
            "mechanistic": expected.get("mechanistic", 0),
        }
        if observed != wanted:
            failures.append(ContractFailure(
                rule="evidence_role_count_consistency",
                detail=(
                    f"evidence-role count {observed} does not match "
                    f"post-SPAR accepted receipts {wanted}."
                ),
            ))
    return failures


_APPENDIX_DIST_RE = re.compile(r"\*\*(Evidence tier|Directness|Outcome-class) distribution:\*\*.*?\|[^\n]*Count[^\n]*\|\n\|[-|: ]+\|\n(?P<rows>(?:\|[^\n]*\|\n)+)", re.I | re.S)


def _check_appendix_distribution_counts(body: str, canon: CanonicalCounts) -> list[ContractFailure]:
    if canon.accepted_papers <= 0:
        return []
    return [
        ContractFailure("evidence_role_count_consistency", f"{m.group(1)} distribution totals {n}, but post-SPAR accepted receipts total {canon.accepted_papers}.")
        for m in _APPENDIX_DIST_RE.finditer(body)
        for nums in ([int(x) for x in re.findall(r"\|\s*(\d+)\s*\|$", m.group("rows"), re.M)],)
        if (n := sum(nums)) and n != canon.accepted_papers
    ]


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
    "no LLM authorship", "LLM proposes, code disposes", "deterministic evidence summary",
    "Tournament selector", "Selected thesis:", "no matched source in the accepted evidence",
    "source-context sentence", "unsupported sentence", "Researka-Certified", "A2A-AAA",
    "Grok", "certification tolerances", "In the Conclusion, this framing",
    "In the Limitations, this framing", "The surviving section therefore",
    "source passage cannot support its own specificity", "Cochrane RoB-2", "ROBINS-I",
    "risk-of-bias roll-up",
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


# ---- rule 7: broken prose -----------------------------------------------


# Domain-agnostic semantic-gibberish patterns. None of these encode
# biomedical jargon — they detect English-language broken constructions
# (truncations, value/unit-as-effect mismatches) that would be a
# manuscript fail in any field.
_BROKEN_PROSE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # "but was <single-word>." — likely a truncated coordinator
    # ("X was not associated with mortality but was mortality"). Flag a
    # single word right after "but was" terminating a sentence.
    (
        re.compile(r"\bbut\s+was\s+\w+\s*[,.]\s+[A-Z]", re.I),
        "truncated 'but was <word>' construction",
    ),
    # "effect estimate of <year>" — a 4-digit year cannot be an effect.
    (
        re.compile(r"\beffect\s+estimate\s+of\s+(\d{4})\b", re.I),
        "year-as-effect-estimate",
    ),
    # "effect estimate of <number><unit>" where the unit is a dose unit
    # (mg/kg/ml/etc.) — that's a dose, not an effect estimate.
    (
        re.compile(
            r"\beffect\s+estimate\s+of\s+\d+(?:\.\d+)?\s*"
            r"(?:mg|kg|ml|µg|mcg|nmol|mmol|L|g)\b",
            re.I,
        ),
        "dose-as-effect-estimate",
    ),
    # "effect estimate of <N> years/months/days/etc." — that's a duration,
    # not an effect estimate.
    (
        re.compile(
            r"\beffect\s+estimate\s+of\s+\d+(?:\.\d+)?\s+"
            r"(?:years?|months?|days?|hours?|weeks?)\b",
            re.I,
        ),
        "duration-as-effect-estimate",
    ),
    # "reported an effect estimate." — sentence-terminated without a
    # value. The phrase is incomplete prose.
    (
        re.compile(
            r"\breported\s+an\s+effect\s+estimate\.\s+[A-Z]", re.I,
        ),
        "truncated 'reported an effect estimate.' (no value)",
    ),
    (
        re.compile(r"\bsingle\s*\.\s*When\s+a\s+cannot\b", re.I),
        "broken floor-backfill fragment 'single . When a cannot'",
    ),
)


def _check_broken_prose(body: str) -> list[ContractFailure]:
    fails: list[ContractFailure] = []
    body_clean = _strip_code_fences(body)
    for pat, desc in _BROKEN_PROSE_PATTERNS:
        n = len(pat.findall(body_clean))
        if n > 0:
            fails.append(
                ContractFailure(
                    rule="broken_prose",
                    detail=f"{desc} appears {n}x in MD",
                )
            )
    return fails


# ---- rule 8: repeated boilerplate ---------------------------------------


_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+[^\n]*$", re.M)


def _check_repeated_boilerplate(
    body: str, *, min_words: int = 8, max_repeats: int = 2,
) -> list[ContractFailure]:
    body_clean = _strip_code_fences(_strip_table_rows(body))
    # Strip Markdown heading lines so headings don't get glued onto the
    # following sentence by the splitter (otherwise "## A\\n\\nFoo." and
    # "## B\\n\\nFoo." would normalise to different strings even though
    # the sentence body 'Foo.' is identical).
    body_clean = _HEADING_LINE_RE.sub("", body_clean)
    # Split on either sentence-end punctuation followed by whitespace,
    # OR a blank-line paragraph break. Both are universal cues.
    sents = re.split(r"(?<=[.!?])\s+|\n\s*\n", body_clean)
    counts: Counter[str] = Counter()
    for s in sents:
        norm = re.sub(r"\s+", " ", s.strip())
        if len(norm.split()) < min_words:
            continue
        if not re.search(r"[a-zA-Z]", norm):
            continue
        counts[norm] += 1
    fails: list[ContractFailure] = []
    for sent, n in counts.most_common(10):
        if n > max_repeats:
            preview = sent[:100] + ("..." if len(sent) > 100 else "")
            fails.append(
                ContractFailure(
                    rule="repeated_boilerplate",
                    detail=f"sentence repeated {n}x: '{preview}'",
                )
            )
    return fails


# ---- rule 9: SPAR reject leakage ----------------------------------------


# Wave 22 trust-spine enforcement: rejected receipts must NEVER appear
# anywhere in the public MD except the dedicated 'Rejected / Contested
# Evidence' quarantine appendix. This includes ALL main evidence tables
# (Included Studies, QEI, RoB, Cross-Domain Tensions). Universal: same
# heading across all topics. The contract excises the quarantine section
# from the scan window, then any reject citation remaining is a fail.
_QUARANTINE_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:Rejected\s*/?\s*Contested\s+Evidence|"
    r"Quarantined\s+Evidence|Quarantined\s+Receipts)\b[^\n]*\n",
    re.I | re.M,
)


def _excise_quarantine_section(body: str) -> str:
    m = _QUARANTINE_HEADING_RE.search(body)
    if not m:
        return body
    start = m.start()
    nxt = re.search(r"^#{1,4}\s+\S", body[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(body)
    return body[:start] + body[end:]


# Wave 25: References is audit-only — it lists every receipt with
# explicit [accepted] / [QUARANTINED] verdict tags (per
# build_references_full_section). Including a rejected citation there
# is part of trust-spine transparency, not an evidence claim. The leak
# scan must skip it. Universal — every topic uses the same References
# format.
_REFERENCES_HEADING_RE_C = re.compile(
    r"^(##\s+References\b[^\n]*\n)", re.I | re.M,
)


def _excise_references_section(body: str) -> str:
    m = _REFERENCES_HEADING_RE_C.search(body)
    if not m:
        return body
    start = m.start()
    nxt = re.search(r"^##\s+\S", body[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(body)
    return body[:start] + body[end:]


def _load_spar_cache(run_dir: Path | None) -> dict[str, str] | None:
    if run_dir is None:
        return None
    cache_path = run_dir / "spar_cache.json"
    if not cache_path.is_file():
        return None
    try:
        raw = json.loads(cache_path.read_text())
    except (OSError, ValueError):
        return None
    verdicts = raw.get("verdicts") or {}
    out: dict[str, str] = {}
    for rid, v in verdicts.items():
        if not isinstance(v, dict):
            continue
        verdict = (v.get("verdict") or "").lower()
        if verdict.startswith("reject"):
            out[rid] = verdict
    return out


def _check_spar_reject_leakage(
    body: str,
    manifest: dict,
    run_dir: Path | None,
) -> list[ContractFailure]:
    rejected = _load_spar_cache(run_dir)
    if not rejected:
        return []
    # Map rejected receipt_ids → citation_tokens via the manifest.
    receipts = manifest.get("receipts") or ()
    rejected_cites: dict[str, str] = {}
    for r in receipts:
        if not isinstance(r, dict):
            continue
        rid = r.get("receipt_id")
        cite = (r.get("citation_token") or "").strip()
        if rid in rejected and cite:
            rejected_cites[cite] = rejected[rid]
    if not rejected_cites:
        return []
    # Excise the Rejected / Contested Evidence quarantine zone AND the
    # References section. References is the audit trail (every receipt
    # listed with verdict tag — quarantined entries are legitimate
    # there, not evidence claims). Universal — every topic uses the
    # same References + Rejected / Contested Evidence headings.
    main_paper = _excise_references_section(
        _excise_quarantine_section(body)
    )
    fails: list[ContractFailure] = []
    leak_counts: dict[str, int] = {}
    for cite, verdict in rejected_cites.items():
        n = len(re.findall(r"\b" + re.escape(cite) + r"\b", main_paper))
        if n > 0:
            leak_counts[f"{cite} [{verdict}]"] = n
    if leak_counts:
        # One failure per unique citation so each leak is auditable.
        for label, n in sorted(leak_counts.items()):
            fails.append(
                ContractFailure(
                    rule="spar_reject_leakage",
                    detail=(
                        f"SPAR-rejected citation '{label}' appears {n}x in "
                        f"the main paper (prose or evidence tables) outside "
                        f"the Rejected / Contested Evidence quarantine zone. "
                        f"cite it as evidence — the only legitimate "
                        f"surface is the quarantine appendix."
                    ),
                )
            )
    return fails


# ---- rule 10: rejected appendix required ---------------------------------


def _check_rejected_appendix_required(
    body: str,
    run_dir: Path | None,
) -> list[ContractFailure]:
    rejected = _load_spar_cache(run_dir)
    if not rejected:
        return []
    if _QUARANTINE_HEADING_RE.search(body):
        return []
    return [
        ContractFailure(
            rule="rejected_appendix_required",
            detail=(
                f"{len(rejected)} SPAR-rejected receipt(s) exist for this "
                f"run but the public MD has no 'Rejected / Contested "
                f"Evidence' quarantine section. Trust-spine ordering "
                f"requires every reject to be listed transparently."
            ),
        )
    ]


# ---- rule 11: QEI title row-count mismatch ------------------------------


_QEI_HEADING_RE_C = re.compile(
    r"^##\s+Quantitative\s+Evidence\s+Index[^\n]*\n", re.I | re.M,
)
# `\b` doesn't match the `_Top` boundary in markdown italics because
# `_` is a word character in Python regex. Plain match is sufficient.
_TOP_N_RE_C = re.compile(r"Top\s+(\d+)", re.I)
_QEI_DATA_ROW_RE = re.compile(
    r"^\s*\|\s*[A-Za-z0-9][A-Za-z0-9\-']*(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}",
)


def _check_qei_title_row_mismatch(body: str) -> list[ContractFailure]:
    m = _QEI_HEADING_RE_C.search(body)
    if not m:
        return []
    start = m.end()
    nxt = re.search(r"^##\s+\S", body[start:], re.M)
    end = start + nxt.start() if nxt else len(body)
    section = body[start:end]
    title_m = _TOP_N_RE_C.search(section)
    if not title_m:
        return []
    claimed = int(title_m.group(1))
    actual = sum(
        1 for line in section.split("\n") if _QEI_DATA_ROW_RE.match(line)
    )
    if actual == 0 or claimed == actual:
        return []
    return [
        ContractFailure(
            rule="qei_title_row_mismatch",
            detail=(
                f"QEI title says 'Top {claimed}' but the table contains "
                f"{actual} data rows. Title and content must agree."
            ),
        )
    ]


# ---- rule 12: References section duplicates -----------------------------


def _check_reference_duplicates(body: str) -> list[ContractFailure]:
    m = _REFERENCES_HEADING_RE_C.search(body)
    if not m:
        return []
    start = m.end()
    nxt = re.search(r"^##\s+\S", body[start:], re.M)
    end = start + nxt.start() if nxt else len(body)
    section = body[start:end]
    cites: list[str] = []
    for line in section.split("\n"):
        m2 = re.match(
            r"^\s*[-*]\s*\*\*([A-Za-z0-9][A-Za-z0-9\-']*(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)\.?\*\*",
            line,
        )
        if m2:
            cites.append(m2.group(1).strip())
    counts = Counter(cites)
    dupes = sorted(c for c, n in counts.items() if n > 1)
    if not dupes:
        return []
    return [
        ContractFailure(
            rule="reference_duplicates",
            detail=(
                f"References section lists {len(dupes)} citation(s) "
                f"more than once: {dupes[:5]}. Same paper retrieved under "
                f"different identifiers must be merged to a single "
                f"bibliography entry."
            ),
        )
    ]


# ---- rule 13: malformed markdown table rows -----------------------------


_ORPHAN_TABLE_FRAGMENT_RE = re.compile(
    r"(?m)^[ \t]*[A-Za-z0-9]{1,8}[ \t]*\|[^\n]*\|[ \t]*$",
)


def _check_malformed_table_rows(body: str) -> list[ContractFailure]:
    hits = _ORPHAN_TABLE_FRAGMENT_RE.findall(body)
    if not hits:
        return []
    return [
        ContractFailure(
            rule="malformed_table_row",
            detail=(
                f"{len(hits)} orphan table row fragment(s) appear without "
                f"a leading pipe; markdown tables must render complete rows."
            ),
        )
    ]


def _check_section_outcome_integrity(
    body: str,
    manifest: dict,
    rejected_verdicts: Mapping[str, str] | None = None,
) -> list[ContractFailure]:
    accepted = _accepted_receipts_from_manifest(manifest, rejected_verdicts)
    return [
        ContractFailure(
            rule="section_outcome_integrity",
            detail=(
                f"{msg} Outcome subsections must be fed by matching "
                f"evidence packets."
            ),
        )
        for msg in section_outcome_failures(body, accepted)
    ]


# ---- rule 15: conclusion hygiene ----------------------------------------


def _check_conclusion_hygiene(body: str) -> list[ContractFailure]:
    hits, subheads = conclusion_faults(body)
    failures: list[ContractFailure] = []
    if hits:
        failures.append(ContractFailure(
            rule="conclusion_hygiene",
            detail=f"Conclusion contains contribution/table boilerplate: {hits[:8]}.",
        ))
    if subheads:
        failures.append(ContractFailure(
            rule="conclusion_hygiene",
            detail=f"Conclusion contains subsection heading(s): {subheads[:5]}.",
        ))
    return failures


# ---- helpers -------------------------------------------------------------


_FENCE_RE = re.compile(r"```[\s\S]*?```", re.M)
_TABLE_ROW_RE = re.compile(r"^\|[^\n]*\|\s*$", re.M)


def _strip_code_fences(s: str) -> str:
    return _FENCE_RE.sub("", s)


def _strip_table_rows(s: str) -> str:
    return _TABLE_ROW_RE.sub("", s)


def _extract_section(body: str, heading_re: re.Pattern[str]) -> str | None:
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
    run_dir: Path | None = None,
) -> ContractResult:
    try:
        rejected_verdicts = _load_spar_cache(run_dir)
        canon = CanonicalCounts.from_manifest(manifest, rejected_verdicts)
    except Exception as e:
        return ContractResult(
            status="FAIL",
            failures=(
                ContractFailure(
                    rule="canonical_link",
                    detail=f"manifest unreadable: {e!r}",
                ),
            ),
            canonical=CanonicalCounts(0, 0, 0, 0, 0, 0),
            abstract_words=0,
            n_failures_by_rule={"canonical_link": 1},
        )
    fails: list[ContractFailure] = []
    fails.extend(_check_counts(paper_md, canon))
    fails.extend(_check_duplicate_rows(paper_md, manifest))
    fails.extend(_check_table_row_counts(paper_md, canon))
    fails.extend(_check_table_set_consistency(paper_md))
    fails.extend(_check_cross_table_metadata_conflict(paper_md))
    fails.extend(_check_tension_table_integrity(paper_md))
    fails.extend(_check_evidence_role_counts(
        paper_md, manifest, rejected_verdicts,
    ))
    fails.extend(_check_appendix_distribution_counts(paper_md, canon))
    fails.extend(_check_section_outcome_integrity(
        paper_md, manifest, rejected_verdicts,
    ))
    section_fails, abs_words = _check_sections(
        paper_md, abstract_word_cap=abstract_word_cap,
    )
    fails.extend(section_fails)
    fails.extend(_check_residue(paper_md))
    fails.extend(_check_broken_prose(paper_md))
    fails.extend(_check_repeated_boilerplate(paper_md))
    fails.extend(_check_spar_reject_leakage(paper_md, manifest, run_dir))
    fails.extend(_check_rejected_appendix_required(paper_md, run_dir))
    fails.extend(_check_qei_title_row_mismatch(paper_md))
    fails.extend(_check_reference_duplicates(paper_md))
    fails.extend(_check_malformed_table_rows(paper_md))
    fails.extend(_check_conclusion_hygiene(paper_md))
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
    try:
        paper_md = (run_dir / "full_paper.md").read_text()
        manifest = json.loads((run_dir / "manifest.json").read_text())
        if not isinstance(manifest, dict):
            raise ValueError("manifest root is not an object")
    except Exception as e:
        failure = ContractFailure(
            rule="canonical_link",
            detail=f"run_dir unreadable or malformed: {e!r}",
        )
        return ContractResult(
            status="FAIL", failures=(failure,),
            canonical=CanonicalCounts(0, 0, 0, 0, 0, 0),
            abstract_words=0, n_failures_by_rule={"canonical_link": 1},
        )
    return validate(
        paper_md, manifest, abstract_word_cap=abstract_word_cap,
        run_dir=run_dir,
    )


def write_sidecar(
    run_dir: Path, result: ContractResult,
) -> Path:
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
