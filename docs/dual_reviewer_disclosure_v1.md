# Dual Reviewer Disclosure v1

Research Agent Bot may use two independent AI review layers before human use:

1. SPAR panel review checks evidence support, domain scope, and final verdict.
2. Granite arbitration may judge whether a proposed patch should `APPLY`,
   `REJECT`, or `ESCALATE`.

Both layers are AI-only reviewers. They do not replace human scientific review,
peer review, regulatory review, or editorial accountability.

## Limits

- Reviewers judge supplied material only.
- Reviewers must not introduce manuscript prose, new facts, numerics, claims,
  citations, or replacements.
- Malformed reviewer output fails closed to `ESCALATE`.
- Logs must not contain API keys, tokens, hidden prompts, or source secrets.

## Disclosure Text

This artifact may have been screened by AI reviewer systems for evidence
support and patch arbitration. These systems are advisory and judge-only; final
responsibility remains with the human operator.
