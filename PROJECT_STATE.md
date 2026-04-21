# PROJECT_STATE.md

## Current Objective
Ship a minimal Python V0 that turns `topic + domain + criteria` into a research draft, submits to Researka when configured, and surfaces submission state on the page.

## Success Condition
- Hosted page runs the query set end to end without hanging or hidden dead paths.
- `criteria` changes both search intent and retained evidence.
- Researka submission (when RESEARKA_URL is set) passes intake gates and publishes.
- Run log records queries, retained evidence, usage, submission ID, and decision.

## Constraints
- Runtime target: ~1,500 LOC (raised from 1,200 — see DECISIONS.md 2026-04-21 "scope creep").
  Hard ceiling: 1,800 LOC. Actual: ~1,482 LOC.
- Use only `httpx` as a runtime dependency.
- Keep the code obvious enough for a customer to customize in under an hour.
- Provider is MiMo v2 Pro only (`MIMO_API_KEY` env var). No multi-model switching.

## Winning Path
Deterministic planner + bounded public literature queries + MiMo draft pass + Researka submission + dedup + publication surfacing + tiny dashboard.

## Open Risks
- PubMed/OpenAlex relevance ranking must stay simple without becoming naive.
- Golden eval harness now has 3-tier eval corpus (gold + adversarial + breadth) with CI gating.

## Next Validation Step
All hardening steps complete. Ready for main merge and real-world QA.

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
| 11 | bioRxiv/medRxiv, ChEMBL | DEFERRED |
| 12 | Weekly report script | DONE (scripts/weekly_report.py; 7 tests including gate_blocked + submission_breakdown) |
| 13 | 3-tier eval corpus (gold + adversarial + breadth) | DONE (10 gold topics, 30 adversarial, 60 breadth; 4 scoring functions; CI workflow) |

## Eval Corpus (Step 13)
- **3-tier structure**: 10 gold + 30 adversarial + 60 breadth
- **Gold ground truth**: OpenAlex programmatic — top systematic review since 2022 matching topic tokens in title, `referenced_works` → 14–15 included DOIs per topic. Every DOI CrossRef-verified. 148 verified DOIs, zero dead. `curator: openalex-programmatic`.
- **Scoring**: study_overlap (0.35), quantitative_fidelity (0.30), direction_agreement (0.20), limitation_overlap (0.15)
- **CI gate**: `.github/workflows/eval.yml` — schema validation on push, `gold_smoke` soft-skips until `MIMO_API_KEY` is wired as a CI secret + a pre-test step runs `scripts/generate_fixtures.py`
- **Gold topics**: rapamycin, nad_precursors, metformin, senolytics, glp1, time_restricted_eating, creatine_cognition, omega3_cv, vitamin_d_mortality, exercise_mci
- **Schema validator**: `tests/golden/schema.py` validates all topic JSONs
- **Scripts**: `scripts/curate_gold.py` (re-populate gold), `scripts/verify_dois.py` (CrossRef check), `scripts/generate_eval_corpus.py` (adversarial+breadth), `scripts/generate_fixtures.py` (live bot drafts — needs MIMO_API_KEY)

## Test Coverage
- MacBook: 207 passed, 7 skipped (6 judge calibration + 1 gold_smoke without fixtures)
- ruff clean
- Gold corpus: 10/10 topic-matched, 148/148 CrossRef-verified DOIs, 0 dead
- Main is current. No uncommitted scope creep — see DECISIONS.md 2026-04-21 for the 4 out-of-scope features that got accepted with a raised LOC budget.
