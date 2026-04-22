# Tier 2 Validator Audit

## Scope
- Branch: `tier2-finish`
- Slice:
  - citation role taxonomy + advisory validator
  - Europe PMC -> Unpaywall -> CORE full-text cascade
  - exact-compound resolver/gate compatibility fix
  - excerpt grounding + unsupported-numeric scrub

## Runtime Surfaces
- New:
  - `agent/citation_roles.py`
  - `agent/validator.py`
  - `agent/sources/core.py`
- Expanded:
  - `agent/sources/unpaywall.py`
  - `agent/fulltext.py`
  - `agent/drafter.py`
  - `agent/cli.py`
  - `agent/entity_resolver.py`

## Judge Pass
- Changed-surface suites:
  - `78 passed` on drafter / validator / role / full-text / resolver surfaces
  - `27 passed` on coverage-audit + dead-code detector repairs
- Full suite:
  - `403 passed, 6 skipped, 5 xfailed`
  - `ruff` clean

## Live Benchmark
- Before snapshot:
  - `scripts/karpathy-loop/snapshots/20260422_181957_snapshot.json`
- After snapshot:
  - `scripts/karpathy-loop/snapshots/20260422_191110_snapshot.json`
- Diff:
  - `scripts/karpathy-loop/diffs/20260422_191138_diff.json`

### Average Delta
- `composite_score`: `+0.0256`
- `quantitative_fidelity`: `+0.0444`
- `limitation_overlap`: `+0.0889`
- `direction_agreement`: `-0.0333`
- `study_overlap`: `+0.0000`

### Topic Summary
- Improved: `7`
- Regressed: `4`
- Unchanged: `4`

Largest improvements:
- `omega3_cv`: `+0.2167`
- `donanemab_alzheimer`: `+0.2000`
- `sglt2_heart_failure`: `+0.2000`
- `statin_primary_prevention`: `+0.2000`

Remaining regressions:
- `senolytics`: `-0.2833`
- `glp1_cv_mace`: `-0.2000`
- `creatine_cognition`: `-0.1500`
- `semaglutide_weight`: `-0.0167`

## Citation Validator Audit
- High severity violations: `0`
- Medium severity violations remain concentrated in summary-only bundles where the evidence lacks explicit numeric outcome strings.

Per-topic non-zero counts:
- `time_restricted_eating`: `10 medium`
- `donanemab_alzheimer`: `6 medium`
- `glp1_cv_mace`: `3 medium`
- `omega3_cv`: `3 medium`
- `statin_primary_prevention`: `3 medium`
- `rapamycin`: `2 medium`
- `glp1`: `1 medium`
- `semaglutide_weight`: `1 medium`
- `senolytics`: `1 medium`

Representative medium-severity validator misses:
1. `time_restricted_eating`
   - issue: `missing_numeric`
   - window: `One high-grade RCT in adults found no significant effect of intermittent fasting on a composite health outcome [6].`
2. `glp1_cv_mace`
   - issue: `missing_numeric`
   - window: `One trial reported that an intervention led to a specific outcome [1].`
3. `senolytics`
   - issue: `missing_numeric`
   - window: `the DQ combination significantly reduced senescence-associated β-galactosidase activity in human gingival keratinocytes [1].`

## What Actually Improved
- Registry-only ClinicalTrials citations no longer get outcome verbs.
- Posted CT.gov results now feed structured `effects[]` without an LLM pass.
- Exact known compound/class topics (`GLP-1`, `omega-3`, `NAD`, etc.) no longer trip the typo gate.
- Bundle excerpts now preserve later numeric result sentences when available.
- Unsupported quantitative claims are scrubbed before the artifact ships.

## Remaining Risks
- `glp1_cv_mace` still lacks strong numeric grounding because the retained bundle often surfaces narrative summaries rather than trial-result abstracts with explicit effect sizes.
- `creatine_cognition` and `senolytics` remain sensitive to direction wording because the evidence mix is sparse and partly indirect.
- Validator is still advisory only; it logs misses but does not yet trigger an automatic rewrite loop.
- Full-text hit rate improved, but PDF-only Unpaywall hits still cannot feed extraction until a parser lands.

## Next Real Step
1. Add a validator-driven rewrite loop for medium-severity `missing_numeric` failures on `published_results`.
2. Tighten ranking for `glp1_cv_mace` and `senolytics` toward explicit trial-result abstracts and away from narrative summaries.
3. Only then revisit broader PDF parsing / GROBID expansion.
