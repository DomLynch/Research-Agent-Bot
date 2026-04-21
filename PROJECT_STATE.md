# PROJECT_STATE.md

## Current Objective
Ship a minimal Python V0 that turns `topic + domain + criteria` into a research draft, submits to Researka when configured, and surfaces submission state on the page.

## Success Condition
- Hosted page runs the query set end to end without hanging or hidden dead paths.
- `criteria` changes both search intent and retained evidence.
- Researka submission (when RESEARKA_URL is set) passes intake gates and publishes.
- Run log records queries, retained evidence, usage, submission ID, and decision.

## Constraints
- Runtime target: ~1,200 LOC (submit/poll/dedup/publication surfacing + quality gate are now in scope).
- Use only `httpx` as a runtime dependency.
- Keep the code obvious enough for a customer to customize in under an hour.
- Provider is MiMo v2 Pro only (`MIMO_API_KEY` env var). No multi-model switching.

## Winning Path
Deterministic planner + bounded public literature queries + MiMo draft pass + Researka submission + dedup + publication surfacing + tiny dashboard.

## Open Risks
- PubMed/OpenAlex relevance ranking must stay simple without becoming naive.
- Golden eval harness is in git at `tests/golden/harness.py` (VPS-side, requires live API). CI uses `tests/test_golden.py` with mock data.

## Next Validation Step
Run calibration on VPS after deployment to verify kappas still hold with ClinicalTrials.gov entries in the mix.

## Hardening Status
| Step | What | Status |
|---|---|---|
| 1 | Kill switch + submit switch + daily cost cap | DONE |
| 2 | Prompt injection sanitizer for titles/excerpts | DONE |
| 3 | .env.example + last_validated in harness | DONE |
| 4 | Golden harness upgrade (5 metrics) | DONE |
| 5 | Bundle quality gate, fail-closed | DONE |
| 6 | Judge calibration round | DONE (6/6 pass, all kappas ≥ 0.60) |
| 7 | Evidence cards | DONE (build_card() returns 7 fields: citation, journal, quality_signal, study_type, population, intervention, outcomes; heuristic regex extraction) |
| 8 | Adversarial break-it pack | DONE (38 tests across 7 test classes) |
| 9 | Topic-specific negative filters | DONE (DOMAIN_NEGATIVE_FILTERS, _should_filter_entry(); 17 tests) |
| 10 | Conditional source expansion (ClinicalTrials.gov) | DONE (ClinicalTrialsClient; interventional/observational entries now accepted by drafter and harness; conditional in cli.py for oncology/longevity domains; 17 tests) |
| 11 | bioRxiv/medRxiv, ChEMBL | DEFERRED |
| 12 | Weekly report script | DONE (scripts/weekly_report.py; 5 tests) |

## Test Coverage
- Total: 167 collected, 161 passed, 6 skipped (judge calibration — needs MIMO_API_KEY)
- Break-it pack (38 tests) now collected automatically via `tests/golden` in testpaths
- ruff clean
