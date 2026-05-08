# OSF Live Readiness v1

This drill is dry-run only. It does not read `OSF_PAT`, `DW_API_TOKEN`, or call
OSF/DW. It reports whether run bundles are ready for a future sibling
`osf-publisher` live smoke, not whether live publishing is already proven.

Architecture decision: OSF publishing stays outside `research-agent-bot` and
outside Derivation Web. The bot generates AAA research artifacts and provenance
events. DW records append-only provenance. A sibling `osf-publisher` service
polls DW, creates OSF registrations/DOIs, and writes registry records back to
DW through the public API.

## Scope

`scripts/osf_live_readiness.py` checks latest local runs for:

- omega3
- statins
- caloric restriction (`cr` alias only)
- metformin
- rapamycin
- six latest rich/PUBFIX/PATHABASKET runs

It writes:

- `reports/osf_provenance_drill/report.json`
- `reports/osf_provenance_drill/readiness_matrix.md`

## Rotated-PAT VPS Runbook

1. Rotate any pasted or previously exposed OSF token before use.
2. Local: export the rotated PAT only in the shell that runs the live smoke.
3. VPS: install the rotated PAT only in the service environment or one-shot
   command environment.
4. Keep `OSF_PUBLISHER_LIVE=1` unset by default.
5. Run dry readiness first:

```bash
python scripts/osf_live_readiness.py
```

6. First live smoke, one run only:

```bash
osf-publisher publish --run-dir <run_dir> --live
```

Do not echo the PAT. Do not write it to `.env`, reports, logs, or shell history.

## VPS Env Checklist

- `OSF_PAT` is present only for the sibling publisher live smoke process.
- `OSF_PUBLISHER_LIVE=1` is present only on the live smoke command.
- `DW_API_TOKEN` is only needed when the sibling publisher writes the registry
  record back to DW.
- Shell history is disabled or the PAT is injected outside the command line.

## Security Checklist

- Rotate any pasted token before use.
- Run dry readiness immediately before live smoke.
- Secret-scan reports before sharing.
- Confirm `osf_publish_result.json` is absent unless deliberately using
  `--force`.

## First Live Smoke Protocol

- Choose the smallest green dry-run bundle.
- Confirm no existing `osf_publish_result.json` unless intentionally using
  `--force`.
- Run the live command once.
- If it fails before result write, inspect OSF for a private partial node and
  delete or quarantine it manually before retrying.
- If result writes, verify uploaded file count matches dry-run `file_count` and
  generated publisher artifacts are absent.

Expected no-partial-state artifacts:

- success: `bundle_snapshot.json`, `osf_publish_plan.json`,
  `osf_publish_result.json`
- auth/network failure before node creation: no `osf_publish_result.json`
- upload failure after node creation: result may contain sanitized file errors;
  inspect OSF and quarantine/delete the private partial node before retry

## DW Assumptions

- DW register endpoint is append-only.
- Caller sends an idempotency key.
- Auth failure and network failure must not print tokens.
- DW live registration remains separate from OSF live publish.

Endpoint contract:

- accepts JSON payload schema `derivation_web.register_public_bundle.v1`
- enforces `Idempotency-Key`
- returns sanitized failures without echoing auth headers

## Retry / Rate Limit

OSF retries only transient statuses. Treat 429 as stop-and-inspect during the
first live smoke. Do not loop a live smoke blindly; retry only after confirming
the OSF node state.

## Placement Decision

Keep OSF publication outside this repository's runtime path. This repo may keep
dry-run contract checks, but live OSF publishing belongs in a sibling
`osf-publisher` service with its own auth, retries, rate limits, and failure
handling.
