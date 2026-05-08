# Journal Surface Root Cause v1

Diagnostic summary for the Lane C journal-surface campaign.

## Decision

Do not edit manuscripts. Fix generators/gates, then rerun target topics.

## Root Causes

1. Public `## Methods` currently contains operational provenance.
   Source: `scripts/run_mode_contract.py:230-249`.
2. The universal gate is narrower than the new batch audit.
   Source: `agent/journal_surface_gate.py:22-55`.
3. Backfill paragraphs can repeat across sections.
   Source: `scripts/apply_consistency_fixes.py:1873-1984`.
4. Appendix insertion is best-effort and historical artifacts can carry bare
   `## Search Provenance and Selection`.
   Source: `agent/manuscript_appendix.py:615-646` and
   `scripts/run_v06_synthesis.py:2331-2380`.

## Evidence

Latest seven-topic audit: 89 issues.

- 55 template/meta
- 31 duplicate paragraph
- 3 placeholder
- 0 QEI
- 0 citation artifact
- 0 standalone hedge fragment

Prior baseline audit: 99 issues with the same classes.

Artifacts are stored in `reports/journal_surface_root_cause/`.

## Minimal Next Edits

1. `scripts/run_mode_contract.py`: make Methods public-facing and add blocked
   phrases for observed leaks. Expected 25-45 LOC.
2. `agent/journal_surface_gate.py`: add template/meta and duplicate paragraph
   checks. Expected 35-55 LOC.
3. `agent/manuscript_appendix.py` or `scripts/run_v06_synthesis.py`: fail closed
   if appendix subsections appear without `## Publication Appendix`. Expected
   15-30 LOC.
4. `scripts/apply_consistency_fixes.py`: make backfill insertion document-global
   idempotent. Expected 20-40 LOC.

## Required Tests

- Public Methods excludes operational meta.
- Public-body gate blocks template/meta but allows appendix meta.
- Duplicate paragraph gate catches long repeated paragraphs.
- Appendix splice wraps Search Provenance.
- Backfill pass does not duplicate existing paragraphs.

## Rerun Order

GLP1, creatine, metformin, omega3, statins, rapamycin, caloric restriction.

## Risk

Duplicate paragraph detection has the highest false-positive risk. Keep it scoped to
long public-body prose and exempt tables/appendix.
