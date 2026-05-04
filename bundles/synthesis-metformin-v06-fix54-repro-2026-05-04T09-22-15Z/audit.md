# v0.6.0 Synthesis Paper — Trust-Spine Audit

**Score:** 10.0/10
**P1 ship-blockers:** PASS
**Pass rate:** 13/13 checks

## Checks

| # | Check | P1? | Status | Detail |
|---|---|---|---|---|
| Q1_word_count | Q1_word_count | **P1** | ✅ | word_count=9863 (threshold=5000) |
| Q2_numeric_integrity | Q2_numeric_integrity | **P1** | ✅ | 33/33 numerics trace to corpus (100%); per-category: percentage=13/13, p_value=11/11, ratio=4/4, sample_size=2/2, dose=1/1, speed=2/2; untraceable: {} |
| Q3_no_paper_id_in_body | Q3_no_paper_id_in_body | **P1** | ✅ | no paper-ID leakage |
| Q4_no_polarity_error | Q4_no_polarity_error | **P1** | ✅ | no mortality/lifespan polarity error |
| Q5_no_fabricated_methods | Q5_no_fabricated_methods | **P1** | ✅ | no fabricated methodology claims |
| Q6_preclinical_hedge | Q6_preclinical_hedge | P2 | ✅ | unhedged preclinical→human sentences: 1 (threshold ≤3) |
| Q7_section_coverage | Q7_section_coverage | **P1** | ✅ | all required sections present |
| Q8_thesis_present | Q8_thesis_present | P2 | ✅ | thesis sentence found |
| Q9_numeric_density | Q9_numeric_density | P2 | ✅ | density 13.8 numerics/1000 words (threshold ≥8.0; contract=2026-05-03-v2) |
| Q10_hedge_density | Q10_hedge_density | P2 | ✅ | 9/14 hedge phrases in Discussion (threshold ≥4 — Fix #44 adaptive: corpus uncertainty-weighted) |
| Q11_discussion_depth | Q11_discussion_depth | P2 | ✅ | Discussion 911 words (threshold ≥800 — Fix #41 depth gate) |
| Q12_cross_domain_depth | Q12_cross_domain_depth | P2 | ✅ | Cross-Domain Synthesis 1060 words (threshold ≥800 — Fix #42 depth gate) |
| Q13_analytical_ratio | Q13_analytical_ratio | P2 | ✅ | analytical ratio 20.0% (Discussion 911 + Cross-Domain 1060 / body 9863; threshold ≥15% — Fix #43 depth gate) |

## Verdict: AAA

All 13 checks pass (P1 + P2). Paper meets the AAA bar.