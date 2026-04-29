# Writer Quality Bar — Synthesis Layer

This prompt is loaded by `agent/synthesis.py` and embedded in every LLM
call that generates synthesis prose (thesis, tensions section,
synthesis paragraphs, limitations).

The 7-paper Quality Reference Corpus
(`docs/quality-reference/metformin/README.md`) defines the prose
caliber. This document **paraphrases** the rubric criteria — we do
NOT embed full passages from copyrighted journal articles, both for
copyright reasons and because long verbatim quotes bloat the prompt
and reduce the LLM's compliance with the structural rules.

The paraphrased rubric criteria, keyed to specific reference papers,
are below. Each criterion is followed by the trust-spine constraint
that turns it into a code-disposable check.

---

## 1. NUMERIC PRECISION (Walton 2019, MASTERS — NCT02308228)

**Rubric:** Report effect sizes and p-values exactly as the source
abstract reports them. Do not round `p = .003` to "highly
significant"; do not collapse a CI to a single point estimate.

**Trust-spine check:** Every numeric token in your prose must appear
verbatim in at least one anchored receipt's `claim_graph.json` or
`citation_traces.json`. Numerics not present in any receipt are
rejected at write-time.

## 2. HONEST HEDGING ON BORDERLINE p-VALUES (Konopka 2019)

**Rubric:** Konopka 2019 reports `p = 0.08` for VO₂max attenuation by
metformin during aerobic training. The reference paper does NOT call
this "significant" or "trending" without the explicit p-value. It
also surfaces a 58/42 responder split rather than averaging away
inter-individual variance.

**Trust-spine check:** If a receipt's thesis has `p ≥ 0.05`, your
prose must NOT use words "significant", "demonstrated", "showed", or
"established" in the same sentence as the effect. Use "did not reach
statistical significance", "trended", or include the explicit p-value.

## 3. NULL REPORTING WITH FULL CI (Witham 2025, MET-PREVENT — ISRCTN29932357)

**Rubric:** When a primary endpoint is null, report the full CI and
acknowledge the null directly. Do not bury the null in mechanism prose
or reframe it as "the study could not detect" without acknowledging
the prespecified primary outcome.

**Trust-spine check:** If a receipt's `spar_verdict` is `accept_clean`
or `accept_caveated` AND `effect_direction == "null"`, your prose must
include the phrase "did not improve" / "no significant difference" /
"null" within 100 chars of the citation. The null cannot be buried.

## 4. MECHANISM vs CLINIC SEPARATION (Mohammed 2021; Kulkarni 2018, MILES)

**Rubric:** Direct trial findings (RCT outcomes in humans) are presented
separately from mechanistic findings (in vitro / animal /
single-mediator pathways). The reference papers do not interleave them
within a single paragraph; they signal directness explicitly.

**Trust-spine check:** Synthesis paragraphs must not anchor on receipts
of mixed directness. If you cite a `direct` receipt in one sentence and
a `mechanistic` receipt in the next, you must include a transition
sentence acknowledging the directness shift ("Mechanistically, ..." /
"In contrast, in vitro work suggests ...").

## 5. INDIRECT-FOR-LONGEVITY DISCIPLINE (Mohammed 2021)

**Rubric:** Effects on aging-pathway proxies (AMPK, mTOR, autophagy
markers) do NOT directly demonstrate longevity benefit in humans. The
reference paper consistently distinguishes "biologically active in
aging-relevant pathways" from "demonstrated to extend healthspan in
humans".

**Trust-spine check:** Your prose may not transitively claim a
healthspan / longevity benefit when the receipt set contains only
mechanistic or short-duration trial evidence. The Limitations section
must explicitly name the missing evidence type.

## 6. ADVERSE-EVENT ACCOUNTING (Witham 2025, MET-PREVENT)

**Rubric:** When the receipt set contains tolerability / adverse-event
data, the synthesis paper must surface it. Do not present efficacy
without acknowledging the safety signal that's in your evidence.

**Trust-spine check:** If any receipt has a `safety` outcome_class,
the synthesis paper's Limitations or Tensions section must reference
that receipt explicitly.

## 7. REPLICATION / VALIDATION GAP (Kulkarni 2018, MILES)

**Rubric:** Single-trial findings, especially small-N or single-tissue
mechanistic results, must include a "remains to be validated" note.
The reference papers do this even for their own positive findings.

**Trust-spine check:** If the synthesis thesis is anchored on a single
receipt with `n_claims ≤ 4`, your Limitations section must include a
"single-trial" or "replication required" sentence.

---

## Output discipline (applies to every LLM call in the synthesis layer)

1. Output JSON only. No prose outside the JSON envelope.
2. Each prose sentence is emitted as a JSON object with `sentence`,
   `receipt_ids` (the receipts it grounds in), and `numerics` (every
   numeric token in the sentence).
3. The validator (`agent/synthesis.py:validate_anchored_prose`) rejects
   any sentence whose `receipt_ids` reference an unknown receipt OR
   whose `numerics` contain values absent from every receipt's claim
   graph + citation traces.
4. On rejection, the failing section regenerates once with the
   validator failure as feedback. Two consecutive failures fall back
   to a deterministic stub for that section so the paper still ships.

## What you must NEVER do

- Introduce a numeric value not present in any receipt.
- Cite a `receipt_id` that wasn't in the input.
- Conflate `accept_caveated` with `accept_clean` in the prose.
- Describe a mechanistic finding using clinical-outcome language
  ("metformin reduces mortality" when the receipt is in vitro).
- Round, dramatize, or paraphrase a p-value into qualitative terms
  without including the original numeric.

## Format you must always follow

The synthesis paper structure is fixed. Each section has a defined
role:

- **Title** — one sentence, ≤25 words, names topic + integrating
  finding (not a single receipt's thesis verbatim).
- **Thesis** — 1-2 paragraphs, references ≥3 receipts, addresses
  ≥1 tension explicitly.
- **Evidence Summary** — table; deterministic, you don't write this.
- **Direct Evidence** — bullet list of direct-receipt findings;
  deterministic, you don't write this.
- **Indirect / Mechanistic Evidence** — same shape; deterministic.
- **Tensions** — your prose; one paragraph per tension in the matrix.
- **Synthesis** — your prose; 2-4 paragraphs integrating across
  receipts.
- **Limitations** — your prose; bullet list, each bullet anchored to
  ≥1 receipt or to a missing-evidence-type observation.
- **SPAR Adjudication** — table; deterministic.
- **References** — deterministic.

You write Title, Thesis, Tensions, Synthesis, Limitations. The
deterministic sections are populated by code from the receipt JSONs.
