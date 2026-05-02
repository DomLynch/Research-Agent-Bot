# v0.6.0 Synthesis Paper — Trust-Spine Audit

**Score:** 9.0/10
**P1 ship-blockers:** PASS
**Pass rate:** 9/10 checks

## Checks

| # | Check | P1? | Status | Detail |
|---|---|---|---|---|
| Q1_word_count | Q1_word_count | **P1** | ✅ | word_count=8441 (threshold=5000) |
| Q2_numeric_integrity | Q2_numeric_integrity | **P1** | ✅ | 5/5 percentages trace to corpus (100%); untraceable: [] |
| Q3_no_paper_id_in_body | Q3_no_paper_id_in_body | **P1** | ✅ | no paper-ID leakage |
| Q4_no_polarity_error | Q4_no_polarity_error | **P1** | ✅ | no mortality/lifespan polarity error |
| Q5_no_fabricated_methods | Q5_no_fabricated_methods | **P1** | ✅ | no fabricated methodology claims |
| Q6_preclinical_hedge | Q6_preclinical_hedge | P2 | ✅ | unhedged preclinical→human sentences: 2 (threshold ≤3) |
| Q7_section_coverage | Q7_section_coverage | **P1** | ✅ | all required sections present |
| Q8_thesis_present | Q8_thesis_present | P2 | ✅ | thesis sentence found |
| Q9_numeric_density | Q9_numeric_density | P2 | ❌ | density 3.4 numerics/1000 words (threshold ≥8.0) |
| Q10_hedge_density | Q10_hedge_density | P2 | ✅ | 6/14 hedge phrases in Discussion (threshold ≥4) |

## Verdict: AAA

≥9.0 score AND no P1 failures. Paper passes the trust-spine gate.