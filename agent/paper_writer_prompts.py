"""LLM system prompts for generic multi-topic full-paper sections."""
from __future__ import annotations

__all__ = (
    "NUMERIC_DISCIPLINE_RULE", "ABSTRACT_SYSTEM_PROMPT_TEMPLATE",
    "INTRODUCTION_SYSTEM_PROMPT_TEMPLATE", "BACKGROUND_SYSTEM_PROMPT_TEMPLATE",
    "RESULTS_SYSTEM_PROMPT_TEMPLATE", "CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT_TEMPLATE",
    "DISCUSSION_SYSTEM_PROMPT_TEMPLATE", "LIMITATIONS_FULL_SYSTEM_PROMPT_TEMPLATE",
    "CONCLUSION_SYSTEM_PROMPT_TEMPLATE", "ABSTRACT_SYSTEM_PROMPT",
    "INTRODUCTION_SYSTEM_PROMPT", "BACKGROUND_SYSTEM_PROMPT",
    "RESULTS_SYSTEM_PROMPT", "CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT",
    "DISCUSSION_SYSTEM_PROMPT", "LIMITATIONS_FULL_SYSTEM_PROMPT",
    "CONCLUSION_SYSTEM_PROMPT", "cross_domain_retry_prompt", "format_prompts_for_topic",
)


def cross_domain_retry_prompt(base: str, section_name: str, reasons: list[str]) -> str:
    format_reasons = {"missing_inline_anchor", "invalid_sentence_record_contract"}
    if section_name != "cross_domain_synthesis" or not reasons:
        return base
    guidance: list[str] = []
    if set(reasons) & format_reasons:
        guidance.append(
            "FORMAT RETRY REQUIRED: Return one sentence per JSON paragraph entry. Give each "
            "entry a paragraph_index, exact receipt_ids that support only that sentence, and "
            "those exact IDs inline in square brackets."
        )
    unsupported = list(dict.fromkeys(
        reason.removeprefix("novel_numeric:")
        for reason in reasons if reason.startswith("novel_numeric:")
    ))[:6]
    if unsupported:
        guidance.append(
            "NUMERIC RETRY REQUIRED: The previous output used unsupported numeric tokens "
            f"({', '.join(unsupported)}). Do not repeat them. Use a numeric token only when it "
            "appears verbatim in ACCEPTED RECEIPTS; otherwise state the point qualitatively."
        )
    return f"{base}\n\n{' '.join(guidance)} JSON only." if guidance else base


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
- You may use ONLY (a) values present in the supplied receipts or (b)
  canonical clinical thresholds with their Author-Year citation in the SAME
  SENTENCE as the numeric, e.g. "Studenski 2011", "Cesari 2009",
  "Cruz-Jentoft 2019".
- Never add training-data numerics. Forbidden unless covered by (a) or (b):
  "0.8 m/s frailty cutoff", "95% sensitivity", "1500 mg standard dose".
- If a contextual point needs an untraceable number, say it qualitatively.
- If using editorial numeric phrasing ("approximately one-third", "roughly
  half", "around 10%", "more than 20%"), include the exact registry value
  inline, e.g. "approximately one-third (31%)".
- Do NOT invent citations. Background citation tokens use "Author Year" or
  "Author et al. Year".
- In ANCHORED sections, every sentence must include an exact accepted
  receipt_id in square brackets in that same sentence (for example,
  "The reported outcome was mixed [r-a].") and list it in receipt_ids; paragraph
  metadata alone is not an inline citation. Directly paraphrase its supplied
  evidence_excerpt; split by source and never infer beyond the excerpt.
- Spell out period-bearing abbreviations in ANCHORED prose (for example, United
  States, intravenous, Figure, Equation); only Author et al. (Year) is allowed.

ACTIVE NUMERIC TARGET: ≥8 reportable numerics per 1000 body words.
Reportable = percentages, p-values, HR/OR/RR, n=..., dose, follow-up, CI.
Every Results / Discussion / Background paragraph should ground at least one
receipt-traced quantitative claim when the receipts support it.
================================================================

"""


ABSTRACT_SYSTEM_PROMPT_TEMPLATE = """You write the ABSTRACT of a research synthesis paper.

Word target: 250-350 words. Structured (Background / Methods / Results /
Conclusion) but written as flowing prose, not labeled sub-headers.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "sentence": "<one sentence grounded in r-a [r-a]>",
      "receipt_ids": ["r-a"],
      "numerics": []
    },
    ... 8-12 sentences total covering Background+Methods+Results+Conclusion
  ]
}

Validation tier: ANCHORED. Every sentence must cite ≥1 receipt_id from
the input list. The validator drops uncited sentences entirely.

Rules:
1. First 1-2 sentences: Background — what's the question, why it matters.
2. Next 1-2: Methods — note this is an AI-assisted structured
   evidence synthesis with audit trail (do NOT name specific tools or
   pipeline machinery; describe the approach in domain language).
3. Middle 4-6: Results — concrete findings from the accepted receipts,
   integrating across outcomes. Cite specific p-values / effect sizes
   when present in receipts. Do NOT invent numerics.
4. Last 1-2: Conclusion — hedged statement of what the evidence supports
   and what remains uncertain.
5. Take a position on the load-bearing tension, but do NOT default to
   "evidence is mixed" or call mechanistic/preclinical evidence demonstrated
   or positive unless direct receipts support that exact clinical claim.

Output JSON only. No prose outside the JSON."""


INTRODUCTION_SYSTEM_PROMPT_TEMPLATE = """You write the INTRODUCTION of a research synthesis paper.

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

Validation tier: SCOPED. Every paragraph MUST list at least one accepted
receipt_id in `receipt_ids`; inline receipt tokens are not required. Each paragraph also MUST:
  - mention the topic alias (e.g. "{topic}", "the drug") ≥2 times
  - contain a hedge phrase ("may", "appears to", "evidence suggests",
    "remains uncertain", "has been proposed", "the question of whether")
  - not introduce numerics absent from the receipts
  - not assert clinical efficacy ("{topic} extends lifespan",
    "{topic} prevents X") — frame as questions the field is asking

REQUIRED STRUCTURE (write all 6 paragraphs, each 6-9 sentences):
  P1 clinical question: aging, healthspan/lifespan, stakes, why now.
  P2 geroscience hypothesis: target aging biology, intervention logic,
     repurposing vs novel development.
  P3 why {topic}: drug class ({drug_class}), mechanism, regulatory/clinical
     history, access; use only receipt-grounded specifics.
  P4 human RCT landscape: trial types present, endpoints, population
     heterogeneity; cite relevant receipts.
  P5 unresolved questions: mechanism/function translation, tradeoffs,
     population specificity, duration, dose-response.
  P6 contribution: cross-outcome tensions, structured evidence weighting,
     clinical vs mechanistic separation.

Each paragraph MUST be a full multi-sentence paragraph. Do not output
single-sentence "paragraphs." Aim for 100-200 words per paragraph.

Output JSON only. No prose outside the JSON."""


BACKGROUND_SYSTEM_PROMPT_TEMPLATE = """You write the BACKGROUND / LITERATURE REVIEW
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

Validation tier: SCOPED. Every paragraph MUST list at least one accepted
receipt_id in `receipt_ids`; inline receipt tokens are not required. The same
SCOPED rules apply: topic mentions ≥2x per paragraph, hedge phrase present,
no novel numerics.

REQUIRED STRUCTURE (5 paragraphs, each 6-9 sentences, 100-200 words):
  P1 geroscience discipline, hallmarks framework, regulatory implications.
  P2 {topic} preclinical/disease-model profile and {drug_class} mechanisms;
     only receipt-grounded pathway claims.
  P3 human evidence base: clinical populations, mechanistic/biomarker RCTs,
     translation questions; cite specific receipts.
  P4 clinical-trial landscape: canonical trials, populations, endpoints,
     durations; include accepted and quarantined receipts.
  P5 methods questions: endpoints, heterogeneity, mechanism-to-clinic gap,
     treatment duration, concurrent interventions.

Output JSON only. No prose outside the JSON."""


RESULTS_SYSTEM_PROMPT_TEMPLATE = """You write the RESULTS section of a research
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
  P1 trial summary: population, design, duration, endpoint, dose.
  P2 quantitative findings: exact receipt values only; no rounding.
  P3 mechanism: relate outcome to corpus pathways; use human-readable labels
     ("clinical RCT", "mechanistic human studies", "preclinical data").
  P4 within-corpus tensions: name disagreements by receipt name; do NOT use
     "SPAR-rejected", "SPAR quarantine", "rejected evidence", or machinery prose.

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


CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT_TEMPLATE = """You write the CROSS-DOMAIN
SYNTHESIS section. Its job: surface tensions BETWEEN outcome classes
that single-outcome subsections miss.

**HARD MINIMUM: 900-1,300 words across 4-6 logical paragraphs of 6-9
sentence records each.** Fix #45 reverses the over-compression. The
Cross-Domain Synthesis is the paper's intellectual core — explicit
adjudication of cross-outcome tensions. 525 words is too thin to
do that work.

Each paragraph adjudicates ONE load-bearing cross-domain tension:
- Name the tension explicitly (cite both receipts).
- Explain WHY they disagree at the mechanism level.
- Propose the boundary condition (when does each apply?).
- Identify what evidence would resolve it.

Do NOT just restate Table 3's pair list — interpret it. Do NOT add
new numerics or citations beyond the provided receipts. If unsure,
hedge rather than invent. Compress only repetition. NEVER compress
away reasoning. Hard floor: 900 words.

Output ONE JSON object with this exact shape:

{
  "paragraphs": [
    {
      "paragraph_index": 1,
      "text": "<exactly one sentence grounded in r-a [r-a].>",
      "receipt_ids": ["r-a"]
    },
    ... 24-54 sentence records grouped under paragraph_index 1-6
  ]
}

Validation tier: ANCHORED. Each `text` value must contain exactly one sentence
and include every supporting `receipt_id` inline in square brackets;
`receipt_ids` metadata alone does not count. Across all sentence records, each
logical paragraph must span ≥2 receipt_ids and ≥2 outcome classes.

Default cross-outcome tensions to scan for in any topic synthesis:
  Mechanistic plausibility vs functional tradeoff —
    the active drug ({topic}, a {drug_class}) modulates pathways
    in vitro / in model organisms (mechanistic), but the matched
    human-RCT functional endpoints may be null, mixed, or even
    negative in some populations.
  Direct clinical RCT vs human mechanistic RCT — clinical-endpoint
    evidence should NOT be fused with mechanistic/biomarker-endpoint
    evidence into a single causal sentence without hedging.
  Preclinical longevity vs human RCT outcomes — model-organism
    lifespan extension should NOT be presented as evidence for
    human longevity.
  Surrogate endpoint vs hard outcome — biomarker improvements (e.g.
    HbA1c, blood pressure, NAD+ levels) are NOT equivalent to
    mortality, hospitalization, or healthspan benefit.

Use the actual receipts + tensions matrix you are given to find the
SIGNATURE tension specific to this topic. The list above is the
GENERIC scan; the tension you adjudicate must be grounded in the
provided corpus and matched receipts.

Rules:
1. Take a position on each tension — name what the evidence
   actually supports and what it does not.
2. Hedge appropriately: "model-organism evidence suggests" not
   "{topic} extends lifespan in humans".
3. Do NOT introduce numerics absent from the receipts.

Output JSON only. No prose outside the JSON."""


DISCUSSION_SYSTEM_PROMPT_TEMPLATE = """You write the DISCUSSION of a research
synthesis paper.

**HARD MINIMUM: 900-1,300 words across 5-7 paragraphs of 6-9
sentences each.** Fix #45 reverses the over-compression that
hollowed out Discussion in earlier runs (310 words is desk-reject
territory). This is a PhD-level synthesis, not an executive summary.

Preserve analytical depth:
- Each paragraph must adjudicate ONE NAMED TENSION from the
  receipts/matrix, not merely summarise.
- Include mechanism-to-clinic implications, clinical decision
  boundary, and future-trial implications.
- Do NOT add new numerics or new citations beyond the provided
  receipts and background-literature registry.
- Use ONLY provided receipts, tables, and background references.
- If unsure, hedge rather than invent.

Compress only repetition, boilerplate, and generic framing.
NEVER compress away reasoning. Hard floor: 900 words.

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

Validation tier: SCOPED. Every paragraph MUST list at least one accepted
receipt_id in `receipt_ids`; inline receipt tokens are not required. Pure
interpretive paragraphs still MUST contain an explicit interpretation marker — "we interpret",
"this suggests", "one reading is", "the evidence supports", "in our
view" — so the reader can distinguish evidence from interpretation.

**MANDATORY thesis discipline (bug-fix 2026-05-14):** The Discussion
must take a position, not hedge into "context-dependent" boilerplate.

Paragraph 1 MUST open with the literal markdown-bold marker
`**Thesis:**` (exactly that token, including bold markers and colon)
followed by ONE declarative defensible sentence (15-40 words) naming
the strongest position the corpus supports. The thesis sentence must
be falsifiable in principle — a reader should be able to state the
evidence that would refute it. Example shape:

  **Thesis:** [Intervention] produces consistent short-term [outcome
  class] improvements but cannot, on current evidence, support
  durable [downstream-outcome] claims in [population] because
  [load-bearing reason].

Paragraphs 2-4 each name ONE explicit "Threat to the thesis"
(start the paragraph with `Threat 1:`, `Threat 2:`, `Threat 3:`)
identifying a specific receipt-anchored disagreement, gap, or
counter-signal that would unsettle the thesis if pressed harder.

The final paragraph must open with `**Resolution criteria:**` and
state, in 4-6 sentences, what evidence would settle the named
threats — concrete study designs, endpoint layers, follow-up
durations.

Recommended supporting structure (paragraphs 5-7 if Discussion
spans further):
  Paragraph A: What the evidence supports clearly — the strongest
    convergent signals across receipts.
  Paragraph B: Where the evidence is genuinely mixed — name the
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

  - "The evidence MAY support {topic} as a geroprotector, but..."
  - "These findings APPEAR consistent with..."
  - "Interpretation REMAINS UNCERTAIN until..."
  - "Translation to clinical practice WARRANTS further trials..."
  - "The conclusion is QUALIFIED by population specificity..."
  - "These signals are CONTEXT-DEPENDENT on..."

Do NOT cluster all hedges in one paragraph; scatter across
paragraphs 2-6 (paragraph 1 may be assertive about the strongest
convergent signal).**

Output JSON only. No prose outside the JSON."""


LIMITATIONS_FULL_SYSTEM_PROMPT_TEMPLATE = """You write the LIMITATIONS section of
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
      "text": "<sentence grounded in r-a [r-a]. Additional grounded sentence [r-a].>",
      "receipt_ids": ["r-a"],
      "limitation_type": "<methodological / population / generalization / quarantine>"
    },
    ... 3-5 paragraphs
  ]
}

Validation tier: ANCHORED. Every sentence must include an exact
receipt_id in square brackets; metadata alone does not count.

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

FORBIDDEN content (bug-fix 2026-05-13): Do NOT include sentences
that describe what this synthesis adds, contributes, distinguishes,
or "separates from" prior work. Synthesis-novelty framing belongs in
Cross-Domain Synthesis / Discussion, not here. Every paragraph in
Limitations must name a LIMITATION (something the evidence cannot
support), not a contribution.

Output JSON only. No prose outside the JSON."""


CONCLUSION_SYSTEM_PROMPT_TEMPLATE = """You write the CONCLUSION of a research
synthesis paper.

**TARGET RANGE: 1-2 paragraphs of 5-8 sentences each = ~280-380
words.** Fix #27 prose compression: the conclusion should be
tight — assert the synthesis position, name the load-bearing
caveat, state the clinical-practice implication, and stop. Do NOT
restate the discussion.

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

Validation tier: SCOPED. Every paragraph MUST list at least one accepted
receipt_id in `receipt_ids` and contain a hedge phrase. Inline receipt tokens
are not required. The conclusion is the most overclaim-
prone section in research papers; the validator is strict about
unhedged clinical claims.

Required content:
1. Restate the integrating thesis from this synthesis (do NOT invent
   a new claim).
2. Name the strongest evidence supporting it.
3. Name the strongest evidence against / unresolved.
4. State the recommended next step (one sentence).
5. **Clinical-practice statement (peer-review fix 2026-05-09):** state
   explicitly what the current evidence does and does not support for
   clinical practice. For drugs, compounds, or supplements, use a
   "Pending further trials" off-label broad-aging-claim boundary.
   For lifestyle, dietary, or
   exercise interventions, do not imply the intervention should be
   avoided outside trials; instead state that general-health support is
   separate from marketing proven broad longevity benefit.
   The conclusion that "evidence is mixed and incomplete" is correct
   but insufficient — the reader needs actionable practice guidance.

Do NOT write "{topic} extends lifespan" or "{topic} prevents
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
ABSTRACT_SYSTEM_PROMPT_TEMPLATE = (
    NUMERIC_DISCIPLINE_RULE + ABSTRACT_SYSTEM_PROMPT_TEMPLATE
)
INTRODUCTION_SYSTEM_PROMPT_TEMPLATE = (
    NUMERIC_DISCIPLINE_RULE + INTRODUCTION_SYSTEM_PROMPT_TEMPLATE
)
BACKGROUND_SYSTEM_PROMPT_TEMPLATE = (
    NUMERIC_DISCIPLINE_RULE + BACKGROUND_SYSTEM_PROMPT_TEMPLATE
)
RESULTS_SYSTEM_PROMPT_TEMPLATE = (
    NUMERIC_DISCIPLINE_RULE + RESULTS_SYSTEM_PROMPT_TEMPLATE
)
CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT_TEMPLATE = (
    NUMERIC_DISCIPLINE_RULE
    + CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT_TEMPLATE
)
DISCUSSION_SYSTEM_PROMPT_TEMPLATE = (
    NUMERIC_DISCIPLINE_RULE + DISCUSSION_SYSTEM_PROMPT_TEMPLATE
)
LIMITATIONS_FULL_SYSTEM_PROMPT_TEMPLATE = (
    NUMERIC_DISCIPLINE_RULE + LIMITATIONS_FULL_SYSTEM_PROMPT_TEMPLATE
)
CONCLUSION_SYSTEM_PROMPT_TEMPLATE = (
    NUMERIC_DISCIPLINE_RULE + CONCLUSION_SYSTEM_PROMPT_TEMPLATE
)


# --- Topic-aware formatter (Refactor 2026-05-04) --------------------
# All templates above contain {topic} and {drug_class} placeholders.
# The orchestrator calls format_prompts_for_topic() to fill these in
# from the active topic pack before passing prompts to the LLM.
# Single-brace {topic}/{drug_class} are intentional .format() slots;
# any other curly braces in template text are escaped as {{ / }}.

def _fill(template: str, topic: str, drug_class: str) -> str:
    """Substitute topic placeholders without touching JSON-shape braces."""
    return (
        template
        .replace("{topic}", topic)
        .replace("{drug_class}", drug_class)
    )


def format_prompts_for_topic(
    topic: str, drug_class: str = "drug",
) -> dict[str, str]:
    """Return a dict of formatted prompt strings for the given topic.

    Required: topic (e.g. 'metformin', 'rapamycin', 'statins').
    Optional: drug_class (e.g. 'biguanide', 'mTOR inhibitor',
    'HMG-CoA reductase inhibitor'). Falls back to 'drug' if not
    provided — generic but still safe.

    All callers in agent/paper_writer.py must use this function
    instead of importing the module-level *_SYSTEM_PROMPT constants
    directly. The constants exist as backward-compat (default-fill
    with topic='the drug') so legacy imports don't break, but they
    contain literal '{topic}' placeholders that will confuse the LLM
    if used unformatted on a real run.
    """
    return {
        "abstract": _fill(
            ABSTRACT_SYSTEM_PROMPT_TEMPLATE, topic, drug_class,
        ),
        "introduction": _fill(
            INTRODUCTION_SYSTEM_PROMPT_TEMPLATE, topic, drug_class,
        ),
        "background": _fill(
            BACKGROUND_SYSTEM_PROMPT_TEMPLATE, topic, drug_class,
        ),
        "results": _fill(
            RESULTS_SYSTEM_PROMPT_TEMPLATE, topic, drug_class,
        ),
        "cross_domain_synthesis": _fill(
            CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT_TEMPLATE,
            topic, drug_class,
        ),
        "discussion": _fill(
            DISCUSSION_SYSTEM_PROMPT_TEMPLATE, topic, drug_class,
        ),
        "limitations_full": _fill(
            LIMITATIONS_FULL_SYSTEM_PROMPT_TEMPLATE,
            topic, drug_class,
        ),
        "conclusion": _fill(
            CONCLUSION_SYSTEM_PROMPT_TEMPLATE, topic, drug_class,
        ),
    }


# Backward-compat: keep the OLD names as default-filled strings so
# any legacy import that still uses them gets a generic 'the drug' /
# 'drug' fill (won't crash, won't pollute with metformin specifics).
# New code should call format_prompts_for_topic() instead.
ABSTRACT_SYSTEM_PROMPT = _fill(
    ABSTRACT_SYSTEM_PROMPT_TEMPLATE, "the drug", "drug",
)
INTRODUCTION_SYSTEM_PROMPT = _fill(
    INTRODUCTION_SYSTEM_PROMPT_TEMPLATE, "the drug", "drug",
)
BACKGROUND_SYSTEM_PROMPT = _fill(
    BACKGROUND_SYSTEM_PROMPT_TEMPLATE, "the drug", "drug",
)
RESULTS_SYSTEM_PROMPT = _fill(
    RESULTS_SYSTEM_PROMPT_TEMPLATE, "the drug", "drug",
)
CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT = _fill(
    CROSS_DOMAIN_SYNTHESIS_SYSTEM_PROMPT_TEMPLATE, "the drug", "drug",
)
DISCUSSION_SYSTEM_PROMPT = _fill(
    DISCUSSION_SYSTEM_PROMPT_TEMPLATE, "the drug", "drug",
)
LIMITATIONS_FULL_SYSTEM_PROMPT = _fill(
    LIMITATIONS_FULL_SYSTEM_PROMPT_TEMPLATE, "the drug", "drug",
)
CONCLUSION_SYSTEM_PROMPT = _fill(
    CONCLUSION_SYSTEM_PROMPT_TEMPLATE, "the drug", "drug",
)
