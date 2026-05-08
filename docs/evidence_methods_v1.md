# Evidence Methods Scaffold v1

This lane is render/scaffold only. It does not insert methods tables or
meta-analysis into the manuscript pipeline.

## Labels

- RoB output is a derived screening aid, not a full Cochrane RoB 2 signaling
  questionnaire.
- GRADE output is conservative GRADE-lite, not a full GRADE evidence profile.
- Meta-analysis uses fixed-effect inverse-variance pooling only when at least
  two compatible effect sizes and standard errors are present.

## Fail-Closed Rules

- Missing tier/directness: RoB high risk, fail-closed.
- Missing or invalid GRADE fields: very low certainty, fail-closed.
- Missing effect size, missing standard error, mixed effect measures, or fewer
  than two compatible studies: no pooled estimate.
- High risk of bias in the requested outcome: no pooled estimate.
- Plot functions return placeholder contracts only; they add no plotting
  dependency.
