# OSF Publisher Fake-DW E2E

Date: 2026-05-08

Scope:
- sibling service only: `/Users/domininclynch/Desktop/Business/osf-publisher`
- report only in Research Agent Bot: `reports/osf_publisher_service/`
- no live OSF call
- no real DW call
- no real token read, stored, or logged

Evidence:
- fake DW fixture returns approved AAA candidates and accepts `registry_record` artifact plus `register` step write-back
- dry-run E2E covers: poll fake DW -> plan OSF registration -> mock OSF -> DW write-back
- transient OSF retry covers one failed OSF boundary call followed by success, with one DW write-back
- duplicate source artifact hash produces one planned registry action
- L3/L4 artifacts are skipped by default
- fake-DW E2E constructs in-memory mock config and does not read `OSF_PAT` or `DW_API_TOKEN`
- operator safety checklist is in the sibling README
- CLI smoke command remains: `python3 -m osf_publisher.cli fixtures/approved_statins_aaa.json --out dry_report.json`

Changed sibling files:
- `/Users/domininclynch/Desktop/Business/osf-publisher/README.md`
- `/Users/domininclynch/Desktop/Business/osf-publisher/osf_publisher/service.py`
- `/Users/domininclynch/Desktop/Business/osf-publisher/tests/fake_dw.py`
- `/Users/domininclynch/Desktop/Business/osf-publisher/tests/test_fake_dw_e2e.py`

Verification:
- `python3 -m pytest -q` -> 32 passed, repeated
- `python3 -m ruff check .` -> clean, repeated
- `python3 -m osf_publisher.cli fixtures/approved_statins_aaa.json --out /tmp/osf_publisher_cli_smoke.json` -> dry-run report generated
- touched-file secret scan -> no PAT/Bearer/JWT-style values found
- sibling whitespace check -> clean

Live blockers:
- rotated OSF PAT must be installed env-only before any live smoke
- real DW candidate and register endpoints still need operator confirmation
- HTTP transport for live service remains outside this fake-DW dry-run evidence
- first live run must keep systemd timer disabled until manual smoke succeeds
- generated Python caches were removed after verification

Readiness:
- dry-run fake-DW E2E: ready
- live OSF/DW publication: not ready
