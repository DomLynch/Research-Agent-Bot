# OSF/DW Provenance Drill

Ready for first live smoke: yes
Live proven: no

| Label | OK | Files | Reader files | Generated excluded | Keys match | Run |
|---|---:|---:|---:|---:|---:|---|
| omega3 | yes | 15 | 15 | yes | yes | `runs/synthesis-omega3-v06-Q14VALID-2026-05-06T12-19-00Z` |
| statins | yes | 14 | 14 | yes | yes | `runs/synthesis-statins-v06-proof003-2026-05-04T11-49-04Z` |
| caloric_restriction | yes | 19 | 19 | yes | yes | `runs/synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z` |
| metformin | yes | 18 | 18 | yes | yes | `runs/synthesis-metformin-v06-refactor-verify-2026-05-04T11-34-03Z` |
| rapamycin | yes | 14 | 14 | yes | yes | `runs/synthesis-rapamycin-v06-r2-2026-05-04T13-38-48Z` |
| rich-1 | yes | 17 | 17 | yes | yes | `runs/synthesis-statins-v06-PATH2RICHFIX2-2026-05-08T09-40-00Z` |
| rich-2 | yes | 19 | 19 | yes | yes | `runs/synthesis-statins-v06-PATH2RICHFIX3-2026-05-07T20-44-41Z` |
| rich-3 | yes | 19 | 19 | yes | yes | `runs/synthesis-statins-v06-PATH2RICHFIX3-2026-05-08T10-35-00Z` |
| rich-4 | yes | 17 | 17 | yes | yes | `runs/synthesis-statins-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER` |
| rich-5 | yes | 17 | 17 | yes | yes | `runs/synthesis-statins-v06-PATHABASKET84-2026-05-07T10-36-32Z` |
| rich-6 | yes | 16 | 16 | yes | yes | `runs/synthesis-statins-v06-PUBFIX-2026-05-06T18-04-23Z` |

## First Live Smoke

Use only after installing a rotated PAT on the target host:

```bash
osf-publisher publish --run-dir <run_dir> --live
```

Rollback/no-partial-state check: if the command fails before writing `osf_publish_result.json`, rerun dry mode and inspect OSF manually for any private node created without uploaded files.

DW registration remains a separate explicit write-back from the sibling osf-publisher service. Assume append-only semantics, idempotency-key enforcement, and sanitized HTTP errors.

## Rate Limit / Retry Risk

OSF upload retry is intentionally narrow for transient HTTP statuses. If rate-limited, stop after the smoke, inspect OSF state, and retry only with the same idempotency key.

## Placement

Keep OSF publishing outside this repository's runtime path. The long-term home is a sibling osf-publisher service that polls Derivation Web and writes registry records back through DW's API.
