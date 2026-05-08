# State of Platform — 2026-05-08

Status: draft report. Verified fields are filled from local artifacts; final
basket totals, final test totals, and tri-sync state remain pending main-lane
completion.

## Snapshot

| Field | Value |
|---|---|
| Report date | 2026-05-08 |
| Current local HEAD | `ab38f297` |
| GitHub origin/main | `PENDING_FINAL_TRI_SYNC` |
| VPS `/opt/research-agent-bot` | `PENDING_FINAL_TRI_SYNC` |
| VPS `/root/Research-Agent-Bot` | `PENDING_FINAL_TRI_SYNC` |
| Working tree dirty state | `1045` changed/untracked paths at review time; not final |
| Test count | targeted L6/spec lane tests: `38 passed`; final full suite pending |
| Service status | `PENDING_FINAL_SERVICE_CHECK` |
| Run final-verdict artifacts visible locally | `266` |

## Architecture Decisions

- Research Agent Bot remains the synthesis engine.
- Derivation Web remains append-only provenance infrastructure.
- OSF publishing remains an independent sibling service.
- PROSPERO automation is out of scope; manual PROSPERO IDs may be recorded as
  optional external metadata.
- Mistral arbitration is bounded to `APPLY`, `REJECT`, or `ESCALATE` and
  never rewrites manuscript text.
- Bad JSON, timeout, invalid verdict, unsafe patch class, non-unique target, or
  failed post-apply audit all fail closed.
- No fake L5 inflation: unresolved flagged patches, auto-strips, or public
  surface failures block L5.

## Basket Status

Final basket totals are pending main-lane report generation.

| Metric | Value |
|---|---|
| Topics attempted | `PENDING_BASKET_REPORT` |
| AAA topics | `PENDING_BASKET_REPORT` |
| L5 topics | `PENDING_BASKET_REPORT` |
| L6 topics | rapamycin verified L6 from PATHA8/9/10; total pending basket report |
| Ship-blocked topics | `PENDING_BASKET_REPORT` |
| Total receipts | `PENDING_BASKET_REPORT` |
| Total tensions | `PENDING_BASKET_REPORT` |
| Average cost per paper | `PENDING_BASKET_REPORT` |

## Third-Layer Arbitration Status

Current claim: Mistral is wired as a logged, judge-only arbitration signal
inside deterministic safety gates. It is not trusted as a free semantic
overrider.

| Metric | Value |
|---|---|
| Arbitration enabled in final run batch | `PENDING_FINAL_BATCH_REPORT` |
| Arbitration events | `PENDING_FINAL_BATCH_REPORT` |
| APPLY decisions | `PENDING_FINAL_BATCH_REPORT` |
| REJECT decisions | `PENDING_FINAL_BATCH_REPORT` |
| ESCALATE/fail-closed decisions | `PENDING_FINAL_BATCH_REPORT` |
| Validation benchmark agreement | `PENDING_VALIDATION_REPORT` |

## Publication Infrastructure

- Provenance canonical host: `https://provenance.researka.org/`.
- OSF V1 target: PAT-only independent publisher service.
- OAuth/developer-app flow: V2.
- Live OSF publication status: pending sibling-publisher verification.
- Public reader status: pending reader-service verification.

## Remaining Empirical Gaps

1. Validation benchmark: agreement with human-consensus fixtures is still the
   key evidence gap before claiming systematic-review equivalence.
2. Human-RCT thin topics: topics such as urolithin A may be analytically useful
   but still limited by direct human RCT depth.
3. Public manuscript packaging: audit/provenance material should remain in
   bundles or supplements unless a target journal explicitly wants it in the
   main manuscript.
4. L6 reproducibility: topic-level reproducibility claims require consecutive
   clean L5 runs, not single-run AAA.
5. OSF live publishing: registry publication must be verified by the sibling
   publisher before DOI/OSF fields appear in reader or citation metadata.

## Finalization Checklist

- Replace every `PENDING_*` value from final artifacts.
- Confirm `git status --short` is clean locally and on both VPS checkouts.
- Record final commit hash and test command output.
- Verify final basket report and state report agree.
- Ensure no credentials, local absolute paths, or unverified DOI/OSF claims are
  present in public docs.
