# V3 publishing recovery — audited working status

Publishing recovery is not yet complete. The current tested runtime is
`7e449d0abbecf14e28449d367114d240674b67d8`. Production remains on the
reconciliation release `64086d2fe119c85529af8e6a3963cb15d9d23920` while its fresh
worker is active. No recovery submission has reached Core acceptance or public
publication. Resveratrol v7 reached Core through normal submission: `5642c184-d9a3-4736-a8ae-1b1f7371cd7c`; autonomous review is pending.

## Five-step audit

| Step | Evidence | Remaining completion check |
|---|---|---|
| 1. Bound reconciliation | Deployed to both VPS mirrors. Two actual service passes completed in 57–58 seconds with exit 0 and retained progress across 80 distinct submission IDs. Partial results survive deferred requests. | Reconciliation complete; this is not proof of completed scientific revisions. |
| 2. Correct source records, QEI and Methods | All 37 Resveratrol source identities remain. Corrected design/directness/outcome records and recovered historical metadata-selection and extraction records. The v5 manuscript passed all six normal revision requests. | v7 passed all six revision checks, 14/14 audit, final depth, preflight and frozen-package gates; 37 source snapshots are unchanged. |
| 3. Preserve manuscript completeness | A normal full-review replay retained a 447-word Conclusion. Native Abstract generation now supports its real sentence schema and rejects unsupported clauses. Fixed a reproduced repair bug that removed only table prefixes, leaving orphan numbers. | v7 passed the live complete-row and full-manuscript checks. Resistance training exposed further punctuation, empty-cell and source-classification defects; fixes pass regression tests and its repaired replay is next. |
| 4. Align publishing contracts | Final source binding, complete manuscript review, frozen-package checks and revision coverage remain mandatory. Preflight identified two trailing spaces after repair; cleanup now precedes final review. Rejected complete QEI rows remain quarantined through regeneration and artifact organization. | Complete: ordinary preflight passed with identical input/cleaned hashes, no safe fixes, and Core received the exact reviewed v7 package. |
| 5. Prove publication and repeatability | The third normal Resveratrol attempt submitted successfully after correcting the two local blockers. Native resistance training correctly stopped at its quality gate; its repaired replay remains required. | Core decision, public artifact, additional distinct-topic proof and safe production rollout remain required. |

## Verification receipts

- Full suite: **4,972 passed**, two existing XPASS results, 16 warnings;
  153.23 seconds. Log: `/tmp/v3-second-topic-suite-final.log`.
- Quality: passed, including 343 gate/coverage/LOC tests. Mypy: 181 source/test files.
  Logs: `/tmp/v3-second-topic-quality-final2.log`; no limits were raised.
- Focused repair/QEI/runner tests: 104 passed locally and on the isolated VPS.
- The test for partial table-row deletion failed before the repair and passes
  after it. Tests also cover neighboring rows, partial/unrelated/advisory
  quarantine entries, historical debug-folder records and preservation through
  artifact organization.
- Historical docstring condensation was checked for executable AST equivalence.
- The deployed reconciliation history was merged into development at `771fa74a`;
  its source tree exactly matched the already-tested `6b7bb381` tree.

## Running and retained evidence

The isolated release checkout is `/tmp/v3-standardized-release-20260910` on the
VPS. Its v7 Resveratrol run preserves the source snapshots and original extracted
facts, records the five previously reviewed row removals, regenerates the table,
and runs the normal manuscript pipeline, final-status routine, six-request
coverage and frozen-package checks. Script: `/tmp/v3-final-package-v7.py`;
log: `/tmp/v3-final-package-v7.log`.

The separate native resistance-training run remains on its original `98cce1f7`
checkout at `/tmp/v3-recovery-review-parity-20260910`. It uses 19 frozen sources;
its writer produced Results of 880 words and a Conclusion of 443 words. Those
are drafting measurements, not a final manuscript or publication result.
Log: `/tmp/v3-resistance-full-v2.log`.

The plasma-exchange probe detected stale handover instructions: the current
eligible parent has eight substantive revision requests, not the old single
abstract-matching request. It stopped before generation. Do not reuse the old
request or the separate terminally rejected parent.

## Scientific and operational boundaries

The working route is a full-length curated evidence map using verified existing
records. Results 400 / Conclusion 180 final minimums and higher writer targets
remain. A1 is a design code, not a quality rating; no formal appraisal, systematic
screening or pooling is invented. The internally conflicting Montoya-Estrada
statistic remains excluded; treatment attribution is never guessed.

Writers remain configured Sol High; reviewer remains Terra Medium, with the
existing technical-failure-only fallback policy. Valid negative reviews are
preserved. Core and website code have not changed.

The deployment script `/tmp/v3-standardized-deploy.sh` is prepared but has not
run. Update its expected SHA to the final tested release, verify all publishing
workers are idle in a separate read, then use the existing exclusive prepare
lock, clean-tree checks and timer restoration. Never update an active checkout.

## Second-topic audit additions

Three reproduced failures now have passing regressions: parenthesis cleanup damaged a verbatim table fragment; a reviewer repair left a blank required estimate; and auto-strip of a pipe-free cell left an orphan row. The source audit also found an explicit healthy-human trial relabelled as animal evidence from background excerpts and a protocol whose future-results statement appeared only in the abstract. Those classification regressions pass. Research-question and Methods templates no longer imply clinical actionability or executed pooling without supporting outputs. The complete suite passes 4,972 tests; two XPASS results and 16 warnings remain as before.
