# Writer brief and section-contract audit

Scope: production `render_full_paper`, its eight LLM section briefs, builders,
length/rejection retries, structural backstop, and downstream surface restoration.
Baseline: `4281b5d661c7be2671e070cd9bb4987374ff4145`. No provider or publication-policy change.

## Section contracts

| Section | Draft target | Contract and audit outcome |
| --- | --- | --- |
| Abstract | 200-280 words, 8-10 sentences | Inline source IDs, mapped findings, bounded conclusion. Normal and source-exact retry now agree with the 300-word public ceiling. Writer retries excess; downstream restoration preserves excess for the gate instead of replacing findings with boilerplate. |
| Introduction | 1,000-1,200 words, 5 paragraphs | Question, rationale, actual study landscape, disagreement, contribution. Removed conflicting six-paragraph instruction and compulsory geroscience framing. |
| Background | 800-1,000 words, 4 paragraphs | Definitions, supported mechanisms, admitted studies, transfer limits. Removed conflicting five-paragraph instruction and instruction to include quarantined evidence. |
| Results | 400-600 words per outcome, 3 paragraphs | Separate calls per outcome. Actual designs/populations, exact effects and uncertainty, disagreements. Removed conflicting four-paragraph minimum and whole-paper target in each outcome call. |
| Cross-Domain Synthesis | 900-1,300 words, 4-6 groups | 24-54 one-sentence records, mapped IDs, at least two sources and outcome classes per group. Qualitative-only. Removed demand to invent a mechanistic explanation when excerpts cannot establish one. |
| Discussion | 900-1,300 words, 5-7 paragraphs | Thesis, three named threats, resolution criteria; distinguish interpretation from findings. Removed competing paragraph plans and numerical trial-design demands. |
| Limitations | 500-700 words, 4 groups | 16-20 one-sentence records, mapped IDs, qualitative-only. Do not assume RoB tables exist or cite one source as proof of a literature-wide absence. |
| Conclusion | 280-380 words, 1-2 paragraphs | Thesis, supporting finding, counterevidence, qualitative next step, evidence boundary. Explicit topic/hedge requirements; no invented clinical guidance, statistics or study designs. |

These are section targets, not a 380-word manuscript limit. Results expands with
outcome groups; Methods, evidence tables, references and appendices add length.
No new whole-paper word cap or additional model retry budget was introduced.

## Cross-cutting changes

- All eight briefs prohibit invented citations, numerics, methods, risk assessments,
  unsupported treatment advice, filler and instructions embedded in evidence.
- Numeric permission is tied to the cited receipts, not a value elsewhere in the
  corpus or an unsupported background Author-Year citation.
- Scoped validation now reports missing topic mentions, hedge and paragraph
  shape. Retry feedback includes those reasons rather than silently repeating.
- Late backstop prompts preserve one-sentence JSON records and paragraph groups;
  they no longer demand 8-12 sentences inside each record.
- The 80% external evidence threshold, source-matching logic and source-identity
  requirements are unchanged.

## Process findings not solved by this patch

- Research Question, Methods, QEI, framework and references are code-generated;
  a writer brief cannot fix their incorrect input labels or missing provenance.
- Today's BNT run recorded failed retrieval, no query/date and no RoB assessments.
  Its source-design/population errors precede drafting. Do not call these repaired.
- Abstract drafting precedes the deterministic question; sections primarily share
  the receipt packet/thesis, not the final repaired manuscript. Full-document
  coherence must still be checked after assembly.
- Short/missing-section and deterministic anchor fallbacks still exist. This patch
  removes the observed oversized-abstract overwrite, not the whole repair stack.
- Raw failed conclusion responses were not saved in the inspected run artifacts.
  Historical cause attribution remains limited; new rejection logs improve it.

## Verification and review

Three distinct Semble searches covered section instructions, builder validation
and retries; subsequent searches covered backstops and transport limits.
CodeGraph supplied non-authoritative callers/tests from the canonical old checkout
at `82219f21cd9449fd3561fffaa2e151036c0834c2`, not the release worktree at
`4281b5d661c7be2671e070cd9bb4987374ff4145`. Graph edges were discovery hints only,
not proof of current structure. All edited source was read and verified directly
in `/private/tmp/v3-evidence-repair-20260906`; it has no CodeGraph index. No index
was installed or modified. Semble located the new ceiling helper after edits.
Repository AGENTS, PROJECT_STATE, DESIGN-001 and V4 playbook were consulted.

Self-review covered all eight rendered prompts against actual builders, retry
schemas, source restrictions, word floors/ceiling and post-render behavior.

`python -m pytest -q tests/test_paper_writer.py tests/test_paper_writer_builders.py tests/test_paper_writer_backstop.py tests/test_run_v06_section_contract.py tests/test_journal_finalizer.py tests/test_loc_budget.py tests/test_topic_parameterization.py`

Initial result: 413 passed; 11 existing positional-maxsplit deprecation warnings.
`python -m ruff check agent scripts tests`: all checks passed.
`python -m mypy agent scripts`: success, 178 source files.

## Review follow-up

- Moved Hypothesis from optional diagnostics into `dev`, which CI installs with
  `pip install -e '.[dev]'`. The lifecycle test now imports it normally: missing
  installation fails rather than silently skipping. A fresh local `.venv` installed
  these declared dependencies successfully, including Hypothesis 6.167.1.
- Re-ran the command above plus `tests/test_revision_coverage.py` and
  `tests/test_codex_writer.py`: **708 passed, 11 warnings in 25.32s** on macOS.
  This includes the mandatory lifecycle test and all three timeout/cancellation
  cases. Ruff passed and the normal 178-file mypy command passed again.
- An additional, non-CI mypy invocation including `tests/test_revision_coverage.py`
  reports two bytes/str inference errors in unchanged `review_noise_control.py`
  lines 190 and 201. That broader type-check is not clean; no suppression added.
- Baseline [CI Gate 34022156312](https://github.com/DomLynch/Research-Agent-Bot/actions/runs/34022156312)
  on `4281b5d6` failed before this patch: **1 failed, 4396 passed, 39 skipped,
  2 xpassed**. `test_timeout_and_cancellation_reap_process[orphan-False]` failed
  because `os.kill(pid, 0)` did not raise `ProcessLookupError` immediately after
  cleanup. The transport sends SIGKILL to the process group and awaits the direct
  child; the fixture forks a grandchild whose parent exits. The log cannot
  distinguish a still-running orphan from a killed process awaiting reaping.
  Local passing tests do not resolve this Linux failure. No new CI run or full
  suite pass is claimed, and the process test was not weakened.

No live LLM generation, deployment, submission or publication is proven by these
offline checks. Next production validation must inspect an actual assembled paper,
not just a successful model request or section word count.
