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
- Title-based dedup replaced with fingerprint-based (sha256), but still local-only (no cross-instance dedup).
- Golden eval harness exists as VPS-side script; not yet CI-integrated due to PubMed network dependency.

## Next Validation Step
Run golden harness on VPS for real precision/coverage baseline, then flip Researka to judge_panel.
