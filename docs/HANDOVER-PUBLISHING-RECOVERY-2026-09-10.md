# V3 publishing recovery — audited status, 10 September 2026

Publishing recovery is **not complete**. Step 1 is deployed and verified.
The latest full manuscript replay preserves a substantive 447-word Conclusion,
resolves all eight scientific-review patches, and passes 14/14 structural audits.
The subsequent rendering audit removes two external table locators without
changing source files. The normal six-request structural gate now passes;
a fresh full scientific review and final payload check are next. No recovery
submission or publication has been made.

## Five-step status

| Step | Implementation and first audit | Second audit / completion status |
|---|---|---|
| 1. Bound reconciliation and revision startup | Durable, fair polling with a 60-second budget, bounded individual requests, atomic checkpoints and preservation of partial valid results. | **Complete for reconciliation.** Two actual production service runs finished in 57–58 seconds with exit 0; 80 distinct IDs were retained across passes. This does not prove that a scientific revision completes. |
| 2. Correct source records, QEI and Methods | Authorized classification corrections preserve all 37 identities. Historical retrieval records distinguish 4,286 metadata candidates, 1,384 retained at metadata selection and 114 extracted records from the 37 admitted receipts. QEI exposes endpoint, study comparison, estimate, uncertainty, significance and exact result clause. | **Open.** Full-source QEI review retained 30 of 31 rows and quarantined an internally conflicting statistic. All six stored revision asks pass structural coverage, but final scientific coverage and manuscript framing remain unproven. |
| 3. Preserve completeness through repair | Fixed sentence boundaries, numeric-role mistakes, exact-quote formatting and overly aggressive paragraph similarity. Methods are rendered before review; reviewers receive verified source evidence. | **Manuscript repair verified.** The latest configured writer produced 437 words; the normal full-review/repair pipeline retained 447, with no numeric issues, all eight review patches resolved and all source hashes unchanged. Final payload and live revision remain to be proved. |
| 4. Align publishing contracts | Current reviewer-v15 policy retained. No model, acceptance threshold, source identity or section-floor waiver. Writer/reviewer source context now includes complete own-result passages, including conflicting passages. | **Partially verified.** Latest replay passes 14/14 audits. Private source/author-record review preserves justified prose; normal numeric, citation, depth and Core acceptance gates remain. Rendering audit clears the two orphan source-table references and verifies Findings Map statistics against full own-source Results. |
| 5. Prove publication and repeatability | Two controlled manuscript runs and a separate real QEI review were executed without submitting. | **Not complete.** No accepted Core decision or new public artifact; no successful repeatability series across distinct topics. |

## Current code and production

- Tested development commit: `a93a8d4f4c2fa3218d823057579cf474e72d583e`,
  pushed to `codex/01a089bc/main`. Later documentation-only commits may follow.
- Production `/opt/research-agent-bot` and `/root/Research-Agent-Bot` remain on
  the reconciliation release `64086d2fe119c85529af8e6a3963cb15d9d23920`.
- Production trees were clean. All three lane timers were active. The latest
  observed fresh service was failed; revise and reconcile were idle. Timer
  enablement is not evidence of successful paper generation.
- The broader scientific repairs have **not** been deployed to production.
  Do not overwrite an active checkout to test them.

## Verification receipts

- Full development suite: **4,922 passed**, two existing XPASS results,
  16 warnings; 159.03 seconds.
- `make quality`: passed, including 343 gate/coverage/LOC tests.
- Mypy: passed for 180 source files. No complexity, duplication or LOC ceiling
  was raised. Obsolete explanatory history was condensed in citation helpers.
- Focused source/QEI/writer/submission checks: 553 passed.
- Isolated VPS checks: 144 passed; seven tests skipped because their parsed-PDF
  fixtures are absent. Runtime checkout: `/tmp/v3-recovery-review-parity-20260910`.
- Local receipts: `/tmp/v3-final-source-review-suite.log`,
  `/tmp/v3-qei-consistency-quality-2.log`,
  `/tmp/v3-qei-consistency-mypy.log`.

## Important scientific findings

The Montoya-Estrada source is internally inconsistent: its Results and abstract
report total antioxidant capacity increases of 30% for resveratrol plus vitamin
C and 28% for vitamin C, while its Conclusion says vitamin C increased capacity
by up to 33%. The previous extractor omitted the relevant Results sentences
because it missed nominal effect language and changed source typography.
Those extraction defects are fixed. The new configured Terra review rejected
the disputed row in 38.21 seconds and retained 30 other rows. It did not replace
33% with 30%, which would have changed the treatment attribution. All source
snapshot hashes remained unchanged.

The complete manuscript review also found:

- An unclear research question and a mismatch between measurement-method
  eligibility wording and the admitted intervention studies.
- A PRISMA scoping-synthesis claim that the reviewer judged unsupported by the
  available screening documentation.
- Directness wording that overstates the clinical proximity of biomarker and
  pharmacokinetic outcomes; a pseudo-randomized study described as observational.
- Unsupported source-context tallies and claimed disagreements between studies
  that both reported favorable inflammatory-marker changes.
- A Conclusion composed of unintegrated source excerpts. The retry prompt
  currently steers failed paraphrases toward verbatim source sentences, while
  the patch process favors deletions. That interaction still needs repair.

Literal source tracing and a high deterministic score do not resolve these
scientific findings. The 29/30 score in the later replay is the deterministic
publication scorer, not a Core acceptance or an independent semantic verdict.

## Current recovery route and next audit

We are proceeding with a **full-length curated evidence map** using the verified
existing records. The optional scope question received no answer; it is not a
reason to stop the authorized work. The new `curated_evidence_map` type remains
outside compact types and preserves the 400-word Results / 180-word Conclusion
minimums. The question, Methods and appraisal disclosure must describe the work
actually supported by the records.

The first curated replay's real Terra review accepted the Abstract's scientific
findings and limitations, but rejected its question and Methods paragraphs:
external papers cannot establish our own mapping procedure. The private prose
review now also receives the run's question, source count, retrieval and Methods
records. Such author assertions can remain uncited when justified by those
records; study findings still require their cited sources. Text, source bundle,
Methods and policy hashes invalidate stale approvals. No cache fields are sent
to Core, and full manuscript review and normal acceptance remain mandatory.

The source/prose regression suite has 17 passing cases, including changed values,
source/citation changes, negative/malformed review, author-record attribution,
changed methods, policy changes, and context isolation. Focused writer/pipeline
checks passed 139 cases locally and on the isolated VPS. Quality's 343 checks
and mypy passed without increasing limits. Historical docstrings were condensed;
AST comparisons proved executable parity for those documentation edits.

The second replay is `/tmp/v3-curated-replay-v2.py` on the isolated VPS; its log
is `/tmp/v3-curated-replay-v2.log`. It must demonstrate a substantive supported
Conclusion after the normal pipeline, complete semantic coverage of all six Core
requests, and every final gate. Then require a normal Core decision and public
artifact, followed by distinct-topic runs including a revision. Native Abstract
generation and cross-topic repeatability still need proof; do not call this
standardized publishing yet.

Replay artifacts are under `.tmp/v3-standardized/runs/`, especially
`synthesis-resveratrol-parity-replay-20260910` and
`synthesis-resveratrol-standardized-20260910-LATEST-DETERMINISTIC`.
The completed QEI audit is on the isolated VPS at
`qei-statistical-consistency-audit/`; its copied local review is
`/tmp/v3-qei-complete-source-review.json`.

## Latest second audit: Methods and source layout

The first six-request review reported only the classification/quality request
unmet. A direct audit localized its deterministic failure to a required Methods
criterion phrase removed during the wording correction. Methods now explicitly
state when human primary evidence is coded direct and retain the qualification
that directness establishes neither clinical benefit nor low risk of bias.
All six requests pass the unchanged structural gate.

The layout audit also found that the statistics checker read abstracts alone.
It now reads verified own-result excerpts as separate passages. Only pure source
layout parentheticals are omitted during comparison/rendering; mixed statistical
parentheticals, altered values, endpoints, operators and wrong-source claims
still fail. All Findings Map statistics pass that check on the actual manuscript.
The rendering pass is idempotent, and source snapshot hashes are unchanged.

Focused Methods/source-layout/revision checks: 433 passed. Quality 343 and mypy
180 files passed. The initial broad run exposed two obsolete wording assertions;
those are fixed and the broad suite is rerunning. Final isolated replay script:
`/tmp/v3-curated-final-v3.py`. No production rollout of these changes yet.
