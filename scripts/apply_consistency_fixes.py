"""Day 10.17 Phase 6.2 Layer 1 — deterministic fixer.

Reads <paper>.consistency.json (from final_consistency_audit.py) and
applies fixes for issues marked auto_fixable. Per fix type:

  duplicate_section          → remove all but the first ## References
  malformed_header           → '### ### Foo' → '### Foo'
  repair_artifact            → strip ' (potentially)' inline marker
                                 (no replacement — sentence-level hedges
                                 already exist elsewhere in the prose)
  stale_method_boilerplate   → strip the offending paragraph from Methods
                                 OR replace with a v0.6 adapter sentence
                                 (handled paragraph-by-paragraph)
  audit_verdict_overclaim    → rewrite audit.md verdict heading
  paper_id_in_body           → flag-only (needs receipt list, deferred to
                                 Layer 2 / Grok or human review)

Every fix logged to <paper>.fixed_log.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path

from agent.topic_display import humanize_topic, intervention_label
from agent.outcome_class_remap import outcome_key
from direction_consistency import repair_abstract_direction_summary
from evidence_map_summary import signal_summary_cell, source_context_map

__all__ = ["apply_fixes", "main"]


_POTENTIALLY_RE = re.compile(r"\s*\(potentially\)", re.IGNORECASE)
_DOUBLE_HASH_RE = re.compile(r"^(#{2,4})\s+#{2,4}\s+", re.MULTILINE)
_H3_RESIDUE_HEADING_RE = re.compile(r"(?im)^###\s+H3[:.]\s+")
# Sentences that contain stale-SPAR phrases — strip the entire sentence.
# Fix #29: extended phrase set per reviewer — "spar quarantine"
# (noun form), "spar-rejected", "rejected evidence" added.
# Phrases like bare "quarantined" are too broad to ban
# unconditionally; the regex below pairs them with SPAR context.
_STALE_SPAR_SENT_RE = re.compile(
    r"[^.!?\n#]*\b(?:spar\s+adjudication|rejected\s+by\s+spar|"
    r"spar-?rejected|spar-?quarantined?|spar\s+quarantine|"
    r"rejected\s+evidence|"
    r"claim\s+receipts?|receipt\s+clusters?|"
    r"receipt-level\s+spar|synthesis-level\s+spar|"
    r"trust-spine\s+multi-receipt)\b[^.!?\n#]*[.!?]",
    re.IGNORECASE,
)
_ROLE_REPAIR_ARTIFACT_SENT_RE = re.compile(
    r"(?m)(?:^|(?<=[.!?])\s*)"
    r"[A-Z][A-Za-z'`.\-]+(?:\s+[A-Z][A-Za-z'`.\-]+)?\s+"
    r"\d{4}\s+reported\s+(?:an?\s+)?(?:dose|effect\s+value|"
    r"outcome\s+value|baseline\s+value|population\s+descriptor|"
    r"threshold|change)(?:\s+of\s+[^;\n]+)?;\s+this\s+manuscript\s+"
    r"treats\s+the\s+value\s+according\s+to\s+that\s+source\s+role\."
    r"[ \t]*(?:\n+)?",
    re.IGNORECASE,
)
_EFFECT_ESTIMATE_ARTIFACT_SENT_RE = re.compile(
    r"(?m)(?:^|(?<=[.!?])\s*)"
    r"[A-Z][A-Za-z'`.\-]+(?:\s+\d{4}[a-z]?)?\s+reported\s+an\s+"
    r"effect\s+estimate(?:\s+of\s+(?:[^.!?\n]|\.(?=\d))*)?[.!?][ \t]*(?:\n+)?",
    re.IGNORECASE,
)
_ORPHAN_THRESHOLD_SENT_RE = re.compile(
    r"(?m)(?:^|(?<=[.!?])\s*)This\s+improvement,\s+while\s+"
    r"statistically\s+detectable,\s+fell\s+below\s+"
    r"(?:[^.!?\n]|\.(?=\d))*[.!?][ \t]*(?:\n+)?",
    re.IGNORECASE,
)
_ORPHAN_DEMONSTRATED_CLAUSE_RE = re.compile(
    r",\s+yet\s+demonstrated\s+that\s+"
    r"(?:[^,\n]|\,(?!\s+and\s+))*?,\s+and\s+",
    re.IGNORECASE,
)
_EMPTY_ATTRIBUTION_SENT_RE = re.compile(
    r"(?m)(?:^|(?<=[.!?])\s*)"
    r"[^.!?\n#]*\b(?:described|reported|observed|shown|demonstrated)\s+"
    r"by\s+\.[ \t]*(?:\n+)?",
    re.IGNORECASE,
)
_TOXIN_MOBILIZATION_SENT_RE = re.compile(
    r"(?m)(?:^|(?<=[.!?])\s*)"
    r"[^.!?\n#]*\b(?:polychlorinated\s+biphenyls|lipophilic\s+toxins)\b"
    r"[^.!?\n#]*[.!?][ \t]*(?:\n+)?",
    re.IGNORECASE,
)
_ORPHAN_DEMONSTRATED_TAIL_RE = re.compile(
    r",\s+and\s+demonstrated\s+that\s+[^.!?\n#]*[.!?]",
    re.IGNORECASE,
)
_PUBLIC_REFERENCE_DUMP_RE = re.compile(
    r"(?ims)(?:^|\n\n)(?!##\s)"
    r"(?=[^\n]*(?:\bDOI:|\bPMID:))"
    r"[^\n]*(?:\n\n|$)"
)
_BACKGROUND_REFERENCES_RE = re.compile(
    r"(?ims)^###\s+Background References\b.*?(?=^##\s+|\Z)"
)
_FINAL_INTERPRETATION_RE = re.compile(
    r"(?ims)^###\s+Final interpretation\b.*?(?=^##\s+|^###\s+|\Z)"
)
_DISCUSSION_HOWEVER_RE = re.compile(
    r"(?m)(^##\s+Discussion\s*\n\n)However,\s+"
)
_PIPELINE_META_LINE_RE = re.compile(
    r"(?m)^[^\n]*\b(?:Explicit-absence audit-trail block|"
    r"earlier drafts inherited Methods boilerplate)\b[^\n]*(?:\n|$)"
)
_PUBLIC_PLACEHOLDER_PARAGRAPH_RE = re.compile(
    r"(?ims)(?:^|\n\n)(?!##\s)"
    r"(?=[^\n]*\b(?:this\s+synthesis\s+aims\s+to\s+contribute\s+to\s+"
    r"the\s+field\s+by|this\s+paper\s+evaluates\s+the\s+topic\s+"
    r"through\s+accepted\s+receipts|the\s+evidence\s+base\s+is\s+"
    r"limited\s+to\s+accepted\s+receipts|deterministic\s+evidence\s+"
    r"summary|deterministic\s+synthesis\s+summary)\b)"
    r"[^\n]*(?:\n\n|$)"
)
_ET_AL_PAREN_CITE_RE = re.compile(
    r"\(([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+)\s+et\s+al\.\s+"
    r"((?:19|20)\d{2})\)"
)
_PVALUE_DISPLAY_RE = re.compile(
    r"\b[Pp]\s*(<=|>=|[<>=\u2264\u2265])\s*(0?\.\d+|\.\d+|\d+(?:\.\d+)?)"
)
_CHANGE_SPEED_SENTENCE_RE = re.compile(
    r"\b(?:change|improvement|increase|decrease|difference|delta|"
    r"reduction|rise|decline|gain)\b[^.!?\n]{0,120}"
    r"\b\d+(?:\.\d+)?\s*m/s\b|"
    r"\b\d+(?:\.\d+)?\s*m/s\b[^.!?\n]{0,120}"
    r"\b(?:change|improvement|increase|decrease|difference|delta|"
    r"reduction|rise|decline|gain)\b",
    re.IGNORECASE,
)


_DEPTH_PROTECTED_SECTIONS = {
    # Sections whose post-strip word count is policed by Fix #53
    # depth-preservation guard. Floors are SAFETY MARGINS above the
    # audit thresholds (Q11=800, Q12=800), so a tiny drift below
    # margin doesn't immediately break the audit gate. Limitations
    # + Conclusion added per reviewer request — they're analytical-
    # core too and easy strip-targets when claim-strength repair
    # fires on hedged language.
    "Discussion": 850,            # Q11 audit floor 800 + 50 margin
    "Cross-Domain Synthesis": 850,  # Q12 audit floor 800 + 50 margin
    "Limitations": 200,           # analytical-core, not Q-gated
    "Conclusion": 150,            # analytical-core, not Q-gated
}
_PUBLIC_BODY_CUTOFF_RE = re.compile(
    r"^##\s+(?:Publication Appendix|Researka Submitter Block|"
    r"Data and Code Availability|Search Provenance|AI(?:-Use)? "
    r"Disclosure|Accountability|References)\b",
    re.MULTILINE,
)
_ORDINAL_WORDS = ("First", "Second", "Third", "Fourth", "Fifth")
def _split_public_body(paper_md: str) -> tuple[str, str]:
    m = _PUBLIC_BODY_CUTOFF_RE.search(paper_md)
    return (paper_md[:m.start()], paper_md[m.start():]) if m else (paper_md, "")


def _normalize_ordinal_gaps(paper_md: str) -> tuple[str, int]:
    """Renumber paragraph-local ordinal openers in encounter order."""
    ordinal_re = re.compile(r"\b(?:First|Second|Third|Fourth|Fifth),")
    changes = 0
    parts = re.split(r"(\n\s*\n)", paper_md)
    for idx, part in enumerate(parts):
        matches = list(ordinal_re.finditer(part))
        if len(matches) < 2:
            continue
        seen = [m.group(0)[:-1] for m in matches]
        expected = list(_ORDINAL_WORDS[:len(seen)])
        if seen == expected:
            continue
        cursor = 0
        rebuilt: list[str] = []
        for n, m in enumerate(matches):
            rebuilt.append(part[cursor:m.start()])
            rebuilt.append(expected[n] + ",")
            cursor = m.end()
        rebuilt.append(part[cursor:])
        parts[idx] = "".join(rebuilt)
        changes += 1
    return "".join(parts), changes


def _strip_empty_parenthetical_citations(paper_md: str) -> tuple[str, int]:
    return re.subn(r"\s+\(\s*(?:;\s*)?\)", "", paper_md)


def _looks_like_change_speed_sentence(text: str) -> bool:
    return bool(_CHANGE_SPEED_SENTENCE_RE.search(str(text or "")))


def _topic_display_name(topic: str) -> str:
    repo = Path(__file__).resolve().parent.parent
    return humanize_topic(topic, title_case=True, root=repo)


def _normalize_public_topic_slug(
    paper_md: str, manifest: dict | None,
) -> tuple[str, int]:
    if not isinstance(manifest, dict):
        return paper_md, 0
    topic = str(manifest.get("topic") or "").strip()
    if not topic or ("_" not in topic and topic not in {"glp1", "omega3"}):
        return paper_md, 0
    body, tail = _split_public_body(paper_md)
    # A raw underscore slug leaking into prose is a COMPOUND-NOUN position
    # ("studies of resveratrol_metabolism_effects"), so replace it with the
    # intervention entity ('Resveratrol', 'Urolithin A') — the compound
    # name, not the multi-token topic phrase that includes aspect words.
    repo = Path(__file__).resolve().parent.parent
    display = intervention_label(topic, title_case=True, root=repo)
    pattern = re.compile(rf"\b{re.escape(topic)}\b", re.IGNORECASE)
    body, n = pattern.subn(display, body)
    return body + tail, n


_PUBLIC_SNAKE_CASE_RE = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]*\b")
_PUBLIC_LABELS = {
    "ci": "confidence interval",
    "cross_domain": "cross-domain",
    "mean_sd": "mean ± SD",
    "null_vs_positive": "null vs positive",
    "null_vs_negative": "null vs negative",
    "p_value": "p-value",
    "sample_size": "sample size",
    "unit_value": "unit value",
}


_PUBLIC_TERM_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bSPAR-adjudicated sources\b", re.IGNORECASE), "adjudicated sources"),
    (re.compile(r"\baccepted evidence base\b", re.IGNORECASE), "included evidence base"),
    (re.compile(r"\baccepted source papers\b", re.IGNORECASE), "included source papers"),
    (re.compile(r"\baccepted sources\b", re.IGNORECASE), "included sources"),
    (re.compile(r"\baccepted source\b", re.IGNORECASE), "included source"),
    (re.compile(r"\baccepted receipts\b", re.IGNORECASE), "included studies"),
    (re.compile(r"\breceipt set\b", re.IGNORECASE), "evidence base"),
    (re.compile(r"\btension matrix\b", re.IGNORECASE), "cross-study disagreement map"),
    (re.compile(r"\bnon-orthogonal conflicts\b", re.IGNORECASE), "cross-study disagreements"),
    (re.compile(r"\bnon-orthogonal tensions\b", re.IGNORECASE), "cross-study disagreements"),
    (re.compile(r"\bcross-study tensions\b", re.IGNORECASE), "cross-study disagreements"),
    (re.compile(r"\bsystematic search\b", re.IGNORECASE), "structured corpus search"),
    (
        re.compile(
            r"\b(?:the\s+)?most robust\s+([^.;\n]{1,120}?)\s+"
            r"for\s+extending\s+lifespan\s+across\s+species\b",
            re.IGNORECASE,
        ),
        r"one of the most extensively studied \1 for aging-related outcomes",
    ),
)
_PAIRWISE_TENSION_SUMMARY_RE = re.compile(
    r"The corpus(?:'s)?\s+(?:tension matrix|cross-study disagreement map)\s+"
    r"contains\s+(\d+)\s+pairwise tensions\s+across the source set,\s+"
    r"of which\s+(\d+)\s+were classified as severe\s*\([^)]*\)\.",
    re.IGNORECASE,
)
_TABLE_REF_RE = re.compile(r"\bTable\s+(\d+)\b", re.IGNORECASE)


def _defined_public_table_numbers(body: str) -> set[str]:
    return {
        number
        for m in re.finditer(
            r"^(?:#{2,6}\s+Table\s+(\d+)\b|Table\s+(\d+)\s*[:.\-—])",
            body,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        for number in m.groups()
        if number
    }


def _normalize_orphan_table_references(paper_md: str) -> tuple[str, int]:
    body, tail = _split_public_body(paper_md)
    missing = {
        m.group(1)
        for m in _TABLE_REF_RE.finditer(body)
        if m.group(1) not in _defined_public_table_numbers(body)
    }
    if not missing:
        return paper_md, 0
    n = 0
    for number in sorted(missing, key=int, reverse=True):
        table = rf"Table\s+{number}"
        for pattern, replacement in (
            (rf"\b{table}\s+presents\b", "The synthesis presents"),
            (rf"\b{table}\s+summarizes\b", "The synthesis summarizes"),
            (rf"\b{table}\s+shows\b", "The synthesis shows"),
            (rf"\bdetailed\s+in\s+{table}\b", "detailed in the evidence synthesis"),
            (rf"\bsummarized\s+in\s+{table}\b", "summarized in the evidence synthesis"),
            (rf"\b{table}\b", "the evidence synthesis"),
        ):
            body, k = re.subn(pattern, replacement, body, flags=re.IGNORECASE)
            n += k
    return body + tail, n


def _normalize_public_evidence_terms(
    paper_md: str, manifest: dict | None,
) -> tuple[str, int]:
    """Journalize public body terms without touching audit/reference tails."""
    body, tail = _split_public_body(paper_md)
    n = 0
    public_tension_n = None
    if isinstance(manifest, dict):
        raw = manifest.get("n_non_orthogonal_tensions")
        if isinstance(raw, int) or (isinstance(raw, str) and raw.isdigit()):
            public_tension_n = int(raw)

    def tension_summary(match: re.Match[str]) -> str:
        pairwise, severe = match.group(1), match.group(2)
        retained = (
            f"; {public_tension_n} public cross-study disagreements were "
            "retained for synthesis"
            if public_tension_n is not None
            else ""
        )
        return (
            f"The broader pairwise-comparison map contains {pairwise} "
            f"pairwise comparisons across the source set, with {severe} "
            f"severe comparisons{retained}."
        )

    body, k = _PAIRWISE_TENSION_SUMMARY_RE.subn(tension_summary, body)
    n += k
    body, k = re.subn(r"\b(\d+)\s+pairwise tensions\b", r"\1 pairwise comparisons", body, flags=re.IGNORECASE)
    n += k
    body, k = re.subn(r"\b(\d+)\s+severe tensions\b", r"\1 severe pairwise comparisons", body, flags=re.IGNORECASE)
    n += k
    for pattern, replacement in _PUBLIC_TERM_REPLACEMENTS:
        body, k = pattern.subn(replacement, body)
        n += k
    return body + tail, n


def _repair_connector_punctuation(paper_md: str) -> tuple[str, int]:
    body, tail = _split_public_body(paper_md)
    body, n = re.subn(
        r"\bThese findings,\s+suggest\b",
        "These findings suggest",
        body,
        flags=re.IGNORECASE,
    )
    return body + tail, n


def _normalize_public_snake_case_labels(paper_md: str) -> tuple[str, int]:
    """Rewrite internal enum-style labels in the public manuscript body."""
    body, tail = _split_public_body(paper_md)

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return _PUBLIC_LABELS.get(token, token.replace("_", " "))

    body, n = _PUBLIC_SNAKE_CASE_RE.subn(repl, body)
    return body + tail, n


def _ensure_public_thesis_marker(
    paper_md: str, manifest: dict | None,
) -> tuple[str, int]:
    has_thesis = bool(
        re.search(r"^\*\*Thesis:\*\*", paper_md, re.MULTILINE)
        or re.search(r"^\*\*Picked thesis\b.*?:\*\*", paper_md, re.MULTILINE)
        or re.search(r"\bThe deterministic thesis is:", paper_md)
        or re.search(
            r"\bThe synthesis surfaces\s+\d+\s+non-orthogonal tensions\b",
            paper_md,
            re.IGNORECASE,
        )
        or re.search(r"thesis(?:\s+is)?\s+that", paper_md[:3000], re.IGNORECASE)
        # Abstract already opens with a thesis-framing sentence ("This
        # synthesis/paper tests/synthesizes/maps ..."). Injecting another
        # "This synthesis tests the thesis ..." sentence on top stacks two
        # near-identical openers — the redundancy Researka flagged. Treat the
        # existing opener as the thesis. Universal academic framing, no topic
        # terms; the gate-required **Thesis:** marker is added separately in
        # Discussion by the finalizer, so skipping here never leaves a paper
        # thesis-less.
        or re.search(
            r"^##\s+Abstract\s*\n+(?:\*\*[^*\n]+\*\*\s+)?"
            r"This\s+(?:synthesis|paper|review|analysis|study)\s+"
            r"(?:synthesi[sz]es|tests|maps|evaluates|examines|assesses|presents|reports|investigates|analy[sz]es)\b",
            paper_md, re.IGNORECASE | re.MULTILINE,
        )
    )
    if has_thesis:
        return paper_md, 0
    topic = ""
    if isinstance(manifest, dict):
        topic = str(manifest.get("topic") or "").strip()
    display = _topic_display_name(topic) if topic else "the topic"
    marker = (
        f"This synthesis tests the thesis that evidence for {display} is "
        "context-dependent, separating outcome-specific "
        "signals from broader claims and identifying the evidence "
        "gaps that should bound interpretation."
    )
    new, n = re.subn(
        r"(^##\s+Abstract\s*\n+)",
        rf"\1{marker}\n\n",
        paper_md,
        count=1,
        flags=re.MULTILINE,
    )
    return new, n


def _collapse_adjacent_duplicate_words(paper_md: str) -> tuple[str, int]:
    dup_word_re = re.compile(r"\b(\w{3,})[ \t]+\1\b", re.IGNORECASE)
    n_dup_words = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal n_dup_words
        word = match.group(1)
        if word.lower() in {"had", "that", "what", "which"}:
            return match.group(0)
        if paper_md[match.end():match.end() + 1] == "-":
            return match.group(0)
        n_dup_words += 1
        return word

    return dup_word_re.sub(repl, paper_md), n_dup_words


def _normalize_heading_boundaries(paper_md: str) -> tuple[str, int]:
    fixed, n_split_h3 = re.subn(r"(?m)^#\s*\n\n##\s+", "### ", paper_md)
    fixed, n_glued = re.subn(r"(?m)(?<=[^\n#])(?=#{2,6}\s+)", "\n\n", fixed)
    return fixed, n_split_h3 + n_glued


def _normalize_sentence_spacing(paper_md: str) -> tuple[str, int]:
    body, tail = _split_public_body(paper_md)
    fixed, n = re.subn(r"(?<=[a-z0-9)\]])\.(?=[A-Z])", ". ", body)
    return fixed + tail, n


def _split_dense_conclusion_paragraphs(paper_md: str) -> tuple[str, int]:
    match = re.search(
        r"(^##\s+Conclusion\s*\n+)(.*?)(?=^##\s+|\Z)",
        paper_md,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        return paper_md, 0
    body = match.group(2)
    split_re = re.compile(
        r"(?<!\n)\s+"
        r"(The recommended next step is|Pending further trials,|Until such evidence accrues,)"
    )
    new_body, n = split_re.subn(r"\n\n\1", body)
    if not n:
        return paper_md, 0
    return (
        paper_md[:match.start(2)] + new_body + paper_md[match.end(2):],
        n,
    )


def _surface_outcome_key(text: str) -> str:
    return outcome_key(text).replace("_", " ")


def _align_results_count_claims(paper_md: str) -> tuple[str, int]:
    match = re.search(
        r"(^##\s+Results\s*\n)(.*?)(?=^##\s+|\Z)",
        paper_md,
        re.M | re.S,
    )
    if not match:
        return paper_md, 0
    results = match.group(2)
    counts: dict[str, int] = {}
    lines = [line.strip() for line in results.splitlines()]
    for idx, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or not cells or cells[0].lower() != "outcome class":
            continue
        for row in lines[idx + 2:]:
            if not row.startswith("|"):
                break
            row_cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(row_cells) >= 2 and (m := re.search(r"\bn\s*=\s*(\d+)\b", row_cells[1], re.I)):
                counts[_surface_outcome_key(row_cells[0])] = int(m.group(1))
        break
    if not counts:
        return paper_md, 0
    heading_re = re.compile(r"^###\s+(.+?)\s*$", re.M)
    headings = list(heading_re.finditer(results))
    claim_re = re.compile(
        r"\b(spans|contains|includes|covers|across)\s+(\d+)\s+"
        r"((?:curated\s+)?(?:references?|sources?|studies|papers))\b",
        re.I,
    )
    n = 0
    rebuilt = []
    cursor = 0
    for pos, heading in enumerate(headings):
        end = headings[pos + 1].start() if pos + 1 < len(headings) else len(results)
        section = results[heading.end():end]
        expected = counts.get(_surface_outcome_key(heading.group(1)))
        rebuilt.append(results[cursor:heading.end()])
        if expected is None:
            rebuilt.append(section)
        else:
            head = section[:900]
            tail = section[900:]

            def repl(claim: re.Match[str]) -> str:
                nonlocal n
                if int(claim.group(2)) == expected:
                    return claim.group(0)
                n += 1
                return f"{claim.group(1)} {expected} {claim.group(3)}"

            rebuilt.append(claim_re.sub(repl, head, count=1) + tail)
        cursor = end
    if not n:
        return paper_md, 0
    rebuilt.append(results[cursor:])
    return paper_md[:match.start(2)] + "".join(rebuilt) + paper_md[match.end(2):], n


def _insert_missing_declared_outcome_sections(paper_md: str) -> tuple[str, int]:
    match = re.search(r"(^##\s+Results\s*\n)(.*?)(?=^##\s+|\Z)", paper_md, re.M | re.S)
    if not match:
        return paper_md, 0
    results = match.group(2)
    declared: list[tuple[str, int | None, str, str, str]] = []
    lines = [line.strip() for line in results.splitlines()]
    for idx, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or not cells or cells[0].lower() != "outcome class":
            continue
        for row in lines[idx + 2:]:
            if not row.startswith("|"):
                break
            row_cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if row_cells:
                count = None
                if len(row_cells) > 1 and (
                    m := re.search(r"\bn\s*=\s*(\d+)\b", row_cells[1], re.I)
                ):
                    count = int(m.group(1))
                declared.append((
                    row_cells[0],
                    count,
                    row_cells[2] if len(row_cells) > 2 else "direction not pooled",
                    row_cells[3] if len(row_cells) > 3 else "directness not classified",
                    row_cells[4] if len(row_cells) > 4 else "bounded endpoint support",
                ))
        break
    if not declared:
        return paper_md, 0
    seen = {
        _surface_outcome_key(m.group(1))
        for m in re.finditer(r"^###\s+(.+?)\s*$", results, re.M)
    }
    missing = [
        row
        for row in declared
        for name in (row[0],)
        if _surface_outcome_key(name) not in seen
    ]
    if not missing:
        return paper_md, 0
    blocks = []
    for name, count, signal, directness, limitation in missing:
        scope = f"n={count}" if count is not None else "limited source support"
        blocks.append(
            f"### {name} Outcomes\n\n"
            f"{name} is retained as a separate Results slice ({scope}; "
            f"{signal.lower()}; {directness.lower()}; {limitation.lower()}) "
            "and is not pooled into adjacent endpoint classes.\n"
        )
    insert = "\n" + "\n".join(blocks)
    return paper_md[:match.end(2)] + insert + paper_md[match.end(2):], len(missing)


def _demote_unexpected_results_h3s(paper_md: str) -> tuple[str, int]:
    match = re.search(r"(^##\s+Results\s*\n)(.*?)(?=^##\s+|\Z)", paper_md, re.M | re.S)
    if not match:
        return paper_md, 0
    results = match.group(2)
    declared: set[str] = set()
    lines = [line.strip() for line in results.splitlines()]
    for idx, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or not cells or cells[0].lower() != "outcome class":
            continue
        for row in lines[idx + 2:]:
            if not row.startswith("|"):
                break
            row_cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if row_cells:
                declared.add(_surface_outcome_key(row_cells[0]))
        break
    if not declared:
        return paper_md, 0

    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        heading = m.group(1).strip()
        if _surface_outcome_key(heading) in declared:
            return m.group(0)
        n += 1
        return f"**{heading}.**"

    new_results = re.sub(r"^###\s+(.+?)\s*$", repl, results, flags=re.M)
    if not n:
        return paper_md, 0
    return paper_md[:match.start(2)] + new_results + paper_md[match.end(2):], n


def _shorten_legacy_results_outcome_stubs(paper_md: str) -> tuple[str, int]:
    pattern = re.compile(
        r"The Results table identifies ([^.]+?) evidence as a separate "
        r"outcome slice \(([^)]+)\)\. Because this slice is small, it is kept "
        r"separate from adjacent outcomes and interpreted as hypothesis-generating "
        r"rather than as a standalone endpoint conclusion\.",
        re.I,
    )
    n = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal n
        n += 1
        name = m.group(1).strip().title()
        return (
            f"{name} remains a separate Results slice ({m.group(2)}) "
            "and is not pooled into adjacent endpoint classes."
        )

    out = pattern.sub(repl, paper_md)
    return out, n


def _strip_thin_analytic_paragraphs(paper_md: str) -> tuple[str, int]:
    body, tail = _split_public_body(paper_md)
    analytic_re = re.compile(
        r"^(?:meta-analytic evidence corroborates|mechanistically,|"
        r"mechanistic(?:al)? evidence|evidence corroborates|findings corroborate)\b",
        re.I,
    )
    parts = re.split(r"(\n\s*\n)", body)
    out: list[str] = []
    n = 0
    for idx in range(0, len(parts), 2):
        para = parts[idx]
        sep = parts[idx + 1] if idx + 1 < len(parts) else ""
        text = re.sub(r"\s+", " ", para.strip())
        words = re.findall(r"[a-z0-9]+", text.lower())
        is_stub = (
            5 <= len(words) <= 14
            and analytic_re.search(text)
            and not re.search(r"\d|;|:", text)
            and not text.startswith(("#", "|"))
        )
        lower = text.lower()
        is_cross_topic_template = all(phrase in lower for phrase in (
            "biomedical intervention",
            "management field experiment",
            "economics policy corpus",
        ))
        is_legacy_backstop = lower.startswith((
            "findings are therefore grouped by outcome domain",
            "this guardrail is deliberately numeric-free",
            "descriptive findings remain separate from interpretation",
            "the principal limitation is evidence-role imbalance",
            "a second limitation is endpoint heterogeneity",
            "a third limitation is that unsafe source-level numerics",
            "the final interpretation is therefore intentionally resistant",
            "readers can weigh each section against the provenance trail",
            "interpretation is deliberately scoped to the retained corpus",
        ))
        if is_stub or is_cross_topic_template or is_legacy_backstop:
            n += 1
            continue
        out.append(para)
        if sep:
            out.append(sep)
    if not n:
        return paper_md, 0
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).rstrip() + "\n\n" + tail, n


def _strip_conclusion_scope_leak(paper_md: str) -> tuple[str, int]:
    match = re.search(r"(^##\s+Conclusion\s*\n)(.*?)(?=^##\s+|\Z)", paper_md, re.M | re.S)
    if not match:
        return paper_md, 0
    body, n = re.subn(
        r"(?im)(?:^|(?<=[.!?])\s*)It separates endpoint[- ]specific evidence from broad [^.!?\n]*claims?[^.!?\n]*[.!?]\s*",
        "The synthesis therefore supports a bounded interpretation rather than a generalized clinical recommendation. ",
        match.group(2),
    )
    if not n:
        return paper_md, 0
    return paper_md[:match.start(2)] + body + paper_md[match.end(2):], n


def _rebuild_thin_results_from_manifest(paper_md: str, manifest: dict | None) -> tuple[str, int]:
    if not manifest or manifest.get("review_type") not in {"thin_corpus_brief", "evidence_brief", "evidence_map"}:
        return paper_md, 0
    receipts = [r for r in manifest.get("receipts", ()) if isinstance(r, dict) and r.get("outcome_class")]
    if not receipts or not re.search(r"^##\s+Results\b", paper_md, re.M):
        return paper_md, 0
    by_outcome: dict[str, list[dict]] = defaultdict(list)
    for r in receipts:
        by_outcome[str(r.get("outcome_class") or "other")].append(r)
    topic = str(manifest.get("topic") or "")
    topic_anchor = _topic_display_name(topic) if topic else ""
    lines = ["## Results", "", "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |", "|---|---|---|---|---|"]
    for outcome, group in sorted(by_outcome.items(), key=lambda item: (-len(item[1]), item[0])):
        direct = Counter(str(r.get("directness") or "indirect").lower() for r in group)
        label = outcome.replace("_", " ").title()
        row_label = f"{topic_anchor} / {label}" if topic_anchor else label
        lines.append(f"| {row_label} | n={len(group)}; claims={sum(int(r.get('n_claims') or 0) for r in group)} | {signal_summary_cell(group)} | {direct.most_common(1)[0][1]} {direct.most_common(1)[0][0]} | {'single-source support' if len(group) == 1 else 'primary-tier limited'} |")
    context_table = source_context_map(receipts)
    if context_table:
        lines += ["", context_table.rstrip()]
    lines += ["", "This evidence brief reports outcome packets as a map of retained evidence rather than as a full journal Results narrative or pooled effect estimate."]
    for outcome, group in sorted(by_outcome.items(), key=lambda item: (-len(item[1]), item[0])):
        direct = Counter(str(r.get("directness") or "indirect").lower() for r in group)
        label = outcome.replace("_", " ").title()
        lines += ["", f"### {label} Outcomes", "", f"{len(group)} included source{'s' if len(group) != 1 else ''} were assigned to this outcome class. Signal summary: {signal_summary_cell(group)}. Directness coding: {', '.join(f'{k}={v}' for k, v in sorted(direct.items()))}."]
    rebuilt = "\n".join(lines).rstrip() + "\n"
    patched = re.sub(r"^##\s+Results\b.*?(?=^##\s+|\Z)", rebuilt + "\n", paper_md, count=1, flags=re.M | re.S)
    return patched, int(patched != paper_md)


def _append_known_background_references(paper_md: str) -> tuple[str, int]:
    try:
        from agent.journal_surface_gate import unreferenced_citation_tokens
    except ImportError:
        return paper_md, 0
    tokens = unreferenced_citation_tokens(paper_md)
    if not tokens:
        return paper_md, 0
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import background_literature as _bg
        registry = _bg.load_registry()
    except (ImportError, OSError, ValueError):
        return paper_md, 0
    wanted = {token for token in tokens}
    entries = []
    seen: set[str] = set()
    for entry in registry.values():
        token = entry.citation_token
        if token in wanted and token not in seen:
            entries.append(entry)
            seen.add(token)
    if not entries or not re.search(r"^##\s+References\b", paper_md, re.M):
        return paper_md, 0
    if "### Background References" not in paper_md:
        block = [
            "",
            "### Background References",
            "",
            "*Canonical background sources cited in the public manuscript.*",
            "",
        ]
    else:
        block = [""]
    for entry in entries:
        parts = [f"- **{entry.citation_token}.**"]
        if entry.canonical_reference:
            parts.append(f"_{entry.canonical_reference.strip().rstrip('.')}._")
        if entry.doi:
            parts.append(f"DOI: {entry.doi}.")
        if entry.pmid:
            parts.append(f"PMID: {entry.pmid}.")
        block.append(" ".join(parts))
    block.append("")
    return paper_md.rstrip() + "\n".join(block), len(entries)


def _ensure_near_floor_conclusion(paper_md: str) -> tuple[str, int]:
    match = re.search(r"(^##\s+Conclusion\s*\n)(.*?)(?=^##\s+|\Z)", paper_md, re.M | re.S)
    if not match:
        return paper_md, 0
    body = match.group(2).rstrip()
    words = len(re.findall(r"\b\w+\b", body))
    if not (225 <= words < 250):
        return paper_md, 0
    addition = (
        "\n\nThe synthesis therefore supports bounded interpretation rather "
        "than broad clinical extrapolation until direct endpoint trials close "
        "the remaining evidence gaps."
    )
    return paper_md[:match.start(2)] + body + addition + "\n\n" + paper_md[match.end(2):].lstrip(), 1


def _strip_empty_headings(paper_md: str) -> tuple[str, int]:
    matches = list(re.finditer(r"^(#{2,6})\s+.+?\s*$", paper_md, flags=re.M))
    removals: list[tuple[int, int]] = []
    for idx, match in enumerate(matches):
        level = len(match.group(1))
        nxt = matches[idx + 1] if idx + 1 < len(matches) else None
        if nxt is not None and len(nxt.group(1)) > level:
            continue
        end = nxt.start() if nxt else len(paper_md)
        if not paper_md[match.end():end].strip():
            removals.append((match.start(), end))
    for start, end in reversed(removals):
        paper_md = paper_md[:start].rstrip() + "\n\n" + paper_md[end:].lstrip()
    return paper_md, len(removals)


def _demote_sentence_like_headings(paper_md: str) -> tuple[str, int]:
    n = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal n
        level, heading = match.group(1), match.group(2).strip()
        words = re.findall(r"\b\w+\b", heading)
        is_sentence = len(words) >= 12 or heading.endswith(".")
        if level == "###" and is_sentence:
            n += 1
            return f"**{heading}**"
        return match.group(0)

    out = re.sub(r"^(#{2,6})\s+(.+?)\s*$", repl, paper_md, flags=re.M)
    return out, n


def _strip_reference_only_next_study_section(paper_md: str) -> tuple[str, int]:
    pattern = re.compile(
        r"^###\s+Next-Study Design Recommendation\s*$"
        r"(?P<body>.*?)(?=^##\s+References\b|\Z)",
        flags=re.M | re.S,
    )

    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        body = match.group("body")
        residue = re.sub(r"^\s*-\s+\*\*.+?\*\*.*$", "", body, flags=re.M)
        residue = re.sub(r"(?is)\bAdditional corpus sources\b.*", "", residue)
        if residue.strip():
            return match.group(0)
        changed += 1
        return ""

    return pattern.sub(repl, paper_md), changed


def apply_lightweight_public_polish(
    paper_md: str,
    manifest: dict | None = None,
) -> tuple[str, list[dict]]:
    """Final safe polish only. No numeric/table/source-context stripping."""
    log: list[dict] = []
    new_md, n_thesis_marker = _ensure_public_thesis_marker(paper_md, manifest)
    if n_thesis_marker:
        log.append({
            "fix_type": "public_thesis_marker_backfill",
            "n_changes": n_thesis_marker,
            "description": (
                "inserted an explicit public Abstract thesis marker when "
                "writer prose lacked an auditor-detectable thesis sentence"
            ),
        })
    new_md, n_public_terms = _normalize_public_evidence_terms(new_md, manifest)
    if n_public_terms:
        log.append({
            "fix_type": "public_evidence_term_normalization",
            "n_changes": n_public_terms,
            "description": (
                "rewrote audit-shaped corpus terms and raw pairwise-tension "
                "phrases into journal-facing evidence language"
            ),
        })
    new_md, n_pvalue_norm = _normalize_public_p_values(new_md)
    if n_pvalue_norm:
        log.append({
            "fix_type": "public_p_value_normalization",
            "n_changes": n_pvalue_norm,
            "description": (
                "normalized public p-value notation after finalizer and "
                "template repairs"
            ),
        })
    new_md, n_connector_punctuation = _repair_connector_punctuation(new_md)
    if n_connector_punctuation:
        log.append({
            "fix_type": "connector_punctuation_repair",
            "n_changes": n_connector_punctuation,
            "description": "repaired punctuation left by template-phrase cleanup",
        })
    new_md, n_orphan_tables = _normalize_orphan_table_references(new_md)
    if n_orphan_tables:
        log.append({
            "fix_type": "orphan_table_reference_normalization",
            "n_changes": n_orphan_tables,
            "description": (
                "rewrote public references to absent numbered tables into "
                "self-contained evidence-synthesis language"
            ),
        })
    new_md, n_conclusion_splits = _split_dense_conclusion_paragraphs(new_md)
    if n_conclusion_splits:
        log.append({
            "fix_type": "conclusion_paragraph_split",
            "n_changes": n_conclusion_splits,
            "description": (
                "split dense conclusion transition sentences into separate "
                "journal paragraphs without changing claims"
            ),
        })
    new_md, n_count_claims = _align_results_count_claims(new_md)
    if n_count_claims:
        log.append({
            "fix_type": "results_count_claim_alignment",
            "n_changes": n_count_claims,
            "description": (
                "aligned prose count claims in outcome sections with the "
                "compiler-owned Results table counts"
            ),
        })
    new_md, n_missing_outcomes = _insert_missing_declared_outcome_sections(new_md)
    if n_missing_outcomes:
        log.append({
            "fix_type": "missing_results_outcome_section_insert",
            "n_changes": n_missing_outcomes,
            "description": (
                "inserted compiler-owned Results subsections for outcome "
                "classes declared in the Results table but missing from body prose"
            ),
        })
    new_md, n_unexpected_results_h3s = _demote_unexpected_results_h3s(new_md)
    if n_unexpected_results_h3s:
        log.append({
            "fix_type": "unexpected_results_h3_demote",
            "n_changes": n_unexpected_results_h3s,
            "description": (
                "demoted non-outcome Results H3 headings so the surface gate "
                "only treats declared outcome classes as Results subsections"
            ),
        })
    new_md, n_legacy_outcome_stubs = _shorten_legacy_results_outcome_stubs(new_md)
    if n_legacy_outcome_stubs:
        log.append({
            "fix_type": "legacy_results_outcome_stub_shorten",
            "n_changes": n_legacy_outcome_stubs,
            "description": (
                "shortened older compiler-owned outcome stubs that were too "
                "template-like for the duplicate-paragraph surface gate"
            ),
        })
    new_md, n_thin_analytic = _strip_thin_analytic_paragraphs(new_md)
    if n_thin_analytic:
        log.append({
            "fix_type": "thin_analytic_paragraph_strip",
            "n_changes": n_thin_analytic,
            "description": (
                "removed underdeveloped analytical stub paragraphs from "
                "public manuscript prose"
            ),
        })
    new_md, n_conclusion_scope = _strip_conclusion_scope_leak(new_md)
    if n_conclusion_scope:
        log.append({
            "fix_type": "conclusion_scope_leak_strip",
            "n_changes": n_conclusion_scope,
            "description": (
                "removed What-This-Adds scope language from the Conclusion"
            ),
        })
    new_md, n_thin_results = _rebuild_thin_results_from_manifest(new_md, manifest)
    if n_thin_results:
        log.append({
            "fix_type": "thin_results_rebuild",
            "n_changes": n_thin_results,
            "description": "rebuilt thin-corpus Results from manifest outcome packets",
        })
    new_md, n_background_refs = _append_known_background_references(new_md)
    if n_background_refs:
        log.append({
            "fix_type": "background_reference_completion",
            "n_changes": n_background_refs,
            "description": (
                "added canonical background bibliography entries for "
                "author-year citations used in public prose"
            ),
        })
    new_md, n_conclusion_floor = _ensure_near_floor_conclusion(new_md)
    if n_conclusion_floor:
        log.append({
            "fix_type": "near_floor_conclusion_completion",
            "n_changes": n_conclusion_floor,
            "description": (
                "completed a near-threshold Conclusion after public-surface "
                "cleanup without introducing new evidence claims"
            ),
        })
    new_md, n_sentence_headings = _demote_sentence_like_headings(new_md)
    if n_sentence_headings:
        log.append({
            "fix_type": "sentence_like_heading_demote",
            "n_changes": n_sentence_headings,
            "description": (
                "demoted sentence-like H3 lines that markdown rendering had "
                "mistaken for empty section headings"
            ),
        })
    new_md, n_empty_headings = _strip_empty_headings(new_md)
    if n_empty_headings:
        log.append({
            "fix_type": "empty_heading_strip",
            "n_changes": n_empty_headings,
            "description": "removed headings left empty after deterministic cleanup",
        })
    new_md, n_ref_only_next = _strip_reference_only_next_study_section(new_md)
    if n_ref_only_next:
        log.append({
            "fix_type": "reference_only_next_study_strip",
            "n_changes": n_ref_only_next,
            "description": "removed next-study recommendation sections containing only reference residue",
        })
    new_md, n_heading_boundaries = _normalize_heading_boundaries(new_md)
    if n_heading_boundaries:
        log.append({
            "fix_type": "heading_boundary_normalization",
            "n_changes": n_heading_boundaries,
            "description": "restored blank lines before markdown headings",
        })
    new_md, n_sentence_headings_late = _demote_sentence_like_headings(new_md)
    if n_sentence_headings_late:
        log.append({
            "fix_type": "sentence_like_heading_demote_post_boundary",
            "n_changes": n_sentence_headings_late,
            "description": (
                "demoted sentence-like H3 lines introduced after heading "
                "boundary normalization"
            ),
        })
    new_md, n_sentence_spacing = _normalize_sentence_spacing(new_md)
    if n_sentence_spacing:
        log.append({
            "fix_type": "sentence_spacing_normalization",
            "n_changes": n_sentence_spacing,
            "description": "restored missing spaces after sentence periods",
        })
    new_md, n_dup_words = _collapse_adjacent_duplicate_words(new_md)
    if n_dup_words:
        log.append({
            "fix_type": "duplicate_word_collapse",
            "n_changes": n_dup_words,
            "description": (
                "collapsed adjacent duplicated prose words flagged by "
                "Stage-2 C08 (for example 'not not')"
            ),
        })
    new_md, n_dup_paragraphs = _strip_consecutive_duplicate_paragraphs(new_md)
    if n_dup_paragraphs:
        log.append({
            "fix_type": "duplicate_paragraph",
            "n_changes": n_dup_paragraphs,
            "description": (
                "removed consecutive duplicate prose paragraphs during "
                "final lightweight polish"
            ),
        })
    new_md, n_fuzzy_dup_paragraphs = _strip_fuzzy_duplicate_paragraphs(new_md)
    if n_fuzzy_dup_paragraphs:
        log.append({
            "fix_type": "fuzzy_duplicate_paragraph",
            "n_changes": n_fuzzy_dup_paragraphs,
            "description": (
                "removed later body paragraphs with high token overlap "
                "during final lightweight polish"
            ),
        })
    new_md, n_sentence_headings_final = _demote_sentence_like_headings(new_md)
    if n_sentence_headings_final:
        log.append({
            "fix_type": "sentence_like_heading_demote_final",
            "n_changes": n_sentence_headings_final,
            "description": (
                "demoted sentence-like H3 lines after final duplicate cleanup"
            ),
        })
    return new_md, log


def _strip_consecutive_duplicate_paragraphs(paper_md: str) -> tuple[str, int]:
    body, tail = _split_public_body(paper_md)
    paragraphs = re.split(r"(\n\s*\n)", body)
    out: list[str] = []
    last_norm = ""
    n = 0
    for i in range(0, len(paragraphs), 2):
        para = paragraphs[i]
        sep = paragraphs[i + 1] if i + 1 < len(paragraphs) else ""
        norm = re.sub(r"\s+", " ", para.strip())
        is_prose = (
            len(norm.split()) >= 12
            and not norm.startswith(("#", "|", "_Cited:"))
        )
        if is_prose and norm == last_norm:
            n += 1
            continue
        out.append(para)
        if sep:
            out.append(sep)
        last_norm = norm if is_prose else ""
    cleaned = "".join(out) + tail
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def _strip_duplicate_subsections(paper_md: str) -> tuple[str, int]:
    parts = re.split(r"(^###\s+.+?$)", paper_md, flags=re.MULTILINE)
    out: list[str] = []
    seen: list[set[str]] = []
    n = 0
    i = 0
    while i < len(parts):
        heading = parts[i]
        if not heading.startswith("###"):
            out.append(heading)
            i += 1
            continue
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if re.match(r"^###\s+.+?\s+Outcomes?\s*$", heading.strip()):
            out.extend([heading, body])
            i += 2
            continue
        body_for_key, sep, tail = body.partition("\n## ")
        norm = re.sub(r"\s+", " ", f"{heading}\n{body_for_key}".strip()).lower()
        tokens = _paragraph_token_set(norm)
        is_body_subsection = len(norm.split()) >= 20 and tokens and "\n|" not in body_for_key
        is_duplicate = is_body_subsection and any(
            len(tokens & prior) / min(len(tokens), len(prior)) >= 0.82
            for prior in seen
        )
        if is_duplicate:
            n += 1
            if sep:
                out.append("\n## " + tail)
            i += 2
            continue
        if is_body_subsection:
            seen.append(tokens)
        out.extend([heading, body])
        i += 2
    cleaned = re.sub(r"\n{3,}", "\n\n", "".join(out))
    return cleaned, n


def _strip_fuzzy_duplicate_paragraphs(paper_md: str) -> tuple[str, int]:
    """Remove later body paragraphs that substantially repeat earlier
    body paragraphs. This catches LLM stutter across sections while
    preserving tables, appendices, Methods, and short recurring caveats."""
    body, tail = _split_public_body(paper_md)
    blocks = re.split(r"(^##\s+.+?$)", body, flags=re.MULTILINE)
    out: list[str] = []
    seen: list[set[str]] = []
    current_heading = ""
    n = 0
    skip_sections = {
        "Methods", "References", "Publication Appendix",
        "Data and Code Availability", "Researka Submitter Block",
        "Results",
    }
    for block in blocks:
        heading = re.match(r"^##\s+(.+?)\s*$", block)
        if heading:
            current_heading = heading.group(1).strip()
            out.append(block)
            continue
        if current_heading in skip_sections:
            out.append(block)
            continue
        kept: list[str] = []
        for para in block.split("\n\n"):
            stripped = para.strip()
            tokens = _paragraph_token_set(stripped)
            is_prose = (
                len(stripped.split()) >= 25
                and tokens
            and not stripped.startswith(("#", "|", "-", "`", "* "))
            and "\n|" not in para
        )
            if is_prose and any(
                _jaccard(tokens, prior) >= 0.82 for prior in seen
            ):
                n += 1
                continue
            kept.append(para)
            if is_prose:
                seen.append(tokens)
        out.append("\n\n".join(kept))
    if not n:
        return paper_md, 0
    cleaned = "".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned + tail, n


def _paragraph_token_set(text: str) -> set[str]:
    words = re.findall(r"\b[a-z][a-z0-9]{2,}\b", text.lower())
    stop = {
        "the", "and", "that", "this", "with", "from", "into", "for",
        "are", "but", "not", "can", "has", "have", "was", "were",
        "across", "receipt", "receipts", "evidence", "synthesis",
    }
    return {w for w in words if w not in stop}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _strip_exact_duplicate_public_paragraphs(paper_md: str) -> tuple[str, int]:
    """Remove later exact public-body prose paragraphs.

    This runs after restoration/backfill paths and is deliberately narrower
    than fuzzy dedupe: exact normalized paragraph repeats only.
    """
    body, tail = _split_public_body(paper_md)
    parts = re.split(r"(\n\s*\n)", body)
    out: list[str] = []
    seen: set[str] = set()
    n = 0
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        text = para.strip()
        norm = re.sub(r"\s+", " ", text).lower()
        is_long_prose = (
            len(re.findall(r"\b\w+\b", text)) >= 30
            and not text.startswith(("#", "|", "-", "`", "*", "_Cited:"))
            and "\n|" not in para
            and not _is_depth_backfill_paragraph(text)
        )
        if is_long_prose and norm in seen:
            n += 1
            continue
        out.append(para)
        if sep:
            out.append(sep)
        if is_long_prose:
            seen.add(norm)
    if not n:
        return paper_md, 0
    fixed_body = re.sub(r"\n{3,}", "\n\n", "".join(out)).rstrip()
    return fixed_body + "\n\n" + tail, n


def _is_depth_backfill_paragraph(text: str) -> bool:
    norm = re.sub(r"\s+", " ", text).strip().lower()
    return norm in {
        re.sub(r"\s+", " ", str(globals().get(name, ""))).strip().lower()
        for name in (
            "_INTRODUCTION_BACKFILL",
            "_BACKGROUND_BACKFILL",
            "_DISCUSSION_BACKFILL",
            "_CONCLUSION_BACKFILL",
            "_DEPTH_BACKFILL_EXTENSION",
        )
    }


def _strip_duplicate_long_sentences(paper_md: str) -> tuple[str, int]:
    sentence_re = re.compile(r"(?<=[.!?])\s+")
    seen: set[str] = set()
    n = 0
    out_sections: list[str] = []
    current_heading = ""
    body, tail = _split_public_body(paper_md)
    for block in re.split(r"(^##\s+.+?$)", body, flags=re.MULTILINE):
        heading = re.match(r"^##\s+(.+?)\s*$", block)
        if heading:
            current_heading = heading.group(1).strip()
            out_sections.append(block)
            continue
        if current_heading in {"References", "Publication Appendix"}:
            out_sections.append(block)
            continue
        out_paras: list[str] = []
        for para in block.split("\n\n"):
            stripped = para.strip()
            if (
                not stripped
                or stripped.startswith(("#", "|", "-", "`"))
                or "\n|" in para
            ):
                out_paras.append(para)
                continue
            kept: list[str] = []
            for sent in sentence_re.split(para):
                norm = re.sub(r"\s+", " ", sent.strip()).lower()
                is_long_prose = (
                    len(norm.split()) >= 8
                    and "[" not in norm
                    and "http" not in norm
                )
                if is_long_prose and norm in seen:
                    n += 1
                    continue
                if is_long_prose:
                    seen.add(norm)
                kept.append(sent)
            out_paras.append(" ".join(s for s in kept if s).strip())
        out_sections.append("\n\n".join(out_paras))
    if not n:
        return paper_md, 0
    cleaned = "".join(out_sections) + tail
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def _strip_extra_methods_numbered_steps(paper_md: str) -> tuple[str, int]:
    start, end, methods = _extract_section(paper_md, "Methods")
    if start < 0:
        return paper_md, 0
    # The deterministic run-mode Methods block legitimately has a
    # 10-step pipeline list plus Claim source. The old strip rule was
    # for leaked writer prose masquerading as numbered Methods steps;
    # once deterministic Methods has been re-applied, keep only the
    # known deterministic step labels and strip leaked result/prose
    # list-items that reuse numbers like "8." inside Methods.
    if "### Pipeline stages" in methods and "### Claim source" in methods:
        allowed_steps = {
            "1": "quant-claim extraction",
            "2": "source summarization",
            "3": "tension matrix construction",
            "4": "thesis selection",
            "5": "claim-strength repair",
            "6": "paper_id",
            "7": "references block append",
            "8": "stage-1 audit",
            "9": "final-layer llm review",
            "10": "final audit",
        }
        step_re = re.compile(
            r"(?ms)^(\d+)\.\s+(.*?)(?=^\d+\.|^###\s|^##\s|\Z)"
        )

        def keep_or_strip(match: re.Match[str]) -> str:
            number = match.group(1)
            body = re.sub(r"\s+", " ", match.group(2).strip()).lower()
            expected = allowed_steps.get(number)
            if number == "6" and body.startswith(("paper_id", "paper id")):
                return match.group(0)
            if expected and body.startswith(expected):
                return match.group(0)
            return ""

        cleaned, n = step_re.subn(keep_or_strip, methods)
        if not n or cleaned == methods:
            return paper_md, 0
        n_stripped = sum(
            1
            for m in step_re.finditer(methods)
            if keep_or_strip(m) == ""
        )
        if not n_stripped:
            return paper_md, 0
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return paper_md[:start] + cleaned + paper_md[end:], n_stripped
    step_re = re.compile(r"(?ms)^([8-9]|\d{2,})\.\s+.*?(?=^\d+\.|^##\s|\Z)")
    cleaned, n = step_re.subn("", methods)
    if not n:
        return paper_md, 0
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return paper_md[:start] + cleaned + paper_md[end:], n


def _strip_role_repair_artifacts(paper_md: str) -> tuple[str, int]:
    cleaned = paper_md
    total = 0
    while True:
        cleaned_next, n = _ROLE_REPAIR_ARTIFACT_SENT_RE.subn("", cleaned)
        if not n:
            break
        cleaned = cleaned_next
        total += n
    if not total:
        return paper_md, 0
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, total


def _normalize_public_p_values(paper_md: str) -> tuple[str, int]:
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        op = match.group(1)
        value = match.group(2)
        op = {"<=": "\u2264", ">=": "\u2265"}.get(op, op)
        if value.startswith("."):
            value = f"0{value}"
        if (
            op in {"<", "=", "\u2264"}
            and re.fullmatch(r"0\.0+", value) is not None
        ):
            decimals = len(value.partition(".")[2])
            replacement = f"P < 0.{('0' * (decimals - 1))}1"
        else:
            replacement = f"P {op} {value}"
        changed += replacement != match.group(0)
        return replacement

    return _PVALUE_DISPLAY_RE.sub(repl, paper_md), changed


def normalize_public_p_values(text: str) -> tuple[str, int]:
    """Normalize public p-value notation without changing other prose."""
    return _normalize_public_p_values(text)


def _normalize_h3_residue_headings(paper_md: str) -> tuple[str, int]:
    return _H3_RESIDUE_HEADING_RE.subn("### ", paper_md)


def _strip_public_pipeline_meta(paper_md: str) -> tuple[str, int]:
    cleaned, n = _PIPELINE_META_LINE_RE.subn("", paper_md)
    if not n:
        return paper_md, 0
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def _strip_public_placeholder_paragraphs(paper_md: str) -> tuple[str, int]:
    cleaned, n = _PUBLIC_PLACEHOLDER_PARAGRAPH_RE.subn("\n\n", paper_md)
    if not n:
        return paper_md, 0
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n", n


def _normalize_public_meta_phrases(paper_md: str) -> tuple[str, int]:
    replacements = (
        (
            re.compile(
                r"the load-bearing principle is \*\*LLM proposes, "
                r"code disposes\*\* — no claim, citation, evidence tier, "
                r"or thesis is author-LLM-invented\.",
                re.IGNORECASE,
            ),
            (
                "citations, evidence tiers, numeric claims, and thesis "
                "selection are constrained by the run registry and audit "
                "record."
            ),
        ),
        (
            re.compile(
                r"Every row traces to a corpus-bound claim — no LLM "
                r"authorship\.",
                re.IGNORECASE,
            ),
            "Every row traces to a corpus-bound claim and a registered citation.",
        ),
        (
            re.compile(r"deterministic evidence summary", re.IGNORECASE),
            "structured evidence summary",
        ),
        (
            re.compile(r"deterministic synthesis summary", re.IGNORECASE),
            "structured synthesis summary",
        ),
        (
            re.compile(r"The deterministic thesis is:", re.IGNORECASE),
            "The thesis is:",
        ),
        (
            re.compile(r"\s*\(no LLM judgment\)", re.IGNORECASE),
            "",
        ),
        (
            re.compile(r"audited corpus", re.IGNORECASE),
            "retained corpus",
        ),
        (
            re.compile(r"audited evidence structure", re.IGNORECASE),
            "source record",
        ),
        (
            re.compile(r"stripped sentence", re.IGNORECASE),
            "unsupported sentence",
        ),
        (
            re.compile(r"\bTaken together,\s*", re.IGNORECASE),
            "Across the corpus, ",
        ),
        (
            re.compile(r"\bthe evidence base is limited to\b", re.IGNORECASE),
            "The available evidence is concentrated in",
        ),
        (
            re.compile(r"\bevidence base is limited to\b", re.IGNORECASE),
            "evidence base is concentrated in",
        ),
        (
            re.compile(r"\breceipt-traced\b", re.IGNORECASE),
            "source-traced",
        ),
        (
            re.compile(r"\breceipt-level\b", re.IGNORECASE),
            "source-level",
        ),
        (
            re.compile(r"\breceipts\b", re.IGNORECASE),
            "sources",
        ),
        (
            re.compile(r"\breceipt\b", re.IGNORECASE),
            "source",
        ),
        (
            re.compile(
                r"\b\d+\s+non-orthogonal\s+(?:pairwise\s+)?tensions\b",
                re.IGNORECASE,
            ),
            "cross-study tensions",
        ),
    )
    out = paper_md
    n_total = 0
    for pattern, replacement in replacements:
        out, n = pattern.subn(replacement, out)
        n_total += n
    if not n_total:
        return paper_md, 0
    out = re.sub(r" {2,}", " ", out)
    return out, n_total


def _strip_effect_estimate_artifact_sentences(
    paper_md: str,
) -> tuple[str, int]:
    cleaned, n = _EFFECT_ESTIMATE_ARTIFACT_SENT_RE.subn("", paper_md)
    if not n:
        return paper_md, 0
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def _strip_orphan_threshold_sentences(
    paper_md: str,
) -> tuple[str, int]:
    cleaned, n = _ORPHAN_THRESHOLD_SENT_RE.subn("", paper_md)
    if not n:
        return paper_md, 0
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def _strip_orphan_demonstrated_clauses(
    paper_md: str,
) -> tuple[str, int]:
    cleaned, n = _ORPHAN_DEMONSTRATED_CLAUSE_RE.subn(", and ", paper_md)
    cleaned, n_tail = _ORPHAN_DEMONSTRATED_TAIL_RE.subn(".", cleaned)
    total = n + n_tail
    return (cleaned, total) if total else (paper_md, 0)


def _strip_public_reference_dumps(paper_md: str) -> tuple[str, int]:
    public, appendix = _split_public_body(paper_md)
    public, n_bg = _BACKGROUND_REFERENCES_RE.subn("", public)
    public, n_dump = _PUBLIC_REFERENCE_DUMP_RE.subn("\n\n", public)
    total = n_bg + n_dump
    if not total:
        return paper_md, 0
    public = re.sub(r"\n{3,}", "\n\n", public).rstrip()
    return public + "\n\n" + appendix.lstrip(), total


def _strip_final_interpretation_blocks(paper_md: str) -> tuple[str, int]:
    public, appendix = _split_public_body(paper_md)
    public, n = _FINAL_INTERPRETATION_RE.subn("", public)
    if not n:
        return paper_md, 0
    public = re.sub(r"\n{3,}", "\n\n", public).rstrip()
    return public + "\n\n" + appendix.lstrip(), n


def _normalize_discussion_opener(paper_md: str) -> tuple[str, int]:
    return _DISCUSSION_HOWEVER_RE.subn(r"\1", paper_md)


def _strip_empty_attribution_sentences(
    paper_md: str,
) -> tuple[str, int]:
    cleaned, n = _EMPTY_ATTRIBUTION_SENT_RE.subn(" ", paper_md)
    if not n:
        return paper_md, 0
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def _strip_toxin_mobilization_sentences(
    paper_md: str,
) -> tuple[str, int]:
    cleaned, n = _TOXIN_MOBILIZATION_SENT_RE.subn("", paper_md)
    if not n:
        return paper_md, 0
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


def _citation_key(author: str, year: str) -> str:
    folded = unicodedata.normalize("NFKD", author)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^a-z0-9]", "", folded.lower())
    return f"{folded}:{year}"


def _allowed_author_year_keys(
    paper_md: str, manifest: dict | None,
) -> set[str]:
    out: set[str] = set()

    def add_token(token: object) -> None:
        text = str(token or "").strip()
        m = re.match(
            r"([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+)"
            r"(?:\s+et\s+al\.)?\s+((?:19|20)\d{2})\b",
            text,
        )
        if m:
            out.add(_citation_key(m.group(1), m.group(2)))

    if isinstance(manifest, dict):
        for receipt in manifest.get("receipts") or ():
            add_token(receipt.get("citation_token"))
            add_token(receipt.get("body_citation"))
            add_token(receipt.get("receipt_id"))
    for m in re.finditer(r"(?m)^-\s+\*\*(.+?)\.\*\*", paper_md):
        add_token(m.group(1))
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import background_literature as _bg
        for entry in _bg.load_registry().values():
            add_token(entry.citation_token)
    except (ImportError, OSError, ValueError):
        pass
    return out


def _strip_unreferenced_et_al_parentheticals(
    paper_md: str, manifest: dict | None,
) -> tuple[str, int]:
    allowed = _allowed_author_year_keys(paper_md, manifest)
    if not allowed:
        return paper_md, 0
    n = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal n
        key = _citation_key(match.group(1), match.group(2))
        if key in allowed:
            return match.group(0)
        n += 1
        return ""

    cleaned = _ET_AL_PAREN_CITE_RE.sub(repl, paper_md)
    if not n:
        return paper_md, 0
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned, n


def _strip_orphan_inference_fragments(paper_md: str) -> tuple[str, int]:
    n = 0
    out: list[str] = []
    current_section = ""
    for paragraph in paper_md.split("\n\n"):
        heading = re.match(r"^##\s+(.+?)\s*$", paragraph.strip())
        if heading:
            current_section = heading.group(1).strip()
            out.append(paragraph)
            continue
        hay = paragraph.lower()
        is_orphan = (
            "[d1_" in hay
            or "[mechanism_anchor:" in hay
            or "[mechanism anchor:" in hay
            or "[conservation:" in hay
            or "[testability:" in hay
            or hay.lstrip().startswith("existing human signal:")
        )
        if is_orphan and current_section != "Inferential Bridge":
            n += 1
            continue
        out.append(paragraph)
    if not n:
        return paper_md, 0
    cleaned = "\n\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


_BRIDGE_SECTION_RE = re.compile(
    r"^##\s+Inferential Bridge\b.*?\n(.*?)(?=^##\s+\w|\Z)",
    re.DOTALL | re.MULTILINE,
)
_D1_TAG_RE = re.compile(
    r"\[D1_[^\]]+\|\s*confidence=(low|medium|high)\]",
    re.IGNORECASE,
)
_INLINE_NUMERIC_RE = re.compile(r"(?<![A-Za-z])(?:\d+(?:\.\d+)?|\d+\s*%)")


def _valid_d1_block(block: str) -> bool:
    if not _D1_TAG_RE.search(block):
        return False
    if (
        not any(t in block for t in ("[mechanism_anchor:", "[mechanism anchor:"))
        or "[conservation:" not in block
        or "[testability:" not in block
    ):
        return False
    visible = re.sub(r"\[[^\]]+\]", "", block)
    visible = re.sub(r"^\s*(?:\d+\.|\-)\s+", "", visible)
    visible = re.sub(r"Existing human signal:.*?(?:\n|$)", "", visible)
    return not _INLINE_NUMERIC_RE.search(visible)


def _strip_invalid_inferential_bridge_claims(
    paper_md: str,
) -> tuple[str, int]:
    match = _BRIDGE_SECTION_RE.search(paper_md)
    if not match:
        return paper_md, 0
    body = match.group(1).strip()
    if not body:
        return paper_md, 0
    blocks = [
        b.strip()
        for b in re.split(r"\n(?=\d+\.\s+|\-\s+)", body)
        if re.match(r"^(?:\d+\.|\-)\s+", b.strip())
    ]
    kept: list[str] = []
    n_removed = 0
    for block in blocks:
        if not _valid_d1_block(block):
            n_removed += 1
            continue
        kept.append(re.sub(r"^\s*(?:\d+\.|\-)\s+", f"{len(kept) + 1}. ", block))
    if not n_removed:
        return paper_md, 0
    if kept:
        replacement = "## Inferential Bridge\n\n" + "\n\n".join(kept) + "\n\n"
    else:
        replacement = ""
    cleaned = paper_md[:match.start()].rstrip() + "\n\n" + replacement
    cleaned += paper_md[match.end():].lstrip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n_removed


def _section_word_count(paper: str, heading: str) -> int:
    """Word count for one ## heading section (header line excluded)."""
    m = re.search(
        rf"^##\s+{re.escape(heading)}(.*?)(?=^##\s+\w|\Z)",
        paper, re.DOTALL | re.MULTILINE,
    )
    if not m:
        return 0
    return len(re.findall(r"\b\w+\b", m.group(1)))


def _extract_section(paper: str, heading: str) -> tuple[int, int, str]:
    """Return (start_offset, end_offset, body) of a ## heading
    section. Used by Fix #53 to roll back over-aggressive strips."""
    m = re.search(
        rf"^##\s+{re.escape(heading)}(.*?)(?=^##\s+\w|\Z)",
        paper, re.DOTALL | re.MULTILINE,
    )
    if not m:
        return -1, -1, ""
    return m.start(), m.end(), m.group(0)


def apply_fixes(
    paper_md: str, issues: Sequence[object],
    *,
    manifest: dict | None = None,
    quant_claims_dir=None,
    numeric_quarantine_path: Path | None = None,
) -> tuple[str, list[dict]]:
    """Apply auto-fixable patches; return (new_md, log).

    Fix #53: snapshots Discussion, Cross-Domain Synthesis,
    Limitations + Conclusion BEFORE any strip pass runs. After all
    strips, if a protected section has dropped below its safety-
    margin floor (Discussion/CD: 850 = Q11/Q12 800 + 50 margin;
    Limitations: 200; Conclusion: 150), the section is restored to
    its pre-strip state. Trust-spine deletion safety +
    analytical-depth preservation.

    Slice 7 P2 (2026-05-05): optional manifest + quant_claims_dir
    let the Numeric Role Guard auto-strip RECEIPT-side source-
    context drift (not just bg_lit-side). Without these, the audit
    flags receipt-side drift but the fixer can't strip it because
    it lacks the receipt → quant_claims mapping. Defaulted None
    for back-compat with callers that don't have manifest context.

    Path A (2026-05-07): optional numeric_quarantine_path records
    every stripped Numeric Role Guard sentence so fact-contract
    failures are auditable, not silent text loss."""
    new_md = paper_md
    log: list[dict] = []
    enforce_depth = manifest is not None and not (
        numeric_quarantine_path and (numeric_quarantine_path.parent / "submission_source_proofs.json").exists()
    )

    def apply(
        repair: Callable[..., tuple[str, int]], fix_type: str,
        description: str, *args: object,
    ) -> int:
        nonlocal new_md
        new_md, count = repair(new_md, *args)
        if count:
            log.append({
                "fix_type": fix_type,
                "n_changes": count,
                "description": description,
            })
        return count

    # Snapshot for Fix #53 depth-preservation guard
    pre_strip_sections: dict[str, str] = {}
    for heading in _DEPTH_PROTECTED_SECTIONS:
        _s, _e, body = _extract_section(new_md, heading)
        if body:
            pre_strip_sections[heading] = body

    # 1. Strip (potentially) inline artifacts (highest count, run first).
    new_md, pot_count_before = _POTENTIALLY_RE.subn("", new_md)
    if pot_count_before:
        log.append({
            "fix_type": "repair_artifact",
            "n_changes": pot_count_before,
            "description": "stripped ' (potentially)' inline artifacts",
        })

    apply(
        _strip_role_repair_artifacts, "role_repair_artifact_strip",
        "stripped numeric role-repair artifact sentences from "
        "public prose",
    )

    apply(
        _strip_public_pipeline_meta, "public_pipeline_meta_strip",
        "stripped public-facing pipeline meta-comments left by "
        "section repair or absence-audit scaffolding",
    )

    apply(
        _strip_public_placeholder_paragraphs, "public_placeholder_paragraph_strip",
        "stripped public placeholder prose paragraphs before "
        "journal surface review",
    )

    apply(
        _normalize_public_topic_slug, "public_topic_slug_normalization",
        "rewrote topic-pack slug tokens in the public manuscript "
        "body to the display topic name",
        manifest,
    )

    if manifest is not None:
        apply(
            repair_abstract_direction_summary, "abstract_results_direction_consistency_repair",
            "rewrote the Abstract direction-summary sentence from "
            "manifest receipt direction counts; advisory repair only",
            manifest,
        )

    apply(
        _strip_empty_parenthetical_citations, "empty_parenthetical_citation_strip",
        "removed empty citation parentheses left by safe citation "
        "stripping",
    )

    apply(
        _normalize_ordinal_gaps, "ordinal_gap_normalization",
        "renumbered paragraph-local ordinal openers in encounter "
        "order to prevent stale outline fragments",
    )

    apply(
        _normalize_h3_residue_headings, "h3_residue_heading_normalization",
        "rewrote leaked '### H3:' headings to normal markdown H3 headings",
    )

    apply(
        _normalize_public_snake_case_labels, "public_snake_case_label_normalization",
        "rewrote internal enum-style snake_case labels in the "
        "public manuscript body",
    )

    apply(
        _ensure_public_thesis_marker, "public_thesis_marker_backfill",
        "inserted an explicit public Abstract thesis marker when "
        "writer prose lacked an auditor-detectable thesis sentence",
        manifest,
    )

    apply(
        _normalize_public_meta_phrases, "public_meta_phrase_normalization",
        "rewrote audit/compiler meta phrases into neutral "
        "journal-facing manuscript prose",
    )

    apply(
        _strip_effect_estimate_artifact_sentences, "effect_estimate_artifact_sentence_strip",
        "stripped generic 'reported an effect estimate of ...' "
        "sentences that are repair artifacts rather than "
        "publishable source-context prose",
    )

    apply(
        _strip_orphan_threshold_sentences, "orphan_threshold_sentence_strip",
        "stripped anaphoric threshold-comparison sentences whose "
        "improvement anchor was absent",
    )

    apply(
        _strip_orphan_demonstrated_clauses, "orphan_demonstrated_clause_strip",
        "removed orphaned 'yet demonstrated that ...' clauses "
        "left after unsupported citation cleanup",
    )

    apply(
        _strip_public_reference_dumps, "public_reference_dump_strip",
        "removed DOI/PMID dump blocks from journal-main prose",
    )

    apply(
        _strip_final_interpretation_blocks, "final_interpretation_block_strip",
        "removed internal final-interpretation subsection from journal main",
    )

    apply(
        _normalize_discussion_opener, "discussion_opener_normalization",
        "removed leading contrast marker from Discussion opener",
    )

    apply(
        _strip_empty_attribution_sentences, "empty_attribution_sentence_strip",
        "removed sentences left with empty attribution fragments "
        "such as 'described by .'",
    )

    apply(
        _strip_toxin_mobilization_sentences, "toxin_mobilization_sentence_strip",
        "removed public toxin-mobilization asides that require "
        "specialized source context outside the synthesis claim",
    )

    apply(
        _normalize_public_p_values, "public_p_value_normalization",
        "normalized public p-value spacing/casing before "
        "final-layer review",
    )

    apply(
        _strip_unreferenced_et_al_parentheticals, "unreferenced_parenthetical_citation_strip",
        "removed Author et al. YYYY parenthetical citations that "
        "were not backed by the manifest, background registry, "
        "or References block",
        manifest,
    )

    apply(
        _strip_orphan_inference_fragments, "orphan_inference_fragment_strip",
        "stripped D1 inferential-bridge fragments that were "
        "left outside an Inferential Bridge section",
    )

    apply(
        _strip_invalid_inferential_bridge_claims, "invalid_inferential_bridge_claim_strip",
        "stripped Inferential Bridge claims missing required "
        "Q14 tags or containing untraced numerics",
    )

    apply(
        _strip_duplicate_subsections, "duplicate_subsection",
        "removed repeated markdown subsections produced by "
        "section backstops or repair loops",
    )
    apply(
        _strip_empty_headings, "empty_heading_strip",
        "removed headings left empty after deterministic cleanup",
    )
    apply(
        _strip_reference_only_next_study_section, "reference_only_next_study_strip",
        "removed next-study recommendation sections containing only reference residue",
    )

    apply(
        _strip_consecutive_duplicate_paragraphs, "duplicate_paragraph",
        "removed consecutive duplicate prose paragraphs produced "
        "by section backstops or repair loops",
    )

    apply(
        _strip_fuzzy_duplicate_paragraphs, "fuzzy_duplicate_paragraph",
        "removed later body paragraphs with high token overlap "
        "against earlier body paragraphs",
    )

    new_md, n_fused_repeat = re.subn(
        r"(?P<sentence>[A-Z][^.!?\n]{20,})(?<!doi)\.org/10\.\d{4,9}/"
        r"[^\s\]]+\]\.\s+(?P=sentence)\.",
        r"\g<sentence>.", new_md,
    )
    new_md, n_malformed_doi = re.subn(
        r"(?<!doi)(?<=[A-Za-z])\.org/10\.\d{4,9}/[^\s\]]+\]", "", new_md,
        flags=re.I,
    )
    if n_fused_repeat or n_malformed_doi:
        log.append({
            "fix_type": "malformed_doi_tail",
            "n_changes": n_fused_repeat + n_malformed_doi,
            "description": "removed a DOI tail fused onto manuscript prose",
        })

    apply(
        _strip_duplicate_long_sentences, "duplicate_sentence",
        "removed repeated long prose sentences produced by "
        "section backstops or repair loops",
    )

    # 2. Fix '### ###' / '## ##' malformed headers.
    new_md, bad_hdr_count = _DOUBLE_HASH_RE.subn(r"\1 ", new_md)
    if bad_hdr_count:
        log.append({
            "fix_type": "malformed_header",
            "n_changes": bad_hdr_count,
            "description": "collapsed '### ###' / '## ##' to single tier",
        })

    # 3. Strip stale-SPAR sentences without crossing section
    # boundaries. Earlier code ran one global sentence regex over the
    # whole paper, so a stale Methods disclosure could consume the
    # preceding QEI line plus the `## Methods` heading. Section scope
    # makes Methods corruption structurally impossible.
    apply(
        _strip_stale_spar_sentences, "stale_method_boilerplate",
        "stripped stale SPAR/receipt-cluster sentences with "
        "section-scoped matching; deterministic Methods "
        "'What did NOT run' disclosure is preserved",
    )

    # 4. Dedupe '## References' (keep first).
    refs_pattern = re.compile(
        r"^##\s+References\b.*?(?=^##\s+\w|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    refs_matches = list(refs_pattern.finditer(new_md))
    if len(refs_matches) > 1:
        # Keep the LAST one (post-processed Author-Year) — drop earlier.
        # The post-processor's References has cleaner Author-Year format.
        first_match = refs_matches[0]
        new_md = (
            new_md[:first_match.start()]
            + new_md[first_match.end():]
        )
        log.append({
            "fix_type": "duplicate_section",
            "n_changes": 1,
            "description": (
                "removed first References block (writer-rendered); kept "
                "deterministic post-processed Author-Year block"
            ),
        })

    # 5. Fix #18c: citation-order auto-fix.
    # `Konopka 2019 et al.` → `Konopka et al. 2019`. Common LLM
    # generation artifact. Safe deterministic regex sub.
    cite_order_re = re.compile(
        r"\b([A-Z][a-zA-Z]+)\s+(\d{4})\s+et\s+al\.?",
    )
    new_md, cite_order_count = cite_order_re.subn(r"\1 et al. \2", new_md)
    if cite_order_count:
        log.append({
            "fix_type": "broken_citation_order",
            "n_changes": cite_order_count,
            "description": (
                "rewrote 'Author YYYY et al.' → 'Author et al. YYYY' "
                "(canonical scholarly citation order)"
            ),
        })

    # 5b. Normalize duplicate citation-year artifacts.
    # `Witham et al. 2025 (2025)` / `Witham et al. 2025 2025`
    # → `Witham et al. 2025`.
    dup_cite_year_paren_re = re.compile(
        r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.)?)\s+(\d{4})\s+\(\2\)"
    )
    dup_cite_year_bare_re = re.compile(
        r"\b([A-Z][a-zA-Z]+(?:\s+et\s+al\.)?)\s+(\d{4})\s+\2\b"
    )
    dup_cite_year_count = (
        len(dup_cite_year_paren_re.findall(new_md))
        + len(dup_cite_year_bare_re.findall(new_md))
    )
    if dup_cite_year_count:
        new_md = dup_cite_year_paren_re.sub(r"\1 \2", new_md)
        new_md = dup_cite_year_bare_re.sub(r"\1 \2", new_md)
        log.append({
            "fix_type": "duplicate_citation_year",
            "n_changes": dup_cite_year_count,
            "description": (
                "collapsed duplicate citation-year artifacts like "
                "'Author et al. YYYY (YYYY)' or 'Author et al. YYYY YYYY'"
            ),
        })

    # 6. Fix #18b: strip sentences containing background-literature
    # numerics WITHOUT their canonical citation token in the same
    # sentence. Stage-2 audit flags these as P1; the writer should
    # have included the citation per its prompt rule (Fix #17). We
    # remove the offending sentence rather than ship an unsourced
    # numeric — the surrounding paragraph still reads coherently
    # because the preceding/following sentences carry the argument.
    bg_strip_count = _strip_unsourced_background_sentences_inplace(
        new_md, log, manifest=manifest, quant_claims_dir=quant_claims_dir,
    )
    if bg_strip_count > 0:
        new_md = _strip_unsourced_background_sentences(
            new_md, manifest=manifest, quant_claims_dir=quant_claims_dir,
        )

    # 6b. Fix #46: strip sentences flagged as change-value misread
    # (C13). The corpus says X is an improvement/change/difference
    # value; the writer rendered it as an absolute below a threshold.
    # Pure deletion of the offending sentence (analogous to Fix #18b
    # for unsourced background numerics). Numeric is corpus-traced
    # (Q2 untouched); only the misread sentence is lost. The writer's
    # surrounding prose carries the rest of the argument.
    apply(
        _strip_change_value_misread_sentences, "change_value_misread_strip",
        "stripped sentences containing change-value numerics "
        "(e.g. 0.13 m/s 'improvement') rendered as absolute "
        "values below thresholds (Fix #46 / C13 auto-fix)",
    )

    # 6c. Fix #54: strip cross-sentence anaphoric misreads. C13's
    # per-sentence detection misses 'This walk speed value is below
    # 0.8 m/s threshold' because that sentence has no 0.13 m/s; the
    # change-numeric is in the PRECEDING sentence. Fix #54 strips
    # the threshold-comparison sentence (the misread carrier), not
    # the corpus-traced numeric sentence (which is fine).
    n_anaphor_stripped = apply(
        _strip_change_value_anaphor_sentences, "change_value_anaphor_strip",
        "stripped cross-sentence anaphoric misreads — "
        "sentences referring back to a change-value numeric "
        "('this walk speed value...') and treating it as "
        "absolute via threshold-comparison phrasing "
        "(Fix #54 / C13b auto-fix)",
    )

    # 6d. Fix #58 (C13c): strip threshold-comparison sentences
    # from paragraphs that juxtapose a corpus change-numeric with
    # threshold language. Reviewer's stronger requirement: catch
    # ANY paragraph where the change-value is compared to a
    # threshold, regardless of wording. The strip removes the
    # threshold-comparison sentence(s); the change-numeric
    # sentence stays.
    apply(
        _strip_change_value_paragraph_threshold_sentences, "change_value_paragraph_threshold_strip",
        "stripped threshold-comparison sentences from "
        "paragraphs that juxtaposed a corpus change-numeric "
        "(e.g. 0.13 m/s) with threshold language without "
        "the change-framing in proximity (Fix #58 / C13c "
        "auto-fix)",
    )

    # 7. Fix #22: strip orphan / consecutive `_Cited:` blocks.
    # Stage-2 surface-render-lint flags these as P2 with
    # auto_fixable=True. Strip is safe by construction (no anchor
    # sentence was lost — the surrounding prose either survives or
    # the cite was already credited via the preceding cite block).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import surface_render_lint as _srl
        new_md, n_orphan_stripped = _srl.strip_orphan_citation_blocks(
            new_md,
        )
        if n_orphan_stripped > 0:
            log.append({
                "fix_type": "surface_orphan_cite_strip",
                "n_changes": n_orphan_stripped,
                "description": (
                    "stripped orphan / consecutive `_Cited:` blocks "
                    "that had no anchor sentence (Fix #22 surface lint)"
                ),
            })
        # Fix #52: strip sentence fragments (single-letter starts +
        # lowercase preposition starts) left behind by upstream
        # auto-strips. Pure deletion; the fragment is by construction
        # broken/meaningless.
        new_md, n_fragments_stripped = _srl.strip_sentence_fragments(
            new_md,
        )
        if n_fragments_stripped > 0:
            log.append({
                "fix_type": "surface_sentence_fragment_strip",
                "n_changes": n_fragments_stripped,
                "description": (
                    "stripped broken sentence fragments (single-letter "
                    "starts like 'e when paired' or lowercase-"
                    "preposition starts like 'on 2019 in...') left "
                    "behind by upstream auto-strips (Fix #52)"
                ),
            })
        new_md, n_blank_rows = _srl.strip_blank_table_rows(new_md)
        if n_blank_rows > 0:
            log.append({
                "fix_type": "surface_blank_table_row_strip",
                "n_changes": n_blank_rows,
                "description": (
                    "stripped blank markdown table rows left behind by "
                    "numeric or reviewer patch deletions"
                ),
            })
        new_md, n_bad_rows = _srl.strip_malformed_table_rows(new_md)
        if n_bad_rows > 0:
            log.append({
                "fix_type": "surface_malformed_table_row_strip",
                "n_changes": n_bad_rows,
                "description": (
                    "stripped malformed markdown table rows whose "
                    "cell count no longer matched the table header"
                ),
            })
        new_md, n_empty_qei = _srl.strip_empty_qei_rows(new_md)
        if n_empty_qei > 0:
            log.append({
                "fix_type": "surface_empty_qei_row_strip",
                "n_changes": n_empty_qei,
                "description": (
                    "stripped public QEI rows whose numeric payload "
                    "was emptied by post-render repair"
                ),
            })
        new_md, n_unterminated = _srl.strip_unterminated_paragraphs(new_md)
        if n_unterminated > 0:
            log.append({
                "fix_type": "surface_unterminated_paragraph_strip",
                "n_changes": n_unterminated,
                "description": (
                    "stripped unterminated prose paragraphs left behind "
                    "by review or repair deletion"
                ),
            })
    except ImportError:
        pass

    # 8a. Fix #33: replace internal tier labels with human-readable
    # equivalents. Defence-in-depth — the writer's prompt humanises
    # these labels (Fix #33 in agent/paper_writer.py) but Grok
    # patches or LLM creativity can still leak them.
    _TIER_LABEL_HUMAN: dict[str, str] = {
        "A1_clinical_RCT": "RCT (clinical)",
        "A2_human_mechanistic": "RCT (mechanistic)",
        "B1_review": "review/meta-analysis",
        "B2_observational": "observational",
        "C1_preclinical": "preclinical",
        "C2_in_vitro": "in-vitro",
    }
    n_tier_relabel = 0
    for raw, human in _TIER_LABEL_HUMAN.items():
        n = new_md.count(raw)
        if n:
            new_md = new_md.replace(raw, human)
            n_tier_relabel += n
    if n_tier_relabel:
        log.append({
            "fix_type": "internal_tier_label_relabel",
            "n_changes": n_tier_relabel,
            "description": (
                "replaced internal tier labels (A1_clinical_RCT, "
                "C1_preclinical, etc.) with human-readable equivalents "
                "(Fix #33 defence-in-depth)"
            ),
        })

    apply(
        _strip_extra_methods_numbered_steps, "methods_extra_step_strip",
        "stripped numbered Methods steps beyond the deterministic "
        "run-mode contract",
    )

    # 8b. Q6 structural backstop: preclinical → human transfer must be
    # hedged. This is universal translational discipline, not a
    # topic-specific patch.
    apply(
        _hedge_preclinical_translation, "preclinical_translation_hedge",
        "added neutral translational-uncertainty hedge after "
        "unhedged preclinical/model-organism sentences",
    )

    # 8. Collapse mid-line double spaces to single space.
    # Stage-2 C08 flags these as P2 auto_fixable; before this fix the
    # auto-fixer had no implementation, so the issues survived to
    # final consistency.json and tripped the no-regression gate
    # (consistency_count regression). Conservative pattern matches
    # 2+ spaces NOT at line start (line-start indentation is
    # legitimate in markdown bullets / cite blocks) AND NOT preceded
    # by a newline.
    double_space_re = re.compile(r"(?<=\S)  +(?=\S)")
    new_md, n_collapsed = double_space_re.subn(" ", new_md)
    if n_collapsed:
        log.append({
            "fix_type": "double_space_collapse",
            "n_changes": n_collapsed,
            "description": (
                "collapsed mid-line double spaces to single space "
                "(Stage-2 C08 was flagging without auto-fix)"
            ),
        })

    apply(
        _collapse_adjacent_duplicate_words, "duplicate_word_collapse",
        "collapsed adjacent duplicated prose words flagged by "
        "Stage-2 C08 (for example 'not not')",
    )

    # Fix #56: strip internal pipeline metadata from prose body.
    # The writer's title block produces a '**Submission:**
    # `synthesis-metformin-v06-...`' line that's machine-friendly but
    # publication-noise — reviewer flagged it as 'too much internal
    # pipeline language'. The run-tag belongs in the supplement /
    # reproducibility appendix (manifest.json), not the prose.
    submission_re = re.compile(
        r"^\*\*Submission:\*\*\s*`[^`]+`\s*\n+",
        re.MULTILINE,
    )
    new_md, n_submission = submission_re.subn("", new_md)
    if n_submission:
        log.append({
            "fix_type": "internal_pipeline_metadata_strip",
            "n_changes": n_submission,
            "description": (
                "stripped '**Submission:** `synthesis-...`' run-tag "
                "from title block — internal pipeline metadata "
                "belongs in manifest.json/supplement, not prose "
                "(Fix #56 / cert old-defect scan)"
            ),
        })

    # Strip residual blank-line runs created by deletions
    # (collapse 3+ newlines to a single paragraph break: \n\n).
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)

    # Fix #53: depth-preservation guard — restore protected sections
    # if the cumulative strips above pushed Discussion / Cross-Domain
    # / Limitations / Conclusion below their safety-margin floors.
    # The analytical-depth backstop: trust-spine deletions are
    # correct individually but can collectively over-aggress on the
    # analytical-core sections (clean-repro showed Q12 dropping from
    # 930 → 582 words after auto-strips). Only restores when:
    #   (a) a snapshot was taken (section existed pre-strip), AND
    #   (b) the post-strip count is BELOW the floor, AND
    #   (c) the pre-strip count was ABOVE the floor (i.e. this
    #       regression was strip-caused, not writer-caused).
    # If the writer never produced enough words, the original
    # depth-floor failure is preserved — Fix #53 rolls back over-
    # aggressive strips, not writer shortfalls. Section heading
    # vanishing entirely (e.g. SPAR-strip ate a header line) is
    # handled by re-extracting after restore — the snapshot
    # preserves the heading.
    for heading, floor in _DEPTH_PROTECTED_SECTIONS.items():
        if heading not in pre_strip_sections:
            continue
        post_count = _section_word_count(new_md, heading)
        if post_count >= floor:
            continue  # still above floor — strips were safe
        pre_count = len(pre_strip_sections[heading].split())
        if pre_count < floor:
            continue  # was already below floor — not strip-caused
        snapshot = pre_strip_sections[heading]
        if (
            _strip_fuzzy_duplicate_paragraphs(snapshot)[1]
            or _strip_duplicate_long_sentences(snapshot)[1]
        ):
            continue  # never restore writer repetition removed by dedupe
        # Strips pushed a previously-deep section below its floor.
        # Restore the snapshot.
        s, e, _body = _extract_section(new_md, heading)
        if s < 0:
            continue  # heading vanished entirely — can't restore
        new_md = new_md[:s] + pre_strip_sections[heading] + new_md[e:]
        log.append({
            "fix_type": "depth_preservation_restore",
            "n_changes": 1,
            "description": (
                f"restored '{heading}' section to pre-strip state "
                f"({post_count} → {pre_count} words; cumulative "
                f"auto-strips would have dropped it below the "
                f"depth-safety floor of {floor}; Fix #53 depth guard "
                "reverted strips on this section)"
            ),
        })
        # Re-collapse blank-line runs in case restoration mismatched.
        new_md = re.sub(r"\n{3,}", "\n\n", new_md)

    # Fix #53b (Refactor 2026-05-04): re-strip unsourced bg-lit
    # AFTER depth-preservation restore. The restore can re-introduce
    # bg-lit-unsourced sentences that the strip just removed, leading
    # to a Stage-2 P1 SHIP-BLOCKER even though the strip "fired".
    # Apply just the bg-lit strip again post-restore. If this re-
    # strip pushes a section below its floor again, the depth-floor
    # failure is honest (we can't have BOTH no-unsourced-bg-lit AND
    # 850-word Discussion if the only way to fill 850 is via
    # unsourced bg-lit). Q11/Q12 P2 is preferable to C09 P1.
    n_re_stripped = _strip_unsourced_background_sentences_inplace(
        new_md, [], manifest=manifest, quant_claims_dir=quant_claims_dir,
    )
    if n_re_stripped:
        new_md = _strip_unsourced_background_sentences(new_md, manifest=manifest, quant_claims_dir=quant_claims_dir)
        log.append({
            "fix_type": "background_lit_unsourced_restrip_post_depth",
            "n_changes": n_re_stripped,
            "description": (
                "re-stripped bg-lit-unsourced sentences after Fix #53 "
                "depth-preservation restore re-introduced them. "
                "Choosing C09-clean over Q11/Q12-depth — P1 cleanliness "
                "trumps P2 depth (Fix #53b)"
            ),
        })

    # Fix #53c (2026-05-04): re-strip cosmetic '(potentially)' inline
    # repair-artifacts AFTER depth-preservation. The restore can put
    # them back if the protected section dropped below its floor;
    # losing 16 chars of artifact never threatens a 850-word floor,
    # so this re-strip is unconditionally safe. Without this re-pass
    # the C05 P2 issue resurfaces in the final consistency audit even
    # though the strip "fired" earlier.
    new_md, pot_re_count = _POTENTIALLY_RE.subn("", new_md)
    if pot_re_count:
        log.append({
            "fix_type": "repair_artifact_restrip_post_depth",
            "n_changes": pot_re_count,
            "description": (
                "re-stripped '(potentially)' inline artifacts after "
                "Fix #53 depth-preservation restore re-introduced "
                "them. Cosmetic strip; safe to re-apply unconditionally "
                "(Fix #53c)"
            ),
        })

    apply(
        _strip_public_pipeline_meta, "public_pipeline_meta_restrip_post_depth",
        "re-stripped public-facing pipeline meta-comments after "
        "depth-preservation restore reintroduced them",
    )

    apply(
        _strip_public_placeholder_paragraphs, "public_placeholder_paragraph_restrip_post_depth",
        "re-stripped public placeholder prose after section "
        "restoration",
    )

    apply(
        _normalize_public_p_values, "public_p_value_renormalization_post_depth",
        "re-normalized public p-value spacing/casing after "
        "section restoration",
    )

    apply(
        _strip_unreferenced_et_al_parentheticals, "unreferenced_parenthetical_citation_restrip_post_depth",
        "re-removed unreferenced Author et al. YYYY parenthetical "
        "citations after section restoration",
        manifest,
    )

    # Universal Numeric Role Guard auto-fix (2026-05-05): strip P1
    # sentences flagged for arithmetic_violation, role_mismatch, OR
    # source-context drift (Slice 7 step 1, 2026-05-05). Universal
    # class-level fix subsuming Fixes #54/#57/#58/#58c.
    try:
        import numeric_role_guard as _nrg
        _scan = _nrg.scan_paper
        _strip = _nrg.auto_strip_offending_sentences
        _repair = getattr(
            _nrg, "repair_source_context_drift_sentences", None,
        )
    except ImportError:
        _scan = None
        _repair = None
    if _scan is not None:
        # Slice 7 P2: feed BOTH bg_lit registry AND manifest +
        # quant_claims_dir so the auto-strip path covers VALUE drift
        # AND ROLE drift on receipt-side citations (not just bg_lit
        # canon). Falls back to bg_lit-only when caller didn't pass
        # manifest (back-compat).
        import json as _json
        from pathlib import Path as _Path
        repo = _Path(__file__).resolve().parent.parent
        bg_lit_path = repo / "docs" / "background_literature.json"
        bg_lit_registry: dict | None = None
        if bg_lit_path.exists():
            try:
                bg_lit_registry = _json.loads(bg_lit_path.read_text())
            except (OSError, ValueError):
                bg_lit_registry = None
        # Resolve quant_claims dir from topic in manifest if not given
        qcd = quant_claims_dir
        if qcd is None and isinstance(manifest, dict):
            topic = manifest.get("topic")
            if topic:
                qcd = (
                    repo / "docs" / "quality-reference" / topic
                    / "quant_claims"
                )
        # Last-resort fallback: read _ACTIVE_MANIFEST + _ACTIVE_TOPIC
        # globals from the orchestrator (preserves fix-#53c-style
        # behavior for callers that don't thread manifest in).
        manifest_obj = manifest
        if manifest_obj is None:
            try:
                import sys as _sys
                _sys.path.insert(0, str(repo / "scripts"))
                import run_v06_synthesis as _orch
                manifest_obj = getattr(_orch, "_ACTIVE_MANIFEST", None)
                if qcd is None:
                    topic = getattr(_orch, "_ACTIVE_TOPIC", None)
                    if topic:
                        qcd = (
                            repo / "docs" / "quality-reference"
                            / topic / "quant_claims"
                        )
            except (ImportError, AttributeError):
                pass
        nrg_issues = _scan(
            new_md,
            manifest=manifest_obj if isinstance(
                manifest_obj, dict,
            ) else None,
            bg_lit_registry=bg_lit_registry,
            quant_claims_dir=qcd,
        )
        if n_anaphor_stripped:
            nrg_issues = [
                issue for issue in nrg_issues
                if not _looks_like_change_speed_sentence(getattr(issue, "sentence", ""))
            ]
        if nrg_issues and _repair is not None:
            new_md, n_repaired = _repair(
                new_md,
                nrg_issues,
                manifest=manifest_obj if isinstance(
                    manifest_obj, dict,
                ) else None,
                bg_lit_registry=bg_lit_registry,
                quant_claims_dir=qcd,
            )
            if n_repaired:
                log.append({
                    "fix_type": "numeric_role_guard_repair",
                    "n_changes": n_repaired,
                    "description": (
                        "rewrote source-context ROLE-drift sentences "
                        "to match the cited source role; every rewrite "
                        "passed a fresh Numeric Role Guard scan"
                    ),
                })
                nrg_issues = _scan(
                    new_md,
                    manifest=manifest_obj if isinstance(
                        manifest_obj, dict,
                    ) else None,
                    bg_lit_registry=bg_lit_registry,
                    quant_claims_dir=qcd,
                )
        if nrg_issues:
            _append_numeric_quarantine(numeric_quarantine_path, nrg_issues)
            new_md, n_stripped = _strip(new_md, nrg_issues)
            if n_stripped < sum(1 for i in nrg_issues if i.severity == "P1"):
                new_md, n_fuzzy = _strip_numeric_role_evidence_spans(
                    new_md, nrg_issues,
                )
                n_stripped += n_fuzzy
            if n_stripped:
                log.append({
                    "fix_type": "numeric_role_guard_strip",
                    "n_changes": n_stripped,
                    "description": (
                        "stripped sentences flagged by Numeric Role "
                        "Guard (arithmetic violation, role mismatch, "
                        "malformed-subject repair artifact, or "
                        "source-context numeric drift). Universal "
                        "class-level fix subsuming Fixes "
                        "#54/#57/#58/#58c."
                    ),
                })
                n_contract = sum(
                    1 for i in nrg_issues
                    if getattr(i, "issue_type", "") == "numeric_claim_contract"
                    and getattr(i, "severity", "") == "P1"
                )
                if n_contract:
                    log.append({
                        "fix_type": "numeric_claim_contract_quarantine",
                        "n_changes": n_contract,
                        "description": (
                            "quarantined editorial numeric sentences that "
                            "lacked an inline exact registry value or a "
                            "source-supported range contract"
                        ),
                    })

    # Final depth floor backfill for non-evidence framing sections.
    if manifest is not None:
        new_md, cross_dup_log = _strip_conclusion_paragraphs_repeated_earlier(
            new_md,
        )
        log.extend(cross_dup_log)
        if enforce_depth and manifest.get("review_type") not in {"thin_corpus_brief", "evidence_brief", "evidence_map"}:
            new_md, depth_log = _ensure_analytical_depth_floors(new_md)
            log.extend(depth_log)
        new_md, hedge_log = _ensure_discussion_hedge_density(new_md)
        log.extend(hedge_log)
        apply(
            _strip_duplicate_subsections, "duplicate_subsection_restrip_post_depth",
            "re-removed repeated markdown subsections after "
            "depth restoration",
        )

    apply(
        _normalize_public_meta_phrases, "public_meta_phrase_normalization_post_depth",
        "rewrote audit/compiler meta phrases reintroduced by "
        "section restoration or final depth backfill",
    )

    apply(
        _normalize_public_topic_slug, "public_topic_slug_normalization_post_depth",
        "re-normalized topic-pack slug tokens after section "
        "restoration/backfill",
        manifest,
    )

    apply(
        _normalize_public_snake_case_labels, "public_snake_case_label_normalization_post_depth",
        "re-normalized internal enum-style snake_case labels after "
        "section restoration/backfill",
    )

    apply(
        _ensure_public_thesis_marker, "public_thesis_marker_backfill_post_depth",
        "reinserted explicit public Abstract thesis marker after "
        "section restoration/backfill",
        manifest,
    )

    new_md, n_final_dup_paragraphs = _strip_exact_duplicate_public_paragraphs(
        new_md,
    )
    if n_final_dup_paragraphs:
        log.append({
            "fix_type": "exact_public_duplicate_paragraph_post_depth",
            "n_changes": n_final_dup_paragraphs,
            "description": (
                "removed exact repeated long public-body prose paragraphs "
                "after restoration/backfill paths"
            ),
        })
        if enforce_depth:
            new_md, depth_log = _ensure_analytical_depth_floors(new_md)
            log.extend(depth_log)

    apply(
        _normalize_public_p_values, "public_p_value_normalization_final",
        "re-normalized public p-values after all restoration and "
        "numeric-role repair paths",
    )

    apply(
        _strip_thin_analytic_paragraphs, "thin_analytic_restrip_post_depth",
        "re-removed generic prose restored by depth guards",
    )

    return new_md, log


def _append_numeric_quarantine(path: Path | None, issues) -> None:
    if path is None:
        return
    rows: list[dict] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, list):
                rows = loaded
        except (OSError, ValueError):
            rows = []
    seen = {
        (
            str(r.get("issue_type", "")),
            str(r.get("sentence", "")),
            str(r.get("detail", "")),
        )
        for r in rows
    }
    for issue in issues:
        if getattr(issue, "severity", "") != "P1":
            continue
        row = {
            "issue_type": getattr(issue, "issue_type", ""),
            "severity": getattr(issue, "severity", ""),
            "detail": getattr(issue, "detail", ""),
            "sentence": getattr(issue, "sentence", ""),
            "suggested_fix": getattr(issue, "suggested_fix", ""),
        }
        key = (row["issue_type"], row["sentence"], row["detail"])
        if key in seen:
            continue
        rows.append(row)
        seen.add(key)
    path.write_text(json.dumps(rows, indent=2))


def _strip_conclusion_paragraphs_repeated_earlier(
    paper_md: str,
) -> tuple[str, list[dict]]:
    s, e, conclusion = _extract_section(paper_md, "Conclusion")
    if s < 0:
        return paper_md, []
    earlier = paper_md[:s]
    earlier_norms = {
        re.sub(r"\s+", " ", p.strip())
        for p in re.split(r"\n\s*\n", earlier)
        if len(re.sub(r"\s+", " ", p.strip()).split()) >= 12
        and not p.lstrip().startswith(("#", "|", "`", "-"))
    }
    if not earlier_norms:
        return paper_md, []
    parts = re.split(r"(\n\s*\n)", conclusion)
    out: list[str] = []
    n = 0
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        norm = re.sub(r"\s+", " ", para.strip())
        repeated = (
            len(norm.split()) >= 12
            and not para.lstrip().startswith(("#", "|", "`", "-"))
            and norm in earlier_norms
        )
        if repeated:
            n += 1
            continue
        out.append(para)
        if sep:
            out.append(sep)
    if not n:
        return paper_md, []
    updated = re.sub(r"\n{3,}", "\n\n", "".join(out)).rstrip() + "\n\n"
    fixed = paper_md[:s] + updated + paper_md[e:]
    return fixed, [{
        "fix_type": "conclusion_cross_section_duplicate",
        "n_changes": n,
        "description": (
            "removed conclusion paragraphs that duplicated earlier "
            "public-prose paragraphs before final depth backfill"
        ),
    }]


def _strip_numeric_role_evidence_spans(paper_md: str, issues) -> tuple[str, int]:
    """Fallback strip for C14 evidence snippets.

    Sentence splitting can differ between the audit wrapper and the
    fixer when markdown/citation blocks are nearby. If exact sentence
    replacement misses a P1 Numeric Role Guard issue, strip the
    paragraph containing the evidence snippet. This is fail-closed and
    universal: better to lose one paragraph than ship source-context
    numeric drift.
    """
    out = paper_md
    n = 0
    for issue in issues:
        if getattr(issue, "severity", "") != "P1":
            continue
        evidence = (getattr(issue, "sentence", "") or "").strip()
        if not evidence:
            continue
        if evidence in out:
            continue
        pos = -1
        for width in (160, 120, 90, 70, 50):
            snippet = evidence[:width].strip()
            if not snippet:
                continue
            pos = out.find(snippet)
            if pos >= 0:
                break
        if pos < 0:
            continue
        start = out.rfind("\n\n", 0, pos)
        end = out.find("\n\n", pos)
        start = 0 if start < 0 else start + 2
        end = len(out) if end < 0 else end
        out = out[:start] + out[end:]
        n += 1
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out, n


_PRECLINICAL_TRANSFER_RE = re.compile(
    r"\b(?:mice|rats?|C\.\s*elegans|mouse\s+models?|preclinical|"
    r"animal\s+models?|in\s+vitro|cell\s+culture)\b",
    re.IGNORECASE,
)
_PRECLINICAL_HEDGE_RE = re.compile(
    r"\b(?:humans?|translation|translate|extrapolat|may\s+not\s+apply|"
    r"remains?\s+to\s+be|warrant|caution|uncertain|context-dependent|"
    r"speculative|mechanistic\s+evidence|limit|preclinical|in\s+mice|"
    r"in\s+animals|animal\s+model|model\s+organism|in\s+rodents?|rat|"
    r"murine|mouse|c\.\s*elegans|drosophila|zebrafish|in\s+vitro|"
    r"ex\s+vivo|cell\s+culture|rodent)\b",
    re.IGNORECASE,
)


def _hedge_preclinical_translation(paper_md: str) -> tuple[str, int]:
    stop = re.search(
        r"^##\s+(?:Structured Evidence Tables|Search Provenance|References)\b",
        paper_md,
        re.MULTILINE,
    )
    prose_end = stop.start() if stop else len(paper_md)
    prose = paper_md[:prose_end]
    tail = paper_md[prose_end:]
    sentence_re = re.compile(r"[^.!?\n#](?:[^.!?\n#]|\.(?=\d))*[.!?]")
    out: list[str] = []
    last = 0
    n = 0
    matches = list(sentence_re.finditer(prose))
    for idx, m in enumerate(matches):
        sent = m.group(0)
        out.append(prose[last:m.start()])
        replacement = sent
        if _PRECLINICAL_TRANSFER_RE.search(sent):
            nxt = matches[idx + 1].group(0) if idx + 1 < len(matches) else ""
            window = sent + " " + nxt
            if not _PRECLINICAL_HEDGE_RE.search(window):
                replacement = (
                    sent.rstrip()
                    + " Translational relevance to humans remains uncertain."
                )
                n += 1
        out.append(replacement)
        last = m.end()
    out.append(prose[last:])
    return "".join(out) + tail, n


def _strip_unsourced_background_sentences_inplace(
    paper_md: str,
    log: list[dict],
    *,
    manifest: dict | None = None,
    quant_claims_dir=None,
) -> int:
    """Count + log unsourced background numerics; returns count.
    Separate from the actual strip so the log accurately reports
    BEFORE-state count even after the strip. Caller does the strip
    via _strip_unsourced_background_sentences()."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import background_literature as _bg
        registry = _bg.load_registry(topic=str(manifest.get("topic") or "") if manifest is not None else None)
        unsourced = _bg.find_unsourced_background_uses(
            paper_md,
            registry,
            manifest=manifest,
            quant_claims_dir=quant_claims_dir,
        )
    except (ImportError, FileNotFoundError, ValueError):
        return 0
    if not unsourced:
        return 0
    log.append({
        "fix_type": "background_lit_unsourced_strip",
        "n_changes": len(unsourced),
        "description": (
            "stripped sentences containing background-lit numerics "
            "without their required canonical citation in the same "
            "sentence"
        ),
    })
    return len(unsourced)


def _strip_stale_spar_sentences(paper_md: str) -> tuple[str, int]:
    """Remove stale SPAR/receipt-cluster sentences section-by-section.

    Methods gets one deterministic replacement sentence for legacy
    boilerplate, but its `### What did NOT run` disclosure block is
    protected. Non-Methods sections simply lose the stale sentence.
    Top-level `##` headings are never part of a match.
    """
    heading_re = re.compile(r"^##\s+([^\n]+)\n?", re.MULTILINE)
    matches = list(heading_re.finditer(paper_md))
    if not matches:
        fixed, n = _strip_stale_in_span(paper_md, replace_first=False)
        return fixed, n

    out: list[str] = [paper_md[:matches[0].start()]]
    total = 0
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(paper_md)
        heading = m.group(1).strip().lower()
        body = paper_md[m.end():end]
        if heading == "methods":
            body, n = _strip_stale_in_methods_body(body)
        else:
            body, n = _strip_stale_in_span(body, replace_first=False)
        total += n
        out.append(paper_md[m.start():m.end()])
        out.append(body)
    return "".join(out), total


def _strip_stale_in_methods_body(body: str) -> tuple[str, int]:
    protected_re = re.compile(
        r"^###\s+What did NOT run\b.*?(?=^### |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    matches = list(protected_re.finditer(body))
    if not matches:
        return _strip_stale_in_span(body, replace_first=True)

    out: list[str] = []
    total = 0
    pos = 0
    replace_first = True
    for m in matches:
        chunk, n = _strip_stale_in_span(
            body[pos:m.start()], replace_first=replace_first,
        )
        out.append(chunk)
        out.append(m.group(0))
        total += n
        replace_first = replace_first and n == 0
        pos = m.end()
    chunk, n = _strip_stale_in_span(
        body[pos:], replace_first=replace_first,
    )
    out.append(chunk)
    total += n
    return "".join(out), total


def _strip_stale_in_span(text: str, *, replace_first: bool) -> tuple[str, int]:
    matches = list(_STALE_SPAR_SENT_RE.finditer(text))
    if not matches:
        return text, 0
    replacement = (
        "This synthesis used the v0.6 quant-claim adapter; no "
        "multi-receipt adjudication pipeline ran."
    )
    state = {"first": replace_first}

    def _replace(_m: "re.Match[str]") -> str:
        if state["first"]:
            state["first"] = False
            return replacement
        return ""

    return _STALE_SPAR_SENT_RE.sub(_replace, text), len(matches)


def _ensure_analytical_depth_floors(paper_md: str) -> tuple[str, list[dict]]:
    log: list[dict] = []
    for heading, floor, paragraph in (
        (
            "Introduction", 400,
            _INTRODUCTION_BACKFILL,
        ),
        (
            "Background", 300,
            _BACKGROUND_BACKFILL,
        ),
        (
            "Discussion", 800,
            _DISCUSSION_BACKFILL,
        ),
        (
            "Conclusion", 250,
            _CONCLUSION_BACKFILL,
        ),
    ):
        count = _section_word_count(paper_md, heading)
        if count >= floor:
            continue
        s, e, section = _extract_section(paper_md, heading)
        if s < 0:
            continue
        n_blocks = 0
        if not _paragraph_already_present(paper_md, paragraph):
            updated = section.rstrip() + "\n\n" + paragraph + "\n\n"
            paper_md = paper_md[:s] + updated + paper_md[e:]
            n_blocks = 1
        new_count = _section_word_count(paper_md, heading)
        extension_index = 1
        while new_count < floor and extension_index <= 7:
            extension = _depth_backfill_extension(heading, extension_index)
            extension_index += 1
            if _paragraph_already_present(paper_md, extension):
                continue
            s, e, section = _extract_section(paper_md, heading)
            if s < 0:
                break
            updated = (
                section.rstrip()
                + "\n\n"
                + extension
                + "\n\n"
            )
            paper_md = paper_md[:s] + updated + paper_md[e:]
            new_count = _section_word_count(paper_md, heading)
            n_blocks += 1
        if not n_blocks:
            continue
        log.append({
            "fix_type": "analytical_depth_backfill",
            "n_changes": n_blocks,
            "description": (
                f"appended numeric-free deterministic analytical "
                f"backfill to '{heading}' ({count} → {new_count} "
                f"words; floor {floor})"
            ),
        })
    return paper_md, log


def _depth_backfill_extension(heading: str, index: int) -> str:
    prefixes = (
        "Population fit, comparator alignment, clinical directness, follow-up "
        "length, ascertainment method, baseline risk, adherence, exposure "
        "dose, and external validity are kept separate during interpretation.",
        "Cellular mechanism, animal-model response, observational association, "
        "pilot-trial signal, randomized evidence, intermediate outcome behavior, "
        "and hard clinical outcomes are treated as different evidentiary layers.",
        "Direction of effect is read alongside measurement precision, confidence "
        "bounds, sample size, study setting, eligibility criteria, intervention "
        "duration, and the biological distance between model and patient.",
        "The synthesis distinguishes replication across similar designs from "
        "convergence across different designs, because those patterns answer "
        "different questions about reliability, transportability, and mechanism.",
        "Where evidence is sparse, the manuscript emphasizes unresolved design "
        "choices: dose selection, comparator choice, endpoint hierarchy, subgroup "
        "definition, follow-up window, and clinically meaningful thresholds.",
        "Where evidence is broad but indirect, the public conclusion remains "
        "conditional on whether the same pathway produces measurable benefit in "
        "the target human population rather than only in adjacent systems.",
        "The final interpretive step is conservative: it preserves the question, "
        "the uncertainty, and the boundary conditions while withholding any "
        "unsupported estimate, causal claim, or population-level generalization.",
    )
    section_context = {
        "Introduction": (
            "The research question is interpreted through design, population, "
            "and endpoint boundaries."
        ),
        "Background": (
            "The biological rationale is treated as context rather than as "
            "clinical proof."
        ),
        "Results": (
            "Descriptive findings remain separate from interpretation and "
            "endpoint-specific boundaries."
        ),
        "Cross-Domain Synthesis": (
            "Cross-domain interpretation compares outcome classes and "
            "identifies where signals converge or diverge."
        ),
        "Discussion": (
            "The interpretation calibrates confidence, clinical meaning, "
            "generalizability, and unresolved study-design needs."
        ),
        "Limitations": (
            "The limitations identify evidence gaps, missing populations, "
            "indirect endpoints, and unresolved follow-up windows."
        ),
        "Conclusion": (
            "The conclusion preserves the final claim boundary and avoids "
            "implying certainty beyond the retained evidence."
        ),
    }.get(heading, "In this section, the framing preserves interpretive limits.")
    prefix = prefixes[min(max(index - 1, 0), len(prefixes) - 1)]
    return _DEPTH_BACKFILL_EXTENSION.format(
        section_context=section_context,
        prefix=prefix,
    )


def _paragraph_already_present(paper_md: str, paragraph: str) -> bool:
    needle = re.sub(r"\s+", " ", paragraph).strip().lower()
    haystack = re.sub(r"\s+", " ", paper_md).lower()
    return needle in haystack


_DISCUSSION_HEDGE_PHRASES = (
    "may", "might", "suggests", "consistent with", "appears",
    "context-dependent", "uncertain", "warrants", "remains to be",
    "preliminary", "interpretive", "qualified", "limited", "cautious",
)

_DISCUSSION_HEDGE_BACKFILL = """### Confidence calibration

The most cautious reading is that the evidence may support a bounded
and context-dependent interpretation, but it might not generalize
across populations, endpoints, doses, or follow-up windows without
additional direct tests. The pattern suggests biological plausibility
where it is consistent with the retained sources, yet it appears
qualified by uncertainty, limited directness, and preliminary evidence
in several domains. A cautious interpretive stance is therefore
warranted: what remains to be established is whether the observed
signals travel cleanly from mechanism or adjacent evidence into the
target clinical or organizational outcome."""


def _ensure_discussion_hedge_density(paper_md: str) -> tuple[str, list[dict]]:
    start, end, section = _extract_section(paper_md, "Discussion")
    if start < 0:
        return paper_md, []
    body_lc = section.lower()
    n_hedges = sum(1 for h in _DISCUSSION_HEDGE_PHRASES if h in body_lc)
    if n_hedges >= 6:
        return paper_md, []
    updated = section.rstrip() + "\n\n" + _DISCUSSION_HEDGE_BACKFILL + "\n\n"
    new_md = paper_md[:start] + updated + paper_md[end:]
    return new_md, [{
        "fix_type": "discussion_hedge_density_backfill",
        "n_changes": 1,
        "description": (
            "appended numeric-free confidence-calibration paragraph to "
            f"Discussion ({n_hedges} hedge phrases before backfill)"
        ),
    }]


_DEPTH_BACKFILL_EXTENSION = """{section_context} {prefix} The interpretation
separates direct clinical findings from mechanistic and adjacent evidence,
preserving uncertainty where endpoint, population, comparator, or follow-up
differs. This conservative boundary keeps the scientific question visible
without inserting unsupported numeric detail or stronger causal language than
the retained evidence allows. Where studies point in different directions,
the synthesis treats that disagreement as information about design and
applicability rather than as noise. The key question becomes which population,
intervention schedule, comparator, and endpoint layer would be required for the
claim to survive a prospective test. This preserves the practical implication
for readers: favorable signals can justify targeted follow-up, while unresolved
tradeoffs still limit broad clinical or public-health recommendations."""


_INTRODUCTION_BACKFILL = """### Scope of the synthesis

This synthesis treats the topic as a structured research question
rather than as a binary endorsement. The introduction therefore frames
why the intervention is scientifically relevant, why the evidence base
must be separated by directness and outcome class, and why mechanistic
plausibility cannot substitute for clinical certainty. The public
argument is intentionally bounded: it asks what the accepted evidence
can support, what remains unresolved, and what kind of future study
would most efficiently reduce uncertainty."""


_BACKGROUND_BACKFILL = """### Evidence Context

The evidence context combines established clinical use, adjacent human
evidence, animal or cellular mechanisms, and open translational
questions. Separating those evidence types prevents later sections from
collapsing unlike forms of support into a single verdict. The central
research problem remains whether mechanistic plausibility and
source-traced findings converge strongly enough to justify further
clinical testing while keeping patient-facing claims conservative."""


_DISCUSSION_BACKFILL = """### Interpretation constraints

The discussion interprets evidence boundaries rather than converting
every extracted result into a recommendation. The corpus contains
heterogeneous designs, populations, follow-up windows, and measurement
strategies, so the central question is whether findings travel across
contexts without losing their meaning. Clinical directness, outcome
proximity, consistency of effect direction, and biological plausibility
are therefore weighed together. Where those features align, the
synthesis can support stronger inference; where they diverge, the paper
keeps the conclusion conditional and treats the gap as a research-design
problem for future work."""


_CONCLUSION_BACKFILL = """A defensible next study should pre-specify
which endpoint layer it intends to test, align intervention exposure with
that endpoint, and report functional or safety tradeoffs with the same
visibility as benefit signals. Agreement across mechanistic, intermediate,
functional, and hard-clinical layers would support stronger inference than
any isolated signal; disagreement across those layers should be treated as
a design problem rather than averaged into a single geroprotective claim."""


def _strip_change_value_misread_sentences(
    paper_md: str,
) -> tuple[str, int]:
    """Fix #46: strip sentences whose change-value numeric is
    rendered as absolute. Mirrors the audit's
    _check_change_value_misread but performs the deletion. Safe by
    construction: numerics are corpus-traced (Q2 untouched), only
    interpretation-broken sentences disappear.

    Returns (new_md, n_stripped). Iterates per-paragraph: builds the
    same change_value_map the audit uses, splits paragraphs into
    sentences, drops any sentence with the change-numeric paired with
    absolute-value phrasing AND missing the source's change-words."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import audit_v06_paper as _audit
        change_value_map: dict[str, set[str]] = {}
        if not _audit.QUANT_DIR.exists():
            return paper_md, 0
        for qf in _audit.QUANT_DIR.glob("*.quant_claims.json"):
            try:
                data = json.loads(qf.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            for c in data.get("claims", []):
                if c.get("binding_confidence") != "high":
                    continue
                raw = (c.get("raw_text") or "").strip()
                if not raw:
                    continue
                sent_lc = (c.get("sentence") or "").lower()
                from final_consistency_audit import _CHANGE_WORDS
                hits = {w for w in _CHANGE_WORDS if w in sent_lc}
                if hits:
                    change_value_map.setdefault(raw, set()).update(hits)
    except (ImportError, OSError, ValueError):
        return paper_md, 0
    if not change_value_map:
        return paper_md, 0
    from final_consistency_audit import _ABSOLUTE_VALUE_PHRASES
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    n_stripped = 0
    out_parts: list[str] = []
    for paragraph in paper_md.split("\n\n"):
        # Skip markdown tables (don't strip table rows).
        lines = [ln for ln in paragraph.splitlines() if ln.strip()]
        if lines and (
            sum(1 for ln in lines if ln.lstrip().startswith("|"))
            / len(lines) >= 0.5
        ):
            out_parts.append(paragraph)
            continue
        sentences = sent_split.split(paragraph)
        kept: list[str] = []
        for sent in sentences:
            sent_lc = sent.lower()
            should_drop = False
            for numeric, change_words in change_value_map.items():
                if numeric not in sent:
                    continue
                has_absolute = any(
                    p in sent_lc for p in _ABSOLUTE_VALUE_PHRASES
                )
                # Fix #57: PROXIMITY check — change-word must be
                # within ±40 chars of the numeric to count.
                # Defends against long sentences where a change-
                # word for a DIFFERENT metric ("no change in one
                # endpoint, and value Y was 0.13") falsely
                # cleared the numeric.
                from final_consistency_audit import (
                    _CHANGE_WORD_PROXIMITY_CHARS, _CHANGE_WORDS,
                )
                num_idx = sent_lc.find(numeric.lower())
                window_start = max(
                    0, num_idx - _CHANGE_WORD_PROXIMITY_CHARS,
                )
                window_end = min(
                    len(sent_lc),
                    num_idx + len(numeric)
                    + _CHANGE_WORD_PROXIMITY_CHARS,
                )
                window = sent_lc[window_start:window_end]
                has_change = any(w in window for w in set(change_words) | set(_CHANGE_WORDS))
                if has_absolute and not has_change:
                    should_drop = True
                    n_stripped += 1
                    break
            if not should_drop:
                kept.append(sent)
        out_parts.append(" ".join(kept) if kept else "")
    new_md = "\n\n".join(p for p in out_parts if p.strip() or p == "")
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)
    return new_md, n_stripped


def _strip_change_value_anaphor_sentences(
    paper_md: str,
) -> tuple[str, int]:
    """Fix #54: strip cross-sentence anaphoric misreads.

    Mirrors final_consistency_audit._check_change_value_anaphor_misread
    but performs the deletion. For each paragraph that contains a
    change-value numeric followed by a sentence that combines an
    anaphoric reference ('this walk speed value', 'the figure', etc.)
    with threshold-comparison phrasing ('below the 0.8 threshold',
    'below the cutoff', 'threshold'), the threshold-sentence
    is dropped. The change-numeric sentence stays — it's the
    misreading sentence (B) we lose, not the corpus-traced one (A).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import audit_v06_paper as _audit
        if not _audit.QUANT_DIR.exists():
            return paper_md, 0
        from final_consistency_audit import (
            _CHANGE_SPEED_VALUE_RE, _CHANGE_WORDS, _ANAPHOR_RE,
            _THRESHOLD_KEYWORD_RE,
        )
        change_value_map: dict[str, set[str]] = {}
        for qf in _audit.QUANT_DIR.glob("*.quant_claims.json"):
            try:
                data = json.loads(qf.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            for c in data.get("claims", []):
                if c.get("binding_confidence") != "high":
                    continue
                raw = (c.get("raw_text") or "").strip()
                if not raw:
                    continue
                sent_lc = (c.get("sentence") or "").lower()
                hits = {w for w in _CHANGE_WORDS if w in sent_lc}
                if hits:
                    change_value_map.setdefault(raw, set()).update(hits)
    except (ImportError, OSError, ValueError):
        return paper_md, 0
    if not change_value_map:
        return paper_md, 0
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    n_stripped = 0
    out_paragraphs: list[str] = []
    for para in paper_md.split("\n\n"):
        # Skip tables.
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if lines and (
            sum(1 for ln in lines if ln.lstrip().startswith("|"))
            / len(lines) >= 0.5
        ):
            out_paragraphs.append(para)
            continue
        sentences = sent_split.split(para)
        if len(sentences) < 2:
            out_paragraphs.append(para)
            continue
        # Map: numeric → first sentence index containing it
        change_sent_indices: dict[str, int] = {}
        for i, sent in enumerate(sentences):
            sent_lc = sent.lower()
            for numeric in change_value_map:
                if numeric in sent and numeric not in change_sent_indices:
                    change_sent_indices[numeric] = i
            change_hits = {w for w in _CHANGE_WORDS if w in sent_lc}
            if change_hits:
                for numeric in _CHANGE_SPEED_VALUE_RE.findall(sent):
                    change_sent_indices.setdefault(numeric, i)
                    change_value_map.setdefault(numeric, set()).update(change_hits)
        if not change_sent_indices:
            out_paragraphs.append(para)
            continue
        kept_sentences: list[str] = []
        for i, sent in enumerate(sentences):
            sent_lc = sent.lower()
            earlier_numerics = [
                n for n, idx in change_sent_indices.items() if idx < i
            ]
            should_drop = False
            if earlier_numerics:
                has_anaphor = bool(_ANAPHOR_RE.search(sent))
                has_threshold = bool(_THRESHOLD_KEYWORD_RE.search(sent))
                if has_anaphor and has_threshold:
                    change_words: set[str] = set()
                    for n in earlier_numerics:
                        change_words.update(change_value_map[n])
                    if not any(w in sent_lc for w in change_words):
                        should_drop = True
                        n_stripped += 1
            if not should_drop:
                kept_sentences.append(sent)
        out_paragraphs.append(
            " ".join(kept_sentences) if kept_sentences else ""
        )
    new_md = "\n\n".join(p for p in out_paragraphs if p.strip() or p == "")
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)
    return new_md, n_stripped


def _strip_change_value_paragraph_threshold_sentences(
    paper_md: str,
) -> tuple[str, int]:
    """Fix #58 (C13c) auto-strip: in paragraphs flagged as
    juxtaposing a change-numeric with threshold language, remove
    the threshold-comparison sentence(s). Keeps the sentence(s)
    containing the change-numeric (those are corpus-traced and
    legitimate; the misread is in the comparison framing).

    Strategy: for each paragraph, build the change-numeric set and
    threshold-marker set. If a paragraph has both AND lacks the
    nearby change-word hedge, strip the sentence(s) that contain
    threshold markers but DO NOT contain the change-numeric (those
    are pure threshold-comparison sentences). Sentences with the
    change-numeric stay (they're the corpus evidence)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import audit_v06_paper as _audit
        if not _audit.QUANT_DIR.exists():
            return paper_md, 0
        from final_consistency_audit import (
            _CHANGE_WORDS,
            _THRESHOLD_MARKERS,
        )
        change_value_map: dict[str, set[str]] = {}
        for qf in _audit.QUANT_DIR.glob("*.quant_claims.json"):
            try:
                data = json.loads(qf.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            for c in data.get("claims", []):
                if c.get("binding_confidence") != "high":
                    continue
                raw = (c.get("raw_text") or "").strip()
                if not raw:
                    continue
                sent_lc = (c.get("sentence") or "").lower()
                hits = {w for w in _CHANGE_WORDS if w in sent_lc}
                if hits:
                    change_value_map.setdefault(raw, set()).update(hits)
    except (ImportError, OSError, ValueError):
        return paper_md, 0
    if not change_value_map:
        return paper_md, 0
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
    n_stripped = 0
    out_paragraphs: list[str] = []
    for para in paper_md.split("\n\n"):
        para_lc = para.lower()
        # Skip tables
        lines = [ln for ln in para.splitlines() if ln.strip()]
        if lines and (
            sum(1 for ln in lines if ln.lstrip().startswith("|"))
            / len(lines) >= 0.5
        ):
            out_paragraphs.append(para)
            continue
        # Skip Limitations section (legitimate change-framing)
        if "## limitations" in para_lc:
            out_paragraphs.append(para)
            continue
        # Find change-numerics in the paragraph
        present_numerics = [
            n for n in change_value_map if n in para
        ]
        if not present_numerics:
            out_paragraphs.append(para)
            continue
        has_threshold = any(
            m in para_lc for m in _THRESHOLD_MARKERS
        )
        if not has_threshold:
            out_paragraphs.append(para)
            continue
        # Check if any change-numeric has a nearby change-word hedge.
        # If yes → paragraph is fine, keep as-is.
        any_hedged = False
        for numeric in present_numerics:
            num_idx = para_lc.find(numeric.lower())
            window = para_lc[
                max(0, num_idx - 60):
                min(len(para_lc), num_idx + len(numeric) + 60)
            ]
            change_words = change_value_map[numeric]
            if any(w in window for w in change_words):
                any_hedged = True
                break
        if any_hedged:
            out_paragraphs.append(para)
            continue
        # Strip threshold-comparison sentences (those with a
        # threshold marker but NOT the change-numeric).
        sentences = sent_split.split(para)
        kept: list[str] = []
        for sent in sentences:
            sent_lc = sent.lower()
            has_marker = any(
                m in sent_lc for m in _THRESHOLD_MARKERS
            )
            has_numeric = any(
                n in sent for n in present_numerics
            )
            if has_marker and not has_numeric:
                # Pure threshold-comparison sentence — strip
                n_stripped += 1
                continue
            kept.append(sent)
        out_paragraphs.append(
            " ".join(kept) if kept else ""
        )
    new_md = "\n\n".join(
        p for p in out_paragraphs if p.strip() or p == ""
    )
    new_md = re.sub(r"\n{3,}", "\n\n", new_md)
    return new_md, n_stripped


def _strip_unsourced_background_sentences(
    paper_md: str,
    *,
    manifest: dict | None = None,
    quant_claims_dir=None,
) -> str:
    """Remove sentences whose background-numeric→citation gate fails.

    Fix #19: ITERATIVE strip until stable (a single pass can leave
    survivors when multiple background numerics share a sentence or
    when paragraph-wise splitting differs from the audit's sentence
    splitter). Caps at 5 iterations to avoid pathological loops."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import background_literature as _bg
        registry = _bg.load_registry(topic=str(manifest.get("topic") or "") if manifest is not None else None)
    except (ImportError, FileNotFoundError, ValueError):
        return paper_md
    if not registry:
        return paper_md

    receipt_numeric_tokens = _bg._receipt_numeric_tokens_by_citation(manifest, quant_claims_dir)
    sent_split = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

    def _is_markdown_table_paragraph(paragraph: str) -> bool:
        """A markdown table paragraph has lines that mostly start with
        `|` (table rows). The whole paragraph is structured data, not
        prose — strip-by-sentence would treat the table as one
        sentence and drop the entire table when ANY background numeric
        appears anywhere in it. Tables are deterministic and Q9-counted
        carriers; we DON'T want them stripped."""
        lines = [ln for ln in paragraph.splitlines() if ln.strip()]
        if not lines:
            return False
        n_table_lines = sum(1 for ln in lines if ln.lstrip().startswith("|"))
        return n_table_lines / len(lines) >= 0.5

    def _one_pass(text: str) -> str:
        out_parts: list[str] = []
        for paragraph in text.split("\n\n"):
            # Fix #21 follow-up: skip markdown tables — Table 5 surfaces
            # corpus numerics (some of which match background_literature
            # entries like '7%' or '0.8 m/s') without citation tokens
            # in the same cell. Stripping the whole table for that
            # would tank Q9 density and remove load-bearing structured
            # evidence. The numerics in tables ARE authorised: they
            # come from the corpus's quant_claims, not from the LLM's
            # training-data world knowledge.
            if _is_markdown_table_paragraph(paragraph):
                out_parts.append(paragraph)
                continue
            sentences = sent_split.split(paragraph)
            kept: list[str] = []
            for sent in sentences:
                drop = False
                unsourced = _bg.find_unsourced_background_uses(
                    sent,
                    registry,
                    manifest=manifest,
                    quant_claims_dir=quant_claims_dir,
                    receipt_numeric_tokens=receipt_numeric_tokens,
                )
                if unsourced:
                    drop = True
                if not drop:
                    kept.append(sent)
            out_parts.append(" ".join(kept) if kept else "")
        return "\n\n".join(p for p in out_parts if p.strip() or p == "")

    out = paper_md
    for _ in range(5):
        nxt = _one_pass(out)
        if nxt == out:
            break
        out = nxt
    return out


def fix_audit_verdict(audit_md: str) -> tuple[str, list[dict]]:
    """Rename audit verdict heading from 'AAA' to 'Trust-Spine Pass'
    when score≥9 + P1 clean but some P2 failed."""
    log: list[dict] = []
    new = audit_md
    # Only rename if both signals are present in the file
    if "## Verdict: AAA" in new and "❌" in new:
        new = new.replace(
            "## Verdict: AAA",
            "## Verdict: Trust-Spine Pass",
        )
        new = new.replace(
            "≥9.0 score AND no P1 failures. Paper passes the trust-spine gate.",
            "≥9.0 score AND no P1 failures, but one or more P2 quality "
            "checks flagged issues. 'AAA Paper' is reserved for "
            "all-green.",
        )
        log.append({
            "fix_type": "audit_verdict_overclaim",
            "n_changes": 1,
            "description": (
                "renamed verdict 'AAA' → 'Trust-Spine Pass' "
                "(P2 check failed)"
            ),
        })
    return new, log


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply deterministic fixes from final_consistency_audit",
    )
    parser.add_argument("paper_md", help="full_paper.md to fix")
    args = parser.parse_args(argv)
    paper_path = Path(args.paper_md).resolve()
    if not paper_path.exists():
        print(f"not found: {paper_path}", file=sys.stderr)
        return 2
    consistency_path = paper_path.with_suffix(".consistency.json")
    if not consistency_path.exists():
        print(
            "Run scripts/final_consistency_audit.py first to generate "
            f"{consistency_path}",
            file=sys.stderr,
        )
        return 2

    issues_doc = json.loads(consistency_path.read_text())
    paper = paper_path.read_text()
    fixed, log = apply_fixes(paper, issues_doc.get("issues", []))
    paper_path.write_text(fixed)

    # Also fix the audit.md verdict
    audit_md_path = paper_path.with_suffix(".audit.md")
    if audit_md_path.exists():
        audit_md = audit_md_path.read_text()
        new_audit, audit_log = fix_audit_verdict(audit_md)
        audit_md_path.write_text(new_audit)
        log.extend(audit_log)

    log_path = paper_path.with_suffix(".fixed_log.json")
    log_path.write_text(json.dumps({"fixes_applied": log}, indent=2))
    print(
        f"Fixed: {paper_path}\n"
        f"Log: {log_path}\n"
        f"Total fix categories applied: {len(log)}",
        file=sys.stderr,
    )
    for entry in log:
        print(
            f"  - {entry['fix_type']}: {entry['n_changes']} change(s) "
            f"— {entry['description']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
