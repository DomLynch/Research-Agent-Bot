# OSF Publisher Install-Pack Readiness

Date: 2026-05-08

Scope:
- sibling service only: `/Users/domininclynch/Desktop/Business/osf-publisher`
- report only in Research Agent Bot: `reports/osf_publisher_service/`
- no live OSF call
- no real DW call
- no real token read, stored, or logged

Evidence:
- MacBook install checklist added to sibling README
- VPS placement checklist added to sibling README
- dry-run systemd smoke wrapper added: `deploy/dry-run-smoke.sh`
- systemd oneshot now calls the smoke wrapper, not live publishing
- status CLI added for dry-run eligibility and last idempotency key
- smoke CLI emits structured JSON stderr and redacts secret-like strings
- lockfile prevents overlapping timer runs
- dead-letter file records repeated dry-run smoke failures by error class only
- live-smoke docs require rotated env-only PAT and timer disabled first

Changed sibling files:
- `/Users/domininclynch/Desktop/Business/osf-publisher/README.md`
- `/Users/domininclynch/Desktop/Business/osf-publisher/deploy/dry-run-smoke.sh`
- `/Users/domininclynch/Desktop/Business/osf-publisher/deploy/env.example`
- `/Users/domininclynch/Desktop/Business/osf-publisher/deploy/osf-publisher.service`
- `/Users/domininclynch/Desktop/Business/osf-publisher/osf_publisher/cli.py`
- `/Users/domininclynch/Desktop/Business/osf-publisher/osf_publisher/ops.py`
- `/Users/domininclynch/Desktop/Business/osf-publisher/tests/test_deploy_templates.py`
- `/Users/domininclynch/Desktop/Business/osf-publisher/tests/test_ops_cli.py`

Verification:
- `python3 -m pytest -q` -> 40 passed, repeated
- `python3 -m ruff check .` -> clean, repeated
- `OSF_PUBLISHER_PAYLOAD=fixtures/approved_statins_aaa.json OSF_PUBLISHER_STATE_DIR=/tmp/osf-publisher-smoke ./deploy/dry-run-smoke.sh` -> exit 0, report written
- missing-payload smoke -> exit 2, dead-letter written, no secret values
- production-file secret scan -> no PAT/Bearer/JWT-style values found
- test-file scan contains synthetic redaction fixtures only
- generated Python caches were removed after verification

Remaining live blockers:
- install rotated OSF PAT env-only; never reuse any pasted token
- confirm live DW registry-candidate and register endpoints
- install/verify live HTTP transport separately before enabling timer
- first live smoke must run manually with timer disabled

Readiness:
- install-pack dry-run readiness: ready
- live OSF/DW publishing: not ready
