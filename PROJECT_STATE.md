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
- Runtime target: ~5,200 LOC (raised from 3,500 — see DECISIONS.md 2026-04-23 "Source substrate + 12-citation intake alignment").
  Hard ceiling: 5,800 LOC. Actual: ~5,515 LOC.
- Use only `httpx` as a runtime dependency.
- Keep the code obvious enough for a customer to customize in under an hour.
- Provider is MiMo v2 Pro only (`MIMO_API_KEY` env var). No multi-model switching.

## Winning Path
Deterministic planner + bounded public literature queries + directness-aware bundle + MiMo draft pass + PRISMA/grade/protocol surfacing + Researka submission + dedup + publication surfacing + tiny dashboard.

## Open Risks
- PubMed/OpenAlex relevance ranking must stay simple without becoming naive.
- Golden eval harness now has 3-tier eval corpus (gold + adversarial + breadth) with CI gating.
- Runtime is now above the previous 1,800 ceiling; further additions need deletions or another explicit DECISIONS entry.
- Submission intake now correctly requires 12+ retained sources, which raises pressure on retrieval depth and tier-aware bundle filling for thin longevity topics.
- OpenAlex / Semantic Scholar are now richer metadata substrates and Europe PMC is now a direct retrieval source, but the new NIH RePORTER / DOAJ paths are still early and need live-topic validation.
- Quantitative fidelity is now honestly measured and still weak on the gold baseline; drafter must earn future quality gains with supported numbers.
- Directness labeling is still heuristic. The new generic longevity topic-fit scorer removed the metformin-only bundle path and now generalizes across aliases/classes, and a new MiMo editor pass now cleans the assembled artifact, but live bundle quality still varies by topic and retrieval quality still dominates final bundle quality.
- Topic/entity resolution is now ChEMBL-first plus alias/fuzzy fallback. It still needs richer biomedical vocabularies before Tier 1 full-text work.
- Tier 1 full-text coverage is Europe PMC-only and DOI/PMID-driven. Closed-access PDFs, figures/tables, and non-PMC papers still fall back to abstract-only behavior.
- Tier 2 full-text coverage now cascades Europe PMC -> Unpaywall -> CORE, but only Europe PMC and Unpaywall are exercised locally today. CORE is env-gated on `CORE_API_KEY`, and PDF-only Unpaywall hits still need GROBID or another parser before they help extraction.
- Tier 1.5 extraction is cached and real, but quantitative fidelity is still uneven. Unsupported numbers are now scrubbed and high-severity citation-role violations trigger one revision pass plus fail-closed behavior, but medium-severity numeric misses still need a richer rewrite loop.
- ClinicalTrials.gov registry records are now split into `trial_registered` versus `trial_results`, and posted registry results can supply structured effects without an LLM extraction call. Registry-only studies are design-only in the prompt and get scrubbed if the drafter tries to state outcomes.
- Citation-role validation is now logged in `citation_violations`, and high-severity violations trigger one revision pass before the run fails closed. Medium-severity issues remain advisory.

## Next Validation Step
 Re-run `metformin aging older adults`, `rapamycin aging older adults`, and one blind longevity topic (for example `senolytics dasatinib quercetin older adults`) on the live site and judge four things only: bundle relevance, evidence-tier separation, extraction-to-prose quality, and whether direct trials stay centered without topic-specific code.

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
- **Tier 2 citation-role discipline:** every bundle entry now gets a `role` (`published_results`, `registered_pending`, `published_protocol`, `animal_model`, `off_domain_indirect`, etc.), the drafter prompt is grouped by role with explicit language rules, and post-draft citation validation logs forbidden-role language, missing hedges, and missing numerics.
- **Tier 2 multi-source full-text:** full-text enrichment now cascades Europe PMC -> Unpaywall -> CORE, tracking `found_any`, `parseable_text_count`, and per-source hit counts so OA coverage gains are visible even when only PDF URLs are available.
- **Tier 2 benchmarked:** live MiMo fixture regeneration now ran end-to-end on all 15 gold topics. Honest Karpathy delta versus the clean pre-run fixture set: `composite +0.0256`, `quant +0.0444`, `limitations +0.0889`, `direction -0.0333`, `study_overlap +0.0000`. See `docs/tier2-validator-audit.md`.
- **Tier 2 judge veto:** published-results/design-language drift is now repaired before validation, and any remaining high-severity citation-role violations trigger one revision pass before the run fails closed instead of shipping known-bad prose.
- **Metformin cleanup pass:** longevity bundles now drop explicit off-domain leaks such as embryo/antiseizure/ocular/COVID/exercise-timing records, `direct` requires a real topic token in title rather than generic aging words, prompt evidence lines now include titles, and Key Findings are instructed to center the top direct published metformin trials.
- **Semantic Scholar graph wiring:** Brief 8 is now partially integrated — `agent/sources/semantic_scholar.py` is live, `run_agent()` expands retrieval from review reference lists on longevity/anti-aging topics, and full-text enrichment now accepts `semantic_scholar` entries so cited DOI hits can flow into Europe PMC / Unpaywall / CORE.
- **Generic longevity fit gate:** the old metformin-only retention path is gone. Topic handling now flows through canonical entity resolution (`canonical_term`, aliases, class terms), generic topic-fit scoring, generic claim-fit gating, and a shared human-only filter that now rejects nonhuman primate studies.
- **MiMo editor pass + evidence tiers:** a bounded second MiMo pass now edits the assembled draft for abstract completeness, duplicate hook removal, and clearer Tier A/B/C evidence separation; the source bundle now carries generic `evidence_tier` labels instead of relying on topic-specific prose hacks.
- **MiMo upstream judgment layer:** retained candidates now go through a generic MiMo reranking pass (`core` / `landscape` / `drop`) and a generic MiMo role/directness/tier labeling pass before drafting. Deterministic scoring remains as scaffold and validator, but explicit MiMo `drop` decisions are no longer revived by low-count fallback bundling.
- **Source substrate + intake alignment:** Europe PMC is now a first-class retrieval adapter, OpenAlex/Semantic Scholar now carry richer metadata into ranking, Semantic Scholar graph expansion now includes recommendations, source bundles can include protocol-type support records, NIH RePORTER is available as Tier C/project-context retrieval, DOAJ can mark indexed journals in the final bundle, and the Researka submission floor is now correctly enforced at 12 retained sources instead of the stale 8-source gate.
- **Bundle hygiene repair under the 12-source rule:** final bundle selection now hard-drops entries with no canonical intervention fit, collapses MED/PMC mirror duplicates by normalized title/URL/DOI, and uses `Tier A1 / A2 / B / C` labels so direct older-adult RCTs outrank disease-context cohorts, reviews, and protocol/mechanistic support without reverting the Researka 12-citation floor.

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
- MacBook: 455 passed, 6 skipped, 5 xfailed
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
  `agent/**/*.py` modules are not imported anywhere. After Tier 2, `unpaywall.py`
  is live and no longer flagged; `schema.py` remains externally exercised.

After Tier 2, the detector goes silent on `unpaywall.py`; the other surrogate
checks keep running against the integrated modules.
