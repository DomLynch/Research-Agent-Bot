# Journal Surface Fix v2

Universal hardening for journal-surface public manuscripts.

## What Changed

- Public Methods now describes evidence selection and controls, not operational
  provenance.
- Journal surface gate now blocks public-body template/meta phrases and repeated
  long paragraphs.
- Appendix splicing now wraps bare Search Provenance under
  `## Publication Appendix`.
- Named deterministic backfill blocks are document-global idempotent.

## What Did Not Change

Historical run artifacts were not edited. They require rerun or regeneration.

## Next Rerun Order

1. GLP1
2. Creatine
3. Metformin
4. Omega3
5. Statins
6. Rapamycin
7. Caloric restriction

## Remaining Risk

Duplicate paragraph detection is heuristic. It is scoped to public body prose,
uses long paragraphs only, and ignores tables/headings/appendix. The depth-floor
extension path is deferred because a full fix needs multiple distinct safe
paragraph variants.
