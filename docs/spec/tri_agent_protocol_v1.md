# Tri-Agent Protocol v1

Status: draft spec reflecting the current bounded Mistral arbitration
contract. It is not a claim of equivalence to human dual-review or peer review.

## Roles

| Role | Function | Boundary |
|---|---|---|
| Writer | Drafts manuscript prose from accepted evidence artifacts. | Cannot create certified claims outside the claim graph. |
| Reviewer | Flags unsupported claims, malformed citations, numeric drift, and public-surface defects. | Proposes patches; does not certify final truth. |
| Arbitrator | Judges contested reviewer patches. | Only `APPLY`, `REJECT`, or `ESCALATE`; never rewrites. |

Mistral Small 4 may serve as the V1 arbitrator through the configured provider.
It is a bounded judge, not a domain authority.

## Arbitration Input

Each arbitration case should include:

- `patch_id`
- exact `before`
- exact `after`
- reviewer rationale
- smart-gate refusal reason
- bounded local paper context
- deterministic context hash
- model identifiers

No secrets, hidden prompts, or full private source payloads should be sent.

## Arbitration Output

The only accepted schema:

```json
{
  "verdict": "APPLY",
  "confidence": 0.0,
  "rationale": "short reason"
}
```

`verdict` must be exactly `APPLY`, `REJECT`, or `ESCALATE`.

## Deterministic Boundary

The model never supplies replacement prose. If `APPLY` is accepted, code applies
the exact reviewer-proposed `after` text only when:

- `before` appears exactly once
- the patch class is allowed by deterministic policy
- the patch does not introduce new claims, citations, or numerics
- post-apply audit remains safe

`REJECT` preserves the original manuscript text and logs the reason. For unsafe
deletion disputes, `REJECT` may be treated as `ESCALATE` so the existing
fail-closed path still handles the risk.

`ESCALATE`, timeout, bad JSON, invalid verdict, missing rationale,
non-unique `before`, or failed post-apply audit all fail closed.

## Logs

Every arbitration event must write a sidecar entry:

- schema version
- run id
- patch id
- decision
- model id
- rationale
- confidence
- input hash
- fail-closed reason when applicable
- timestamp

The final review patch log should include arbitration counts. A run must not
silently inflate from L4 to L5 because a third model was consulted.

## Validation State

Current internal Granite validation showed low raw agreement on unconstrained
semantic arbitration cases. The implemented value is therefore narrow:
deterministic wrapping plus logged third-reviewer signal, not broad semantic
override authority. External validation against human-consensus fixtures remains
planned.
