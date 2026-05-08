# OSF Independent Service

Status: architecture decision.

OSF publishing is a sibling service. It does not live inside Research Agent Bot
and does not live inside Derivation Web.

## Boundary

```text
Research Agent Bot -> Derivation Web -> osf-publisher -> OSF -> Derivation Web
```

- Research Agent Bot generates evidence artifacts, bundles, and provenance
  payloads.
- Derivation Web records append-only provenance and registry steps.
- `osf-publisher` polls or receives approved artifact records, registers them
  with OSF, and writes a registry record back to Derivation Web.

## Why Separate

OSF publishing has external-service concerns:

- PAT auth
- retries
- API failures
- rate limits
- partial OSF nodes
- DOI/URL state
- idempotency

Those concerns should not change the synthesis engine or the append-only
provenance ledger.

## V1 Scope

V1 should be PAT-only and idempotent:

- read `OSF_PAT` only from the sibling service environment
- accept a run/bundle/provenance record as input
- create or update one OSF record
- write `{osf_url, doi, node_id, checksum, published_at}` back as a registry
  record through the Derivation Web API
- never write credentials to logs, bundles, or failure artifacts

Bundle file upload may be deferred to V1.1. A minimal V1 can publish metadata
and registry linkage first.

OAuth developer-app flow is deferred to V2. V1 is for a controlled publisher
owned by the operator, not multi-user delegated publishing.

## Bot Contract

Research Agent Bot may emit:

- bundle manifest
- reader manifest
- provenance payload
- OSF dry-run/readiness report

It must not perform live OSF calls in the synthesis path.
