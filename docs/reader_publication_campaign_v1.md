# Reader Publication Campaign v1

This campaign validates local static reader exports. It is separate from
Derivation Web verification and does not publish, deploy, register, or mutate
source run artifacts.

Checks performed:

- export at least five representative readers
- run `static_reader_quality_gate.py` on each `index.html`
- verify artifact links are relative and files exist in the exported bundle
- verify JSON-LD parses as `ScholarlyArticle`
- verify trust-panel presence
- verify path traversal, absolute links, and raw script leakage through tests
- record public-readiness scores in `reports/reader_publication/summary.json`

Campaign output lives under `reports/reader_publication/`.

Public readiness rule:

- static reader quality gate must pass
- all copied artifact links must exist
- JSON-LD must parse
- trust panel must exist
- audit P1 must pass
- no unsafe links or raw non-JSON-LD scripts may appear

This campaign currently treats DW verification, OSF DOI status, CID proof,
signature proof, and gateway availability as out of scope.
