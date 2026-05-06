"""Researka multi-topic dashboard — scans all run dirs and summarizes
verdict + cert status per topic.

Output:
  - docs/multi_topic_dashboard.md: human-readable per-topic status
  - docs/multi_topic_dashboard.json: machine-readable summary

For each topic, picks the BEST run (preference: Researka Certified
A2A-AAA > AAA verdict > Trust-Spine Pass > everything else) and
shows: cert status, verdict, audit scores, word counts, cost,
patch counts. Across all topics, computes:
  - n_topics_attempted
  - n_topics_AAA (≥1 AAA run)
  - n_topics_certified (consecutive-AAA gate cleared)
  - cumulative LLM cost across all runs
  - total reviewer interventions logged

Used as the "methods paper exhibit" — shows the trust-spine in
action across every topic the platform has touched. No LLM cost.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class TopicSummary:
    topic: str
    n_runs: int
    best_run_id: str
    best_verdict: str
    aaa_runs: tuple[str, ...] = field(default_factory=tuple)
    certified: bool = False  # consecutive-AAA gate cleared
    cert_runs: tuple[str, ...] = field(default_factory=tuple)
    stage1_pass: str = "?/?"
    stage2_p1: int = 0
    stage2_p2: int = 0
    q2_traceability_pct: float = 0.0
    grok_unresolved_p1: int = 0
    word_count: int = 0
    cost_usd: float = 0.0
    n_patches_applied: int = 0
    n_patches_repaired: int = 0
    # Wave 7 / Slice 4 (Evidence Factory): maturity ladder + expansion
    # targets surfaced per-topic so the dashboard becomes the living
    # status of the platform, not just an after-the-fact verdict log.
    maturity_level: int = 0
    maturity_label: str = "L0 — UNSEEDED"
    journal_ready: bool = False
    corpus_gaps: tuple[str, ...] = field(default_factory=tuple)
    expansion_targets: tuple[str, ...] = field(default_factory=tuple)
    # Slice 6 step 4d: corpus pipeline funnel per topic. Empty dict
    # when the topic hasn't run the calibrated pipeline yet.
    corpus_funnel: dict[str, int] = field(default_factory=dict)


def _read_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


_VERDICT_RANK = {
    "AAA": 4,
    "Trust-Spine Pass": 3,
    "Trust-Spine Pass — Agent Review Unresolved": 2,
    "SHIP-BLOCKED": 1,
    "Unknown": 0,
}


def _verdict_rank(v: str) -> int:
    return _VERDICT_RANK.get(v, 0)


def _topic_from_run_dir(name: str) -> str | None:
    # synthesis-<topic>-v06-...
    parts = name.split("-")
    if len(parts) < 3 or parts[0] != "synthesis":
        return None
    return parts[1]


def scan_runs() -> dict[str, list[Path]]:
    """Group all synthesis-* run dirs by topic."""
    runs_dir = REPO / "runs"
    by_topic: dict[str, list[Path]] = {}
    if not runs_dir.exists():
        return by_topic
    for d in runs_dir.iterdir():
        if not d.is_dir():
            continue
        topic = _topic_from_run_dir(d.name)
        if topic is None:
            continue
        # Only include runs that completed (have full_paper.md +
        # final_verdict.json)
        if not (d / "full_paper.md").exists():
            continue
        if not (d / "full_paper.final_verdict.json").exists():
            continue
        by_topic.setdefault(topic, []).append(d)
    return by_topic


def summarize_topic(topic: str, runs: list[Path]) -> TopicSummary:
    """Build the per-topic summary from the available runs."""
    aaa_runs: list[str] = []
    cert_runs: list[str] = []
    best_run = None
    best_rank: tuple[int, int, int, int, str] = (-1, -1, -1, -1, "")

    import re as _re

    def _extract_ts(name: str) -> str:
        m = _re.search(
            r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)", name,
        )
        return m.group(1) if m else ""

    def _surface_ok(run: Path) -> bool:
        try:
            from agent.journal_surface_gate import evaluate_journal_surface
            return evaluate_journal_surface(
                (run / "full_paper.md").read_text(),
            ).passed
        except (ImportError, OSError):
            return False

    for r in sorted(runs):
        verdict_doc = _read_json(
            r / "full_paper.final_verdict.json"
        ) or {}
        cert_doc = _read_json(r / "full_paper.certification.json")
        verdict = verdict_doc.get("verdict", "Unknown")
        rank = _verdict_rank(verdict)
        if cert_doc and cert_doc.get("aaa_certified"):
            cert_runs.append(r.name)
        if verdict == "AAA":
            aaa_runs.append(r.name)
        maturity = int(verdict_doc.get("maturity_level", 0))
        journal = bool(verdict_doc.get("journal_ready", False))
        if journal and not _surface_ok(r):
            journal = False
            maturity = min(maturity, 4)
        rank_tuple = (
            1 if journal else 0,
            maturity,
            1 if cert_doc and cert_doc.get("aaa_certified") else 0,
            rank,
            _extract_ts(r.name),
        )
        if rank_tuple > best_rank:
            best_rank, best_run = rank_tuple, r

    if best_run is None:
        return TopicSummary(
            topic=topic, n_runs=len(runs),
            best_run_id="(none)", best_verdict="Unknown",
        )
    # Pull metrics from the best run
    audit = _read_json(best_run / "full_paper.audit.json") or {}
    verdict_doc = _read_json(
        best_run / "full_paper.final_verdict.json"
    ) or {}
    manifest = _read_json(best_run / "manifest.json") or {}
    patch_log = _read_json(
        best_run / "full_paper.review_patch_log.json"
    ) or {}
    patches_raw = _read_json(
        best_run / "full_paper.review_patches.json"
    ) or {}
    cert_doc = _read_json(
        best_run / "full_paper.certification.json"
    ) or {}

    # Q2 percent
    q2_pct = 0.0
    for c in audit.get("checks", []):
        if c.get("name") == "Q2_numeric_integrity":
            import re as _re
            m = _re.search(r"\((\d+)%\)", c.get("detail", ""))
            if m:
                q2_pct = float(m.group(1))

    n_repaired = sum(
        1 for p in patch_log.get("patches", [])
        if "repair" in (p.get("decision") or "").lower()
    )

    # Determine if topic has the consecutive-AAA cert
    # (≥2 AAA runs that BOTH pass the cert criteria).
    # Sort AAA runs by extracted timestamp (chronological), not
    # alphabetical — different run-name prefixes (AAA2-, FINAL-,
    # public-, etc.) make alphabetical sort wrong.
    certified = False
    if len(aaa_runs) >= 2:
        # Sort by timestamp DESCENDING — most recent first
        sorted_aaa = sorted(
            aaa_runs, key=_extract_ts, reverse=True,
        )
        try:
            sys.path.insert(0, str(REPO / "scripts"))
            import certification_report as _cert
            paths = [
                REPO / "runs" / name / "full_paper.md"
                for name in sorted_aaa[:2]
                if (
                    REPO / "runs" / name / "full_paper.md"
                ).exists()
            ]
            if len(paths) == 2:
                result = _cert.certify_consecutive(paths)
                certified = bool(result.get("certified"))
        except (ImportError, OSError, ValueError):
            pass

    cost = float(manifest.get("total_cost_usd", 0.0)) + float(
        patches_raw.get("cost_usd", 0.0)
    )

    # Slice 4 fields (back-compat: old runs without these keys
    # fall back to L0 / empty tuples — they predate the verdict
    # extension, so the dashboard renders them as 'unknown maturity'
    # rather than crashing).
    maturity_level = int(verdict_doc.get("maturity_level", 0))
    maturity_label = verdict_doc.get(
        "maturity_label", "L? — pre-Wave-7",
    )
    if maturity_level == 4 and maturity_label == "L4 — AAA":
        maturity_label = "L4 — ANALYTICALLY CERTIFIED"
    journal_ready = bool(verdict_doc.get("journal_ready", False))
    if journal_ready:
        try:
            from agent.journal_surface_gate import evaluate_journal_surface
            surface = evaluate_journal_surface(
                (best_run / "full_paper.md").read_text(),
            )
            if not surface.passed:
                journal_ready = False
                if maturity_level >= 5:
                    maturity_level = 4
                    maturity_label = "L4 — ANALYTICALLY CERTIFIED"
        except (ImportError, OSError):
            journal_ready = False
    corpus_gaps = tuple(verdict_doc.get("corpus_gaps") or [])
    expansion_targets = tuple(verdict_doc.get("expansion_targets") or [])

    # Slice 6 step 4d: read the calibrated-pipeline corpus manifest
    # if it exists. Funnel = {retrieved, classified_keep / drop,
    # extractable_core / background / adjacent, class_<each>,
    # cap_triggered}.
    corpus_funnel: dict[str, int] = {}
    funnel_path = (
        REPO / "docs" / "quality-reference" / topic
        / "corpus_manifest.json"
    )
    if funnel_path.exists():
        funnel_doc = _read_json(funnel_path)
        if funnel_doc:
            corpus_funnel = dict(funnel_doc.get("funnel", {}))

    return TopicSummary(
        topic=topic,
        n_runs=len(runs),
        best_run_id=best_run.name,
        best_verdict=verdict_doc.get("verdict", "Unknown"),
        aaa_runs=tuple(aaa_runs),
        certified=certified,
        cert_runs=tuple(cert_runs),
        stage1_pass=verdict_doc.get("stage1_pass_rate", "?/?"),
        stage2_p1=int(verdict_doc.get("stage2_p1", 0)),
        stage2_p2=int(verdict_doc.get("stage2_p2", 0)),
        q2_traceability_pct=q2_pct,
        grok_unresolved_p1=int(
            verdict_doc.get("grok_unresolved_p1", 0)
        ),
        word_count=int(manifest.get("total_words", 0)),
        cost_usd=cost,
        n_patches_applied=int(patch_log.get("n_applied", 0)),
        n_patches_repaired=n_repaired,
        maturity_level=maturity_level,
        maturity_label=maturity_label,
        journal_ready=journal_ready,
        corpus_gaps=corpus_gaps,
        expansion_targets=expansion_targets,
        corpus_funnel=corpus_funnel,
    )


def render_md(summaries: list[TopicSummary]) -> str:
    """Render the human-readable dashboard."""
    n_topics = len(summaries)
    n_aaa = sum(1 for s in summaries if s.aaa_runs)
    n_journal_ready = sum(1 for s in summaries if s.journal_ready)
    n_certified = sum(1 for s in summaries if s.certified)
    total_cost = sum(s.cost_usd for s in summaries)
    total_patches = sum(s.n_patches_applied for s in summaries)
    total_repaired = sum(s.n_patches_repaired for s in summaries)
    total_runs = sum(s.n_runs for s in summaries)

    lines = [
        "# Researka Multi-Topic Dashboard",
        "",
        f"**Topics attempted:** {n_topics}",
        f"**Topics at L5 (Journal-Ready):** {n_journal_ready}",
        f"**Topics with ≥1 AAA run:** {n_aaa}",
        f"**Topics with consecutive-AAA cert:** {n_certified}",
        f"**Total runs across all topics:** {total_runs}",
        f"**Cumulative LLM cost:** ${total_cost:.3f}",
        f"**Total reviewer interventions logged:** "
        f"{total_patches} applied "
        f"({total_repaired} via repair loop)",
        "",
        "## Per-Topic Status",
        "",
        "| Topic | Maturity | Best verdict | Journal | n_runs "
        "| AAA | Stage1 | S2 P1/P2 | Q2 | Words | Cost |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in sorted(
        summaries,
        key=lambda x: (
            -x.maturity_level,
            -1 if x.certified else 0,
            -len(x.aaa_runs),
            -_verdict_rank(x.best_verdict),
            x.topic,
        ),
    ):
        journal_badge = "📰" if s.journal_ready else "—"
        lines.append(
            f"| {s.topic} | {s.maturity_label} | {s.best_verdict} "
            f"| {journal_badge} | {s.n_runs} | {len(s.aaa_runs)} "
            f"| {s.stage1_pass} | {s.stage2_p1}/{s.stage2_p2} "
            f"| {s.q2_traceability_pct:.0f}% | {s.word_count:,} "
            f"| ${s.cost_usd:.3f} |"
        )
    lines += [
        "",
        "## Best Run per Topic",
        "",
    ]
    for s in sorted(
        summaries,
        key=lambda x: (
            -x.maturity_level,
            -_verdict_rank(x.best_verdict),
            x.topic,
        ),
    ):
        lines += [
            f"### {s.topic} — {s.maturity_label}",
            "",
            f"- **Best run:** `{s.best_run_id}`",
            f"- **Verdict:** {s.best_verdict}",
            f"- **Journal-Ready:** "
            f"{'yes 📰' if s.journal_ready else 'no'}",
            f"- **Cert (consecutive-AAA gate):** "
            f"{'PASS 🏆' if s.certified else 'pending'}",
            f"- **Stage-1 audit:** {s.stage1_pass}",
            f"- **Stage-2 consistency:** P1={s.stage2_p1} P2={s.stage2_p2}",
            f"- **Q2 numeric traceability:** {s.q2_traceability_pct:.0f}%",
            f"- **Grok unresolved P1:** {s.grok_unresolved_p1}",
            f"- **Word count:** {s.word_count:,}",
            f"- **LLM cost:** ${s.cost_usd:.3f}",
            f"- **Patches applied:** {s.n_patches_applied} "
            f"({s.n_patches_repaired} via repair loop)",
        ]
        if s.corpus_gaps:
            lines.append("- **Next expansion targets** "
                         "(from corpus_gaps):")
            n = max(len(s.corpus_gaps), len(s.expansion_targets))
            for i in range(min(n, 5)):  # cap at 5 per topic to keep readable
                gap = (
                    s.corpus_gaps[i] if i < len(s.corpus_gaps) else ""
                )
                tgt = (
                    s.expansion_targets[i]
                    if i < len(s.expansion_targets) else ""
                )
                lines.append(f"  - **{gap}** → {tgt}")
        if s.corpus_funnel:
            lines.append(
                f"- **Corpus funnel** "
                f"(retrieved → keep → core / background / adjacent): "
                f"{s.corpus_funnel.get('retrieved', 0)} → "
                f"{s.corpus_funnel.get('classified_keep', 0)} → "
                f"{s.corpus_funnel.get('extractable_core', 0)} / "
                f"{s.corpus_funnel.get('extractable_background', 0)} / "
                f"{s.corpus_funnel.get('extractable_adjacent', 0)}"
            )
        lines.append("")
    lines += [
        "## What this dashboard demonstrates",
        "",
        "Each topic is a separate test of the Researka generic "
        "pipeline. **No Python code differs between topics** — the "
        "only difference is `topic_packs/<topic>.toml` and the "
        "auto-discovered corpus from "
        "`scripts/seed_topic_corpus.py --topic <X>`. A topic that "
        "hits AAA via the same code path that other topics use "
        "is structural evidence of architecture portability, not "
        "topic-tuned overfitting.",
        "",
        "Per-run public bundles live in `bundles/<run-id>/` "
        "(18-file inspectable archive: paper + audit + cert + "
        "patch trail + manifest + composed README). Drop-in to "
        "OSF / Zenodo / GitHub Pages for public release.",
        "",
        "Trust-spine principle: **LLM proposes, code disposes.** "
        "Every claim, citation, and numeric in every paper traces "
        "to the source corpus AND survives an adversarial review "
        "pass with logged interventions.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    by_topic = scan_runs()
    summaries: list[TopicSummary] = []
    for topic, runs in sorted(by_topic.items()):
        summaries.append(summarize_topic(topic, runs))
    md = render_md(summaries)
    md_path = REPO / "docs" / "multi_topic_dashboard.md"
    md_path.write_text(md)
    json_path = REPO / "docs" / "multi_topic_dashboard.json"
    from dataclasses import asdict
    json_path.write_text(
        json.dumps([asdict(s) for s in summaries], indent=2),
    )
    print(
        f"Dashboard written:\n  {md_path}\n  {json_path}\n",
        file=sys.stderr,
    )
    print(
        f"Topics: {len(summaries)} | "
        f"AAA: {sum(1 for s in summaries if s.aaa_runs)} | "
        f"Certified: {sum(1 for s in summaries if s.certified)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
