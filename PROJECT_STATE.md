# PROJECT_STATE.md

## Current Objective
Ship a minimal Python V0 that turns `topic + domain + criteria` into a visible research draft plus markdown download.

## Success Condition
- Hosted page runs the bounded query set end to end without hanging or hidden dead paths.
- `criteria` changes both search intent and retained evidence.
- Run log records queries, retained evidence, usage, and markdown output.

## Constraints
- Stay as small as possible; aim for a sub-700 LOC runtime slice.
- Use only `httpx` as a runtime dependency.
- Keep the code obvious enough for a customer to customize in under an hour.

## Winning Path
Deterministic planner + bounded public literature queries + one provider-selected draft pass + markdown/log output + tiny dashboard.

## Open Risks
- Live provider latency still dominates the user-perceived speed.
- PubMed/OpenAlex relevance ranking must stay simple without becoming naive.

## Next Validation Step
Finish the V0 deletion pass, rerun planner/cli tests, then smoke the hosted page manually.
