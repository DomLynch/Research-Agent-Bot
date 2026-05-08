# OSF Publisher Service v1

Independent sibling project: `/Users/domininclynch/Desktop/Business/osf-publisher`.

Architecture:

`Research Agent Bot -> public bundle/provenance payload -> provenance.researka.org`

`osf-publisher -> OSF -> provenance.researka.org registry record`

Research Agent Bot remains synthesis-only. It writes local artifacts and public
bundle/provenance payloads. The canonical provenance endpoint is
`https://provenance.researka.org/`. The sibling publisher polls approved
registry candidates, plans or performs OSF publication, then writes a
`registry_record` and `register` step back to provenance. The bot never performs
live OSF calls.

## V1 Scope

- dry-run default
- PAT-only OSF auth when live mode is later enabled
- no token values in plans, reports, logs, or tests
- live mode requires `OSF_PUBLISHER_LIVE=1`
- client boundaries are injectable/mocked in tests

## Env Contract

- `OSF_PUBLISHER_LIVE=1`
- `OSF_PAT`
- `DW_API_URL`
- `DW_API_TOKEN`
- optional `OSF_BASE_URL`

Do not use any pasted token. Rotate before first live smoke.

## Deployment Sketch

1. Deploy sibling repo to `/opt/osf-publisher`.
2. Install rotated OSF PAT and DW API token as root-owned environment/secrets.
3. Run dry mode first.
4. Run one mocked/live-gated smoke.
5. Only then enable a timer.

Remaining blocker: DW enum/API support for `registry_record` + `register` must
be confirmed on the target DW deployment before live write-back.
