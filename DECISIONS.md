# DECISION JOURNAL

## 2026-04-20 — Collapse to V0 Manual Draft Tool
**Decision:** Strip the Researka submit path, MiMo spar pass, and DeepSeek fallback from V0 and optimize only for the live draft page.
**Why:** The public product is currently a manual draft-and-download tool. Keeping submit-era code in V0 adds LOC, latency, and failure surfaces without user value.
**Alternatives rejected:**
- Keep the full external-submission stack in place — rejected because it bloats V0 and pulls the code away from the hosted page's actual job.
- Leave the old contract untouched and only patch around it — rejected because stale project rules would keep reintroducing dead code.
**Revisit if:** V2 explicitly reintroduces autonomous submission to Researka.

## 2026-04-20 — Re-add Researka submission path
**Decision:** Add optional submit to Researka /submissions when RESEARKA_URL is set, with inline pipeline processing, dedup, and UI surfacing of submission_id/decision/publication_id.
**Why:** Researka v2 backend is live and accepting submissions. The bot's drafts are now contract-compliant (7 sections incl. Gaps Identified, 12+ sources, 50+ word RQ, 50%+ recent). Submitting to Researka closes the loop from draft to publication.
**Alternatives rejected:**
- Keep V0 draft-only — rejected because Researka is ready and the integration is ~25 LOC.
- Use async worker instead of inline polling — deferred. Inline /jobs/run-once is pilot-grade; async worker orchestration is a follow-up.
**Revisit if:** Inline polling causes request hangs or Researka worker flakes become frequent.

## 2026-04-21 — Safety rails (Step 1)
**Decision:** Add three env-gate controls (BOT_ENABLED, BOT_SUBMIT_ENABLED, DAILY_COST_CAP_USD) checked before expensive work begins.
**Why:** Bot must not burn API costs unattended or submit when disabled. Kill switch allows instant halt, cost cap prevents runaway spend, submit switch separates submission from drafting.
**Details:**
- `_is_enabled()` / `_is_submit_enabled()` accept `true`, `1`, `yes`, `on` (case-insensitive).
- `_daily_cost()` scans today's `runs/*.json` (skipping `.raw.json`) and sums `estimated_cost_usd`.
- Kill check runs first (line 115), cost cap check second (line 118), submit switch gates the POST (line 167).
- 7 new tests added to `tests/test_cli.py` (total 15).
**Alternatives rejected:**
- Use a single file-based lock — rejected because env vars are simpler and VPS-friendly.
- Cost cap via external service — rejected, local JSON scan is fast enough for V0.
**Revisit if:** Cost tracking needs inter-day or cross-instance aggregation.
