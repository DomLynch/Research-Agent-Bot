"""Deterministic renderer for cross-topic meta-synthesis artifacts."""
from __future__ import annotations

from agent.contradiction_detector import TopicContradiction
from agent.convergence_detector import MechanismConvergence
from agent.cross_topic_aggregator import FieldManifest


def render_cross_topic_meta_synthesis(
    manifest: FieldManifest,
    convergences: tuple[MechanismConvergence, ...],
    contradictions: tuple[TopicContradiction, ...],
) -> str:
    primary = [t for t in manifest.topics if t.eligibility == "full_aaa_primary"]
    analytical = [t for t in manifest.topics if t.eligibility == "analytical_support"]
    scoped = [t for t in manifest.topics if t.eligibility == "scoped_support"]
    excluded = [t for t in manifest.topics if t.eligibility == "excluded"]
    parts = [
        "# Cross-Topic GeroScience Meta-Synthesis",
        "",
        "This meta-synthesis compares finalized Researka topic runs only. It does "
        "not assert human journal review, introduce raw-paper claims, or convert "
        "scoped evidence into pipeline-primary conclusions.",
        "",
        "## Topic Eligibility",
        _topic_table(primary + analytical + scoped + excluded),
        "",
        "_Count semantics: source papers are the corpus entering the run; eligible "
        "sources and public disagreements come from the final public-contract "
        "state; pipeline tensions are the raw matrix count._",
        "",
        "## Pipeline Evidence Lane",
        _primary_lane(primary, analytical),
        "",
        "## Mechanism Convergences",
        _convergence_section(convergences),
        "",
        "## Cross-Topic Contradictions",
        _contradiction_section(contradictions),
        "",
        "## Scoped-Evidence Appendix",
        _scoped_section(scoped),
        "",
        "## Audit Boundary",
        "- Every topic-level statement above cites source run IDs.",
        "- Excluded and SCOP topics do not drive primary conclusions.",
        "- Cross-topic findings are maps of agreement or tension, not clinical advice.",
    ]
    return "\n".join(parts).rstrip() + "\n"


def _topic_table(topics: list) -> str:
    rows = [
        "| Topic | Lane | Pipeline status | Human review | Source papers | Eligible sources | Claims / observations | Public disagreements | Pipeline tensions | Run |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for t in topics:
        rows.append(
            f"| {t.topic} | {_lane_label(t.eligibility)} | {_status_label(t.eligibility)} | "
            f"not manually reviewed | {_source_papers(t)} | {_eligible_sources(t)} | "
            f"{t.n_high_confidence_claims} | {_public_tensions(t)} | "
            f"{_pipeline_tensions(t)} | `{t.run_id}` |"
        )
    return "\n".join(rows)


def _lane_label(eligibility: str) -> str:
    return {
        "full_aaa_primary": "pipeline-primary",
        "analytical_support": "analytical-support",
        "scoped_support": "scoped-support",
    }.get(eligibility, "excluded")


def _status_label(eligibility: str) -> str:
    return "pipeline-qualified" if eligibility != "excluded" else "excluded"


def _primary_lane(primary: list, analytical: list) -> str:
    if not primary and not analytical:
        return "No pipeline-primary or analytical topics were eligible."
    lines = []
    for topic in (*primary, *analytical):
        lane = "pipeline-primary" if topic.eligibility == "full_aaa_primary" else "analytical"
        domains = ", ".join(topic.outcome_domains) or "unspecified"
        lines.append(
            f"- `{topic.run_id}` enters the {lane} lane with "
            f"{_source_papers(topic)} source papers and "
            f"{_eligible_sources(topic)} eligible sources across {domains}."
        )
    return "\n".join(lines)


def _source_papers(topic) -> int:
    return int(getattr(topic, "n_source_papers", 0) or topic.n_receipts)


def _eligible_sources(topic) -> int:
    return int(getattr(topic, "n_accepted_papers", 0) or topic.n_receipts)


def _public_tensions(topic) -> int:
    return int(getattr(topic, "n_public_tensions", 0) or topic.n_tensions)


def _pipeline_tensions(topic) -> int:
    return int(getattr(topic, "n_pipeline_tensions", 0) or topic.n_tensions)


def _convergence_section(convergences: tuple[MechanismConvergence, ...]) -> str:
    if not convergences:
        return "No deterministic mechanism convergence met the topic-count floor."
    return "\n".join(
        f"- **{c.mechanism}** converges across {', '.join(c.topics)} "
        f"(`{', '.join(c.run_ids)}`)."
        for c in convergences
    )


def _contradiction_section(contradictions: tuple[TopicContradiction, ...]) -> str:
    if not contradictions:
        return "No deterministic positive-vs-negative cross-topic contradictions were found."
    return "\n".join(
        f"- **{c.outcome_domain}**: positive lane {', '.join(c.positive_topics)} "
        f"versus negative lane {', '.join(c.negative_topics)} "
        f"(`{', '.join(c.run_ids)}`)."
        for c in contradictions
    )


def _scoped_section(scoped: list) -> str:
    if not scoped:
        return "No scoped-support topics were included."
    return "\n".join(
        f"- `{topic.run_id}` remains scoped support only; human-review status "
        "is not asserted."
        for topic in scoped
    )
