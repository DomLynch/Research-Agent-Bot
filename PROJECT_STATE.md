# PROJECT_STATE.md

## Current Objective
Ship a minimal Python V0 that turns `topic + domain + criteria` into a research draft, submits to Researka when configured, and surfaces submission state on the page.

## Success Condition
- Hosted page runs the query set end to end without hanging or hidden dead paths.
- `criteria` changes both search intent and retained evidence.
- Researka submission (when RESEARKA_URL is set) passes intake gates and publishes.
- Run log records queries, retained evidence, usage, submission ID, and decision.

## Constraints
- Runtime target: ~1,100 LOC (submit/poll/dedup/publication surfacing are now in scope).
- Use only `httpx` as a runtime dependency.
- Keep the code obvious enough for a customer to customize in under an hour.
- Provider is MiMo v2 Pro only (`MIMO_API_KEY` env var). No multi-model switching.

## Winning Path
Deterministic planner + bounded public literature queries + MiMo draft pass + Researka submission + dedup + publication surfacing + tiny dashboard.

## Open Risks
- PubMed/OpenAlex relevance ranking must stay simple without becoming naive.
- Golden eval harness is in git at `tests/golden/harness.py` (VPS-side, requires live API). CI uses `tests/test_golden.py` with mock data.

## Next Validation Step
Run golden harness on VPS for real precision/coverage baseline, then flip Researka to judge_panel.

## Hardening Status
| Step | What | Status |
|---|---|---|
| 1 | Kill switch + submit switch + daily cost cap | DONE |
| 2 | Prompt injection sanitizer for titles/excerpts | DONE |
| 3 | .env.example + last_validated in harness | DONE |
| 4 | Golden harness upgrade (5 metrics) | DONE |
| 5 | Bundle quality gate, fail-closed | NOT STARTED |
| 6 | Judge calibration round | NOT STARTED |
| 7 | Evidence cards | NOT STARTED |
| 8 | Adversarial break-it pack | NOT STARTED |
| 9 | Topic-specific negative filters | NOT STARTED |
| 10 | Conditional source expansion (ClinicalTrials.gov) | NOT STARTED |
| 11 | bioRxiv/medRxiv, ChEMBL | DEFERRED |
| 12 | Weekly report script | NOT STARTED |
