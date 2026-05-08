# Methodology Paper Outline v1

Working title: *A Deterministic Trust Spine for AI-Assisted Evidence Synthesis*

## Thesis

LLMs can draft and critique evidence syntheses, but categorical trust decisions
must be made by deterministic code and auditable artifacts.

## Outline

1. Problem: generated reviews can hide unsupported claims.
2. Architecture: LLM proposes, code disposes.
3. Evidence objects: receipts, claim graph, citation trace, audit, verdict.
4. Rendering: markdown/paper surfaces are downstream of structured artifacts.
5. Arbitration: judge-only patch dispute resolution.
6. Bundle schema: public artifact completeness and hash integrity.
7. Reader/provenance split: static public reader vs provenance registry vs OSF.
8. Validation study.
9. Limitations.
10. Future work.

## Validation Study Design

- Corpus: multiple health/longevity topics with predeclared source bundles.
- Conditions: baseline single-run, repeat-run L6, cross-model L7, cross-corpus
  L8.
- Outcomes: unsupported claim rate, numeric trace error rate, citation role
  error rate, reviewer escalation rate, reproducibility rate.
- Adjudication: blinded human review on sampled claims and deterministic logs.
- Failure reporting: publish rejected runs and quarantine reasons.

## Limits

- Not a substitute for a full systematic review protocol.
- No active PROSPERO path.
- Not a Cochrane RoB or GRADE replacement unless those full instruments are
  explicitly run.
- OSF and provenance publication are downstream infrastructure, not evidence
  validity guarantees.
