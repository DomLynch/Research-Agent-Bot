# AGENTS.md

## Purpose
- Research Agent Bot: minimal V0 research draft tool with optional Researka submission.
- Optimize for readability, reversibility, and low LOC.
- Keep the runtime lean and obvious enough to fork quickly.

## Non-Negotiables
- Python only.
- Provider is MiMo v2 Pro only (`MIMO_API_KEY` env var).
- V0 pipeline: plan -> retrieve -> draft -> markdown/log -> dashboard.
- Submit path enabled: optional POST to Researka /submissions when RESEARKA_URL is set. Includes inline pipeline processing and dedup.
- No fallback model in V0.
- No frameworks, no multi-agent orchestration, no persistence beyond run logs.

## Quality Bar
- `criteria` must affect retrieval, not just prompt text.
- Show the draft on-page and offer a markdown download.
- Track prompt version, tokens, and cost on every model call.
- Keep diffs small and easy for customers to fork.
- Source bundle must have 12+ entries with relevance scores for Researka intake.
