# Bundle Schema 1.0

Status: draft infrastructure spec.

The bot is synthesis-only. It writes local run artifacts and public bundle
metadata. OSF publication is owned by a sibling service. Public provenance is
registered at `https://provenance.researka.org/`.

## Required 19-File Bundle

1. `README.md`
2. `bundle_manifest.json`
3. `full_paper.md`
4. `full_paper.audit.json`
5. `full_paper.audit.md`
6. `full_paper.final_verdict.md`
7. `full_paper.review_summary.md`
8. `full_paper.review_patches.json`
9. `full_paper.review_patch_log.json`
10. `full_paper.consistency.md`
11. `manifest.json`
12. `provenance.json`
13. `citation.bib`
14. `citation.csl.json`
15. `paper.schema.jsonld`
16. `trust_panel.json`
17. `checksums.sha256`
18. `versions.html`
19. `index.html`

## Optional Files

- `full_paper.certification.md`
- `no_regression_report.md`
- `quality_gate.json`
- `reader_deep_report.json`
- `dw_verifier.json`
- `osf_record.json`

Optional files must be listed in `bundle_manifest.json` when shipped.

## `bundle_manifest.json`

Required top-level fields:

- `schema_version`: `"bundle_schema.v1"`
- `run_id`
- `topic`
- `generated_at`
- `source_run_dir`
- `canonical_url`
- `files`
- `provenance`

Each file entry:

- `path`: relative path only
- `bytes`
- `sha256`
- `media_type`
- `required`: boolean

Rules:

- no absolute paths
- no `..` traversal
- no secrets
- hash every shipped file after final copy
- `source_run_dir` is provenance metadata, not a public filesystem path

## Run Provenance

`provenance` records:

- repo commit
- dirty/clean state
- command shape
- topic pack id/hash when available
- model names used for generation/review
- audit result path
- final verdict path
- optional provenance registry URL

Do not include OSF credentials, DW API credentials, local usernames, or private
machine paths.

## Implementation Boundaries

- Bot: produces synthesis run artifacts, bundle metadata, and provenance
  payloads; it does not publish to OSF or mutate public registry state.
- Provenance registry: owns canonical public provenance URLs under
  `https://provenance.researka.org/` and records immutable bundle references.
- OSF publisher: sibling service that reads approved provenance/bundle records,
  performs OSF planning or publication, and writes verified OSF metadata back to
  provenance.
- Reader: static public surface that renders a verified bundle and links to
  provenance/OSF records; it is not an evidence verifier.
