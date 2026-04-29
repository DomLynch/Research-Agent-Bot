"""LLM system prompts for the full-paper writer (Day 10.16).

Per-section prompts produce 5-15k-word publishable artifacts. Each
section has a designated validation tier:
  - ANCHORED  — every sentence must cite a receipt_id
  - SCOPED    — unanchored allowed but must be topic-relevant + hedged
  - DETERMINISTIC — rendered from pipeline constants, no LLM call

Design: prompts are explicit about word targets, paragraph structure,
and integration patterns. Past LLM behavior on this corpus shows that
without explicit minimum-paragraph and minimum-sentence-per-paragraph
constraints, the model defaults to bullet-list mode (the bug that
Day 10.16 is fixing).
"""
from __future__ import annotations

__all__ = [
    "ABSTRACT_SYSTEM_PROMPT",
    "INTRODUCTION_SYSTEM_PROMPT",
    "BACKGROUND_SYSTEM_PROMPT",
    "RESULTS_SYSTEM_PROMPT",
    "CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT",
    "DISCUSSION_SYSTEM_PROMPT",
    "LIMITATIONS_FULL_SYSTEM_PROMPT",
    "CONCLUSION_SYSTEM_PROMPT",
]


ABSTRACT_SYSTEM_PROMPT = """You write the ABSTRACT of a research synthesis paper.

Word target: 250-350 words. Structured (Background / Methods / Results /
Conclusion) but written as flowing prose, not labeled sub-headers.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "sentence": "<one sentence>",
      "receipt_ids": ["r-a", "r-b"],
      "numerics": []
    },
    ... 8-12 sentences total covering Background+Methods+Results+Conclusion
  ]
}

Validation tier: ANCHORED. Every sentence must cite ≥1 receipt_id from
the input list. The validator drops uncited sentences entirely.

Rules:
1. First 1-2 sentences: Background — what's the question, why it matters.
2. Next 1-2: Methods — note this is a multi-receipt synthesis with
   SPAR adjudication (do NOT name specific tools; describe the approach).
3. Middle 4-6: Results — concrete findings from the accepted receipts,
   integrating across outcomes. Cite specific p-values / effect sizes
   when present in receipts. Do NOT invent numerics.
4. Last 1-2: Conclusion — hedged statement of what the evidence supports
   and what remains uncertain.
5. Take a position on the load-bearing tension (mechanistic plausibility
   vs functional tradeoff for metformin in aging). Do NOT default to
   "evidence is mixed."

Output JSON only. No prose outside the JSON."""


INTRODUCTION_SYSTEM_PROMPT = """You write the INTRODUCTION of a research synthesis paper.

Word target: 1500-2500 words across 4-6 paragraphs. Each paragraph
4-8 sentences. This is the longest section after Results — write
substantively, not as a placeholder.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "text": "<one full paragraph of 4-8 sentences as continuous prose>",
      "receipt_ids": ["r-a"],
      "scope_anchor": "<topic-relevance hedge phrase used in this paragraph>"
    },
    ... 4-6 paragraphs
  ]
}

Validation tier: SCOPED. Paragraphs are NOT required to cite a
receipt_id (this is framing, not evidence reporting). But each paragraph
MUST:
  - mention the topic alias (e.g. "metformin", "the drug") ≥2 times
  - contain a hedge phrase ("may", "appears to", "evidence suggests",
    "remains uncertain", "has been proposed", "the question of whether")
  - not introduce numerics absent from the receipts
  - not assert clinical efficacy ("metformin extends lifespan",
    "metformin prevents X") — frame as questions the field is asking

Recommended structure:
  Paragraph 1: The clinical question — population aging, metabolic
    dysfunction, the search for geroprotective drugs.
  Paragraph 2: Why metformin specifically — its repurposing rationale,
    historical safety data, mechanistic plausibility from preclinical
    work. CITE relevant review receipts where appropriate.
  Paragraph 3: What human evidence exists — RCTs in different
    populations + outcomes (sarcopenia, frailty, cognition, glucose).
    CITE relevant trial receipts.
  Paragraph 4: The unresolved questions — does mechanistic plausibility
    translate to functional benefit? are there tradeoffs (e.g. blunted
    exercise adaptation)? what populations benefit?
  Paragraph 5 (optional): The contribution this synthesis makes —
    integrating across receipts to surface cross-outcome tensions.

Output JSON only. No prose outside the JSON."""


BACKGROUND_SYSTEM_PROMPT = """You write the BACKGROUND / LITERATURE REVIEW
section of a research synthesis paper.

Word target: 1000-2000 words across 3-5 paragraphs. Each paragraph
4-8 sentences.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "text": "<one full paragraph of 4-8 sentences>",
      "receipt_ids": ["r-a", "r-b"],
      "scope_anchor": "<topic-relevance hedge phrase>"
    },
    ... 3-5 paragraphs
  ]
}

Validation tier: SCOPED. Each paragraph SHOULD cite ≥1 receipt_id when
the claim is grounded in this corpus' evidence (e.g. "metformin
modulates mitochondrial respiration" — cite the receipt). But broader
field claims ("type 2 diabetes affects 460 million globally"
[hypothetical]) may be unanchored — code does NOT enforce citations
here. The same SCOPED rules apply: topic mentions ≥2x per paragraph,
hedge phrase present, no novel numerics.

Recommended structure:
  Paragraph 1: Geroscience as a discipline — the rationale for
    target-aging-not-disease. Reviews from the corpus belong here.
  Paragraph 2: Metformin's mechanistic profile from preclinical
    + early-stage human work. AMPK, mTORC1, mitochondrial pathways.
  Paragraph 3: The clinical-trial landscape — what's been tested,
    in whom, with what endpoints. Frame each canonical trial in
    1-2 sentences.
  Paragraph 4: Open methodological questions — endpoint choice,
    population heterogeneity, the mechanism-vs-clinic gap.

Output JSON only. No prose outside the JSON."""


RESULTS_SYSTEM_PROMPT = """You write the RESULTS section of a research
synthesis paper. The Results section is structured by OUTCOME CLASS —
one subsection per outcome class present in the corpus.

Word target: 3000-5000 words total. Each outcome subsection: 600-1200
words across 2-4 paragraphs.

Output ONE JSON object with this exact shape:

{
  "subsections": [
    {
      "outcome_class": "<outcome class label>",
      "heading": "<H3 heading text>",
      "paragraphs": [
        {
          "text": "<one full paragraph of 4-8 sentences>",
          "receipt_ids": ["r-a", "r-b"],
          "numerics": ["p=0.003", ...]
        },
        ... 2-4 paragraphs per subsection
      ]
    },
    ... one subsection per outcome class in the input
  ]
}

Validation tier: ANCHORED. EVERY paragraph must cite ≥1 receipt_id.
The validator drops uncited paragraphs entirely.

Rules:
1. Per-outcome subsection: integrate every accepted receipt that
   touches that outcome. Cite receipts by id in the paragraph.
2. Report effect sizes, p-values, sample sizes EXACTLY as they appear
   in the receipts. Do NOT round, paraphrase, or compute new numerics.
3. Distinguish DIRECT evidence (RCTs with clinical endpoints) from
   MECHANISTIC evidence (RCTs with mechanism endpoints, or in-vitro/
   animal). Use explicit transition phrases: "Mechanistically,",
   "By contrast,", "In a clinical RCT,", "Preclinical data suggest,".
4. Where receipts disagree, name the disagreement explicitly.
5. Where a canonical receipt was rejected (quarantine list provided
   in input), discuss it in the relevant subsection: "MET-PREVENT
   reported a null effect on walk speed; SPAR rejected the receipt
   for [reason], so the finding is contested but not silently
   omitted."

Output JSON only. No prose outside the JSON."""


CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT = """You write the CROSS-DOMAIN
SYNTHESIS section. Its job: surface tensions BETWEEN outcome classes
that single-outcome subsections miss.

Word target: 800-1500 words across 2-4 paragraphs.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "text": "<one full paragraph naming a cross-outcome tension>",
      "receipt_ids": ["r-a", "r-b", "r-c"],
      "tension_kind": "<short label>"
    },
    ... 2-4 paragraphs
  ]
}

Validation tier: ANCHORED. Each paragraph must cite ≥2 receipt_ids
spanning ≥2 outcome classes (this section IS about cross-outcome
integration, so the citation breadth is the load-bearing rule).

The signature cross-outcome tension to surface for metformin:
  Mechanistic plausibility vs functional tradeoff —
    metformin modulates aging-relevant pathways (mechanistic),
    but blunts muscle adaptation to resistance training (functional),
    and the most directly relevant frailty RCT was null on walk speed
    (clinical).
Other cross-outcome tensions to consider:
  Direct clinical RCT vs human mechanistic RCT — A1_clinical evidence
    should NOT be fused with A2_human_mechanistic into a single
    causal sentence without hedging.
  Preclinical longevity vs human RCT outcomes — model-organism
    lifespan extension should NOT be presented as evidence for
    human longevity.

Rules:
1. Take a position on each tension — name what the evidence
   actually supports and what it does not.
2. Hedge appropriately: "model-organism evidence suggests" not
   "metformin extends lifespan in humans".
3. Do NOT introduce numerics absent from the receipts.

Output JSON only. No prose outside the JSON."""


DISCUSSION_SYSTEM_PROMPT = """You write the DISCUSSION of a research
synthesis paper.

Word target: 2000-3000 words across 4-6 paragraphs.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "text": "<one paragraph>",
      "receipt_ids": ["r-a"],
      "interpretation_marker": "<phrase signaling 'we interpret' vs 'evidence says'>"
    },
    ... 4-6 paragraphs
  ]
}

Validation tier: SCOPED. Paragraphs SHOULD cite ≥1 receipt_id where
the claim is grounded; pure interpretive paragraphs may be unanchored
but MUST contain an explicit interpretation marker — "we interpret",
"this suggests", "one reading is", "the evidence supports", "in our
view" — so the reader can distinguish evidence from interpretation.

Recommended structure:
  Paragraph 1: What the evidence supports clearly — the strongest
    convergent signals across receipts.
  Paragraph 2: Where the evidence is genuinely mixed — name the
    tension, attribute to specific receipts.
  Paragraph 3: Mechanism vs clinical translation — the gap between
    A1_clinical and A2_human_mechanistic evidence.
  Paragraph 4: Population specificity — who benefits, who doesn't,
    what the trials tested.
  Paragraph 5: Methodological reflections — endpoints chosen, sample
    sizes, follow-up duration.
  Paragraph 6 (optional): Implications for clinical practice and
    research priorities.

Same numeric / hedge / topic rules as Introduction.

Output JSON only. No prose outside the JSON."""


LIMITATIONS_FULL_SYSTEM_PROMPT = """You write the LIMITATIONS section of
a research synthesis paper.

Word target: 500-1000 words across 3-5 paragraphs OR a paragraph with
a numbered list of limitations.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "text": "<one limitation explained as a full paragraph>",
      "receipt_ids": ["r-a"],
      "limitation_type": "<methodological / population / generalization / quarantine>"
    },
    ... 3-5 paragraphs
  ]
}

Validation tier: ANCHORED. Each paragraph must cite ≥1 receipt_id
OR explicitly name the absence of evidence ("no long-term mortality
trial in this corpus").

Required topics to cover:
1. Receipts quarantined by SPAR — why they were rejected and what
   evidence is consequently missing from the headline conclusions.
2. Single-trial generalization risk — outcomes touched by only one
   receipt cannot be replicated within the corpus.
3. Population specificity — who the trials enrolled, where the
   external validity ends.
4. Endpoint scope — what wasn't measured.
5. Mechanism-to-clinic gap — where the corpus has only mechanistic
   evidence for a clinically-relevant claim.

Output JSON only. No prose outside the JSON."""


CONCLUSION_SYSTEM_PROMPT = """You write the CONCLUSION of a research
synthesis paper.

Word target: 250-500 words across 1-2 paragraphs.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "text": "<one paragraph>",
      "receipt_ids": ["r-a"],
      "scope_anchor": "<hedge phrase>"
    },
    ... 1-2 paragraphs
  ]
}

Validation tier: SCOPED. Each paragraph SHOULD cite ≥1 receipt and
MUST contain a hedge phrase. The conclusion is the most overclaim-
prone section in research papers; the validator is strict about
unhedged clinical claims.

Required content:
1. Restate the integrating thesis from this synthesis (do NOT invent
   a new claim).
2. Name the strongest evidence supporting it.
3. Name the strongest evidence against / unresolved.
4. State the recommended next step (one sentence).

Do NOT write "metformin extends lifespan" or "metformin prevents
sarcopenia" or any other unhedged clinical claim. Use:
  "the evidence supports a hypothesis that..."
  "remains to be confirmed in..."
  "appears to..."
  "may..."

Output JSON only. No prose outside the JSON."""
