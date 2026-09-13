# Bounded reviewer inputs — 2026-09-13

Goal: prevent ordinary papers from exceeding the primary review service's input
limit while preserving complete cited evidence and independent scientific review.
Live HPV failure: 2,922,330 characters > 1,048,576; fallback OpenRouter returned
402. Sentry event c24bc15203704a80a0d9759f8580ab30, production release 5ba52060,
matched the 08:47 Dubai journal. No manuscript or prompt is sent to Sentry.

Three approaches considered: truncate evidence (rejected: hides contradictions),
rely on a larger/funded backup (rejected as routine design), or send complete
relevant evidence in bounded batches (selected). No new dependency or model
routing change. One shared packet builder; existing reviewers retain ownership.

Prose review groups statements by cited sources, preserves original source
indexes, validates citation-to-source identity and retains every cited source's
full verified sections/tables. Uncited author statements get actual author
records and the complete source catalogue; catalogue labels cannot substantiate
uncited scientific effects. Every original statement receives exactly one result.
A late invalid batch returns no partial approval. Review policy changes invalidate
old prose approvals; frozen source/context hashes remain unchanged.

The final reviewer sees the complete manuscript in each source packet. All
packets must finish; source order is joined by citation identity, never position.
Patch findings are combined, with stable distinct IDs and duplicate elimination.
Conservative cost preflight includes all packets and output-token allowances.
Optional low-patch escalation remains for single-packet legacy calls only;
multi-packet findings are never replaced by an escalation over one packet.
Technical fallback routing is unchanged; a valid negative review is not fallback.

The revision checker reviews every source batch and ANDs each required correction
across all results. Any malformed response or failed call leaves asks unresolved.
The complete paper and source catalogue are present in every packet. Exact
repeated outgoing body/section/evidence-span text is referenced to its identical
copy only; differing outgoing text is retained. This projection never changes
the actual submission payload or its fingerprint. Every payload source must be
represented in the frozen evidence records before batching.

Every request is preflighted at 300,000 characters including its system prompt,
with ample transport headroom. An indivisible oversized source/request is an
explicit local error before any provider call; it is never silently truncated or
sent to a paid fallback just to bypass the input limit. Sequential batches can
increase total review time; no concurrency framework or queue was added.

Discovery: three Semble queries plus CodeGraph before edits; CodeGraph refreshed
and found all new helper/caller edges after edits. Literal caller inventory and
ast-grep confirmed three bounded packet entry points. Knowledge registry lacked
V3; local AGENTS/PROJECT_STATE/active plan/DESIGN/failure contract were used.

Verification: source-index reversal, complete source coverage, oversized late
item before network, late invalid/negative outcomes, preservation of full paper,
identity mismatch, and exact-only outgoing text references. Existing source,
writer, fallback, revision and submission tests pass. Full local suite: 5,286
passed, 2 xpassed, 16 existing warnings. make quality: 347 passed, unchanged LOC,
complexity and duplication ceilings. Mypy: all 183 agent/script source files clean.
Runtime files were hashed before/after checks to detect concurrent mutation.

Real saved-input replay (post-failure artifact, not the original transport log):
- HPV prose: 32 statements, 13 cited sources; 2.90M chars -> 5 packets,
  maximum 293,042; total 1,086,437.
- Metformin prose: 35 statements, 20 cited sources; 1.51M -> 5 packets,
  maximum 299,091; total 1,436,932.
- HPV final review: all 50 sources; 5 packets, maximum 298,317.
- HPV revision check: all 50 sources; 20 packets, maximum 290,239. Complete-paper
  repetition increases total input; this is a remaining latency/cost tradeoff.

Second audit: inspected source matching, batch result aggregation, failure paths,
cache binding and standalone imports separately from implementation. It found
that bare helper imports relied on pytest's scripts path; package-qualified
runtime imports and a fresh-interpreter regression now cover that seam. An
external peer review was unavailable because that task was status-only; no
independent PASS is claimed.

Live primary canary passed: Terra reviewed the largest HPV prose packet (293,042
characters, three statements) in 10.7 seconds, returning all three assessments.
OpenRouter was not used. This was an isolated diagnostic, not paper approval.
Receipt: V3-Universal-Repair-2026-09-12/primary-review-canary.json.

Release/CI/deployment and normal current-parent resubmission remain to verify.
A technically successful reviewer call or HTTP 200 is not publication proof.

## Follow-up: writer packets — 2026-09-13

The 11:28 Metformin failure was before abstract completion: writer receipt-list
inputs bypassed cited-source selection, attaching all 53 receipts plus duplicated
author records to every statement. It was not one 300k study. Reproduced without
provider calls from that run's manifest and author_records.json.

Writer packets now select complete receipts by receipt_id, reject unknown or
duplicate cited IDs, and retain the legacy index-list transport contract. Shared
author records use exact-equality path references within author_context; original
records are unchanged. Expanding the transport restores the entire author record
exactly (256,973 serialized characters -> 133,709). Complete cited results,
contradictions and classifications are never truncated. The prompt explains the
references; its policy hash invalidates old prose approvals. All batch results
remain required, with negative results retained and technical fallback unchanged.

Offline failed-run replay: 53 source statements, four packets, largest 211,614
characters. This uses source thesis statements as a coverage probe; the failed
writer's discarded paragraphs were not available. Live complete HPV review:
five batches, 32 assessments, five unsupported, primary Terra only, 73.76 seconds.
This verifies complete review execution, not scientific approval or publication.

Audit: three materially different Semble searches and CodeGraph caller/impact
inspection before edits (repeated after a checkpoint hook overlooked the first
receipt). ast-grep confirmed writer and manuscript entry points. No disputed
call edge or cross-agent handoff required Tree-sitter/Repomix. Sentry tools were
unavailable; production journals provided the incident receipt. No clean Sentry
claim is made. Checked source identity, legacy API behavior, approval binding,
late failure, exact-record restoration, and 100 randomized key-order roundtrips.
A bounded mutation restoring whole-corpus packets fails both new writer tests.
The full-suite first pass exposed legacy list transport and prompt-contract
regressions; both were corrected and are rerun before release. Existing LOC and
quality ceilings are unchanged; final-review metadata aliases were removed and
its prompt consolidated without changing the smart-gate contract.

Remaining boundary: a genuinely indivisible cited record or shared author record
that exceeds 300k after lossless deduplication still fails closed locally. This
patch fixes the observed corpus-repetition defect; it does not silently fragment
scientific context or guarantee arbitrary-size manuscripts can be reviewed.

Live writer-path review also completed: all four batches, 53 assessments, three
unsupported, primary Terra only, 89.30 seconds. Neither diagnostic submitted a paper.

Follow-up release checks: 5,291 passed, 2 xpassed, 16 existing warnings in 153.06s;
make quality passed with 347 checks; mypy passed all 183 runtime files. The second
review preserved the legacy index-list API and exact smart-gate instructions.
Both complete live reviewer checks passed technically and retained negative
scientific findings. Deployment and normal publishing remain separately gated.
# Follow-up: complete manuscript and project CI

The Metformin full writer completed, then its consistency preparation failed
before a provider call. The exact manuscript has 35 review statements. A cited
comparison repeated 406 admission IDs as both dictionary keys and record fields.
The transport now represents such maps as keyed record lists and references exact
repeated records over 256 characters. Decoding restores every original value;
the 300,000-character cap and scientific acceptance policy remain unchanged.
The same 35 statements now form seven packets, maximum 299,906 characters.
This sizing receipt is not a scientific approval or publication receipt.

Audit: complete cited passages and decisions round-trip unchanged, including
mismatched IDs and 100 randomized orderings. Two cross-domain regression cases
retain a negative reviewer result. Full suite: 5,294 passed, 2 xpassed, 16 existing
warnings. Required quality gate: 347 passed, no new complexity or LOC findings.
Mypy: 183 source files clean. AST-grep confirms the four transport call sites.

V3 project CI now checks two Import Linter contracts: stage types cannot depend
on providers/orchestration, and source adapters cannot depend on writing/review.
Both direct and indirect imports are checked. Both contracts pass; deliberate
forbidden imports in isolated copies fail. These are focused static boundaries,
not a claim to inspect arbitrary dynamic imports or all architectural layers.

The diff-cover trial reuses the existing full test run under coverage, compares
against the actual PR base or preceding push SHA, and uploads XML/Markdown reports.
It has no coverage threshold and is report-only. A missing event base is explicitly
reported as unavailable. Neither tool is added to the per-turn quality hook.
Local publishing-change trial against `9a8a3f66`: seven changed executable lines,
seven covered (100%). This measures exercised lines, not assertion quality.

Reproduce: install `.[dev]`, run `make imports`; run the full suite under
`coverage run --branch --source=agent,scripts`, then `coverage xml` and
`make diff-cover DIFF_BASE=<reviewed-base-sha>`. CI runs these automatically.
Tool contracts follow [Import Linter](https://import-linter.readthedocs.io/en/v2.6/contract_types.html)
and [diff-cover](https://github.com/Bachmann1234/diff_cover).
