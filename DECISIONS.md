# DECISION JOURNAL

## 2026-04-20 — Collapse to V0 Manual Draft Tool
**Decision:** Strip the Researka submit path, MiMo spar pass, and DeepSeek fallback from V0 and optimize only for the live draft page.
**Why:** The public product is currently a manual draft-and-download tool. Keeping submit-era code in V0 adds LOC, latency, and failure surfaces without user value.
**Alternatives rejected:**
- Keep the full external-submission stack in place — rejected because it bloats V0 and pulls the code away from the hosted page's actual job.
- Leave the old contract untouched and only patch around it — rejected because stale project rules would keep reintroducing dead code.
**Revisit if:** V2 explicitly reintroduces autonomous submission to Researka.

## 2026-04-20 — Re-add Researka submission path
**Decision:** Add optional submit to Researka /submissions when RESEARKA_URL is set, with inline pipeline processing, dedup, and UI surfacing of submission_id/decision/publication_id.
**Why:** Researka v2 backend is live and accepting submissions. The bot's drafts are now contract-compliant (7 sections incl. Gaps Identified, 12+ sources, 50+ word RQ, 50%+ recent). Submitting to Researka closes the loop from draft to publication.
**Alternatives rejected:**
- Keep V0 draft-only — rejected because Researka is ready and the integration is ~25 LOC.
- Use async worker instead of inline polling — deferred. Inline /jobs/run-once is pilot-grade; async worker orchestration is a follow-up.
**Revisit if:** Inline polling causes request hangs or Researka worker flakes become frequent.

## 2026-04-21 — Safety rails (Step 1)
**Decision:** Add three env-gate controls (BOT_ENABLED, BOT_SUBMIT_ENABLED, DAILY_COST_CAP_USD) checked before expensive work begins.
**Why:** Bot must not burn API costs unattended or submit when disabled. Kill switch allows instant halt, cost cap prevents runaway spend, submit switch separates submission from drafting.
**Details:**
- `_is_enabled()` / `_is_submit_enabled()` accept `true`, `1`, `yes`, `on` (case-insensitive).
- `_daily_cost()` scans today's `runs/*.json` (skipping `.raw.json`) and sums `estimated_cost_usd`.
- Kill check runs first (line 115), cost cap check second (line 118), submit switch gates the POST (line 167).
- 7 new tests added to `tests/test_cli.py` (total 15).
**Alternatives rejected:**
- Use a single file-based lock — rejected because env vars are simpler and VPS-friendly.
- Cost cap via external service — rejected, local JSON scan is fast enough for V0.
**Revisit if:** Cost tracking needs inter-day or cross-instance aggregation.

## 2026-04-21 — 3-Tier Eval Corpus (Cochrane-grounded, not LLM-picked)
**Decision:** Build golden eval as 10 human-curated topics (real 2023-2026 systematic reviews) + 30 adversarial + 60 breadth (MiniMax-generated), not 100 LLM-picked "elite" papers.
**Why:** LLM-picked benchmarks are circular (LLM picks → LLM drafts → LLM grades). Real published systematic reviews are free ground truth with traceable DOIs, effect directions, and limitations. The 15k/day MiniMax quota is better spent on CI-gated regression runs (100 topics × 6 queries × every push) than on one-shot benchmark construction.
**Details:**
- 10 gold topics: rapamycin, nad_precursors, metformin, senolytics, glp1, time_restricted_eating, creatine_cognition, omega3_cv, vitamin_d_mortality, exercise_mci
- 4 scoring functions: study_overlap (0.35), quantitative_fidelity (0.30), direction_agreement (0.20), limitation_overlap (0.15)
- Schema validator in `tests/golden/schema.py`
- CI workflow in `.github/workflows/eval.yml`
- Bulk generation script in `scripts/generate_eval_corpus.py`
**Alternatives rejected:**
- 100 MiniMax-picked elite papers — rejected for circularity (LLM picks → LLM drafts → LLM grades)
- Full-text scraping — rejected, out of V0 scope
- ClinicalTrials.gov / bioRxiv / ChEMBL integration now — rejected; data-gated on quantitative_fidelity baseline
**Revisit if:**
- `quantitative_fidelity` on interventional topics baselines below 0.50 → wire ClinicalTrials.gov
- Direction classifier accuracy below 80% → replace rule-based with MiMo JSON extraction
- CI run exceeds 20 min → cache layer or matrix split
