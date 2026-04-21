# AGENTS.md

## Purpose
- Research Agent Bot: minimal V0 research draft tool with optional Researka submission.
- Optimize for readability, reversibility, and low LOC.
- Keep the runtime lean and obvious enough to fork quickly.

## Non-Negotiables
- Python only.
- Provider is MiMo v2 Pro only (`MIMO_API_KEY` env var).
- V0 pipeline: plan -> retrieve -> draft -> markdown/log -> dashboard.
- Submit path enabled: optional POST to Researka /submissions when RESEARKA_URL is set. Async: returns queued immediately, status checked via /status/<id>.
- Source bundle must have 12+ entries with relevance scores for Researka intake.
- No fallback model in V0.
- No frameworks, no multi-agent orchestration, no persistence beyond run logs.

## Safety Rails (Step 1)
Three env-gate controls checked before expensive work begins:

| Env var | Default | Effect |
|---|---|---|
| `BOT_ENABLED` | `true` | Kill switch — `false`/`0`/`no`/`off` blocks all runs immediately |
| `BOT_SUBMIT_ENABLED` | `true` | Submit switch — `false`/`0`/`no`/`off` skips Researka POST even when `RESEARKA_URL` is set |
| `DAILY_COST_CAP_USD` | `10.0` | Cost cap — blocks run if today's `runs/*.json` costs already >= cap |

All three accept `true`, `1`, `yes`, `on` (case-insensitive) as truthy values.
