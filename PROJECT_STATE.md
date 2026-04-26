# PROJECT_STATE.md

## Current Objective
V1 rebuild — turn `topic + domain + criteria` into a 9/10-grade rapid-review draft via a deterministic-first pipeline. The LLM is editor only; the LLM never decides source role, citation identity, evidence tier, or result/protocol status.

## Pipeline
```
plan -> retrieve -> normalize -> bundle -> facts -> compose -> [polish] -> qa -> render -> [submit]
```
The deterministic Draft must be publishable before the LLM ever touches it. Polish is an opt-in pass that may improve wording but cannot add/remove citations, change role labels, or invent numbers.

## Success Condition
- Five golden topics (rapamycin, metformin, senolytics dasatinib+quercetin, semaglutide weight, vitamin D mortality) produce snapshot-identical Drafts on every run.
- The rapamycin fixture would have caught the published_results-vs-protocol contradiction that broke V0.
- Markdown artifact + bibliography + evidence table render deterministically.
- `agent/` runtime stays under 2,500 LOC; no single file exceeds 500 LOC.
- `agent/` never imports from `agent_legacy/`.

## Constraints
- Hard ceiling: **2,500 LOC** for `agent/` (enforced by `tests/test_loc_budget.py`).
- Hard ceiling: **500 LOC per file** (enforced same place).
- Runtime dependency: `httpx` only. No Pydantic, no frameworks.
- Python ≥ 3.11, stdlib `dataclasses` with `frozen=True, slots=True`.
- Researka submission deferred to V1.x once quality is locked.

## Day Plan (5 days)
| Day | Ship | Done when |
|---|---|---|
| 1 | Scaffold + types + harness | This file. Pytest green. ✅ |
| 2 | sources/ + retrieve.py + bundle.py + real fixture capture | Deterministic role/tier passes on all 5 fixtures |
| 3 | facts.py + compose.py + render.py | Markdown deterministic; rapamycin end-to-end without LLM |
| 4 | qa.py + optional llm.py + invariants | All 5 golden topics produce 9/10 artifacts; polish opt-in and provably safe |
| 5 | app.py + dashboard + smoke deploy | CLI works; dashboard renders; ready for submit.py later |

## Day 1 Status — DONE
- `agent/` package: `__init__.py`, `types.py` (183 LOC after review fixes; frozen dataclasses + `assert_invariants` enforcing both forward and reverse role↔fact-kind pairings).
- `tests/`: snapshot harness (fails loud on missing baseline unless `UPDATE_SNAPSHOTS=1`), types contract (18 cases), LOC budget enforcer, legacy-import guard.
- pyproject `packages.find` now `["agent", "agent.*"]` — `agent_legacy` never ships.

## Day 2 Status — DONE
- 4 source adapters (pubmed, openalex, europepmc, clinicaltrials) behind shared `SourceClient` Protocol; ~340 LOC total.
- `agent/retrieve.py` (116 LOC) — single shared `httpx.AsyncClient`, parallel fanout via `asyncio.gather`, 4-key dedup (DOI > PMID > NCT > normalized title), 1-indexed refs, raw_signals propagation.
- `agent/bundle.py` (216 LOC) — deterministic role/tier/design/direct/strict classifier with truth-table docstring. Word-boundary regex markers (not substring).
- `scripts/capture_fixtures.py` — captured **real** PubMed/OpenAlex/EuropePMC/ClinicalTrials responses for the 5 golden topics (148 hits across 20 fixture files, sort_keys=True for stable diffs).
- `tests/test_sources.py` — parser regression against real fixtures (40 parametrized cases).
- `tests/test_retrieve.py` — plan_queries + dedup logic (9 cases).
- `tests/test_bundle.py` — truth-table cases (23) + per-topic snapshot baselines (5).
- Bugs caught and fixed during capture: EuropePMC `resultType=lite` silently dropped abstracts; CT.gov barfed on "RCT" filter token (fix: `plan_queries` no longer joins criteria into the retrieval query). Bundle marker matching was substring-based and missed sentence-initial "Mice"/"Rats" — switched to word-boundary regex.
- 93 tests green in 0.08s. Total `agent/` LOC: 859 / 2,500 (1,641 headroom).

## Legacy
The pre-rebuild package lives at `agent_legacy/` for git archaeology. New code MUST NOT import from it. CI guard: `tests/test_no_legacy_imports.py`.

## Open Risks
- Day-2 source adapters need to be ported clean from `agent_legacy/sources/` without inheriting drafter coupling.
- Real fixture capture (day 2) requires live API calls — rate limits and quotas to respect.
- The role/tier classifier in `bundle.py` (day 2) is the most complex single module — must stay under 500 LOC.

## Next Validation Step
Day 2: port PubMed/OpenAlex/EuropePMC/ClinicalTrials adapters behind a `SourceClient` protocol; capture real responses for the 5 golden topics into `tests/fixtures/`; build deterministic `bundle.py` and prove role/tier classification against captured fixtures.
