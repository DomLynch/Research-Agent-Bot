# Claude Parallel Lane — Rapamycin Paper Quality Dossier

**Generated:** 2026-05-09
**Owner:** Claude (research/judge lane)
**Scope:** Docs only. Lives entirely under `docs/paper_quality/claude_parallel/`.
**Status:** Complete — 10 deliverables on disk plus this README.

---

## What this dossier is

This is the parallel research/judge work for the rapamycin WORLDCLASS sprint. Codex owns platform code, corpus qualification, synthesis runner, quant artifacts, deployment, and commits. Claude's lane is intellectual groundwork that the writer module will later convert into rendered paper sections.

**Hard rule for this lane:** Docs only. No edits to `agent/`, `scripts/`, `tests/`, `topic_packs/`, `docs/quality-reference/`, `runs/`, deployment files, or commits. Every deliverable is self-contained Markdown.

---

## Anchor artifacts

The dossier was written against:

- **AAA4 paper:** `bundles/synthesis-rapamycin-v06-AAA4-2026-05-04T15-50-14Z/paper.md` (3 receipts, 9,002 words, all cardiometabolic; the public-facing baseline manuscript).
- **AAA4 manifest:** same bundle, `manifest.json` (3 receipts, 18 high-confidence claims, 3 non-orthogonal tensions).
- **Gap analysis (Phase 1):** `docs/paper_quality/rapamycin_gap_analysis.md` (already on disk; identifies the 8 desk-rejection risks the dossier addresses).
- **Project AGENTS.md:** confirms the post-rescue corpus is now 34 receipts (up from 16 in PATHA10).
- **Vibe Coding Playbook v4:** loaded via `mcp__knowledge__get_playbook` for operating standards.

---

## The 10 deliverables

1. **[field_framework_dossier.md](field_framework_dossier.md)** — Eight named field frameworks (Mannick, Lamming, Kennedy, Kaeberlein, Harrison/ITP, Selman, Anisimov, López-Otín). For each: core thesis, anchor papers, what they would criticize in our paper, what our corpus supports/challenges, drop-in engagement language for the paper.

2. **[novel_framework_candidates.md](novel_framework_candidates.md)** — Five candidate organizing frameworks (Dose-Regime, mTORC1/mTORC2 Two-Drug, **Endpoint-Sensitivity**, Tissue-Context, Reserve-Capacity). For each: thesis, contradictions explained, falsifying experiment, weaknesses. Recommends Endpoint-Sensitivity as the load-bearing scaffold.

3. **[missing_literature_audit.md](missing_literature_audit.md)** — 23 papers identified as missing. 8 must-haves (Tier 1, gates AAA-CLIN), 9 should-haves (Tier 2), 6 optional (Tier 3). Each with verification flag (✓ / ⚠ / ?).

4. **[rob2_manual_pilot.md](rob2_manual_pilot.md)** — Manual application of Cochrane RoB 2 (RCTs), ROBINS-I (observational), SYRCLE (animal) across 6 studies × 5 domains. Identifies 14 source-text fields the extractor must capture; includes activation plan (~250 LOC) for `scripts/risk_of_bias.py`.

5. **[grade_manual_pilot.md](grade_manual_pilot.md)** — GRADE certainty per outcome group (lifespan, immune, cardiometabolic, cognition, physical function, skin/senescence, adverse effects). Most outcomes Very Low certainty. Includes activation plan (~360 LOC) for `scripts/grade_assessment.py`.

6. **[meta_analysis_feasibility.md](meta_analysis_feasibility.md)** — Pool-eligibility audit. Mouse lifespan plausibly poolable (supplement target). Vaccine response plausibly poolable post-corpus-expansion. RTI rate has load-bearing PIE-vs-PROTECTOR inconsistency that precludes naive pooling. 17 source-text fields needed; activation plan (~430 LOC) for meta-analysis tooling.

7. **[senior_reviewer_rejection_memo.md](senior_reviewer_rejection_memo.md)** — Adversarial top-10 objections from a skeptical *Aging Cell* / *Nature Aging* reviewer. Severity-ranked. For each: problem, fix, fix LOC. Verdict on AAA4 paper: reject with possibility of major revision.

8. **[template_language_audit.md](template_language_audit.md)** — 8 categories of AI-template phrases identified (bloated openers, empty hedges, buzz phrases, recursive restating, shopping-lists, vague conclusions, first-person plural overuse, loose connectives). Per-phrase rewrites; pipeline-actionable deny-list.

9. **[cross_paper_tension_atlas.md](cross_paper_tension_atlas.md)** — Top 10 internal tensions in the rapamycin literature, with papers, numeric conflict, plausible explanation, resolving experiment. Compressed into 4 meta-categories (endpoint-distance, replication-at-scale, population-and-timing, dose-regime) for the paper's Discussion.

10. **[publication_readiness_rubric.md](publication_readiness_rubric.md)** — Four publication tiers (bioRxiv / mid-tier / *Aging Cell* / *Nature Aging*) × 5 dimensions (corpus, methodology, framework engagement, novelty, prose). AAA4 scores Marginal–Fail at Tier 1, Fail at Tier 2–4. Post-expansion + full sprint reaches Pass at Tier 2 and Tier 3 (with major revision); Tier 4 is plausible with additional sprint.

---

## How the deliverables connect

The dossier is *internally coherent*: each deliverable references the others where dependencies exist.

```
field_framework_dossier ──┐
                          ├─► novel_framework_candidates ──► senior_reviewer_rejection_memo
missing_literature_audit ─┤                              │
                          │                              ▼
rob2_manual_pilot ────────┼─► grade_manual_pilot ──► publication_readiness_rubric
                          │
meta_analysis_feasibility ┤
                          │
cross_paper_tension_atlas ┤
                          │
template_language_audit ──┘
```

**Key shared concepts (defined once in the most relevant deliverable, referenced elsewhere):**

- **Endpoint-Sensitivity Framework** — defined in `novel_framework_candidates.md` Framework 3; referenced in `cross_paper_tension_atlas.md` (Tensions 1, 2, 3), `senior_reviewer_rejection_memo.md` (Objection 2 fix), `publication_readiness_rubric.md` (Tier 3 framework engagement).
- **Tier-1 papers (the 8 must-haves)** — defined in `missing_literature_audit.md`; referenced in `rob2_manual_pilot.md` (Mannick 2018 RoB), `grade_manual_pilot.md` (corpus-expansion conditional), `senior_reviewer_rejection_memo.md` (Objection 1 fix).
- **Source-text data fields** — defined cumulatively in `rob2_manual_pilot.md` (14 fields), `grade_manual_pilot.md` (6 requirements), `meta_analysis_feasibility.md` (17 fields). The extractor pipeline needs the union of these.
- **Provisional flag** — every deliverable carries one. The dossier is intellectual groundwork conditional on (a) the post-rescue 34-receipt corpus landing the Tier-1 papers and (b) activation of the source-text data extraction the deliverables call for.

---

## What the dossier does NOT do

Per the rules of the parallel lane:

- ❌ Does not edit platform code (`agent/`, `scripts/`).
- ❌ Does not edit corpus, manifests, quant_claims, topic_packs.
- ❌ Does not commit, push, or deploy.
- ❌ Does not run synthesis, audit, or render.
- ❌ Does not modify the AAA4 paper or any other rendered paper.

What it does instead:

- ✅ Drafts the *intellectual* contributions a senior-PhD review needs.
- ✅ Specifies *what* the writer module needs to render (frameworks, drop-in language, deny-list rewrites).
- ✅ Specifies *what* the extractor needs to capture (source-text fields).
- ✅ Specifies *what* the corpus expansion needs to land (Tier-1 papers).
- ✅ Provides activation plans (LOC-scoped) for the three module activations (RoB 2, GRADE, inferential bridge / meta-analysis).
- ✅ Provides a tier-rubric the next render can be scored against.

---

## Recommended adoption order

When Codex's corpus expansion lane completes and the writer module is ready to consume the dossier:

1. **First** — adopt `template_language_audit.md` deny-list. This is the lowest-risk surgical change; it improves prose quality without changing claims.
2. **Then** — adopt `field_framework_dossier.md` engagement section + `novel_framework_candidates.md` Endpoint-Sensitivity framework. This restructures the Discussion.
3. **Then** — apply `missing_literature_audit.md` Tier-1 verification before the next paper render. Validate every Tier-1 paper's identifier.
4. **Then** — run `rob2_manual_pilot.md` activation plan (or honest relabel) and `grade_manual_pilot.md` activation plan in parallel.
5. **Then** — run `cross_paper_tension_atlas.md` as the Discussion's organising structure (4 meta-categories).
6. **Then** — score the resulting render against `publication_readiness_rubric.md` and decide whether to ship to bioRxiv (if Tier 2 reached) or continue to Tier 3 sprint.
7. **Last** — read `senior_reviewer_rejection_memo.md` adversarially against the new render. Use the 10 objections as a stress-test.

The order is roughly: prose → framework → references → methodology → tensions → tier-scoring → adversarial review.

---

## Total dossier scope

- **10 deliverable Markdown files** + this README.
- **Approximately 28,000 words** of prose.
- **Zero platform code changes.**
- **Zero corpus changes.**
- **Zero commits.**

The dossier is itself a structured input to the next paper render. Every recommendation is implementable; every claim is hedged with provisional flags and falsifying conditions; every cross-reference is internally consistent.

---

## Provisional flags (consolidated)

The dossier's recommendations are conditional on:

1. The post-rescue 34-receipt corpus landing the 8 Tier-1 papers in `missing_literature_audit.md`. If any Tier-1 paper does not qualify under the current pipeline, the corresponding sections of the dossier must be re-checked.
2. Identifier verification for every ⚠ and ? citation. The author-year-journal triples are sufficient for prose drafting; DOI/PMID/PMCID must be PubMed-verified before final render.
3. Activation of the three module plans (RoB 2, GRADE, meta-analysis tooling). Without activation, the dossier's "post-expansion + full sprint" tier scoring drops by approximately one tier.
4. The Endpoint-Sensitivity framework being defensible against the field's existing frameworks. The dossier argues it is; the next render's Discussion must defend the framework against alternatives explicitly.

---

## When this dossier expires

Each deliverable carries a "Falsifying conditions" section that names the specific evidence that would invalidate it. The dossier as a whole expires when:

- A 2026 *Aging Cell* / *Nature Aging* review on rapamycin-aging is published that supersedes the framework analysis.
- The Endpoint-Sensitivity framework is empirically falsified.
- The corpus expansion fails to land the Tier-1 papers and an alternative scaffolding strategy is needed.

In any of these cases, the dossier should be re-run, not patched.

---

**End of README.** Read each deliverable as a self-contained document; the cross-references make them more useful but each can stand alone.
