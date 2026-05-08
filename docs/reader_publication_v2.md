# Reader Publication v2

The reader site is separate from the bot and separate from DW verification.
The bot should only export static bundles and machine-readable manifests. A
static-site adapter can publish those bundles later if independent reader and
DW gates pass.

## V2 Readiness Gates

- `index.html` passes static reader quality gate.
- trust panel exists and audit P1 passed.
- JSON-LD parses and carries article metadata.
- every link is relative and traversal-safe.
- every referenced file exists in the exported bundle.
- `bundle_manifest.json` lists copied files with `sha256`, size, and media type.
- `citation.bib` and `citation.csl.json` exist.
- topic index exists at `/reader/<topic>/`.
- version index lists every immutable run for the topic.

## Minimum Public Page Metadata

- topic
- run id
- title or thesis
- generated date
- paper path
- audit score and audit P1 status
- receipt count
- tension count
- final verdict path
- certification path when available
- canonical public URL after publication

## Trust Panel JSON Summary Draft

```json
{
  "run_id": "synthesis-topic-v06-...",
  "topic": "topic",
  "audit": {"score_out_of_10": 10.0, "p1_pass": true},
  "quality_gate": {"passed": true, "errors": []},
  "bundle": {"manifest_path": "bundle_manifest.json", "sha256_verified": true},
  "citations": {"bibtex": "citation.bib", "csl_json": "citation.csl.json"},
  "dw": {"status": "not_checked", "report_path": null},
  "osf": {"doi": null, "status": "not_checked"}
}
```

`dw` and `osf` fields are placeholders until independent verifiers populate
them. The reader must not infer those statuses.

## Route Shape

- `/reader/` collection index
- `/reader/index.json` search/index data
- `/reader/<topic>/` topic landing page with latest ready version
- `/reader/<topic>/versions.html` version history
- `/reader/<topic>/<run-id>/` immutable reader bundle
- `/reader/<topic>/<run-id>/bundle_manifest.json`
- `/reader/<topic>/<run-id>/citation.bib`
- `/reader/<topic>/<run-id>/citation.csl.json`

## Search Index v1

Use one static JSON file with:

- topic
- run id
- title
- thesis/abstract snippet
- generated date
- audit score and P1 status
- receipt count
- tension count
- ready flag
- canonical URL

No client framework is required; a static HTML page can filter this JSON later.

## Citation Exports

V2 needs lightweight BibTeX and CSL-JSON generated from manifest metadata.
Required fields: title/topic, generated date, canonical URL, publisher
`Researka`, and run id. DOI/OSF fields should be blank unless a verifier
provides them.

Checklist:

- BibTeX file exists and has one stable entry id.
- CSL-JSON file exists and parses as a list or object.
- Both exports include topic/title, run id, generated date, publisher, and URL.
- DOI is omitted unless OSF/DOI verification provides it.

## Topic and Version Indexes

Checklist:

- `/reader/index.json` contains every public-ready bundle.
- `/reader/<topic>/index.html` links to the latest ready bundle.
- `/reader/<topic>/versions.html` lists every immutable run id for that topic.
- Index links are relative and covered by the static quality gate.


## Bundle Integrity

`bundle_manifest.json` should include every shipped artifact:

- relative path
- byte size
- sha256
- media type

DW CID/signature verification remains separate and should appear as a distinct
trust-panel subsection only after the DW verifier emits a result.

## Current Build Slice

`scripts/reader_publication_deep_report.py` is read-only. It reports missing
v2 pieces against existing static exports; it does not generate the missing
assets and does not publish.
