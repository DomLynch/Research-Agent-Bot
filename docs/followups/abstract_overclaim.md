# Follow-up: abstract_overclaim writer/judge convergence

Date: 2026-05-31

## Status
Open. This is intentionally separate from the v3 paper-surface compiler slice.

## Why it matters
The fresh paper lane can still spend a full cycle on topics that synthesize cleanly but fail the `abstract_overclaim` gate. That gate is classified as `C_writer_fixable`, so the right fix is writer/judge convergence, not selector terminalization.

## Evidence to collect before editing
- Latest `scripts/daily_research_paper_cycle.py` ledger attempts with `gate_status=abstract_overclaim`.
- The failing `full_paper.md` abstract and `revision_coverage.unsupported_abstract_claims(...)` output for 2-3 unrelated topics.
- Whether the abstract sentence is genuinely unsupported by receipts or the judge is over-strict.

## Candidate fixes
1. Writer-side: bound abstract claims to the receipt-backed evidence profile before final render.
2. Judge-side: make `unsupported_abstract_claims` report source-span evidence and suppress claims already hedged by evidence-class limits.
3. Repair-side: route the exact unsupported abstract sentence back through one cheap abstract-only repair before spending another full synthesis attempt.

## Non-goals
- Do not weaken the trust spine by bypassing the gate.
- Do not hardcode topic names or one-off phrases.
