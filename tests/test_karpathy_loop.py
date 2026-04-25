"""Tests for scripts/karpathy_loop.py — snapshot, diff, report subcommands."""

import json
from pathlib import Path
from scripts.karpathy_loop import (
    study_overlap,
    direction_agreement,
    limitation_overlap,
    quantitative_fidelity,
    bundle_contract_score,
    audit_trail_score,
    composite_score,
    score_topic,
    load_topics,
    load_fixtures,
    _classify_direction,
    _direction_distance,
    _normalize_doi,
    _normalize_token,
    _jaccard_similarity,
    main,
)


# ── Fixture data ──────────────────────────────────────────────────────────────

_GOLD = {
    "included_dois": ["10.1234/test1", "10.1234/test2", "10.5678/test3"],
    "conclusion_direction": "positive_with_caveats",
    "limitations": [
        "small sample size",
        "short duration",
        "lack of placebo control",
    ],
}

_DRAFT = {
    "canonical_term": "metformin",
    "canonical_topic": "metformin aging older adults",
    "sections": {
        "Key Findings": (
            "Three studies with 45 participants showed significant improvement "
            "in 85% of cases. Doses ranged from 5 mg to 10 mg over 12 weeks."
        ),
        "Conclusion": (
            "Results suggest positive outcomes but preliminary findings require "
            "confirmation in larger trials."
        ),
        "Limitations": (
            "Limited by small sample size and short duration. "
            "Mixed results across heterogeneous populations."
        ),
    },
    "source_bundle": [
        {
            "doi": "10.1234/test1",
            "title": "Metformin trial in older adults",
            "excerpt": "45 participants showed 85% improvement with metformin in older adults",
            "role": "published_results",
            "directness": "direct",
            "evidence_tier": "Tier A1 direct aging evidence",
        },
        {
            "doi": "10.1234/test2",
            "title": "Metformin systematic review in aging",
            "excerpt": "5 mg dose over 12 weeks in metformin aging studies",
            "role": "meta_analysis",
            "directness": "indirect",
            "evidence_tier": "Tier B supporting human evidence",
        },
        {
            "doi": "10.5678/test3",
            "title": "Metformin protocol in frail older adults",
            "excerpt": "10 mg dose over 12 weeks planned for metformin protocol",
            "role": "published_protocol",
            "directness": "indirect",
            "evidence_tier": "Tier C protocol/mechanistic support",
        },
    ],
    "bridge": {
        "mode": "moa_spar",
        "moa": {"reference_models": ["mimo-v2.5-pro", "mistralai/mistral-small-2603", "google/gemma-4-31b-it"]},
        "spar": {"approved": True, "issues": []},
    },
    "human_peer_review": False,
}

_DRAFT_NO_FINDINGS = {
    "canonical_term": "metformin",
    "canonical_topic": "metformin aging older adults",
    "sections": {
        "Key Findings": "",
        "Conclusion": "Insufficient evidence.",
        "Limitations": "No limitations noted.",
    },
    "source_bundle": [],
}


# ── Unit tests: helper functions ──────────────────────────────────────────────

class TestNormalizeDoi:
    def test_strips_https_prefix(self):
        assert _normalize_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_strips_http_prefix(self):
        assert _normalize_doi("http://doi.org/10.1234/test") == "10.1234/test"

    def test_strips_doi_prefix(self):
        assert _normalize_doi("doi:10.1234/test") == "10.1234/test"

    def test_lowercases(self):
        assert _normalize_doi("10.1234/ABC") == "10.1234/abc"

    def test_strips_whitespace(self):
        assert _normalize_doi("  10.1234/test  ") == "10.1234/test"


class TestClassifyDirection:
    def test_positive_keywords(self):
        assert _classify_direction("This demonstrates efficacy and supports improvement") == "positive"

    def test_negative_evidence(self):
        assert _classify_direction("no evidence of benefit, ineffective") in ("negative", "negative_with_caveats")

    def test_mixed(self):
        text = "suggests improvement but no evidence of benefit"
        result = _classify_direction(text)
        assert result in ("mixed", "negative_with_caveats", "positive_with_caveats")

    def test_caveats(self):
        # "promising" is in CAVEAT_KW, "limited" and "preliminary" are too
        # No positive keywords → caveat_count > 2 → "mixed"
        assert _classify_direction("promising but limited preliminary data") == "mixed"

    def test_insufficient(self):
        assert _classify_direction("The weather was nice today") == "insufficient_evidence"


class TestDirectionDistance:
    def test_same(self):
        assert _direction_distance("positive", "positive") == 0.0

    def test_off_by_one(self):
        assert _direction_distance("positive", "positive_with_caveats") == 0.5

    def test_completely_different(self):
        assert _direction_distance("negative", "positive") == 1.0

    def test_unknown_label(self):
        assert _direction_distance("nonexistent", "positive") == 1.0


class TestNormalizeToken:
    def test_expands_abbreviation(self):
        assert _normalize_token("rcts") == "trial"

    def test_expands_plural(self):
        assert _normalize_token("studies") == "study"

    def test_passes_unknown(self):
        assert _normalize_token("xyz") == "xyz"


class TestJaccardSimilarity:
    def test_identical(self):
        assert _jaccard_similarity("small sample size", "small sample size") == 1.0

    def test_partial_overlap(self):
        result = _jaccard_similarity("limited by small sample", "small sample size")
        assert result >= 0.5

    def test_no_overlap(self):
        assert _jaccard_similarity("totally unrelated text", "small sample size") == 0.0

    def test_empty_target(self):
        assert _jaccard_similarity("some text", "") == 0.0


# ── Unit tests: scoring functions ─────────────────────────────────────────────

class TestStudyOverlap:
    def test_full_overlap(self):
        assert study_overlap(_DRAFT, _GOLD) > 0.9

    def test_no_sources(self):
        assert study_overlap(_DRAFT_NO_FINDINGS, _GOLD) == 0.0

    def test_no_gold_dois(self):
        gold = {**_GOLD, "included_dois": []}
        assert study_overlap(_DRAFT, gold) == 0.0

    def test_partial_overlap(self):
        gold = {**_GOLD, "included_dois": ["10.1234/test1", "10.1234/missing"]}
        result = study_overlap(_DRAFT, gold)
        assert 0.4 < result < 0.6


class TestDirectionAgreement:
    def test_close_match(self):
        result = direction_agreement(_DRAFT, _GOLD)
        assert result >= 0.5

    def test_empty_conclusion(self):
        draft = {"sections": {"Key Findings": "", "Conclusion": ""}}
        gold = {"conclusion_direction": "insufficient_evidence"}
        result = direction_agreement(draft, gold)
        assert result == 1.0


class TestLimitationOverlap:
    def test_majority_matched(self):
        result = limitation_overlap(_DRAFT, _GOLD)
        assert result >= 0.5

    def test_no_gold_limitations(self):
        gold = {**_GOLD, "limitations": []}
        assert limitation_overlap(_DRAFT, gold) == 0.0

    def test_no_draft_limitations(self):
        draft = {"sections": {"Limitations": ""}}
        assert limitation_overlap(draft, _GOLD) == 0.0


class TestQuantitativeFidelity:
    def test_supported_numbers(self):
        result = quantitative_fidelity(_DRAFT, _GOLD)
        assert result > 0.5

    def test_no_findings(self):
        assert quantitative_fidelity(_DRAFT_NO_FINDINGS, _GOLD) == 0.5

    def test_perfect_support(self):
        draft = {
            "sections": {"Key Findings": "showed 85% improvement in 45 participants"},
            "source_bundle": [{"excerpt": "85% improvement in 45 participants"}],
        }
        result = quantitative_fidelity(draft, _GOLD)
        assert result == 1.0


class TestCompositeScore:
    def test_weighted_sum(self):
        result = composite_score(_DRAFT, _GOLD)
        expected = (
            0.10 * study_overlap(_DRAFT, _GOLD)
            + 0.25 * quantitative_fidelity(_DRAFT, _GOLD)
            + 0.20 * direction_agreement(_DRAFT, _GOLD)
            + 0.15 * limitation_overlap(_DRAFT, _GOLD)
            + 0.20 * bundle_contract_score(_DRAFT, _GOLD)
            + 0.10 * audit_trail_score(_DRAFT, _GOLD)
        )
        assert abs(result - expected) < 1e-6

    def test_range(self):
        result = composite_score(_DRAFT, _GOLD)
        assert 0.0 <= result <= 1.0


class TestBundleContractScore:
    def test_clean_bundle_scores_high(self):
        assert bundle_contract_score(_DRAFT, _GOLD) == 1.0

    def test_empty_bundle_scores_zero(self):
        assert bundle_contract_score(_DRAFT_NO_FINDINGS, _GOLD) == 0.0


class TestAuditTrailScore:
    def test_complete_bridge_scores_high(self):
        assert audit_trail_score(_DRAFT, _GOLD) == 1.0

    def test_unresolved_issue_requires_notes(self):
        draft = {
            "bridge": {
                "mode": "moa_spar",
                "moa": {"reference_models": ["mimo-v2.5-pro"]},
                "spar": {"approved": False, "issues": ["strict eligibility not met"]},
            },
            "markdown": "Adjudication: structured model adjudication\nHuman peer review: false",
        }
        assert audit_trail_score(draft, _GOLD) == 0.8
        draft["markdown"] += "\n\n## Adjudication Notes\n- strict eligibility not met"
        assert audit_trail_score(draft, _GOLD) == 1.0


class TestScoreTopic:
    def test_returns_all_keys(self):
        result = score_topic(_DRAFT, _GOLD)
        expected_keys = {"study_overlap", "direction_agreement", "limitation_overlap", "quantitative_fidelity", "bundle_contract_score", "audit_trail_score", "composite_score"}
        assert set(result.keys()) == expected_keys

    def test_values_are_rounded(self):
        result = score_topic(_DRAFT, _GOLD)
        for v in result.values():
            assert isinstance(v, float)
            # Verify rounding to 4 decimal places
            assert v == round(v, 4)


# ── Integration tests: subcommands via main() ────────────────────────────────

class TestSnapshotSubcommand:
    def test_creates_snapshot_file(self, tmp_path: Path, monkeypatch):
        topics_dir = tmp_path / "topics"
        fixtures_dir = tmp_path / "fixtures"
        output_dir = tmp_path / "snapshots"
        topics_dir.mkdir()
        fixtures_dir.mkdir()
        output_dir.mkdir()

        # Write a minimal topic + fixture
        (topics_dir / "test_topic.json").write_text(json.dumps({
            "included_dois": ["10.1234/t1"],
            "conclusion_direction": "positive",
            "limitations": ["small study"],
        }))
        (fixtures_dir / "test_topic_draft.json").write_text(json.dumps({
            "sections": {
                "Key Findings": "demonstrates efficacy",
                "Conclusion": "promising results",
                "Limitations": "limited by small study",
            },
            "source_bundle": [
                {"doi": "10.1234/t1", "excerpt": "demonstrates efficacy"},
            ],
        }))

        exit_code = main([
            "snapshot",
            "--topics-dir", str(topics_dir),
            "--fixtures-dir", str(fixtures_dir),
            "--output-dir", str(output_dir),
        ])

        assert exit_code == 0
        snapshots = list(output_dir.glob("*.json"))
        assert len(snapshots) == 1
        data = json.loads(snapshots[0].read_text())
        assert "topics" in data
        assert "test_topic" in data["topics"]
        assert "composite_score" in data["topics"]["test_topic"]
        assert "averages" in data

    def test_no_matching_pairs_exits_error(self, tmp_path: Path):
        topics_dir = tmp_path / "topics"
        fixtures_dir = tmp_path / "fixtures"
        output_dir = tmp_path / "snapshots"
        topics_dir.mkdir()
        fixtures_dir.mkdir()
        output_dir.mkdir()

        (topics_dir / "alpha.json").write_text(json.dumps({"included_dois": [], "conclusion_direction": "mixed", "limitations": []}))
        (fixtures_dir / "beta_draft.json").write_text(json.dumps({"sections": {}, "source_bundle": []}))

        exit_code = main([
            "snapshot",
            "--topics-dir", str(topics_dir),
            "--fixtures-dir", str(fixtures_dir),
            "--output-dir", str(output_dir),
        ])
        assert exit_code == 1


class TestDiffSubcommand:
    def test_produces_correct_deltas(self, tmp_path: Path, monkeypatch):
        before = tmp_path / "before.json"
        after = tmp_path / "after.json"
        diff_out = tmp_path / "diffs"
        diff_out.mkdir()

        before.write_text(json.dumps({
            "timestamp": "2026-01-01T00:00:00Z",
            "git_sha": "abc1234",
            "topics": {
                "topic_a": {
                    "composite_score": 0.5,
                    "study_overlap": 0.6,
                    "direction_agreement": 0.7,
                    "limitation_overlap": 0.8,
                    "quantitative_fidelity": 0.4,
                    "bundle_contract_score": 0.3,
                    "audit_trail_score": 0.2,
                }
            },
            "averages": {
                "composite_score": 0.5,
                "study_overlap": 0.6,
                "direction_agreement": 0.7,
                "limitation_overlap": 0.8,
                "quantitative_fidelity": 0.4,
                "bundle_contract_score": 0.3,
                "audit_trail_score": 0.2,
            },
        }))
        after.write_text(json.dumps({
            "timestamp": "2026-01-02T00:00:00Z",
            "git_sha": "def5678",
            "topics": {
                "topic_a": {
                    "composite_score": 0.6,
                    "study_overlap": 0.7,
                    "direction_agreement": 0.7,
                    "limitation_overlap": 0.9,
                    "quantitative_fidelity": 0.5,
                    "bundle_contract_score": 0.8,
                    "audit_trail_score": 0.2,
                }
            },
            "averages": {
                "composite_score": 0.6,
                "study_overlap": 0.7,
                "direction_agreement": 0.7,
                "limitation_overlap": 0.9,
                "quantitative_fidelity": 0.5,
                "bundle_contract_score": 0.8,
                "audit_trail_score": 0.2,
            },
        }))

        # Redirect DIFFS_DIR so diff writes to tmp_path
        monkeypatch.setattr("scripts.karpathy_loop.DIFFS_DIR", diff_out)

        exit_code = main(["diff", str(before), str(after)])
        assert exit_code == 0

        diff_files = list(diff_out.glob("*_diff.json"))
        assert len(diff_files) == 1
        data = json.loads(diff_files[0].read_text())
        assert data["before_sha"] == "abc1234"
        assert data["after_sha"] == "def5678"
        assert data["topics"]["topic_a"]["composite_score"] == 0.1
        assert data["topics"]["topic_a"]["study_overlap"] == 0.1
        assert data["topics"]["topic_a"]["direction_agreement"] == 0.0
        assert data["topics"]["topic_a"]["bundle_contract_score"] == 0.5
        assert data["topics"]["topic_a"]["audit_trail_score"] == 0.0
        assert data["average_delta"]["composite_score"] == 0.1


class TestReportSubcommand:
    def test_outputs_report(self, tmp_path: Path, monkeypatch):
        diff_file = tmp_path / "test_diff.json"
        diff_file.write_text(json.dumps({
            "before_sha": "aaa1111",
            "after_sha": "bbb2222",
            "before_ts": "2026-01-01T00:00:00Z",
            "after_ts": "2026-01-02T00:00:00Z",
            "topics": {
                "topic_x": {
                    "composite_score": 0.05,
                    "study_overlap": 0.1,
                    "quantitative_fidelity": 0.02,
                    "direction_agreement": 0.0,
                    "limitation_overlap": -0.03,
                    "bundle_contract_score": 0.25,
                    "audit_trail_score": 0.1,
                }
            },
            "average_delta": {
                "composite_score": 0.05,
                "study_overlap": 0.1,
                "quantitative_fidelity": 0.02,
                "direction_agreement": 0.0,
                "limitation_overlap": -0.03,
                "bundle_contract_score": 0.25,
                "audit_trail_score": 0.1,
            },
        }))

        exit_code = main(["report", str(diff_file)])
        assert exit_code == 0


# ── Loader tests against real fixtures ────────────────────────────────────────

class TestLoaders:
    def test_load_topics_returns_all_fifteen(self):
        topics_dir = Path(__file__).parent / "golden" / "topics"
        topics = load_topics(topics_dir)
        assert len(topics) == 15

    def test_load_fixtures_returns_all_fifteen(self):
        fixtures_dir = Path(__file__).parent / "golden" / "fixtures"
        fixtures = load_fixtures(fixtures_dir)
        assert len(fixtures) == 15

    def test_scoring_no_errors_on_real_data(self):
        """Verify scoring runs without error on all real topic/fixture pairs."""
        topics_dir = Path(__file__).parent / "golden" / "topics"
        fixtures_dir = Path(__file__).parent / "golden" / "fixtures"
        topics = load_topics(topics_dir)
        fixtures = load_fixtures(fixtures_dir)
        shared = set(topics) & set(fixtures)
        assert len(shared) == 15
        for slug in shared:
            result = score_topic(fixtures[slug], topics[slug])
            for key in ("study_overlap", "direction_agreement", "limitation_overlap", "quantitative_fidelity", "bundle_contract_score", "audit_trail_score", "composite_score"):
                assert 0.0 <= result[key] <= 1.0
