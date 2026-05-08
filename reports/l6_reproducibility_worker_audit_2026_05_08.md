# L6 Reproducibility Worker Audit - 2026-05-08

## Verdict

Rapamycin PATHA8/9/10 has confirmed L6 evidence from existing run bundles.
No paper was rerendered.

## Run Evidence

| Run | Generated | Verdict | Level | JS | Reviewer P1 | Receipts | Claims | Tensions |
|---|---:|---|---:|---|---:|---:|---:|---:|
| `synthesis-rapamycin-v06-PATHA8-2026-05-07T09-02-06Z` | `2026-05-07T09:19:20+00:00` | AAA | 5 | true | 0 | 16 | 72 | 31 |
| `synthesis-rapamycin-v06-PATHA9-2026-05-07T09-20-53Z` | `2026-05-07T09:37:57+00:00` | AAA | 5 | true | 0 | 16 | 72 | 31 |
| `synthesis-rapamycin-v06-PATHA10-2026-05-07T09-38-47Z` | `2026-05-07T09:54:14+00:00` | AAA | 5 | true | 0 | 16 | 72 | 31 |

## Consecutive Gate Evidence

Direct three-run gate:

- Output: `reports/l6_arbitration_worker/cert/rapamycin_patha8_9_10_consecutive.json`
- `certified`: true
- `maturity_level`: 6
- `l6_reproducibly_journal_ready`: true
- `l6_blockers`: []
- Selected pair: `PATHA9` + `PATHA10`

Pairwise retrofit gate:

- Output: `reports/l6_arbitration_worker/rapamycin_patha_retrofit/report.json`
- Status: `confirmed_l6`
- Candidate pairs:
  - `PATHA8` + `PATHA9`
  - `PATHA9` + `PATHA10`
- Both pairwise cert outputs returned `maturity_level=6`,
  `l6_reproducibly_journal_ready=true`, and empty `l6_blockers`.

## Audit Pass 1

- Consecutive ordering: PATHA8, PATHA9, PATHA10 are ordered by manifest
  `generated_at`.
- Same topic: all three manifests report `topic=rapamycin`.
- Same corpus: all three report 16 receipts, 72 high-confidence claims, and
  31 non-orthogonal tensions.
- Same code signature: all three report `extractor_version=v0.6.0` and
  `writer_path=agent.paper_writer.render_full_paper (production)`.
- Cleanness: all three are AAA/L5, JS pass true, reviewer unresolved P1 = 0,
  Stage-2 P1 = 0, Stage-2 P2 = 0.

## Audit Pass 2

- The retrofit scanner groups by topic, corpus signature, and code signature
  before forming pairs.
- `confirmed_l6` requires the real `certification_report.py --consecutive`
  gate, not just adjacent L5 labels.
- Added false-positive guard: if the cert output's `selected_pair` does not
  match the evaluated pair, the pair is blocked.
- Added test: `test_wrong_selected_pair_cannot_confirm_l6`.

## Boundary

This proves local run-level L6 reproducibility for the existing rapamycin
PATHA run bundles. It does not prove cross-corpus L8 reproducibility, human
peer-review acceptance, or external clinical truth.
