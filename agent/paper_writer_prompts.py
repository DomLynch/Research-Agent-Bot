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
2. Next 1-2: Methods — note this is a structured corpus synthesis
   (do NOT name specific tools or pipeline machinery; describe the
   approach in domain language).
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

**TARGET RANGE: 4-5 paragraphs of 5-8 sentences each = ~1,000-1,400
words.** Fix #27 prose compression: tables now carry the structured
evidence; prose should be lean and argument-driven, not exhaustive.
Do NOT pad with restated literature; cite once and move on. The
prior version over-produced (~1,800-2,500 words); aim closer to
1,200 words.

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
    across the corpus to surface cross-outcome tensions, applying
    structured evidence weighting to distinguish strong from weak
    findings, separating clinical from mechanistic endpoints.

Each paragraph MUST be a full multi-sentence paragraph. Do not output
single-sentence "paragraphs." Aim for 100-200 words per paragraph.

Output JSON only. No prose outside the JSON."""


BACKGROUND_SYSTEM_PROMPT = """You write the BACKGROUND / LITERATURE REVIEW
section of a research synthesis paper.

**TARGET RANGE: 3-4 paragraphs of 5-8 sentences each = ~800-1,100
words.** Fix #27 prose compression: Tables 1-5 carry the structured
evidence map; the Background section should set up the topic
landscape lean, not catalogue every prior review. Cite once per
claim and rely on Tables for breadth.

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

**TARGET RANGE: every outcome subsection has 2-3 paragraphs of 5-7
sentences each (~400-600 words per subsection).** Fix #27 prose
compression: Table 2 (Per-Study Endpoint Evidence) carries every
study × p-value tuple, so the prose can REFERENCE the table rather
than restate every numeric. Aim for ~1,500 total words across
subsections, not 3,000.

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
    DNA repair, etc.). Distinguish clinical-RCT, mechanistic-RCT,
    and preclinical evidence using HUMAN-READABLE labels (e.g. "in
    the clinical RCT", "in mechanistic human studies", "preclinical
    data suggest...") — do NOT use internal labels like
    `A1_clinical_RCT` or `C1_preclinical` verbatim.
  Paragraph 4 — Within-corpus tensions: if any accepted receipts
    disagree, name the disagreement using receipt names directly
    (e.g. "Walton 2019 reports negative muscle-function effects;
    Vujović 2026 reviews mechanistic effects that would predict
    benefit"). Do NOT use pipeline-internal terminology like
    "SPAR-rejected", "SPAR quarantine", "rejected evidence" —
    those phrases describe machinery the v0.6 quant-claim adapter
    does NOT run.

Rules:
1. Cite ≥1 receipt_id in EVERY paragraph; multiple receipts when
   the paragraph integrates evidence across them.
2. Report effect sizes, p-values, sample sizes EXACTLY as they
   appear in receipts. Do NOT round, paraphrase, or compute new
   numerics. Validator drops paragraphs with novel numerics.
3. Use explicit directness transitions: "Mechanistically,",
   "By contrast,", "In a clinical RCT,", "Preclinical data suggest,",
   "The mechanistic substrate underlying this functional finding,".
4. NEVER mention "SPAR", "quarantine", "rejected by", or any other
   pipeline-internal term in prose. The corpus is presented as
   curated evidence; tensions are surfaced through standard
   academic discussion of disagreement.

Output JSON only. No prose outside the JSON."""


CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT = """You write the CROSS-DOMAIN
SYNTHESIS section. Its job: surface tensions BETWEEN outcome classes
that single-outcome subsections miss.

**TARGET RANGE: 3 paragraphs of 5-7 sentences each = ~600-800 words.**
Fix #27 prose compression: Table 3 (Cross-Domain Tensions) lists
every non-orthogonal pair with severity + practical implication.
Reference the table; do NOT restate the full pair list. Each
paragraph picks the SINGLE most load-bearing tension in its scope
and interprets it.

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
  Direct clinical RCT vs human mechanistic RCT — clinical-endpoint
    evidence should NOT be fused with mechanistic/biomarker-endpoint
    evidence into a single causal sentence without hedging.
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

**TARGET RANGE: 4-5 paragraphs of 5-8 sentences each = ~1,100-1,400
words.** Fix #27 prose compression: Tables 1-5 + the deterministic
What-This-Adds section now carry the structured evidence and the
originality claim. The Discussion's job is INTERPRETATION over
that evidence — not restating it. Lean prose, dense with hedges
(see Q10 requirement below).

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
    direct clinical-endpoint RCTs and human mechanistic/biomarker
    RCTs.
  Paragraph 4: Population specificity — who benefits, who doesn't,
    what the trials tested.
  Paragraph 5: Methodological reflections — endpoints chosen, sample
    sizes, follow-up duration.
  Paragraph 6 (optional): Implications for clinical practice and
    research priorities.

Same numeric / hedge / topic rules as Introduction.

**HARD HEDGE-DENSITY REQUIREMENT (Q10 audit gate, ≥4 distinct
phrases): the Discussion section as a whole MUST contain at least
4 of the following hedge phrases (each at least once):

  may, might, suggests, appears, consistent with, uncertain,
  warrants, remains to be, preliminary, qualified, limited,
  cautious, context-dependent, interpretive

Distribute them across paragraphs so the prose reads as honest
synthesis, not flat assertion. The audit COUNTS the unique
phrases that appear in the rendered Discussion section — under-
hedging trips a P2 fail. Examples of correct integration:

  - "The evidence MAY support metformin as a geroprotector, but..."
  - "These findings APPEAR consistent with..."
  - "Interpretation REMAINS UNCERTAIN until..."
  - "Translation to clinical practice WARRANTS further trials..."
  - "The conclusion is QUALIFIED by population specificity..."
  - "These signals are CONTEXT-DEPENDENT on..."

Do NOT cluster all hedges in one paragraph; scatter across
paragraphs 2-6 (paragraph 1 may be assertive about the strongest
convergent signal).**

Output JSON only. No prose outside the JSON."""


LIMITATIONS_FULL_SYSTEM_PROMPT = """You write the LIMITATIONS section of
a research synthesis paper.

**TARGET RANGE: 3-4 paragraphs of 4-6 sentences each = ~500-700
words.** Fix #27 prose compression: Table 4's per-domain RoB +
Overall RoB + Weight columns surface design-level limitations
already; the Limitations section's job is to add the
synthesis-level limitations the table cannot encode (e.g. corpus
scope, missing populations, methodology choices).

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
1. Corpus scope — which canonical trials or evidence types were
   NOT represented in the curated corpus (e.g. long-term mortality
   RCTs in non-diabetic adults), and what gaps that creates in the
   headline conclusions. Use plain academic phrasing — do NOT
   mention "SPAR", "quarantine", "rejected", or other pipeline-
   internal machinery (the v0.6 quant-claim adapter does not run
   any rejection layer).
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

**TARGET RANGE: 1-2 paragraphs of 5-8 sentences each = ~250-350
words.** Fix #27 prose compression: the conclusion should be
tight — assert the synthesis position, name the load-bearing
caveat, and stop. Do NOT restate the discussion.

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
