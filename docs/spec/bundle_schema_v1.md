# Researka Bundle Schema v1

Status: draft spec. Some files are implemented in current run bundles; reader
HTML, public registry records, and OSF records may be produced by downstream
services.

## Purpose

A Researka bundle is an immutable, inspectable snapshot of one evidence
synthesis run. It should let a reader verify what was generated, what was
audited, what was changed or quarantined, and which verdict was assigned.

## Required Core Files

Every certified bundle should include:

1. `README.md`
2. `bundle_manifest.json`
3. `full_paper.md`
4. `full_paper.audit.json`
5. `full_paper.audit.md`
6. `full_paper.final_verdict.json`
7. `full_paper.final_verdict.md`
8. `full_paper.review_patch_log.json`
9. `manifest.json`
10. `checksums.sha256`

## Conditional Files

Include when produced by the run:

- `full_paper.review_summary.md`
- `full_paper.review_patches.json`
- `full_paper.consistency.md`
- `full_paper.certification.md`
- `full_paper.arbitration_log.json`
- `numeric_claim_quarantine.json`
- `qei_quarantine.json`
- `no_regression_report.md`
- `citation.bib`
- `citation.csl.json`
- `paper.schema.jsonld`
- `trust_panel.json`
- `researka_reader_manifest.json`
- `osf_record.json`
- `dw_registry_record.json`
- `index.html`
- `versions.html`

Conditional files must be listed in `bundle_manifest.json` when shipped.

## `bundle_manifest.json`

Required fields:

- `schema_version`: `researka.bundle.v1`
- `run_id`
- `topic`
- `generated_at`
- `repo_commit`
- `topic_pack_hash`
- `files`
- `verdict_ref`
- `audit_ref`

Each file entry:

- `path`: relative path only
- `bytes`
- `sha256`
- `media_type`
- `required`: boolean

Rules:

- no absolute paths
- no `..` traversal
- no secrets or API keys
- hash after final copy, not before
- ignored/local run paths may be recorded internally but must not become public
  filesystem paths

## Source-of-Truth Rules

The manuscript is not the source of truth. The bundle must preserve structured
artifacts that support the manuscript:

- `manifest.json` for receipts, claims, tensions, evidence weights, and topic
  metadata
- audit JSON for deterministic checks
- review patch log for reviewer changes, strips, flags, and arbitration counts
- quarantine files for rejected public numerics or rows
- final verdict JSON for machine-readable maturity state

## Service Boundaries

- Research Agent Bot produces run artifacts and bundle metadata.
- Derivation Web records provenance and registry steps.
- OSF publisher is a sibling service that registers approved artifacts and
  writes OSF metadata back through provenance.
- Public reader renders verified bundles and links to provenance/OSF records.

The bundle schema is independent of any one renderer or registry.
