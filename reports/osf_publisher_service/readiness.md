# OSF Publisher Service Readiness

Dry-run scaffold ready: yes.

Live-ready: no. It is ready for a first dry deployment, not a real OSF/DW
publication.

Latest local checks:

- pytest: 20 passed
- ruff: clean
- scoped secret scan: clean

## Architecture

`research-agent-bot -> Derivation Web -> osf-publisher -> OSF -> Derivation Web`

## Blockers

- No live OSF call performed.
- No live DW write-back performed.
- Rotated OSF PAT required before first smoke.
- DW `registry_record` / `register` support must be confirmed on deployment.

## First Deployment Steps

1. Deploy `/Users/domininclynch/Desktop/Business/osf-publisher` as a sibling
   service, not inside Research Agent Bot or DW.
2. Run `python3 -m pytest -q`.
3. Install rotated PAT and DW token outside the repo.
4. Run dry deployment.
5. Enable live smoke with `OSF_PUBLISHER_LIVE=1` for one candidate only.
