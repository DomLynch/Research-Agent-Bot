# Submission rejected

## DRAFT REJECTED

**SPAR verdict:** `reject_critical` (3-0 unanimous reject).

## Proposed thesis (rejected)

> Change in Total Recall Score in the Selective Reminding Test. timeframe=12 months. Placebo=5.7 (±8.7); Metformin=9.4 (±8.5). p=0.05

## Failed citation traces

- **nct_exists** on `C072` (ref=33): NCT 'NCT00620191' not found in registry (fabricated or stale)
- **alias_match** on `C072` (ref=0): alias 'Change' NOT resolved (drift)
- **alias_match** on `C072` (ref=0): alias 'Recall' NOT resolved (drift)
- **alias_match** on `C072` (ref=0): alias 'Score' NOT resolved (drift)
- **alias_match** on `C072` (ref=0): alias 'Selective' NOT resolved (drift)
- **alias_match** on `C072` (ref=0): alias 'Reminding' NOT resolved (drift)
- **alias_match** on `C072` (ref=0): alias 'Test' NOT resolved (drift)

## Panel reviews

### `evidence_auditor` — `reject` (score 1)

The submission fails on critical evidence verification. The primary citation [33] failed the nct_exists trace, indicating that the referenced clinical trial ID (NCT00620191) is either fabricated or cannot be verified in the registry. Furthermore, there are systemic alias match failures for every key term in the claim's metric ('Change', 'Recall', 'Score', 'Selective', 'Reminding', 'Test'), indicating a complete disconnect between the claim's terminology and the source evidence.

**Flagged claims:** C072

### `domain_skeptic` — `reject` (score 3)

The claim is statistically precarious and lacks sufficient calibration. A p-value of exactly 0.05 is the absolute threshold of marginal significance; presenting this as a 'moderate' effect without discussing the high variance (standard deviations of 8.7 and 8.5 relative to means of 5.7 and 9.4) is misleading. The overlap in distributions is substantial, suggesting the result is not robust.

**Flagged claims:** C072

### `final_judge` — `reject` (score 1)

I align with both the Evidence Auditor and the Domain Skeptic. The submission is fundamentally flawed due to a failure in evidence verification; the primary citation [33] references a clinical trial ID (NCT00620191) that could not be found in the registry, which is a critical failure of authenticity. Additionally, the systemic failure of alias matches for every key term in the metric suggests that the claim is not properly grounded in the source text.

Even if the source were authentic, I agree with the Domain Skeptic that the statistical presentation is misleading. A p-value of 0.05 combined with standard deviations that exceed the mean values indicates an extremely high degree of overlap between the placebo and metformin groups, rendering the 'moderate' confidence rating unjustified. Given the combination of suspected fabrication and statistical fragility, the claim cannot be accepted.

**Flagged claims:** C072

## References

[33] Metformin in Amnestic Mild Cognitive Impairment (2012). https://clinicaltrials.gov/study/NCT00620191
