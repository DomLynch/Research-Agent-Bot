# PROJECT_STATE.md

## Current Objective
Ship a minimal Python V0 that turns `topic + domain + criteria` into a credible rapid-review draft, submits to Researka when configured, and surfaces submission state on the page.

## Success Condition
- Hosted page runs the query set end to end without hanging or hidden dead paths.
- `criteria` changes both search intent and retained evidence.
- Researka submission (when RESEARKA_URL is set) passes intake gates and publishes.
- Run log records queries, retained evidence, per-source telemetry, protocol path, usage, submission ID, and decision.
- Run log records raw topic, canonical topic, resolver confidence, retained evidence, per-source telemetry, protocol path, usage, submission ID, and decision.
- Draft output includes a PRISMA-style Methods block and GRADE-lite source labels.
- Anti-aging topics with indirect-only bundles refuse submission instead of overclaiming.
- Obvious typo / wrong-entity compound topics fail safely instead of drafting over junk retrieval.

## Constraints
- Runtime target: ~2,400 LOC (raised from 2,100 — see DECISIONS.md 2026-04-21 "Add Tier 1.5 structured extraction").
  Hard ceiling: 2,800 LOC. Actual: ~2,591 LOC.
- Use only `httpx` as a runtime dependency.
- Keep the code obvious enough for a customer to customize in under an hour.
- Provider is MiMo v2 Pro only (`MIMO_API_KEY` env var). No multi-model switching.

## Winning Path
Deterministic planner + bounded public literature queries + directness-aware bundle + MiMo draft pass + PRISMA/grade/protocol surfacing + Researka submission + dedup + publication surfacing + tiny dashboard.

## Open Risks
- PubMed/OpenAlex relevance ranking must stay simple without becoming naive.
- Golden eval harness now has 3-tier eval corpus (gold + adversarial + breadth) with CI gating.
- Runtime is now above the previous 1,800 ceiling; further additions need deletions or another explicit DECISIONS entry.
- Quantitative fidelity is now honestly measured and still weak on the gold baseline; drafter must earn future quality gains with supported numbers.
- Directness labeling is still heuristic. The tightened classifier now blocks obvious indirect-only longevity bundles, but retrieval quality still dominates final bundle quality.
- Topic/entity resolution is now ChEMBL-first plus alias/fuzzy fallback. It still needs richer biomedical vocabularies before Tier 1 full-text work.
- Tier 1 full-text coverage is Europe PMC-only and DOI/PMID-driven. Closed-access PDFs, figures/tables, and non-PMC papers still fall back to abstract-only behavior.
- Tier 1.5 extraction is cached and real, but numeric validation is not yet a hard gate. The model now sees extracted facts from a subset of papers; it is still possible to draft unsupported numbers until a validator pass lands.
- ClinicalTrials.gov registry records are now split into `trial_registered` versus `trial_results`, and posted registry results can supply structured effects without an LLM extraction call. Registry-only studies are design-only in the prompt and get scrubbed if the drafter tries to state outcomes.

## Next Validation Step
Re-run `metformin aging older adults` with `2023 onwards human studies relevance` and confirm ClinicalTrials entries with no posted results are described as design-only while any posted-result entries surface numeric claims from structured effects rather than generic prose.

## Hardening Status
| Step | What | Status |
|---|---|---|
| 1 | Kill switch + submit switch + daily cost cap | DONE |
| 2 | Prompt injection sanitizer for titles/excerpts | DONE |
| 3 | .env.example + last_validated in harness | DONE |
| 4 | Golden harness upgrade (5 metrics) | DONE |
| 5 | Bundle quality gate, fail-closed | DONE |
| 6 | Judge calibration round | DONE (6/6 pass, all kappas ≥ 0.60; readability rubric rewritten with subjective gate) |
| 7 | Evidence cards | DONE (build_card() returns 7 fields: citation, journal, quality_signal, study_type, population, intervention, outcomes; heuristic regex extraction) |
| 8 | Adversarial break-it pack | DONE (44 tests across 8 test classes) |
| 9 | Topic-specific negative filters | DONE (DOMAIN_NEGATIVE_FILTERS, _should_filter_entry(); 24 tests) |
| 10 | Conditional source expansion (ClinicalTrials.gov) | DONE (ClinicalTrialsClient; interventional/observational entries now accepted by drafter and harness; conditional in cli.py for oncology/longevity domains; 17 tests) |
| 11 | bioRxiv/medRxiv, ChEMBL | DONE (RxivClient via Europe PMC preprints filtered to bioRxiv/medRxiv publishers; ChEMBLClient for compound/mechanism context on drug-like topics) |
| 12 | Weekly report script | DONE (scripts/weekly_report.py; 7 tests including gate_blocked + submission_breakdown) |
| 13 | 3-tier eval corpus (gold + adversarial + breadth) | DONE (15 gold topics, 30 adversarial, 60 breadth; 4 scoring functions; CI workflow) |

## Phase 1 Credibility Slice (Apr 21)
- **Directness labels:** each retained source now carries `direct`, `indirect`, or `mechanistic` for downstream gating and audit.
- **GRADE-lite:** evidence cards now expose `evidence_grade` (`H/M/L`) and `context` labels.
- **Protocol preregistration:** every run writes `runs/protocols/<stem>.protocol.json` before drafting.
- **PRISMA-style methods:** every draft surfaces search date, sources searched, queries, and flow counts (`retrieved → filtered → final bundle`).
- **PRISMA-style methods:** every draft now surfaces search date, sources searched, queries, screened/excluded/included counts, and explicit exclusion-reason summaries that reconcile with the final source bundle.
- **Submit trust gate:** anti-aging / longevity runs with indirect-only bundles return `indirect_only_bundle` instead of posting to Researka.
- **Telemetry:** run logs now include `source_telemetry` with per-source retrieved, post-filter, final-bundle, and final-directness counts.
- **Tier 0 entity layer:** compound-like topics now resolve to canonical names before retrieval, ChEMBL returns `[]` on no real match, and low topic-match bundles fail before draft generation.
- **Tier 1 full-text ingestion:** literature entries now attempt Europe PMC full-text fetch with cache-by-identity, run logs expose `full_text` telemetry, Methods surfaces full-text coverage, and evidence cards can extract fields from full-text text when available.
- **Tier 1.5 structured extraction:** full-text-backed entries now attempt cached MiMo extraction into population/intervention/comparator/methods/effects JSON, evidence cards prefer extracted facts, and drafter prompts now see extracted outcomes/effect summaries instead of a bare full-text flag.
- **Scope/directness tightening:** criteria parsing now accepts `2023 onwards`, `post-2023`, and `≥2023`; human-only filtering rejects obvious non-human species titles; protocol/rationale/design papers are labeled `protocol` and no longer count as direct evidence.
- **Tier 1.6 trial-results grounding:** ClinicalTrials.gov entries now distinguish registry-only records from posted results, posted-result trials can populate structured `effects[]` directly from CT.gov outcomes, Methods reconciles bundle-backed extraction/full-text counts, and draft post-processing strips outcome claims attached to registration-only citations while forcing a numeric fallback when effect data exists.

## Eval Corpus (Step 13)
- **3-tier structure**: 15 gold + 30 adversarial + 60 breadth
- **Gold ground truth**: OpenAlex programmatic — top systematic review since 2022 matching topic tokens in title, `referenced_works` → 14–15 included DOIs per topic. Every DOI CrossRef-verified. 207 verified DOIs, zero dead. `curator: openalex-programmatic`.
- **Scoring**: study_overlap (0.10), quantitative_fidelity (0.40), direction_agreement (0.30), limitation_overlap (0.20)
- **Direction classifier fix** (Apr 21): expanded `_classify_direction` keyword lists — positive 5→33 terms, caveat 7→15, negative narrowed 8→6 strong-only. DA improved from 0.40→0.65 avg.
- **CI gate**: `.github/workflows/ci.yml` — tests + ruff on every push/PR; `.github/workflows/karpathy-pr.yml` — fixture regen + snapshot diff on PRs; `.github/workflows/weekly-reports.yml` — Monday cron for coverage audit + weekly report
- **Gold topics**: rapamycin, nad_precursors, metformin, senolytics, glp1, time_restricted_eating, creatine_cognition, omega3_cv, vitamin_d_mortality, exercise_mci, donanemab_alzheimer, semaglutide_weight, glp1_cv_mace, sglt2_heart_failure, statin_primary_prevention
- **Schema validator**: `tests/golden/schema.py` validates all topic JSONs
- **Scripts**: `scripts/curate_gold.py` (re-populate gold), `scripts/verify_dois.py` (CrossRef check), `scripts/generate_eval_corpus.py` (adversarial+breadth), `scripts/generate_fixtures.py` (live bot drafts — needs MIMO_API_KEY)

## Test Coverage
- MacBook: 349 passed, 6 skipped (judge calibration — needs MIMO_API_KEY)
- ruff clean
- Gold corpus: 15/15 topic-matched, 207/207 CrossRef-verified DOIs, 0 dead
- Main is current. See DECISIONS.md 2026-04-21 for the quant-fidelity honesty fix and the Phase 1 credibility-layer budget raise.

## Surrogate Wiring (Brief 7)

Modules built but not yet integrated into `run_agent()` are kept alive via:

- **Schema conformance** (`tests/test_schema_conformance.py`): every pytest run validates
  real extraction cache files against `agent/schema.py` — catches output shape drift.
- **Unpaywall smoke** (`scripts/unpaywall_smoke.py`): weekly cron resolves 5 known OA DOIs,
  writes `docs/weekly/YYYY-MM-DD-unpaywall.md`. Exits 1 on hit rate < 60%.
- **Dead-code detector** (`scripts/detect_unused_modules.py`): CI warning when
  `agent/**/*.py` modules are not imported anywhere. Currently flags `unpaywall.py` + `schema.py`
  pending Tier 2. Guards against future bloat.

When Tier 2 lands, the detector goes silent on those two modules; the other two
surrogate checks keep running against the integrated modules.


## Judge Panel Prototype (Brief 9)

New module `agent/review/judge_panel.py` — standalone peer review system.
Three judges (methodology, evidence, claims) independently score drafts
on 10 rubric axes, adjudicator synthesizes verdict.

Public API:
    from agent.review.judge_panel import review_draft
    review = review_draft(draft_artifact)
    # review["adjudicated_verdict"] -> accept|minor_revision|major_revision|reject
    # review["required_fixes"] -> list of specific fixes
    # review["aggregate_score"] -> 1.0-5.0 mean

Cost: ~4 MimoClient calls per review, roughly $0.003 per submission.

Not wired into production Researka submission flow yet — that's the next brief.
