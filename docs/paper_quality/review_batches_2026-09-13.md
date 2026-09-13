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
