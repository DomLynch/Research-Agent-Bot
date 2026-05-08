# Release Watchdog Deep Report

**Verdict:** BLOCKED

## Blockers

- 45 dirty path(s)

## Dirty State

- Dirty paths: `45`
- Staged paths: `0`
- Untracked paths: `13`
- Lane counts: `{"basket": 8, "journal_surface": 3, "osf": 12, "other": 15, "reader": 4, "release_watchdog_deep": 3}`

## Integrity

- Full SHA match: `True`
- VPS SHA prefix match: `True`
- Secret hits: `0`
- Large file warnings: `0`
- OSF placement warnings: `0`

## Recovery Commands

- Dirty state: `git status --short --untracked-files=all`
- Full SHA: `git rev-parse HEAD && git rev-parse origin/main`
- VPS read-only: `python scripts/tri_sync_status.py --repo . --vps-host root@49.12.7.18 --ssh-key ~/.ssh/binance_futures_tool --json`
- Final tests: `python -m pytest`
