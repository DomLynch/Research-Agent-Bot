# Static Reader Quality Gate v1

`scripts/static_reader_quality_gate.py` validates an exported static reader
`index.html` without a browser. It is not the Decentralized Web verifier and
does not validate DID, CID, signature, or registry state.

It checks:

- trust panel exists
- artifacts section exists
- JSON-LD is present and valid
- no raw non-JSON-LD script tags are present
- links are relative and traversal-safe
- referenced bundle files exist

The command prints compact JSON and exits non-zero on failure. It does not
publish, deploy, mutate bundles, or call external services.
