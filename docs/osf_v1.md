# OSF V1 Publisher

The OSF publisher is PAT-only. Live mode reads `OSF_PAT` from the environment and never writes the token to the snapshot, plan, result, or error fields. OAuth is intentionally out of scope for V1.

Default operation is safe:

```bash
python scripts/osf_publish.py --run-dir runs/<run>
```

Dry-run writes `bundle_snapshot.json` and `osf_publish_plan.json`. Per-file `file_url` values stay `null` until live upload.

Live mode requires both an explicit CLI flag and an explicit environment gate.
It reads the PAT from the process environment:

```bash
OSF_PUBLISH_LIVE=1 python scripts/osf_publish.py --run-dir runs/<run> --live
```

If `osf_publish_result.json` already exists, the publisher skips the run. Use `--force` only when intentionally replacing a prior result. Generated publisher artifacts are excluded from the uploaded snapshot.

Cron scaffold:

```bash
python scripts/osf_publish_cron.py --runs-dir runs
OSF_PUBLISH_LIVE=1 python scripts/osf_publish_cron.py --runs-dir runs --live
```

The cron path uses the same idempotency rule and PAT-only live path. OAuth is
deferred to V2.

Public reader manifest:

```bash
python scripts/researka_reader_manifest.py bundles/<run-id>
```

Derivation Web registration is intentionally separated from the publisher. See `docs/provenance_reader_v1.md` for the offline payload schema; no outbound DW calls are made by `osf_publish.py`.

Public reader handoff:

```bash
python scripts/researka_reader_manifest.py runs/<run> \
  --public-url https://researka.io/topic/<topic>/<version>
```

This writes `researka_reader_manifest.json` for the future static reader. A
companion helper exposes the DW `register` payload shape; it does not call DW
or OSF.
