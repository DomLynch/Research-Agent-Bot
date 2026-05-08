# OSF V1 Publisher

Architecture decision: OSF publishing is a sibling service, not
`research-agent-bot` runtime and not Derivation Web runtime. This repository can
produce exportable bundles and dry-run publisher plans, but the live publisher
owns OSF auth, retries, rate limits, partial-node cleanup, and DW registry
write-back.

The sibling OSF publisher is PAT-only. Live mode reads `OSF_PAT` from the
publisher environment and never writes the token to snapshots, plans, results,
or error fields. OAuth is intentionally out of scope for V1.

Legacy local dry-run operation is safe:

```bash
python scripts/osf_publish.py --run-dir runs/<run>
```

Dry-run writes `bundle_snapshot.json` and `osf_publish_plan.json`. Per-file `file_url` values stay `null` until live upload.

Live publishing should move to the sibling service. If the legacy local CLI is
used for one smoke, it requires both an explicit CLI flag and an explicit
environment gate, and reads the PAT from the process environment:

```bash
osf-publisher publish --run-dir runs/<run> --live
```

If `osf_publish_result.json` already exists, the publisher skips the run. Use `--force` only when intentionally replacing a prior result. Generated publisher artifacts are excluded from the uploaded snapshot.

Legacy cron scaffold:

```bash
python scripts/osf_publish_cron.py --runs-dir runs
OSF_PUBLISH_LIVE=1 python scripts/osf_publish_cron.py --runs-dir runs --live
```

The cron path is a prototype contract check, not the long-term deployment home.
OAuth is deferred to V2.

Public reader manifest:

```bash
python scripts/researka_reader_manifest.py bundles/<run-id>
```

Derivation Web registration is intentionally separated from this repository.
The sibling publisher writes a registry record back to DW through DW's public
API after OSF returns a stable URL/DOI. See `docs/provenance_reader_v1.md` for
the offline payload schema; no outbound DW calls are made by `osf_publish.py`.

Public reader handoff:

```bash
python scripts/researka_reader_manifest.py runs/<run> \
  --public-url https://researka.io/topic/<topic>/<version>
```

This writes `researka_reader_manifest.json` for the future static reader. A
companion helper exposes the DW `register` payload shape; it does not call DW
or OSF.
