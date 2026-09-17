"""Revise-ask bucketer measured against the live Core feedback (snapshot of _revise_reasons.json, 2026-09-17)."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from agent.publishing.revision_lane import revise_reason_bucket

LIVE_ASKS = json.loads((Path(__file__).parent / "fixtures" / "revise_asks_2026-09-17.json").read_text())


def test_live_asks_are_bucketed_below_ten_percent_unknown() -> None:
    counts = Counter(revise_reason_bucket(text) for text in LIVE_ASKS)
    assert counts["unknown"] / len(LIVE_ASKS) < 0.10, counts
    assert len(counts) >= 12  # every class in the taxonomy is exercised by real feedback


@pytest.mark.parametrize("text, bucket", [
    ("High overlap with publication 9e9f3163. Differentiate angle, findings, or population to resubmit.", "publication_overlap"),
    ("The Research Question conflates a narrow evidence brief with a broad framing; narrow the title and scope.", "scope_mismatch"),
    ("The Key Findings section is a near-verbatim duplicate of the Conclusion section.", "section_duplication"),
    ("The Evidence Landscape table provides no actual numeric findings, effect sizes, or directional claims.", "table_without_numbers"),
    ("Lai 2023 is labeled \"null\" despite the abstract reporting favorable strength findings; the direction profile is mis-coded.", "direction_coding"),
    ("The Methods do not provide an auditable rule-based path from 3,255 retrieved records to the 19 admitted sources.", "methods_accounting"),
    ("Add exact source tokens, DOI/PMID links, or evidence spans to major claims; 12/23 claims are exactly traceable.", "citation_bundle_mismatch"),
    ("Hontecillas-Prieto 2025 is coded as 'direction=null' with no extracted directional signal.", "direction_coding"),
])
def test_each_class_matches_its_canonical_ask(text: str, bucket: str) -> None:
    assert revise_reason_bucket(text) == bucket


def test_revision_lessons_prefix_top_buckets_of_trailing_window(tmp_path: Path) -> None:
    from agent.paper_writer_prompts import format_prompts_for_topic
    from agent.publishing.revision_lane import _LESSONS, REVISE_REASONS_RELPATH, revision_lessons
    import datetime as dt

    assert revision_lessons(tmp_path) == ""  # no ledger yet: prompts unchanged
    path = tmp_path / REVISE_REASONS_RELPATH
    path.parent.mkdir(parents=True)
    now = dt.datetime.now(dt.UTC)
    path.write_text(json.dumps({"reviews": [
        {"reviewed_at": (now - dt.timedelta(days=2)).isoformat(), "asks": [{"bucket": "citation_bundle_mismatch"}] * 3 + [{"bucket": "publication_overlap"}] * 5},
        {"reviewed_at": (now - dt.timedelta(days=3)).isoformat(), "asks": [{"bucket": "section_duplication"}]},
        {"reviewed_at": (now - dt.timedelta(days=90)).isoformat(), "asks": [{"bucket": "scope_mismatch"}] * 9},  # outside the window
    ]}))
    block = revision_lessons(tmp_path)
    assert block.startswith("Reviewer lessons (most frequent revision requests, last 30 days):\n- ")
    assert block.index(_LESSONS["citation_bundle_mismatch"]) < block.index(_LESSONS["section_duplication"])
    assert _LESSONS["scope_mismatch"] not in block and "overlap" not in block  # stale bucket; non-writer bucket
    prompts = format_prompts_for_topic("the drug", "drug", lessons=block)
    assert all(text.startswith(block) for text in prompts.values())
    assert len(revision_lessons(tmp_path, cap=1).splitlines()) == 3
