# Provenance Reader V1

`scripts/researka_reader_manifest.py` emits a deterministic public-reader manifest for a run or exported bundle.

```bash
python scripts/researka_reader_manifest.py bundles/<run-id> \
  --public-url https://researka.io/topic/<topic>/<version>
```

The manifest contains relative paths, sizes, sha256 hashes, file count, total size, Schema.org JSON-LD, public URL, and entrypoints for paper, certification, audit, run manifest, and citation registry when present. It excludes secret-like paths and generated publisher artifacts:

- `bundle_snapshot.json`
- `osf_publish_plan.json`
- `osf_publish_result.json`
- `researka_reader_manifest.json`

Schema: `researka.reader_manifest.v1`.

Derivation Web registration is a follow-up step, not part of the OSF publisher. The helper exposes a payload shape only:

```json
{
  "schema": "derivation_web.register_public_bundle.v1",
  "reader_manifest_schema": "researka.reader_manifest.v1",
  "run_id": "run-id",
  "public_url": "https://osf.io/example/",
  "osf": {"node_id": "abc123", "url": "https://osf.io/abc123/", "doi": null},
  "file_count": 2,
  "aggregate_files": [{"path": "paper.md", "sha256": "...", "size": 123}]
}
```

No outbound Derivation Web call is made by the core publisher or reader manifest helper.
