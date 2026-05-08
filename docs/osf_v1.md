# OSF V1 Publisher Boundary

Architecture decision: OSF publishing is a sibling service, not
`research-agent-bot` runtime and not Derivation Web runtime. This repository
produces AAA research artifacts, provenance events, public bundle metadata, and
readiness reports. The sibling publisher owns OSF auth, retries, rate limits,
partial-node cleanup, and DW registry write-back.

The sibling OSF publisher is PAT-only. Live mode reads `OSF_PAT` from the
publisher environment and never writes the token to snapshots, plans, results,
or error fields. OAuth is intentionally out of scope for V1.

Sibling dry-run operation:

```bash
cd /Users/domininclynch/Desktop/Business/osf-publisher
python3 -m osf_publisher.cli approved_artifact.json --out dry_report.json
```

First live smoke, after rotating any exposed PAT:

```bash
osf-publisher publish --run-dir runs/<run> --live
```

`OSF_PAT` must exist only in the sibling publisher runtime environment. OAuth is
deferred to V2.

Public reader manifest:

```bash
python scripts/researka_reader_manifest.py bundles/<run-id>
```

Derivation Web registration is intentionally separated from this repository.
The sibling publisher writes a registry record back to DW through DW's public
API after OSF returns a stable URL/DOI. See `docs/provenance_reader_v1.md` for
the offline payload schema; no outbound DW or OSF calls are made by this bot.

Public reader handoff:

```bash
python scripts/researka_reader_manifest.py runs/<run> \
  --public-url https://researka.io/topic/<topic>/<version>
```

This writes `researka_reader_manifest.json` for the future static reader. A
companion helper exposes the DW `register` payload shape; it does not call DW
or OSF.
