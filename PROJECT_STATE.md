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
- Inline /jobs/run-once polling can block the dashboard on Researka flake. Needs async refactor.
- PubMed/OpenAlex relevance ranking must stay simple without becoming naive.
- Title-based dedup is simplistic. Needs fingerprint-based dedup.

## Next Validation Step
Fix docs, kill inline orchestration, add golden eval harness, then flip Researka to judge_panel.
