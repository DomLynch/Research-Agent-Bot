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
