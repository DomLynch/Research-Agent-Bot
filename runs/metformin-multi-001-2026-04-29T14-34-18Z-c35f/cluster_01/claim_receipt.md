# Submission rejected

## DRAFT REJECTED

**SPAR verdict:** `reject_critical` (3-0 unanimous reject).

## Proposed thesis (rejected)

> Mean 4-m walk speed at 4 months was 0·57 m/s (SD 0·19) in the metformin group and 0·58 m/s (0·24) in the placebo group (adjusted treatment effect 0·001 m/s [95% CI -0·06 to 0·06]; p=0·96).

## Failed citation traces

- **nct_exists** on `C011` (ref=4): NCT 'ISRCTN29932357' not found in registry (fabricated or stale)
- **nct_exists** on `C012` (ref=4): NCT 'ISRCTN29932357' not found in registry (fabricated or stale)
- **nct_exists** on `C013` (ref=4): NCT 'ISRCTN29932357' not found in registry (fabricated or stale)
- **nct_exists** on `C014` (ref=4): NCT 'ISRCTN29932357' not found in registry (fabricated or stale)

## Panel reviews

### `evidence_auditor` — `reject` (score 1)

The submission fails the evidence audit due to critical failures in citation tracing. Specifically, the registry identifier 'ISRCTN29932357' associated with reference [4] failed the nct_exists check across all claims (C011, C012, C013, and C014). This indicates that the primary source of evidence for the entire thesis is either fabricated or cannot be verified in the official registry.

**Flagged claims:** C011, C012, C013, C014

### `domain_skeptic` — `reject` (score 3)

The submission suffers from severe sample-size issues and an over-scoped conclusion. The data provided (C011-C013) is derived from an extremely small cohort (n=71 total), which is insufficient to make broad claims about tolerability or efficacy in a general population. 

Specifically, claim C014 extrapolates a definitive conclusion ('was poorly tolerated in this population') based on a tiny sample where the difference in adverse events between groups is marginal (100% vs 92%). Furthermore, the claim that metformin 'did not improve' walk speed based on a single small trial is an overstatement of the evidence; a lack of statistical significance in an underpowered study is not proof of a lack of effect. The conclusion is not appropriately calibrated to the weakness of the underlying data.

**Flagged claims:** C014

### `final_judge` — `reject` (score 1)

I align with both the Evidence Auditor and the Domain Skeptic. The submission is fundamentally flawed due to a critical failure in the verification of the primary source; the registry identifier (ISRCTN29932357) failed the nct_exists check, rendering the data in C011, C012, and C013 unverifiable and potentially fabricated. Even if the data were authentic, the Domain Skeptic correctly identifies that the sample size (n=71) is far too small to support the definitive conclusions drawn in C014 regarding tolerability and efficacy. The combination of a failed audit trail and severe over-extrapolation makes this submission entirely unreliable.

**Flagged claims:** C011, C012, C013, C014

## References

[4] Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT): a double-blind, randomised, placebo-controlled trial. (2025). https://pubmed.ncbi.nlm.nih.gov/40147475/
