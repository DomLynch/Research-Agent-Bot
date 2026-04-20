# DECISION JOURNAL

## 2026-04-20 — Collapse to V0 Manual Draft Tool
**Decision:** Strip the Researka submit path, MiMo spar pass, and DeepSeek fallback from V0 and optimize only for the live draft page.
**Why:** The public product is currently a manual draft-and-download tool. Keeping submit-era code in V0 adds LOC, latency, and failure surfaces without user value.
**Alternatives rejected:**
- Keep the full external-submission stack in place — rejected because it bloats V0 and pulls the code away from the hosted page's actual job.
- Leave the old contract untouched and only patch around it — rejected because stale project rules would keep reintroducing dead code.
**Revisit if:** V2 explicitly reintroduces autonomous submission to Researka.
