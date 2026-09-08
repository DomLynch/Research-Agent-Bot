# V3 source ownership and evidence classification audit

Scope: local V3 only, based on HEAD 10a38832ef257bb6f522db6ff41cd8b9e9506834.
No Core edits, live deployment, model calls, submission or publication in this verification.

## Findings and repairs

- QEI previously proved only that a sentence existed in the host paper. It now
  checks result-section ownership and excludes explicit cited/background findings.
  This is conservative screening, not a general semantic proof of every claim.
- The taxonomy missed "Rationale and Study Design" and used background descriptions
  of earlier randomized studies as evidence of the host paper's design. Structured
  Methods now supplies abstract design evidence; case-series terms are recognized.
- An explicit multi-source classification correction previously failed authorization
  because tier and directness counted as two independent fields. That coupled pair
  is now allowed for named sources only. Mixed unrelated field changes still fail.
- Active full-paper section calls/retries, final-review/patch-repair prompts and
  revision-coverage prompts share PUBLICATION_REQUIREMENTS, targeting Core's
  reviewer-v13-repairability policy and six exact rubric keys. Section schemas and
  word budgets remain section-specific. This does not claim every auxiliary LLM
  prompt or existing stored manuscript has been rewritten.

## Saved manuscript replay

Command: `.venv/bin/python /private/tmp/v3-ownership-replay-20260907.py`

Input: `/private/tmp/v3-boundary-replay-20260907/resveratrol-reviewed-v12`.
Receipt: `/private/tmp/v3-ownership-20260907/receipt.json`.

```text
QEI rows: 19 before -> 16 after
Made 2017 prior-study quotation containing 5.83: present -> absent
Montoya-Estrada quotation attributing results to Abdollahi et al.: present -> absent
PMID 27005658: A1/direct -> D1/protocol
PMID 23736827: A1/direct -> B2/indirect
PMID 28054939: A1/direct -> A1/direct (positive control)
Authorized revision receipt regeneration: 37 receipts; source identities unchanged
Final copied payload table: both demonstrated attribution errors absent
Payload idempotence: passed
Original frozen evidence files: unchanged
Submitted: false
```

The old snapshot's classifications are deliberately not silently edited. Corrected
receipts are generated separately through the normal authorized revision builder.
A full revised manuscript still needs regeneration/validation and normal Core review.

## Verification

Focused tests: 731 passed in 17.85s, covering results tables, taxonomy, revision
authorization, final payload preparation, section calls, review/fallback/repair and LOC.

```text
make quality
Complexity: 222 existing findings; 0 new/worsened
jscpd: exit 0, no new clones
Ruff: All checks passed!
Revision/LOC tests: 278 passed in 1.02s
Targeted coverage: 83% (not full-repository coverage)
mypy agent scripts: Success: no issues found in 178 source files
git diff --check: exit 0
CodeGraph sync: Already up to date (canonical V3 path)
Production raw LOC change: 0
Effective LOC: agent 25,267/25,269; scripts 40,231/40,231
```

An earlier concurrent full suite reported 4663 passed and three LOC failures.
The ceiling was not raised: duplicated setup and verbose historical docstrings
were simplified. The current LOC and quality checks above pass. Final full-suite
rerun on the final source tree:

```text
.venv/bin/python -m pytest -q tests -m 'not gold_smoke and not full_matrix' --randomly-seed=907
4667 passed, 2 xpassed, 16 warnings in 146.15s
```

The excluded markers are the existing CI selection, not new exclusions. The two
XPASS results and deprecation warnings remain visible. Another broad randomized
run exposed one intermittent pre-existing Results-cleanup test failure (synthetic
word0...word379 disappeared). Its file alone passed 141 tests; the final seeded run
passed too. Only diagnostic assertion output was added, not a production fix.
The cause of that intermittent failure remains unlocalized; a passing rerun does
not establish that it is fixed.

## Review passes

1. Source and call-path review: traced QEI construction from writer and submission,
   classifier entry through the normal receipt builder, and frozen-field authorization.
   Compared actual parsed source text with the saved reviewed manuscript. Semble
   discovery and canonical-tree CodeGraph caller/impact inspection were used.
2. Boundary review: checked final payload idempotence, source hash preservation,
   background/contradicted/missing-source negatives, valid null results and RCT
   positives, ambiguous multi-source authorization refusal, and shared active prompts.
   Fixed the complexity regression and a test import-path conflict found during checks.
   The second review also caught "published PE cohorts" escaping the narrower
   background marker: the original source sentence is now a rejecting regression
   case, with an independent own-result control preserving numeric formatting.

Existing unrelated quality-tooling and environment-isolation edits from the hooks
developer remain intact. No clean-tree, deployed or accepted claim is made here.

## Release verification - 2026-09-07

The earlier local-only limitation above describes the initial audit. The user then
authorized end-to-end integration. Reviewed V3 changes and the hooks developer's
explicit diagnostic-tooling handoff were committed together:
`d0c425cca7d00aedc43fc92dab02281911383d75`.

```text
git push origin HEAD:codex/019e9ce8/main
10a38832..d0c425cc
git ls-remote origin refs/heads/codex/019e9ce8/main
d0c425cca7d00aedc43fc92dab02281911383d75
Mac git status --porcelain: empty
VPS /opt and /root HEAD: d0c425cca7d00aedc43fc92dab02281911383d75
VPS /opt and /root dirty: empty
V3 dashboard service: active; HTTP 200
```

Deployment used exclusive `/run/research-agent-paper-prepare.lock` and clean
fast-forward merges, not resets. Before stopping the old revise invocation,
`py-spy dump` proved it was waiting in submission-decision discovery with no
writer child. The cancellation marker was cleared after deployment; its journal
was preserved. No timer schedules or Core services were changed.

Fresh verification on this commit:

```text
Local full CI-selection suite, seed 907: 4667 passed, 2 xpassed, 16 warnings
Local Ruff: All checks passed!
Local mypy: Success: no issues found in 178 source files
make quality: 278 passed; no new/worsened complexity or clone findings
GitHub CI Gate 34144560646: success
GitHub unit suite: 4529 passed, 38 skipped, 2 xpassed in 172.14s
VPS focused source/payload/policy/revision/LOC tests: 721 passed in 33.25s
CodeGraph: canonical tree, 340 files, 11593 nodes, 30680 edges, up to date
```

VPS test collection initially failed because the newly required pytest-randomly
dev dependency was absent. Installed the declared pytest-randomly 5.0.0 and
coverage 7.16.0, then reran successfully. No runtime dependencies were changed.

Actual VPS prompt-builder comparison fetched HTTP 200 from
`https://api.researka.org/contracts/current`: V3 version exactly matches
`reviewer-v13-repairability`, all six rubric keys match, and the writer-section,
final-review, patch-repair and revision-coverage paths consume the policy.

The VPS source replay initially found 173 AppleDouble `._` files introduced by
the earlier Mac transfer. Each had the AppleDouble signature and a real-file
counterpart. They were archived outside runs at
`/root/v3-transfer-metadata-20260907/resveratrol-reviewed-v12`; all 167 real files
retained identical SHA-256 hashes. Transfer metadata is not research evidence.
Future Mac archive transfers must suppress resource forks (`COPYFILE_DISABLE=1`).

The actual deployed-code replay then passed, with the same 19-to-16 table change,
37 identity-preserved regenerated receipts, corrected protocol/case-series roles,
unchanged real-RCT control, payload idempotence and frozen-source checks. Receipt:
`/tmp/v3-live-ownership-d0c425cc/receipt.json` on the VPS. This remains a copied
offline candidate, not a claim that the entire manuscript is ready or accepted.

Core's owner requeued the SAME stored submission
`5011371c-05c8-487e-a312-3cdcc625a7c6` through normal reassessment. V3 did not submit
a duplicate while editorial adjudication prohibited resubmission. Core reported
actual reviewer authentication failing with `refresh_token_reused`, requiring
user sign-in. Login-status text and API health do not establish model access.
The corrected manuscript still requires normal validation and permitted review;
publication recovery is not complete. Existing timer schedules remain enabled.

Discovery receipt for release work: three distinct Semble searches covered safe
deployment/locks, revision source and feedback selection, and submission
idempotency/duplicate tests. Canonical CodeGraph traced run_cycle, revision source
loading, synthesis and submission locks. Local AGENTS, PROJECT_STATE and active
plan instructions were read; the knowledge playbook/AAA protocol was consulted
earlier in the same task. No stale sibling graph was treated as authoritative.

Final direct decision receipt used the actual systemd EnvironmentFile, not the
repository's separate `.env` (an earlier ad-hoc probe using that file returned
403 and was not production evidence). The normal V3 decision reader then returned:

```text
submission_id: 5011371c-05c8-487e-a312-3cdcc625a7c6
error: null
status: failed; decision: null; reason_code: PROVIDER_ERROR
fault_domain: system; retryable: true; resubmission.allowed: false
publication_state: NOT_PUBLISHED; failure_stage: autonomous_review
last failure: 2026-09-07T20:51:13.628901+04:00
reason: panel_both_gpt_reviewers_failed:
        bad_request:codex_authentication_failed | bad_request:codex_authentication_failed
```

Fresh public feed: HTTP 200, paper-surface total 159, latest
`9be40a10-b14d-4e4a-afff-f058a818c80b`, NAD+ Cardiovascular Effects,
`2026-08-22T21:12:12.335726+04:00`. No new public paper is proven.
Core's owner is handling the sign-in in its existing task. V3 timers remain
enabled, but no manual duplicate or corrected resubmission was sent against
the explicit hold. This is a verified V3 release, not completed publication recovery.
