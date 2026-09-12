# Final source admission and post-repair accounting

Objective: explain actual admission and prevent repairs from removing sources,
classifications or totals unnoticed. Baseline deployed commit: 5ba52060.

Approaches considered: (1) another reviewer prompt/label-presence rule;
(2) final deterministic validation only; (3) contemporaneous admission records,
record-derived Methods/table restoration and validation at the outgoing boundary.
Selected (3): (1) misses structural defects; (2) cannot explain source selection.

Constraints: preserve frozen study facts, normal Core review, rejection/cap
safeguards and existing LOC/complexity ceilings. No topic-specific repair rule.
The new candidate assessment must equal the frozen included set; a different set
stops for scientific review rather than silently changing evidence.

Discovery: three Semble queries and CodeGraph were completed before first edit.
Their repeated checkpoint receipts are saved in the desktop repair package as
`discovery-receipts.json`. CodeGraph confirmed receipt construction, finalizer,
consistency audit and frozen-package submission dependencies.

Implemented: source_admission.json records rule, date, IDs and decisions from
actual filters. Revision preparation preserves an existing candidate assessment,
or assesses the saved full candidate corpus before switching to frozen sources.
Methods renders the full candidate assessment separately from retained-source
reassessment. Final Findings Map is restored after cleanup and independently
checked for rows, required classifications, source references and totals.
Protocols cannot acquire completed findings. The outgoing boundary recomputes
these checks and binds the reviewed package to source records and Methods.

First audit: the submitted manuscript fails the new exact accounting check;
regenerating its table from 19 frozen records passes. A fresh deterministic
assessment of the saved VPS corpus assessed 224 files: 107 outside active scope,
89 without admissible claims, five failing topic identity and four failing direct
source identity, leaving exactly the same 19. This is a newly dated assessment,
not reconstruction of unrecorded historical screening. No source was forced in.

Mutation coverage: three corpora (exercise, drug, preclinical), missing/duplicate
source, blank/wrong classification, wrong total/reference, protocol overclaim,
post-review paper/record/admission edits, missing ledger and changed selection.
Real numeric notation is rendered without changing values/signs; unsupported TeX
is preserved, not guessed. QEI explicitly states its selected-subset scope.

Remaining: full quality/suite, final runtime audit and exact outgoing scientific
review, release/CI/VPS parity, one normal current-parent resubmission and observed
Core/public outcome. Tests and deployment alone are not publication proof.
