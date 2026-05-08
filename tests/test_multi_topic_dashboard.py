"""Tests for scripts/multi_topic_dashboard.py — Slice 4 (Wave 7).

The dashboard reads each run's final_verdict.json and surfaces the
maturity ladder + Journal-Ready + expansion targets per topic. Older
runs predating Wave 7 fall back to L? badges without crashing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import multi_topic_dashboard as dash  # noqa: E402
import certification_report as cert  # noqa: E402


def _make_run(
    base: Path, run_id: str, *, verdict_doc: dict,
    audit: dict | None = None, manifest: dict | None = None,
) -> Path:
    """Synthesize a minimal run dir that the dashboard scanner accepts."""
    d = base / "runs" / run_id
    d.mkdir(parents=True)
    (d / "full_paper.md").write_text("# Paper\n")
    (d / "full_paper.final_verdict.json").write_text(
        json.dumps(verdict_doc),
    )
    if audit is not None:
        (d / "full_paper.audit.json").write_text(json.dumps(audit))
    if manifest is not None:
        (d / "manifest.json").write_text(json.dumps(manifest))
    return d


def _surface_clean_paper() -> str:
    def words(n: int) -> str:
        return " ".join(f"word{i}" for i in range(n))
    return "\n\n".join((
        f"## Abstract\n\n{words(150)}",
        f"## Introduction\n\n{words(400)}",
        f"## Background\n\n{words(300)}",
        "## Quantitative Evidence Index\n\n"
        "| Study | Endpoint | Arm | Value | Type | Statistic |\n"
        "|---|---|---|---|---|---|\n"
        "| Smith 2024 | fasting glucose | control | 89 mg/dL | mg/dL | — |",
        f"## Methods\n\n{words(300)}",
        f"## Results\n\n{words(500)}",
        f"## Cross-Domain Synthesis\n\n{words(850)}",
        f"## Discussion\n\n{words(800)}",
        f"## Limitations\n\n{words(250)}",
        f"## Conclusion\n\n{words(250)}",
    ))


def test_summarize_topic_pulls_wave7_fields(tmp_path, monkeypatch):
    """Dashboard reads maturity_level / journal_ready / corpus_gaps
    from final_verdict.json."""
    monkeypatch.setattr(dash, "REPO", tmp_path)
    run = _make_run(
        tmp_path, "synthesis-metformin-v06-AAA1-2026-05-05T10-00-00Z",
        verdict_doc={
            "verdict": "AAA",
            "stage1_pass_rate": "13/13",
            "stage2_p1": 0, "stage2_p2": 0,
            "grok_unresolved_p1": 0,
            "maturity_level": 5,
            "maturity_label": "L5 — JOURNAL-READY",
            "journal_ready": True,
            "corpus_gaps": [],
            "expansion_targets": [],
        },
        manifest={"total_words": 11000, "total_cost_usd": 0.20},
    )
    (run / "full_paper.md").write_text(_surface_clean_paper())
    summary = dash.summarize_topic("metformin", [run])
    assert summary.maturity_level == 5
    assert summary.maturity_label == "L5 — JOURNAL-READY"
    assert summary.journal_ready is True
    assert summary.corpus_gaps == ()
    assert summary.expansion_targets == ()


def test_summarize_topic_promotes_consecutive_l5_to_l6(
    tmp_path, monkeypatch,
):
    """Dashboard surfaces topic-level L6 when consecutive cert says so."""
    monkeypatch.setattr(dash, "REPO", tmp_path)
    for suffix in ("AAA1-2026-05-05T10-00-00Z",
                   "AAA2-2026-05-05T11-00-00Z"):
        run = _make_run(
            tmp_path, f"synthesis-topic-v06-{suffix}",
            verdict_doc={
                "verdict": "AAA",
                "stage1_pass_rate": "14/14",
                "stage2_p1": 0, "stage2_p2": 0,
                "grok_unresolved_p1": 0,
                "maturity_level": 5,
                "maturity_label": "L5 — JOURNAL-READY",
                "journal_ready": True,
            },
        )
        (run / "full_paper.md").write_text(_surface_clean_paper())
    monkeypatch.setattr(
        cert, "certify_consecutive",
        lambda paths: {
            "certified": True,
            "l6_reproducibly_journal_ready": True,
            "maturity_level": 6,
            "maturity_label": "L6 — REPRODUCIBLY JOURNAL-READY",
        },
    )
    summary = dash.summarize_topic("topic", list((tmp_path / "runs").iterdir()))
    assert summary.certified is True
    assert summary.maturity_level == 6
    assert summary.maturity_label == "L6 — REPRODUCIBLY JOURNAL-READY"
    assert summary.journal_ready is True


def test_summarize_topic_caps_stale_l5_when_surface_fails(
    tmp_path, monkeypatch,
):
    """Dashboard must not count old L5 verdict files as
    Journal-Ready when the rendered paper fails the new surface gate."""
    monkeypatch.setattr(dash, "REPO", tmp_path)
    run = _make_run(
        tmp_path, "synthesis-topic-v06-AAA1-2026-05-05T10-00-00Z",
        verdict_doc={
            "verdict": "AAA",
            "stage1_pass_rate": "13/13",
            "stage2_p1": 0, "stage2_p2": 0,
            "grok_unresolved_p1": 0,
            "maturity_level": 5,
            "maturity_label": "L5 — JOURNAL-READY",
            "journal_ready": True,
        },
    )
    (run / "full_paper.md").write_text(
        "## Introduction\n\n"
        "This paper evaluates the topic through accepted receipts.\n",
    )
    summary = dash.summarize_topic("topic", [run])
    assert summary.journal_ready is False
    assert summary.maturity_level == 4
    assert summary.maturity_label == "L4 — ANALYTICALLY CERTIFIED"


def test_summarize_topic_normalizes_old_l4_label(tmp_path, monkeypatch):
    monkeypatch.setattr(dash, "REPO", tmp_path)
    run = _make_run(
        tmp_path, "synthesis-topic-v06-AAA1-2026-05-05T10-00-00Z",
        verdict_doc={
            "verdict": "AAA",
            "maturity_level": 4,
            "maturity_label": "L4 — AAA",
            "journal_ready": False,
        },
    )
    summary = dash.summarize_topic("topic", [run])
    assert summary.maturity_label == "L4 — ANALYTICALLY CERTIFIED"


def test_summarize_topic_falls_back_for_pre_wave7_runs(
    tmp_path, monkeypatch,
):
    """Old verdict.json without Wave 7 fields → maturity_level=0,
    label='L? — pre-Wave-7', journal_ready=False (no crash)."""
    monkeypatch.setattr(dash, "REPO", tmp_path)
    run = _make_run(
        tmp_path, "synthesis-aspirin-v06-OLD-2026-05-04T10-00-00Z",
        verdict_doc={
            "verdict": "AAA",
            "stage1_pass_rate": "13/13",
            "stage2_p1": 0, "stage2_p2": 0,
            "grok_unresolved_p1": 0,
        },
        manifest={"total_words": 7000, "total_cost_usd": 0.15},
    )
    summary = dash.summarize_topic("aspirin", [run])
    assert summary.maturity_level == 0
    assert "pre-Wave-7" in summary.maturity_label
    assert summary.journal_ready is False


def test_summarize_topic_carries_expansion_targets(
    tmp_path, monkeypatch,
):
    """A sub-AAA topic carries the corpus_gaps / expansion_targets
    so the dashboard can show 'next expansion targets'."""
    monkeypatch.setattr(dash, "REPO", tmp_path)
    run = _make_run(
        tmp_path, "synthesis-statins-v06-PARTIAL-2026-05-05T11-00-00Z",
        verdict_doc={
            "verdict": "Trust-Spine Pass",
            "stage1_pass_rate": "13/13",
            "stage2_p1": 0, "stage2_p2": 0,
            "grok_unresolved_p1": 0,
            "maturity_level": 2,
            "maturity_label": "L2 — PARTIAL",
            "journal_ready": False,
            "corpus_gaps": [
                "Receipts: 2/10 (short by 8)",
                "High-confidence claims: 4/50 (short by 46)",
            ],
            "expansion_targets": [
                "Add ≥8 more topic-fit receipts",
                "Re-run extraction or expand corpus",
            ],
        },
        manifest={"total_words": 8500, "total_cost_usd": 0.18},
    )
    summary = dash.summarize_topic("statins", [run])
    assert summary.maturity_level == 2
    assert len(summary.corpus_gaps) == 2
    assert len(summary.expansion_targets) == 2
    assert any("Receipts:" in g for g in summary.corpus_gaps)


# ---------- render_md ------------------------------------------------

def _summary(**kw):
    """Helper: build a TopicSummary with sensible defaults."""
    base = dict(
        topic="X", n_runs=1, best_run_id="r1",
        best_verdict="AAA", aaa_runs=("r1",),
        stage1_pass="13/13",
    )
    base.update(kw)
    return dash.TopicSummary(**base)


def test_render_md_includes_maturity_column():
    """Per-topic table now exposes a Maturity column with the
    L0-L5 badge."""
    s = _summary(
        maturity_level=5, maturity_label="L5 — JOURNAL-READY",
        journal_ready=True,
    )
    md = dash.render_md([s])
    assert "Maturity" in md
    assert "L5 — JOURNAL-READY" in md
    assert "📰" in md  # Journal-Ready badge


def test_render_md_surfaces_journal_ready_count():
    """Top-line summary counts L5 topics (Topics at L5)."""
    s_l5 = _summary(
        topic="A", maturity_level=5,
        maturity_label="L5 — JOURNAL-READY", journal_ready=True,
    )
    s_l3 = _summary(
        topic="B", maturity_level=3, maturity_label="L3 — FLOOR-MET",
        journal_ready=False,
    )
    md = dash.render_md([s_l5, s_l3])
    assert "Topics at L5 (Journal-Ready):** 1" in md


def test_render_md_lists_expansion_targets_for_subaaa_topics():
    """Per-topic detail section emits the expansion-target list
    when corpus_gaps is non-empty."""
    s = _summary(
        topic="rapamycin", best_verdict="Trust-Spine Pass",
        maturity_level=2, maturity_label="L2 — PARTIAL",
        journal_ready=False,
        corpus_gaps=("Receipts: 5/10 (short by 5)",),
        expansion_targets=("Add ≥5 more receipts",),
    )
    md = dash.render_md([s])
    assert "Next expansion targets" in md
    assert "Receipts: 5/10" in md
    assert "Add ≥5 more receipts" in md


def test_render_md_orders_topics_by_maturity_descending():
    """Higher-maturity topics appear first in the table."""
    a = _summary(topic="zeta", maturity_level=5,
                 maturity_label="L5 — JOURNAL-READY", journal_ready=True)
    b = _summary(topic="alpha", maturity_level=2,
                 maturity_label="L2 — PARTIAL", journal_ready=False)
    md = dash.render_md([b, a])
    assert md.find("zeta") < md.find("alpha")


def test_render_md_surfaces_corpus_funnel():
    """When a topic has run the calibrated pipeline (corpus_funnel
    populated), the per-topic detail section must show the funnel
    (Slice 6 step 4d wiring)."""
    s = _summary(
        topic="rapamycin", maturity_level=3,
        maturity_label="L3 — FLOOR-MET", journal_ready=False,
        corpus_funnel={
            "retrieved": 5000, "classified_keep": 3500,
            "classified_drop": 1500,
            "extractable_core": 2200,
            "extractable_background": 1300,
            "extractable_adjacent": 0,
        },
    )
    md = dash.render_md([s])
    assert "Corpus funnel" in md
    assert "5000" in md
    assert "3500" in md
    assert "2200" in md and "1300" in md  # core / background
    assert "core / background / adjacent" in md


def test_render_md_omits_funnel_when_no_data():
    """A topic that hasn't run the calibrated pipeline yet has
    empty corpus_funnel — dashboard skips the funnel line cleanly."""
    s = _summary(
        topic="aspirin", maturity_level=4,
        maturity_label="L4 — AAA", journal_ready=False,
        corpus_funnel={},
    )
    md = dash.render_md([s])
    assert "Corpus funnel" not in md
