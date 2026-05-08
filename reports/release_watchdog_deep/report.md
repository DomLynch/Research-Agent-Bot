# Release Watchdog Deep Report

**Verdict:** BLOCKED

## Blockers

- 162 dirty path(s)
- local/origin full SHA mismatch
- VPS short SHA does not match local full SHA prefix

## Dirty State

- Dirty paths: `162`
- Staged paths: `0`
- Untracked paths: `154`
- Lane counts: `{"basket": 4, "journal_surface": 2, "osf": 3, "other": 75, "reader": 50, "release_watchdog_deep": 28}`

## Integrity

- Full SHA match: `False`
- VPS SHA prefix match: `False`
- Secret hits: `0`
- Large file warnings: `0`

## Recovery Commands

- Dirty state: `git status --short --untracked-files=all`
- Full SHA: `git rev-parse HEAD && git rev-parse origin/main`
- VPS read-only: `python scripts/tri_sync_status.py --repo . --vps-host root@49.12.7.18 --ssh-key ~/.ssh/binance_futures_tool --json`
- Final tests: `python -m pytest`
