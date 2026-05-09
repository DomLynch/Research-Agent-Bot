# AAA-SCOP Certification Track Proposal v1

Status: runtime v1 wired.

## Purpose

`AAA-SCOP` is a proposed scoped-certification track for evidence briefs that
are traceable, review-clean, and useful, but do not clear the full AAA evidence
floor or directness requirements. It exists to avoid two bad outcomes:

- inflating thin or narrow topics into full AAA
- discarding bounded evidence work that is honest about scope

## Non-Negotiable Boundary

`AAA-SCOP` is not full-corpus AAA. It can certify a bounded scoping artifact
when the audit/review gates are clean and the corpus has at least one direct
A1 receipt, but it must keep scoped labels visible.

| Field | Full AAA | AAA-SCOP proposal |
|---|---|---|
| `verdict` | `AAA` | `AAA` with `certification_track=AAA-SCOP` |
| `maturity_level` | L4-L5 single run, L6 with consecutive evidence | L4/L5 with scoped maturity label |
| `journal_ready` | possible | possible only as `L5-SCOPING-JOURNAL-READY` |
| `l6_reproducibly_journal_ready` | possible after adjacent L5 pair | false |
| Public wording | synthesis paper | scoped evidence brief |

## Candidate Entry Gate

A topic may be considered for `AAA-SCOP` only when all are true:

- deterministic audit has no P1 blockers
- stage-2 consistency has no P1 blockers
- reviewer unresolved P1 count is zero
- journal surface gate passes
- numeric traceability is complete for included claims
- all included claims are source-traced and citation-whitelisted
- scope envelope is machine-readable and visible in the rendered artifact

Runtime v1 scoped evidence floor:

- `2 <= n_receipts < 10`
- `n_high_confidence_claims_total > 0`
- at least one `A1` direct receipt
- no unsupported longevity, mortality, or clinical recommendation claim

These floors are intentionally below full AAA and therefore cannot promote L5.

## Scope Envelope

Every AAA-SCOP artifact must carry:

- `scope_kind`: `mechanistic`, `safety`, `pilot_clinical`, `adjacent_clinical`,
  `thin_topic`, or `methods_demo`
- `scope_claim`: one sentence naming exactly what the artifact supports
- `excluded_claims`: claims the artifact explicitly does not support
- `dominant_directness`: direct, indirect, mechanistic, or review
- `dominant_evidence_tier`: A1/A2/B1/B2/C1/C2/unknown
- `reader_warning`: standard prose that this is not full AAA

## Required Metadata

Minimum JSON fields:

```json
{
  "verdict": "AAA",
  "certification_track": "AAA-SCOP",
  "scope_kind": "mechanistic",
  "scope_claim": "...",
  "excluded_claims": ["..."],
  "maturity_label": "L4-SCOPING-CERTIFIED",
  "journal_ready": false,
  "l6_reproducibly_journal_ready": false,
  "full_aaa_eligible": false
}
```

## Implementation Plan

1. Runtime selects `AAA-SCOP` in `_select_certification_track()`.
2. Tests prove clean thin direct-A1 corpora can reach scoped L5.
3. Tests prove scoped surgery remains `L4-SCOPING-CERTIFIED`.
4. Dashboard rendering must keep `AAA-SCOP` separate from full-corpus L5/L6.

## Acceptance Tests

- Thin direct-A1 corpus with clean audits can become `AAA` under
  `certification_track=AAA-SCOP`.
- `AAA-SCOP` plus clean public surface can become
  `L5-SCOPING-JOURNAL-READY`.
- Consecutive `AAA-SCOP` runs do not become L6.
- Full AAA tracks are unchanged.
- Dashboards count AAA-SCOP separately from L4/L5/L6.

## Open Risks

- Readers may still infer full AAA from the token `AAA`. UI copy must lead with
  "Scoped" and not badge it as journal-ready.
- Evidence floors need empirical calibration from thin-topic lanes.
- Existing `SCOP` runtime track currently means floor-fail; migration must not
  reinterpret old `SCOP` artifacts as certified.
