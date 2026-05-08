# Journal Surface Fix Report

## Summary

Implemented universal generator/gate hardening for public manuscript surface leaks.
No topic-specific Python and no manuscript/run artifact edits.

## Changes

| File | Change |
|---|---|
| `scripts/run_mode_contract.py` | Rewrote public Methods to remove submission IDs, model names, SPAR/Grok/quarantine absence prose, and patch mechanics. Extended blocked-phrase validation. |
| `agent/journal_surface_gate.py` | Added appendix-aware template/meta phrase checks and long duplicate paragraph detection scoped to public body. |
| `agent/manuscript_appendix.py` | Wrapped inserted or historical bare Search Provenance sections under `## Publication Appendix`. |
| `scripts/apply_consistency_fixes.py` | Made named analytical backfill blocks document-global idempotent where low risk. |

## Before

Root-cause latest-7 audit found 89 historical artifact issues:

- 55 template/meta
- 31 duplicate paragraph
- 3 placeholder

The same historical artifacts still fail because this patch does not mutate run
dirs. A fresh smoke copy is stored at
`reports/journal_surface_fix/historical_latest_7_audit.json`.

## After Target Assertions

New/rerun manuscripts should satisfy:

- Public Methods contains no `submission`, model names, `SPAR`, `Grok`,
  `patches are auto-applied`, or quarantine absence prose.
- Appendix/provenance material is under `## Publication Appendix` or cut from
  public-body gates.
- Public body gate fails on repeated long prose paragraphs.
- Named deterministic backfill sections are not inserted twice across the same
  manuscript.
- Existing QEI checks remain intact.

## Deferred

The depth-extension backfill can still repeat when a section is far below the
word floor. I left that path intact because globally blocking it broke existing
depth-floor restoration. The new universal gate will catch repeated long public
paragraphs after render; a later lower-risk fix should add multiple distinct
extension variants instead of duplicating one paragraph.

## Validation

First validation pass:

- `ruff`: passed
- `pytest tests/test_journal_surface_gate.py tests/test_run_mode_contract.py tests/test_manuscript_appendix.py tests/test_final_consistency_audit.py tests/test_journal_surface_batch_audit.py`: 145 passed

Final double-audit commands are recorded in the final response.
