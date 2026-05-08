# Provenance Canonical URL v1

Status: repo-side documentation. DNS/nginx changes live in the Derivation Web
deployment repo, not in Research Agent Bot.

## Canonical Host

Use:

```text
https://provenance.researka.org/
```

for public provenance, registry, and verifier links.

## Legacy Host

`dw.domlynch.com` may remain as an operational alias, but new Research Agent Bot
docs, JSON-LD, reader manifests, and public reports should prefer
`provenance.researka.org`.

## Boundary

Research Agent Bot may emit provenance payloads and public bundle metadata. It
does not mutate Derivation Web DNS, nginx, certificates, database state, or
append-only chain records.

## Verification

Before public launch, verify in the Derivation Web project:

- DNS A/AAAA record resolves.
- TLS certificate covers `provenance.researka.org`.
- `/health` or equivalent endpoint returns 200.
- old host remains alias or redirects by explicit operator choice.
- generated bundle links use only the canonical host.
