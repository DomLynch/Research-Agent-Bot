# Final Checkpoint Report V1

`scripts/final_checkpoint_report.py` is an offline end-game summarizer. It
does not run Git, SSH, curl, tests, or deploy commands.

Input:

```bash
python scripts/tri_sync_status.py --repo . --json > tri-sync.json
pytest ... > test-output.txt
ruff check ... >> test-output.txt
python scripts/final_checkpoint_report.py \
  --tri-sync-json tri-sync.json \
  --test-output test-output.txt \
  --out final-checkpoint.md
```

The report marks the checkpoint `PASS` only when:

- local dirty count is zero
- local state is synced with `origin/main`
- every provided VPS entry matches local HEAD and is not dirty
- provided test output has no failed/error counts, or ruff reports clean

Use this before moving from an implementation lane to commit/deploy. The script
is read-only and safe for CI or local dry runs.
