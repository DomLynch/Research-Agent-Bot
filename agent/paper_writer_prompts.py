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
    "NUMERIC_DISCIPLINE_RULE",
    "ABSTRACT_SYSTEM_PROMPT",
    "INTRODUCTION_SYSTEM_PROMPT",
    "BACKGROUND_SYSTEM_PROMPT",
    "RESULTS_SYSTEM_PROMPT",
    "CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT",
    "DISCUSSION_SYSTEM_PROMPT",
    "LIMITATIONS_FULL_SYSTEM_PROMPT",
    "CONCLUSION_SYSTEM_PROMPT",
]


# Fix #17: shared hard rule prepended to EVERY section prompt below.
# The rule is the writer-side enforcement of Fix #16's external-context
# lane: numerics from world-knowledge / training data are forbidden
# unless they appear in the supplied receipts (corpus evidence) OR are
# canonical clinical thresholds with their citation in the SAME
# sentence (background context lane). The post-paper audit gates
# (Q2 strict + Stage-2 background-lit-unsourced) catch any violation;
# this prompt change reduces the violation rate at generation time so
# we don't waste cycles on regenerations.
NUMERIC_DISCIPLINE_RULE = """\
================================================================
HARD NUMERIC DISCIPLINE (load-bearing, ship-blocking if violated)
================================================================
- You may use ONLY two kinds of numerics:
  (a) Values that appear in the supplied receipts (corpus evidence
      — e.g. p-values, hazard ratios, percentages from the bound
      claims you are given).
  (b) Canonical clinical thresholds that come WITH their canonical
      Author-Year citation, used as background context — and ONLY
      when the citation token (e.g. "Studenski 2011", "Cesari 2009",
      "Cruz-Jentoft 2019") appears in the SAME SENTENCE as the
      numeric.
- You MUST NOT write a numeric from your training-data world
  knowledge without it being in (a) or (b). Examples of forbidden
  uses: "0.8 m/s frailty cutoff", "95% sensitivity", "1500 mg
  metformin standard dose" — none of these are admissible unless
  the corresponding number is in the provided receipts OR you cite
  the canonical source in the same sentence.
- If you want to make a contextual point that requires a number you
  cannot trace, describe it qualitatively without a number ("walk
  speed below clinical thresholds is associated with frailty" —
  fine; "walk speed below 0.7 m/s is associated with frailty" —
  forbidden without citation).
- Citation tokens for background context use the form "Author Year"
  or "Author et al. Year" (e.g. "Studenski 2011", "Cruz-Jentoft
  et al. 2019"). Do NOT invent citations.
================================================================

"""


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

**HARD MINIMUM: 6 paragraphs of 6-9 sentences each = ~1,800 words.**
This is the second-longest section after Results. The prior version
of this prompt under-produced (3 paragraphs of ~100 words each =
~300-500 words total). That output was rejected for being too thin.
Write the full 6 paragraphs — do NOT default to a concise summary.

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

REQUIRED STRUCTURE (write all 6 paragraphs, each 6-9 sentences):
  Paragraph 1: The clinical question — population aging,
    metabolic dysfunction, healthspan vs lifespan, the
    economic and human stakes of geroprotective intervention.
    Why this matters now.
  Paragraph 2: The geroscience hypothesis specifically — target
    aging biology rather than individual diseases. Why
    pharmacological intervention (vs lifestyle) might be needed.
    The repurposing-vs-novel-development trade-off.
  Paragraph 3: Why metformin specifically — its decades of
    glycemic-control safety data, its preclinical longevity
    profile in model organisms, the AMPK / mTORC1 / mitochondrial
    pathways implicated. Its accessibility (off-patent, cheap).
  Paragraph 4: What human RCT evidence exists — describe the
    landscape of trials (sarcopenia, frailty, cognition,
    cardiometabolic) including specific trials present in this
    synthesis. CITE relevant trial receipts. Note endpoint
    diversity and population heterogeneity.
  Paragraph 5: The unresolved questions — mechanistic plausibility
    vs functional translation, tradeoffs like blunted exercise
    adaptation, population specificity (who benefits, who doesn't),
    duration of treatment, dose-response.
  Paragraph 6: The contribution this synthesis makes — integrating
    across receipts to surface cross-outcome tensions, applying
    SPAR adjudication to filter weak evidence, distinguishing
    clinical from mechanistic endpoints.

Each paragraph MUST be a full multi-sentence paragraph. Do not output
single-sentence "paragraphs." Aim for 100-200 words per paragraph.

Output JSON only. No prose outside the JSON."""


BACKGROUND_SYSTEM_PROMPT = """You write the BACKGROUND / LITERATURE REVIEW
section of a research synthesis paper.

**HARD MINIMUM: 5 paragraphs of 6-9 sentences each = ~1,500 words.**
The prior version of this prompt under-produced (3 paragraphs ~100
words each). Write the full 5 paragraphs of substantive prose.

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

REQUIRED STRUCTURE (5 paragraphs, each 6-9 sentences, 100-200 words):
  Paragraph 1: Geroscience as a discipline — its history,
    rationale for target-aging-not-disease, the hallmarks-of-
    aging framework, and the regulatory implications. Cite
    review receipts.
  Paragraph 2: Metformin's preclinical longevity profile — animal
    models (C. elegans, mice), molecular mechanisms (AMPK
    activation, mTORC1 inhibition, mitochondrial complex I,
    ETC effects), and the cellular phenotypes consistent with
    delayed senescence.
  Paragraph 3: Metformin's human evidence base — observational
    diabetes cohorts suggesting reduced age-related morbidity,
    early-stage human mechanistic RCTs, and the translation
    questions they raise. Cite specific receipts.
  Paragraph 4: The clinical-trial landscape relevant to this
    synthesis — describe the canonical trials in 2-3 sentences
    each (their populations, primary endpoints, durations).
    Include both accepted and quarantined receipts.
  Paragraph 5: Open methodological questions — endpoint choice
    (functional vs surrogate vs molecular), population
    heterogeneity (diabetic vs non-diabetic, baseline frailty),
    the mechanism-to-clinic gap, treatment duration, and
    interactions with concurrent interventions like exercise.

Output JSON only. No prose outside the JSON."""


RESULTS_SYSTEM_PROMPT = """You write the RESULTS section of a research
synthesis paper. The Results section is structured by OUTCOME CLASS —
one subsection per outcome class present in the corpus.

**HARD MINIMUM: every outcome subsection MUST have at least 4
paragraphs of 5-8 sentences each (~600-900 words per subsection).**
The prior version of this prompt produced 1 paragraph per subsection
(~70 words each); that output was rejected. Write the full multi-
paragraph subsections this time.

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

REQUIRED PER-SUBSECTION STRUCTURE (4 paragraphs minimum):
  Paragraph 1 — Trial summary: describe the trial(s) anchoring
    this outcome class. Population, design, duration, primary
    endpoint, dose. Specific to the receipts cited.
  Paragraph 2 — Quantitative findings: effect sizes, p-values,
    confidence intervals, percentage changes from receipts —
    exactly as they appear, no rounding or paraphrasing.
  Paragraph 3 — Mechanistic context: how this outcome relates
    to the molecular pathways described in the corpus
    (mitochondrial respiration, AMPK, pyruvate metabolism,
    DNA repair, etc.). Distinguish A1_clinical_RCT vs
    A2_human_mechanistic vs C1_preclinical evidence.
  Paragraph 4 — Within-corpus tensions or quarantined receipts:
    if any accepted receipts disagree, name the disagreement.
    If MET-PREVENT (or any other canonical paper) was rejected
    by SPAR for THIS outcome class, discuss it explicitly:
    "MET-PREVENT reported a null walk-speed effect (0.001 m/s
    [95% CI -0.06 to 0.06], p=0.96); SPAR rejected the receipt
    on Domain Skeptic grounds of population over-generalization,
    so the finding is contested but is NOT silently omitted from
    this synthesis."

Rules:
1. Cite ≥1 receipt_id in EVERY paragraph; multiple receipts when
   the paragraph integrates evidence across them.
2. Report effect sizes, p-values, sample sizes EXACTLY as they
   appear in receipts. Do NOT round, paraphrase, or compute new
   numerics. Validator drops paragraphs with novel numerics.
3. Use explicit directness transitions: "Mechanistically,",
   "By contrast,", "In a clinical RCT,", "Preclinical data suggest,",
   "The mechanistic substrate underlying this functional finding,".
4. The quarantine paragraph is REQUIRED when a SPAR-rejected
   canonical receipt touches the outcome — it cannot be silently
   omitted. The synthesis must surface the contested evidence.

Output JSON only. No prose outside the JSON."""


CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT = """You write the CROSS-DOMAIN
SYNTHESIS section. Its job: surface tensions BETWEEN outcome classes
that single-outcome subsections miss.

**HARD MINIMUM: 4 paragraphs of 6-9 sentences each = ~1,000-1,400 words.**
Each paragraph addresses one cross-outcome tension. The prior version
under-produced (~250 words total) — write the full 4 paragraphs.

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

**HARD MINIMUM: 6 paragraphs of 6-9 sentences each = ~1,800-2,400 words.**
The prior version of this prompt produced 4 paragraphs averaging ~145
words each (583 words total). That output was rejected. Write the
full 6 paragraphs.

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

**HARD MINIMUM: 5 paragraphs of 4-7 sentences each = ~700-1,000 words.**
The prior version produced 4 short paragraphs (~300 words). Write
the full 5 paragraphs.

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

**HARD MINIMUM: 2 paragraphs of 5-8 sentences each = ~350-500 words.**
The prior version produced 1 paragraph (~160 words). Write 2 full
paragraphs.

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


# Fix #17: prepend NUMERIC_DISCIPLINE_RULE to every section system
# prompt. Done after definition so the constants exist when we
# rebind. The rule lives at the TOP of each prompt where the model's
# attention is strongest. Mutating the bound names is the smallest
# possible diff vs editing each individual prompt string in-place.
ABSTRACT_SYSTEM_PROMPT = NUMERIC_DISCIPLINE_RULE + ABSTRACT_SYSTEM_PROMPT
INTRODUCTION_SYSTEM_PROMPT = NUMERIC_DISCIPLINE_RULE + INTRODUCTION_SYSTEM_PROMPT
BACKGROUND_SYSTEM_PROMPT = NUMERIC_DISCIPLINE_RULE + BACKGROUND_SYSTEM_PROMPT
RESULTS_SYSTEM_PROMPT = NUMERIC_DISCIPLINE_RULE + RESULTS_SYSTEM_PROMPT
CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT = (
    NUMERIC_DISCIPLINE_RULE + CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT
)
DISCUSSION_SYSTEM_PROMPT = NUMERIC_DISCIPLINE_RULE + DISCUSSION_SYSTEM_PROMPT
LIMITATIONS_FULL_SYSTEM_PROMPT = (
    NUMERIC_DISCIPLINE_RULE + LIMITATIONS_FULL_SYSTEM_PROMPT
)
CONCLUSION_SYSTEM_PROMPT = NUMERIC_DISCIPLINE_RULE + CONCLUSION_SYSTEM_PROMPT
