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

Derivation Web registration is a follow-up step, not part of the OSF publisher. The OSF publisher writes OSF artifacts; it does not call Derivation Web. DW is append-only, so outbound registration is a separate explicit CLI step after the public bundle and reader manifest exist.

Dry-run payload:

```bash
python scripts/dw_register_public_bundle.py bundles/<run-id>/researka_reader_manifest.json
```

Live POST is opt-in and mock-tested only in this repo:

```bash
DW_API_URL=https://provenance.researka.org/api/register-public-bundle \
DW_API_TOKEN=... \
python scripts/dw_register_public_bundle.py bundles/<run-id>/researka_reader_manifest.json --live
```

The CLI reads `DW_API_TOKEN` only from the environment. It never writes or prints the token. `DW_API_URL` is the exact append-only registration endpoint to POST to; core publish paths do not use it.

Expected endpoint behavior:

- Method: `POST`
- Headers: `Authorization: Bearer <env token>`, `Content-Type: application/json`, `Idempotency-Key: <payload idempotency_key>`
- Body: the JSON payload below
- Success: any 2xx JSON response; optional response `id` is surfaced as `response_id`
- Failure: non-2xx exits nonzero without printing the response body or token

Payload shape:

```json
{
  "schema": "derivation_web.register_public_bundle.v1",
  "idempotency_key": "dw-register:<sha256>",
  "reader_manifest_schema": "researka.reader_manifest.v1",
  "run_id": "run-id",
  "public_url": "https://osf.io/example/",
  "osf": {"node_id": "abc123", "url": "https://osf.io/abc123/", "doi": null},
  "file_count": 2,
  "aggregate_files": [{"path": "paper.md", "sha256": "...", "size": 123}],
  "dw": {
    "append_only": true,
    "artifact": {"kind": "registry_record"},
    "step": {"step_type": "register"}
  }
}
```

The `osf` object is optional metadata. `node_id`, `url`, and `doi` may be `null`; Derivation Web registration does not require an OSF DOI.

The idempotency key is derived from `run_id` plus the aggregate public file hashes, so repeated registration attempts for the same public bundle are stable without storing local state.
