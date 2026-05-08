# Validation Reference Plan — 2026-05-08

## Scope

This is a local, no-network validation plan for the tri-agent arbitration and methods-evidence lane. It does not claim Cochrane-equivalent validation. It defines what must be collected before such a claim is defensible.

## Reference Set

Target `N=10` Cochrane-like reviews, chosen to cover geroscience-adjacent evidence shapes:

| Slot | Review Type | Reason |
|---|---|---|
| 1 | Statins primary prevention | Large cardiovascular RCT/meta-analysis base |
| 2 | Statins secondary prevention | Distinct risk-benefit boundary |
| 3 | Omega-3 cardiovascular outcomes | Conflicting trial signals |
| 4 | Metformin diabetes prevention | Mature clinical and mechanistic evidence |
| 5 | Caloric restriction / weight loss maintenance | Behavioral intervention heterogeneity |
| 6 | Vitamin D fracture/frailty outcomes | Common null/heterogeneous outcomes |
| 7 | Resistance training sarcopenia outcomes | Functional endpoint emphasis |
| 8 | Sleep intervention cardiometabolic outcomes | Indirectness and adherence issues |
| 9 | Anti-inflammatory intervention cardiovascular outcomes | Mechanism-to-clinic tension |
| 10 | Dementia-prevention pharmacologic intervention | High risk of indirectness and bias |

## Local Fixture Shape

Each reference review should be transcribed into local JSON before running the validation harness:

```json
{
  "review_id": "string",
  "review_label": "string",
  "topic": "string",
  "included_studies": [{"study_id": "string", "citation": "string"}],
  "human_rob": [{"study_id": "string", "domain": "string", "judgment": "low|some_concerns|high"}],
  "human_grade": [{"outcome": "string", "certainty": "high|moderate|low|very_low"}],
  "human_effects": [{"outcome": "string", "effect": "string", "ci": "string"}],
  "researka_output_path": "local/path/or/null",
  "notes": "string"
}
```

No live web/API calls are required. Human reference fields are copied manually from already-downloaded review PDFs or existing local review notes.

## Tri-Agent Patch Fixture Shape

Patch arbitration fixtures are local JSON/JSONL rows with:

- `id`
- `patch_id`
- `patch_type`
- `severity`
- `before`
- `after`
- `grok_rationale`
- `smart_gate_reason`
- `expected_verdict`
- `manual_judgment_reason`
- `model_response`
- `source_run`

Allowed verdicts: `APPLY`, `REJECT`, `ESCALATE`.

## Metrics

Minimum reported metrics:

- overall agreement
- per-class agreement
- confusion matrix
- fail-closed count and rate
- bad-json rejection rate
- source-run availability count
- synthetic-vs-artifact-derived case count

## Claim Boundary

Passing the local arbitration fixture validates fixture parsing and recorded-decision agreement only. It does not validate live Mistral judgment, RoB 2 agreement, GRADE agreement, or Cochrane-equivalent dual-human review.
