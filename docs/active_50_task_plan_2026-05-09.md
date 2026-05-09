# Active 50+ Task Plan - 2026-05-09

## Operating Rule
Reload this file after compaction. Work step by step. Double-audit each completed
step. Commit and deploy only from a clean, tested state.

## Sprint Mission
Research Agent Bot must produce world-class research papers. The 48-72 hour
horizon is rapamycin paper quality, not Researka platform engineering.

## Out Of Scope For This Sprint
- Researka public reader / provenance UI.
- DW/OSF integration.
- Topic-pack auto-generator expansion.
- Cross-topic meta-synthesis V2, except release-green correctness fixes.
- Methodology paper about Researka.

## Release-Green Cleanup
1. Fix cross-topic auto-selection to use only explicit certification tracks and
   complete 14/14 audits. Status: done in current branch.
2. Regenerate cross-topic meta-synthesis after corrected selection. Status: done
   in current branch; contradictions now 3, not stale 5.
3. Raise LOC ceiling with `DECISIONS.md` rationale and no per-file cap change.
   Status: done in current branch.
4. Refresh `AGENTS.md` and `PROJECT_STATE.md` to current mission. Status: done
   in current branch.
5. Run focused tests for cross-topic and LOC gates. Status: done in current branch.
6. Run full pytest, ruff, diff check, and secret scan. Status: done in current
   branch; latest full pytest `2369 passed`.
7. Commit, push, sync VPS `/opt` and `/root`, verify service active and endpoint
   503. Status: done through deployed baseline `05b962f5`; repeat after each
   qualification-rescue checkpoint.

## Rapamycin World-Class Paper Sprint

### Phase 1 - Diagnostic: Journal-Grade Gap Analysis
8. Read the current rapamycin L6 paper end-to-end.
9. Compare against recent senior rapamycin/mTOR aging reviews.
10. Pull or identify 3 recent systematic/review papers from PubMed or local corpus.
11. Document concrete gaps in `docs/paper_quality/rapamycin_gap_analysis.md`.
12. Identify 6-8 desk-reject weaknesses by impact and fixability.
13. Decide what is realistically fixable in 72 hours.

### Phase 2 - Corpus Depth
14. Audit rapamycin retrieval funnel: retrieved, classified, extracted, receipts.
    Status: done; retrieval is not the active bottleneck.
15. Identify bottleneck: retrieval, classification, extraction, or receipt gating.
    Status: done; bottleneck is qualification/binding, not topic-pack retrieval.
16. Expand `topic_packs/rapamycin.toml` retrieval terms if bottleneck is retrieval.
    Status: deferred; current candidate pool is already large enough.
17. Add canonical/field anchor IDs only when source-backed and topic-pack suitable.
    Status: deferred until qualification ceiling is reached.
18. Re-run rapamycin retrieval with target >=150 unique candidates. Status:
    satisfied by existing corpus candidate count.
19. Re-run extraction with target >=60 successful extraction candidates. Status:
    partially satisfied; quant artifacts exist for 287 files.
20. Re-run classification with target >=40 on-thesis receipts. Status:
    done; runner-admitted receipts are now 40, up from the 16 ceiling.
21. If receipts stay <40, fix the actual bottleneck before moving on. Status:
    closed; the >=40 minimum is met, while 50+ remains the stretch target.
21a. Add source-validated LLM qualification rescue for empty/partial candidates.
     Status: done; LLM proposes, code validates exact sentence/raw numeric
     surface/endpoint/arm/direction before artifact mutation.
21b. Harden rapamycin domain vocabulary for rescued endpoint and arm terms.
     Status: done; includes RAPA/eRapa/RPM aliases and high-signal endpoints.
21c. Re-run runner dry-run after rescue. Status: done; accepted=40,
     outside_scope=133, partial_only=19, partial_none_only=40, none_only=6.
21d. Continue qualification only where exact source text supports high-confidence
     claims; do not inflate receipts from narrative-only or protocol numerics.

### Phase 3 - Field Engagement And Novel Framework
22. Extract named frameworks from Mannick, Lamming, Kennedy, Kaeberlein, Selman.
23. Design minimal `agent/field_engagement.py` contract before implementation.
24. Implement field-engagement data/prose generator only if corpus inputs support it.
25. Design minimal `agent/novel_framework.py` contract before implementation.
26. Add validation: framework must resolve >=3 corpus tensions and name a falsifier.
27. Add `Novel Synthesis Framework` section.
28. Add `Engagement with Established Frameworks` section.
29. Update prompts to require named attribution for established positions.

### Phase 4 - RoB 2 And GRADE
30. Audit existing `scripts/risk_of_bias.py` and any GRADE scaffold.
31. Define schema for RoB 2 domains and justifications.
32. Wire RoB assessment for A/B-tier receipts without changing claim truth gates.
33. Render per-study RoB traffic-light table.
34. Define GRADE per-outcome schema.
35. Render Summary of Findings table.
36. Re-render rapamycin with RoB/GRADE active.
37. Verify discussion cites certainty ratings per outcome.

### Phase 5 - Quantitative Meta-Analysis
38. Audit existing numeric/QEI structures for comparable effect sizes.
39. Implement minimal random-effects pooling only if existing deps support it or
   dependency addition is justified.
40. Add heterogeneity stats: Q, I2, tau2.
41. Add forest plot rendering for outcomes with >=3 comparable effects.
42. Add funnel plot / Egger only if data shape is valid.
43. Add `Meta-Analysis Results` section.
44. Verify pooled estimates align with individual study effects.

### Phase 6 - Prose Elevation
45. Audit rapamycin for AI-template language.
46. Build template-language detector and wire as journal-surface P2/L5 blocker.
47. Add forbidden phrase list to prompts.
48. Add field-vocabulary requirements for geroscience and rapamycin.
49. Re-render and compare before/after prose.
50. Human-read three representative paragraphs; iterate if generic.

### Phase 7 - Cross-Paper Tension Depth
51. Select top 5 corpus tensions by evidence weight.
52. Generate 200-300 word elaborations naming both papers, numerics, and conflict
   hypotheses.
53. Add `Cross-Paper Tensions` section.
54. Push lower-priority tensions into supplementary tables.
55. Verify each Results subsection surfaces agreement or conflict when present.

### Phase 8 - Final Gate
56. Render `WORLDCLASS` rapamycin run.
57. Run Q1-Q14 audit and require 14/14.
58. Run journal surface gate and require zero blocking issues.
59. Run template-language detector and require zero hits.
60. Generate final cert and verify L5 or L6.
61. Read full paper end-to-end against: senior voice, submit-worthiness, novel
   insight.
62. Document publication-ready state or exact remaining gaps.
63. Decide next venue path: bioRxiv, mid-tier review journal, or top-tier with
   senior co-author.

## Persistence Task
64. After every compaction, reload this file and restore the task queue before new
   work.
