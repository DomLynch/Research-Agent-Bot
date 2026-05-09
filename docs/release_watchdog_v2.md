# Release Watchdog V2

Lane F deep watchdog is read-only. It reports release readiness from captured
artifacts and does not commit, push, deploy, restart, or mutate remote hosts.

Capture:

```bash
mkdir -p reports/release_watchdog_deep
git status --short --untracked-files=all > reports/release_watchdog_deep/status.txt
git diff --cached --name-only > reports/release_watchdog_deep/staged.txt
{ printf 'local_full='; git rev-parse HEAD; printf 'origin_full='; git rev-parse origin/main; } > reports/release_watchdog_deep/sha.txt
python scripts/tri_sync_status.py --repo . --vps-host root@49.12.7.18 --ssh-key ~/.ssh/binance_futures_tool --json > reports/release_watchdog_deep/tri_sync.json
python scripts/release_watchdog_deep.py \
  --status reports/release_watchdog_deep/status.txt \
  --sha reports/release_watchdog_deep/sha.txt \
  --tri-sync-json reports/release_watchdog_deep/tri_sync.json \
  --out-json reports/release_watchdog_deep/report.json \
  --out-md reports/release_watchdog_deep/report.md
```

Release `PASS` requires:

- no dirty paths
- local full SHA equals `origin/main` full SHA
- VPS short SHA is a prefix of local full SHA
- VPS service is `active`
- endpoint is expected; `200` is required for the live status endpoint
- no secret scan hits
- no large generated file warnings
- no OSF auth/API placement warnings inside bot runtime or bot-side publisher
  scripts; live OSF publishing belongs in the sibling publisher service
