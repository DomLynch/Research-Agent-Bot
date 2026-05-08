# OSF Publisher Deployment Dry Run

Dry deployment ready: yes.

Live ready: no. No live OSF/DW call was performed.

## Fixture

- Source run: `synthesis-statins-v06-AAA-2026-05-04T16-05-37Z`
- Audit score: `9.2`
- Fixture: `/Users/domininclynch/Desktop/Business/osf-publisher/fixtures/approved_statins_aaa.json`

## Checks

- Sibling cache/secret pre-check: clean.
- Dry-run output generated twice.
- Idempotency stable: `True`
- Dry-run config: `{'dry_run': True, 'live': False}`
- No PAT read probe: passed.
- Live gate documented: `OSF_PUBLISHER_LIVE=1 plus OSF_PAT, DW_API_URL, DW_API_TOKEN`
- Deploy templates added under sibling `deploy/` with placeholder-only env and
  dry-run systemd command.

## Outputs

- `/Users/domininclynch/Desktop/Business/osf-publisher/dry_run_statins_aaa.json`
- `/Users/domininclynch/Desktop/Business/osf-publisher/dry_run_statins_aaa_repeat.json`

## Blockers

- rotated OSF PAT required before live smoke
- DW register endpoint support must be confirmed
- no live OSF/DW call performed in this lane
