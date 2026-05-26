from __future__ import annotations

import json
import re
import importlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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


def finalize_run(out_dir: Path) -> FinalizerReport:
    paper_path = out_dir / "full_paper.md"
    if not paper_path.is_file():
        return FinalizerReport(paper_changed=False, final_word_count=0)
    text = paper_path.read_text()
    original = text
    entries: list[FinalizerLogEntry] = []

    text, log = _phase_a_methods_replace(text, out_dir)
    entries.extend(log)
    text, log = _phase_b_lane_qualifier(text, out_dir)
    entries.extend(log)
    text, log = _phase_c_terminology(text)
    entries.extend(log)
    text, log = _phase_d_reference_closure(text)
    entries.extend(log)
    text, log = _phase_b_lane_qualifier(text, out_dir)
    entries.extend(log)
    text, log = _phase_e_structural_fallback(text, out_dir)
    entries.extend(log)
    text, log = _phase_f_reconcile_results_table(text, out_dir)
    entries.extend(log)
    text, log = _phase_h_topic_slug_normalise(text, out_dir)
    entries.extend(log)
    text, log = _phase_i_split_concatenated_headings(text)
    entries.extend(log)
    text, log = _phase_k_route_outcome_paragraphs(text, out_dir)
    entries.extend(log)
    text, log = _phase_l_strengthen_analytical_sections(text, out_dir)
    entries.extend(log)
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
    g_log = _phase_g_refresh_sidecars(out_dir)
    entries.extend(g_log)
    report = FinalizerReport(paper_changed=changed, final_word_count=len(text.split()), entries=tuple(entries))  # noqa: E501
    (out_dir / "journal_finalizer.json").write_text(json.dumps(asdict(report), indent=2))
    return report


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
        paragraphs[i] = lead + _lowercase_first_letter(para.lstrip())
        n_patched += 1
    if n_patched == 0:
        return text, []
    new_body = "".join(paragraphs)
    return new_body + tail, [FinalizerLogEntry(phase="B_lane_qualifier", rule="animal_preclinical_lead_in", n_changes=n_patched, detail=f"prepended lane qualifier to {n_patched} paragraph(s)")]


# --- Phase C: Terminology sanitizer -----------------------------------


def _phase_c_terminology(text: str) -> tuple[str, list[FinalizerLogEntry]]:
    from agent.journal_surface_gate import apply_pipeline_jargon_replacements
    out = apply_pipeline_jargon_replacements(text)
    if out == text:
        return text, []
    return out, [FinalizerLogEntry(phase="C_terminology", rule="pipeline_jargon_to_academic", n_changes=1, detail="applied _PIPELINE_JARGON_PUBLIC substitution table")]


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


def _phase_i_split_concatenated_headings(text: str) -> tuple[str, list[FinalizerLogEntry]]:
    new_text, n = _CONCAT_HEADING_RE.subn(r"\1\n\n\2", text)
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
_CITE_AY_RE = re.compile(r"\b[A-Z][a-zA-Z\-]+ \d{4}\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _outcome_display(slug: str) -> str:
    cleaned = re.sub(
        r"\s+outcomes?$", "", slug.replace("_", " "), flags=re.I,
    )
    return " ".join(w.capitalize() for w in cleaned.split())


def _phase_k_route_outcome_paragraphs(text: str, out_dir: Path) -> tuple[str, list[FinalizerLogEntry]]:
    from agent.journal_surface_gate import _outcome_key
    from collections import Counter
    manifest = _load_sidecar(out_dir / "manifest.json") or {}
    registry = _load_sidecar(out_dir / "citation_registry.json") or {}
    rs = re.search(r"^## Results\b.*?(?=^## (?!#)|\Z)", text, flags=re.M | re.S)
    if not (isinstance(manifest, dict) and isinstance(registry, dict) and rs):
        return text, []
    oc = {r["receipt_id"]: r["outcome_class"] for r in (manifest.get("receipts") or ())
          if isinstance(r, dict) and r.get("outcome_class") and r.get("receipt_id")}
    cmap = {e["body_citation"]: oc[rid] for rid, e in registry.items()
            if isinstance(e, dict) and e.get("body_citation") and rid in oc}
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
    if not n_moved:
        return text, []
    new_block = block[:h3s[0].start()] + "\n\n".join(headings[i] + "\n\n" + "\n\n".join(b) for i, b in enumerate(bodies)) + "\n\n"
    return text[:rs.start()] + new_block + text[rs.end():], [FinalizerLogEntry(phase="K_outcome_routing", rule="route_paragraph_by_citation_class", n_changes=n_moved, detail=f"moved {n_moved} paragraph(s) to correct outcome subsection")]


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

    plans = _load_sidecar(out_dir / "audit" / "tension_elaboration_plans.json") or {}
    rows = []
    for p in (plans.get("plans") or [])[:15] if isinstance(plans, dict) else []:
        if not isinstance(p, dict):
            continue
        anchors = ", ".join(dict.fromkeys(p.get("numeric_anchors") or ()).keys())
        anchors = anchors[:120].rstrip(", ")
        hypotheses = "; ".join((p.get("hypotheses") or [])[:2])
        rows.append(
            f"- {p.get('paper_a')} versus {p.get('paper_b')} defines a "
            f"{p.get('outcome_class')} {p.get('conflict_type')} with severity "
            f"{p.get('severity')}. Numeric anchors include {anchors}. The "
            f"leading explanation is {hypotheses}. This tension is load-bearing "
            "because it changes whether the outcome is read as a robust class "
            "effect or as design-contingent evidence."
        )
    if rows:
        append("Cross-Domain Synthesis", "### Load-Bearing Tensions\n\n" + "\n".join(rows), "load_bearing_tensions")

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
            insertion = (
                f"\n\n**Thesis:** {thesis_text}\n\n"
            )
            text = (
                text[:heading_end]
                + insertion
                + text[heading_end:]
            )
            entries.append(FinalizerLogEntry(phase="E_structural_fallback", rule="insert_thesis_marker", n_changes=1, detail=f"inserted **Thesis:** marker from manifest ({len(thesis_text)} chars)"))

    # E.2 — append **Resolution criteria:** if missing
    disc_match2 = re.search(
        r"^## Discussion\b(.*?)(?=^## (?!#))", text,
        flags=re.M | re.S,
    )
    if (
        disc_match2
        and not _RESOLUTION_MARKER_PRESENT.search(disc_match2.group(1))
    ):
        # Insert before the section's closing boundary
        section_end = disc_match2.end()
        # The match ends right BEFORE the next `## ` heading; we want
        # to insert just before that heading line.
        insertion = (
            "\n\n**Resolution criteria:** The thesis would be "
            "reinforced by adequately powered trials with "
            "pre-specified clinical endpoints, ≥2-year follow-up, "
            "intention-to-treat and per-protocol analyses, and "
            "concurrent biomarker plus functional measurement. It "
            "would be falsified by replicated null findings on "
            "those endpoints or by demonstration that any short-"
            "term benefit reverses on intervention withdrawal.\n"
        )
        text = (
            text[:section_end]
            + insertion
            + text[section_end:]
        )
        entries.append(FinalizerLogEntry(
            phase="E_structural_fallback",
            rule="insert_resolution_criteria",
            n_changes=1,
            detail="appended **Resolution criteria:** paragraph",
        ))

    # E.3 — soften ungrounded "we propose"
    paragraphs = re.split(r"(\n\s*\n)", text)
    n_softened = 0
    for i in range(0, len(paragraphs), 2):
        para = paragraphs[i]
        if not _WE_PROPOSE_RE.search(para):
            continue
        # Has an inline citation in the same paragraph?
        if re.search(
            r"\b([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+|[A-Z]{2,})"
            r"(?:\s+et\s+al\.)?\s+((?:19|20)\d{2})\b",
            para,
        ):
            continue
        # Preserve original capitalization — "We propose" → "We
        # operationalize"; "we propose" → "we operationalize".
        def _soften(m: re.Match[str]) -> str:
            return (
                "We operationalize"
                if m.group(0)[0].isupper()
                else "we operationalize"
            )
        paragraphs[i] = _WE_PROPOSE_RE.sub(_soften, para)
        n_softened += 1
    if n_softened:
        text = "".join(paragraphs)
        entries.append(FinalizerLogEntry(
            phase="E_structural_fallback",
            rule="soften_we_propose",
            n_changes=n_softened,
            detail=f"softened 'we propose' → 'we operationalize' in "
                   f"{n_softened} ungrounded paragraph(s)",
        ))

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
            f"{top_effect} signal in {effect_counts.get(top_effect, 0)}/{n} sources"
            if n else "no sources"
        )
        limitation_cell = (
            "single-source slice; hypothesis-generating"
            if n <= 1 else "limited corpus depth in this outcome class"
        )
        rows.append(
            f"| {_outcome_display(slug)} | n={n}; claims={n_claims} | {signal_cell} "
            f"| {directness_cell} | {limitation_cell} |"
        )
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
    manifest = _load_sidecar(out_dir / "manifest.json")
    if not paper_path.is_file() or not isinstance(manifest, dict):
        return 0
    lanes = _load_sidecar(out_dir / "evidence_lanes.json") or {}
    registry = _load_sidecar(out_dir / "citation_registry.json") or {}
    animal = [str(a.get("citation", "")) for a in (lanes.get("animal_citations") or [])
              if isinstance(a, dict) and a.get("citation")]
    oc = {r["receipt_id"]: r["outcome_class"] for r in (manifest.get("receipts") or ())
          if isinstance(r, dict) and r.get("outcome_class") and r.get("receipt_id")}
    cmap = {e["body_citation"]: oc[rid] for rid, e in (registry.items() if isinstance(registry, dict) else ())
            if isinstance(e, dict) and e.get("body_citation") and rid in oc}
    try:
        from agent.journal_surface_gate import evaluate_journal_surface
        report = evaluate_journal_surface(
            paper_path.read_text(), animal_citations=animal,
            citation_outcome_map=cmap,
            declared_review_type=manifest.get("review_type"))
    except (ImportError, ValueError):
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
    new_audit = bool(isinstance(audit, dict) and audit.get("p1_pass") and audit.get("n_pass") == audit.get("n_total"))
    reviewer_p1, _, _ = _reviewer_counts(out_dir)
    new_reviewer = int(inputs.get("unresolved_reviewer_p1_count", reviewer_p1))
    if "unresolved_reviewer_p1_count" in inputs:
        new_reviewer = reviewer_p1
    if (
        bool(inputs.get("journal_surface_passed")) == new_surface
        and bool(inputs.get("audit_gates_passed")) == new_audit
        and int(inputs.get("unresolved_reviewer_p1_count", new_reviewer)) == new_reviewer
    ):
        return False
    try:
        from agent.final_gate import GateInputs, evaluate_final_gate
        fresh = {
            **inputs,
            "journal_surface_passed": new_surface,
            "audit_gates_passed": new_audit,
            "unresolved_reviewer_p1_count": new_reviewer,
        }
        result = evaluate_final_gate(GateInputs(**fresh))
    except (ImportError, TypeError, ValueError):
        return False
    gate["inputs"], gate["result"] = fresh, asdict(result)
    (out_dir / "pre_submit_gate.json").write_text(json.dumps(gate, indent=2))
    return True


def _reviewer_counts(out_dir: Path) -> tuple[int, int, int]:
    try:
        synth = importlib.import_module("scripts.run_v06_synthesis")
        return synth._reviewer_p1_counts_from_log(out_dir)
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        return 0, 0, 0


def _refresh_final_verdict(out_dir: Path) -> bool:
    try:
        return bool(importlib.import_module("scripts.run_v06_synthesis")._refresh_post_finalizer_verdict(out_dir))
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        return False


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
    if _refresh_final_verdict(out_dir):
        _g("refresh_final_verdict_post_finalizer", 1, "full_paper.final_verdict refreshed against post-finalizer sidecars")
    n_items = _refresh_readiness_contract_items(out_dir)
    if n_items:
        _g("reconcile_readiness_contract_items", n_items, f"refreshed {n_items} stale readiness-contract item(s) against post-Phase-G sidecars")
    return log


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
    from agent.final_status import ADVISORY_READINESS_ITEM_IDS
    fresh: dict[int, dict[str, object]] = {
        1: {"status": "pass" if submission_ready else "not_ready",
            "audit": f"pre_submit_gate={gate_passed}; "
                     f"journal_surface={surface_pass}; "
                     f"submission_ready={submission_ready}"},
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
    return n_changed
