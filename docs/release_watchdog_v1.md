# Release Watchdog V1

Lane F is a read-only release manager. It does not commit, push, deploy,
restart services, or mutate remote hosts.

Checkpoint commands:

```bash
python scripts/tri_sync_status.py --repo . --json > reports/release_watchdog/tri_sync.json
git status --short > reports/release_watchdog/dirty.txt
{ printf 'local_full='; git rev-parse HEAD; printf 'origin_full='; git rev-parse origin/main; } > reports/release_watchdog/sha.txt
cat ruff.log pytest.log > reports/release_watchdog/tests.txt
python scripts/release_watchdog_report.py \
  --tri-sync-json reports/release_watchdog/tri_sync.json \
  --sha reports/release_watchdog/sha.txt \
  --dirty reports/release_watchdog/dirty.txt \
  --tests reports/release_watchdog/tests.txt \
  --out reports/release_watchdog/release_report.md
```

Release `PASS` requires:

- local dirty list empty
- local full SHA equals `origin/main` full SHA
- VPS `/opt` and `/root` match the intended SHA
- VPS service is `active`
- endpoint is expected safe status; `200` is required for the live status endpoint
- selected tests and ruff are clean

Short SHA values from tri-sync are display-only. Full 40-character SHA files
control release confidence.

Final commands to run from the repo root:

```bash
# Full suite, when main is ready for release verification
python -m pytest

# Deploy command is intentionally not automated by this lane.
# Main release lane should update both VPS trees, then restart/verify service.

# Final tri-sync
python scripts/tri_sync_status.py --repo . \
  --vps-host root@49.12.7.18 \
  --ssh-key ~/.ssh/binance_futures_tool \
  --json
```

Recovery checklist:

- Dirty local: review `git status --short --untracked-files=all`; commit only intended files.
- Origin mismatch: push the intended commit after tests pass.
- VPS mismatch: deploy the intended commit to `/opt/research-agent-bot` and `/root/Research-Agent-Bot`.
- Service mismatch: inspect `systemctl status research-agent-bot.service` before any restart.
