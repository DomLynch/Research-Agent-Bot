# PROJECT_STATE.md

## Current Objective
V1.1 — `topic + domain + criteria` → research-grade rapid-review draft. Three-LLM pipeline (relevance + writer + judge) with deterministic gates as the spine.

## Pipeline (current)
```
retrieve  →  bundle  →  classify_relevance (LLM #1, mandatory) →
write_draft (LLM #2) →  qa →  judge_draft (LLM #3, mandatory) →
[revision-then-rejudge if needed]  →  render
```
- All three LLMs always run when API keys are configured. Judge silently no-ops without `OPENROUTER_API_KEY` but the artifact's `## Adjudication` block visibly marks the SKIPPED state.
- On dual-rejection (both QA attempts fail OR judge rejects post-revision), the markdown still ships with an `⚠️ UNVERIFIED` banner + `## QA Failures` block — never an empty result.

## Constraints
- Hard ceiling: **3,500 LOC** for `agent/` (raised from 2,500 in DECISIONS.md 2026-04-26 to fund the trust-layer features).
- Hard ceiling: **500 LOC per file**.
- Runtime dep: `httpx` only.
- Python ≥ 3.11, stdlib `dataclasses` (frozen+slots).

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

## V1.1 Status — feature-complete with mandatory three-LLM pipeline
- `agent/relevance.py` (LLM #1) — three-tier classifier MiMo → Gemma → Mistral. Single batch call before the writer; overrides deterministic `direct` when LLM judgment differs.
- `agent/llm.py` (LLM #2 — writer) — MiMo 2.5 Pro primary, Mistral fallback. Surgical retry: previous draft + per-failure-code editing rules + temperature 0.05.
- `agent/judge.py` (LLM #3 — mandatory judge) — three-tier chain Gemma → MiMo → Mistral. Hyper-critical prompt: cross-reference every citation, flag mis-attribution, reject made-up trial names.
- After judge rejection + writer revision, **judge re-runs on the revised draft** so the rendered `## Adjudication` block reflects the SHIPPED draft (not stale pre-revision verdict).
- Dual-rejection: markdown still renders with `⚠️ UNVERIFIED` banner + `## QA Failures` block.
- Judge skipped (no `OPENROUTER_API_KEY`) → visibly marked in `## Adjudication` (never silent).
- Trust-layer in render.py: Eligibility / Evidence (with risk-of-bias) / Excluded Sources / Confidence verdict / Adjudication / QA Failures / Bibliography.
- Cost per draft: ~$0.002–0.005 (3 LLM calls + occasional revision + re-judge).
- Tests: **165 green in ~0.3s**, ruff clean, agent/ runtime: **~2,810 / 3,500 LOC**.

## V1 Status — feature-complete (`agent/app.py dashboard` ready to deploy)
- **133 tests green in 0.15s** across types, sources, retrieve, bundle, qa, render, draft.
- **agent/ runtime: 1,810 / 2,500 LOC** (690 headroom). Largest file: bundle.py 298. Every file under 500.
- **End-to-end pipeline**: `topic + domain + criteria → retrieve (4 sources, parallel) → bundle (deterministic role/tier/topic gate) → llm (MiMo 2.5 Pro, JSON output, strict prompt) → qa (4 typed gates, retry once) → render (markdown + bibliography + evidence table)`.
- **CLI**: `python -m agent.app run --topic ... --domain ... --criteria ...` prints markdown.
- **Dashboard**: `python -m agent.app dashboard --port 8791` — same cream/teal V0 look, 187 LOC stdlib http.server, no Flask/FastAPI.
- **Safety rails**: `BOT_ENABLED`, `MIMO_API_KEY` required, `DAILY_COST_CAP_USD` blocks runs over today's cap.
- **Pivot from day-3 plan**: dropped `compose.py` templated-skeleton + `facts.py` standalone extractor. Frontier LLM (MiMo 2.5 Pro) writes prose given typed bundle + strict prompt; QA gates catch any drift. Saves ~600 LOC vs the original templated-compose plan.

## Deploy steps (for the user to run on the VPS)
```bash
ssh root@<vps>
cd /opt/research-agent-bot
git pull
.venv/bin/pip install -e .   # in case pyproject.toml changed
sudo cp deploy/research-agent-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart research-agent-bot
sudo systemctl status research-agent-bot --no-pager
# Verify: curl -s https://research-agent.domlynch.com/ | head -20
```

## Day 2 Status — DONE (with audit fixes applied)
- 4 source adapters (pubmed, openalex, europepmc, clinicaltrials) behind shared `SourceClient` Protocol.
- `agent/retrieve.py` (144 LOC) — single shared `httpx.AsyncClient`, parallel fanout via `asyncio.gather`, multi-key dedup (DOI > PMID > NCT > NCT-in-abstract > normalized title), 1-indexed refs, `logger.warning` on swallowed adapter errors.
- `agent/bundle.py` (278 LOC) — deterministic role/tier/design/direct/strict classifier with truth-table docstring. Topic-anchor gate prevents off-topic candidates from being marked direct.
- `scripts/capture_fixtures.py` — captured **real** PubMed/OpenAlex/EuropePMC/ClinicalTrials responses for the 5 golden topics. Topic queries tuned to surface the actual published+protocol pair (e.g. `rapamycin older adults` returns PMIDs 41985884 and 39354527 — the V0 contradiction case).
- 102 tests green in 0.11s. Total `agent/` LOC: 963 / 2,500 (1,537 headroom). Max file: bundle.py at 278 LOC.

### Day 2 audit fixes (the second pass)
- `_REPORTED_OUTCOME_RE` was too greedy — `\d+%` matched "60% female" in protocol abstracts and flipped role to `published_results`. Now requires effect-verb proximity ("reduced by 22%") or `participants(n=...)`, not bare percentages or `n=24 mice`.
- `_PROTOCOL` markers expanded to catch "study to evaluate", "evaluates the safety and efficacy", "we will assess", etc. — the RAPA-EX-01 protocol paper (PMID 39354527) was misclassified as `mechanistic` before this fix.
- `clean_text` only strips recognized HTML tag names now (was stripping anything between `<` and `>`, which destroyed `p<0.05`).
- `bundle()` now takes `topic` and gates `direct` on topic-anchor presence — RTB101 in a rapamycin query is no longer marked direct evidence.
- `normalize_and_dedup` scans abstracts for NCT identifiers — a PubMed paper citing `NCT04098874` and the CT.gov registry entry for that NCT now collapse into one source instead of being cited twice as independent evidence.
- Bundle snapshots are per-source rows (ref, title, role, design, tier, direct, strict) — aggregate counts could mask role swaps between two sources.
- Test fixture loader iterates in adapter priority order (PubMed first), not alphabetical, so PMIDs survive cross-source dedup.
- PubMed `retmax` no longer over-fetches 3×; EuropePMC year falls back to `firstPublicationDate`; CT.gov empty `briefSummary` no longer drops the trial; `retrieve()` lost its unused `domain` param.

### Regression coverage for the V0 bug class
- `test_rapamycin_fixture_contains_rapaex_papers` — PMIDs 41985884 and 39354527 must be in the fixture
- `test_rapamycin_fixture_classifies_rapaex_correctly` — full pipeline asserts results→`published_results/rct`, protocol→`published_protocol/protocol`
- `test_protocol_with_percentage_does_not_classify_as_results` — the exact bug class repro
- `test_protocol_evaluates_safety_and_efficacy_phrasing` — RAPA-EX phrasing locked in
- `test_off_topic_paper_marked_indirect` — RTB101 ≠ rapamycin
- `test_clean_text_preserves_pvalue_inequality` — `p<0.05` survives

## Legacy
The pre-rebuild package lives at `agent_legacy/` for git archaeology. New code MUST NOT import from it. CI guard: `tests/test_no_legacy_imports.py`.

## Open Risks
- Day-2 source adapters need to be ported clean from `agent_legacy/sources/` without inheriting drafter coupling.
- Real fixture capture (day 2) requires live API calls — rate limits and quotas to respect.
- The role/tier classifier in `bundle.py` (day 2) is the most complex single module — must stay under 500 LOC.

## Next Validation Step
Day 2: port PubMed/OpenAlex/EuropePMC/ClinicalTrials adapters behind a `SourceClient` protocol; capture real responses for the 5 golden topics into `tests/fixtures/`; build deterministic `bundle.py` and prove role/tier classification against captured fixtures.
