# Cross-Topic Meta-Synthesis v1 Implementation Brief

Status: implementation brief only. No runtime wiring in this lane.

## Goal

Build a compact cross-topic synthesis layer that compares already-certified
topic artifacts without reusing raw extraction shortcuts or promoting weaker
topics. The output is a reader-facing map of where evidence agrees, conflicts,
or stays scoped across topics.

## Non-Goals

- No new claims from raw papers.
- No full-paper rerendering.
- No L5/L6 promotion.
- No combining SCOP/AAA-SCOP artifacts into full AAA.
- No clinical recommendation engine.

## Inputs

Use only immutable run artifacts:

- `manifest.json`
- `full_paper.final_verdict.json`
- `full_paper.certification.json` when present
- `citation_registry.json`
- `full_paper.audit.json`
- `full_paper.consistency.json`

Eligible topic inputs:

- L5/L6 full AAA artifacts for primary claims.
- L3/L4 or proposed AAA-SCOP artifacts only in a separate scoped-evidence lane.
- SHIP-BLOCKED artifacts excluded except as negative operational examples.

## Output

Recommended artifact set:

- `cross_topic_manifest.json`
- `cross_topic_matrix.json`
- `cross_topic_meta_synthesis.md`
- `cross_topic_audit.json`

Core sections:

1. Topic eligibility table.
2. Evidence class matrix by topic, directness, and outcome domain.
3. Agreement and conflict map.
4. Scoped-evidence appendix.
5. Claim boundary and non-recommendation notice.

## Data Model

`cross_topic_matrix.json` should include:

- `topics`: topic, run_id, verdict, maturity_level, certification_track
- `evidence_profile`: receipt count, high-confidence claims, tensions,
  directness mix, evidence tier mix
- `outcome_domains`: cardiometabolic, immune, cognition, muscle_function,
  frailty, mortality, safety, other
- `claims`: topic-level claim summaries copied from certified artifacts only
- `conflicts`: cross-topic tensions with source topic IDs
- `scope_flags`: SCOP/AAA-SCOP/full-AAA boundary markers

## Implementation Sequence

1. Add a read-only loader for final verdict and manifest artifacts.
2. Build eligibility classification:
   - `full_aaa_primary`: L5/L6 and `verdict=AAA`
   - `analytical_support`: L4 and `verdict=AAA`
   - `scoped_support`: SCOP/AAA-SCOP/L3
   - `excluded`: ship-blocked or missing required artifacts
3. Build deterministic topic/outcome matrix from manifest receipts.
4. Detect cross-topic conflicts only from existing topic-level claims and
   tension metadata.
5. Render markdown with strict lane separation.
6. Add audit checks that forbid unsupported cross-topic numerics and forbid
   scoped evidence from entering primary full-AAA conclusions.

## Hard Gates

- Every cross-topic sentence must cite topic/run IDs, not raw paper IDs alone.
- Any topic below L5 must be visibly scoped.
- A scoped topic cannot be used to state a global conclusion.
- A cross-topic conclusion cannot increase maturity for any source topic.
- Missing final verdict JSON excludes the topic.

## Acceptance Tests

- L5/L6 topics render in primary lane.
- L3/SCOP topics render only in scoped appendix.
- SHIP-BLOCKED topic is excluded.
- A scoped topic cannot appear in the primary conclusion.
- Missing citation registry fails the audit.
- Generated markdown contains no new numeric claim absent from input artifacts.

## Open Risks

- Outcome labels are currently coarse and may not align across topics.
- Existing manifests may omit enough claim text for useful comparison.
- Readers may mistake cross-topic synthesis for higher certainty; the renderer
  must keep maturity and certification tracks visible.
