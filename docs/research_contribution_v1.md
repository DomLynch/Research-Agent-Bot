# Research Contribution v1

This lane is a deterministic scaffold, not a manuscript writer.

## Scope

- `scripts/novel_framework.py` builds structured boundary-condition rows,
  gap priorities, trial-design recommendations, and a framework proposal.
- `scripts/research_contribution_report.py` renders those structures to
  Markdown for review.
- The helper stays under `scripts/` so it does not add to the `agent/`
  runtime LOC budget.

## Inputs

- `manifest["receipts"]` rows with `outcome_class`, `directness`, and
  `effect_direction`.
- Optional claim rows with the same fields.
- Optional tension rows with `outcome_class` and `severity`.

## Guarantees

- No LLM calls.
- No topic-specific Python branches.
- No unsupported scientific numerics, doses, p-values, ratios, or effect sizes.
- Trial-design recommendations fail closed when structured evidence is thin.
- Framework proposals are validated scaffolds only; they do not claim novelty
  unless the structured evidence has enough matrix and gap signal.

## Non-goals

- No pipeline integration in v1.
- No topic-specific recommendation text.
- No replacement for human study-design expertise.
