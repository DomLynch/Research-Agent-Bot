# OSF/DW Pipeline Check v1

`scripts/osf_dw_pipeline_check.py` is a dry-run-only verifier for one run
directory. It builds local payload shapes for:

- OSF publish plan
- public reader manifest
- Derivation Web register payload

It never reads `OSF_PAT`, `DW_API_TOKEN`, or performs network calls.

## Usage

```bash
python scripts/osf_dw_pipeline_check.py runs/<run> \
  --public-url https://researka.io/topic/example/v1 \
  --osf-node-id abc123 \
  --osf-url https://osf.io/abc123/
```

## Validations

- OSF plan has an `idempotency_key`.
- DW payload has an `idempotency_key`.
- Generated publisher artifacts are not planned for upload.
- Reader manifest and DW payload contain `public_url`.
- DW payload contains `osf.node_id`, `osf.url`, and `osf.doi` slots.
- OSF and DW idempotency keys are stable across repeated dry builds.
- Report body contains no known token/header markers.

## Failure Modes

- Missing run directory: exits `2`; no network call is attempted.
- Missing `public_url`: CLI rejects the command before building payloads.
- Missing `OSF_PAT`, `DW_API_TOKEN`, auth failure, or network failure: not
  applicable to this verifier. Live publish/register commands own those gates.
- Generated artifacts in either the OSF upload plan or reader manifest: exits
  `1` with an error in the JSON report.

Exit code is `0` when all checks pass, `1` for validation failures, and `2`
for local filesystem errors.
