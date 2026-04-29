# Synthesis Quality Checklist — 7 Questions

This checklist is loaded by `agent/synthesis.py` and used in two places:

1. **Build-time validation** — every check runs deterministically (or
   with a small LLM call) against the rendered `paper_synthesis.md`,
   producing a `QualityCheckResult`. The audit aggregates results into
   `synthesis_quality_audit.json` with a 0-10 score.

2. **SPAR judges' rubric prompt** — the auditor and skeptic are
   primed with these questions when reviewing a synthesis paper. The
   judges score each question pass/fail and surface failures as
   `flagged_claims`.

The 7 questions are keyed to specific papers from the Quality
Reference Corpus (`docs/quality-reference/metformin/README.md`). They
encode the lessons each reference paper teaches without copying their
text. Day 10 ship criterion: ≥6 of 7 must pass for an `accept_*`
verdict on the synthesis layer.

---

## Q1 — Borderline-p hedging (keyed to Konopka 2019)

**Question:** Does the paper round any p-value `≥ 0.05` to "significant"
or use "demonstrated"/"showed" language for an underpowered finding?

**Pass criterion:** No occurrence of "significant" / "demonstrated" /
"showed" / "established" within 80 chars of any p-value where
`p ≥ 0.05` in the cited receipts.

**Why this matters:** Konopka 2019 reports `p = 0.08` for VO₂max
attenuation. Rounding that to "metformin attenuated VO₂max
significantly" is the most common synthesis-paper failure mode.

**Implementation:** Deterministic regex scan of `paper_synthesis.md`
against every borderline p-value in the receipt set.

## Q2 — Null-result acknowledgment (keyed to Witham 2025, MET-PREVENT)

**Question:** When a primary endpoint is null in the receipt set, does
the synthesis paper acknowledge that null directly?

**Pass criterion:** For every receipt with `effect_direction == "null"`,
the synthesis paper's Synthesis or Tensions section contains "no
significant difference" / "did not improve" / "null" / "no benefit"
within the same paragraph as the receipt's citation.

**Why this matters:** MET-PREVENT 2025 is a clean null on 4-m walk
speed. Synthesis papers that bury the null in mechanism prose are
overclaiming.

**Implementation:** Deterministic — find every null-receipt citation
in the paper, scan the surrounding paragraph for null-acknowledgment
phrases.

## Q3 — Direct vs indirect separation (keyed to Mohammed 2021)

**Question:** Does the paper interleave direct trial findings with
mechanistic / animal / in-vitro findings within the same paragraph
without a directness-shift transition?

**Pass criterion:** For every paragraph that anchors on receipts of
mixed directness (some `direct`, some `mechanistic` or `indirect`),
the paragraph must contain a transition phrase: "Mechanistically",
"In vitro", "Preclinically", "In contrast", "However", or "By
contrast,".

**Why this matters:** Mohammed 2021's framing — "indirect via
metabolic effects" vs "direct effects on aging" — is the discipline
this question enforces.

**Implementation:** Per-paragraph anchor inspection + phrase scan.

## Q4 — Replication / validation gap (keyed to Kulkarni 2018, MILES)

**Question:** When the synthesis thesis is anchored on a single trial
or single small-cohort receipt, does the Limitations section name the
replication gap?

**Pass criterion:** If the thesis references ≤2 distinct receipts AND
those receipts have `n_claims ≤ 4`, the Limitations section must
include "remains to be validated" / "single-trial" / "single-cohort"
/ "replication required" / "external validation" / "small sample".

**Why this matters:** MILES 2018 is small-N (n=14), and even for its
positive mechanistic findings the paper acknowledges "remain to be
validated in other tissues and study designs".

**Implementation:** Receipt-count + claims-count check on the thesis,
then phrase scan in Limitations.

## Q5 — Healthspan inference discipline (keyed to Mohammed 2021)

**Question:** Does the paper claim healthspan / longevity benefit when
the receipt set contains only mechanistic or short-duration evidence?

**Pass criterion:** If NO receipt in the set has both
`outcome_class == "longevity"` AND `directness == "direct"` AND
`evidence_tier in {"A1", "A2"}`, the synthesis paper must NOT
contain phrases "extends lifespan", "longevity benefit",
"increases healthspan", or "geroprotective" without a "may"
modifier or a "remains unproven" / "indirect" qualifier nearby.

**Why this matters:** Mohammed 2021's central framing — that
biological activity in aging-relevant pathways does not equal
demonstrated human healthspan extension — is the bar.

**Implementation:** Receipt-set inspection + phrase scan with
qualifier-proximity rule.

## Q6 — Adverse event surfacing (keyed to Witham 2025, MET-PREVENT)

**Question:** When the receipt set includes a safety / tolerability
signal, does the synthesis paper surface it in the Tensions or
Limitations section?

**Pass criterion:** For every receipt with `outcome_class == "safety"`,
the synthesis paper must reference that receipt in Tensions OR
Limitations section.

**Why this matters:** MET-PREVENT 2025 reported "metformin was poorly
tolerated in this population" — a load-bearing finding that synthesis
papers routinely drop because the efficacy null is what gets headlines.

**Implementation:** Receipt iteration + section anchor check.

## Q7 — Numeric fidelity (keyed to Walton 2019, MASTERS)

**Question:** Does every numeric token in the synthesis paper appear
verbatim in at least one receipt's `claim_graph.json` or
`citation_traces.json`?

**Pass criterion:** Zero novel numerics. Build-time validator already
enforces this at write time, but the audit re-checks against the
final rendered markdown to catch any path that bypassed validation.

**Why this matters:** Walton 2019 (MASTERS) sets the bar for numeric
precision. Synthesis papers that round, dramatize, or fabricate
numerics undermine the entire trust spine.

**Implementation:** Tokenize all numerics in `paper_synthesis.md`,
check membership in the union of all receipts' numeric sets.

---

## Aggregate score formula

```
score_out_of_10 = (passed_count / total_count) * 10
```

**Day 10 ship criterion:** `score ≥ 8.5` AND no failure on Q1, Q3, Q5
(the three trust-spine-load-bearing questions). Q2/Q4/Q6/Q7 failures
are documented in the audit but don't block ship.

The audit JSON shape (saved to `synthesis_quality_audit.json`):

```json
{
  "submission_id": "metformin-001-...-abcd",
  "score": 9.0,
  "checks": [
    {
      "question_id": "Q1-konopka-p008-hedging",
      "question": "Does the paper round any p-value...",
      "passed": true,
      "detail": "No 'significant' within 80 chars of p>=0.05.",
      "excerpt": null
    },
    ...
  ],
  "notes": "All 7 questions evaluated; ..."
}
```
