# Deploy Checkpoint V1

Read-only status:

```bash
python scripts/tri_sync_status.py --repo .
python scripts/tri_sync_status.py --repo . \
  --vps-host root@49.12.7.18 \
  --ssh-key ~/.ssh/binance_futures_tool
```

The CLI reports:

- local `HEAD`
- local `origin/main`
- working-tree dirty count
- ahead/behind state
- optional VPS `/opt/research-agent-bot` and `/root/Research-Agent-Bot` heads
- optional VPS service status and local dashboard HTTP code

Deploy checkpoint before moving to the next task:

1. Local targeted tests pass.
2. Local full suite passes when the change warrants it.
3. `ruff check` passes.
4. Working tree contains only intended files.
5. Commit is on MacBook.
6. Commit is pushed to GitHub `origin/main`.
7. VPS `/opt/research-agent-bot` is at the same SHA.
8. VPS `/root/Research-Agent-Bot` is at the same SHA.
9. `research-agent-bot.service` is active.
10. Dashboard endpoint returns expected safe status.

This document is only a checklist. `tri_sync_status.py` never mutates Git,
never restarts services, and never deploys.
