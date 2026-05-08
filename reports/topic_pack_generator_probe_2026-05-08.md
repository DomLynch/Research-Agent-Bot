# Topic Pack Generator Probe — 2026-05-08

## Scope

This lane added a dry-run topic-pack generator prototype only.
It does not replace curated TOML packs.
It does not write DB records.
It does not expose a public API.
It does not run retrieval.

## Implemented

- `GeneratedTopicPack`: frozen dataclass with topic, slug, tier, status,
  candidate cap, aliases, retrieval terms, and validation errors.
- `RetrievalCounts`: frozen dataclass for later retrieval feedback.
- `AdaptiveExpansionPlan`: frozen dataclass returned by pure expansion hooks.
- Deterministic tier labels:
  - `mainstream`
  - `adjacent`
  - `emerging`
  - `contested`
  - `pseudo`
- Strict `proceed` / `stop` status:
  - pseudo topics stop with candidate cap `0`
  - proceeding topics must have positive candidate cap
- TOML-style output via `to_topic_pack_dict()`, matching current loader field
  names such as `topic`, `class_`, `aliases`, `retrieval`, and
  `known_role_overrides`.
- Pure precursor expansion for known biomedical topics, currently including
  urolithin A, NAD/NMN, and omega-3.
- Pure adaptive expansion hook:
  - accepts retrieval counts
  - returns `enough`, `expand`, or `stop`
  - never calls live APIs
- Validation checks:
  - required top-level fields present
  - non-empty retrieval topic terms
  - pseudo tier cannot proceed
  - no species hard filter by default

## Why This Does Not Perturb Current Packs

- No existing `topic_packs/*.toml` files are read or rewritten by the generator.
- No synthesis script imports the generator.
- No persistence layer is touched.
- No public API is touched.
- Generated packs are review artifacts until explicitly promoted later.

## Out of Scope

- DB-backed generated-pack persistence.
- TOML serialization.
- Network retrieval dry-runs.
- Live candidate counts from PubMed, Europe PMC, Crossref, OpenAlex, or trials
  registries.
- LLM term generation.
- Replacing curated packs.
- Allowing generated packs to bypass audit, journal-surface, final-reviewer,
  arbitrator, or maturity gates.

## Probe Results

| Check | Result |
|---|---:|
| Mainstream biomedical generation | pass |
| Urolithin A precursor expansion | pass |
| Pseudo stop behavior | pass |
| Contested candidate cap behavior | pass |
| Adaptive expansion hook | pass |
| `_biomedical_default.toml` compatibility | pass |
| Species hard-filter validation | pass |

## Commands

```bash
python3 -m pytest tests/test_topic_pack_generator.py
ruff check agent/topic_pack_generator.py tests/test_topic_pack_generator.py
```

Final result:

```text
9 passed
ruff: all checks passed
```

Runtime LOC check: `agent/topic_pack_generator.py` is 297 lines, below the
300-line soft budget.

## Remaining Risks

- Tier classification is heuristic and intentionally conservative.
- Precursor expansion is hand-curated and narrow.
- Candidate caps are policy defaults, not empirically optimized.
- Compatibility is structure-level only; generated packs still need retrieval
  benchmarking before use in real synthesis runs.
