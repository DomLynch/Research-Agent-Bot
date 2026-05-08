# Tri-Agent / Granite Arbitration Spec v2

Status: draft.

The arbitration layer is judge-only. It may decide whether a proposed patch or
review objection should apply. It must not write new scientific claims,
numerics, citations, estimates, or replacement prose.

## Roles

- Writer: produces candidate text or patch proposals from accepted evidence.
- Reviewer: flags risks, missing support, overclaims, and surface defects.
- Arbitrator: judges contested patches or reviewer objections.

IBM Granite may be used as the arbitrator when available. Granite is not a
domain authority; it is a logged judge in a bounded dispute.

## Judge-Only Constraint

Arbitrator output schema:

```json
{
  "verdict": "APPLY | REJECT | ESCALATE",
  "confidence": 0.0,
  "rationale": "short reason",
  "constraints_checked": ["no_new_claims", "no_new_citations"]
}
```

Invalid JSON, invalid verdicts, missing rationale, or any invented factual
content fail closed to `ESCALATE`.

## Audit Log

Every arbitration event writes:

- schema version
- run id
- patch id
- writer/reviewer model ids
- arbitrator model id
- input patch hash
- verdict
- rationale
- confidence
- fail-closed flag
- timestamp

The audit log is a sidecar. It does not replace deterministic audit, SPAR, or
final verdict artifacts.
