# Planted-failure corpus — metformin

Five hand-crafted broken submissions. The Proof 001 pipeline must catch all
five at the gate listed in `expected_catch.gate`. If a future change re-routes
classification logic in a way that bypasses these protections, the relevant
test fails immediately.

| # | File | Failure type | Catches at | Day implemented |
|---|---|---|---|---|
| 1 | `case_1_protocol_as_results.json` | TAME (protocol) cited as "demonstrated CV benefit" | `topic_pack` registry override + verb-ban | Day 1 (topic-layer) → Day 2 (evidence_cards full) |
| 2 | `case_2_fabricated_nct.json` | NCT99999999 — entirely fake registry id | `citation_trace` via `TrialRegistryClient` | Day 3 |
| 3 | `case_3_inflated_pvalue.json` | Konopka 2019 cited with "p<0.001" (real: p=0.08) | `citation_trace` p-value text-grep | Day 3 |
| 4 | `case_4_alias_drift.json` | "Glufomin" — invented alias for metformin | `topic_pack` alias whitelist + `DrugAliasClient` | Day 1 (topic-layer) → Day 2 |
| 5 | `case_5_off_domain.json` | Oncology metformin paper cited as longevity evidence | `evidence_cards` topic-anchor gate (existing in bundle.py) | Day 2 |

## Format

Each fixture is JSON with this shape:

```json
{
  "case_id": "C1",
  "name": "protocol-as-results",
  "description": "...",
  "synthetic_source": {
    "ref": 1, "title": "...", "abstract": "...",
    "doi": null, "pmid": null, "nct": "NCT04264897",
    "year": 2025, "url": "...", "source": "ClinicalTrials.gov"
  },
  "synthetic_claim_text": "TAME demonstrated cardiovascular benefit ...",
  "synthetic_claim_verb": "demonstrated",
  "expected_catch": {
    "gate": "topic_pack",            // or evidence_cards / citation_trace
    "code": "ROLE_OVERRIDE_PROTOCOL",
    "detail_pattern": "registered_pending"
  }
}
```

## Discipline (v4 Rule 14 + Rule 57)

Tests that load these fixtures live in `tests/test_planted_failures.py`. As
each Proof 001 layer comes online (Day 2 evidence_cards, Day 3 citation_trace),
its test asserts the corresponding case is caught at the right gate with the
right error code.

If a fixture stops failing — i.e. the pipeline accepts a planted broken
submission — that is a P0 regression. Investigate before any other commit.
