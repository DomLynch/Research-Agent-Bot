# Missing Literature Audit — Rapamycin Paper

**Status:** Provisional. Anchored on the AAA4 (3-receipt) public manuscript bundle and the post-rescue corpus expansion to 34 receipts described in `AGENTS.md`. Identifies key papers that should appear in the receipt set or background literature for a senior-PhD-grade rapamycin review.
**Generated:** 2026-05-09
**Purpose:** Provide the corpus expansion lane with a prioritised target list. Every paper named here has at least one specific role in the paper that the corpus currently cannot fill.

---

## Identifier verification policy

Each paper below is tagged with one of:

- **✓ in-bundle** — already cited in `bundles/synthesis-rapamycin-v06-AAA4-2026-05-04T15-50-14Z/paper.md` references; identifier confirmed.
- **⚠ probable** — identifier comes from common literature familiarity; verify via PubMed before render.
- **? unknown** — paper is named in field reviews but the identifier requires lookup; rely on author-year-journal until a verified ID is confirmed.

The pipeline must NOT regurgitate ⚠ or ? identifiers as authoritative until verified. The author-year-journal triple is sufficient for prose; the DOI/PMID is required for the references block.

---

## What the current corpus has

**Receipts (3):**
- Moel 2025 — PEARL trial, A1 RCT on cardiometabolic. PMC12074816. ✓
- Stanfield 2026 — RAPA-EX-01, A1 RCT on cardiometabolic + exercise. PMC13082878. ✓
- Kell 2026 — Observational cohort on immune mTOR. PMC12794675. ✓

**Background tokens (cited but not receipts):**
- Harrison 2009 (mouse ITP, *Nature*; DOI: 10.1038/nature08221). ✓
- Mannick 2014 (immune function in elderly, *Sci Transl Med*; DOI: 10.1126/scitranslmed.3009892; PMID: 25540326). ✓
- Lamming 2012 (referenced in prose; identifier not in references block). ⚠
- Kahan 2000 (transplant PK; PMID: 10963197). ✓
- Studenski 2011, Cruz-Jentoft 2019, Schulz 2010, ADA 2024, WHO 2000 — clinical thresholds; not rapamycin-specific. ✓

**The corpus is missing**, as a structural matter:
1. The dose-finding human evidence (Mannick 2018 PIE trial, Mannick 2021 RTB101 phase 3).
2. The independent-replication preclinical evidence (Anisimov, Komarova).
3. The dose-response preclinical evidence (Miller 2014, Strong 2020).
4. The transient/mid-life dosing evidence (Bitto 2016, Wilkinson 2012).
5. The genetic-complement evidence (Selman 2009).
6. The companion-animal evidence (Urfer 2017, Creevy 2022).
7. The integrative-framework anchors (López-Otín 2013/2023, Kennedy 2014).
8. The 2023–2026 systematic reviews (Lee et al. 2024, Mannick & Lamming 2023).

---

## Tier 1 — Must-have (gates AAA-CLIN cert; absence is desk-rejection grade)

These 8 papers cover the load-bearing claims a senior reviewer at *Aging Cell* or *Nature Aging* will check first. Without these, the paper cannot credibly engage the field.

### MH-1. Mannick et al., *Sci Transl Med* 2018 — PIE trial (RTB101 + everolimus)

- **Identifier:** DOI: 10.1126/scitranslmed.aaq1564 ⚠ (verify); PMID approximately 30021923 ⚠.
- **Why it matters.** This is the *load-bearing positive human RCT* for rapalog geroprotection. ~264 older adults, 16 weeks, primary endpoint reduction in respiratory-tract infection rate. Replicates Mannick 2014's vaccine-response framework with a clinical-incidence outcome.
- **Where it should appear in the paper.** As an A1 clinical RCT receipt under the immune-aging outcome class. Currently absent because the AAA4 corpus is cardiometabolic-only.
- **Effect on tensions.** Resolves the "Mannick framework has no current corpus support" gap in `field_framework_dossier.md`. Reframes the load-bearing tension from "PEARL null vs Stanfield mixed" to "cardiometabolic null vs immune-aging positive."
- **Without it.** The paper's "preclinical-clinical translation gap" framing is incomplete because it ignores the clinical evidence on the *correct endpoint*. Senior reviewer comment: "The authors review human cardiometabolic data and conclude translation is incomplete, but ignore Mannick 2018, the field's strongest positive RCT signal."

### MH-2. Lamming et al., *Science* 2012 — mTORC2 disruption / insulin resistance

- **Identifier:** DOI: 10.1126/science.1215135 ⚠; PMID: 22461613 ⚠. Verify.
- **Why it matters.** This paper *defines* the mTORC1-benefit / mTORC2-toxicity boundary that frames the entire field's intermittent-dosing strategy. The two-week threshold cited in the AAA4 paper's Discussion ("chronic rapamycin dosing beyond approximately 2 weeks disrupts mTORC2") originates here.
- **Where it should appear.** As a mechanistic background-literature receipt or an A2-tier mechanistic receipt. Currently referenced in prose but not in the references block — a citation hygiene failure.
- **Effect on tensions.** Provides the mechanistic prediction for Stanfield 2026's bidirectional HbA1c result. Without it, that result reads as ambiguous noise; with it, it reads as predicted by a well-established framework.
- **Without it.** The paper's mechanistic engagement is reviewer-reads-as-borrowed-shorthand. Senior reviewer comment: "The authors invoke a 2-week mTORC2 threshold without citing the canonical Lamming 2012 paper that established it."

### MH-3. Mannick & Lamming, *Nature Aging* 2023 — joint review

- **Identifier:** ? (verify; the gap-analysis doc references this URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC10330278/).
- **Why it matters.** This is the most recent senior-author joint review of the rapalog-aging field, written by the two leads whose frameworks dominate the literature. A senior reviewer will expect any 2026 review to engage with it directly. If the reviewer authors themselves are Mannick or Lamming (entirely plausible at *Nature Aging*), they will read for whether their own positions are accurately represented.
- **Where it should appear.** As background literature for the Introduction and Discussion. Likely also as a citation in the "Engagement with Established Frameworks" section.
- **Effect on tensions.** Provides the field's current consensus position on dose-regime translation. Our paper's tensions either align with this consensus (and we say so) or diverge (and we say why).
- **Without it.** The paper appears not to have read the 2023 field-state-of-play. Senior reviewer comment: "The authors do not engage Mannick & Lamming 2023, the most recent senior review of this exact question."

### MH-4. Miller et al., *Aging Cell* 2014 — rapamycin dose-response in mice

- **Identifier:** DOI: 10.1111/acel.12194 ⚠; PMID: 24341993 ⚠. Verify.
- **Why it matters.** This is the canonical preclinical dose-response paper, demonstrating that rapamycin's lifespan extension is dose-dependent (3 mg/kg → 14 mg/kg) and sex-dependent in heterogeneous-stock mice. Cited as the dose-finding anchor by Mannick, Lamming, Kennedy, and Kaeberlein.
- **Where it should appear.** As a preclinical mechanistic receipt under longevity outcome class. Provides the dose-response evidence Harrison 2009 alone does not.
- **Effect on tensions.** Grounds the human dose-translation question with quantitative preclinical scaffolding.
- **Without it.** The paper has Harrison 2009 as a single point estimate, not a dose-response curve. Senior reviewer comment: "What is the dose-response evidence for rapamycin in mice?"

### MH-5. López-Otín et al., *Cell* 2013 — Hallmarks of Aging

- **Identifier:** DOI: 10.1016/j.cell.2013.05.039 ⚠; PMID: 23746838 ⚠. Verify.
- **Why it matters.** This is the most-cited integrative framework paper in geroscience (>15,000 citations). Any 2026 rapamycin review that does not cite Hallmarks of Aging is structurally incomplete. The framework provides the biological mapping for the endpoint-sensitivity hypothesis (in `novel_framework_candidates.md`).
- **Where it should appear.** As background literature in the Introduction; as the integrative scaffold in Discussion's mechanism-to-clinic narrative.
- **Effect on tensions.** Reframes the cardiometabolic-vs-immune disagreement as "different hallmarks at different stages of pathway propagation," which is a more parsimonious explanation than "the trials disagree."
- **Without it.** The paper's "geroscience hypothesis" framing has no canonical citation. Senior reviewer comment: "The geroscience framework is invoked without citation to López-Otín 2013."

### MH-6. López-Otín et al., *Cell* 2023 — Hallmarks of Aging: Expanding Universe

- **Identifier:** ? (verify).
- **Why it matters.** Updates the 2013 framework with three additional hallmarks (compromised autophagy, dysbiosis, chronic inflammation). All three are mechanistically connected to mTOR. A 2026 review should cite the 2023 update, not just the 2013 original.
- **Where it should appear.** As background literature; replaces or accompanies MH-5 depending on writer's choice.
- **Effect on tensions.** Provides the strongest current mapping of mTOR-pathway intervention onto specific hallmarks.
- **Without it.** The paper is citing a 13-year-old framework when a 3-year-old update exists. Senior reviewer comment: "Why López-Otín 2013 and not 2023?"

### MH-7. Kennedy et al., *Cell* 2014 — Geroscience hypothesis

- **Identifier:** ? DOI for "Geroscience: linking aging to chronic disease, Cell 2014, 159(4):709-713" — verify.
- **Why it matters.** This is the canonical geroscience hypothesis paper. Provides the rationale for multi-domain composite endpoints (Framework 3 in `novel_framework_candidates.md`).
- **Where it should appear.** As background literature in Introduction; as a citation for the composite-endpoint trial-design recommendation.
- **Effect on tensions.** Provides the trial-design rationale for moving past single-domain trials.
- **Without it.** The paper's call for composite endpoints has no canonical anchor. Senior reviewer comment: "Where is Kennedy 2014?"

### MH-8. Lee et al., *Lancet Healthy Longevity* 2024 — systematic review of rapamycin/rapalogs in aging

- **Identifier:** ? (verify; the gap-analysis doc references the URL https://www.sciencedirect.com/science/article/pii/S2666756823002581 — this looks plausible for a *Lancet Healthy Longevity* paper but verify).
- **Why it matters.** This is the most recent systematic review of the same evidence base our paper is reviewing. Lee 2024 screened 18,400 articles, included 19 human studies. Our paper *must* engage with this — either as a competing review (we extend it, we re-adjudicate it) or as a complementary review (we add the trust-spine framework on top).
- **Where it should appear.** In Introduction (positioning), Methods (selection comparison), and Discussion (consensus / divergence with Lee).
- **Effect on tensions.** Identifies which of our tensions are field-consensus and which are our framework-level reinterpretation.
- **Without it.** The paper appears unaware of the most recent systematic review of its own topic. Senior reviewer comment: "How does this review differ from Lee 2024?"

---

## Tier 2 — Should-have (substantial gain in field engagement; absence is reviewer-flagged)

These 9 papers raise the paper from "credible review" to "definitive 2026 review." Their absence will not desk-reject the paper but will draw individual reviewer comments.

### SH-1. Mannick et al., 2021 — RTB101 phase 3 / PROTECTOR trial

- **Identifier:** ? — verify. RTB101 (an mTORC1-selective compound, not rapamycin per se) was tested in respiratory tract infection prevention in a multi-thousand-subject phase 3 by resTORbio.
- **Why it matters.** The phase 3 was *negative* on the primary endpoint, contradicting Mannick 2018's positive PIE result. This is a crucial negative result for the immune-aging-first narrative.
- **Where it should appear.** As an A1 clinical RCT receipt or as a background-literature negative result. The paper's tension matrix should include MH-1 (PIE positive) vs SH-1 (phase 3 negative) — a load-bearing internal disagreement within Mannick's own program.
- **Effect on tensions.** Adds a critical negative human signal that the paper currently does not engage. Strengthens the "translation is harder than mechanism predicts" argument.
- **Without it.** The paper's engagement with Mannick is incomplete and overly positive.

### SH-2. Bitto et al., *eLife* 2016 — transient rapamycin in middle-aged mice

- **Identifier:** DOI: 10.7554/eLife.16351 ⚠; PMID: 27549339 ⚠. Verify.
- **Why it matters.** Demonstrates that 3-month transient rapamycin in 20-month-old mice extends median lifespan by ~60% in females and ~35% in males — a *larger* effect than chronic dosing in younger mice. This is a load-bearing finding for the dose-regime framework.
- **Where it should appear.** As a preclinical mechanistic receipt; as a citation for the intermittent-vs-chronic dosing argument.
- **Effect on tensions.** Reframes the "chronic dosing necessary?" question. If transient mid-life dosing is *better* than chronic young-onset dosing, intermittent human dosing is the predicted strategy, not a compromise.
- **Without it.** The paper's intermittent-dosing argument cites only Mannick 2014's empirical use, not the preclinical evidence supporting it.

### SH-3. Wilkinson et al., *Aging Cell* 2012 — rapamycin slows aging in mice

- **Identifier:** DOI: 10.1111/j.1474-9726.2012.00832.x ⚠; PMID: 22587563 ⚠. Verify.
- **Why it matters.** Demonstrates rapamycin's effect on multiple aging-related phenotypes beyond lifespan: cancer incidence, cardiac function, cognitive performance, immune function. Provides the multi-hallmark preclinical evidence the López-Otín framework requires.
- **Where it should appear.** As a preclinical mechanistic receipt; as the strongest "rapamycin engages multiple hallmarks" citation.
- **Effect on tensions.** Strengthens the endpoint-sensitivity framework's prediction that rapamycin's effects are correlated across hallmarks.

### SH-4. Selman et al., *Science* 2009 — S6K1 KO extends lifespan

- **Identifier:** DOI: 10.1126/science.1177221 ⚠; PMID: 19797661 ⚠. Verify.
- **Why it matters.** Genetic complement to rapamycin; demonstrates that mTORC1-S6K1 axis modulation alone is sufficient for lifespan extension, with female-specific effect that parallels Harrison 2009's sex asymmetry.
- **Where it should appear.** As a mechanistic background-literature citation.
- **Effect on tensions.** Provides the mechanistic basis for the sex-stratification gap our paper identifies.

### SH-5. Anisimov et al., *Cell Cycle* 2011 — rapamycin in cancer-prone mice

- **Identifier:** ? — verify.
- **Why it matters.** Independent replication of rapamycin's lifespan effect outside the NIA ITP, in non-heterogeneous strains. Establishes external validity.
- **Where it should appear.** As a preclinical mechanistic receipt.
- **Effect on tensions.** Removes the "single-laboratory" critique of the preclinical case.

### SH-6. Komarova et al., *Aging* 2012 — rapamycin in p53+/- mice

- **Identifier:** ? — verify.
- **Why it matters.** Tests whether rapamycin's lifespan benefit operates through cancer prevention vs aging deceleration in cancer-prone mice. Addresses a mechanistic question the AAA4 paper does not currently engage.
- **Where it should appear.** As a preclinical mechanistic receipt; as a citation for the "what kind of geroprotection?" question.

### SH-7. Urfer et al., *Geroscience* 2017 — rapamycin in companion dogs

- **Identifier:** ? — verify.
- **Why it matters.** First randomized rapamycin trial in companion dogs; demonstrates short-term safety and cardiac function effects in a translationally informative model. Aligned with Kaeberlein's framework.
- **Where it should appear.** As an adjacent-clinical receipt under the cross-species translation outcome class.
- **Effect on tensions.** Provides the bridge between Harrison 2009 (mouse) and PEARL/RAPA-EX-01 (human) that the paper currently lacks.

### SH-8. Creevy et al., *Nature* 2022 — Dog Aging Project cohort design

- **Identifier:** ? — verify.
- **Why it matters.** Establishes the DAP cohort that will produce the next decade's most translationally informative rapamycin data. Even without outcome data, the cohort design is a citation anchor.
- **Where it should appear.** As background literature in Discussion's "next-generation evidence" paragraph.

### SH-9. Mannick et al., 2018 RTB101 detailed PIE-1 paper

- **Identifier:** ? — separate from MH-1's PIE 16-week paper. The PIE-1 specifically with RTB101 alone may be a separate publication; verify.
- **Why it matters.** mTORC1-selective compound testing the Lamming framework directly. If RTB101 produces the same or better immune signal than rapamycin without mTORC2 disruption, the framework is supported.

---

## Tier 3 — Optional (genuine field-completeness; absence is silent)

These 6 papers add depth on specific sub-topics. Their absence is unlikely to be flagged unless the reviewer has a specific sub-topic interest.

### O-1. Robida-Stubbs et al., *Cell Metab* 2012 — mTOR in C. elegans

- **Identifier:** ? — verify.
- **Why it matters.** Cross-species mTOR conservation in invertebrates. Strengthens the "pathway is conserved" claim but adds little to the specific human-translation question.

### O-2. Kapahi et al., *Nature* 2004 — early mTOR-aging Drosophila

- **Identifier:** ? — verify.
- **Why it matters.** Foundational invertebrate mTOR-aging paper. Optional unless the paper has a "field history" paragraph.

### O-3. Kraig et al., *Pilot Study* 2018 — rapamycin pilot in healthy older adults

- **Identifier:** ? — verify.
- **Why it matters.** A small pilot RCT; provides feasibility evidence rather than efficacy evidence.

### O-4. Singh et al., 2018 or similar — open-label rapamycin in older adults

- **Identifier:** ? — verify.
- **Why it matters.** Adds a small open-label cohort to the human evidence base.

### O-5. Strong et al., *Aging Cell* 2020 — encapsulated rapamycin formulation

- **Identifier:** ? — verify.
- **Why it matters.** Tests whether encapsulated formulation alters lifespan extension; relevant to formulation translation but not to the central efficacy question.

### O-6. Kennedy & Lamming, *Cell Metab* 2016 — mTOR signaling in aging review

- **Identifier:** ? — verify.
- **Why it matters.** Joint review pre-dating Mannick & Lamming 2023; useful for tracing field consensus evolution.

---

## Identifier verification triage

The corpus expansion lane should resolve identifier verification in the following order:

1. **MH-1, MH-2, MH-3, MH-8** (Mannick 2018, Lamming 2012, Mannick & Lamming 2023, Lee 2024) — load-bearing, hard requirement, verify first.
2. **MH-4, MH-5, MH-6, MH-7** (Miller 2014, López-Otín 2013, López-Otín 2023, Kennedy 2014) — load-bearing, framework anchors, verify second.
3. **SH-1 through SH-5** — substantial reviewer flag risk; verify before final paper render.
4. **SH-6 through SH-9, O-1 through O-6** — verify if corpus expansion permits; otherwise omit.

The verification step for each paper is a single PubMed lookup. Total estimated effort: ~30 minutes for the full Tier 1 + Tier 2 list, by an analyst with PubMed access.

---

## Corpus expansion strategy implications

The 34-receipt post-rescue corpus is roughly the right size for a senior-PhD-grade rapamycin review, but it must contain the right papers. A 34-receipt corpus that excludes Mannick 2018 (MH-1) and Lamming 2012 (MH-2) is *worse* than a 16-receipt corpus that includes them, because the larger receipt count creates the expectation of completeness.

The corpus expansion lane should therefore prioritise *coverage of the 8 Tier-1 papers* over *raw receipt count*. If the post-rescue 34 receipts include all 8 Tier-1 papers, the paper is structurally adequate; if they exclude any, the paper is structurally deficient regardless of receipt count.

**Recommendation for the corpus expansion lane (Codex-owned):**

1. Run a targeted retrieval pass against the 8 Tier-1 author-year-journal triples.
2. Verify each paper's identifier via PubMed direct lookup.
3. If any Tier-1 paper is in the candidate pool but failed qualification (per `receipt_funnel.json`), prioritise its qualification rescue over generic claim-binding improvements.
4. The Tier-1 list IS the "must-have" gate for AAA-CLIN cert in the next render; treat it as such.

---

## What this audit refuses to claim

- That the 8 Tier-1 papers will all qualify under the current pipeline. Some may have low claim density relative to the receipt-builder threshold; the rescue is to lower the threshold for known-canonical papers, not to invent claims.
- That this list is exhaustive. There are likely 5–10 additional rapamycin-aging papers from 2025–2026 that this audit has not surfaced; the Lee 2024 systematic review is the best place to cross-check.
- That the identifier verification I have flagged is sufficient. Every ⚠ and ? identifier requires a fresh PubMed lookup before final paper render.

---

## Falsifying conditions

This audit is wrong if:

1. **Any Tier-1 paper does not exist** — e.g., if "Mannick & Lamming 2023" does not exist as a joint *Nature Aging* review (the gap-analysis doc references a PMC ID, which suggests it does exist; verify). If wrong, that section of the audit collapses.
2. **The post-rescue corpus already includes all Tier-1 papers** — in which case the audit is redundant, but not harmful. Re-run after the next rapamycin synthesis to confirm.
3. **A more recent (2025–2026) systematic review supersedes Lee 2024** — in which case MH-8's identification is wrong but the principle (engage the most recent review) holds.

---

**Provisional flag:** All identifier verifications in this document are flagged. The author-year-journal triples are sufficient for prose drafting; the DOI/PMID/PMCID must be verified before the references block is rendered into the final paper.
