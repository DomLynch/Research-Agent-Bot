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

## Day 1 Status
- `agent/` package: `__init__.py`, `types.py` (161 LOC, frozen dataclasses + `assert_invariants`).
- `tests/`: snapshot harness, types contract (14 cases), LOC budget enforcer, legacy-import guard.
- All 14 tests green. Total `agent/` LOC: 163 / 2,500.
- Old code preserved at `agent_legacy/`, old tests at `tests_legacy/` (excluded from default pytest run).

## Legacy
The pre-rebuild package lives at `agent_legacy/` for git archaeology. New code MUST NOT import from it. CI guard: `tests/test_no_legacy_imports.py`.

## Open Risks
- Day-2 source adapters need to be ported clean from `agent_legacy/sources/` without inheriting drafter coupling.
- Real fixture capture (day 2) requires live API calls — rate limits and quotas to respect.
- The role/tier classifier in `bundle.py` (day 2) is the most complex single module — must stay under 500 LOC.

## Next Validation Step
Day 2: port PubMed/OpenAlex/EuropePMC/ClinicalTrials adapters behind a `SourceClient` protocol; capture real responses for the 5 golden topics into `tests/fixtures/`; build deterministic `bundle.py` and prove role/tier classification against captured fixtures.
