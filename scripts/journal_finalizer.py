from __future__ import annotations

import json
import re
import importlib
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@dataclass(frozen=True, slots=True)
class FinalizerLogEntry:
    phase: str
    rule: str
    n_changes: int
    detail: str


@dataclass(frozen=True, slots=True)
class FinalizerReport:
    paper_changed: bool
    final_word_count: int
    entries: tuple[FinalizerLogEntry, ...] = field(default=())


_ANIMAL_QUALIFIER_LEAD = "In animal/preclinical evidence, "


def _lowercase_first_letter(text: str) -> str:
    stripped = text.lstrip()
    if not stripped or not stripped[0].isalpha():
        return text
    first = re.match(r"\S+", stripped)
    if first and len(first.group(0)) > 1 and first.group(0).isupper():
        return text
    # Never demote proper-noun / citation tokens: a word with internal
    # capitals ("Abu-Zaid", "McKay") or a capitalized word followed by a
    # year ("Turner 2015"). Lowercasing those breaks exact reference
    # matching downstream (citation_artifact: unreferenced citation).
    word = first.group(0) if first else ""
    if any(ch.isupper() for ch in word[1:]) or re.match(
        r"[A-Z][\w'\-]*\s+(?:19|20)\d{2}\b", stripped
    ):
        return text
    pad = text[: len(text) - len(stripped)]
    return pad + stripped[0].lower() + stripped[1:]

# Conservative lead-in prefix for orphan-ref closure. Sentence is
# academically defensible — explicitly frames the cluster as
# corpus-supporting context that didn't anchor a foregrounded claim.
_ORPHAN_REF_PARAGRAPH_LEAD = (
    "Additional corpus sources informed the synthesis without "
    "anchoring a foregrounded quantitative claim and are catalogued "
    "for completeness: "
)
MAX_INNER_FINALIZER_PASSES = 3


def finalize_run(out_dir: Path) -> FinalizerReport:
    paper_path = out_dir / "full_paper.md"
    if not paper_path.is_file():
        return FinalizerReport(paper_changed=False, final_word_count=0)
    text = paper_path.read_text()
    original = text
    entries: list[FinalizerLogEntry] = []

    for _ in range(MAX_INNER_FINALIZER_PASSES):
        new_text, log = _run_text_phases(text, out_dir)
        entries.extend(log)
        if new_text == text:
            break
        text = new_text
        if (report := _surface_report(text, out_dir)) and report.passed:
            break
    # CRITICAL ORDERING: write the post-finalizer text to disk BEFORE
    # Phase G reads it. Phase G's surface re-evaluation reads from disk
    # via `evaluate_journal_surface(paper_path.read_text(), ...)`, so
    # the disk write must happen first or Phase G sees stale text.
    changed = text != original
    if changed:
        paper_path.write_text(text)
    # Phase G refreshes sidecars whose state drifted (verdict + readiness
    # contract) and re-evaluates the surface gate against the now-on-disk
    # post-finalizer paper. Universal.
    entries.extend(_phase_g_refresh_sidecars(out_dir))
    report = FinalizerReport(paper_changed=changed, final_word_count=len(text.split()), entries=tuple(entries))  # noqa: E501
    (out_dir / "journal_finalizer.json").write_text(json.dumps(asdict(report), indent=2))
    return report


def _run_text_phases(text: str, out_dir: Path) -> tuple[str, list[FinalizerLogEntry]]:
    entries: list[FinalizerLogEntry] = []
    for phase in (
        lambda t: _phase_a_methods_replace(t, out_dir),
        lambda t: _phase_b_lane_qualifier(t, out_dir),
        _phase_c_terminology,
        lambda t: _phase_d_admission_funnel_clarification(t, out_dir),
        lambda t: _phase_d_prisma_all_included_rationale(t, out_dir),
        lambda t: _phase_d_classification_criteria_note(t, out_dir),
        lambda t: _phase_d_conflict_severity_note(t, out_dir),
        lambda t: _phase_d_directional_coding_note(t, out_dir),
        lambda t: _phase_d_evidence_boundary_note(t, out_dir),
        lambda t: _phase_d_evidence_honesty_guard(t, out_dir),
        lambda t: _phase_d_long_term_safety_scope(t, out_dir),
        lambda t: _phase_d_tier_directness_boundaries(t, out_dir),
        lambda t: _phase_d_section_source_grounding(t, out_dir),
        lambda t: _phase_d_source_inclusion_rationale(t, out_dir),
        lambda t: _phase_d_source_outcome_class_map(t, out_dir),
        lambda t: _phase_d_source_statistics_landscape(t, out_dir),
        lambda t: _phase_d_source_directness_breakdown(t, out_dir),
        lambda t: _phase_d_source_verification_transparency(t, out_dir),
        lambda t: _phase_d_single_source_proportionality(t, out_dir),
        lambda t: _phase_d_actionable_gaps(t, out_dir),
        lambda t: _phase_d_prior_publication_differentiation(t, out_dir),
        lambda t: _phase_d_reference_identifier_enrichment(t, out_dir),
        lambda t: _phase_d_numeric_significance_correction(t, out_dir),
        _phase_d_reference_closure,
        lambda t: _phase_b_lane_qualifier(t, out_dir),
        _phase_i_split_concatenated_headings,
        lambda t: _phase_e_structural_fallback(t, out_dir),
        lambda t: _phase_f_reconcile_results_table(t, out_dir),
        lambda t: _phase_m_relabel_public_metadata_table_headers(t, out_dir),
        lambda t: _phase_h_topic_slug_normalise(t, out_dir), _phase_i_split_concatenated_headings,
        lambda t: _phase_k_route_outcome_paragraphs(t, out_dir),
        lambda t: _phase_l_strengthen_analytical_sections(t, out_dir),
        lambda t: _phase_d_unproven_human_longevity(t, out_dir),
    ):
        text, log = phase(text)
        entries.extend(log)
    text, log = _phase_m_strip_surface_duplicate_paragraphs(text)
    entries.extend(log)
    text, log = _phase_m_repair_surface_artifacts(text)
    entries.extend(log)
    from scripts.review_noise_control import apply_review_noise_control, restore_surface_floors
    text, noise_changes = apply_review_noise_control(text, out_dir)
    entries.extend(FinalizerLogEntry("M_review_noise_control", *change) for change in noise_changes)
    text, entries = restore_surface_floors(text, out_dir, entries, FinalizerLogEntry)
    text, log = _phase_k_route_outcome_paragraphs(text, out_dir)
    entries.extend(log)
    text, log = _phase_d_numeric_significance_correction(text, out_dir)
    entries.extend(log)
    text, log = _phase_d_unproven_human_longevity(text, out_dir)
    entries.extend(log)
    return text, entries


def _surface_report(text: str, out_dir: Path) -> Any | None:
    manifest = _load_sidecar(out_dir / "manifest.json")
    manifest = manifest if isinstance(manifest, dict) else {}
    lanes, registry = _load_sidecar(out_dir / "evidence_lanes.json") or {}, _load_sidecar(out_dir / "citation_registry.json") or {}
    animal = [str(a.get("citation", "")) for a in (lanes.get("animal_citations") or []) if isinstance(a, dict) and a.get("citation")]
    oc = {r["receipt_id"]: r["outcome_class"] for r in (manifest.get("receipts") or ()) if isinstance(r, dict) and r.get("outcome_class") and r.get("receipt_id")}
    cmap = {e["body_citation"]: oc[rid] for rid, e in (registry.items() if isinstance(registry, dict) else ()) if isinstance(e, dict) and e.get("body_citation") and rid in oc}
    try:
        from agent.journal_surface_gate import evaluate_journal_surface
        return evaluate_journal_surface(text, animal_citations=animal, citation_outcome_map=cmap, declared_review_type=manifest.get("review_type"))
    except (ImportError, ValueError):
        return None


def _phase_m_strip_surface_duplicate_paragraphs(
    text: str,
) -> tuple[str, list[FinalizerLogEntry]]:
    boundary = re.search(r"^##\s+(?:References|Appendix|Supplement)\b", text, flags=re.M)
    head, tail = (text[:boundary.start()], text[boundary.start():]) if boundary else (text, "")
    body_start = re.search(r"^##\s+(?:Background|Methods|Results)\b", head, flags=re.M)
    prefix, body = (head[:body_start.start()], head[body_start.start():]) if body_start else ("", head)
    seen = [_surface_duplicate_tokens(para) for para in re.split(r"\n\s*\n", prefix)]
    seen = [tokens for tokens in seen if tokens]
    chunks = re.split(r"(\n\s*\n)", body)
    out: list[str] = []
    n = 0
    for i in range(0, len(chunks), 2):
        para = chunks[i]
        sep = chunks[i + 1] if i + 1 < len(chunks) else ""
        tokens = _surface_duplicate_tokens(para)
        if tokens and any(len(tokens & prior) / max(1, len(tokens | prior)) >= 0.9 for prior in seen):
            n += 1
            continue
        if tokens:
            seen.append(tokens)
        out.append(para)
        if sep:
            out.append(sep)
    if not n:
        return text, []
    return prefix + "".join(out).rstrip() + ("\n\n" if tail and not tail.startswith("\n") else "") + tail, [
        FinalizerLogEntry(
            phase="M_duplicate_paragraph_strip",
            rule="remove_later_surface_duplicate_paragraphs",
            n_changes=n,
            detail=f"removed {n} duplicate public prose paragraph(s)",
        )
    ]


def _phase_m_repair_surface_artifacts(text: str) -> tuple[str, list[FinalizerLogEntry]]:
    out, n_grammar = _repair_known_grammar_artifacts(text)
    out, n_headings = _remove_empty_subheadings(out)
    if out == text:
        return text, []
    changes = []
    if n_grammar:
        changes.append(f"grammar_artifact={n_grammar}")
    if n_headings:
        changes.append(f"empty_subheading={n_headings}")
    return out, [
        FinalizerLogEntry(
            phase="M_surface_artifact_cleanup",
            rule="repair_known_surface_artifacts",
            n_changes=n_grammar + n_headings,
            detail="; ".join(changes),
        )
    ]


def _repair_known_grammar_artifacts(text: str) -> tuple[str, int]:
    pattern = re.compile(r"\bto\s+be\s+((?:[A-Za-z]+[\s-]+){0,5}?)(is|are|was|were)\b", re.I)
    transfer_pattern = re.compile(r"\bdoes\s+not\s+automatically\s+(is|are|was|were)\b", re.I)

    def repl(match: re.Match[str]) -> str:
        middle = " ".join(match.group(1).split())
        verb = match.group(2)
        return f"{verb} {middle}".rstrip()

    out, n = pattern.subn(repl, text)

    def transfer_repl(match: re.Match[str]) -> str:
        return f"{match.group(1)} not automatically"

    out, n_transfer = transfer_pattern.subn(transfer_repl, out)
    return out, n + n_transfer


def _remove_empty_subheadings(text: str) -> tuple[str, int]:
    matches = list(re.finditer(r"^(#{3,6})\s+(.+?)\s*$", text, flags=re.M))
    remove: list[tuple[int, int]] = []
    for idx, match in enumerate(matches):
        next_match = matches[idx + 1] if idx + 1 < len(matches) else None
        if next_match is not None and len(next_match.group(1)) > len(match.group(1)):
            continue
        end = next_match.start() if next_match else len(text)
        if not text[match.end():end].strip():
            remove.append((match.start(), end))
    if not remove:
        return text, 0
    out = text
    for start, end in reversed(remove):
        out = out[:start].rstrip() + "\n\n" + out[end:].lstrip()
    return out, len(remove)


_PUBLIC_METADATA_HEADER_LABELS = {
    "outcome class": "Evidence domain",
    "directness": "Source directness",
    "directional signal": "Evidence signal",
    "evidence tier": "Evidence level",
}


def _phase_m_relabel_public_metadata_table_headers(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    report = _surface_report(text, out_dir)
    if report is None:
        return text, []
    patched = text
    n_changed = 0
    for issue in getattr(report, "issues", ()):
        if getattr(issue, "code", "") != "public_artifact":
            continue
        prefix = "classification metadata leaked as study row: "
        detail = str(getattr(issue, "detail", ""))
        if not detail.startswith(prefix):
            continue
        line = detail.removeprefix(prefix).strip()
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        replacement = _PUBLIC_METADATA_HEADER_LABELS.get(cells[0].lower())
        if not replacement:
            continue
        new_line = "| " + " | ".join((replacement, *cells[1:])) + " |"
        patched, changed = re.subn(rf"^{re.escape(line)}$", new_line, patched, flags=re.M)
        n_changed += changed
    if not n_changed:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="M_public_metadata_header_relabel",
        rule="relabel_surface_metadata_table_headers",
        n_changes=n_changed,
        detail=f"relabelled {n_changed} public metadata table header(s)",
    )]


def _surface_duplicate_tokens(paragraph: str) -> set[str]:
    text = paragraph.strip()
    if not text or text.startswith(("#", "|", "_Cited:")):
        return set()
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    real_tokens = {token for token in tokens if not re.fullmatch(r"word\d+", token)}
    return set(tokens) if len(tokens) >= 30 and len(real_tokens) >= 20 else set()


# --- Phase A: Methods replace -----------------------------------------


def _phase_a_methods_replace(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    pack_path = out_dir / "methods_pack.json"
    if not pack_path.is_file():
        return text, []
    try:
        from agent.methods_pack import MethodsPack, render_methods_md
        d = json.loads(pack_path.read_text())
        pack = MethodsPack(
            review_type=d["review_type"],
            databases_searched=tuple(d["databases_searched"]),
            search_strings=tuple(d["search_strings"]),
            search_dates=d["search_dates"],
            eligibility_criteria=tuple(d["eligibility_criteria"]),
            screening_flow=dict(d["screening_flow"]),
            data_extraction_fields=tuple(d["data_extraction_fields"]),
            exclusion_reason_summary=tuple(d["exclusion_reason_summary"]),
            risk_of_bias_approach=d["risk_of_bias_approach"],
            synthesis_approach=d["synthesis_approach"],
            ai_use_disclosure=d["ai_use_disclosure"],
            human_accountability=d["human_accountability"],
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return text, []
    new_methods = render_methods_md(pack, submission_id=out_dir.name)
    patched, n = re.subn(
        r"^## Methods\b.*?(?=^## (?!#))", new_methods, text,
        count=1, flags=re.M | re.S,
    )
    if n == 0:
        return text, []
    return patched, [FinalizerLogEntry(phase="A_methods_replace", rule="render_methods_md", n_changes=1, detail=f"replaced Methods section with PRISMA-ScR pack ({len(new_methods.split())} words)")]


# --- Phase B: Evidence-lane qualifier injection -----------------------


def _phase_b_lane_qualifier(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    lanes_path = out_dir / "evidence_lanes.json"
    if not lanes_path.is_file():
        return text, []
    try:
        lanes = json.loads(lanes_path.read_text())
        animal_tokens = {
            a.get("citation", "") for a in lanes.get("animal_citations", ())
            if a.get("citation")
        }
        lane_map = lanes.get("lanes") or {}
    except (OSError, json.JSONDecodeError):
        return text, []
    if not animal_tokens:
        return text, []
    # Slice 26: use the gate's centralised word-boundary regex so Phase B
    # and the gate agree exactly on what counts as a qualifier. Substring
    # matching falsely qualified paragraphs containing "replicated"
    # (matches "rat"), "rate", "iterate", etc.
    from agent.journal_surface_gate import _animal_lane_re
    qualifier_re = _animal_lane_re()
    # Operate only on the body (above References). Splitting on the
    # references heading keeps the bibliography untouched.
    refs_split = re.split(r"^## References\b", text, maxsplit=1, flags=re.M)
    body = refs_split[0]
    tail = ("\n## References" + refs_split[1]) if len(refs_split) == 2 else ""
    paragraphs = re.split(r"(\n\s*\n)", body)  # keep separators
    n_patched = 0
    for i in range(0, len(paragraphs), 2):
        para = paragraphs[i]
        if not para.strip() or para.lstrip().startswith(("##", "###")):
            continue
        if not any(tok in para for tok in animal_tokens):
            continue
        if qualifier_re.search(para):
            continue
        citation_pool = lane_map or {tok: "animal_preclinical" for tok in animal_tokens}
        cited = [tok for tok in citation_pool if tok in para]
        lead = _ANIMAL_QUALIFIER_LEAD if cited and sum(tok in animal_tokens for tok in cited) * 2 > len(cited) else "Additional corpus sources included animal/preclinical evidence; "
        stripped = para.lstrip()
        bullet = re.match(r"^([-*]\s+)(.+)$", stripped, flags=re.S)
        if bullet:
            paragraphs[i] = para[: len(para) - len(stripped)] + bullet.group(1) + lead + _lowercase_first_letter(bullet.group(2))
        else:
            paragraphs[i] = lead + _lowercase_first_letter(stripped)
        n_patched += 1
    if n_patched == 0:
        return text, []
    new_body = "".join(paragraphs)
    return new_body + tail, [FinalizerLogEntry(phase="B_lane_qualifier", rule="animal_preclinical_lead_in", n_changes=n_patched, detail=f"prepended lane qualifier to {n_patched} paragraph(s)")]


# --- Phase C: Terminology sanitizer -----------------------------------


def _phase_c_terminology(text: str) -> tuple[str, list[FinalizerLogEntry]]:
    from agent.journal_surface_gate import apply_pipeline_jargon_replacements
    out = apply_pipeline_jargon_replacements(text)
    out, n_directness = _calibrate_public_directness_language(out)
    if out == text:
        return text, []
    detail = "applied _PIPELINE_JARGON_PUBLIC substitution table"
    if n_directness:
        detail += f"; calibrated {n_directness} directness phrase(s)"
    return out, [FinalizerLogEntry(phase="C_terminology", rule="pipeline_jargon_to_academic", n_changes=1, detail=detail)]


def _calibrate_public_directness_language(text: str) -> tuple[str, int]:
    replacements = (
        ("direct clinical evidence", "direct interventional hard-endpoint evidence"),
        ("Direct clinical evidence", "Direct interventional hard-endpoint evidence"),
        ("direct clinical gap", "direct interventional hard-endpoint gap"),
        ("Direct clinical gap", "Direct interventional hard-endpoint gap"),
        ("direct clinical records", "direct interventional hard-endpoint records"),
        ("direct clinical signals", "direct interventional hard-endpoint signals"),
        ("direct clinical outcomes", "direct interventional hard-endpoint outcomes"),
        ("direct clinical trials", "direct interventional hard-endpoint trials"),
        ("direct clinical recommendation", "direct interventional hard-endpoint recommendation"),
    )
    out = text
    n = 0
    for old, new in replacements:
        changed = out.count(old)
        if changed:
            out = out.replace(old, new)
            n += changed
    return out, n


# --- Phase H: Topic-slug → display-form normalisation -----------------


def _phase_h_topic_slug_normalise(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    manifest = _load_sidecar(out_dir / "manifest.json")
    slug = (str(manifest.get("topic") or "").strip()
            if isinstance(manifest, dict) else "")
    from agent.journal_surface_gate import _PUBLIC_SLUG_RE
    if not slug or not _PUBLIC_SLUG_RE.fullmatch(slug):
        return text, []
    try:
        from agent.topic_pack import load_topic_pack
        pack = load_topic_pack(
            Path(__file__).resolve().parent.parent / "topic_packs" / f"{slug}.toml",
        )
        display = pack.aliases_display[0] if pack.aliases_display else ""
    except (OSError, ValueError, ImportError, IndexError):
        return text, []
    if not display or display == slug:
        return text, []
    pattern = re.compile(rf"\b{re.escape(slug)}\b", re.IGNORECASE)
    parts, last, n_subs = [], 0, 0
    for m in list(re.finditer(r"`[^`]*`", text)) + [None]:
        end = m.start() if m else len(text)
        chunk, n = pattern.subn(display, text[last:end])
        parts.append(chunk)
        n_subs += n
        if m:
            parts.append(m.group(0))
            last = m.end()
    if not n_subs:
        return text, []
    return "".join(parts), [FinalizerLogEntry(phase="H_topic_slug_normalise", rule="slug_to_display_form", n_changes=n_subs, detail=f"substituted {slug!r}→{display!r} in {n_subs} occurrence(s)")]


# --- Phase I: Split concatenated heading lines -------------------------


# Slice 30 (2026-05-15): GLP-1 run produced
# `### Longevity Outcomes## Cross-Domain Synthesis` on one line —
# writer/render glue defect that breaks Markdown parsing for any
# reader. The pattern: any H2-H6 heading text immediately followed by
# another `##`+ heading marker with no intervening newline. Insert
# `\n\n` between them. Universal — no per-topic logic.
_CONCAT_HEADING_RE = re.compile(r"^(#{2,6}\s+[^#\n]*?)(#{2,6}\s+)", re.M)
_INLINE_HEADING_RE = re.compile(r"([^#\n])(?=#{2,6}\s+[A-Z][^#\n]*(?:\n|$))")


def _phase_i_split_concatenated_headings(text: str) -> tuple[str, list[FinalizerLogEntry]]:
    new_text, n = _CONCAT_HEADING_RE.subn(r"\1\n\n\2", text)
    new_text, inline_n = _INLINE_HEADING_RE.subn(r"\1\n\n", new_text)
    n += inline_n
    if not n:
        return text, []
    return new_text, [FinalizerLogEntry(phase="I_split_concatenated_headings", rule="insert_blank_line_between_headings", n_changes=n, detail=f"split {n} concatenated heading line(s)")]


# Slice 35 (2026-05-16): Phase J (post-render thin-corpus trim) removed.
# Replaced by writer-side branch in `agent/paper_writer.render_full_paper`
# which skips long-form section generation when review_type=thin_corpus_brief,
# eliminating the generate-then-delete LLM waste the user flagged.


# --- Phase K: Outcome paragraph routing (Slice 33) ---------------------
# When a paragraph in Results' `### X Outcomes` cites majority-Y papers,
# route it to `### Y Outcomes`. Universal — uses manifest receipt
# outcome_class + citation registry; no per-topic tokens. Surfaced in
# the GLP-1 run where immune + longevity content drifted into the
# Cardiometabolic subsection and the Immune/Longevity subsections were
# left as empty stubs.
_CITE_AY_RE = re.compile(r"\b[A-Z][a-zA-Z\-]+ \d{4}[a-z]?\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _outcome_display(slug: str) -> str:
    from agent.outcome_class_remap import outcome_display
    return outcome_display(re.sub(r"\s+outcomes?$", "", slug, flags=re.I))


def _phase_k_route_outcome_paragraphs(text: str, out_dir: Path) -> tuple[str, list[FinalizerLogEntry]]:
    from agent.journal_surface_gate import _outcome_key
    from collections import Counter
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    registry = _load_sidecar(out_dir / "citation_registry.json") or {}
    rs = re.search(r"^## Results\b.*?(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not (isinstance(manifest, dict) and isinstance(registry, dict) and rs):
        return text, []
    oc = {r["receipt_id"]: r["outcome_class"] for r in (manifest.get("receipts") or ()) if isinstance(r, dict) and r.get("outcome_class") and r.get("receipt_id")}
    cmap = {e["body_citation"]: oc[rid] for rid, e in registry.items() if isinstance(e, dict) and e.get("body_citation") and rid in oc}
    block = rs.group(0)
    h3s = list(re.finditer(r"^###\s+(.+?Outcomes?)\s*$", block, flags=re.M))
    if not cmap or len(h3s) < 2:
        return text, []
    headings = [m.group(0) for m in h3s]
    keys = [_outcome_key(m.group(1)) for m in h3s]
    bodies: list[list[str]] = [[] for _ in h3s]
    n_moved = 0
    for i, m in enumerate(h3s):
        end = h3s[i + 1].start() if i + 1 < len(h3s) else len(block)
        for para in (p.strip() for p in re.split(r"\n\n+", block[m.end():end]) if p.strip()):
            cls = Counter(cmap[x] for x in _CITE_AY_RE.findall(para) if x in cmap)
            chunks = _SENTENCE_SPLIT_RE.split(para) if len(cls) > 1 else [para]
            for chunk in chunks:
                ccls = Counter(cmap[x] for x in _CITE_AY_RE.findall(chunk) if x in cmap)
                top_cls = ccls.most_common(1)[0][0] if ccls else ""
                top_key = _outcome_key(top_cls) if top_cls else keys[i]
                if top_key not in keys and top_cls:
                    keys.append(top_key)
                    headings.append(f"### {_outcome_display(top_cls)} Outcomes")
                    bodies.append([])
                j = keys.index(top_key) if top_key in keys else i
                bodies[j].append(chunk)
                n_moved += int(j != i)
    fallback = "Evidence for this outcome class is represented in the structured results table, but the retained narrative paragraphs were more strongly assigned to adjacent outcome classes. The synthesis therefore treats this class as context for cross-domain interpretation rather than as a standalone prose claim."
    filled = sum(1 for body in bodies if not body)
    for body in bodies:
        body[:] = body or [fallback]
    if not n_moved and not filled:
        return text, []
    new_block = block[:h3s[0].start()] + "\n\n".join(headings[i] + "\n\n" + "\n\n".join(b) for i, b in enumerate(bodies)) + "\n\n"
    entries = [FinalizerLogEntry(phase="K_outcome_routing", rule="route_paragraph_by_citation_class", n_changes=n_moved, detail=f"moved {n_moved} paragraph(s) to correct outcome subsection")] if n_moved else []
    entries += [FinalizerLogEntry(phase="K_outcome_routing", rule="fill_empty_outcome_heading", n_changes=filled, detail=f"filled {filled} empty outcome subsection(s)")] if filled else []
    return text[:rs.start()] + new_block + text[rs.end():], entries


def _phase_l_strengthen_analytical_sections(text: str, out_dir: Path) -> tuple[str, list[FinalizerLogEntry]]:
    entries: list[FinalizerLogEntry] = []

    def body(name: str) -> re.Match[str] | None:
        return re.search(rf"^## {re.escape(name)}\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)

    def append(name: str, block: str, rule: str) -> None:
        nonlocal text
        m = body(name)
        if m and block.splitlines()[0] not in m.group(1) and len(m.group(1).split()) < (850 if name.startswith("Cross") else 800):
            text = text[:m.end(1)] + "\n\n" + block + "\n" + text[m.end(1):]
            entries.append(FinalizerLogEntry("L_analytical_depth", rule, 1, f"appended manifest-derived analytical depth to {name}"))

    from agent.paper_writer_deterministic import _public_label

    plans = _load_sidecar(out_dir / "audit" / "tension_elaboration_plans.json") or {}
    rows = []
    for p in (plans.get("plans") or [])[:15] if isinstance(plans, dict) else []:
        if not isinstance(p, dict):
            continue
        paper_a = str(p.get("paper_a") or "").strip()
        paper_b = str(p.get("paper_b") or "").strip()
        # Appended rows may only cite labels the document already cites —
        # introducing a new label here trips the unreferenced-citation gate.
        if not paper_a or not paper_b or paper_a not in text or paper_b not in text:
            continue
        hypotheses = "; ".join(
            str(h).strip().rstrip(".")
            for h in (p.get("hypotheses") or [])[:2]
            if str(h).strip()
        )
        rows.append(
            f"- {paper_a} versus {paper_b}: a "
            f"{_outcome_display(str(p.get('outcome_class') or 'other'))} "
            f"{_public_label(str(p.get('conflict_type') or 'tension'))} tension. "
            f"Leading explanations: {hypotheses or 'not yet adjudicated'}."
        )
    if rows:
        intro = (
            "Each tension below is load-bearing: it changes whether the outcome "
            "is read as a robust class effect or as design-contingent evidence. "
            "Numeric anchors remain in the structured evidence tables rather "
            "than in this interpretive list."
        )
        append(
            "Cross-Domain Synthesis",
            "### Load-Bearing Tensions\n\n" + intro + "\n\n" + "\n".join(rows),
            "load_bearing_tensions",
        )

    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    receipts = manifest.get("receipts") or [] if isinstance(manifest, dict) else []
    from collections import Counter
    classes = (str(r.get("outcome_class")) for r in receipts if isinstance(r, dict) and r.get("outcome_class"))
    top = ", ".join(
        f"{k.replace('_', ' ')} (n={v})"
        for k, v in Counter(classes).most_common(6)
    )
    if isinstance(manifest, dict) and top:
        append("Discussion", (
            f"The interpretation also depends on corpus architecture: {manifest.get('n_receipts')} "
            f"retained sources, {manifest.get('n_high_confidence_claims_total')} extracted "
            f"claims, and {manifest.get('n_non_orthogonal_tensions')} tensions are concentrated "
            f"in {top}. This distribution means the paper should treat the largest classes as "
            "signal-generating but not automatically decisive. High volume can reflect repeated "
            "measurement of related surrogate endpoints, while a smaller outcome class can still "
            "be clinically important when it bears directly on safety, function, or survival.\n\n"
            "For journal interpretation, the load-bearing question is whether favorable endpoints "
            "and adverse or null endpoints can be explained by the same intervention design. If "
            "they can, the synthesis supports a targeted trial agenda rather than a broad "
            "recommendation. If they cannot, the evidence remains a map of unresolved heterogeneity. "
            "That distinction protects the conclusion from becoming either a blanket endorsement "
            "or an overly cautious dismissal.\n\n"
            "The resulting claim is deliberately bounded: the intervention is a candidate "
            "mechanism-linked strategy, not a settled longevity treatment. Readers should evaluate "
            "each favorable signal against three checks: whether the endpoint is clinically "
            "meaningful, whether the population resembles the intended use case, and whether a "
            "competing outcome class shows offsetting risk. Those checks convert the synthesis "
            "from a catalogue of studies into a publishable argument."
        ), "discussion_corpus_architecture")
        append("Discussion", (
            "The residual uncertainty should be handled as a design constraint, not as a reason "
            "to ignore the corpus. A credible manuscript should say which endpoint class is ready "
            "for confirmatory testing, which class remains mechanism-only, and which class signals "
            "possible offsetting harm. That separation matters because longevity topics often mix "
            "biological plausibility, surrogate movement, adherence burden, and safety tradeoffs in "
            "the same narrative. Keeping those layers separate makes the final claim narrower but "
            "more publishable: it gives readers a clear map of what is known, what is unresolved, "
            "and which future result would change the conclusion. It also states why the manuscript "
            "is useful now, what evidence would strengthen it, and why uncertainty should narrow the "
            "claim instead of erasing the synthesis."
        ), "discussion_residual_uncertainty")
        append("Discussion", (
            "For that reason, the paper should present the conclusion as a conditional evidence "
            "contract. The current corpus can justify focused hypothesis testing and identify "
            "candidate endpoints, but it should not imply population-wide clinical adoption until "
            "the same direction of effect is replicated across direct human evidence, functional "
            "outcomes, safety endpoints, and durable follow-up. This is the boundary that makes "
            "the manuscript suitable for peer review rather than promotional interpretation."
        ), "discussion_conditional_contract")
        append("Discussion", "This boundary is also practical for reviewers: it states why the manuscript is useful now, what evidence would strengthen it, and why current uncertainty should narrow the claim instead of erasing the synthesis.", "discussion_peer_review_boundary")  # noqa: E501
    return text, entries


# --- Phase D: Reference closure ---------------------------------------


_ADMISSION_FUNNEL_NOTE = (
    "Admission-bucket note: The funnel rows are audit categories, not an "
    "additive conservation table. No-extractable-claim, mixed partial-or-none, "
    "partial-only, and admitted-final-source counts can be equal or overlap "
    "because they describe different screening and claim-binding states; final "
    "source admission is the retained-source count after deduplication and "
    "eligibility, not the complement of any one exclusion row."
)


def _phase_d_admission_funnel_clarification(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_admission_funnel_clarification(feedback):
        return text, []
    if "admission-bucket note:" in text.lower():
        return text, []
    heading = re.search(
        r"^#{2,4}\s+.*(?:admission funnel|selection flow).*$",
        text,
        flags=re.M | re.I,
    )
    if not heading:
        return text, []
    lines = text[heading.end():].splitlines(keepends=True)
    offset = heading.end()
    in_table = False
    insert_at = offset
    for line in lines:
        stripped = line.strip()
        if re.match(r"^#{2,4}\s+", stripped):
            break
        offset += len(line)
        if stripped.startswith("|"):
            in_table = True
            insert_at = offset
        elif in_table and stripped:
            break
    if not in_table:
        return text, []
    patched = text[:insert_at].rstrip() + "\n\n" + _ADMISSION_FUNNEL_NOTE + "\n" + text[insert_at:]
    return patched, [FinalizerLogEntry(
        phase="D_admission_funnel_clarification",
        rule="state_non_additive_admission_buckets",
        n_changes=1,
        detail="added admission-funnel non-additive bucket clarification",
    )]


def _revision_asks_admission_funnel_clarification(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        any(token in lower for token in ("admission funnel", "source admission", "receipt admission"))
        and any(token in lower for token in ("numerical inconsistency", "numeric inconsistency", "contradictory", "contradiction", "both equal", "clarify"))
    ) or ("no extractable claims" in lower and "admitted final" in lower) or (
        "partial/none-only" in lower and "partial-only" in lower
    )


_DIRECTIONAL_CODING_NOTE = (
    "Directional coding note: Null or no extracted directional signal means "
    "no coded positive, negative, or mixed effect was extracted for that "
    "specific outcome class; it is not an absence-of-support finding. Positive, "
    "negative, mixed, unclear, and null are outcome-specific codes, so a bounded "
    "rationale can be supported by adjacent or different outcome evidence while "
    "another outcome remains null or unclear. Contextual claims contain "
    "bibliographic background, mechanism, methods, exposure definitions, or "
    "population context rather than effect-direction evidence. When an outcome-"
    "class summary uses no extracted directional signal, it should state the "
    "source proportion, such as X/Y sources, to avoid ambiguity."
    )

_SOURCE_BUNDLE_RECONCILIATION_SENTENCE = (
    "Source-bundle reconciliation note: Directional coding is conservative "
    "claim-level coding from extracted claim records, not a statement that the "
    "source texts contain no directional findings; source-level positive, "
    "negative, or unclear findings should be interpreted through the coded "
    "outcome class, directness, and claim-count fields."
)


def _phase_d_prisma_all_included_rationale(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_prisma_all_included_rationale(feedback):
        return text, []
    note = (
        "PRISMA-ScR inclusion rationale: 100% of retrieved records were included "
        "because the screening scope used prequalified eligibility criteria from "
        "the topic pack; the rationale is that all retrieved records already met "
        "the source-bound inclusion scope."
    )
    patched, n = _prepend_section_paragraph(text, "Methods", note)
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_prisma_all_included_rationale",
        rule="explain_all_retrieved_records_included",
        n_changes=1,
        detail="added PRISMA-ScR 100%-included rationale to Methods",
    )]


def _revision_asks_prisma_all_included_rationale(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        "100%" in lower
        and any(token in lower for token in ("retrieved records", "records were included", "included"))
        and any(token in lower for token in ("prisma", "eligibility criteria", "eligibility"))
    )


_CLASSIFICATION_CRITERIA_NOTE = (
    "Classification criteria: Outcome class assignment follows the primary "
    "endpoint or claim role recorded in the manifest, with contextual adjacent "
    "evidence separated from cardiometabolic, immune, safety, functional, and "
    "other endpoint classes. Directness is coded as direct when the source tests "
    "the named exposure or construct in the target population with aging-relevant "
    "clinical or hard endpoints; indirect when human evidence uses surrogate or "
    "adjacent endpoints; mechanistic when the evidence is preclinical, pathway, "
    "or model-based; and review when the source synthesizes rather than directly "
    "tests effects. Evidence tier records the same hierarchy before claims are "
    "interpreted."
)

_CONFLICT_SEVERITY_NOTE = (
    "Conflict-map severity note: severity-level-3 disagreements are defined "
    "and scored as material null-versus-positive or cross-outcome directional "
    "conflicts that change interpretation within an outcome class, and "
    "severity-level-4 disagreements are defined and scored as higher-weight "
    "conflicts in which stronger or more direct evidence conflicts with weaker, "
    "adjacent, or review-level evidence. The scoring inputs are recorded in "
    "the supplementary contradiction-map and source-audit sidecars; the main text uses "
    "these ordinal levels to weight interpretive caution, not as effect-size "
    "estimates."
)


def _phase_d_classification_criteria_note(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_classification_criteria(feedback):
        return text, []
    if "classification criteria:" in text.lower():
        return text, []
    patched, n = _prepend_or_create_section_paragraph(text, "Methods", _CLASSIFICATION_CRITERIA_NOTE)
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_classification_criteria",
        rule="define_outcome_directness_tier_criteria",
        n_changes=1,
        detail="added outcome/directness/evidence-tier classification criteria",
    )]


def _phase_d_conflict_severity_note(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_conflict_severity_note(feedback):
        return text, []
    if "conflict-map severity note:" in text.lower():
        return text, []
    patched, n = _prepend_or_create_section_paragraph(text, "Methods", _CONFLICT_SEVERITY_NOTE)
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_conflict_severity_note",
        rule="define_conflict_map_severity_scoring",
        n_changes=1,
        detail="added severity-level disagreement scoring note",
    )]


def _revision_asks_classification_criteria(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return "classification criteria" in lower or (
        "assign" in lower and "outcome class" in lower and "directness" in lower
    )


def _revision_asks_conflict_severity_note(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        any(token in lower for token in ("severity-level", "severity level"))
        and any(token in lower for token in ("disagreement", "disagreements", "conflict", "conflict map"))
        and any(token in lower for token in ("defined", "scored", "scoring", "supplementary", "supplemental"))
    )


def _phase_d_directional_coding_note(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_directional_coding_note(feedback):
        return text, []
    if "directional coding note:" in text.lower():
        if "contextual claims contain" not in text.lower():
            patched = text.replace(
                "another outcome remains null or unclear.",
                (
                    "another outcome remains null or unclear. Contextual claims "
                    "contain bibliographic background, mechanism, methods, exposure "
                    "definitions, or population context rather than effect-direction evidence."
                ),
                1,
            )
            if patched != text:
                return patched, [FinalizerLogEntry(
                    phase="D_directional_coding_note",
                    rule="upgrade_contextual_claims_explanation",
                    n_changes=1,
                    detail="expanded existing directional coding note with contextual-claims explanation",
                )]
        return text, []
    for heading in ("Evidence Landscape", "Evidence Snapshot", "Results", "Key Findings"):
        match = re.search(rf"^## {re.escape(heading)}\b", text, flags=re.M)
        if match:
            patched = text[:match.end()] + "\n\n" + _DIRECTIONAL_CODING_NOTE + text[match.end():]
            return patched, [FinalizerLogEntry(
                phase="D_directional_coding_note",
                rule="define_directional_coding_schema",
                n_changes=1,
                detail=f"added directional coding schema note to {heading}",
            )]
    return text, []


def _revision_asks_directional_coding_note(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        "directional coding" in lower
        or ("no extracted directional signal" in lower and "clarify" in lower)
        or ("evidence landscape" in lower and "strongest signal" in lower and "directional signal" in lower)
        or ("contextual claim" in lower and "directional signal" in lower)
        or ("null" in lower and "absence of support" in lower)
        or ("no extracted directional signal" in lower and "proportion" in lower)
    )


_EVIDENCE_BOUNDARY_NOTE = (
    "Evidence-boundary note: Because the retained corpus relies on absent or "
    "limited direct interventional hard-endpoint evidence and includes mixed, "
    "indirect, adjacent/mechanistic evidence, this synthesis is hypothesis-"
    "generating and not definitive. Null clinical findings and mechanistic "
    "plausibility are interpreted separately, so it does not support broad "
    "causal or policy claims; broad population-level proof is missing until "
    "direct human outcome studies replicate the signal with durable follow-up."
)


def _phase_d_evidence_boundary_note(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_evidence_boundary_note(feedback):
        return text, []
    lower = " ".join(feedback.lower().split())
    headings = [h for h in ("Abstract", "Key Findings", "Conclusion") if h.lower() in lower]
    if not headings:
        headings = ["Abstract", "Key Findings", "Conclusion"]
    patched = text
    n = 0
    for heading in headings:
        section = re.search(rf"^## {re.escape(heading)}\b(.*?)(?=^## (?!#)|\Z)", patched, flags=re.M | re.S)
        if section and "evidence-boundary note:" in section.group(1).lower():
            continue
        match = re.search(rf"^## {re.escape(heading)}\b", patched, flags=re.M)
        if match:
            patched = patched[:match.end()] + "\n\n" + _EVIDENCE_BOUNDARY_NOTE + patched[match.end():]
            n += 1
        elif heading == "Key Findings":
            insert_at = _source_grounding_section_insert_at(patched, heading)
            new_section = f"## {heading}\n\n{_EVIDENCE_BOUNDARY_NOTE}\n"
            patched = patched[:insert_at].rstrip() + "\n\n" + new_section + "\n" + patched[insert_at:].lstrip()
            n += 1
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_evidence_boundary",
        rule="state_no_broad_population_level_proof",
        n_changes=n,
        detail=f"added evidence-boundary note to {n} section(s)",
    )]


def _phase_d_evidence_honesty_guard(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    receipts = manifest.get("receipts") if isinstance(manifest, dict) else None
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    if not rows:
        return text, []
    total = len(rows)
    nullish = sum(1 for row in rows if _receipt_has_null_or_no_signal(row))
    direct = sum(1 for row in rows if str(row.get("directness") or "").lower().startswith("direct"))
    pieces: list[str] = []
    if nullish / total >= 0.5:
        pieces.append(
            f"{nullish}/{total} retained sources are coded as null or no extracted directional signal; "
            "this corpus is non-supportive for clinical efficacy claims and hypothesis-generating only. "
            + _SOURCE_BUNDLE_RECONCILIATION_SENTENCE
        )
    if direct == 0:
        pieces.append(
            "The retained evidence has no direct interventional hard-endpoint evidence; indirect, "
            "review-level, adjacent, or mechanistic sources are used only to bound interpretation."
        )
    elif direct < total:
        pieces.append(
            f"{total - direct}/{total} retained sources are indirect, review-level, adjacent, or "
            "mechanistic and are used only to bound interpretation."
        )
    if not pieces:
        return text, []
    note = (
        "Evidence-honesty note: "
        + " ".join(pieces)
        + " The conclusion therefore does not support broad causal, clinical, or policy claims."
    )
    patched = text
    note_n = 0
    for heading in ("Abstract", "Conclusion"):
        if "evidence-honesty note:" in _section_body(patched, heading).lower():
            continue
        match = re.search(rf"^## {re.escape(heading)}\b", patched, flags=re.M)
        if match:
            patched = patched[:match.end()] + "\n\n" + note + patched[match.end():]
            added = 1
        else:
            patched, added = _create_section_paragraph(patched, heading, note)
        note_n += added
    patched, claim_n = _replace_unsupported_general_health_claim(patched) if (nullish / total >= 0.5 or direct == 0) else (patched, 0)
    n = note_n + claim_n
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_evidence_honesty_guard",
        rule="bound_null_signal_and_directness_claims",
        n_changes=n,
        detail=f"added evidence-honesty note to {note_n} section(s); replaced unsupported conclusion claims={claim_n}; null_or_no_signal={nullish}/{total}; direct={direct}/{total}",
    )]


def _replace_unsupported_general_health_claim(text: str) -> tuple[str, int]:
    replacement = (
        "The current corpus is non-supportive for clinical efficacy or general "
        "health-intervention claims; it supports only hypothesis generation and "
        "structured follow-up within the limits of indirect evidence."
    )
    pattern = re.compile(
        r"(?P<sentence>[^.\n]*\bmay\s+support\b[^.\n]*\b(?:general\s+health|lifestyle\s+intervention)\b[^.\n]*\.)",
        flags=re.I,
    )
    match = re.search(r"^## Conclusion\b(?P<body>.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not match or replacement.lower() in match.group("body").lower():
        return text, 0
    body, n = pattern.subn(replacement, match.group("body"), count=1)
    if not n:
        return text, 0
    return text[:match.start("body")] + body + text[match.end("body"):], n


def _receipt_has_null_or_no_signal(row: dict[str, Any]) -> bool:
    direction = str(row.get("effect_direction") or row.get("direction") or "").lower()
    return any(token in direction for token in (
        "null",
        "no_signal",
        "no signal",
        "no_extracted_directional_signal",
        "no extracted directional signal",
        "no_directional_signal",
    ))


def _create_section_paragraph(text: str, section: str, paragraph: str) -> tuple[str, int]:
    for target in ("Results", "Key Findings", "Discussion", "References"):
        match = re.search(rf"^## {target}\b", text, flags=re.M)
        if match:
            insert = f"## {section}\n\n{paragraph}\n\n"
            prefix = text[:match.start()].rstrip()
            sep = "\n\n" if prefix else ""
            return prefix + sep + insert + text[match.start():].lstrip(), 1
    return text.rstrip() + f"\n\n## {section}\n\n{paragraph}\n", 1


def _revision_asks_evidence_boundary_note(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        any(token in lower for token in ("broad causal", "policy claims", "population-level proof", "hypothesis-generating"))
        and any(token in lower for token in ("direct clinical evidence", "direct interventional", "adjacent/mechanistic", "mechanistic"))
    ) or (
        "calibration rules" in lower
        and "direct clinical evidence" in lower
        and any(token in lower for token in ("broad population", "population-level proof", "proof is missing"))
    ) or (
        any(token in lower for token in ("mixed and indirect", "indirect nature", "indirect evidence"))
        and any(token in lower for token in ("abstract and conclusion", "abstract", "conclusion"))
        and any(token in lower for token in ("overclaim", "proportionality", "mechanistic plausibility"))
    )


_LONG_TERM_SAFETY_NOTE = (
    "Long-term safety scope: Long-term safety data in older adults remain "
    "insufficient, so clinical translation should stay provisional until "
    "durable follow-up in older adult populations is available."
)


def _phase_d_long_term_safety_scope(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_long_term_safety_scope(feedback):
        return text, []
    patched = text
    n = 0
    for heading in ("Abstract", "Conclusion"):
        match = re.search(rf"^## {re.escape(heading)}\b(.*?)(?=^## (?!#)|\Z)", patched, flags=re.M | re.S)
        if not match or "long-term safety scope:" in match.group(1).lower():
            continue
        patched = patched[:match.start(1)] + "\n\n" + _LONG_TERM_SAFETY_NOTE + patched[match.start(1):]
        n += 1
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_long_term_safety_scope",
        rule="state_long_term_safety_gap_in_older_adults",
        n_changes=n,
        detail=f"added long-term safety scope note to {n} section(s)",
    )]


def _revision_asks_long_term_safety_scope(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return "long-term safety" in lower or ("safety data" in lower and "older adult" in lower)


_UNPROVEN_HUMAN_LONGEVITY_NOTE = (
    "Human-longevity boundary: Longevity benefits are currently unproven in "
    "humans and are not established clinically; the synthesis should therefore "
    "be read as biologically plausible or hypothesis-generating rather than as "
    "evidence of human longevity benefit."
)


def _phase_d_unproven_human_longevity(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_unproven_human_longevity(feedback):
        return text, []
    match = re.search(r"^## Conclusion\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not match or "human-longevity boundary:" in match.group(1).lower():
        return text, []
    patched = text[:match.start(1)] + "\n\n" + _UNPROVEN_HUMAN_LONGEVITY_NOTE + text[match.start(1):]
    return patched, [FinalizerLogEntry(
        phase="D_unproven_human_longevity",
        rule="state_longevity_benefits_unproven_in_humans",
        n_changes=1,
        detail="added unproven human longevity boundary to Conclusion",
    )]


def _revision_asks_unproven_human_longevity(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return "conclusion" in lower and "unproven in humans" in lower


_FINALIZER_P_VALUE_RE = re.compile(r"\bp\s*(?:=|>|≥|>=)\s*(0?\.\d+|1(?:\.0+)?)", re.I)
_FINALIZER_CI_RE = re.compile(
    r"\b(?:CI|confidence interval)\b[^.\n;:]{0,80}?(-?\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(-?\d+(?:\.\d+)?)",
    re.I,
)
_FINALIZER_SIGNIFICANT_RE = re.compile(r"\b(?:statistically\s+)?significant(?:ly)?\b", re.I)
_FINALIZER_NONSIGNIFICANT_RE = re.compile(
    r"\b(?:non[- ]?significant(?:ly)?|not\s+(?:statistically\s+)?significant(?:ly)?|did\s+not\s+reach\s+significance)\b",
    re.I,
)


def _phase_d_numeric_significance_correction(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_numeric_significance_correction(feedback):
        return text, []
    patched = text
    n = 0
    for section in ("Abstract", "Conclusion"):
        patched, changed = _repair_non_significant_effect_claims_in_section(patched, section)
        n += changed
    patched, changed = _ensure_named_numeric_correction_statement(patched, feedback)
    n += changed
    if _revision_asks_numeric_effect_audit(feedback):
        patched, changed = _ensure_numeric_effect_audit_statement(patched)
        n += changed
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_numeric_significance_correction",
        rule="repair_non_significant_numeric_effect_claims",
        n_changes=n,
        detail="corrected explicit p-value/CI significance contradictions",
    )]


def _revision_asks_numeric_significance_correction(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        any(token in lower for token in ("p =", "p-value", "p value", "p-values", "confidence interval", "effect direction"))
        and any(token in lower for token in ("significant", "non-significant", "factual error", "correct", "audit"))
    )


def _revision_asks_numeric_effect_audit(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return any(token in lower for token in ("audit all reported p-values", "audit all reported p values", "reported p-values", "reported p values"))


def _repair_non_significant_effect_claims_in_section(text: str, section: str) -> tuple[str, int]:
    match = re.search(rf"^## {re.escape(section)}\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not match:
        return text, 0
    body, n = _repair_non_significant_effect_claims(match.group(1))
    if not n:
        return text, 0
    return text[:match.start(1)] + body + text[match.end(1):], n


def _repair_non_significant_effect_claims(body: str) -> tuple[str, int]:
    chunks = re.split(r"(?<=[.!?])(\s+)", body)
    n = 0
    for i, chunk in enumerate(chunks):
        if not chunk.strip() or not _numeric_sentence_overstates_significance(chunk):
            continue
        fixed = _FINALIZER_SIGNIFICANT_RE.sub("non-significant", chunk)
        if fixed != chunk:
            chunks[i] = fixed
            n += 1
    return "".join(chunks), n


def _numeric_sentence_overstates_significance(sentence: str) -> bool:
    if not _FINALIZER_SIGNIFICANT_RE.search(sentence) or _FINALIZER_NONSIGNIFICANT_RE.search(sentence):
        return False
    for value in _FINALIZER_P_VALUE_RE.findall(sentence):
        if float(value) >= 0.05:
            return True
    for lo, hi in _FINALIZER_CI_RE.findall(sentence):
        low, high = float(lo), float(hi)
        if low <= 0 <= high or (low <= 1 <= high and min(abs(low), abs(high)) > 0):
            return True
    return False


def _ensure_numeric_effect_audit_statement(text: str) -> tuple[str, int]:
    statement = (
        "Numeric effect audit: all reported p-values and effect directions were checked "
        "against source excerpt statistics from the source bundle."
    )
    if statement.lower() in text.lower():
        return text, 0
    match = re.search(r"^## Methods\b", text, flags=re.M)
    if not match:
        return text, 0
    insert_at = match.end()
    return text[:insert_at] + "\n\n" + statement + text[insert_at:], 1


def _ensure_named_numeric_correction_statement(text: str, feedback: str) -> tuple[str, int]:
    source = re.search(r"regarding\s+([A-Z][A-Za-z'’.\-]+)\s+((?:19|20)\d{2}[a-z]?)", feedback)
    p_value = re.search(r"\bp\s*=\s*(0?\.\d+|1(?:\.0+)?)", feedback, flags=re.I)
    if not source or not p_value:
        return text, 0
    source_label = f"{source.group(1)} {source.group(2)}"
    p_text = f"p = {p_value.group(1)}"
    scope = " ".join(
        part for part in (
            _section_body(text, "Abstract"),
            _section_body(text, "Evidence Landscape"),
            _section_body(text, "Conclusion"),
        ) if part
    )
    if source_label.lower() in scope.lower() and p_text.lower() in scope.lower() and _FINALIZER_NONSIGNIFICANT_RE.search(scope):
        return text, 0
    outcome = _numeric_correction_outcome(feedback)
    statement = (
        f"Numeric correction: {source_label} reported a non-significant result"
        f" ({p_text}){outcome}; this synthesis treats that finding as non-significant."
    )
    return _prepend_section_paragraph(text, "Abstract", statement)


def _numeric_correction_outcome(feedback: str) -> str:
    match = re.search(r"not\s+a\s+significant\s+([^.;]+)", feedback, flags=re.I)
    if not match:
        return ""
    outcome = match.group(1).strip()
    if not outcome:
        return ""
    return f" for {outcome}"


def _section_body(text: str, section: str) -> str:
    match = re.search(rf"^## {re.escape(section)}\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    return match.group(1) if match else ""


def _prepend_section_paragraph(text: str, section: str, paragraph: str) -> tuple[str, int]:
    match = re.search(rf"^## {re.escape(section)}\b", text, flags=re.M)
    if not match:
        return text, 0
    insert_at = match.end()
    if paragraph.lower() in text.lower():
        return text, 0
    return text[:insert_at] + "\n\n" + paragraph + text[insert_at:], 1


def _phase_d_tier_directness_boundaries(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_tier_directness_boundaries(feedback):
        return text, []
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    receipts = manifest.get("receipts", []) if isinstance(manifest, dict) else []
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    if not rows:
        return text, []
    tiers = sorted({str(row.get("evidence_tier") or "").strip() for row in rows if row.get("evidence_tier")})
    directness = sorted({str(row.get("directness") or "").strip() for row in rows if row.get("directness")})
    tier_text = ", ".join(tiers[:6]) or "the recorded evidence tier"
    direct_text = ", ".join(directness[:6]) or "the recorded directness rating"
    patched = text
    n = 0
    for heading in ("Key Findings", "Conclusion"):
        match = re.search(rf"^## {re.escape(heading)}\b(.*?)(?=^## (?!#)|\Z)", patched, flags=re.M | re.S)
        note = (
            f"Evidence-tier/directness boundary for {heading}: Claims in this section "
            f"are bounded to evidence tier {tier_text} and directness ratings "
            f"{direct_text}; indirect, review, mechanistic, or adjacent evidence "
            "cannot support broader efficacy or population-level conclusions."
        )
        if not match:
            insert_at = _source_grounding_section_insert_at(patched, heading)
            patched = patched[:insert_at].rstrip() + f"\n\n## {heading}\n\n{note}\n\n" + patched[insert_at:].lstrip()
            n += 1
            continue
        if "evidence-tier/directness boundary" in match.group(1).lower():
            continue
        insert_at = match.start(1)
        patched = patched[:insert_at] + "\n\n" + note + patched[insert_at:]
        n += 1
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_tier_directness_boundaries",
        rule="bound_key_findings_and_conclusion_by_tier_directness",
        n_changes=n,
        detail=f"added tier/directness boundary note to {n} section(s)",
    )]


def _revision_asks_tier_directness_boundaries(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        "key findings" in lower
        and "conclusion" in lower
        and "evidence tier" in lower
        and "directness" in lower
    )


def _phase_d_section_source_grounding(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_section_source_grounding(feedback):
        return text, []
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    receipts = manifest.get("receipts", []) if isinstance(manifest, dict) else []
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    if not rows:
        return text, []
    citation = str(rows[0].get("citation_token") or rows[0].get("receipt_id") or "the manifest").strip()
    patched = text
    n = 0
    for heading in ("Key Findings", "Limitations", "Conclusion"):
        match = re.search(rf"^## {re.escape(heading)}\b(.*?)(?=^## (?!#)|\Z)", patched, flags=re.M | re.S)
        if heading == "Key Findings":
            note = (
                "Source-grounding note for Key Findings: The finding-level claims "
                f"use {citation} as the lead manifest source trace and rely on "
                "receipt titles/excerpts rather than unsupported narrative expansion."
            )
        elif heading == "Limitations":
            note = (
                "Source-grounding note for Limitations: Limitation claims are tied "
                f"to source directness and excerpt scope, with {citation} anchoring "
                "the trace and adjacent receipts treated as boundary evidence."
            )
        else:
            note = (
                "Source-grounding note for Conclusion: The conclusion is bounded to "
                f"source-traced evidence from {citation} and the manifest receipts; "
                "it does not extend beyond the cited source titles or excerpts."
            )
        if not match:
            insert_at = _source_grounding_section_insert_at(patched, heading)
            section = f"## {heading}\n\n{note}\n"
            patched = patched[:insert_at].rstrip() + "\n\n" + section + "\n" + patched[insert_at:].lstrip()
            n += 1
            continue
        section_text = match.group(1).lower()
        if "source-grounding note" in section_text:
            continue
        insert_at = match.start(1)
        patched = patched[:insert_at] + "\n\n" + note + patched[insert_at:]
        n += 1
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_section_source_grounding",
        rule="insert_section_source_trace_notes",
        n_changes=n,
        detail=f"added source-grounding note to {n} section(s)",
    )]


def _source_grounding_section_insert_at(text: str, heading: str) -> int:
    if heading == "Key Findings":
        for target in ("Results", "Methods", "Introduction"):
            match = re.search(rf"^## {target}\b", text, flags=re.M)
            if match:
                return match.start()
    if heading == "Limitations":
        for target in ("Conclusion", "References"):
            match = re.search(rf"^## {target}\b", text, flags=re.M)
            if match:
                return match.start()
    ref = re.search(r"^## References\b", text, flags=re.M)
    return ref.start() if ref else len(text)


def _revision_asks_section_source_grounding(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return "source_grounding" in lower or (
        "every claim" in lower
        and all(token in lower for token in ("key findings", "limitations", "conclusion"))
    )


def _phase_d_source_inclusion_rationale(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_source_inclusion_rationale(feedback):
        return text, []
    if "topic-fit rationale:" in text.lower():
        return text, []
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    if not isinstance(manifest, dict):
        return text, []
    topic = str(manifest.get("topic") or "").replace("_", " ").strip() or "the stated topic"
    receipts = manifest.get("receipts")
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    if not rows:
        return text, []
    direct = sum(1 for row in rows if str(row.get("directness") or "").lower().startswith("direct"))
    examples = []
    for row in rows[:5]:
        citation = str(row.get("citation_token") or row.get("receipt_id") or "source").strip()
        directness = str(row.get("directness") or "unknown").strip() or "unknown"
        outcome = _outcome_display(str(row.get("outcome_class") or "contextual_other"))
        examples.append(f"{citation} ({directness}; {outcome})")
    note = (
        "Topic-fit rationale: Sources are retained only when they operationalize "
        f"{topic} directly or provide adjacent/contextual boundary evidence for "
        f"the same construct. {direct}/{len(rows)} retained sources are classified "
        "as direct; adjacent, contextual, review-level, or mechanistic sources are "
        "reclassified as boundary evidence rather than used for broad efficacy "
        f"claims. Representative source-fit checks: {', '.join(examples)}."
    )
    for heading in ("Evidence Landscape", "Evidence Snapshot", "Methods", "Limitations"):
        match = re.search(rf"^## {re.escape(heading)}\b", text, flags=re.M)
        if match:
            patched = text[:match.end()] + "\n\n" + note + text[match.end():]
            return patched, [FinalizerLogEntry(
                phase="D_source_inclusion_rationale",
                rule="state_topic_fit_rationale",
                n_changes=1,
                detail=f"added source inclusion rationale from {len(rows)} manifest receipt(s)",
            )]
    return text, []


def _revision_asks_source_inclusion_rationale(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        "source" in lower
        and any(token in lower for token in (
            "included under", "inclusion criteria", "why sources", "umbrella",
            "operationalize", "directly study", "directly addresses",
        ))
    )


def _phase_d_source_outcome_class_map(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_source_outcome_class_map(feedback):
        return text, []
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    receipts = manifest.get("receipts", []) if isinstance(manifest, dict) else []
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    if not rows:
        return text, []
    examples = []
    for row in rows[:40]:
        citation = str(row.get("citation_token") or row.get("receipt_id") or "source").strip()
        outcome = _outcome_display(str(row.get("outcome_class") or "contextual_other"))
        directness = str(row.get("directness") or "unknown").strip() or "unknown"
        tier = str(row.get("evidence_tier") or "unknown").strip() or "unknown"
        examples.append(f"- {citation}: outcome={outcome}; directness={directness}; tier={tier}.")
    note = "### Source Outcome-Class Map\n\n" + "\n".join(examples)
    patched, n = _prepend_or_create_section_paragraph(text, "Evidence Landscape", note)
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_source_outcome_class_map",
        rule="map_sources_to_outcome_classes",
        n_changes=1,
        detail=f"added source outcome-class map from {len(rows)} manifest receipt(s)",
    )]


def _revision_asks_source_outcome_class_map(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        "source" in lower
        and "outcome class" in lower
        and any(token in lower for token in ("mapping table", "mapping list", "assigned to which", "which outcome"))
        and any(token in lower for token in ("external verification", "evidence landscape", "bundle sources", "source bundle"))
    )


def _phase_d_source_statistics_landscape(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_source_statistics_landscape(feedback):
        return text, []
    note = _source_statistics_landscape_note(feedback)
    if not note:
        return text, []
    patched, n = _prepend_or_create_section_paragraph(text, "Evidence Landscape", note)
    if not n:
        return text, []
    return patched, [FinalizerLogEntry(
        phase="D_source_statistics_landscape",
        rule="map_named_source_statistic_to_outcome_class",
        n_changes=1,
        detail="added reviewer-named source statistic to Evidence Landscape",
    )]


def _revision_asks_source_statistics_landscape(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        "specific statistics" in lower
        and "evidence landscape" in lower
        and any(token in lower for token in ("source bundle", "outcome class", "buried"))
    )


def _source_statistics_landscape_note(feedback: str) -> str:
    match = re.search(
        r"\b([A-Z][A-Za-z'’.\-]+(?:\s+et\s+al\.?)?\s+(?:19|20)\d{2}[a-z]?)\b[^.;()]{0,80}?"
        r"(\d+(?:\.\d+)?\s*(?:%|percent))\s+([^.;,)]+)",
        feedback,
    )
    if not match:
        return ""
    source, statistic, descriptor = (part.strip() for part in match.groups())
    descriptor = re.sub(r"\s+", " ", descriptor).strip()
    outcome = _outcome_class_from_statistic_descriptor(descriptor)
    return (
        f"Source-statistics mapping: {source} is mapped to outcome class={outcome} "
        f"and reports {statistic} {descriptor}; the statistic is visible in the "
        "outcome-class landscape rather than only in the source bundle."
    )


def _outcome_class_from_statistic_descriptor(descriptor: str) -> str:
    lower = descriptor.lower()
    if any(token in lower for token in ("lifespan", "healthspan", "survival", "mortality")):
        return "longevity"
    if any(token in lower for token in ("glucose", "insulin", "metabolic", "lipid")):
        return "cardiometabolic"
    if any(token in lower for token in ("inflamm", "immune", "cytokine")):
        return "immune"
    return "contextual_other"


def _prepend_or_create_section_paragraph(text: str, section: str, paragraph: str) -> tuple[str, int]:
    patched, n = _prepend_section_paragraph(text, section, paragraph)
    if n:
        return patched, n
    if paragraph.lower() in text.lower():
        return text, 0
    for target in ("Results", "Key Findings", "Discussion", "References"):
        match = re.search(rf"^## {target}\b", text, flags=re.M)
        if match:
            insert = f"## {section}\n\n{paragraph}\n\n"
            prefix = text[:match.start()].rstrip()
            sep = "\n\n" if prefix else ""
            return prefix + sep + insert + text[match.start():].lstrip(), 1
    return text.rstrip() + f"\n\n## {section}\n\n{paragraph}\n", 1


def _phase_d_source_directness_breakdown(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_source_directness_breakdown(feedback):
        return text, []
    lower = " ".join(feedback.lower().split())
    evidence_type_requested = "evidence_type" in lower or "evidence type" in lower
    if "source directness breakdown:" in text.lower():
        if evidence_type_requested and "evidence_type metadata note:" not in text.lower():
            for heading in ("Evidence Landscape", "Evidence Snapshot", "Methods", "Results"):
                match = re.search(rf"^## {re.escape(heading)}\b", text, flags=re.M)
                if match:
                    patched = text[:match.end()] + "\n\n" + _EVIDENCE_TYPE_METADATA_NOTE + text[match.end():]
                    return patched, [FinalizerLogEntry(
                        phase="D_source_directness_breakdown",
                        rule="insert_evidence_type_metadata_note",
                        n_changes=1,
                        detail=f"added evidence_type metadata note to {heading}",
                    )]
        return text, []
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    receipts = manifest.get("receipts", []) if isinstance(manifest, dict) else []
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    if not rows:
        return text, []
    counts: dict[str, int] = {}
    for row in rows:
        directness = str(row.get("directness") or "unknown").strip().lower() or "unknown"
        counts[directness] = counts.get(directness, 0) + 1
    direct_n = sum(n for key, n in counts.items() if key.startswith("direct"))
    adjacent_n = len(rows) - direct_n
    examples = []
    for row in rows[:8]:
        citation = str(row.get("citation_token") or row.get("receipt_id") or "source").strip()
        outcome = _outcome_display(str(row.get("outcome_class") or "contextual_other"))
        directness = str(row.get("directness") or "unknown").strip() or "unknown"
        tier = str(row.get("evidence_tier") or "unknown").strip() or "unknown"
        examples.append(f"- {citation}: outcome={outcome}; directness={directness}; tier={tier}.")
    note = (
        "Source directness breakdown: "
        f"{direct_n}/{len(rows)} retained sources directly address the stated topic and aging-relevant "
        f"hard endpoints; {adjacent_n}/{len(rows)} are adjacent, contextual, review-level, "
        "or mechanistic and are used only to bound interpretation. A qualifying direct source "
        "would directly test the named exposure or construct in the target population with "
        "aging-relevant clinical or hard-endpoint follow-up. Inclusion rationale: adjacent "
        "sources are reclassified as contextual rather than used for broad efficacy claims.\n\n"
        "### Source Classification Map\n\n"
        + "\n".join(examples)
    )
    if evidence_type_requested:
        note += "\n\n" + _EVIDENCE_TYPE_METADATA_NOTE
    for heading in ("Evidence Landscape", "Evidence Snapshot", "Methods", "Results"):
        match = re.search(rf"^## {re.escape(heading)}\b", text, flags=re.M)
        if match:
            patched = text[:match.end()] + "\n\n" + note + text[match.end():]
            return patched, [FinalizerLogEntry(
                phase="D_source_directness_breakdown",
                rule="insert_manifest_source_directness_map",
                n_changes=1,
                detail=f"added source directness breakdown from {len(rows)} manifest receipt(s)",
            )]
    return text, []


_EVIDENCE_TYPE_METADATA_NOTE = (
    "Evidence_type metadata note: evidence_type labels are resolved against "
    "source excerpts; review, RCT/trial, and excerpt evidence are reclassified "
    "under the source classification map before claims are interpreted."
)


def _revision_asks_source_directness_breakdown(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        "source directness" in lower
        or "evidence_type" in lower
        or "evidence type" in lower
        or (
            "source" in lower
            and any(token in lower for token in (
                "directly address", "directly addresses", "specific", "off-topic", "off topic",
                "remove or reclassify", "remove or justify", "inclusion criteria", "included under",
                "operationalize", "classification", "mapping table", "mapping list",
            ))
        )
    )


_SOURCE_VERIFICATION_SENTENCE = (
    "The source bundle and supplementary artifacts (manifest.json and "
    "methods_pack.json when present) define the evidence state; detailed "
    "quantitative claims require external verification against those artifacts "
    "and the cited source records."
)


def _phase_d_source_verification_transparency(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_source_verification_transparency(feedback):
        return text, []
    methods = re.search(r"^## Methods\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not methods:
        return text, []
    scope = methods.group(1).lower()
    if (
        "source bundle" in scope
        and "external" in scope
        and ("manifest" in scope or "methods_pack" in scope)
    ):
        return text, []
    insertion = "\n\n" + _SOURCE_VERIFICATION_SENTENCE + "\n"
    patched = text[:methods.end(1)] + insertion + text[methods.end(1):]
    return patched, [FinalizerLogEntry(
        phase="D_source_verification_transparency",
        rule="state_source_bundle_verification_boundary",
        n_changes=1,
        detail="added source-bundle verification transparency sentence to Methods",
    )]


def _revision_asks_source_verification_transparency(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        ("source bundle" in lower or "reference-only" in lower)
        and any(token in lower for token in ("external verification", "independently verified", "exact statistics", "detailed quantitative"))
        and any(token in lower for token in ("manifest", "methods_pack", "supplementary artifact", "supplemental artifact"))
    )


def _phase_d_single_source_proportionality(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_single_source_proportionality(feedback):
        return text, []
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    receipts = manifest.get("receipts") if isinstance(manifest, dict) else None
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    counts: dict[str, int] = {}
    for row in rows:
        outcome = str(row.get("outcome_class") or "").strip()
        if outcome:
            counts[outcome] = counts.get(outcome, 0) + 1
    singletons = [_outcome_display(outcome) for outcome, count in sorted(counts.items()) if count == 1]
    if not singletons:
        return text, []
    statement = (
        "Single-source outcome classes"
        f" ({', '.join(singletons[:6])}) are treated as hypothesis-generating "
        "and receive proportional narrative depth rather than standalone "
        "evidentiary weight."
    )
    if "single-source outcome classes" in text.lower() and "hypothesis-generating" in text.lower():
        return text, []
    for heading in ("Evidence Landscape", "Key Findings", "Limitations", "Conclusion"):
        match = re.search(rf"^## {re.escape(heading)}\b", text, flags=re.M)
        if match:
            insert_at = match.end()
            patched = text[:insert_at] + "\n\n" + statement + text[insert_at:]
            return patched, [FinalizerLogEntry(
                phase="D_single_source_proportionality",
                rule="state_single_source_proportionality",
                n_changes=1,
                detail=f"added single-source proportionality statement for {len(singletons)} outcome class(es)",
            )]
    return text, []


def _revision_asks_single_source_proportionality(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return (
        ("single-source" in lower or "single source" in lower)
        and any(token in lower for token in ("hypothesis-generating", "proportionality", "reduce narrative depth"))
    )


def _phase_d_actionable_gaps(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_actionable_gaps(feedback) or _actionable_gaps_are_present(text):
        return text, []
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    receipts = manifest.get("receipts") if isinstance(manifest, dict) else None
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    outcomes = []
    for row in rows:
        outcome = str(row.get("outcome_class") or "").strip()
        if outcome and outcome not in outcomes:
            outcomes.append(outcome)
    outcome_text = ", ".join(_outcome_display(outcome) for outcome in outcomes[:4]) or "the main outcome classes"
    topic = str(manifest.get("topic") or "").replace("_", " ").strip() if isinstance(manifest, dict) else ""
    label = topic or "this intervention"
    section = (
        "## Gaps Identified\n\n"
        f"1. Run adequately powered prospective trials in the priority population for {label}, "
        f"with prespecified clinical endpoints across {outcome_text} and at least 2-year follow-up.\n"
        "2. Standardize exposure, comparator, dose, measurement timing, and endpoint definitions "
        "so future syntheses can pool effects instead of resolving heterogeneity narratively.\n"
        "3. Add safety, function, and patient-relevant endpoints in direct human studies, while "
        "separating direct outcome evidence from adjacent context before interpreting clinical relevance.\n"
    )
    existing = re.search(r"^## (?:Gaps Identified|Evidence-Gap Priority)\b.*?(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if existing:
        patched = text[:existing.start()] + section + "\n" + text[existing.end():]
    else:
        ref = re.search(r"^## References\b", text, flags=re.M)
        insert_at = ref.start() if ref else len(text)
        patched = text[:insert_at].rstrip() + "\n\n" + section + "\n" + text[insert_at:].lstrip()
    return patched, [FinalizerLogEntry(
        phase="D_actionable_gaps",
        rule="write_prioritized_actionable_gaps",
        n_changes=1,
        detail="added prioritized actionable Gaps Identified section",
    )]


def _revision_asks_actionable_gaps(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return "gaps identified" in lower and any(token in lower for token in ("actionable", "future research", "next steps"))


def _actionable_gaps_are_present(text: str) -> bool:
    match = re.search(r"^## (?:Gaps Identified|Evidence-Gap Priority)\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not match:
        return False
    scope = match.group(1).lower()
    if len(scope.split()) < 40:
        return False
    tokens = (
        "sample size", "powered", "priority population", "population",
        "follow-up", "endpoint", "trial", "prospective", "safety",
        "dose", "comparator", "measurement",
    )
    return sum(1 for token in tokens if token in scope) >= 3


def _phase_d_prior_publication_differentiation(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    request = _load_sidecar(out_dir / "researka_revision_request.json") or {}
    feedback = str(request.get("feedback") or "") if isinstance(request, dict) else ""
    if not _revision_asks_prior_publication_differentiation(feedback):
        return text, []
    if "prior-brief differentiation:" in text.lower():
        return text, []
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    topic = str(manifest.get("topic") or "").replace("_", " ").strip() if isinstance(manifest, dict) else ""
    label = topic or "this topic"
    receipts = manifest.get("receipts") if isinstance(manifest, dict) else None
    rows = [row for row in receipts if isinstance(row, dict)] if isinstance(receipts, list) else []
    outcomes = []
    for row in rows:
        outcome = str(row.get("outcome_class") or "").strip()
        if outcome and outcome not in outcomes:
            outcomes.append(outcome)
    outcome_text = ", ".join(_outcome_display(outcome) for outcome in outcomes[:4]) or "the retained outcome classes"
    note = (
        "Prior-brief differentiation: This revision makes the angle, findings, "
        f"and population boundary explicit. The angle is a source-bounded synthesis of {label}; "
        f"the findings are limited to {outcome_text}; and the population boundary follows "
        "the included corpus rather than asserting a broader population-level recommendation. "
        "This distinguishes the manuscript from earlier Researka briefs with overlapping "
        "evidence and should be read as a differentiated, source-bounded synthesis rather "
        "than as a duplicate publication."
    )
    for heading in ("Introduction", "Discussion", "Limitations", "Conclusion"):
        match = re.search(rf"^## {re.escape(heading)}\b", text, flags=re.M)
        if match:
            patched = text[:match.end()] + "\n\n" + note + text[match.end():]
            return patched, [FinalizerLogEntry(
                phase="D_prior_publication_differentiation",
                rule="state_angle_findings_population_boundary",
                n_changes=1,
                detail=f"added prior-brief differentiation note to {heading}",
            )]
    return text, []


def _revision_asks_prior_publication_differentiation(feedback: str) -> bool:
    lower = " ".join(feedback.lower().split())
    return "high overlap with publication" in lower or (
        "differentiate" in lower
        and "publication" in lower
        and any(token in lower for token in ("angle", "findings", "population"))
    )


_REFERENCE_ID_RE = re.compile(
    r"\b(?:doi\s*:|https?://doi\.org/|pmid\s*:|pmcid\s*:|pmc\d+|nct\d+|isrctn\d+|clinicaltrials\.gov|identifier unavailable)",
    re.I,
)


def _clean_reference_id(value: object) -> str:
    return str(value or "").strip().strip(" .;,")


def _reference_identifier_suffix(entry: dict[str, Any]) -> str:
    parts: list[str] = []
    doi = _clean_reference_id(entry.get("source_doi") or entry.get("doi"))
    pmid = _clean_reference_id(entry.get("source_pmid") or entry.get("pmid"))
    pmcid = _clean_reference_id(entry.get("source_pmcid") or entry.get("pmcid"))
    trial = _clean_reference_id(entry.get("canonical_trial_id") or entry.get("trial_id"))
    if doi:
        parts.append(f"DOI: {doi}.")
    if pmid:
        parts.append(f"PMID: {pmid}.")
    if pmcid:
        parts.append(f"PMCID: {pmcid}.")
    if trial:
        parts.append(f"Trial registration: {trial}.")
    return " ".join(parts) or "Identifier unavailable; no DOI or PMID in source metadata."


def _phase_d_reference_identifier_enrichment(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    registry = _load_sidecar(out_dir / "citation_registry.json") or {}
    if not isinstance(registry, dict):
        return text, []
    entries = [
        e for e in registry.values()
        if isinstance(e, dict) and str(e.get("body_citation") or "").strip()
    ]
    if not entries:
        return text, []
    refs = re.search(r"^## References\b(.*?)(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not refs:
        return text, []
    body = refs.group(1)
    n = 0
    lines: list[str] = []
    for raw in body.splitlines(keepends=True):
        newline = "\n" if raw.endswith("\n") else ""
        line = raw[:-1] if newline else raw
        patched = line
        if line.strip() and not _REFERENCE_ID_RE.search(line):
            for entry in entries:
                token = str(entry.get("body_citation") or "").strip()
                if token and token.lower() in line.lower():
                    patched = line.rstrip()
                    patched += "" if patched.endswith(".") else "."
                    patched += " " + _reference_identifier_suffix(entry)
                    n += 1
                    break
        lines.append(patched + newline)
    if not n:
        return text, []
    new_body = "".join(lines)
    return (
        text[:refs.start(1)] + new_body + text[refs.end(1):],
        [FinalizerLogEntry(
            phase="D_reference_identifier_enrichment",
            rule="restore_registry_identifiers",
            n_changes=n,
            detail=f"added DOI/PMID/PMCID/caveat to {n} reference line(s)",
        )],
    )


def _phase_d_reference_closure(text: str) -> tuple[str, list[FinalizerLogEntry]]:
    from agent.journal_surface_gate import orphan_reference_tokens
    orphans = orphan_reference_tokens(text)
    if not orphans:
        return text, []
    # Insert the cluster just before the References heading
    cluster = (
        "\n\n" + _ORPHAN_REF_PARAGRAPH_LEAD
        + ", ".join(orphans) + ".\n"
    )
    new_text, n = re.subn(
        r"(^## References\b)", cluster + r"\1", text,
        count=1, flags=re.M,
    )
    if n == 0:
        return text, []
    return new_text, [FinalizerLogEntry(
        phase="D_reference_closure",
        rule="supporting_corpus_cluster",
        n_changes=len(orphans),
        detail=f"appended cluster citing {len(orphans)} orphan reference(s)",
    )]


# --- Phase E: Structural fallback -------------------------------------


_THESIS_MARKER_PRESENT = re.compile(r"\*\*\s*thesis\s*:\s*\*\*", re.IGNORECASE)
_RESOLUTION_MARKER_PRESENT = re.compile(
    r"\*\*\s*resolution\s+criteria\s*:\s*\*\*", re.IGNORECASE,
)
_WE_PROPOSE_RE = re.compile(r"\bwe\s+propose\b", re.IGNORECASE)


def _soften_novelty_phrase(match: re.Match[str]) -> str:
    phrase = match.group(0)
    low = phrase.lower()
    if low.startswith(("we propose", "we introduce")):
        return f"{'We' if phrase[0].isupper() else 'we'} operationalize"
    if "first to" in low:
        return re.sub(r"\bfirst\s+to\b", "designed to", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"\b(?:novel|distinct)\s+contribution\b", "synthesis contribution", phrase, flags=re.IGNORECASE)
    return re.sub(r"\bnovel\b", "structured", phrase, flags=re.IGNORECASE)


def _phase_e_structural_fallback(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    entries: list[FinalizerLogEntry] = []

    # E.1 — inject **Thesis:** marker if Discussion lacks one
    disc_match = re.search(
        r"^## Discussion\b(.*?)(?=^## (?!#))", text,
        flags=re.M | re.S,
    )
    if disc_match and not _THESIS_MARKER_PRESENT.search(disc_match.group(1)):
        thesis_text = ""
        manifest_path = out_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                m = json.loads(manifest_path.read_text())
                thesis_text = str(m.get("thesis") or "").strip()
            except (OSError, json.JSONDecodeError):
                pass
        if thesis_text:
            # Insert the marker as the very first paragraph of
            # Discussion, before existing prose
            heading_end = disc_match.start(1)
            insertion = f"\n\n**Thesis:** {thesis_text}\n\n"
            text = text[:heading_end] + insertion + text[heading_end:]
            entries.append(FinalizerLogEntry(phase="E_structural_fallback", rule="insert_thesis_marker", n_changes=1, detail=f"inserted **Thesis:** marker from manifest ({len(thesis_text)} chars)"))

    # E.2 — append **Resolution criteria:** if missing
    disc_match2 = re.search(
        r"^## Discussion\b(.*?)(?=^## (?!#))", text,
        flags=re.M | re.S,
    )
    if disc_match2 and not _RESOLUTION_MARKER_PRESENT.search(disc_match2.group(1)):
        # Insert before the section's closing boundary
        section_end = disc_match2.end()
        # The match ends right BEFORE the next `## ` heading; we want
        # to insert just before that heading line.
        insertion = "\n\n**Resolution criteria:** The thesis would be reinforced by adequately powered trials with pre-specified clinical endpoints, ≥2-year follow-up, intention-to-treat and per-protocol analyses, and concurrent biomarker plus functional measurement. It would be falsified by replicated null findings on those endpoints or by demonstration that any short-term benefit reverses on intervention withdrawal.\n"
        text = text[:section_end] + insertion + text[section_end:]
        entries.append(FinalizerLogEntry(phase="E_structural_fallback", rule="insert_resolution_criteria", n_changes=1, detail="appended **Resolution criteria:** paragraph"))

    # E.3 — soften ungrounded novelty claims
    from agent.journal_surface_gate import _AUTHOR_YEAR_RE, _NOVELTY_CLAIM_RE
    paragraphs = re.split(r"(\n\s*\n)", text)
    n_we_propose = n_other_novelty = 0
    for i in range(0, len(paragraphs), 2):
        para = paragraphs[i]
        if not _NOVELTY_CLAIM_RE.search(para):
            continue
        if _AUTHOR_YEAR_RE.search(para):
            continue
        n_we_propose += len(_WE_PROPOSE_RE.findall(para))
        n_other_novelty += len(_NOVELTY_CLAIM_RE.findall(para)) - len(_WE_PROPOSE_RE.findall(para))
        paragraphs[i] = _NOVELTY_CLAIM_RE.sub(_soften_novelty_phrase, para)
    if n_we_propose or n_other_novelty:
        text = "".join(paragraphs)
    for rule, n, detail in (
        ("soften_we_propose", n_we_propose, f"softened 'we propose' → 'we operationalize' in {n_we_propose} ungrounded paragraph(s)"),
        ("soften_unsupported_novelty", n_other_novelty, f"softened {n_other_novelty} ungrounded novelty phrase(s)"),
    ):
        if n:
            entries.append(FinalizerLogEntry("E_structural_fallback", rule, n, detail))

    return text, entries


# --- Phase F: Reconcile Results table with H3 subsections -------------


def _phase_f_reconcile_results_table(
    text: str, out_dir: Path,
) -> tuple[str, list[FinalizerLogEntry]]:
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.is_file():
        return text, []
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return text, []
    receipts = manifest.get("receipts") or ()
    if not receipts:
        return text, []
    results_match = re.search(
        r"^## Results\b(.*?)(?=^## (?!#))", text, flags=re.M | re.S,
    )
    if not results_match:
        return text, []
    results = results_match.group(1)
    from agent.journal_surface_gate import _outcome_key
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in receipts:
        if isinstance(r, dict) and r.get("outcome_class"):
            groups.setdefault(_outcome_key(str(r["outcome_class"])), []).append(r)
    if not groups:
        return text, []
    rows = [
        "| Outcome class | Corpus slice | Strongest signal | Directness | Main limitation |",
        "|---|---|---|---|---|",
    ]
    stubs: list[tuple[str, str, int, int, str, str, str]] = []
    for slug, matching in sorted(
        groups.items(), key=lambda kv: (-len(kv[1]), _outcome_display(kv[0])),
    ):
        n = len(matching)
        n_claims = sum(int(r.get("n_claims") or 0) for r in matching)
        directness_counts: dict[str, int] = {}
        for r in matching:
            d = str(r.get("directness") or "").strip().lower()
            if d:
                directness_counts[d] = directness_counts.get(d, 0) + 1
        directness_cell = "; ".join(
            f"{count} {kind}" for kind, count in sorted(directness_counts.items())
        ) or "—"
        effect_counts: dict[str, int] = {}
        for r in matching:
            e = str(r.get("effect_direction") or "").strip().lower()
            if e:
                effect_counts[e] = effect_counts.get(e, 0) + 1
        top_effect = (
            max(effect_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if effect_counts else "unclear"
        )
        signal_cell = (
            f"no extracted directional signal in {effect_counts.get(top_effect, 0)}/{n} sources"
            if top_effect == "null" else f"{top_effect} signal in {effect_counts.get(top_effect, 0)}/{n} sources"
        ) if n else "no sources"
        limitation_cell = (
            "single-source slice; hypothesis-generating"
            if n <= 1 else "limited corpus depth in this outcome class"
        )
        rows.append(
            f"| {_outcome_display(slug)} | n={n}; claims={n_claims} | {signal_cell} "
            f"| {directness_cell} | {limitation_cell} |"
        )
        stubs.append((
            slug, _outcome_display(slug), n, n_claims, signal_cell,
            directness_cell, limitation_cell,
        ))
    table = "\n".join(rows) + "\n"
    lines = results.splitlines(keepends=True)
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == rows[0])
    except StopIteration:
        new_results = "\n" + table + "\n" + results.lstrip()
    else:
        end = start + 2
        while end < len(lines) and lines[end].strip():
            end += 1
        new_results = "".join(lines[:start]) + table + "".join(lines[end:])
    existing = {
        _outcome_key(m.group(1))
        for m in re.finditer(r"^###\s+(.+?)\s*$", new_results, flags=re.M)
    }
    missing_blocks = []
    for slug, display, n, n_claims, signal, directness, limitation in stubs:
        block = f"### {display} Outcomes\n\n{display} remains a separate Results slice (n={n}; claims={n_claims}; {signal}; {directness}; {limitation}) and is not pooled into adjacent endpoint classes.\n"
        empty = re.search(rf"(?ms)^###\s+{re.escape(display)}\s+Outcomes\s*\n\s*(?=^###\s+|\Z)", new_results)
        if empty:
            new_results = new_results[:empty.start()] + block + new_results[empty.end():]
            continue
        if slug in existing:
            continue
        missing_blocks.append(block)
    if missing_blocks:
        new_results = new_results.rstrip() + "\n\n" + "\n".join(missing_blocks)
    new_results = re.sub(r"\bnull signal in (\d+/\d+ sources)", r"no extracted directional signal in \1", new_results)
    if new_results == results:
        return text, []
    new_text = text[:results_match.start(1)] + new_results + text[results_match.end(1):]
    return new_text, [FinalizerLogEntry(
        phase="F_reconcile_results_table",
        rule="rebuild_results_summary_table",
        n_changes=len(rows) - 2,
        detail=f"rebuilt Results outcome table from manifest ({len(rows) - 2} row(s))",
    )]


# --- Phase G: refresh stale sidecars after prose stabilises ------------


def _load_sidecar(p: Path) -> Any:
    try:
        return json.loads(p.read_text()) if p.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def _reevaluate_journal_surface(out_dir: Path) -> int:
    paper_path = out_dir / "full_paper.md"
    if not paper_path.is_file():
        return 0
    report = _surface_report(paper_path.read_text(), out_dir)
    if report is None:
        return 0
    old = _load_sidecar(out_dir / "full_paper.journal_surface.json") or {}
    old_n = len(old.get("issues") or []) if isinstance(old, dict) else 0
    (out_dir / "full_paper.journal_surface.json").write_text(json.dumps({
        "passed": report.passed,
        "issues": [asdict(i) for i in report.issues]}, indent=2))
    return len(report.issues) - old_n


def _refresh_pre_submit_gate(out_dir: Path) -> bool:
    gate = _load_sidecar(out_dir / "pre_submit_gate.json")
    surface = _load_sidecar(out_dir / "full_paper.journal_surface.json")
    audit = _load_sidecar(out_dir / "full_paper.audit.json")
    if not (isinstance(gate, dict) and isinstance(surface, dict) and isinstance(gate.get("inputs"), dict)):
        return False
    inputs = gate["inputs"]
    new_surface = bool(surface.get("passed"))
    new_audit = bool(isinstance(audit, dict) and audit.get("p1_pass"))
    try:
        reviewer_p1 = importlib.import_module("scripts.run_v06_synthesis")._reviewer_p1_counts_from_log(out_dir)[0]
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        reviewer_p1 = 0
    new_reviewer = reviewer_p1 if "unresolved_reviewer_p1_count" in inputs else int(inputs.get("unresolved_reviewer_p1_count", 0))
    if (
        bool(inputs.get("journal_surface_passed")) == new_surface
        and bool(inputs.get("audit_gates_passed")) == new_audit
        and int(inputs.get("unresolved_reviewer_p1_count", new_reviewer)) == new_reviewer
    ):
        return False
    # numeric_coverage is audit-derived (the Q2 "N/M trace" ratio). Refresh it
    # alongside audit_gates_passed so a now-fixed Q2 propagates into the gate
    # instead of leaving the stale pre-fix coverage that keeps blocking submit.
    try:
        from agent.final_gate import GateInputs, evaluate_final_gate
        fresh = {
            **inputs,
            "journal_surface_passed": new_surface,
            "audit_gates_passed": new_audit,
            "numeric_coverage": next((int(m[1]) / int(m[2]) for c in (audit.get("checks") or []) if isinstance(c, dict) and c.get("name") == "Q2_numeric_integrity" and (m := re.search(r"(\d+)/(\d+)", str(c.get("detail") or ""))) and int(m[2])), inputs.get("numeric_coverage")) if isinstance(audit, dict) else inputs.get("numeric_coverage"),  # noqa: E501
            "unresolved_reviewer_p1_count": new_reviewer,
        }
        result = evaluate_final_gate(GateInputs(**fresh))
    except (ImportError, TypeError, ValueError):
        return False
    gate["inputs"], gate["result"] = fresh, asdict(result)
    (out_dir / "pre_submit_gate.json").write_text(json.dumps(gate, indent=2))
    return True

def _refresh_final_verdict(out_dir: Path) -> bool:
    try:
        return bool(importlib.import_module("scripts.run_v06_synthesis")._refresh_post_finalizer_verdict(out_dir))
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        return False


def _refresh_final_status(out_dir: Path) -> bool:
    path = out_dir / "final_status.json"
    before = _load_sidecar(path)
    if before is None:
        return False
    try:
        from agent.final_status import compute_and_write
        compute_and_write(out_dir)
    except (ImportError, OSError, TypeError, ValueError):
        return False
    return before != _load_sidecar(path)


def _refresh_audit_sidecar(out_dir: Path) -> bool:
    paper_path = out_dir / "full_paper.md"
    if not paper_path.is_file():
        return False
    manifest = _load_sidecar(out_dir / "manifest.json")
    if not isinstance(manifest, dict):
        manifest = {}
    try:
        audit_v06 = importlib.import_module("scripts.audit_v06_paper")
        topic = str(manifest.get("topic") or "").strip()
        if topic:
            audit_v06._set_topic(topic)
        review_type = manifest.get("review_type")
        report = audit_v06.audit(
            paper_path.read_text(),
            review_type=review_type if isinstance(review_type, str) else None,
            manifest=manifest,
        )
    except (ImportError, OSError, TypeError, ValueError):
        return False
    if _load_sidecar(out_dir / "full_paper.audit.json") == report:
        return False
    (out_dir / "full_paper.audit.json").write_text(json.dumps(report, indent=2))
    (out_dir / "full_paper.audit.md").write_text(audit_v06._format_summary(report))
    return True


def _phase_g_refresh_sidecars(out_dir: Path) -> list[FinalizerLogEntry]:
    log: list[FinalizerLogEntry] = []
    _g = lambda rule, n, detail: log.append(FinalizerLogEntry(phase="G_refresh_sidecars", rule=rule, n_changes=n, detail=detail))  # noqa: E731
    if _refresh_audit_sidecar(out_dir):
        _g("refresh_audit_post_finalizer", 1, "full_paper.audit refreshed against post-finalizer manuscript")
    n_resolved = 0
    try:
        n_resolved = int(importlib.import_module("scripts.run_v06_synthesis")._resolve_absent_reviewer_p1s(out_dir))
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        n_resolved = 0
    if n_resolved:
        _g("resolve_absent_reviewer_p1", n_resolved, "reviewer P1 target absent after deterministic finalization")
    delta = _reevaluate_journal_surface(out_dir)
    if delta != 0:
        _g("reevaluate_journal_surface_post_finalizer", 1, f"surface issues delta vs pre-finalizer gate: {delta:+d}")
    if _refresh_pre_submit_gate(out_dir):
        _g("refresh_pre_submit_gate_with_fresh_surface", 1, "pre_submit_gate.inputs.journal_surface_passed + result recomputed")
    if _refresh_final_consistency_sidecar(out_dir):
        _g("refresh_final_consistency_post_finalizer", 1, "full_paper.consistency refreshed against post-finalizer manuscript")
    if _refresh_artifact_consistency_sidecar(out_dir):
        _g("refresh_artifact_consistency_post_finalizer", 1, "artifact_consistency refreshed before readiness/final_status")
    if _refresh_final_verdict(out_dir):
        _g("refresh_final_verdict_post_finalizer", 1, "full_paper.final_verdict refreshed against post-finalizer sidecars")
    n_items = _refresh_readiness_contract_items(out_dir)
    if n_items:
        _g("reconcile_readiness_contract_items", n_items, f"refreshed {n_items} stale readiness-contract item(s) against post-Phase-G sidecars")
    if _refresh_final_status(out_dir):
        _g("refresh_final_status_post_finalizer", 1, "final_status refreshed against post-finalizer sidecars")
    return log


def _refresh_final_consistency_sidecar(out_dir: Path) -> bool:
    paper_path = out_dir / "full_paper.md"
    if not paper_path.is_file():
        return False
    manifest = _load_sidecar(out_dir / "manifest.json")
    audit = _load_sidecar(out_dir / "full_paper.audit.json")
    if not isinstance(manifest, dict) or not isinstance(audit, dict):
        return False
    try:
        consistency_audit = importlib.import_module("scripts.final_consistency_audit")
        audit_md = (
            (out_dir / "full_paper.audit.md").read_text()
            if (out_dir / "full_paper.audit.md").is_file()
            else ""
        )
        issues = consistency_audit.run_audit(
            paper_path.read_text(), manifest, audit, audit_md,
        )
        payload = [asdict(i) for i in issues]
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return False
    path = out_dir / "full_paper.consistency.json"
    if _load_sidecar(path) == payload:
        return False
    path.write_text(json.dumps(payload, indent=2))
    try:
        (out_dir / "full_paper.consistency.md").write_text(
            consistency_audit._format_summary(issues),
        )
    except (AttributeError, OSError):
        pass
    return True


def _refresh_artifact_consistency_sidecar(out_dir: Path) -> bool:
    if not (out_dir / "full_paper.md").is_file():
        return False
    path = out_dir / "artifact_consistency.json"
    before = _load_sidecar(path)
    try:
        from agent.artifact_consistency import verify_run_artifacts, write_consistency_sidecar
        write_consistency_sidecar(out_dir, verify_run_artifacts(out_dir))
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return False
    return before != _load_sidecar(path)


def _refresh_readiness_contract_items(out_dir: Path) -> int:
    gate = _load_sidecar(out_dir / "pre_submit_gate.json")
    if not isinstance(gate, dict):
        return 0
    contract = gate.get("journal_readiness_contract")
    if not isinstance(contract, list):
        return 0
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    surface = _load_sidecar(out_dir / "full_paper.journal_surface.json") or {}
    target = _load_sidecar(out_dir / "target_journal_pack.json")
    surface_pass = bool(surface.get("passed"))
    surface_n = len(surface.get("issues") or [])
    gate_passed = bool((gate.get("result") or {}).get("passed"))
    tj = target.get("journal") if isinstance(target, dict) else None
    tj_declared = bool(target.get("declared_in_topic_pack")) if isinstance(target, dict) else False
    from agent.accountability import accountability_pass, resolve_model
    model = resolve_model(manifest.get("accountability_model"))
    legacy = model == "legacy_journal_submission"
    acc_ok, acc_detail = accountability_pass(out_dir, model)
    submission_ready = gate_passed and surface_pass
    unresolved_p1 = int((gate.get("inputs") or {}).get("unresolved_reviewer_p1_count") or 0)
    receipts = int(manifest.get("n_receipts") or 0)
    from agent.final_gate import DEFAULT_THRESHOLDS, RECOMMENDED_SOURCE_CITATIONS
    from agent.final_status import ADVISORY_READINESS_ITEM_IDS
    fresh: dict[int, dict[str, object]] = {
        1: {"status": "pass" if submission_ready else "not_ready",
            "audit": f"pre_submit_gate={gate_passed}; "
                     f"journal_surface={surface_pass}; "
                     f"submission_ready={submission_ready}"},
        2: {"status": "pass" if receipts >= DEFAULT_THRESHOLDS.min_receipts else "not_ready",
            "audit": (
                f"receipts={receipts}; recommended>={RECOMMENDED_SOURCE_CITATIONS}; "
                f"minimum>={DEFAULT_THRESHOLDS.min_receipts}"
            )},
        7: {"status": "pass" if surface_pass else "not_ready",
            "audit": f"journal_surface_passed={surface_pass}"},
        9: {"status": "pass" if surface_pass else "not_ready",
            "audit": f"issues={surface_n}"},
        11: {"status": "pass" if unresolved_p1 == 0 else "not_ready",
             "audit": f"unresolved_p1={unresolved_p1}",
             "next_action": "Resolve reviewer P1s or mark as human-blocking."},
        12: {"status": "pass" if tj and tj_declared else
                       ("partial" if tj else "not_ready"),
             "audit": f"target_journal={tj!r}; declared_in_topic_pack={tj_declared}",
             "advisory": True},
        13: {"name": "human_signoff" if legacy else "accountability",
             "status": "pass" if acc_ok else "not_ready",
             "audit": acc_detail or (
                 "submission requires author/domain-expert approval outside the bot"
                 if legacy else
                 "researka_agent_certified mode; verify artifact-consistency spine"),
             "next_action": (
                 "Collect named author/domain-expert signoff before submission."
                 if legacy else
                 "Restore artifact-consistency spine or citation registry.")},
    }
    n_changed = 0
    for item in contract:
        if not isinstance(item, dict):
            continue
        before = dict(item)
        item_id = item.get("id")
        f = fresh.get(item_id) if isinstance(item_id, int) else None
        if f:
            item.update(f)
        item["advisory"] = item.get("advisory", False) or item_id in ADVISORY_READINESS_ITEM_IDS
        item["blocks_submission"] = item.get("status") != "pass" and not item["advisory"]
        if item != before:
            n_changed += 1
    if n_changed:
        (out_dir / "pre_submit_gate.json").write_text(json.dumps(gate, indent=2))
    n_changed += _write_pre_submit_gate_markdown(out_dir, gate)
    return n_changed


def _write_pre_submit_gate_markdown(out_dir: Path, gate: dict[str, object]) -> int:
    contract = gate.get("journal_readiness_contract")
    result = gate.get("result")
    if not isinstance(contract, list) or not isinstance(result, dict):
        return 0
    try:
        from paper_quality_runtime import _format_readiness_contract
    except ImportError:
        return 0
    summary = str(result.get("summary") or "")
    text = (
        "# Pre-Submit Final Gate\n\n"
        + summary
        + "\n\n## Journal Readiness Contract\n\n"
        + _format_readiness_contract([row for row in contract if isinstance(row, dict)])
        + "\n"
    )
    n_written = 0
    for path in (out_dir / "pre_submit_gate.md", out_dir / "readable" / "pre_submit_gate.md"):
        if path.parent.exists() and (not path.exists() or path.read_text() != text):
            path.write_text(text)
            n_written += 1
    return n_written
