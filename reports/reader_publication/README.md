# Reader Publication Campaign

Static reader exports were generated locally under `reports/reader_publication/static/`
for six representative synthesis runs. No deploy, DW registration, or source
run-artifact mutation was performed.

## Results

| Run | Topic | Gate | Audit | P1 | Links | JSON-LD | Trust | Score | Public static ready |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z | caloric_restriction | pass | 10.0 | true | ok | ok | ok | 100 | yes |
| synthesis-glp1-v06-CONTRIBFIX-2026-05-08T01-22-44Z | glp1 | pass | 10.0 | true | ok | ok | ok | 100 | yes |
| synthesis-metformin-v06-FINAL-2026-05-05T21-15-00Z | metformin | pass | 6.9 | false | ok | ok | ok | 80 | no |
| synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z | omega3 | pass | 10.0 | true | ok | ok | ok | 100 | yes |
| synthesis-rapamycin-v06-PATH2RICHFIX3-2026-05-08TCLASSIFIER | rapamycin | pass | 10.0 | true | ok | ok | ok | 100 | yes |
| synthesis-statins-v06-PATH2RICHFIX2-2026-05-08T09-40-00Z | statins | pass | 9.3 | false | ok | ok | ok | 90 | no |

`summary.json` is the machine-readable report. All six exports passed the
static reader quality gate. Metformin and statins are withheld from public-ready
status because their audit P1 status is false.

## Public Reader vs DW Verifier

The static reader validates a public-readable HTML bundle: paper rendering,
trust panel, artifact links, JSON-LD, version stub, relative links, copied
bundle files, and script-leak resistance. It does not validate DID identity,
CID/content addressing, signatures, registry inclusion, gateway availability,
or OSF/DOI state. Those remain DW-verifier concerns.

## Route Shape

- `/reader/` collection index
- `/reader/<topic>/` latest public-ready run for a topic
- `/reader/<topic>/<run-id>/` immutable run export
- `/reader/<topic>/<run-id>/manifest.json` bundle manifest
- `/reader/<topic>/<run-id>/download/` optional bundle download entrypoint

## Missing for Real Public Launch

- Collection index and topic pages.
- Search index v1: `topic`, `run_id`, `title`, `thesis`, `audit_score`,
  `receipt_count`, `updated_at`, and public-ready flag.
- Multi-version index per topic, not just one local `versions.html`.
- Citation export: BibTeX, CSL-JSON, and schema.org fields from manifest.
- Bundle download manifest with file name, size, sha256, media type.
- OSF DOI placement in the trust panel once available.
- Provenance URL placement for source run, DW CID, and verification report.
- Minimal CSS for readable long papers.
- DW verifier panel kept separate from static reader gate.

## Minimal researka.io Adapter

1. Accept a validated static-reader output directory.
2. Refuse if `quality_gate.json.passed != true` or `ready_public_static != true`.
3. Copy to immutable static route `/reader/<topic>/<run-id>/`.
4. Regenerate `/reader/index.json` and `/reader/index.html`.
5. Serve as static files only; no framework or client bundle required.
6. Add DW/OSF badges only from separate verifier outputs.

Exact first local publish command shape:

```bash
rsync -av --delete reports/reader_publication/static/<run-id>/ public/reader/<topic>/<run-id>/
```

Use only after replacing `<run-id>` and `<topic>` with a row where
`ready_public_static` is true.

## Next 5 Build Tasks

1. Build collection index generator from `summary.json`.
2. Add bundle manifest generator with sha256 and file sizes.
3. Add citation export files.
4. Add topic-level version index.
5. Add DW verifier ingestion as a separate trust-panel subsection.
