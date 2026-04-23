import re

import pytest

from agent.drafter import RapidEvidenceDrafter


class BundleContractProvider:
    prompt_version = "bundle-contract/v1"
    model = "mimo-v2-pro"

    def complete_json(self, *, system_prompt: str, user_prompt: str):
        return (
            {
                "question": "What are the effects of the intervention on aging-related outcomes in older adults, compared with usual care or placebo, and what does the retained human evidence imply about efficacy, safety, and remaining uncertainty?",
                "search_summary": "Direct trials, supporting human studies, reviews, and protocols were retained under the bundle contract.",
                "landscape": "The evidence is separated into direct aging evidence, disease-context human evidence, broader support, and protocol/mechanistic context.",
                "findings": "Tier A1 direct evidence provides the main answer, while lower tiers provide support and future-trial context.",
                "limitations": "Evidence remains partly indirect and uneven across endpoints.",
                "gaps_identified": "Larger and longer-duration trials remain needed.",
                "conclusion": "The retained evidence should be read as a tiered pyramid rather than a flat source list.",
            },
            {},
        )


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:120]


def _assert_bundle_contract(artifact: dict, *, allowed_terms: list[str], banned_terms: list[str]) -> None:
    bundle = artifact["source_bundle"]
    assert len(bundle) <= 12
    titles = [_norm_title(str(item.get("title", ""))) for item in bundle]
    assert len(titles) == len(set(titles))
    for item in bundle:
        title = str(item.get("title", "")).lower()
        excerpt = str(item.get("excerpt", "")).lower()
        hay = f"{title} {excerpt}"
        assert not any(term in title for term in banned_terms)
        if item.get("evidence_tier") != "Tier C protocol/mechanistic support":
            assert any(term in hay for term in allowed_terms), item["title"]
    tiers = [str(item.get("evidence_tier") or "") for item in bundle]
    assert 1 <= tiers.count("Tier A1 direct aging evidence") <= 4
    assert 0 <= tiers.count("Tier A2 disease-context human evidence") <= 3
    assert 0 <= tiers.count("Tier B supporting human evidence") <= 3
    assert 0 <= tiers.count("Tier C protocol/mechanistic support") <= 2
    assert any(
        item.get("evidence_tier") == "Tier A1 direct aging evidence"
        and item.get("role") == "published_results"
        and item.get("directness") == "direct"
        for item in bundle
    )


@pytest.mark.parametrize(
    ("topic", "allowed_terms", "banned_terms", "evidence"),
    [
        (
            "metformin aging older adults",
            ["metformin", "glucophage"],
            ["remap trial for optimizing surgical outcomes at upmc"],
            [
                {"title": "Metformin for Preventing Frailty in High-risk Older Adults", "excerpt": "Older adults receiving metformin had frailty outcomes assessed over two years.", "evidence_type": "interventional", "source_type": "clinicaltrials", "has_results": True, "trial_status": "results", "year": 2024, "url": "https://clinicaltrials.gov/study/NCT02570672"},
                {"title": "Metformin and physical performance in older people with probable sarcopenia and physical prefrailty or frailty in England (MET-PREVENT): a double-blind, randomised, placebo-controlled trial.", "excerpt": "Metformin versus placebo in older adults with gait speed and physical performance outcomes.", "evidence_type": "primary", "source_type": "pubmed", "year": 2025, "url": "https://pubmed.ncbi.nlm.nih.gov/40147475/"},
                {"title": "Metformin Effect on Brain Function in Insulin Resistant Elderly People", "excerpt": "Metformin trial in insulin-resistant elderly people with brain-energy outcomes.", "evidence_type": "interventional", "source_type": "clinicaltrials", "has_results": True, "trial_status": "results", "year": 2023, "url": "https://clinicaltrials.gov/study/NCT03733132"},
                {"title": "APOE4-dependent association between metformin use and Alzheimer's disease-related cortical thickness in older adults with type 2 diabetes.", "excerpt": "Cross-sectional metformin study in older adults with diabetes and cortical thickness outcomes.", "evidence_type": "observational", "source_type": "europepmc", "year": 2026, "url": "https://europepmc.org/article/MED/41761644"},
                {"title": "Metformin administration improves adverse outcomes in older adult burn patients: a single-centre cohort study.", "excerpt": "Older adult burn cohort study with metformin exposure and hospital outcomes.", "evidence_type": "observational", "source_type": "pubmed", "year": 2025, "url": "https://pubmed.ncbi.nlm.nih.gov/40419490/"},
                {"title": "Evaluation of glucose-lowering medications in older people: a comprehensive systematic review and network meta-analysis of randomized controlled trials.", "excerpt": "A multi-drug review in older people that includes metformin among glucose-lowering interventions.", "evidence_type": "review", "source_type": "pubmed", "year": 2024, "url": "https://pubmed.ncbi.nlm.nih.gov/39137064/"},
                {"title": "Metformin for Longevity and Sarcopenia: A Therapeutic Paradox in Aging.", "excerpt": "A human metformin aging review on sarcopenia and longevity.", "evidence_type": "review", "source_type": "europepmc", "year": 2026, "url": "https://europepmc.org/article/MED/41751275"},
                {"title": "Metformin for Longevity and Sarcopenia: A Therapeutic Paradox in Aging", "excerpt": "Mirror full text of the same human metformin aging review.", "evidence_type": "review", "source_type": "europepmc", "year": 2026, "url": "https://europepmc.org/article/PMC/PMC12938515"},
                {"title": "Diet and Exercise Plus Metformin to Treat Frailty in Obese Seniors", "excerpt": "Registered protocol of metformin plus lifestyle intervention for frailty in obese seniors.", "evidence_type": "protocol", "source_type": "clinicaltrials", "has_results": False, "year": 2025, "url": "https://clinicaltrials.gov/study/NCT999001"},
                {"title": "A multimodal precision-prevention approach combining lifestyle intervention with metformin repurposing to prevent cognitive impairment and disability: the MET-FINGER randomised controlled trial protocol", "excerpt": "Metformin prevention protocol in older adults at risk of cognitive impairment.", "evidence_type": "review", "source_type": "pubmed", "year": 2026, "url": "https://pubmed.ncbi.nlm.nih.gov/999002/"},
                {"title": "REMAP Trial for Optimizing Surgical Outcomes at UPMC", "excerpt": "Adult elective-surgery outcomes trial with metformin short-course intervention arms and hospital free days at day 90.", "evidence_type": "interventional", "source_type": "clinicaltrials", "has_results": True, "trial_status": "results", "year": 2022, "url": "https://clinicaltrials.gov/study/NCT03861767"},
            ],
        ),
        (
            "rapamycin aging older adults",
            ["rapamycin", "sirolimus"],
            ["metformin for longevity and sarcopenia"],
            [
                {"title": "Influence of rapamycin on safety and healthspan metrics after one year: PEARL trial results", "excerpt": "Weekly rapamycin in older adults did not change visceral adiposity compared with placebo.", "evidence_type": "primary", "source_type": "pubmed", "year": 2025, "url": "https://pubmed.ncbi.nlm.nih.gov/40188830/"},
                {"title": "Exercise and Weekly Sirolimus (Rapamycin) in Older Adults: RAPA-EX-01 Randomised, Double-Blind, Placebo-Controlled Trial.", "excerpt": "Older adults completed a randomized placebo-controlled sirolimus trial with strength and endurance outcomes.", "evidence_type": "primary", "source_type": "pubmed", "year": 2026, "url": "https://pubmed.ncbi.nlm.nih.gov/41985884/"},
                {"title": "Efficacy and safety of sirolimus in the treatment of gastrointestinal angiodysplasias.", "excerpt": "Sirolimus improved outcomes in a disease-specific adult cohort.", "evidence_type": "primary", "source_type": "pubmed", "year": 2025, "url": "https://pubmed.ncbi.nlm.nih.gov/40656607/"},
                {"title": "Evaluation of off-label rapamycin use on oral health.", "excerpt": "Off-label rapamycin use in adults with oral-health outcomes.", "evidence_type": "observational", "source_type": "pubmed", "year": 2024, "url": "https://pubmed.ncbi.nlm.nih.gov/38839644/"},
                {"title": "Rapamycin and healthspan in human aging: a systematic review", "excerpt": "Review of rapamycin and sirolimus evidence in aging and older adults.", "evidence_type": "review", "source_type": "pubmed", "year": 2025, "url": "https://pubmed.ncbi.nlm.nih.gov/501100/"},
                {"title": "A single-center randomized placebo-controlled study to evaluate once-weekly sirolimus in older adults", "excerpt": "Trial protocol in older adults with strength and endurance outcomes.", "evidence_type": "review", "source_type": "pubmed", "year": 2024, "url": "https://pubmed.ncbi.nlm.nih.gov/39354527/"},
                {"title": "Metformin for Longevity and Sarcopenia: A Therapeutic Paradox in Aging", "excerpt": "Metformin review unrelated to rapamycin-specific outcomes.", "evidence_type": "review", "source_type": "pubmed", "year": 2026, "url": "https://pubmed.ncbi.nlm.nih.gov/41751275/"},
            ],
        ),
        (
            "senolytic dasatinib quercetin older adults",
            ["senolytic", "dasatinib", "quercetin", "d+q"],
            ["galleria mellonella pathogen infection models"],
            [
                {"title": "Dasatinib plus quercetin improves physical function in older adults", "excerpt": "Senolytic intervention in older adults with physical performance outcomes.", "evidence_type": "primary", "source_type": "pubmed", "year": 2025, "url": "https://pubmed.ncbi.nlm.nih.gov/501001/"},
                {"title": "Intermittent Dasatinib Plus Quercetin in Older Adults With Frailty: Pilot Trial", "excerpt": "Older adults completed a senolytic pilot with frailty outcomes.", "evidence_type": "primary", "source_type": "pubmed", "year": 2026, "url": "https://pubmed.ncbi.nlm.nih.gov/501010/"},
                {"title": "Senolytic therapy in idiopathic pulmonary fibrosis: a phase I feasibility study", "excerpt": "Dasatinib and quercetin were studied in a disease-specific adult cohort with pulmonary fibrosis.", "evidence_type": "observational", "source_type": "pubmed", "year": 2024, "url": "https://pubmed.ncbi.nlm.nih.gov/501002/"},
                {"title": "Dasatinib plus quercetin feasibility in mild Alzheimer disease", "excerpt": "Disease-context senolytic feasibility study in adults with Alzheimer disease.", "evidence_type": "observational", "source_type": "pubmed", "year": 2025, "url": "https://pubmed.ncbi.nlm.nih.gov/501011/"},
                {"title": "Senolytics and healthspan: a systematic review", "excerpt": "Review of senolytic interventions and healthspan endpoints in human aging.", "evidence_type": "review", "source_type": "pubmed", "year": 2025, "url": "https://pubmed.ncbi.nlm.nih.gov/501003/"},
                {"title": "Protocol for intermittent dasatinib plus quercetin in frail older adults", "excerpt": "Registered senolytic protocol in frail older adults.", "evidence_type": "protocol", "source_type": "clinicaltrials", "has_results": False, "year": 2026, "url": "https://clinicaltrials.gov/study/NCT501004"},
                {"title": "Galleria mellonella pathogen infection models", "excerpt": "Insect infection model unrelated to senolytic therapy in older adults.", "evidence_type": "review", "source_type": "openalex", "year": 2023, "url": "https://doi.org/10.1093/femsre/fuad011"},
            ],
        ),
    ],
)
def test_bundle_contract(topic, allowed_terms, banned_terms, evidence):
    drafter = RapidEvidenceDrafter(provider=BundleContractProvider())
    artifact, _ = drafter.draft(
        topic=topic,
        domain_slug="longevity",
        criteria="2022 onwards human studies relevance",
        queries=[topic],
        evidence=evidence,
        all_evidence=evidence,
    )
    _assert_bundle_contract(artifact, allowed_terms=allowed_terms, banned_terms=banned_terms)
