# Verdict Taxonomy v1

Status: draft spec. L0-L6 are current operational targets. L7-L8 are planned
trust events that require stronger validation evidence before public claims.

This taxonomy describes artifact maturity, not scientific novelty, clinical
truth, or marketing quality. A scoped paper can be useful without becoming
full AAA, and a full AAA paper can remain below L5 when the public surface or
repair trail is not clean.

## Levels

| Level | Label | Meaning | Minimum evidence |
|---:|---|---|---|
| L0 | Unseeded | No usable run artifact. | No receipts or no completed run. |
| L1 | Seeded | Receipts exist, but extraction or claim graph is insufficient. | Manifest or corpus seed exists. |
| L2 | Partial | Claims exist but corpus or audit floor is not met. | Some traceable claims, below synthesis floor. |
| L3 | Floor-met | Corpus floor is met, but certification is blocked. | Audit/review/verdict identifies remaining blockers. |
| L4 | Analytically certified | AAA verdict passes, but clean journal-ready criteria are not met. | Full audit pass, no unresolved P1, known surgery or maturity limitation. |
| L5 | Journal-ready single run | One run passes cleanly with no unresolved P1, no auto-strips, and clean public surface. | Final verdict JSON/MD plus clean audit/review logs. |
| L6 | Reproducibly journal-ready | Two or more consecutive same-topic L5 runs pass without material regression. | Consecutive certification report naming run pair(s). |
| L7 | Cross-model concordant | Planned: L6 plus independent model-family review agrees on verdict-critical claims. | Not claimed until benchmarked and logged. |
| L8 | Cross-corpus reproducible | Planned: cross-model plus independently assembled corpus preserves thesis and verdict class. | Not claimed until second-corpus report exists. |

## No Fake L5 Inflation

L5 is not a reward for good prose. It requires a clean single-run trust event.
The following block L5:

- reviewer unresolved P1
- flagged review patches that remain unresolved after repair/arbitration
- reviewer auto-strip or equivalent surgery
- journal-surface failure
- malformed public numerics or leaked internal labels
- missing final verdict artifact
- unlogged arbitration decision on verdict-critical patch

Third-model arbitration can resolve a contested patch only when the deterministic
boundary accepts the result and writes the log. It must not silently erase the
fact that a patch was contested.

## Cert Math

Required `full_paper.final_verdict.json` fields:

- `verdict`
- `reason`
- `maturity_level`
- `maturity_label`
- `journal_ready`
- `certification_track`
- `stage1_p1_pass`
- `stage1_score`
- `stage1_pass_rate`
- `stage2_p1`
- `stage2_p2`
- `stage2_unknown_severity_count`
- `grok_unresolved_p1`
- `grok_flagged`
- `journal_surface_pass`
- `journal_surface_issues`
- `evidence_weight_total`
- `evidence_weight_clinical`
- `evidence_weight_mechanistic`
- `n_arbitrated`, `n_arbitration_apply`, `n_arbitration_reject`,
  `n_arbitration_escalate` when applicable

Required single-run certification fields from `full_paper.certification.json`:

- `final_verdict`
- `aaa_pass`
- `q2_traceability_pct`
- `q2_full`
- `stage2_p1`
- `stage2_p2`
- `grok_unresolved_p1`
- `auto_stripped_patches`
- `flagged_patches`
- `journal_surface_pass`
- `certification_gate_version`

L6 requires a separate consecutive-run report over consecutive clean L5 runs.
Batch dashboards may nominate L6 candidates but do not upgrade final verdicts
by themselves.

## Certification Tracks

Current runtime tracks:

| Track | Meaning | Can produce full `AAA` today? | Boundary |
|---|---|---:|---|
| `AAA-CLIN` | Direct clinical evidence clears the flat corpus floor. | yes | May support journal-ready claims if all L5 gates are clean. |
| `AAA-INF` | Weighted direct plus mechanistic evidence clears the inferential floor. | yes | Requires machine-checked D1 bridge claims; not a direct clinical recommendation. |
| `AAA-MECH` | Mechanism-heavy evidence clears the mechanistic floor. | yes | Requires D1 bridge claims; must stay mechanism-scoped. |
| `SCOP` | Floor-fail track. | no | Means trust spine may pass, but scoped or full AAA is blocked on evidence substance. |
| `AAA-SCOP` | Bounded scoping-cert track for thin but direct-A1 corpora. | yes, scoped | Requires 2-9 receipts, at least one A1 direct receipt, positive high-confidence claims, all audit/review gates clean, and visible scoped maturity label. |

`AAA-SCOP` is wired as a scoped certification track, not as full-corpus AAA.
It may return `verdict=AAA` only with `certification_track=AAA-SCOP` and a
scoping maturity label. It cannot become L6 without a future scoped
reproducibility policy.

## L6 Metadata

The consecutive certification path writes topic-level fields in the report
object and, for retrofitted run verdicts, into `full_paper.final_verdict.json`:

- `l6_reproducibly_journal_ready`
- `l6_evidence`
- `l6_blockers`
- `l6_selected_pair`
- `consecutive_aaa_count`
- `consecutive_aaa_run_ids`
- `consecutive_l5_count`
- `consecutive_l5_run_ids`
- `certification_gate_version`
- `maturity_level`
- `maturity_label`

L6 is true only when the selected adjacent same-topic pair is clean L5 under
the same gate. An adjacent AAA pair with auto-strip, flagged patch, journal
surface failure, mixed topics, or mixed gate versions is not L6.

## Scientific Novelty Boundary

The maturity level is a trust/maturity label, not a novelty score. A narrow but
stable paper can be L6; a richer and more original paper can remain L4 if it
required surgery or lacks reproducibility evidence.

## No SCOP Inflation

Plain `SCOP` artifacts must not be rendered as:

- `verdict=AAA`
- `maturity_level>=5`
- `journal_ready=true`
- `l6_reproducibly_journal_ready=true`

`AAA-SCOP` artifacts may render as `verdict=AAA`, but only with:

- `certification_track=AAA-SCOP`
- `maturity_label=L4-SCOPING-CERTIFIED` or `L5-SCOPING-JOURNAL-READY`
- explicit scope language in the verdict block and limitations
- no L6 claim

They are useful reader products only when the scope is visible in the title,
abstract, verdict block, limitations, and machine-readable metadata.
