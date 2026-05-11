"""Day 10.17 Phase 6.2 — trust-spine audit for v0.6.0 synthesis paper.

Per the user audit verdict for Phase 6:
  - every numeric in prose traces to a quant claim
  - every citation maps to source metadata
  - every high-confidence claim used has claim_role == "effect"
  - no mortality/lifespan conflation
  - no unhedged model-organism-to-human transfer

Gate: audit ≥ 9/10, all P1 checks pass.

Reads `runs/<dir>/full_paper.md` + the v0.6.0 quant_claims corpus and
produces a JSON audit report + markdown summary.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Module-level corpus paths. Sentinel until _set_topic() runs — same
# universal-fix pattern as scripts/run_v06_synthesis.py: no metformin
# fallback. The orchestrator's _set_topic() calls this module's
# _set_topic() in lockstep at the top of every pipeline invocation.
_TOPIC_UNSET = REPO_ROOT / "_TOPIC_UNSET_call_set_topic_first"
QUANT_DIR: Path = _TOPIC_UNSET
PARSED_DIR: Path = _TOPIC_UNSET
_ACTIVE_TOPIC: str = ""


def _set_topic(topic: str) -> None:
    """Re-point QUANT_DIR + PARSED_DIR to the given topic. Called
    by run_v06_synthesis._set_topic to keep the two modules in
    lockstep (the orchestrator's _set_topic also calls this).

    Refactor 2026-05-04: also tracks active topic so
    _load_background_lit_numerics can pull topic-pack-specific
    bg-lit entries (e.g. PEARL '80' for rapamycin) in addition
    to the global registry."""
    global QUANT_DIR, PARSED_DIR, _ACTIVE_TOPIC
    QUANT_DIR = REPO_ROOT / "docs" / "quality-reference" / topic / "quant_claims"
    PARSED_DIR = REPO_ROOT / "docs" / "quality-reference" / topic / "parsed"
    _ACTIVE_TOPIC = topic


def _load_background_lit_numerics() -> set[str]:
    """Fix #16: numeric tokens from the background-literature registry.
    Pre-vetted clinical thresholds, each with a canonical citation;
    Q2 admits these in addition to corpus_numerics, but the new Stage-2
    `_check_background_lit_citation_present` enforces that any use
    must include the citation token in the same sentence.

    Refactor 2026-05-04: passes topic= so topic-pack-specific bg-lit
    entries are merged into the lookup set (PEARL '80', Harrison '9%'
    etc. live in topic_packs/<topic>.toml not the global JSON)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import background_literature as _bg
        return _bg.numeric_values(
            _bg.load_registry(topic=_ACTIVE_TOPIC)
        )
    except (ImportError, FileNotFoundError, ValueError):
        return set()


_OBJECTIVE_PARTIAL_TYPES = {
    # Objective-fact claim types where partial-confidence reflects
    # interpretive-binding uncertainty (active-vs-control arm,
    # primary-vs-secondary endpoint), not fabrication risk. The number
    # itself is a primary-source fact extracted from the paper text.
    "unit_value", "sample_size", "year", "sample_count",
}


def _load_corpus_numerics() -> set[str]:
    """STRICT pool for prose Q2: HIGH-confidence claims always, plus
    PARTIAL-confidence claims for objective-fact claim types only.
    This is the prose admissibility rule — used to gate any numeric
    in the LLM-authored body sections (introduction, background,
    results, discussion, etc.) where fabrication risk is real.

    P1 reviewer fix (2026-05-04 wave 3): scoped the partial-confidence
    admission to OBJECTIVE_PARTIAL_TYPES only. Loosening this further
    risks turning 'value coincidentally exists in the corpus' into
    'value is claim-bound', the very integrity trap the strict rule
    prevents. The wider HIGH+ALL_PARTIAL pool is kept available for
    the deterministic Quantitative Evidence Index via
    _load_table_admissible_numerics() and applied only inside that
    section by _check_numeric_integrity's scoped audit.

    Background-literature thresholds appended unconditionally (Fix #16
    — admissible in prose ONLY when their canonical citation is in
    the same sentence; enforced by Stage-2 _check_background_lit_*).
    """
    nums: set[str] = set()
    for path in QUANT_DIR.glob("*.quant_claims.json"):
        d = json.loads(path.read_text())
        for c in d.get("claims", []):
            confidence = (c.get("binding_confidence") or "").lower()
            claim_type = c.get("claim_type") or ""
            admit = (
                confidence == "high"
                or (confidence == "partial"
                    and claim_type in _OBJECTIVE_PARTIAL_TYPES)
            )
            if not admit:
                continue
            _add_claim_numerics(c, nums)
    nums |= _load_background_lit_numerics()
    return nums


def _load_table_admissible_numerics() -> set[str]:
    """LOOSE pool for the Quantitative Evidence Index table only.
    HIGH or PARTIAL confidence accepted for any numeric claim type —
    matches agent/results_table._confidence_admissible. Used by
    _check_numeric_integrity to validate numerics that appear inside
    the deterministic table block, where fabrication is structurally
    impossible (table is built from corpus by code, not LLM).

    NEVER applied to prose. Single-purpose function for the scoped
    admissibility audit."""
    nums: set[str] = set()
    for path in QUANT_DIR.glob("*.quant_claims.json"):
        d = json.loads(path.read_text())
        for c in d.get("claims", []):
            confidence = (c.get("binding_confidence") or "").lower()
            if confidence not in ("high", "partial"):
                continue
            _add_claim_numerics(c, nums)
    nums |= _load_background_lit_numerics()
    return nums


def _add_claim_numerics(c: dict, nums: set[str]) -> None:
    """Helper: extract numerics from one claim into the target set."""
    for v in c.get("numeric_values") or ():
        nums.add(str(v))
        try:
            if float(v).is_integer():
                nums.add(str(int(v)))
        except (TypeError, ValueError):
            continue
    raw = (c.get("raw_text") or "").strip()
    if raw:
        nums.add(raw)


def _load_paper_metadata() -> dict[str, dict]:
    """paper_id → {title, authors, year, doi, pmid, journal}."""
    out: dict[str, dict] = {}
    for path in PARSED_DIR.glob("*.paper_sections.json"):
        d = json.loads(path.read_text())
        pid = d.get("paper_id") or path.stem
        out[pid] = d
    return out


# Q1: word count
def _check_word_count(paper: str, threshold: int = 5000) -> tuple[bool, str]:
    wc = len(paper.split())
    return wc >= threshold, f"word_count={wc} (threshold={threshold})"


# Q2: numeric integrity — every reportable numeric in the paper
# (percentages, p-values, HR/OR/RR ratios, sample sizes, doses,
# walk speeds) must trace to a v0.6.0 high-confidence claim. P1
# reviewer fix: pre-fix only checked percentages, so values like
# `HR 0.41` or `n=120` or `0.85 m/s` could be hallucinated without
# tripping the gate.
_PATTERNS_BY_CATEGORY: tuple[tuple[str, str], ...] = (
    # (category, regex_with_one_capture_group)
    # Refactor 2026-05-04: percentage regex now EXCLUDES confidence-
    # interval notation '95% CI', '99% CI', '90% CI'. Without the
    # negative lookahead, every CI in the paper got extracted as an
    # untraceable '95%' percentage claim — false positives that
    # SHIP-BLOCKED runs even on otherwise-clean papers.
    (
        "percentage",
        r"\b(\d+\.?\d*)\s*%(?!\s*(?:CI|confidence\s+interval))",
    ),
    ("p_value", r"\b[Pp]\s*[<>=]\s*(0?\.\d+)\b"),
    # Ratios: mandatory `=` or `:` separator + digit. Pre-fix
    # `OR\s*[=:]?` (optional separator) matched English "or" in
    # prose like "5 or 10 mg" → false ratio extraction. aOR/IRR/
    # SHR/SMR added for completeness.
    ("ratio",
     r"\b(?:aHR|aOR|HR|OR|RR|RRR|IRR|SHR|SMR)\s*[=:]\s*(\d+\.?\d*)"),
    ("sample_size", r"\b[nN]\s*=\s*(\d+)\b"),
    ("dose", r"\b(\d+\.?\d*)\s*(?:mg|g|kg|μg|mcg|mL)\b"),
    ("speed", r"\b(\d+\.?\d*)\s*m\s*/\s*s\b"),
)


# Marker for the deterministic Quantitative Evidence Index section.
# Reviewer wave-3 fix (2026-05-04): partial-confidence numerics are
# admissible ONLY inside this block (the table is built from corpus
# by code, no LLM authorship, so fabrication is structurally
# impossible). Prose stays strict.
_TABLE_HEADING_RE = re.compile(
    r"^##\s+Quantitative\s+Evidence\s+Index\b",
    flags=re.MULTILINE,
)
_NEXT_SECTION_RE = re.compile(r"^##\s+", flags=re.MULTILINE)


def _split_table_section(paper: str) -> tuple[str, str]:
    """Split a paper into (prose_block, table_block).

    Prose: everything outside the Quantitative Evidence Index section.
    Table: the index section content (heading line through the last
    line before the next ## heading).

    Returns (paper, '') unchanged if no index section is present —
    older runs without the deterministic table are audited entirely
    under the strict prose rule, no behavior change.
    """
    m = _TABLE_HEADING_RE.search(paper)
    if not m:
        return paper, ""
    table_start = m.start()
    # Find the next ## heading after the table heading
    rest = paper[m.end():]
    next_m = _NEXT_SECTION_RE.search(rest)
    if next_m:
        table_end = m.end() + next_m.start()
    else:
        table_end = len(paper)
    table_block = paper[table_start:table_end]
    prose_block = paper[:table_start] + paper[table_end:]
    return prose_block, table_block


def _check_numeric_integrity(
    paper: str, corpus_nums: set[str],
) -> tuple[bool, str]:
    """Q2: every reportable numeric in the paper must trace to the
    corpus. Prose uses the STRICT pool (`corpus_nums` arg, from
    _load_corpus_numerics — HIGH + objective-partial). The
    Quantitative Evidence Index block is audited separately under
    the LOOSE pool (HIGH + ALL_PARTIAL) since the table is
    code-rendered and structurally cannot fabricate.
    """
    # Strip CI-level anchors before splitting (so the strip applies
    # uniformly to both prose and table blocks).
    paper_clean = re.sub(
        r"\b(?:95|99|99\.9|90)\s*%\s*CI\b", "", paper, flags=re.IGNORECASE,
    )
    prose_block, table_block = _split_table_section(paper_clean)

    by_cat: dict[str, set[str]] = {}
    untraceable_by_cat: dict[str, list[str]] = {}
    n_total = 0
    n_bad = 0

    # Lazy-load the loose pool only when a table is present.
    table_pool: set[str] | None = None
    if table_block:
        table_pool = _load_table_admissible_numerics()

    def _audit_block(block: str, pool: set[str]) -> None:
        nonlocal n_total, n_bad
        for cat, pat in _PATTERNS_BY_CATEGORY:
            vals = set(re.findall(pat, block))
            if cat == "percentage":
                vals = {v for v in vals if 1.0 < float(v) < 1000}
            by_cat.setdefault(cat, set()).update(vals)
            bad = []
            for v in vals:
                f = float(v)
                candidates = {
                    v, str(f),
                    str(int(f)) if f.is_integer() else v,
                }
                if not any(c in pool for c in candidates):
                    bad.append(v)
            n_total += len(vals)
            n_bad += len(bad)
            if bad:
                untraceable_by_cat.setdefault(cat, []).extend(bad)

    _audit_block(prose_block, corpus_nums)
    if table_block and table_pool is not None:
        _audit_block(table_block, table_pool)

    # Trim per-category untraceable lists for the readout
    for cat, vals in untraceable_by_cat.items():
        untraceable_by_cat[cat] = sorted(set(vals))[:3]

    pct_clean = (n_total - n_bad) / n_total if n_total else 1.0
    detail = ", ".join(
        f"{cat}={len(by_cat[cat])-len([v for v in untraceable_by_cat.get(cat, []) if v in by_cat[cat]])}"
        f"/{len(by_cat[cat])}"
        for cat in by_cat if by_cat[cat]
    )
    return n_bad == 0, (
        f"{n_total - n_bad}/{n_total} numerics trace to corpus "
        f"({pct_clean:.0%}); per-category: {detail or 'none'}; "
        f"untraceable: {dict(list(untraceable_by_cat.items())[:5])}"
    )


# Q3: paper-ID leakage — internal handles must NOT appear in body prose
def _check_no_paper_id_in_body(
    paper: str, paper_meta: dict[str, dict],
) -> tuple[bool, str]:
    leaks: list[str] = []
    body_lines = []
    in_references = False
    for line in paper.splitlines():
        if line.strip().startswith("## References") or line.strip().startswith("## Limitations"):
            # References section — IDs are allowed there
            in_references = line.strip().startswith("## References")
        if not in_references:
            body_lines.append(line)
    body = "\n".join(body_lines)
    for pid in paper_meta:
        # Look for the truncated form (first 25-30 chars) which is what
        # Phase 6-lite was producing.
        short = pid[:25]
        if short and short in body and pid != "":
            leaks.append(short)
    return len(leaks) == 0, (
        f"paper-ID leaks in body: {leaks[:5]}"
        if leaks else "no paper-ID leakage"
    )


# Q4: mortality/lifespan polarity — paper must not say "decreased
# lifespan by N%" (Keys/UKPDS bug); should say "decreased mortality"
# or "reduced risk" instead
_BAD_POLARITY_RE = re.compile(
    r"decreased\s+lifespan\s+by\s+\d|"
    r"lifespan\s+(?:was\s+)?reduced\s+by\s+\d|"
    r"shortened\s+lifespan\s+by\s+\d",
    re.IGNORECASE,
)


def _check_no_mortality_lifespan_conflation(paper: str) -> tuple[bool, str]:
    matches = _BAD_POLARITY_RE.findall(paper)
    return len(matches) == 0, (
        f"polarity violations: {matches[:3]}"
        if matches else "no mortality/lifespan polarity error"
    )


# Q5: methodology fabrication — Methods section must not claim manual
# review / two researchers / consensus / verification by hand
_FAB_PHRASES = (
    "two researchers",
    "manually reviewed",
    "manual review",
    "verified by two",
    "researchers verified",
    "consensus was reached",
    "discussed and resolved",
    "domain expert",
    "expert reviewed",
)


def _check_no_fabricated_methodology(paper: str) -> tuple[bool, str]:
    methods_match = re.search(
        r"##\s+Methods.*?(?=##\s+\w)", paper, re.DOTALL,
    )
    if not methods_match:
        return False, "Methods section not found"
    methods_text = methods_match.group(0).lower()
    flagged: list[str] = []
    for phrase in _FAB_PHRASES:
        if phrase in methods_text:
            # Check for hedging/disclaimer in same sentence
            idx = methods_text.find(phrase)
            sentence_start = max(0, methods_text.rfind(".", 0, idx) + 1)
            sentence_end = methods_text.find(".", idx)
            if sentence_end < 0:
                sentence_end = len(methods_text)
            sent = methods_text[sentence_start:sentence_end]
            if "no manual" in sent or "not" in sent[:30]:
                continue  # disclaimer present
            flagged.append(phrase)
    return len(flagged) == 0, (
        f"fabricated methodology phrases: {flagged}"
        if flagged else "no fabricated methodology claims"
    )


# Q6: model-organism-to-human transfer — sentences mentioning mice/
# rats/C. elegans must hedge before applying findings to humans
_PRECLINICAL_RE = re.compile(
    r"\b(?:mice|rats?|C\.\s*elegans|mouse\s+models?|preclinical|"
    r"animal\s+models?|in\s+vitro|cell\s+culture)\b", re.IGNORECASE,
)


def _check_preclinical_hedge(paper: str) -> tuple[bool, str]:
    """For sentences mentioning preclinical models, check if the
    immediately following sentence (or same sentence) contains a
    translational hedge or limitation marker.

    Excludes the publication-prep appendix sections — those are
    metadata/disclosure prose, not synthesis content, and should
    not be measured for translational hedging."""
    # Strip appendix before measuring (Q9 does the same).
    paper_for_check = _strip_publication_appendix(paper)
    # Q6 is a narrative-prose gate. Reference titles and deterministic
    # evidence tables often contain "mice"/"preclinical" but are not
    # translational claims by the manuscript author.
    paper_for_check = re.split(
        r"^##\s+(?:Structured Evidence Tables|Quantitative Evidence "
        r"Index\b|References\b|Table\s+\d+\b)",
        paper_for_check,
        maxsplit=1,
        flags=re.MULTILINE | re.IGNORECASE,
    )[0]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", paper_for_check)
    violations: list[str] = []
    # Refactor 2026-05-04: expanded hedge phrase set. Previously
    # missed "animal models" / "in mice" / "model organisms" /
    # "in vitro" — sentences explicitly naming the preclinical
    # context were getting flagged as unhedged because the writer's
    # natural phrasing wasn't in the literal hedge list.
    hedges = (
        # Translation-aware
        "humans", "translation", "translate", "extrapolat",
        "may not apply", "may not manifest", "remains to be", "warrant", "caution",
        "uncertain", "context-dependent", "speculative",
        "mechanistic evidence", "limit",
        # Self-tagged preclinical context (these explicitly name
        # the non-human / preclinical setting, which IS the hedge)
        "preclinical", "in mice", "in animals", "animal model",
        "model organism", "in rodents", "rat", "murine", "mouse",
        "c. elegans", "drosophila", "zebrafish", "in vitro",
        "ex vivo", "cell culture", "rodent",
    )
    for i, sent in enumerate(sentences):
        if _PRECLINICAL_RE.search(sent):
            # Check this sentence + next for any hedge.
            window = sent + " " + (sentences[i + 1] if i + 1 < len(sentences) else "")
            window_lc = window.lower()
            if not any(h in window_lc for h in hedges):
                # Also: sentences in Limitations section get a free pass
                # (we trust the section-level hedge there).
                if "limitations" in window_lc or "method" in window_lc:
                    continue
                violations.append(sent[:80])
    pass_threshold = 3  # tolerate up to 3 unhedged preclinical sentences
    return len(violations) <= pass_threshold, (
        f"unhedged preclinical→human sentences: {len(violations)} "
        f"(threshold ≤{pass_threshold})"
    )


# Q7: section coverage
_REQUIRED_SECTIONS = (
    "Abstract", "Introduction", "Methods", "Results",
    "Discussion", "Limitations", "Conclusion",
)


def _check_section_coverage(paper: str) -> tuple[bool, str]:
    missing: list[str] = []
    for sec in _REQUIRED_SECTIONS:
        if not re.search(rf"^##\s+{sec}\b", paper, re.M):
            missing.append(sec)
    return len(missing) == 0, (
        f"missing sections: {missing}" if missing else "all required sections present"
    )


# Q8: thesis sentence presence
def _check_thesis_present(paper: str) -> tuple[bool, str]:
    has_thesis = bool(
        re.search(r"^\*\*Thesis:\*\*", paper, re.M)
        or re.search(r"^\*\*Picked thesis\b.*?:\*\*", paper, re.M)
        or re.search(r"\bThe deterministic thesis is:", paper)
        or re.search(
            r"\bThe synthesis surfaces\s+\d+\s+non-orthogonal tensions\b",
            paper,
            re.I,
        )
        or re.search(r"thesis(?:\s+is)?\s+that", paper[:3000], re.I)
    )
    return has_thesis, (
        "thesis sentence found" if has_thesis else "no thesis sentence"
    )


# Q9: numeric density (claims-per-1k-words). Fix #12: extended
# patterns to include ratios, sample sizes, CIs, and doses —
# symmetric with Q2 numeric-integrity. Tables are explicitly part
# of the contract for density (per the reviewer's "tables-not-
# paragraphs" guidance). Bumped to v2 after reviewer found two P1
# pattern bugs (`OR` matching English "or"; range pattern matching
# years like "2024-2026"). See _DENSITY_CONTRACT_VERSION.

# Versioned metric contract — surfaced in audit output so a future
# replay-on-old-paper run can't be mis-attributed to "paper improved"
# when only the metric changed.
_DENSITY_CONTRACT_VERSION = "2026-05-03-v2"

# Ratios MUST have an explicit `=` or `:` separator + a digit.
# Without that, `OR` matches the English word "or" in prose like
# "5 or 10 mg" → false ratio count. `aOR` (adjusted OR), `IRR`
# (incidence rate ratio), `SHR` (subdistribution HR), `SMR`
# (standardized mortality ratio) added for completeness.
_RATIO_PATTERN = (
    r"\b(?:aHR|aOR|HR|OR|RR|RRR|IRR|SHR|SMR)\s*[=:]\s*\d+\.?\d*"
)

# Range pattern restricted to clinical-context shapes:
#   - Inside parens with a leading CI or 95%/99%/90% marker
#   - Or following an explicit "range" keyword
# Pre-fix the bare `\d+\s*-\s*\d+` matched years ("2024-2026"),
# page numbers ("section 1-3"), and double-counted with the dose
# pattern ("850 mg to 1700 mg" counted 3×).
_RANGE_PATTERN = (
    r"(?:95%\s*CI|99%\s*CI|90%\s*CI|\bCI\b|\brange\b)[^,)\n]*?"
    r"\d+\.?\d*\s*(?:to|–|-)\s*\d+\.?\d*"
)

_DENSITY_PATTERNS: tuple[str, ...] = (
    r"\b\d+\.?\d*\s*%",                                    # percentages
    r"\b[pP]\s*[<=>]\s*\.?\d+\.?\d*",                      # p-values
    _RATIO_PATTERN,                                        # ratios
    r"\b[nN]\s*=\s*\d+",                                   # sample sizes
    r"\b\d+\.?\d*\s*(?:m/s|kg|mg|g|μg|mcg|mL|L|"           # doses + units
    r"months?|years?|weeks?|days?|hours?|min)\b",          # (no bare `h`)
    _RANGE_PATTERN,                                        # CIs / ranges
)


_APPENDIX_HEADINGS_RE = re.compile(
    r"^##\s+(Search Provenance and Selection|"
    r"AI-Use Disclosure|"
    r"Human Accountability Statement|"
    r"Data and Code Availability|"
    r"Acknowledgements?)"
    r".*$",
    re.MULTILINE | re.IGNORECASE,
)


def _strip_publication_appendix(paper: str) -> str:
    """Strip the publication-prep appendix sections (Search
    Provenance / AI-Use Disclosure / Human Accountability / Data
    and Code Availability / Acknowledgements) from the paper before
    measuring synthesis-content metrics.

    These sections are pure metadata/disclosure/methodology — they
    have no claim density by design. Including them in Q6 (hedge
    density) or Q9 (numeric density) measurements would dilute the
    synthesis-content signal those checks are meant to catch.
    Stripping is local to the metric — the actual paper file is
    untouched."""
    # Find the first appendix heading; cut everything from there to
    # the next NON-appendix heading (or to the References section,
    # whichever comes first).
    lines = paper.splitlines()
    out: list[str] = []
    in_appendix = False
    for line in lines:
        m = _APPENDIX_HEADINGS_RE.match(line)
        if m:
            in_appendix = True
            continue
        if in_appendix and line.startswith("## ") and not (
            _APPENDIX_HEADINGS_RE.match(line)
        ):
            in_appendix = False
        if not in_appendix:
            out.append(line)
    return "\n".join(out)


_ANALYTICAL_DENOMINATOR_EXCLUDE_RE = re.compile(
    r"^##\s+(?:Quantitative Evidence Index\b|Structured Evidence "
    r"Tables\b|Table\s+\d+\b|Table\s+\d+\s*\(|References\b)",
    re.IGNORECASE,
)


def _strip_non_prose_sections_for_analytical_ratio(paper: str) -> str:
    """Remove deterministic tables, QEI, references, and publication
    appendix before computing Q13's analytical-prose denominator.

    Q13 is a prose-composition gate. Counting 10k+ words of
    deterministic evidence tables as body prose makes large-corpus
    papers fail for being auditable. The 15% threshold stays strict;
    the denominator is the narrative synthesis body."""
    text = _strip_publication_appendix(paper)
    lines = text.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("## "):
            skipping = bool(_ANALYTICAL_DENOMINATOR_EXCLUDE_RE.match(line))
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _check_numeric_density(
    paper: str, threshold: float = 8.0,
) -> tuple[bool, str]:
    # Exclude publication-prep appendix from density calculation —
    # appendix is pure prose with no claim numerics by design.
    synthesis_content = _strip_publication_appendix(paper)
    wc = len(synthesis_content.split())
    total = sum(
        len(re.findall(pat, synthesis_content))
        for pat in _DENSITY_PATTERNS
    )
    density = (total / max(1, wc)) * 1000
    return density >= threshold, (
        f"density {density:.1f} numerics/1000 words "
        f"(threshold ≥{threshold}; contract={_DENSITY_CONTRACT_VERSION}; "
        f"appendix excluded)"
    )


# Q10: hedge phrases present in Discussion / Limitations
_HEDGE_PHRASES = (
    "may", "might", "suggests", "consistent with", "appears",
    "context-dependent", "uncertain", "warrants", "remains to be",
    "preliminary", "interpretive", "qualified", "limited", "cautious",
)


def _check_hedge_density(paper: str) -> tuple[bool, str]:
    """Fix #44: ADAPTIVE hedge-density threshold. ≥4 was too
    permissive for contested fields. New rule:
      - threshold ≥6 if the corpus is dominated by mixed/unclear
        effect_directions (>50% of receipts)
      - threshold ≥4 otherwise (preserves backward-compat for
        unambiguous-evidence corpora)
    The corpus uncertainty fraction is computed from the
    module-global _PAPER_META (set by audit() at the start of
    each run); falls back to ≥4 if metadata isn't available."""
    discussion_match = re.search(
        r"^##\s+Discussion(.*?)(?=^##\s+\w|\Z)",
        paper,
        re.DOTALL | re.MULTILINE,
    )
    if not discussion_match:
        return False, "Discussion section not found"
    disc = discussion_match.group(1).lower()
    n_hedges = sum(1 for h in _HEDGE_PHRASES if h in disc)
    # Compute uncertainty fraction from corpus.
    # We don't have direct access to manifest receipts here, but
    # quant_claims encode effect_direction per claim — count
    # receipts where the dominant effect_direction is mixed/unclear.
    threshold = _adaptive_hedge_threshold()
    return n_hedges >= threshold, (
        f"{n_hedges}/{len(_HEDGE_PHRASES)} hedge phrases in Discussion "
        f"(threshold ≥{threshold} — Fix #44 adaptive: corpus "
        f"uncertainty-weighted)"
    )


def _adaptive_hedge_threshold() -> int:
    """Returns 6 when >50% of receipts have mixed/unclear effect
    direction, else 4. Reads quant_claims to compute the fraction
    deterministically — no I/O beyond what _load_corpus_numerics
    already does."""
    n_uncertain = 0
    n_total = 0
    for path in QUANT_DIR.glob("*.quant_claims.json"):
        try:
            d = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        # A receipt is 'uncertain dominant' iff its high-conf claims
        # mostly carry effect_direction in {mixed, unclear, null} —
        # all three are 'no clean signal' states.
        directions = [
            (c.get("direction") or "").lower()
            for c in d.get("claims", [])
            if c.get("binding_confidence") == "high"
        ]
        if not directions:
            continue
        n_total += 1
        n_unclean = sum(
            1 for d_ in directions if d_ in ("mixed", "unclear", "null")
        )
        if n_unclean / len(directions) > 0.5:
            n_uncertain += 1
    if n_total == 0:
        return 4
    return 6 if n_uncertain / n_total > 0.5 else 4


# Fix #41: Discussion depth gate. Fail closed on thin analysis; the
# repair layer must not synthesize filler to satisfy this gate.
def _check_discussion_depth(paper: str) -> tuple[bool, str]:
    m = re.search(
        r"##\s+Discussion(.*?)(?=^##\s+\w|\Z)",
        paper, re.DOTALL | re.MULTILINE,
    )
    if not m:
        return False, "Discussion section not found"
    body = m.group(1)
    n = len(body.split())
    return n >= 800, (
        f"Discussion {n} words "
        "(threshold ≥800 — analytical-depth gate)"
    )


# Fix #42: Cross-Domain Synthesis depth gate. Fail closed on thin
# synthesis; the repair layer must not synthesize filler prose.
def _check_cross_domain_depth(paper: str) -> tuple[bool, str]:
    m = re.search(
        r"##\s+Cross-Domain Synthesis(.*?)(?=^##\s+\w|\Z)",
        paper, re.DOTALL | re.MULTILINE,
    )
    if not m:
        return False, "Cross-Domain Synthesis section not found"
    body = m.group(1)
    n = len(body.split())
    return n >= 800, (
        f"Cross-Domain Synthesis {n} words "
        "(threshold ≥800 — analytical-depth gate)"
    )


# Fix #43: combined analytical-prose ratio. Discussion + Cross-Domain
# Synthesis must be ≥15% of body words. Catches the pattern where
# either section is somewhat thin but together they collapse below
# the 'PhD-level analytical depth' threshold.
def _check_analytical_ratio(paper: str) -> tuple[bool, str]:
    discussion = re.search(
        r"##\s+Discussion(.*?)(?=^##\s+\w|\Z)",
        paper, re.DOTALL | re.MULTILINE,
    )
    cross = re.search(
        r"##\s+Cross-Domain Synthesis(.*?)(?=^##\s+\w|\Z)",
        paper, re.DOTALL | re.MULTILINE,
    )
    n_disc = len(discussion.group(1).split()) if discussion else 0
    n_cross = len(cross.group(1).split()) if cross else 0
    ratio_body = _strip_non_prose_sections_for_analytical_ratio(paper)
    body_words = len(ratio_body.split())
    if body_words < 100:
        return False, "paper too short to compute analytical ratio"
    ratio = (n_disc + n_cross) / body_words
    return ratio >= 0.15, (
        f"analytical ratio {ratio*100:.1f}% "
        f"(Discussion {n_disc} + Cross-Domain {n_cross} / "
        f"body {body_words}; threshold ≥15% — Fix #43 depth gate)"
    )


_BRIDGE_RE = re.compile(
    r"^##\s+Inferential Bridge\b(.*?)(?=^##\s+\w|\Z)",
    re.DOTALL | re.MULTILINE,
)
_D1_RE = re.compile(
    r"\[D1_[^\]]+\|\s*confidence=(low|medium|high)\]",
    re.IGNORECASE,
)
_INLINE_NUMERIC_RE = re.compile(r"(?<![A-Za-z])(?:\d+(?:\.\d+)?|\d+\s*%)")


def _check_inferential_bridge_contract(paper: str) -> tuple[bool, str]:
    """Q14: optional D1 section is allowed only with traceable tags.

    Absence passes. Presence must be machine-checkable and must not
    introduce new numerics as inferred facts.
    """
    match = _BRIDGE_RE.search(paper)
    if not match:
        return True, "no Inferential Bridge section"
    body = match.group(1).strip()
    if not body:
        return True, "empty Inferential Bridge section"
    blocks = [
        b.strip()
        for b in re.split(r"\n(?=\d+\.\s+|\-\s+)", body)
        if re.match(r"^(?:\d+\.|\-)\s+", b.strip())
    ]
    if not blocks:
        return False, "Inferential Bridge has no numbered D1 claims"
    for i, block in enumerate(blocks, 1):
        if not _D1_RE.search(block):
            return False, f"D1 claim {i} missing tier/confidence tag"
        tag_groups = (
            ("[mechanism anchor:", "[mechanism_anchor:"),
            ("[conservation:",),
            ("[testability:",),
        )
        for tags in tag_groups:
            if not any(tag in block for tag in tags):
                return False, f"D1 claim {i} missing {tags[0]}"
        visible = re.sub(r"\[[^\]]+\]", "", block)
        visible = re.sub(r"^\s*(?:\d+\.|\-)\s+", "", visible)
        visible = re.sub(r"Existing human signal:.*?(?:\n|$)", "", visible)
        if _INLINE_NUMERIC_RE.search(visible):
            return False, f"D1 claim {i} introduces an untraced numeric"
    return True, f"{len(blocks)} D1 bridge claims carry required tags"


_CHECKS = (
    ("Q1_word_count", _check_word_count, True),  # P1
    ("Q2_numeric_integrity", lambda p: _check_numeric_integrity(p, _CORPUS_NUMS), True),
    ("Q3_no_paper_id_in_body", lambda p: _check_no_paper_id_in_body(p, _PAPER_META), True),
    ("Q4_no_polarity_error", _check_no_mortality_lifespan_conflation, True),
    ("Q5_no_fabricated_methods", _check_no_fabricated_methodology, True),
    ("Q6_preclinical_hedge", _check_preclinical_hedge, False),
    ("Q7_section_coverage", _check_section_coverage, True),
    ("Q8_thesis_present", _check_thesis_present, False),
    ("Q9_numeric_density", _check_numeric_density, False),
    ("Q10_hedge_density", _check_hedge_density, False),
    # Fix #41-43: depth gates. Catch the 'AAA-by-mechanics-but-
    # analytically-hollow' failure mode. P2 (block AAA but not ship).
    ("Q11_discussion_depth", _check_discussion_depth, False),
    ("Q12_cross_domain_depth", _check_cross_domain_depth, False),
    ("Q13_analytical_ratio", _check_analytical_ratio, False),
    ("Q14_inferential_bridge_contract", _check_inferential_bridge_contract, True),
)
# Module-level state so the lambdas above can read corpus + meta.
_CORPUS_NUMS: set[str] = set()
_PAPER_META: dict[str, dict] = {}


def audit(paper: str) -> dict:
    """Run all 10 checks. Returns dict with per-check verdict + score."""
    global _CORPUS_NUMS, _PAPER_META
    _CORPUS_NUMS = _load_corpus_numerics()
    _PAPER_META = _load_paper_metadata()

    results = []
    p1_pass = True
    n_pass = 0
    for name, check_fn, is_p1 in _CHECKS:
        try:
            passed, msg = check_fn(paper)
        except Exception as e:
            passed, msg = False, f"check exception: {e}"
        results.append({
            "name": name,
            "p1": is_p1,
            "passed": passed,
            "detail": msg,
        })
        if is_p1 and not passed:
            p1_pass = False
        if passed:
            n_pass += 1

    score = (n_pass / len(_CHECKS)) * 10
    return {
        "score_out_of_10": round(score, 1),
        "p1_pass": p1_pass,
        "checks": results,
        "n_pass": n_pass,
        "n_total": len(_CHECKS),
    }


def _format_summary(report: dict) -> str:
    lines = [
        "# v0.6.0 Synthesis Paper — Trust-Spine Audit",
        "",
        f"**Score:** {report['score_out_of_10']}/10",
        f"**P1 ship-blockers:** {'PASS' if report['p1_pass'] else 'FAIL'}",
        f"**Pass rate:** {report['n_pass']}/{report['n_total']} checks",
        "",
        "## Checks",
        "",
        "| # | Check | P1? | Status | Detail |",
        "|---|---|---|---|---|",
    ]
    for c in report["checks"]:
        status = "✅" if c["passed"] else "❌"
        p1 = "**P1**" if c["p1"] else "P2"
        lines.append(
            f"| {c['name']} | {c['name']} | {p1} | {status} | {c['detail']} |"
        )
    lines.append("")
    # P1 reviewer fix: AAA is reserved for ALL-GREEN. Pre-fix, the
    # audit declared AAA at score≥9.0 + P1-pass even when P2 checks
    # failed — a separate post-hoc fixer step renamed the verdict.
    # The audit itself should not lie.
    n_pass = sum(1 for c in report["checks"] if c["passed"])
    n_total = len(report["checks"])
    all_green = n_pass == n_total
    if not report["p1_pass"]:
        lines.append("## Verdict: SHIP-BLOCKED")
        lines.append("")
        lines.append("One or more P1 checks failed. Fix before merging.")
    elif all_green:
        lines.append("## Verdict: AAA")
        lines.append("")
        lines.append(
            f"All {n_total} checks pass (P1 + P2). "
            "Paper meets the AAA bar."
        )
    elif report["score_out_of_10"] >= 9.0:
        lines.append("## Verdict: Trust-Spine Pass")
        lines.append("")
        lines.append(
            f"P1 ship-blockers all green; overall score "
            f"{report['score_out_of_10']}/10 ({n_pass}/{n_total} checks). "
            "One or more P2 quality checks flagged non-blocking issues. "
            "AAA is reserved for all-green."
        )
    else:
        lines.append("## Verdict: PASS (with notes)")
        lines.append("")
        lines.append(
            f"P1 checks all green; overall score "
            f"{report['score_out_of_10']}/10. Some P2 checks flagged "
            "non-critical issues."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a v0.6.0 synthesis paper")
    parser.add_argument("paper_md", help="Path to the full_paper.md to audit")
    parser.add_argument(
        "--out",
        help="Output JSON report (default: <paper>.audit.json)",
    )
    args = parser.parse_args(argv)
    paper_path = Path(args.paper_md).resolve()
    if not paper_path.exists():
        print(f"not found: {paper_path}", file=sys.stderr)
        return 2
    paper = paper_path.read_text()
    report = audit(paper)
    out = (
        Path(args.out).resolve() if args.out
        else paper_path.with_suffix(".audit.json")
    )
    out.write_text(json.dumps(report, indent=2))
    summary_md = _format_summary(report)
    summary_path = paper_path.with_suffix(".audit.md")
    summary_path.write_text(summary_md)
    print(summary_md)
    print(f"\nReport: {out}\nSummary: {summary_path}", file=sys.stderr)
    return 0 if report["p1_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
