# Spec Validation 2026-05-08

Status: fail-closed. JSON-LD fixtures pass V1 shape checks; sample synthesis
run directories are not yet Bundle Schema 1.0 public bundles.

## Scope

- Validator: `scripts/spec_bundle_validator.py`
- Tests: `tests/test_spec_bundle_validator.py`
- Fixtures:
  - `reports/spec_validation_2026_05_08/paper.schema.jsonld`
  - `reports/spec_validation_2026_05_08/osf_record.schema.jsonld`
  - `reports/spec_validation_2026_05_08/provenance_link.schema.jsonld`
- Machine report: `reports/spec_validation_2026_05_08/spec_validation_2026_05_08.json`

## V1 Checks

- required 19-file bundle inventory
- `bundle_manifest.json` required fields
- manifest file paths are relative and non-traversing
- listed manifest files exist
- listed file bytes and SHA-256 match when present
- JSON-LD parses as JSON
- JSON-LD includes required Schema.org/publication fields

## Bundle Checks

| Path | Passed | Missing required files |
|---|---:|---|
| `runs/synthesis-urolithin_a-v06-2026-05-08T12-19-07Z` | False | README.md, bundle_manifest.json, provenance.json, citation.bib, citation.csl.json, paper.schema.jsonld, trust_panel.json, checksums.sha256, versions.html, index.html |
| `runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z` | False | README.md, bundle_manifest.json, provenance.json, citation.bib, citation.csl.json, paper.schema.jsonld, trust_panel.json, checksums.sha256, versions.html, index.html |
| `runs/synthesis-metformin-v06-public-final-2026-05-03T17-41-44Z` | False | README.md, bundle_manifest.json, provenance.json, citation.bib, citation.csl.json, paper.schema.jsonld, trust_panel.json, checksums.sha256, versions.html, index.html |

## JSON-LD Checks

| Path | Passed | Issues |
|---|---:|---|
| `reports/spec_validation_2026_05_08/paper.schema.jsonld` | True | none |
| `reports/spec_validation_2026_05_08/osf_record.schema.jsonld` | True | none |
| `reports/spec_validation_2026_05_08/provenance_link.schema.jsonld` | True | none |

## Stale-Language Audit

Grep rechecked docs/reports for:

- active protocol-registration claims
- legacy manual-publication wording
- legacy derivation-domain canonical wording
- old bot-to-OSF canonical flow

Remaining PROSPERO hits are negative caveats only:

- `reports/open_spec_methods_package.md`
- `docs/methodology_paper_outline_v1.md`

No stale derivation-domain canonical language was found in docs/reports
markdown.

## Implementation Boundaries

- Bot: synthesis-only local artifact producer.
- Provenance: canonical public registry at `https://provenance.researka.org/`.
- OSF publisher: sibling service that publishes or plans OSF records after
  provenance/bundle approval.
- Reader: static public consumer of verified bundles; not a DW verifier and not
  an evidence validity engine.

## Open Blockers

- Existing synthesis run directories are not yet full Bundle Schema 1.0 public bundles.
- `bundle_manifest.json`, `provenance.json`, citation exports, trust panel, checksums, and reader files must be generated before public publication.
- Sample bundles cannot claim publication readiness until the missing 10 public
  files are generated and hashed.
- OSF DOI/URL fields must stay absent until the sibling publisher returns a
  verified stable record.

## Evidence Commands

```bash
python3 scripts/spec_bundle_validator.py \
  --bundle runs/synthesis-urolithin_a-v06-2026-05-08T12-19-07Z \
  --bundle runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z \
  --bundle runs/synthesis-metformin-v06-public-final-2026-05-03T17-41-44Z \
  --jsonld reports/spec_validation_2026_05_08/paper.schema.jsonld \
  --jsonld reports/spec_validation_2026_05_08/osf_record.schema.jsonld \
  --jsonld reports/spec_validation_2026_05_08/provenance_link.schema.jsonld \
  --json-out reports/spec_validation_2026_05_08/spec_validation_2026_05_08.json \
  --md-out reports/spec_validation_2026_05_08.md
python3 -m pytest tests/test_spec_bundle_validator.py
python3 -m ruff check scripts/spec_bundle_validator.py tests/test_spec_bundle_validator.py
git diff --check
```
