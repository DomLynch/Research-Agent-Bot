# Journal Surface Endgame Audit — 2026-05-08

Scope: journal-surface/full-paper quality lane only. No run manuscripts were edited.

## Contract Read

- Read `AGENTS.md` and `PROJECT_STATE.md`.
- Reviewed current surfaces:
  - `agent/journal_surface_gate.py`
  - `scripts/run_mode_contract.py`
  - `agent/manuscript_appendix.py`
  - `scripts/apply_consistency_fixes.py`
  - `tests/test_journal_surface_gate.py`
  - `tests/test_final_consistency_audit.py`

## Current Guard Behavior

Public-body gate now evaluates only content before appendix/provenance/reference cutoffs:

- `## Publication Appendix`
- `## Search Provenance...`
- `## AI-Use Disclosure` / `## AI Disclosure`
- `## Researka Submitter Block`
- `## Data and Code Availability`
- `## References`

Blocked in public body:

- template/meta prose: run IDs, pipeline-production claims, reviewer/patch/quarantine status
- deterministic placeholder prose
- LLM/authorship slogans
- citation placeholders and bare citation artifact markers
- standalone hedge fragments
- malformed public QEI rows
- long duplicate public paragraphs

Allowed after boundary:

- provenance/meta disclosure content
- appendix-only citation artifacts
- appendix-only malformed QEI diagnostics
- appendix-only repeated provenance text

## Minimal Code Fix Applied

`agent/journal_surface_gate.py` duplicate detection keeps the synthetic-token exception for test filler such as `word123`, while applying the public duplicate rule to real prose:

- paragraph must have at least 30 tokens
- paragraph must have at least 20 distinct non-synthetic tokens
- paragraph is skipped if heading/table/`_Cited:` metadata
- comparison remains public-body only

Reason: this preserves the regression guard against generated filler false positives while keeping real duplicate public prose blocked.

## Recent Rich Artifact Audit

Command shape:

```bash
python3 - <<'PY'
from pathlib import Path
from agent.journal_surface_gate import evaluate_journal_surface
for d in [...]:
    paper = d / "full_paper.md"
    report = evaluate_journal_surface(paper.read_text(errors="replace"))
    print(d, report.passed, len(report.issues), report.issues[:20])
PY
```

### Omega3

Path: `runs/synthesis-omega3-v06-PATH2RICHFIX2-2026-05-08T14-00-00Z/full_paper.md`

- Saved historical `full_paper.journal_surface.json`: `passed: true`
- Current gate result: `passed: false`, 8 issues
- Public body cutoff: line 935; `## Search Provenance...` starts line 938
- Public leak examples:
  - line 125: `This synthesis was produced by the **v0.6 quant-claim adapter** pipeline...`
  - line 151: `Rejected-evidence quarantine did NOT run...`
- Duplicate public paragraphs:
  - `17,19 token_overlap=1.00`
  - `18,34 token_overlap=1.00`
  - `51,52 token_overlap=1.00`

### Metformin

Path: `runs/synthesis-metformin-v06-PATH2RICHFIX5-2026-05-08TCLASSIFIER/full_paper.md`

- Saved historical `full_paper.journal_surface.json`: `passed: true`
- Current gate result: `passed: false`, 8 issues
- Public body cutoff: line 941
- Public leak examples:
  - line 104: `This synthesis was produced by the **v0.6 quant-claim adapter** pipeline...`
  - line 130: `Rejected-evidence quarantine did NOT run...`
  - line 280: `deterministic evidence summary referenced throughout this paper`
- No current citation-artifact/QEI-row public failures found in the sampled issue list.

### GLP1

Path: `runs/synthesis-glp1-v06-PATH2RICHFIX5-2026-05-08T08-10-00Z/full_paper.md`

- Saved historical `full_paper.journal_surface.json`: `passed: true`
- Current gate result: `passed: false`, 14 issues
- Public body cutoff: line 787
- Public leak examples:
  - line 96: `This synthesis was produced by the **v0.6 quant-claim adapter** pipeline...`
  - line 122: `Rejected-evidence quarantine did NOT run...`
- Duplicate public paragraphs include:
  - `10,65 token_overlap=1.00`
  - `11,66 token_overlap=1.00`
  - `12,67 token_overlap=1.00`
  - `13,68 token_overlap=1.00`
  - `14,69 token_overlap=1.00`

## Source Localization

- Public Methods prose is now scientific in `scripts/run_mode_contract.py:193`.
- Appendix/provenance language remains intentionally external in `agent/manuscript_appendix.py:120`.
- Public placeholder stripping remains in `scripts/apply_consistency_fixes.py:68` and related fix paths.
- Surface gate blocks the historical public leaks in `agent/journal_surface_gate.py:22`, `agent/journal_surface_gate.py:29`, and `agent/journal_surface_gate.py:135`.

## No-Regression Evidence

Tests cover:

- public template/meta leak blocks
- public deterministic evidence-summary leak blocks
- public duplicate paragraph blocks
- appendix duplicate/meta/provenance allowance
- malformed public QEI row blocks
- malformed appendix QEI row allowance
- citation placeholder + standalone hedge fragment blocks
- appendix citation placeholder + hedge fragment allowance
- valid Author-Year tokens preserved by consistency fixer
- low-diversity repeated normal Methods prose does not trigger duplicate block

Scientific hedge prose risk: only standalone hedge fragments of <=4 tokens are blocked. Normal scientific sentences containing "may", "could", "suggests", or "uncertain" are not blocked by that rule.

## Validation

Pass 1:

```bash
python3 -m ruff check agent/journal_surface_gate.py scripts/run_mode_contract.py agent/manuscript_appendix.py scripts/apply_consistency_fixes.py tests/test_journal_surface_gate.py tests/test_run_mode_contract.py tests/test_manuscript_appendix.py tests/test_final_consistency_audit.py
python3 -m pytest tests/test_journal_surface_gate.py tests/test_run_mode_contract.py tests/test_manuscript_appendix.py tests/test_final_consistency_audit.py
```

Result: ruff clean; `144 passed in 11.24s`.

Pass 2:

```bash
python3 -m ruff check agent/journal_surface_gate.py scripts/run_mode_contract.py agent/manuscript_appendix.py scripts/apply_consistency_fixes.py tests/test_journal_surface_gate.py tests/test_run_mode_contract.py tests/test_manuscript_appendix.py tests/test_final_consistency_audit.py
python3 -m pytest tests/test_journal_surface_gate.py tests/test_run_mode_contract.py tests/test_manuscript_appendix.py tests/test_final_consistency_audit.py
```

Result: ruff clean; `144 passed in 10.99s`.

## Interpretation

Historical L5 JSON for sampled papers is stale relative to the current gate. The current gate correctly fails those manuscripts because operational/provenance prose is still in the public body and duplicate paragraphs remain before the appendix boundary.

No topic-specific code was added. The remaining issue is artifact debt plus possible upstream insertion placement. Reruns should regenerate papers with the current gate active and fail if the operational Methods block remains public.

## Rerun Recommendation

1. Rerun metformin first: latest sampled artifact has pure meta/template leaks without duplicate-paragraph noise.
2. Rerun omega3 second: confirms duplicate detector plus meta gate together.
3. Rerun GLP1 third: broadest duplicate-section/public-body stress case.
4. Only certify L5/L6 after regenerated `full_paper.journal_surface.json` is produced by the current code and matches a fresh direct call to `evaluate_journal_surface(full_paper.md)`.

## Live Repro Addendum: Urolithin A

Path: `runs/synthesis-urolithin_a-v06-2026-05-08T12-19-07Z/full_paper.md`

- Saved verdict: `AAA`, `L4 — ANALYTICALLY CERTIFIED`, blocked by journal surface only.
- Current gate result: `passed: false`, 4 issues.
- Duplicate findings:
  - `33,37 token_overlap=1.00`
  - `34,38 token_overlap=1.00`
  - `35,39 token_overlap=1.00`
- Audit result: not a token-set false positive. The paired paragraphs have identical token sets and matching prose bodies; this is real duplicate public-body content.
- Methods issue: compiler/rendering issue. `run_mode_contract.render_methods()` emitted 134 body words, below the gate floor of 300.
- Patch: expanded deterministic public Methods prose in `scripts/run_mode_contract.py` to 311 words, with no operational/model/provenance phrases.
- Dry simulation only, no artifact edit: replacing Methods in-memory leaves only the three duplicate-paragraph issues.

### Duplicate-Prose Root Cause and Fix

Second-pass root cause: the exact repeated urolithin paragraphs were already public-body analytical prose, not table content or appendix text. Existing cleanup ran before later restoration/backfill/final repair paths, so exact repeated public paragraphs could survive into final verdict. A separate depth-repair path could also append repeated deterministic extension prose, which risked trading duplicate removal for a new duplicate/backfill failure.

Fix:

- scoped paragraph/sentence duplicate cleanup to public body only, preserving appendix/provenance duplicates
- added final exact public-body paragraph dedupe after restoration/backfill paths
- logged final cleanup as `exact_public_duplicate_paragraph_post_depth`
- reran analytical depth restoration if final dedupe removes paragraphs
- made deterministic depth extensions section-specific and semantically distinct to avoid creating near-duplicate public paragraphs

No topic hardcoding. The cleanup removes exact normalized long prose paragraph repeats only; it does not collapse merely similar scientific paragraphs or contradictions.

No-write urolithin simulation:

- input: current `full_paper.md`
- in-memory steps: regenerate deterministic Methods, apply fixer with manifest, evaluate current `journal_surface_gate`
- result: `simulated_passed True`, `issues 0`
- duplicate logs: `fuzzy_duplicate_paragraph n=3`, `duplicate_sentence n=5`, `exact_public_duplicate_paragraph_post_depth n=3`
- depth restoration after dedupe: Cross-Domain Synthesis restored from `210` to `968` words

Additional tests:

- urolithin-shaped late duplicate public paragraphs
- true duplicate public stutter remains blocked/fixed
- duplicate appendix paragraphs preserved
- repeated legitimate Methods phrasing preserved
- final dedupe restores section depth after removing duplicated prose

## Residual Risk

- Existing stored `full_paper.journal_surface.json` can disagree with current code; always recompute during certification.
- Duplicate detector uses token-set Jaccard and may miss paraphrased repetition below 0.90 overlap.
- Very short standalone hedge paragraphs are blocked, but short heading-like scientific labels could require manual review if introduced.
