# JSON-LD and Citation Spec v1

Status: draft.

Paper pages and OSF records should share citation metadata, but OSF publishing
is performed by a sibling service. The bot may generate citation files and
JSON-LD; it does not publish them.

## `paper.schema.jsonld`

Use Schema.org `ScholarlyArticle`.

Required fields:

- `@context`: `https://schema.org`
- `@type`: `ScholarlyArticle`
- `name`
- `description`
- `dateCreated`
- `publisher`: `Researka`
- `identifier`: run id
- `url`: canonical reader URL when known
- `isBasedOn`: source run provenance URL when known

Optional verified fields:

- `doi`
- `sameAs`
- `citation`

Do not emit DOI or OSF URL unless the sibling publisher/verifier has returned a
stable record.

## Citation Files

Ship both:

- `citation.bib`
- `citation.csl.json`

Minimum fields:

- title/name
- author or organization (`Researka`)
- issued/generated date
- publisher
- URL
- run id

CSL may be a single object or single-item array. BibTeX should use one stable
entry id derived from topic and run id.

## OSF Record Mapping

The sibling OSF publisher maps bundle fields to OSF metadata. It must preserve:

- title
- abstract/description
- creators/contributors
- tags/topic
- run id
- provenance URL
- bundle checksum

OSF DOI placement in the reader trust panel is deferred until OSF returns a
stable DOI.

## Fixture Validation

Minimum JSON-LD fixtures should cover:

- one paper page using `ScholarlyArticle`
- one OSF registry record returned by the sibling publisher
- one provenance chain link under `https://provenance.researka.org/`

All fixtures must parse as JSON and include the required fields above. Fixture
validation does not prove DOI ownership, OSF publication, or evidence validity.
