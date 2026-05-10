# Researka Database Expansion Decision — 2026-05-10

## Decision
Do **not** expand `papers_primary` yet.

## Why
The first aging-specific benchmark shows the database is useful but not ready
for a larger hot index decision:

- 25/25 questions returned hits.
- 20/25 questions matched the expected topic terms.
- 14/25 returned more than one retrieval lane.
- The five misses all still returned hits, but mostly from the unconstrained
  semantic lane.

Live spot checks showed this is a query/ranking problem before it is a corpus
size problem. Example: direct `metformin` and `semaglutide` searches return
relevant records, while longer Elicit-style prompts can fall into semantic-only
off-topic results.

## Rejected For Now
- Expanding to 50-150K biomedical elite immediately.
- Expanding toward top 1-3% of the raw Storage Box universe.
- Calling this an Elicit-killer benchmark.

## Next Fix Before Expansion
Tighten `/api/v1/search` ranking so semantic hits are lexically anchored or
reranked against query terms before they can dominate long prompts.

Then rerun:

```bash
python scripts/researka_database_benchmark.py --limit 8 \
  --output reports/researka_database_benchmark_latest.json
```

## Expansion Gate
Reconsider hot-index expansion only if the rerun still misses important aging
questions after the semantic/ranking fix.
