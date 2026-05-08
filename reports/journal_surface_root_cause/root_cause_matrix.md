# Journal Surface Root-Cause Matrix

## Scope

Diagnostic only. No generator/compiler files were edited.

Audit inputs:

- Latest 7: `reports/journal_surface_root_cause/latest_7_audit.json`
- Prior baselines: `reports/journal_surface_root_cause/prior_baseline_audit.json`
- Line excerpts: `reports/journal_surface_root_cause/latest_7_excerpts.json`
- Prior excerpts: `reports/journal_surface_root_cause/prior_baseline_excerpts.json`

## Latest 7 Results

| Topic | Run | Issues | Classes |
|---|---|---:|---|
| omega3 | `runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z` | 11 | template_meta 7; duplicate 4 |
| statins | `runs/synthesis-statins-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER` | 17 | template_meta 9; placeholder 1; duplicate 7 |
| caloric_restriction | `runs/synthesis-caloric_restriction-v06-PATH2RICHFIX2-2026-05-08T15-10-00Z` | 12 | template_meta 7; duplicate 5 |
| metformin | `runs/synthesis-metformin-v06-PATH2RICHFIX5-2026-05-08TCLASSIFIER` | 10 | template_meta 9; placeholder 1 |
| glp1 | `runs/synthesis-glp1-v06-PATH2RICHFIX5-2026-05-08T08-10-00Z` | 17 | template_meta 7; duplicate 10 |
| creatine | `runs/synthesis-creatine-v06-PATH2RICHFIX3-2026-05-08T09-10-00Z` | 7 | template_meta 7 |
| rapamycin | `runs/synthesis-rapamycin-v06-PATH2RICHFIX4-2026-05-08TCLASSIFIER` | 15 | template_meta 9; placeholder 1; duplicate 5 |

Aggregate: 89 issues = 55 template/meta, 31 duplicate paragraph, 3 placeholder.
No QEI, citation-artifact, or standalone hedge-fragment hits in latest 7.

Watch pass: by filesystem mtime, statins also has
`runs/synthesis-statins-v06-PATH2RICHFIX3-2026-05-08T10-35-00Z`; smoke audit
returned 8 issues (7 template/meta, 1 duplicate). This does not change the
root-cause classification.

## Prior Baselines

Aggregate: 99 issues = 63 template/meta, 27 duplicate paragraph, 9 placeholder.
The same failure classes predate the latest run wave, so this is both historical
artifact debt and live code risk.

## Classification

| Class | Evidence | Root cause | Current code risk |
|---|---|---|---|
| Public-body meta prose | Latest 7 all include `This synthesis was produced by`, `submission`, `Final-layer reviewer`, `Grok`, `SPAR`, and `Rejected-evidence quarantine did NOT run` before appendix. | `scripts/run_mode_contract.py:184-249` renders operational provenance into `## Methods`. | High. Current renderer still emits these strings. |
| Appendix boundary | omega3 has `## Publication Appendix` at line 936; GLP1 has `## Search Provenance and Selection` at line 788 with no wrapper. | `agent/manuscript_appendix.py:615` creates wrapper, but `scripts/run_v06_synthesis.py:2331-2380` splices appendix best-effort after previous paper write. Some artifacts contain bare appendix subsections. | Medium. Gate cutoffs catch `Search Provenance`, but public manuscripts may still lack a visible appendix wrapper. |
| Duplicate paragraphs | Latest examples: omega3 duplicate paragraphs line 45/67 and 255/266; GLP1 has 10 duplicate hits. | Backfill text from `scripts/apply_consistency_fixes.py:1873-1984` can be inserted into multiple sections; picked thesis is also repeated by `agent/paper_writer_deterministic.py:443-447`. | High. No universal duplicate paragraph gate exists in `agent/journal_surface_gate.py`. |
| Placeholder/backfill prose | `deterministic evidence summary` persists in statins/metformin/rapamycin latest; GLP1 L3 has it at line 263. | `scripts/apply_consistency_fixes.py:394-395` tries to normalize, but table intro text can still survive; deterministic section/table prose appears post-repair. | Medium. Gate catches some placeholder phrases, but not all table-intro variants. |
| QEI rows | No hits in latest/prior sample. | QEI renderer already filters malformed rows in `agent/results_table.py:190-220` and `agent/journal_surface_gate.py:91-133`. | Low, current code has coverage. |
| Citation artifacts | No hits in latest/prior sample. | Batch audit adds coverage; universal gate does not yet. | Low observed, medium future risk. |
| Hedge fragments | No hits in latest/prior sample. | Batch audit adds coverage; universal gate does not yet. | Low observed. |

## Source Localization

- Methods/meta emitter: `scripts/run_mode_contract.py:230-249`.
- Methods renderer insertion: `scripts/run_v06_synthesis.py:1861-1882`.
- Run-mode contract flags set false for v0.6: `scripts/run_v06_synthesis.py:2681-2704`.
- Appendix composer/splicer: `agent/manuscript_appendix.py:590-646`.
- Stage 5b appendix splice call: `scripts/run_v06_synthesis.py:2331-2380`.
- Current journal surface gate: `agent/journal_surface_gate.py:22-55`.
- QEI renderer and empty-placeholder: `agent/results_table.py:190-220`.
- Backfill paragraphs: `scripts/apply_consistency_fixes.py:1873-1984`.
- Duplicate picked thesis source: `agent/paper_writer_deterministic.py:443-447`.

## Existing Protection

- `agent/journal_surface_gate.py` already strips at appendix boundaries and checks
  placeholder prose plus QEI shape.
- `agent/results_table.py` already quarantines many public QEI rows and renders an
  empty-QEI diagnostic instead of malformed rows.
- `scripts/apply_consistency_fixes.py:370-410` normalizes several public meta
  phrases, but it does not fully neutralize `run_mode_contract.render_methods`.

## Remaining Gaps

1. `run_mode_contract.render_methods` is too operational for public Methods.
2. `journal_surface_gate` lacks template/meta, duplicate paragraph, citation artifact,
   and hedge-fragment checks.
3. Appendix splicing allows bare `Search Provenance` sections in some artifacts.
4. Duplicate/backfill insertion is section-local, not document-global.

## Minimal Universal Fix Plan

| Priority | File | Fix | Expected LOC |
|---|---|---|---:|
| P1 | `scripts/run_mode_contract.py` | Rewrite public Methods text to clinical-methods style; move model names, submission id, SPAR/Grok/quarantine absence, and patch mechanics to appendix/report only. Extend `validate_rendered` blocked list with observed phrases. | 25-45 |
| P1 | `agent/journal_surface_gate.py` | Add public-body checks from batch audit: meta/template phrase scan and duplicate paragraph overlap. Keep appendix-only allowance. | 35-55 |
| P2 | `scripts/run_v06_synthesis.py` or `agent/manuscript_appendix.py` | Enforce `## Publication Appendix` wrapper before bare `Search Provenance`/AI/Data sections; fail closed if splice produces bare appendix sections. | 15-30 |
| P2 | `scripts/apply_consistency_fixes.py` | Make backfill insertion idempotent across the whole manuscript, not per-section only; never insert the same paragraph twice. | 20-40 |
| P3 | `agent/journal_surface_gate.py` | Add citation-artifact and standalone-hedge checks from batch audit. | 15-25 |

Expected total: 110-195 LOC plus tests.

## Tests Required Before Generator Edits

- `test_run_mode_contract_public_methods_excludes_operational_meta`
- `test_journal_surface_gate_blocks_public_template_meta_but_allows_appendix`
- `test_journal_surface_gate_blocks_duplicate_paragraphs`
- `test_appendix_splice_wraps_bare_search_provenance`
- `test_consistency_backfill_does_not_duplicate_existing_paragraph`
- `test_journal_surface_gate_blocks_citation_artifacts_and_hedge_fragments`
- Golden smoke: run latest 7 batch audit after rerun; expected zero public-body
  meta/placeholder/duplicate issues.

## GLP1 L3 Diagnosis

`runs/synthesis-glp1-v06-PATH2RICHFIX3-2026-05-08T06-35-00Z` is code/pipeline
risk, not pure stochastic failure. Its verdict records `grok_unresolved_p1=1`
and `journal_surface_pass=false`; the surface issue is
`placeholder_prose: deterministic evidence summary`. The offending line is
`full_paper.md:263`. Later GLP1 runs reach L5, so stochastic review variance
can affect maturity, but the L3 trigger is a deterministic surface-gap class.

## False-Positive Risk

- Meta phrase scan: medium. `SPAR`/`Grok` are valid in appendix, not public body.
  Word-boundary matching reduces accidental hits.
- Duplicate paragraphs: medium. Repeated table captions or required disclosures can
  be legitimate; restrict to public body and long paragraphs, and exempt tables.
- Placeholder scan: low-medium. The current hits are exact deterministic prose.
- QEI/citation/hedge checks: low observed incidence; keep them P2/P3 unless paired
  with final verdict gating.

## Historical vs Current

Historical artifacts require rerun or posthoc regeneration; code fixes cannot mutate
published run dirs. Current code still has live risk because `render_methods` and the
universal gate gaps remain present.

## Rerun Order After Fix

1. GLP1 PATH2RICH rerun: shortest proof that L3 surface regression closes.
2. Creatine: no duplicate/placeholder latest hits, isolates methods/meta fix.
3. Metformin: placeholder-heavy canonical topic.
4. Omega3: duplicate-heavy with publication appendix wrapper present.
5. Statins and rapamycin: combined placeholder + duplicate stress.
6. Caloric restriction: confirms no topic-specific exception.

## Acceptance Criteria

- Latest 7 batch audit returns zero public-body template/meta, placeholder, and
  duplicate issues.
- `full_paper.final_verdict.json` no longer marks journal surface pass while the
  batch audit fails.
- Public Methods contains no model names, submission ids, review patch mechanics,
  SPAR absence blocks, or quarantine absence blocks.
- Appendix sections are visibly under `## Publication Appendix` or excluded from
  public-body gates by heading.
