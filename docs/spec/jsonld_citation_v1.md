# JSON-LD and Citation Spec v1

Status: draft spec for public reader, provenance, and OSF handoff metadata.
This spec does not prove DOI ownership or OSF publication.

## JSON-LD Object

Use Schema.org `ScholarlyArticle`.

Required fields:

- `@context`: `https://schema.org`
- `@type`: `ScholarlyArticle`
- `name`
- `description`
- `dateCreated`
- `publisher`: `Researka`
- `identifier`: run id
- `version`: run/version label
- `isBasedOn`: provenance URL or run identifier when available

Optional verified fields:

- `url`: public reader URL
- `doi`: only after verified OSF/DOI response
- `sameAs`: provenance URL, OSF URL, GitHub commit URL, reader URL
- `citation`: cited source records or citation registry reference
- `license`
- `author`

Do not emit an OSF DOI, OSF URL, or public provenance URL unless the relevant
sibling service has returned and recorded it.

## CSL JSON

Minimum fields:

- `type`: `article`
- `title`
- `author` or `institution`
- `issued`
- `publisher`
- `URL`
- `id`: stable topic/run id

Recommended fields when verified:

- `DOI`
- `version`
- `abstract`
- `keyword`

## BibTeX

Use one deterministic entry id:

```bibtex
@article{researka_<topic>_<run_id>,
  title = {...},
  author = {{Researka}},
  year = {...},
  url = {...}
}
```

Add `doi` only after verified publication. Do not synthesize a DOI-like string.

## Provenance and OSF Mapping

The sibling OSF publisher should preserve:

- title
- description/abstract
- creators or organization
- topic tags
- run id
- bundle checksum
- provenance registry link

The public reader should render citation exports from verified bundle metadata,
not from local runtime state.

## Validation

Fixture validation should confirm:

- valid JSON-LD parse
- required fields present
- no local absolute paths
- no secrets
- no DOI unless an `osf_record` or equivalent verified registry object exists
