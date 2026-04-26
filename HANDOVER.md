# Research Agent Bot Handover

## One-Line Purpose
Turn `topic + domain + criteria` into a credible rapid evidence synthesis with citations, evidence tiers, strict-eligibility disclosure, machine adjudication metadata, markdown output, and optional Researka submission.

## Current State
- Branch: `tier2-finish`
- Code baseline before this handover doc: `48eb802`
- Runtime LOC: `7,991` Python LOC in `agent/`, tests excluded
- App URL: `https://research-agent.domlynch.com/`
- VPS app path: `/opt/research-agent-bot`
- Service: `research-agent-bot`
- Main command locally: `.venv/bin/pytest -q && .venv/bin/ruff check agent tests`

## Before
The system started as a simple deterministic rapid-review bot:
- Plan scoped queries.
- Retrieve public evidence.
- Keep a small bundle.
- Ask one model to draft.
- Render markdown.

It produced some decent `8+` drafts, but had recurring trust bugs:
- Off-topic sources entering bundles.
- Duplicate papers.
- Protocols treated like results.
- Citation number mismatches.
- Raw extraction text leaking into prose.
- Conclusions contradicting Key Findings.
- Model edits fixing one thing while breaking another.

## Current Architecture
The system now has a much stronger evidence/control layer, but too much logic is concentrated in `drafter.py` and `cli.py`.

### Main Flow
1. Dashboard receives a form submit.
2. `run_agent()` resolves topic, builds queries, retrieves evidence.
3. Evidence is filtered by scope/topic.
4. Full text and structured extraction are attempted.
5. Source bundle is selected, deduped, typed, tiered, and annotated.
6. MiMo drafts JSON sections.
7. Gemma reviews and Mistral judges the pre-render JSON.
8. Drafter post-processes citations, registry/protocol language, numeric claims, abstract, and sections.
9. Deterministic validators check citation roles and draft quality.
10. One retry/revision may run if high-severity violations remain.
11. Final markdown is rendered with Methods, Evidence Table, Sources, and adjudication metadata.
12. Optional Researka submission runs if enabled.

## Key Files
### Entry / Orchestration
- `agent/dashboard.py`
  - Tiny HTTP dashboard.
  - Handles async jobs, polling, result rendering.
  - Should stay UI-only.

- `agent/cli.py`
  - Main orchestration through `run_agent()`.
  - Also currently handles progress, validation, repair, markdown rendering, methods, evidence table, submit.
  - This file is overloaded and should be split.

### Evidence / Retrieval
- `agent/planner.py`
  - Builds query variants and scope signals from topic/domain/criteria.
  - Applies broad scope filtering.

- `agent/entity_resolver.py`
  - Canonicalizes topics and aliases.
  - Prevents typo/wrong-entity drafts.

- `agent/sources/*.py`
  - Retrieval adapters.
  - PubMed/OpenAlex/EuropePMC are core.
  - ClinicalTrials is important for protocols/registered results.
  - Semantic Scholar expands from citation graph.
  - ChEMBL/NIH/DOAJ/rxiv/CORE/Unpaywall are supporting and add complexity/noise.

- `agent/fulltext.py`
  - EuropePMC/Unpaywall/CORE full-text enrichment.

- `agent/extractor.py`
  - Structured claim/effect extraction.
  - Useful, but can add latency and model dependency.

### Evidence Classification
- `agent/evidence_cards.py`
  - Builds per-source card: study type, quality signal, population, intervention, outcomes.

- `agent/citation_roles.py`
  - Classifies citation role: `published_results`, `published_protocol`, `registered_pending`, `review`, `meta_analysis`, `mechanistic`, etc.
  - Defines role language constraints.

- `agent/title_patterns.py`
  - Shared source of truth for review/protocol-like title regex.

### Drafting / Post-Processing
- `agent/drafter.py`
  - Biggest file and main bloat: `2,635` LOC.
  - Does too much:
    - bundle selection
    - dedup
    - topic fit
    - directness/tier/strict eligibility
    - prompt construction
    - model result parsing
    - citation rendering
    - abstract generation
    - section post-processing
    - numeric grounding
    - editor pass
  - This is the primary refactor target.

- `agent/moa_spar_bridge.py`
  - Provider wrapper:
    - MiMo V2.5 Pro drafts.
    - Gemma 4 31B reviews.
    - Mistral Small 2603 judges.
  - Reviews pre-render JSON, not final markdown.
  - Current public markdown labels this as `pre-render` to avoid stale-note confusion.

- `agent/provider.py`
  - Direct MiMo client.

### QA / Output
- `agent/validator.py`
  - Deterministic validators:
    - citation role language
    - missing numerics
    - raw extraction leak
    - support-claim drift
    - conclusion contradiction
    - duplicate abstract claims

- `agent/submit.py`
  - Optional Researka submission.

- `agent/schema.py`
  - Schema validation support.

## Current Model Setup
Default provider path:
- Builder/synth: `mimo-v2.5-pro`
- Reviewer: `google/gemma-4-31b-it`
- Judge: `mistralai/mistral-small-2603`

Required env:
- `MIMO_API_KEY`
- `OPENROUTER_API_KEY`

Important env controls:
- `BOT_ENABLED`
- `BOT_SUBMIT_ENABLED`
- `DAILY_COST_CAP_USD`
- `RESEARKA_URL`
- `OPENROUTER_TIMEOUT_SEC`
- `REVIEWER_MODEL`
- `JUDGE_MODEL`

## What Recently Broke
The regression was mostly not “bad LLMs.” It was ordering and responsibility drift.

Main issue:
- The model bridge reviewed pre-render JSON.
- Later deterministic steps changed/added abstract, methods, evidence table, citations, and conclusion.
- Public markdown then showed stale reviewer comments like “abstract missing.”

Recent fix:
- Public markdown now says adjudication is `pre-render`.
- Raw model issues remain in run logs.
- Final public trust is owned by deterministic validators.

## Known Risk Areas
- `drafter.py` has too many hidden interactions.
- `cli.py` repairs and renders, while `drafter.py` also repairs and renders citation state.
- LLM review is not a final artifact review.
- Retrieval sources beyond PubMed/OpenAlex/EuropePMC/ClinicalTrials can add noise.
- The Evidence Table can disagree with source labels if `card.study_type`, `quality_signal`, and `role` drift.
- The conclusion is fragile because multiple post-processors can alter or preserve it.

## How To Reproduce A Run
```bash
cd /private/tmp/research-agent-tier2-finish
.venv/bin/python -m agent.cli \
  --topic "rapamycin" \
  --domain longevity \
  --criteria "2022 onwards human studies relevance"
```

Outputs:
- `runs/*.json`
- `runs/*.raw.json`
- `runs/*.md`
- `runs/protocols/*.protocol.json`

## How To Verify
```bash
cd /private/tmp/research-agent-tier2-finish
.venv/bin/pytest -q
.venv/bin/ruff check agent tests
find agent -name '*.py' -print0 | xargs -0 wc -l | tail -1
```

Live VPS:
```bash
ssh -i ~/.ssh/binance_futures_tool root@49.12.7.18 \
  'cd /opt/research-agent-bot && git rev-parse --short HEAD && systemctl is-active research-agent-bot'
```

## What “Good” Output Means
A publishable-ish draft should have:
- Clean abstract with concrete trial signal.
- No raw extraction strings.
- No stale adjudication claims.
- No `R1/R2` citation leaks.
- No protocol used as efficacy evidence.
- Evidence Table agrees with Sources.
- Tier A1/A2/B/C hierarchy is visible.
- Conclusion gives a verdict, uncertainty, and actionability.
- Strict eligibility count is honest.

## Current Quality Bar
Metformin can reach `~9/10`.
Senolytics can reach `~8+` if classification is clean.
Rapamycin remains hardest because:
- PEARL has positive subjective signals.
- RAPA-EX has objective functional nulls.
- Protocols/preprints/mechanistic sources are tempting but must not drive the conclusion.

## End-Game Architecture
Target split:
1. `plan.py`
   - topic/domain/criteria -> queries/scope.
2. `retrieve.py`
   - source adapters -> raw candidates.
3. `bundle.py`
   - dedup, topic fit, role, tier, strict eligibility, confidence.
4. `draft.py`
   - one final bundle -> draft sections.
5. `qa.py`
   - final-artifact validators and deterministic repairs.
6. `render.py`
   - markdown, evidence table, sources, methods.
7. `dashboard.py`
   - async UX only.

End-game rule:
- Models draft/review.
- Deterministic code owns final public correctness.
- Final markdown should be validated after all post-processing.

## Simplification Plan
### Phase 1: Stop The Bleeding
- Freeze new features.
- Keep only one final artifact validation point.
- Do not show pre-render reviewer issue text as final findings.
- Keep model audit details in run logs.

### Phase 2: Split `drafter.py`
Extract from `drafter.py`:
- `bundle.py`: source selection, dedup, tiers, strict eligibility.
- `citation_render.py`: stable refs -> final numeric citations.
- `section_postprocess.py`: registry/protocol/numeric cleanup.
- `prompt_builder.py`: prompt construction only.

### Phase 3: Slim Retrieval
Default source set:
- PubMed
- OpenAlex
- EuropePMC
- ClinicalTrials

Gate or disable by default:
- NIH RePORTER
- ChEMBL
- DOAJ
- CORE
- rxiv
- Semantic Scholar graph expansion

These are useful, but each adds noise and failure surface.

### Phase 4: Replace Repair Loop With Final QA
Preferred:
- Draft once.
- Final render.
- Run final QA.
- Deterministically repair small known classes.
- Fail closed only for true trust-breaking issues.

Avoid:
- model draft -> model review -> model fix -> editor pass -> validator -> full re-draft -> render.

## Highest-ROI Refactors
1. Move bundle/tier logic out of `drafter.py`.
2. Move markdown/evidence table out of `cli.py` into `render.py`.
3. Add one `final_artifact_qa.py` that checks final markdown/artifact only.
4. Convert source adapters into a registry to simplify `run_agent()`.
5. Delete or env-gate low-yield sources.
6. Replace giant prompt string with `prompt_builder.py` using named bullet sections.

## Files To Read First
Read in this order:
1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `agent/cli.py`
4. `agent/drafter.py`
5. `agent/validator.py`
6. `agent/moa_spar_bridge.py`
7. `tests/test_cli.py`
8. `tests/test_drafter.py`
9. `tests/test_validator.py`

## Do Not Do
- Do not add another model to fix deterministic bugs.
- Do not make topic-specific fixes for metformin/rapamycin/D+Q.
- Do not let Tier B/C evidence drive headline claims.
- Do not treat pre-render adjudication as final review.
- Do not expand LOC without deleting or splitting.
- Do not weaken validators just to pass one draft.

## Immediate Next Move
Refactor, do not add features.

Best first PR:
- Create `agent/render.py`.
- Move `_payload_to_markdown()` and `_evidence_table_lines()` out of `cli.py`.
- Keep behavior identical.
- Tests should stay green.

This reduces cognitive load without changing the pipeline.
