# V3 publishing recovery — audited working status

Publishing recovery is not yet complete. The current tested runtime is
`3f3716e054519b024eeb931d4c0065ce89b1fe42`. Production remains on the
reconciliation release `64086d2fe119c85529af8e6a3963cb15d9d23920` while its fresh
worker is active. No recovery submission has reached Core acceptance or public
publication. This record will be updated after the running manuscript audits.

## Five-step audit

| Step | Evidence | Remaining completion check |
|---|---|---|
| 1. Bound reconciliation | Deployed to both VPS mirrors. Two actual service passes completed in 57–58 seconds with exit 0 and retained progress across 80 distinct submission IDs. Partial results survive deferred requests. | Reconciliation complete; this is not proof of completed scientific revisions. |
| 2. Correct source records, QEI and Methods | All 37 Resveratrol source identities remain. Corrected design/directness/outcome records and recovered historical metadata-selection and extraction records. The v5 manuscript passed all six normal revision requests. | A later full review identified five problematic QEI rows; v7 is reviewing the 25 retained rows after removing those exact reviewed rows. |
| 3. Preserve manuscript completeness | A normal full-review replay retained a 447-word Conclusion. Native Abstract generation now supports its real sentence schema and rejects unsupported clauses. Fixed a reproduced repair bug that removed only table prefixes, leaving orphan numbers. | Verify the complete-row fix and all manuscript gates in the current live replay; finish the independent resistance-training review. |
| 4. Align publishing contracts | Final source binding, complete manuscript review, frozen-package checks and revision coverage remain mandatory. Preflight identified two trailing spaces after repair; cleanup now precedes final review. Rejected complete QEI rows remain quarantined through regeneration and artifact organization. | Pass ordinary enforced preflight and submit the exact reviewed package. |
| 5. Prove publication and repeatability | Two normal Resveratrol submission attempts were correctly blocked locally. A separate native resistance-training manuscript has finished drafting and is undergoing review. | Core decision, public artifact, additional distinct-topic proof and safe production rollout remain required. |

## Verification receipts

- Full suite: **4,967 passed**, two existing XPASS results, 16 warnings;
  156.58 seconds. Log: `/tmp/v3-row-durable-suite.log`.
- Quality: passed, including 343 gate/coverage/LOC tests. Mypy: 180 source files.
  Logs: `/tmp/v3-row-durable-quality-final.log`; no limits were raised.
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
