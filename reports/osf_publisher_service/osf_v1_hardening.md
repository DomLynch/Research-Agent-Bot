# OSF Publisher V1 Hardening

Status: dry-run hardened, not live-ready.

## Evidence

- pytest: 28 passed
- ruff: clean
- strict redaction utility added for bearer / OSF / DW / JWT-like secret strings
- live config fails fast unless `OSF_PUBLISHER_LIVE=1`, `OSF_PAT`, `DW_BASE_URL`, `DW_API_TOKEN`, `OSF_PUBLISHER_ACTOR_ID`, and `DW_PROVENANCE_ENDPOINT` are present
- deploy templates default to dry-run
- bundle inventory scanner is V1.1 design-only and excludes generated publisher artifacts
- V1 policy remains title + description + registry metadata only; no bundle upload

## Operations

Install placeholders from `deploy/env.example`; never store a real PAT in the repo.

Dry-run:

```bash
python3 -m osf_publisher.cli fixtures/approved_statins_aaa.json --out dry_report.json
```

Live smoke only after rotated secrets are installed outside the repo:

```bash
OSF_PUBLISHER_LIVE=1 osf-publisher /etc/osf-publisher/approved.json --out /var/lib/osf-publisher/last_dry_run.json
```

Rollback: disable the timer with `systemctl disable --now osf-publisher.timer`, inspect OSF/DW state, and reconcile manually before retrying if OSF succeeded but DW write-back failed.

## Remaining Blockers

- no live OSF call performed
- no live DW write-back performed
- rotated PAT required
- target DW register support must be confirmed
