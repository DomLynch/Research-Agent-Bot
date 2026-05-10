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
from typing import Literal, Mapping


# ---- canonical counts ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalCounts:
    """Post-SPAR public evidence state for paper-wide totals.

    Raw candidates can describe screening. Accepted receipts/citations
    describe public synthesis. Rejected receipts can appear only in the
    quarantine appendix/References. Universal — every topic uses the
    same manifest + SPAR cache surfaces."""

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
    "wrong_topic_residue",
    "broken_prose",
    "repeated_boilerplate",
    "spar_reject_leakage",
    "rejected_appendix_required",
    "qei_title_row_mismatch",
    "reference_duplicates",
    "table_count_consistency",
)
_RuleName = Literal[
    "count_consistency",
    "duplicate_row",
    "section_boundary",
    "residue_phrase",
    "canonical_link",
    "wrong_topic_residue",
    "broken_prose",
    "repeated_boilerplate",
    "spar_reject_leakage",
    "rejected_appendix_required",
    "qei_title_row_mismatch",
    "reference_duplicates",
    "table_count_consistency",
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


def _check_table_row_counts(
    body: str,
    canon: CanonicalCounts,
) -> list[ContractFailure]:
    """Table 1 must render the public accepted-study surface.

    The expected count is unique accepted citation_tokens, not raw
    accepted receipts: one paper can legitimately contribute multiple
    accepted receipts. Universal — manifest/SPAR state defines the
    expected public row count for every topic.
    """
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
    "Selected thesis:",
    "no matched source in the accepted evidence",
    "source-context sentence",
    "unsupported sentence",
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


# ---- rule 6: wrong-topic residue ----------------------------------------


# Universal: enumerate platform topics from topic_packs/*.toml at runtime.
# Adding a new topic requires no code change — drop a .toml in topic_packs/.
def _list_known_topics(repo_root: Path | None) -> tuple[str, ...]:
    if repo_root is None:
        return ()
    pack_dir = repo_root / "topic_packs"
    if not pack_dir.is_dir():
        return ()
    return tuple(
        sorted(
            p.stem for p in pack_dir.glob("*.toml")
            if not p.stem.startswith("_")
        )
    )


# Evidence-noun anchors that, when a sibling topic precedes them, signal
# a wrong-topic claim assertion. Domain-agnostic: these nouns describe
# any kind of empirical work (biomedical / climate / materials / etc.).
_EVIDENCE_NOUNS = (
    "evidence", "study", "studies", "trial", "trials",
    "effect", "effects", "finding", "findings",
    "data", "research", "literature",
)
_ASSERT_VERBS = (
    "should", "must", "can", "may", "will",
    "is", "are", "was", "were", "need",
)


def _check_wrong_topic_residue(
    body: str,
    manifest: dict,
    repo_root: Path | None,
) -> list[ContractFailure]:
    """Universal sibling-topic detector.

    A paper whose `manifest['topic']` is X must not contain claim-asserting
    sentences about a different platform topic Y (e.g. metformin paper
    asserting "rapamycin evidence should be interpreted ..."). The list of
    sibling topics is auto-derived from `topic_packs/*.toml` so adding a
    new topic does not require code changes.
    """
    own_topic = (manifest.get("topic") or "").strip().lower()
    if not own_topic:
        return []
    siblings = [
        t for t in _list_known_topics(repo_root)
        if t.lower() != own_topic and t.lower() not in own_topic
        and own_topic not in t.lower()
    ]
    if not siblings:
        return []
    nouns = "|".join(_EVIDENCE_NOUNS)
    verbs = "|".join(_ASSERT_VERBS)
    fails: list[ContractFailure] = []
    for sib in siblings:
        # "<sibling>\\s+<evidence-noun>\\b ... \\b<assert-verb>\\b" within 80
        # chars. Word-boundary on the sibling so 'rapamycin' does not match
        # inside 'rapamycin_clinical_brief' citations.
        pat = re.compile(
            rf"\b{re.escape(sib)}\b\s+(?:{nouns})\b[\s\S]{{0,80}}\b"
            rf"(?:{verbs})\b",
            re.I,
        )
        n = len(pat.findall(body))
        if n > 0:
            fails.append(
                ContractFailure(
                    rule="wrong_topic_residue",
                    detail=(
                        f"sibling-topic '{sib}' appears in {n} claim-"
                        f"asserting context(s) inside a '{own_topic}' "
                        f"paper. Likely cross-topic prose leak from a "
                        f"shared template or stale corpus context."
                    ),
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
    """Universal sentence-frequency check.

    Any substantive sentence (>= min_words) appearing more than max_repeats
    times is template residue. Catches "Translational relevance to humans
    remains uncertain" without hardcoding the phrase — the test is
    structural (a writer who keeps emitting the same boilerplate hedge),
    not lexical. Domain-agnostic.
    """
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
    """Return body with the 'Rejected / Contested Evidence' section
    removed. Anything outside that section is the 'main paper' for
    leak-detection purposes."""
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
    """Return {receipt_id: verdict} for rejected receipts, or None if
    no spar_cache.json exists. Universal — works for any topic since
    the cache schema is identical across runs."""
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
    """Wave 22 trust-spine: block AAA when SPAR-rejected receipts appear
    ANYWHERE in the public MD outside the dedicated 'Rejected /
    Contested Evidence' quarantine appendix. This includes evidence
    prose (Discussion / Conclusion / Results / Synthesis / Tensions)
    AND main evidence tables (Included Studies / QEI / RoB / Per-Study
    Endpoint / Cross-Domain Tensions). Universal — uses the manifest
    citation_token mapping plus spar_cache.json (identical schema across
    topics). No domain assumptions.
    """
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
    """Wave 22 trust-spine: when SPAR rejected ≥1 receipt, the public MD
    must contain a 'Rejected / Contested Evidence' (or equivalent
    quarantine) section. Universal — applies to every topic the platform
    synthesises, since every topic uses the same SPAR pipeline.
    """
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
    r"^\s*\|\s*[A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}",
)


def _check_qei_title_row_mismatch(body: str) -> list[ContractFailure]:
    """Wave 25: the QEI section's "Top N" title must match the actual
    number of data rows. Universal — every topic's QEI uses the same
    `## Quantitative Evidence Index` heading + `Top N` title pattern.
    """
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
    """Wave 25: the References section must not list the same citation
    twice. Same paper retrieved under multiple identifiers (PMID/DOI/
    manual ID) must be merged to a single bibliography entry. Universal
    — every topic uses the same References format with bold-leading
    citation tokens."""
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
            r"^\s*[-*]\s*\*\*([A-Z][A-Za-z\-']+(?:\s+(?:et\s+al\.?|&\s+\S+))?\s+\d{4}[a-z]?)\.?\*\*",
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
    repo_root: Path | None = None,
    run_dir: Path | None = None,
) -> ContractResult:
    """Run all nine rules; return ContractResult.

    Universal: rules 6 (wrong-topic) and 9 (SPAR leak) require optional
    paths — `repo_root` to enumerate `topic_packs/*.toml`, and `run_dir`
    to read `spar_cache.json`. Both rules silently skip when their inputs
    are absent so the orchestrator stays useful in unit-test contexts.
    """
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
    section_fails, abs_words = _check_sections(
        paper_md, abstract_word_cap=abstract_word_cap,
    )
    fails.extend(section_fails)
    fails.extend(_check_residue(paper_md))
    fails.extend(_check_wrong_topic_residue(paper_md, manifest, repo_root))
    fails.extend(_check_broken_prose(paper_md))
    fails.extend(_check_repeated_boilerplate(paper_md))
    fails.extend(_check_spar_reject_leakage(paper_md, manifest, run_dir))
    fails.extend(_check_rejected_appendix_required(paper_md, run_dir))
    fails.extend(_check_qei_title_row_mismatch(paper_md))
    fails.extend(_check_reference_duplicates(paper_md))
    by_rule: dict[str, int] = Counter(f.rule for f in fails)
    return ContractResult(
        status="FAIL" if fails else "PASS",
        failures=tuple(fails),
        canonical=canon,
        abstract_words=abs_words,
        n_failures_by_rule=dict(by_rule),
    )


# Repo-root resolution: walk up from this file until we find topic_packs/
# (the project's universal topic registry). Cached so the climb is paid
# once per process.
def _repo_root_from_module() -> Path | None:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "topic_packs").is_dir():
            return parent
    return None


_REPO_ROOT_CACHE: Path | None = _repo_root_from_module()


def validate_run_dir(
    run_dir: Path,
    *,
    abstract_word_cap: int = 500,
) -> ContractResult:
    """Read full_paper.md + manifest.json from a run dir and validate.

    Auto-resolves `repo_root` (for the wrong-topic rule) and passes
    `run_dir` (for the SPAR leak rule). Universal — works for any topic
    that lives inside a project with topic_packs/.
    """
    paper_md = (run_dir / "full_paper.md").read_text()
    manifest = json.loads((run_dir / "manifest.json").read_text())
    return validate(
        paper_md, manifest, abstract_word_cap=abstract_word_cap,
        repo_root=_REPO_ROOT_CACHE, run_dir=run_dir,
    )


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
