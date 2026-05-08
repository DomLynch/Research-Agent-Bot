# L6 Reproducibility Generalization - 2026-05-08

## Verdict

L6 generalizes beyond rapamycin in the existing run archive, but only for
same-topic, same-corpus, same-code, adjacent clean-L5 pairs that pass the real
consecutive certification gate.

Full scan output:

- JSON/stdout: `reports/l6_generalization_2026_05_08.stdout.json`
- Structured report: `reports/l6_generalization_2026_05_08/report.json`
- Markdown report: `reports/l6_generalization_2026_05_08/report.md`

Counts from the full read-only run:

| Status | Count |
|---|---:|
| Cohorts scanned | 61 |
| Confirmed L6 cohorts | 9 |
| Blocked candidate cohorts | 0 |
| Candidate-only cohorts | 0 |
| Needs rerun | 12 |
| No data | 40 |

## Candidate / Confirmed Table

| Topic | Candidate pairs | Same-corpus evidence | Same-code evidence | Verdict | Blockers |
|---|---:|---|---|---|---|
| caloric_restriction | 2 | `receipts:8218ec92153a` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |
| creatine | 2 | `receipts:e73e7b915a4d` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |
| glp1 | 2 | `receipts:20cac3dcdafb` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |
| metformin | 1 | `receipts:42a96121207b` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |
| metformin | 1 | `receipts:94ba4e851291` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |
| nad_precursors | 1 | `receipts:bfe1911ee12d` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |
| omega3 | 1 | `receipts:5ffed8d2a567` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |
| rapamycin | 7 | `receipts:3c88a35bff04` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |
| statins | 1 | `receipts:637b201b0feb` | `v0.6.0 / production / AAA-CLIN` | confirmed L6 | none |

## Concrete Confirmed Examples

- Rapamycin PATHA8/9/10: direct gate returned
  `l6_reproducibly_journal_ready=true`; both adjacent PATHA8+9 and PATHA9+10
  pass pairwise.
- GLP-1: confirmed pair
  `synthesis-glp1-v06-PATH2RICHFIX-2026-05-07T22-00-20Z` +
  `synthesis-glp1-v06-CONTRIB-2026-05-08T00-58-42Z`.
- Creatine: confirmed pair
  `synthesis-creatine-v06-PATH2RICHFIX2-2026-05-07T22-34-47Z` +
  `synthesis-creatine-v06-PATH2RICHFIX3-2026-05-07T22-44-26Z`.

## False-Positive Stress Tests Added

- Mixed-topic L5 runs never form a candidate pair.
- Same-topic but different corpus signatures do not form a pair.
- Same-topic but different code signatures do not form a pair.
- Non-consecutive clean L5 runs separated by a dirty/flagged run do not form a
  pair.
- Runs with flagged patches or auto-stripped patches do not form candidates.
- A certification output cannot confirm L6 if its `selected_pair` does not
  match the pair being evaluated.
- Historical flagged-patch pairs that previously reached the real gate
  (for example older metformin and resistance-training pairs) are now excluded
  before candidate formation because patch-log counts are read directly.

## Interpretation Boundary

L6 is a reproducibility label, not a scientific-novelty label. It says the
same topic/corpus/code cohort can produce clean journal-ready outputs
consecutively. It does not prove higher novelty than L5, cross-corpus
robustness, peer-review acceptance, or clinical truth.

## Changed Paths

- `scripts/l6_retrofit_report.py`
- `tests/test_l6_retrofit_report.py`
- `tests/test_arbitration_validation_harness.py`
- `docs/l6_retrofit_v1.md`
- `reports/arbitration_validation/endgame_validation_plan_2026_05_08.md`
- `reports/l6_generalization_2026_05_08/`
- `reports/l6_reproducibility_generalization_2026_05_08.md`
