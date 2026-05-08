# Open Spec + Methods Package Audit

## Decisions Normalized

- No active PROSPERO path. Protocol registration is historical/deferred only.
- OSF publishing is a sibling service, not bot runtime.
- Canonical provenance surface is `https://provenance.researka.org/`.
- Research Agent Bot remains synthesis-only: it produces local artifacts,
  public bundle metadata, and provenance payloads.
- Reader/public pages are static bundle consumers, not evidence arbiters.
- DW/provenance and OSF state are downstream infrastructure checks, not evidence
  validity guarantees.

## Specs Added or Tightened

- `docs/bundle_schema_v1.md`: 19-file bundle, optional files, hashes, run
  provenance.
- `docs/arbitration_v2.md`: writer/reviewer/arbitrator roles, Granite
  judge-only constraint, fail-closed audit log.
- `docs/verdict_l0_l8_spec_v1.md`: exact L0-L8 maturity criteria.
- `docs/jsonld_citation_spec_v1.md`: Schema.org, BibTeX, CSL-JSON, OSF mapping.
- `docs/methodology_paper_outline_v1.md`: paper outline, validation study,
  limits.
- `docs/osf_publisher_service_v1.md`: updated to sibling publisher +
  `provenance.researka.org` boundary.

## Stale Claims

Removed/normalized:

- bot -> DW -> OSF linear flow
- any active PROSPERO implication in new specs
- any bot-side live OSF publishing implication in new specs

Still present but intentionally scoped:

- existing docs mention Cochrane/PRISMA only as negative caveats or deferred
  non-claims.
- existing release watchdog references OSF placement checks to prevent bot-side
  leakage.

## Open Risks

- Bundle Schema 1.0 is a spec, not yet enforced by a generator.
- Verdict L7/L8 criteria need real cross-model/cross-corpus validation reports.
- Citation exports need implementation and fixture validation.
- Provenance registry API contract should be checked against the live service
  before publication automation.

## Next Validation

1. Add bundle-manifest fixture tests once generator exists.
2. Validate JSON-LD with a schema.org-compatible parser.
3. Run a dry provenance registration against a fixture endpoint.
4. Run human review on the methodology paper outline before external use.
