# AGENTS.md

## Purpose
- Research Agent Bot: minimal V0 research draft tool.
- Optimize for readability, reversibility, and low LOC.
- Keep the runtime lean and obvious enough to fork quickly.

## Non-Negotiables
- Python only.
- Primary model: MiniMax M2.7 Highspeed.
- V0 pipeline only: plan -> retrieve -> draft -> markdown/log -> dashboard.
- No submit path, no poll path, no spar model, no fallback model in V0.
- No frameworks, no multi-agent orchestration, no persistence beyond run logs.

## Quality Bar
- `criteria` must affect retrieval, not just prompt text.
- Show the draft on-page and offer a markdown download.
- Track prompt version, tokens, and cost on every model call.
- Keep diffs small and easy for customers to fork.
