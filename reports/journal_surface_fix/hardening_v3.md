# Journal Surface Hardening v3

## Scope

Second-pass hardening only. No topic-specific Python and no manuscript artifacts
edited.

## Public Body Rules

The journal surface gate scans only text before the first appendix/provenance
boundary:

- `## Publication Appendix`
- `## Search Provenance...`
- `## AI-Use Disclosure` / `## AI Disclosure`
- `## Researka Submitter Block`
- `## Data and Code Availability`
- `## References`

Within that public body it now blocks:

- operational/meta provenance phrases
- placeholder/fallback prose
- malformed public QEI rows
- long duplicate prose paragraphs
- citation placeholder artifacts
- standalone hedge fragments

The same strings remain allowed after the appendix boundary.

## False-Positive Controls

- Duplicate detection ignores headings, tables, and `_Cited:` lines.
- Duplicate detection requires at least 30 tokens and at least 20 distinct tokens.
- Duplicate scoring uses Jaccard overlap across token sets, not substring matching.
- Valid plain Author-Year tokens such as `Konopka 2019` are preserved by the
  consistency fixer.

## Validation

- Ruff passed twice.
- Targeted pytest passed twice: 144 tests.
